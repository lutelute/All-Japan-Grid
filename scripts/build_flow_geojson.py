#!/usr/bin/env python3
"""線路観測（実測潮流＋運用容量＋インピーダンス）を地図用GeoJSONにする。

★照合は **線路名** を第一経路にする。
  OSM の送電線には正式名が入っている（四国は1,532本すべてに name があり、
  `四国中央中幹線` `松山幹線` が事業者公表名と完全一致する）。
  変電所名の突合より確実で、しかも **実線形が得られる**。
  第三者の可視化が端点直線で描いている所を、AGJは実際の線形で描ける。

  第2経路として端点（変電所）座標を結ぶ直線を使う。
  `geometry_kind` に "routed"（実線形）/ "straight"（端点直線）を必ず入れて、
  どちらで描かれた線かを地図側でも区別できるようにする。

入力: data/external/system_disclosure/normalized/line_observations.csv
      data/{region}_lines.geojson（OSM実線形）
      docs/data/substations.geojson ほか（端点フォールバック）
出力: data/external/system_disclosure/viz/flow_lines.geojson

★出力先は **gitignore 下**。docs/ に置くと GitHub Pages で公開され、
  事業者公表CSV（社によっては転載禁止）の再配布になってしまうため。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_line_observations import read_flow, scope_of  # noqa: E402
from scripts.match_impedance_to_model import load_model, resolve  # noqa: E402

NORM = ROOT / "data" / "external" / "system_disclosure" / "normalized"
OUT = ROOT / "data" / "external" / "system_disclosure" / "viz"

CIRCUIT_RX = re.compile(r"[0-9０-９]+\s*[LＬ]\s*$")
PAREN_RX = re.compile(r"[（(][^）)]*[）)]")


def norm_line(s: str) -> str:
    """線路名を照合キーにする。回線サフィックス(1L/2L)と括弧注記を落とす。"""
    n = unicodedata.normalize("NFKC", str(s))
    n = PAREN_RX.sub("", n)
    n = re.sub(r"[\s　・,，]", "", n)
    n = CIRCUIT_RX.sub("", n)
    return n.strip()


SUFFIX_RX = re.compile(r"(変電所|開閉所|発電所|変換所|変|開)$")


def clean(v: object):
    """pandas の NaN を None に落とす。

    NaN を残すと json.dumps が JSON として不正な `NaN` を書き、
    ブラウザ側の JSON.parse が丸ごと失敗する（データが1件も出ない）。
    """
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    if isinstance(v, str) and v.strip().lower() in ("nan", ""):
        return None
    return v


def stem_of(name: object) -> str:
    """`阿波変電所` → `阿波` / `西島根(変)` → `西島根`。端点照合の語幹。"""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    n = unicodedata.normalize("NFKC", str(name))
    n = PAREN_RX.sub("", n)
    n = re.sub(r"[\s　・,，]", "", n)
    return SUFFIX_RX.sub("", n).strip()


def load_osm_lines(region: str) -> dict[str, list[dict]]:
    """OSM送電線を線路名で索引する。同名の way は1本の線路の分割とみなす。"""
    path = ROOT / "data" / f"{region}_lines.geojson"
    index: dict[str, list[dict]] = defaultdict(list)
    if not path.exists():
        return index
    for f in json.loads(path.read_text(encoding="utf-8"))["features"]:
        p = f.get("properties") or {}
        raw = p.get("name") or ""
        if not raw:
            continue
        geom = f.get("geometry") or {}
        if geom.get("type") != "LineString":
            continue
        # `西通線;上天神線` のような併記は両方の候補にする
        for part in str(raw).split(";"):
            key = norm_line(part)
            if len(key) >= 3:
                index[key].append({"coords": geom["coordinates"], "props": p})
    return index


def line_id(utility: str, scope: str, no: object) -> str:
    return f"{utility}:{scope}:{no}"


def build_series(df: pd.DataFrame, wanted: set[str], n_steps: int) -> dict:
    """必要な線路だけ時系列を切り出す。

    GeoJSON に埋め込むと1本あたり8,760値で数MBになるので**別ファイルに分ける**。
    地図は幾何を先に描き、系列は後から読めばよい。
    """
    series: dict[str, list] = {}
    t0 = None
    for path_str, sub in df.groupby("source_flow"):
        path = ROOT / path_str
        if not path.exists():
            continue
        try:
            meta, ts = read_flow(path)
        except Exception:  # noqa: BLE001
            continue
        utility = path.parts[len(ROOT.parts) + 3]
        scope = scope_of(path.name)
        if t0 is None and len(ts):
            t0 = str(ts.iloc[0, 0])
        col_of = {str(m.equipment_no): int(m.col) for _, m in meta.iterrows()}
        for _, r in sub.iterrows():
            lid = line_id(utility, scope, r.equipment_no)
            if lid not in wanted or lid in series:
                continue
            c = col_of.get(str(r.equipment_no))
            if c is None:
                continue
            v = pd.to_numeric(
                ts.iloc[:n_steps, c].astype(str).str.replace(",", ""), errors="coerce"
            )
            series[lid] = [None if pd.isna(x) else round(float(x), 1) for x in v]
    return {"t0": t0, "step_min": 60, "n_steps": n_steps, "series": series}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-obs", type=int, default=1)
    ap.add_argument("--steps", type=int, default=168,
                    help="時系列に出す断面数（既定168=1週間の1時間値）")
    ap.add_argument("--fy", default="2024",
                    help="対象年度。社ごとに公表年度が違うため揃えないと"
                         "別の年の値を同じ時刻軸に重ねることになる")
    args = ap.parse_args()

    df = pd.read_csv(NORM / "line_observations.csv")
    df = df[df.n_obs.fillna(0) >= args.min_obs]

    # 年度を揃える。東京は2024年度・四国は2025年度…と公表年度がまちまちで、
    # 揃えずに1本のスライダーで動かすと「異なる年の断面」を同時刻として
    # 並べてしまう。年度で絞り、落ちた社は明示する。
    if args.fy and "year" in df.columns:
        before = set(df.utility)
        df = df[df.year.astype(str) == str(args.fy)]
        dropped = before - set(df.utility)
        if dropped:
            print(f"年度{args.fy}に無いため除外: {', '.join(sorted(dropped))}")

    features = []
    stat = defaultdict(int)
    for utility, sub in df.groupby("utility"):
        osm = load_osm_lines(utility)
        node_index, _ = load_model(utility)
        for _, r in sub.iterrows():
            key = norm_line(r["name"])
            geometry = None
            kind = None

            hits = osm.get(key)
            if not hits:
                # 第2経路: 端点ペア。OSM側に `阿波変電所~讃岐変電所線` のような
                # 端点由来の名前が入っているため、両端の語幹を含む線路を探す。
                # 公表側が `阿波幹線` と呼ぶ線が OSM では端点名になっている事例が多い。
                a = stem_of(r.get("from_node"))
                b = stem_of(r.get("to_node"))
                if len(a) >= 2 and len(b) >= 2:
                    cand = [
                        h for name, hl in osm.items()
                        if a in name and b in name
                        for h in hl
                    ]
                    if cand:
                        hits = cand
                        stat["by_endpoints"] += 1

            oriented = False
            if hits:
                kind = "routed"
                stat["routed"] += 1
                if len(hits) == 1:
                    coords = list(hits[0]["coords"])
                    # 線形の描画方向を「潮流の正方向(from→to)」に揃える。
                    # こうしておくと地図側の流れるアニメーションが物理的に正しい向きになる。
                    _, na = resolve(str(r.get("from_node") or ""), node_index)
                    if na and len(coords) >= 2:
                        d_head = (coords[0][0]-na["lon"])**2 + (coords[0][1]-na["lat"])**2
                        d_tail = (coords[-1][0]-na["lon"])**2 + (coords[-1][1]-na["lat"])**2
                        if d_tail < d_head:      # 終点の方が from に近い = 逆向き
                            coords.reverse()
                        oriented = True
                        stat["oriented"] += 1
                    geometry = {"type": "LineString", "coordinates": coords}
                else:
                    # 複数way に分割された線路。セグメントの並び順までは決められないので
                    # 向きは保証しない（oriented=False のまま）。
                    geometry = {"type": "MultiLineString",
                                "coordinates": [h["coords"] for h in hits]}
            else:
                frm, to = str(r.get("from_node") or ""), str(r.get("to_node") or "")
                if frm and to:
                    _, na = resolve(frm, node_index)
                    _, nb = resolve(to, node_index)
                    if na and nb:
                        kind = "straight"
                        stat["straight"] += 1
                        oriented = True   # from→to の順で作るので向きは定義どおり
                        geometry = {"type": "LineString",
                                    "coordinates": [[na["lon"], na["lat"]],
                                                    [nb["lon"], nb["lat"]]]}
            if geometry is None:
                stat["unplaced"] += 1
                continue

            props = {
                "line_id": line_id(utility, r.get("scope", "?"), r.equipment_no),
                "utility": utility, "line": r["name"],
                "kv": None if pd.isna(r.voltage_kv) else float(r.voltage_kv),
                "from": clean(r.get("from_node")), "to": clean(r.get("to_node")),
                "geometry_kind": kind, "layer": "observed",
                "oriented": oriented,   # 線形の向き＝潮流正方向 に揃えたか
                "n_obs": int(r.n_obs),
                "osm_segments": len(hits) if hits else 0,
            }
            for k in ("flow_mean_mw", "flow_p95_abs_mw", "flow_max_abs_mw", "reverse_share",
                      "operational_mw", "facility_mw", "constraint", "circuits",
                      "load_factor_p95", "R_pct", "X_pct", "B_half_pct"):
                props[k] = clean(r.get(k))
            features.append({"type": "Feature", "properties": props, "geometry": geometry})

    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / "flow_lines.geojson"
    # allow_nan=False: NaN が混じったら書き出し時点で落とす。
    # Python の json は既定で NaN を書けてしまうが、それは JSON として不正で
    # ブラウザの JSON.parse が丸ごと失敗する（データが1件も出ないのに無言で通る）。
    dest.write_text(json.dumps({
        "type": "FeatureCollection", "features": features,
        "metadata": {
            "layer": "observed",
            "source": "一般送配電事業者 系統情報の公表（様式5 / 空容量 / 潮流実績）+ OSM実線形",
            "note": "生値の再配布不可。私的検証用。負荷率は公表の運用容量ベース",
        },
    }, ensure_ascii=False, allow_nan=False), encoding="utf-8")

    # ビューア本体はコード（commit対象）なので scripts/viz/ が正本。
    # データは gitignore 下なので、実行のたびにデータの隣へ写して同一オリジンで開けるようにする。
    src_html = ROOT / "scripts" / "viz" / "observed_flow.html"
    if src_html.exists():
        (OUT / "index.html").write_text(src_html.read_text(encoding="utf-8"), encoding="utf-8")

    # 地図に載った線だけ時系列を切り出す（載らない線の系列は要らない）
    wanted = {f["properties"]["line_id"] for f in features}
    ser = build_series(df, wanted, args.steps)
    sdest = OUT / "flow_series.json"
    sdest.write_text(json.dumps(ser, ensure_ascii=False, allow_nan=False), encoding="utf-8")

    n_cap = sum(1 for f in features if f["properties"].get("operational_mw"))
    n_imp = sum(1 for f in features if f["properties"].get("X_pct"))
    print(f"時系列 {len(ser['series'])} 本 × {args.steps} 断面 "
          f"(t0={ser['t0']}) → {sdest.relative_to(ROOT)} {sdest.stat().st_size:,}B")
    print(f"features {len(features)}")
    print(f"  実線形 routed   {stat['routed']}")
    print(f"  端点直線 straight {stat['straight']}")
    print(f"  配置できず       {stat['unplaced']}")
    print(f"  運用容量つき {n_cap} / インピーダンスつき {n_imp}")
    print(f"→ {dest.relative_to(ROOT)}  {dest.stat().st_size:,}B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
