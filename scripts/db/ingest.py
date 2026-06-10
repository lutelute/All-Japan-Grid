#!/usr/bin/env python3
"""Ingest the legacy enriched GeoJSON into the unified grid DB (Step 1).

Decomposes ``data/{region}_{layer}.geojson`` into raw features (R layer)
and curated enrichments (C layer) per docs/DB_ARCHITECTURE.md.
Idempotent: re-running replaces the ingested slice.

Usage:
    python scripts/db/ingest.py                       # all 10 regions -> data/grid.db
    python scripts/db/ingest.py --regions okinawa hokuriku
    python scripts/db/ingest.py --db /tmp/test.db --data-dir data
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

from src.db.geojson_sync import (  # noqa: E402
    LAYERS,
    ingest_geojson,
    load_enrichments_jsonl,
)
from src.db.grid_db import GridDatabase  # noqa: E402
from src.server.geojson_loader import REGIONS  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", default="data/grid.db", help="SQLite path")
    parser.add_argument("--data-dir", default="data", help="GeoJSON dir")
    parser.add_argument(
        "--regions",
        nargs="+",
        default=["all"],
        help="Region names or 'all' (default)",
    )
    parser.add_argument(
        "--enrichments",
        default="data/db/enrichments.jsonl",
        help="curation backup to restore after ingest (the committed C layer)",
    )
    parser.add_argument(
        "--no-enrichments",
        action="store_true",
        help="ingest raw only; do not restore the curation backup",
    )
    args = parser.parse_args()

    regions = REGIONS if args.regions == ["all"] else args.regions
    unknown = [r for r in regions if r not in REGIONS]
    if unknown:
        sys.exit(f"unknown region(s): {', '.join(unknown)}")

    db = GridDatabase(args.db)
    total_features = total_curated = 0
    for region in regions:
        for layer in LAYERS:
            path = os.path.join(args.data_dir, f"{region}_{layer}.geojson")
            if not os.path.exists(path):
                print(f"[skip] {path} not found")
                continue
            stats = ingest_geojson(db, region, layer, path)
            total_features += stats["features"]
            total_curated += stats["curated_rows"]
            print(
                f"[ok] {region}/{layer}: {stats['features']} features, "
                f"{stats['curated_rows']} curated rows"
            )
    print(
        f"TOTAL: {total_features} features, {total_curated} curated rows "
        f"-> {args.db}"
    )

    # Restore the committed curation backup (P03, manual fixes, …) so a fresh
    # rebuild reconstructs the full curated state — not just what the legacy
    # GeoJSON markers carry. Idempotent (upsert keyed by feature identity).
    if not args.no_enrichments and os.path.exists(args.enrichments):
        n = load_enrichments_jsonl(db, args.enrichments, regions=regions)
        print(f"[restore] applied {n} curation rows from {args.enrichments}")
    elif not args.no_enrichments:
        print(f"[restore] no curation backup at {args.enrichments} (skipped)")


if __name__ == "__main__":
    main()
