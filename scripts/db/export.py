#!/usr/bin/env python3
"""Export / verify GeoJSON from the unified grid DB (Step 2).

``--verify`` is the golden check: composes every (region, layer) from
the DB and compares it semantically against the legacy file under
``--data-dir``; exits non-zero on any difference.

Usage:
    python scripts/db/export.py --verify                  # golden check vs data/
    python scripts/db/export.py --out-dir data/db/export_preview
    python scripts/db/export.py --dump-enrichments data/db/enrichments.jsonl
"""

import argparse
import json
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
    dump_enrichments_jsonl,
    export_geojson,
    verify_roundtrip,
)
from src.db.grid_db import GridDatabase  # noqa: E402
from src.server.geojson_loader import REGIONS  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", default="data/grid.db", help="SQLite path")
    parser.add_argument(
        "--data-dir", default="data", help="Originals for --verify"
    )
    parser.add_argument(
        "--regions", nargs="+", default=["all"], help="Regions or 'all'"
    )
    parser.add_argument(
        "--out-dir", default=None, help="Write composed GeoJSON here"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Golden check against --data-dir originals",
    )
    parser.add_argument(
        "--dump-enrichments",
        default=None,
        metavar="PATH",
        help="Write the C-layer JSONL dump (tracked curation backup)",
    )
    args = parser.parse_args()

    regions = REGIONS if args.regions == ["all"] else args.regions
    unknown = [r for r in regions if r not in REGIONS]
    if unknown:
        sys.exit(f"unknown region(s): {', '.join(unknown)}")

    db = GridDatabase(args.db)
    failed = False

    if args.verify or args.out_dir:
        for region in regions:
            for layer in LAYERS:
                original = os.path.join(
                    args.data_dir, f"{region}_{layer}.geojson"
                )
                if args.verify:
                    if not os.path.exists(original):
                        print(f"[skip] {original} not found")
                        continue
                    problems = verify_roundtrip(db, region, layer, original)
                    if problems:
                        failed = True
                        print(f"[FAIL] {region}/{layer}:")
                        for p in problems:
                            print(f"       - {p}")
                    else:
                        print(f"[ok] {region}/{layer}: roundtrip equivalent")
                if args.out_dir:
                    os.makedirs(args.out_dir, exist_ok=True)
                    out_path = os.path.join(
                        args.out_dir, f"{region}_{layer}.geojson"
                    )
                    collection = export_geojson(db, region, layer)
                    with open(out_path, "w", encoding="utf-8") as fh:
                        json.dump(
                            collection,
                            fh,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    print(f"[write] {out_path}")

    if args.dump_enrichments:
        os.makedirs(
            os.path.dirname(args.dump_enrichments) or ".", exist_ok=True
        )
        count = dump_enrichments_jsonl(db, args.dump_enrichments)
        print(f"[dump] {count} enrichment rows -> {args.dump_enrichments}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
