#!/usr/bin/env python3
"""Enrich unnamed transmission lines with endpoint-based names.

Loads enriched substation GeoJSON, matches line endpoints to nearest
substations, and constructs names as '{from_sub}~{to_sub}線'.

Fallback naming:
  - If operator and voltage are available: '{operator} {voltage_kv}kV線'
  - Otherwise: '{region_ja}送電線_{seq}'

Also infers operator from nearest substation when the line's operator
field is empty, or falls back to the regional utility from
config/regions.yaml.

Usage:
    python scripts/enrich_lines_endpoints.py                  # all regions
    python scripts/enrich_lines_endpoints.py --region okinawa # single region
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.utils.geo_utils import find_nearest_point

import yaml

DATA_DIR = os.path.join(ROOT, "data")
CONFIG_PATH = os.path.join(ROOT, "config", "regions.yaml")

REGIONS = [
    "hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
    "kansai", "chugoku", "shikoku", "kyushu", "okinawa",
]

from src.regions import REGION_JA  # config/regions.yaml

# Operator name normalization (variants -> canonical)
OPERATOR_NORMALIZE = {
    "東京電力": "東京電力パワーグリッド",
    "東京電力PG": "東京電力パワーグリッド",
    "関西電力": "関西電力送配電",
    "中部電力": "中部電力パワーグリッド",
    "九州電力": "九州電力送配電",
    "東北電力": "東北電力ネットワーク",
    "北海道電力": "北海道電力ネットワーク",
    "中国電力": "中国電力ネットワーク",
    "四国電力": "四国電力送配電",
    "北陸電力": "北陸電力送配電",
    "沖縄電力": "沖縄電力",
}

# Maximum distance (km) for matching line endpoints to substations
_MAX_ENDPOINT_DISTANCE_KM = 50.0


def assign_line_name(props, coords, candidates, name_to_operator,
                     regional_utility, region_ja, fallback_seq):
    """Compute the endpoint-based name for one unnamed line.

    Pure naming algorithm shared by the GeoJSON enricher
    (:func:`enrich_region`) and the DB-native enricher
    (:func:`src.db.enrich.enrich_lines_endpoints`), so both produce
    identical names. Returns
    ``(name, operator_or_None, name_source, new_fallback_seq)`` where
    ``operator_or_None`` is the inferred operator to set (or ``None`` to
    leave the line's operator unchanged).
    """
    # GeoJSON coordinates are [lon, lat]
    start_lon, start_lat = float(coords[0][0]), float(coords[0][1])
    end_lon, end_lat = float(coords[-1][0]), float(coords[-1][1])

    from_name = to_name = ""
    from_operator = to_operator = ""
    if candidates:
        from_id, _ = find_nearest_point(
            start_lat, start_lon, candidates, _MAX_ENDPOINT_DISTANCE_KM)
        to_id, _ = find_nearest_point(
            end_lat, end_lon, candidates, _MAX_ENDPOINT_DISTANCE_KM)
        if from_id:
            from_name = from_id
            from_operator = name_to_operator.get(from_id, "")
        if to_id:
            to_name = to_id
            to_operator = name_to_operator.get(to_id, "")

    # Infer operator if the line has none.
    set_operator = None
    line_operator = (props.get("operator") or "").strip()
    if line_operator:
        line_operator = normalize_operator(line_operator)
    else:
        line_operator = from_operator or to_operator or regional_utility
        if line_operator:
            set_operator = line_operator

    if from_name and to_name and from_name != to_name:
        return f"{from_name}~{to_name}線", set_operator, "endpoints", fallback_seq
    voltage_kv = parse_voltage_kv(props.get("voltage"))
    if line_operator and voltage_kv > 0:
        return (f"{line_operator} {voltage_kv}kV線", set_operator,
                "operator_voltage", fallback_seq)
    fallback_seq += 1
    return (f"{region_ja}送電線_{fallback_seq}", set_operator,
            "regional_fallback", fallback_seq)


def _load_regional_utility(region):
    """Load the regional utility name from config/regions.yaml."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        return cfg.get("regions", {}).get(region, {}).get("utility", "")
    except Exception:
        return ""


def normalize_operator(operator_raw):
    """Normalize operator name to canonical form."""
    if not operator_raw:
        return ""
    op = str(operator_raw).strip()
    if op in OPERATOR_NORMALIZE:
        return OPERATOR_NORMALIZE[op]
    for prefix, canonical in OPERATOR_NORMALIZE.items():
        if op.startswith(prefix):
            return canonical
    return op


def get_centroid(feature):
    """Extract (lat, lon) from a GeoJSON feature."""
    geom = feature["geometry"]
    coords = geom["coordinates"]
    if geom["type"] == "Point":
        if len(coords) < 2:
            return None, None
        return coords[1], coords[0]
    elif geom["type"] == "Polygon":
        ring = coords[0] if coords else []
        if not ring:
            return None, None
        lon = sum(c[0] for c in ring) / len(ring)
        lat = sum(c[1] for c in ring) / len(ring)
        return lat, lon
    elif geom["type"] == "MultiPolygon":
        ring = coords[0][0] if coords and coords[0] else []
        if not ring:
            return None, None
        lon = sum(c[0] for c in ring) / len(ring)
        lat = sum(c[1] for c in ring) / len(ring)
        return lat, lon
    return None, None


def parse_voltage_kv(voltage_raw):
    """Parse OSM voltage string to kV float (0.0 if invalid).

    Canonical max-voltage parser in src.utils.voltage.
    """
    from src.utils.voltage import parse_voltage_kv as _pv
    v = _pv(voltage_raw)
    return round(v, 1) if v is not None else 0.0


def load_substation_candidates(region):
    """Load enriched substation GeoJSON and build candidate list.

    Returns list of (name, lat, lon) tuples for endpoint matching.
    Also returns a dict mapping name -> operator for operator inference.
    """
    path = os.path.join(DATA_DIR, f"{region}_substations.geojson")
    if not os.path.exists(path):
        return [], {}

    with open(path, "r", encoding="utf-8") as f:
        fc = json.load(f)

    candidates = []
    name_to_operator = {}

    for feat in fc.get("features", []):
        lat, lon = get_centroid(feat)
        if lat is None:
            continue

        props = feat["properties"]
        name = (props.get("name") or props.get("name:ja") or "").strip()
        if not name:
            name = (props.get("_display_name") or "").strip()
        if not name:
            continue

        candidates.append((name, lat, lon))

        operator = (props.get("operator") or "").strip()
        if operator:
            name_to_operator[name] = normalize_operator(operator)

    return candidates, name_to_operator


def enrich_region(region):
    """Enrich unnamed lines in a region with endpoint-based names.

    Returns (total, enriched, still_unnamed).
    """
    lines_path = os.path.join(DATA_DIR, f"{region}_lines.geojson")
    if not os.path.exists(lines_path):
        return 0, 0, 0

    # Load substation candidates
    candidates, name_to_operator = load_substation_candidates(region)

    # Load regional utility as ultimate operator fallback
    regional_utility = normalize_operator(_load_regional_utility(region))
    region_ja = REGION_JA.get(region, region)

    with open(lines_path, "r", encoding="utf-8") as f:
        fc = json.load(f)

    features = fc.get("features", [])
    total = len(features)
    enriched = 0
    fallback_seq = 0

    for feat in features:
        props = feat["properties"]
        name = (props.get("name") or "").strip()
        if name:
            continue

        geom = feat.get("geometry", {})
        if geom.get("type") != "LineString":
            continue
        coords = geom.get("coordinates", [])
        if len(coords) < 2:
            continue

        constructed_name, set_operator, name_source, fallback_seq = \
            assign_line_name(props, coords, candidates, name_to_operator,
                             regional_utility, region_ja, fallback_seq)
        if set_operator:
            props["operator"] = set_operator
        props["name"] = constructed_name
        props["_enriched_by"] = "endpoint_matching"
        props["_name_source"] = name_source
        enriched += 1

    # Write back
    with open(lines_path, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False, separators=(",", ":"))

    still_unnamed = sum(
        1 for f in features
        if not (f["properties"].get("name") or "").strip()
    )
    return total, enriched, still_unnamed


def main():
    parser = argparse.ArgumentParser(
        description="Enrich unnamed lines with endpoint-based names"
    )
    parser.add_argument(
        "--region", type=str, default=None,
        help="Single region to process (default: all)",
    )
    args = parser.parse_args()

    regions = [args.region] if args.region else REGIONS

    total_enriched = 0
    for region in regions:
        if region not in REGIONS:
            print(f"  Unknown region: {region}")
            continue
        print(f"  Processing {region}...")
        total, enriched, still_unnamed = enrich_region(region)
        total_enriched += enriched
        print(f"    {total} total, {enriched} enriched, {still_unnamed} still unnamed")

    print(f"\n  TOTAL enriched: {total_enriched}")


if __name__ == "__main__":
    import os, sys
    if os.environ.get("AGJ_ALLOW_BASE_WRITE") != "1":
        sys.exit(
            "[封鎖:全面改修Phase1] data/*.geojson を in-place 書換する破壊的経路です。"
            " 正はDB(grid.db)に一本化済み → enrich は DB-native `ajgrid db enrich`(src/db/enrich.py)。"
            " files=DB-export は tests/test_db_source_unified.py が保証(drift検知)。"
            " 直接書く場合のみ AGJ_ALLOW_BASE_WRITE=1 を設定。")
    main()
