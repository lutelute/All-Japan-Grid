#!/usr/bin/env python3
"""Run DB-native enrichers against the unified grid DB (Step 3b).

Offline only (endpoint line naming). The result lands in the C layer and
is regenerated into GeoJSON by ``scripts/db/export.py``.

Usage:
    python scripts/db/enrich.py --lines                 # all regions
    python scripts/db/enrich.py --lines --regions okinawa
"""

import argparse
import os
import sys

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ),
)

from src.db.enrich import (  # noqa: E402
    apply_audit_fixes,
    enrich_geocode,
    enrich_lines_endpoints,
    enrich_overpass,
    enrich_p03,
)
from src.db.grid_db import GridDatabase  # noqa: E402
from src.server.geojson_loader import REGIONS  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", default="data/grid.db")
    parser.add_argument("--regions", nargs="+", default=["all"])
    parser.add_argument(
        "--lines", action="store_true",
        help="run endpoint line naming (the offline enricher)")
    parser.add_argument(
        "--audit", action="store_true",
        help="clear Category-C substation tag errors (audit --fix -> DB)")
    parser.add_argument(
        "--geocode", action="store_true",
        help="reverse-geocode unnamed subs/plants (live Nominatim -> DB; "
             "rate-limited, run on the server)")
    parser.add_argument(
        "--overpass", action="store_true",
        help="fill name/operator/fuel from OSM tags (live Overpass -> DB; "
             "run on the server)")
    parser.add_argument(
        "--p03", metavar="GML",
        help="match plants to the P03 国土数値情報 GML at this path -> DB "
             "(authoritative generator data)")
    args = parser.parse_args()

    if not (args.lines or args.audit or args.geocode or args.overpass or args.p03):
        sys.exit("nothing to do: pass --lines / --audit / --geocode / "
                 "--overpass / --p03 GML")
    regions = REGIONS if args.regions == ["all"] else args.regions
    unknown = [r for r in regions if r not in REGIONS]
    if unknown:
        sys.exit(f"unknown region(s): {', '.join(unknown)}")

    db = GridDatabase(args.db)
    if args.lines:
        total = 0
        for region in regions:
            stats = enrich_lines_endpoints(db, region)
            total += stats["enriched"]
            print(f"[lines] {region}: {stats['enriched']}/{stats['total']} named")
        print(f"TOTAL {total} lines named")
    if args.audit:
        stats = apply_audit_fixes(db, regions)
        print(f"[audit] {stats['fixed']} Category-C tag errors cleared")
    if args.geocode:
        for region in regions:
            s = enrich_geocode(db, region, "substations", "変電所")
            p = enrich_geocode(db, region, "plants", "発電所")
            print(f"[geocode] {region}: subs {s['enriched']}/{s['total']}, "
                  f"plants {p['enriched']}/{p['total']}")
    if args.overpass:
        for region in regions:
            p = enrich_overpass(db, region, "plants")
            print(f"[overpass] {region}: plants {p['enriched']}/{p['pending']}")
    if args.p03:
        from scripts.enrich_plants_p03 import parse_p03
        p03_plants = parse_p03(args.p03)
        print(f"[p03] parsed {len(p03_plants)} P03 plants from {args.p03}")
        for region in regions:
            s = enrich_p03(db, region, p03_plants)
            print(f"[p03] {region}: matched {s['matched']}, enriched {s['enriched']}")
    print(f"-> {args.db}. Run scripts/db/export.py to regenerate the GeoJSON.")


if __name__ == "__main__":
    main()
