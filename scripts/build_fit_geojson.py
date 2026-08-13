#!/usr/bin/env python3
"""座標化したFIT再エネ設備を地図用GeoJSONにする。

入力: generator_master_geo.csv（scripts/geocode_generators.py の出力）
出力: data/external/system_disclosure/viz/generators_fit.geojson（observed層）

座標は**市区町村の代表点**（番地までのジオコーディングは別途 --precise）。
発電所マップの粒度としては十分だが、点が市役所付近に集まる性質があるため
`geo_precision: city` を属性に明記する（精度を偽らない）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
NORM = ROOT / "data" / "external" / "system_disclosure" / "normalized"
OUT = ROOT / "data" / "external" / "system_disclosure" / "viz"

# FITの発電設備区分 → 燃料色キー（build_generation_geojson の GENFUEL と対応）
FUEL_MAP = {
    "太陽光": "太陽光・太陽熱", "風力": "風力", "陸上風力": "風力",
    "洋上風力": "風力", "水力": "水力", "地熱": "地熱", "バイオマス": "バイオマス",
}


def main() -> int:
    src = NORM / "generator_master_geo.csv"
    if not src.exists():
        print("先に geocode_generators.py を実行する")
        return 1
    d = pd.read_csv(src)
    d = d[d["lon"].notna() & d["lat"].notna()]

    feats = []
    for _, r in d.iterrows():
        fuel = str(r.get("fuel") or "")
        fuel_key = next((v for k, v in FUEL_MAP.items() if k in fuel), "その他")
        cap = r.get("capacity_mw")
        feats.append({
            "type": "Feature",
            "properties": {
                "gen_id": r["gen_id"],
                "fuel": fuel_key,
                "fuel_raw": fuel,
                "capacity_mw": None if pd.isna(cap) else round(float(cap), 3),
                "pref": str(r.get("area") or ""),
                "geo_precision": "city",   # 市区町村代表点。精度を偽らない
                "source": "fit_portal",
                "layer": "observed",
            },
            "geometry": {"type": "Point",
                         "coordinates": [round(float(r["lon"]), 5), round(float(r["lat"]), 5)]},
        })

    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / "generators_fit.geojson"
    dest.write_text(json.dumps(
        {"type": "FeatureCollection", "features": feats,
         "metadata": {"source": "FIT/FIP認定情報＋地理院ジオコーディング",
                      "layer": "observed", "geo_precision": "city",
                      "note": "座標は市区町村代表点。個人情報は含まない"}},
        ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    print(f"FIT設備 地図化 {len(feats)} → {dest.relative_to(ROOT)}  {dest.stat().st_size/1e6:.2f}MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
