#!/usr/bin/env python3
"""
JRP の kyushu/okinawa_plants_lite → AGJ 形式の plants.geojson を生成

AGJ には kyushu_plants.geojson / okinawa_plants.geojson が欠落しているため、
JRP のデータをベースに AGJ 形式に変換して生成する。

生成後、docs/data/plants_*.geojson も再マージする。

実行:
  python3 scripts/restore_missing_plants.py [--dry-run]
"""

import json
import sys
import datetime
from pathlib import Path
from collections import defaultdict

AGJ_ROOT  = Path(__file__).parent.parent
AGJ_DATA  = AGJ_ROOT / "data"
DOCS_DATA = AGJ_ROOT / "docs" / "data"
JRP_DATA  = Path("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/japan-re-potential/docs/grid")

DRY_RUN = "--dry-run" in sys.argv

MISSING_REGIONS = ["kyushu", "okinawa"]

FUEL_COLORS = {
    "nuclear": "#ff0000", "coal": "#444444", "gas": "#ff8800",
    "oil": "#884400", "hydro": "#0088ff", "pumped_hydro": "#0044aa",
    "wind": "#00cc88", "solar": "#ffdd00", "geothermal": "#cc4488",
    "biomass": "#668833", "waste": "#996633", "tidal": "#006688",
    "battery": "#aa00ff", "unknown": "#999999",
}

FUEL_NORM = {
    "solar": "solar", "hydro": "hydro", "nuclear": "nuclear",
    "coal": "coal", "gas": "gas", "wind": "wind", "biomass": "biomass",
    "oil": "oil", "geothermal": "geothermal", "waste": "waste",
    "tidal": "tidal", "pumped_hydro": "pumped_hydro", "battery": "battery",
    "oil;gas": "oil", "waste;solar": "waste",
}

REGION_JA = {
    "kyushu": "九州", "okinawa": "沖縄",
}


def normalize_fuel(raw: str) -> str:
    return FUEL_NORM.get((raw or "").strip().lower(), "unknown")


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    if DRY_RUN:
        print(f"  [dry-run] would write {path} ({len(data.get('features', []))} features)")
        return
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  Written: {path} ({len(data.get('features', []))} features)")


def convert_jrp_to_agj(jrp_features: list, region: str) -> list:
    """JRP plants_lite フィーチャーを AGJ 形式に変換する。"""
    result = []
    for f in jrp_features:
        p = f["properties"]
        raw_fuel = (p.get("fuel") or "").strip()
        fuel_type = normalize_fuel(raw_fuel)
        name = p.get("name") or ""
        raw_out = (p.get("output") or "").strip()

        # capacity_mw: output から数値を抽出 (例: "1000kW" -> 1.0 MW, "1.0MW" -> 1.0)
        capacity_mw = -1.0
        if raw_out:
            import re
            m = re.search(r"([\d.]+)\s*(kW|MW|GW)?", raw_out, re.IGNORECASE)
            if m:
                val = float(m.group(1))
                unit = (m.group(2) or "kW").upper()
                if unit == "KW":
                    val /= 1000
                elif unit == "GW":
                    val *= 1000
                capacity_mw = round(val, 3)

        new_props = {
            "name": name,
            "name:ja": "",
            "name:en": "",
            "operator": "",
            "fuel_type": fuel_type,
            "plant:source": raw_fuel,
            "capacity_mw": capacity_mw,
            "voltage": "",
            "_region": region,
            "_region_ja": REGION_JA.get(region, region),
            "_display_name": name,
            "_fuel_color": FUEL_COLORS.get(fuel_type, FUEL_COLORS["unknown"]),
            "osm_id": None,
            "osm_type": None,
            "_category": "unknown",
            "_enriched_by": "jrp_lite",
            "_p03_distance_km": None,
        }
        result.append({
            "type": "Feature",
            "geometry": f["geometry"],
            "properties": new_props,
        })
    return result


def rebuild_docs_plants():
    """docs/data/plants_*.geojson を全リージョンから再マージする。"""
    all_regions = [
        "hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
        "kansai", "chugoku", "shikoku", "kyushu", "okinawa",
    ]

    all_features = []
    utility_features = []
    ipp_features = []

    for region in all_regions:
        path = AGJ_DATA / f"{region}_plants.geojson"
        if not path.exists():
            print(f"  [warn] {path} not found, skipping")
            continue
        d = load_json(path)
        for f in d["features"]:
            cat = (f["properties"].get("_category") or "").lower()
            all_features.append(f)
            if cat == "ipp":
                ipp_features.append(f)
            else:
                utility_features.append(f)

    def make_fc(features):
        return {"type": "FeatureCollection", "features": features}

    print(f"\nRebuild docs/data/plants_*.geojson:")
    print(f"  all: {len(all_features)}, utility: {len(utility_features)}, ipp: {len(ipp_features)}")
    save_json(DOCS_DATA / "plants_all.geojson", make_fc(all_features))
    save_json(DOCS_DATA / "plants_utility.geojson", make_fc(utility_features))
    save_json(DOCS_DATA / "plants_ipp.geojson", make_fc(ipp_features))


def main():
    print(f"Mode: {'dry-run' if DRY_RUN else 'write'}")
    print(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    for region in MISSING_REGIONS:
        jrp_path = JRP_DATA / f"{region}_plants_lite.geojson"
        agj_path = AGJ_DATA / f"{region}_plants.geojson"

        if agj_path.exists():
            print(f"[{region}] {agj_path.name} は既に存在します。スキップします。")
            print("  強制上書きするには既存ファイルを削除してください。")
            continue

        if not jrp_path.exists():
            print(f"[{region}] JRP ソース {jrp_path} が見つかりません。スキップします。")
            continue

        print(f"[{region}] 生成中...")
        jrp_d = load_json(jrp_path)
        agj_features = convert_jrp_to_agj(jrp_d["features"], region)

        agj_out = {
            "type": "FeatureCollection",
            "_source": "converted_from_jrp_plants_lite",
            "_converted_at": datetime.datetime.now().isoformat(),
            "features": agj_features,
        }
        save_json(agj_path, agj_out)

        # 燃料種別サマリ
        from collections import Counter
        fuel_dist = Counter(f["properties"]["fuel_type"] for f in agj_features)
        print(f"  燃料種別: {dict(fuel_dist.most_common(5))}")

    # docs/data/plants_*.geojson 再マージ
    print()
    rebuild_docs_plants()


if __name__ == "__main__":
    main()
