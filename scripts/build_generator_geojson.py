#!/usr/bin/env python3
"""発電所マスタ（大規模層）を地図用GeoJSONにする。

generator_master.csv の大規模電源（OCCTO由来297）に座標を付けて出力する。
- 座標: plants_all.geojson と発電所名で照合（build_generation_geojson と同じ正規化）
- 定格: マスタが持つ capacity_mw（出典付き容量DBから補完済み）
- 燃料色: OCCTO の発電方式・燃種

出力: data/external/system_disclosure/viz/generators_large.geojson（observed層）

FIT層（38万件）は所在地番地のジオコーディングが要るため本スクリプトの対象外
（別課題。docs/GENERATOR_DB.md 残件参照）。ここは「系統に直結する大規模電源を
地図に載せ、OSM由来DBの欠落（柏崎刈羽等）を可視化する」ことに絞る。
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_generation_geojson import variants, load_plants  # noqa: E402

NORM = ROOT / "data" / "external" / "system_disclosure" / "normalized"
OUT = ROOT / "data" / "external" / "system_disclosure" / "viz"


def main() -> int:
    master = pd.read_csv(NORM / "generator_master.csv")
    large = master[master.scale == "large"].copy()

    idx = load_plants()   # {正規化名: [{name,lon,lat,mw}]}

    # OCCTOの発電所名はユニット名込みのことがある（吉の浦1号 / 石川GT1号）。
    # 発電所名だけに落とした形でも照合する。
    unit_rx = re.compile(
        r"([0-9０-９]+号機?|GT[0-9]*号?|ＧＴ[0-9]*号?|CC|[0-9]+軸|第[0-9]+|新[0-9]+号)\s*$")

    def base_name(n: str) -> str:
        n = unicodedata.normalize("NFKC", str(n))
        return re.sub(r"\s", "", unit_rx.sub("", n))

    feats = []
    matched = unmatched = 0
    unmatched_names = []
    for _, r in large.iterrows():
        name = str(r["name"])
        hit = None
        for v in variants(name) + variants(base_name(name)):
            if v in idx:
                hit = idx[v][0]
                break
        if hit is None:
            unmatched += 1
            unmatched_names.append(name)
            continue
        matched += 1
        cap = r.get("capacity_mw")
        cap = None if pd.isna(cap) else float(cap)
        feats.append({
            "type": "Feature",
            "properties": {
                "gen_id": r["gen_id"],
                "name": name,
                "fuel": str(r["fuel"]),
                "area": str(r["area"]),
                "n_units": int(r["n_units"]) if pd.notna(r["n_units"]) else None,
                "capacity_mw": cap,
                "capacity_source": None if pd.isna(r.get("capacity_source")) else r.get("capacity_source"),
                "source": r["source"],
                "layer": "observed",
            },
            "geometry": {"type": "Point",
                         "coordinates": [round(hit["lon"], 5), round(hit["lat"], 5)]},
        })

    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / "generators_large.geojson"
    dest.write_text(json.dumps(
        {"type": "FeatureCollection", "features": feats,
         "metadata": {"source": "OCCTO発電実績＋出典付き容量DB", "layer": "observed",
                      "note": "大規模電源のみ。座標はplants_all照合"}},
        ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8")

    n_cap = sum(1 for f in feats if f["properties"]["capacity_mw"])
    print(f"大規模電源 {len(large)} → 地図化 {matched} / 座標未解決 {unmatched}")
    print(f"  定格容量つき {n_cap}")
    print(f"  座標未解決の例: {unmatched_names[:8]}")
    print(f"→ {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
