#!/usr/bin/env python3
"""
Audit substation/plant classification overlap in OSM-derived GeoJSON data.

Detects 4 categories of issues:
  A. Substations named as plants (name contains 発電所)
  B. substation=generation (step-up substations at generation sites)
  C. Tag value errors (substation field contains facility name instead of valid type)
  D. Plants named as substations (name contains 変電所)

Additionally finds colocated pairs (substation within 200m of a plant) with
mismatched names.

Usage:
  python scripts/audit_substation_plant_overlap.py           # audit only
  python scripts/audit_substation_plant_overlap.py --fix     # audit + fix Category C
  python scripts/audit_substation_plant_overlap.py --region tokyo  # single region

Output:
  data/audit/substation_plant_overlap.json   — structured audit results
  stdout                                     — human-readable summary
"""

import argparse
import json
import math
import os
import sys

REGIONS = [
    "hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
    "kansai", "chugoku", "shikoku", "kyushu", "okinawa",
]

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
AUDIT_DIR = os.path.join(DATA_DIR, "audit")

VALID_SUBSTATION_TYPES = {
    "distribution", "transmission", "traction", "industrial", "substation",
    "transition", "yes", "generation", "minor_distribution", "converter",
    "compensation", "switching", "rail",
}


def haversine_km(lat1, lon1, lat2, lon2):
    # Canonical impl in src.utils.geo_utils (same (lat, lon) order).
    from src.utils.geo_utils import haversine_distance
    return haversine_distance(lat1, lon1, lat2, lon2)


def get_centroid(feature):
    geom = feature["geometry"]
    if geom is None:
        return None, None
    gtype = geom["type"]
    if gtype == "Point":
        return geom["coordinates"][1], geom["coordinates"][0]
    elif gtype == "Polygon":
        coords = geom["coordinates"][0]
    elif gtype == "MultiPolygon":
        coords = geom["coordinates"][0][0]
    else:
        return None, None
    lat = sum(c[1] for c in coords) / len(coords)
    lon = sum(c[0] for c in coords) / len(coords)
    return lat, lon


def load_features(region, layer):
    path = os.path.join(DATA_DIR, f"{region}_{layer}.geojson")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("features", [])


def audit_region(region):
    subs = load_features(region, "substations")
    plants = load_features(region, "plants")

    cat_a = []  # substations named as plants
    cat_b = []  # substation=generation
    cat_c = []  # tag value errors
    cat_d = []  # plants named as substations

    # --- Substations ---
    for feat in subs:
        props = feat["properties"]
        name = props.get("name") or ""
        sub_type = props.get("substation") or ""
        voltage = props.get("voltage") or ""

        # Category A: substation with 発電所/発電 in name
        if "発電所" in name or ("発電" in name and "変電" not in name):
            lat, lon = get_centroid(feat)
            cat_a.append({
                "region": region,
                "name": name,
                "substation_type": sub_type,
                "voltage": voltage,
                "lat": lat,
                "lon": lon,
            })

        # Category B: substation=generation
        if sub_type == "generation":
            lat, lon = get_centroid(feat)
            cat_b.append({
                "region": region,
                "name": name,
                "voltage": voltage,
                "lat": lat,
                "lon": lon,
            })

        # Category C: tag value is not a recognized type
        if sub_type and sub_type not in VALID_SUBSTATION_TYPES:
            lat, lon = get_centroid(feat)
            cat_c.append({
                "region": region,
                "name": name,
                "bad_substation_value": sub_type,
                "voltage": voltage,
                "lat": lat,
                "lon": lon,
            })

    # --- Plants ---
    for feat in plants:
        props = feat["properties"]
        name = props.get("name") or props.get("_display_name") or ""
        fuel = props.get("fuel_type") or ""

        if "変電所" in name:
            lat, lon = get_centroid(feat)
            cat_d.append({
                "region": region,
                "name": name,
                "fuel_type": fuel,
                "lat": lat,
                "lon": lon,
            })

    # --- Colocated pairs (200m) with name mismatch ---
    colocated_mismatches = []
    sub_coords = []
    for feat in subs:
        lat, lon = get_centroid(feat)
        if lat is not None:
            sub_coords.append((lat, lon, feat["properties"].get("name") or ""))

    plant_coords = []
    for feat in plants:
        lat, lon = get_centroid(feat)
        if lat is not None:
            props = feat["properties"]
            plant_coords.append((
                lat, lon,
                props.get("name") or props.get("_display_name") or "",
                props.get("fuel_type") or "",
            ))

    for slat, slon, sname in sub_coords:
        best_dist = float("inf")
        best_plant = None
        for plat, plon, pname, pfuel in plant_coords:
            if abs(slat - plat) > 0.005:
                continue
            d = haversine_km(slat, slon, plat, plon)
            if d < best_dist:
                best_dist = d
                best_plant = (pname, pfuel, d)
        if best_plant and best_dist < 0.2:
            pname, pfuel, dist = best_plant
            # Check name mismatch
            sn = sname.replace("変電所", "").replace("東京電力 ", "").replace("東京電力パワーグリッド ", "").strip()
            pn = pname.replace("発電所", "").replace("太陽光", "").strip()
            if sn and pn and sn not in pn and pn not in sn:
                colocated_mismatches.append({
                    "region": region,
                    "sub_name": sname,
                    "plant_name": pname,
                    "plant_fuel": pfuel,
                    "distance_m": round(dist * 1000, 1),
                })

    return cat_a, cat_b, cat_c, cat_d, colocated_mismatches


