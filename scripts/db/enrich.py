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

from src.db.enrich import apply_audit_fixes, enrich_lines_endpoints  # noqa: E402
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
    args = parser.parse_args()

    if not (args.lines or args.audit):
        sys.exit("nothing to do: pass --lines and/or --audit")
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
    print(f"-> {args.db}. Run scripts/db/export.py to regenerate the GeoJSON.")


if __name__ == "__main__":
    main()
