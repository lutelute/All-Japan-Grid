#!/usr/bin/env python3
"""OCCTO ユニット別発電実績（30分値）を地図用に整える。

入力: data/external/occto/hks/hks_*.csv（scripts/fetch_hks.py で取得）
      docs/data/plants_all.geojson（AGJの発電所19,138件。座標を引くため）
出力: data/external/system_disclosure/viz/generation.geojson
      data/external/system_disclosure/viz/generation_series.json

出力は **observed 層**。AGJのUC/ディスパッチ計算結果とは混ぜない
（docs/OBSERVED_VS_DERIVED.md）。

出力率の分母について:
  公表側に定格容量は無い。AGJの発電所DBに容量があればそれを使い（basis=nameplate）、
  無ければ**その日の最大値**を分母にする（basis=day_peak）。
  後者は「その日のピークに対する比」であって設備利用率ではない。
  同じ色で塗ると誤読されるので basis を属性に残し、凡例にも出す。
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
HKS = ROOT / "data" / "external" / "occto" / "hks"
PLANTS = ROOT / "docs" / "data" / "plants_all.geojson"
OUT = ROOT / "data" / "external" / "system_disclosure" / "viz"

SUFFIX_RX = re.compile(r"(発電所|発電|電力所)$")
# 公表側は事業者名を前置することがある（電源開発新豊根発電所 / 北陸電力 富山新港火力発電所）
OPERATOR_RX = re.compile(
    r"^(電源開発|北海道電力|東北電力|東京電力|中部電力|北陸電力|関西電力|中国電力"
    r"|四国電力|九州電力|沖縄電力|ＪＦＥ|JFE|新日鐵住金|日本製鉄|東京)")
# 系列・軸の表記（柳井発電所第１号系列上位）は発電所名の一部ではない
SERIES_RX = re.compile(r"第[0-9０-９]+号系列.*$|[0-9０-９]+号系列.*$|(上位|下位)$")
PAREN_RX = re.compile(r"[（(][^）)]*[）)]")
FUEL_TAIL_RX = re.compile(r"(火力|原子力|水力|地熱|風力|太陽光)$")


def norm(s: object) -> str:
    n = unicodedata.normalize("NFKC", str(s))
    return re.sub(r"[\s　・,，\(\)（）]", "", n)


def variants(name: str) -> list[str]:
    """1つの発電所名から照合候補を作る。

    公表側とOSM側で「事業者名の前置」「括弧注記」「系列表記」「火力の有無」が
    食い違うため、順に剥がした形も候補にする。
    例: `電源開発新豊根発電所（中部）` → 新豊根発電所 / 新豊根
        `姉崎`(公表) ⇔ `姉崎火力発電所`(OSM)
    """
    raw = unicodedata.normalize("NFKC", str(name))
    raw = PAREN_RX.sub("", raw)          # 括弧注記を落とす（(東北) 等）
    n = re.sub(r"[\s　・,，]", "", raw)
    n = SERIES_RX.sub("", n)
    out = [n]
    stripped = OPERATOR_RX.sub("", n)
    if stripped != n:
        out.append(stripped)
    for v in list(out):
        base = SUFFIX_RX.sub("", v)      # 「発電所」を落とす
        out.append(base)
        out.append(FUEL_TAIL_RX.sub("", base))   # さらに「火力」等を落とす
        out.append(base + "火力")                 # 逆に補う（公表が省いている場合）
        out.append(base + "火力発電所")
    return [v for v in dict.fromkeys(out) if len(v) >= 2]


def load_plants() -> dict[str, list[dict]]:
    idx: dict[str, list[dict]] = defaultdict(list)
    if not PLANTS.exists():
        return idx
    for f in json.loads(PLANTS.read_text(encoding="utf-8"))["features"]:
        p = f["properties"]
        name = p.get("_display_name") or ""
        g = f.get("geometry") or {}
        c = g.get("coordinates")
        if not name or not c:
            continue
        xy = c[:2] if g.get("type") == "Point" else None
        if xy is None:
            continue
        mw = p.get("capacity_mw")
        if mw in ("", None) or (isinstance(mw, (int, float)) and mw <= 0):
            mw = None
        for v in variants(name):
            idx[v].append({"name": name, "lon": xy[0], "lat": xy[1], "mw": mw})
    return idx


def read_hks(path: Path) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp932"):
        try:
            return pd.read_csv(path, encoding=enc, dtype=str)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"decode failed: {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", help="対象日(YYYY/MM/DD)。省略時は最新のCSV")
    args = ap.parse_args()

    files = sorted(HKS.glob("hks_*.csv"))
    if not files:
        print("HKSのCSVが無い。先に scripts/fetch_hks.py を実行する")
        return 1
    df = pd.concat([read_hks(f) for f in files], ignore_index=True)
    if args.date:
        df = df[df["対象日"] == args.date]
    slot_cols = [c for c in df.columns if re.match(r"^\d{2}:\d{2}\[kWh\]$", str(c))]

    idx = load_plants()
    # 同じユニットが日ごとに1行ずつ来る。**ユニット単位に畳み、日付順に系列を連結**する
    # （日ごとに feature を作ると同じ座標に7個の点が重なる）。
    dates = sorted(df["対象日"].dropna().unique())
    df = df.sort_values("対象日")
    feats, series = [], {}
    matched = unmatched = 0
    for (code, unit), g in df.groupby(["発電所コード", "ユニット名"], sort=False):
        r0 = g.iloc[0]
        pname = str(r0.get("発電所名") or "")
        hit = None
        for v in variants(pname):
            if v in idx:
                hit = idx[v][0]
                break
        if hit is None:
            unmatched += 1
            continue
        matched += 1

        vals: list[float | None] = []
        by_date = {str(r["対象日"]): r for _, r in g.iterrows()}
        for d in dates:                      # 欠測日は None で埋め、時間軸をずらさない
            r = by_date.get(str(d))
            if r is None:
                vals += [None] * len(slot_cols)
                continue
            for c in slot_cols:
                x = pd.to_numeric(str(r[c]).replace(",", ""), errors="coerce")
                # 30分あたりの kWh → MW は ×2/1000
                vals.append(None if pd.isna(x) else round(float(x) * 2 / 1000, 2))

        nums = [x for x in vals if x is not None]
        peak_mw = max(nums) if nums else 0.0
        nameplate = hit["mw"]
        uid = f"{code}:{unit}"
        series[uid] = vals
        feats.append({
            "type": "Feature",
            "properties": {
                "uid": uid,
                "plant": pname, "unit": str(unit),
                "fuel": str(r0.get("発電方式・燃種") or ""),
                "area": str(r0.get("エリア") or ""),
                "code": str(code),
                "peak_mw": round(peak_mw, 2),
                "nameplate_mw": nameplate,
                # 出力率の分母。nameplate が無い場合は期間ピーク＝比の意味が変わる
                "basis": "nameplate" if nameplate else "period_peak",
                "matched_plant": hit["name"],
                "layer": "observed",
            },
            "geometry": {"type": "Point",
                         "coordinates": [round(hit["lon"], 5), round(hit["lat"], 5)]},
        })

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "generation.geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "features": feats,
         "metadata": {"source": "OCCTO ユニット別発電実績公開システム（速報値）",
                      "layer": "observed",
                      "note": "生CSVは再配布しない。出典明記で利用"}},
        ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    (OUT / "generation_series.json").write_text(json.dumps(
        {"step_min": 30, "n_steps": len(slot_cols) * len(dates),
         "dates": [str(d) for d in dates], "slots": slot_cols,
         "t0": f"{dates[0]} 00:30" if dates else None, "series": series},
        ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8")

    n_np = sum(1 for f in feats if f["properties"]["nameplate_mw"])
    print(f"ユニット {len(df)} → 地図化 {matched} / 座標未解決 {unmatched}")
    print(f"  うち定格容量あり {n_np}（残りは当日ピーク基準）")
    print(f"  30分値 {len(slot_cols)}断面 × {len(dates)}日 = {len(slot_cols)*len(dates)} 断面")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
