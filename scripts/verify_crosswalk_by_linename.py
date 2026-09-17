#!/usr/bin/env python3
"""公表インピーダンスの対応付けを **線名** で検証・修正する（#47）。

変電所名だけで照合すると同名異所に弱い（「高津線」は関西にも東京にもあり、
実測で 438 km の「線」が生まれた）。**線名は変電所名より一意性が高い**ので、
`公表の line_name` → `built の同名エッジ群` → `その両端` という第二経路で
対応付けを検証し、既存の from/to と食い違うものを検出する。

出力（`AGJ_DISCLOSURE_OUT`）: crosswalk_linename_check.csv
  span_km        線名照合で得た両端距離
  chord_km       既存の対応付けの弦距離
  verdict        agree / fixable（線名の方が短い＝既存が誤マッチ）/ no_line / ambiguous

これ自体はモデルも crosswalk も書き換えない（OBSERVED_VS_DERIVED の規約）。
"""
from __future__ import annotations
import json, math, os, re, sys, unicodedata
from collections import defaultdict
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
NORM = Path(os.environ.get("AGJ_DISCLOSURE_NORM",
                           ROOT / "data/external/system_disclosure/normalized"))
OUT = Path(os.environ.get("AGJ_DISCLOSURE_OUT", NORM))
BUILT = ROOT / "docs/data/built/all.json"
BBOX = ROOT / "docs/data/built/regions_bbox.json"
# 公表の事業者 → AGJ の region（bbox 判定に使う。bbox は供給エリアと厳密には
# 一致しないので、隣接する region も許容する）
UTIL_REGION = {"hokkaido": ["hokkaido"], "tohoku": ["tohoku", "tokyo"],
               "tokyo": ["tokyo", "tohoku", "chubu"], "chubu": ["chubu", "tokyo", "kansai"],
               "hokuriku": ["hokuriku", "chubu", "kansai"], "kansai": ["kansai", "chubu", "chugoku"],
               "chugoku": ["chugoku", "kansai", "shikoku"], "shikoku": ["shikoku", "chugoku", "kansai"],
               "kyushu": ["kyushu", "chugoku"], "okinawa": ["okinawa"]}
CIRCUIT_RX = re.compile(r"[0-9０-９]*[LＬ]$|[0-9０-９]+回線$|[0-9０-９]+号線$")
# 汎用名は線名照合に使えない（「他社線」で照合すると無関係な線を拾う）。
# 実測で hokkaido 187kV「他社線1L」が 0.38 km の別線に当たった。
GENERIC_NAMES = {"他社線", "連絡線", "引込線", "予備線", "支線", "本線", "分岐線",
                 "送電線", "地中線", "ケーブル"}


def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    return 6371*2*math.asin(math.sqrt(math.sin((la2-la1)/2)**2 +
        math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2))


def key(s: str) -> str:
    """線名の正規化: 全角半角・英字併記・回線番号を落とす。"""
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = re.sub(r"\s*\([^)]*\)", "", s)      # (Shin Okayama Kansen) など
    s = re.sub(r"\s*（[^）]*）", "", s)
    s = "".join(s.split())
    s = CIRCUIT_RX.sub("", s)
    return s


def main() -> int:
    cw_path = NORM / "crosswalk_impedance_to_model.csv"
    if not cw_path.exists():
        print(f"入力が無い: {cw_path}", file=sys.stderr)
        return 1
    cw = pd.read_csv(cw_path)
    built = json.loads(BUILT.read_text(encoding="utf-8"))
    regions = json.loads(BBOX.read_text(encoding="utf-8"))["regions"]

    def region_of(lat, lon):
        for r, b in regions.items():
            if b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]:
                yield r

    # 線名 → エッジ（複合名 "A線;B線" は両方に登録）
    grp: dict = defaultdict(list)
    for e in built["edges"]:
        n = (e.get("name") or "").strip()
        if not n or n in ("leadin", "namebind"):
            continue
        for part in n.split(";"):
            k = key(part)
            if len(k) >= 3:
                grp[k].append(e)
    print(f"線名グループ {len(grp)} / 公表 {len(cw)} 本")

    rows = []
    for _, r in cw.iterrows():
        k = key(r.line_name)
        if k in GENERIC_NAMES or len(k) < 3:
            rows.append({**r.to_dict(), "span_km": None, "chord_km": None,
                         "n_edges": 0, "verdict": "generic_name"})
            continue
        cands = [kk for kk in (k,) if kk in grp]
        if not cands:                      # 部分一致（短い方が長い方に含まれる）
            cands = [kk for kk in grp
                     if len(kk) >= 3 and (kk == k or (len(k) >= 4 and k in kk))]
        allow = UTIL_REGION.get(r.utility, [])
        es = []
        for kk in cands:
            for e in grp[kk]:
                if not allow or any(rg in allow for rg in region_of(*e["a"])):
                    es.append(e)
        chord = (hav([r.from_lat, r.from_lon], [r.to_lat, r.to_lon])
                 if r.both_resolved and pd.notna(r.from_lat) and pd.notna(r.to_lat)
                 else None)
        if not es:
            rows.append({**r.to_dict(), "span_km": None, "chord_km": chord,
                         "n_edges": 0, "verdict": "no_line"})
            continue
        pts = [p for e in es for p in (e.get("path") or [e["a"], e["b"]])]
        step = max(1, len(pts) // 80)
        sub = pts[::step]
        span = max((hav(p, q) for i, p in enumerate(sub) for q in sub[i+1:]), default=0.0)
        if chord is None:
            v = "unresolved"
        elif span < chord * 0.6:
            v = "fixable"                  # 線名の方が明らかに短い＝既存が誤マッチ
        elif span > chord * 1.8:
            v = "ambiguous"                # 線名側が広がりすぎ（複合名の束ね等）
        else:
            v = "agree"
        rows.append({**r.to_dict(), "span_km": round(span, 2),
                     "chord_km": round(chord, 2) if chord else None,
                     "n_edges": len(es), "verdict": v})

    out = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / "crosswalk_linename_check.csv"
    out.to_csv(dest, index=False, encoding="utf-8")
    print("\n=== 判定 ===")
    print(out.verdict.value_counts().to_string())
    fx = out[out.verdict == "fixable"].sort_values("chord_km", ascending=False)
    if len(fx):
        print(f"\n=== 線名照合で正せる {len(fx)} 本（既存の弦距離 → 線名の両端距離）===")
        print(fx[["utility", "voltage_kv", "line_name", "chord_km", "span_km", "n_edges"]]
              .head(15).to_string(index=False))
    print(f"\n→ {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