def fix_category_c(regions_to_fix, cat_c_all):
    """Fix Category C: replace invalid substation tag values with None."""
    # Group by region
    bad_values_by_region = {}
    for item in cat_c_all:
        r = item["region"]
        bad_values_by_region.setdefault(r, set()).add(item["bad_substation_value"])

    fixed_total = 0
    for region in regions_to_fix:
        if region not in bad_values_by_region:
            continue
        bad_vals = bad_values_by_region[region]
        path = os.path.join(DATA_DIR, f"{region}_substations.geojson")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        count = 0
        for feat in data["features"]:
            sub_val = feat["properties"].get("substation") or ""
            if sub_val in bad_vals:
                feat["properties"]["substation"] = None
                count += 1

        if count > 0:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            print(f"  Fixed {count} tag errors in {region}_substations.geojson")
            fixed_total += count

    return fixed_total


def main():
    parser = argparse.ArgumentParser(description="Audit substation/plant classification overlap")
    parser.add_argument("--fix", action="store_true", help="Apply fixes for Category C tag errors")
    parser.add_argument("--region", type=str, help="Audit a single region")
    args = parser.parse_args()

    regions = [args.region] if args.region else REGIONS

    all_a, all_b, all_c, all_d, all_coloc = [], [], [], [], []

    for region in regions:
        a, b, c, d, coloc = audit_region(region)
        all_a.extend(a)
        all_b.extend(b)
        all_c.extend(c)
        all_d.extend(d)
        all_coloc.extend(coloc)

    # Print summary
    print("=" * 70)
    print("Substation / Plant Classification Audit")
    print("=" * 70)

    print(f"\nCategory A — Substations named as plants:        {len(all_a)}")
    for item in all_a:
        print(f"  [{item['region']}] {item['name']}  substation={item['substation_type']}  voltage={item['voltage']}")

    print(f"\nCategory B — substation=generation:               {len(all_b)}")
    for item in all_b:
        print(f"  [{item['region']}] {item['name']}  voltage={item['voltage']}")

    print(f"\nCategory C — Tag value errors:                    {len(all_c)}")
    for item in all_c:
        print(f"  [{item['region']}] {item['name']}  substation={item['bad_substation_value']}")

    print(f"\nCategory D — Plants named as substations:         {len(all_d)}")
    for item in all_d:
        print(f"  [{item['region']}] {item['name']}  fuel={item['fuel_type']}")

    print(f"\nColocated pairs (<200m) with name mismatch:       {len(all_coloc)}")
    for item in sorted(all_coloc, key=lambda x: x["distance_m"])[:20]:
        print(f"  [{item['region']}] {item['sub_name']} <-> {item['plant_name']}  "
              f"dist={item['distance_m']}m  fuel={item['plant_fuel']}")
    if len(all_coloc) > 20:
        print(f"  ... and {len(all_coloc) - 20} more (see JSON output)")

    # Summary table
    print(f"\n{'=' * 70}")
    print(f"{'Category':<50} {'Count':>6}  {'Severity':<8}")
    print(f"{'-' * 70}")
    print(f"{'A. Substations named as plants':<50} {len(all_a):>6}  {'Medium':<8}")
    print(f"{'B. substation=generation':<50} {len(all_b):>6}  {'Low':<8}")
    print(f"{'C. Tag value errors':<50} {len(all_c):>6}  {'HIGH':<8}")
    print(f"{'D. Plants named as substations':<50} {len(all_d):>6}  {'Low':<8}")
    print(f"{'Colocated name mismatches (<200m)':<50} {len(all_coloc):>6}  {'Info':<8}")
    print(f"{'=' * 70}")

    # Save JSON
    os.makedirs(AUDIT_DIR, exist_ok=True)
    output_path = os.path.join(AUDIT_DIR, "substation_plant_overlap.json")
    audit_result = {
        "category_a_substations_named_as_plants": all_a,
        "category_b_substation_generation": all_b,
        "category_c_tag_value_errors": all_c,
        "category_d_plants_named_as_substations": all_d,
        "colocated_name_mismatches": all_coloc,
        "summary": {
            "category_a": len(all_a),
            "category_b": len(all_b),
            "category_c": len(all_c),
            "category_d": len(all_d),
            "colocated_mismatches": len(all_coloc),
        },
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(audit_result, f, ensure_ascii=False, indent=2)
    print(f"\nAudit results saved to {output_path}")

    # Apply fixes if requested
    if args.fix:
        if all_c:
            print(f"\nApplying Category C fixes ({len(all_c)} tag errors)...")
            fixed = fix_category_c(regions, all_c)
            print(f"Fixed {fixed} total entries.")
        else:
            print("\nNo Category C errors to fix.")

    return 0 if not all_c else 1


if __name__ == "__main__":
    sys.exit(main())
