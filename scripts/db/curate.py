#!/usr/bin/env python3
"""Apply curated edits to the unified grid DB (DB unification Step 3).

This is the mechanical-update write path: edits land in the C layer
(``enrichments``) keyed by feature identity, so they survive a later
OSM re-fetch instead of being overwritten in the raw file. Run
``scripts/db/export.py`` afterwards to regenerate the GeoJSON.

Examples:
    # Manual single-field override, located by current name
    python scripts/db/curate.py --layer substations --region okinawa \\
        --where-name "那覇変電所" --set operator="沖縄電力" --source manual

    # Override located by OSM id
    python scripts/db/curate.py --layer plants --region okinawa \\
        --where-osm-id 123456 --set fuel_type=gas

    # Bulk import a fix set: a JSON list of
    #   {layer, region, feature_key|name|osm_id, field, value, source?}
    python scripts/db/curate.py --import fixes.json
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
    apply_enrichments,
    find_feature_keys,
)
from src.db.grid_db import GridDatabase  # noqa: E402


def _coerce(raw: str):
    """Parse a CLI value as JSON when possible, else keep the string."""
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _rows_from_args(db: GridDatabase, args) -> list:
    keys = []
    if args.where_feature_key:
        keys = [args.where_feature_key]
    elif args.where_osm_id is not None:
        keys = find_feature_keys(
            db, args.layer, args.region, osm_id=args.where_osm_id
        )
    elif args.where_name is not None:
        keys = find_feature_keys(
            db, args.layer, args.region, name=args.where_name
        )
    if not keys:
        sys.exit("no matching feature found for the given --where-* selector")
    rows = []
    for assignment in args.set:
        if "=" not in assignment:
            sys.exit(f"--set expects field=value, got {assignment!r}")
        field, raw = assignment.split("=", 1)
        for key in keys:
            rows.append({
                "layer": args.layer,
                "region": args.region,
                "feature_key": key,
                "field": field,
                "value": _coerce(raw),
                "source": args.source,
            })
    return rows


def _rows_from_import(db: GridDatabase, path: str, default_source: str) -> list:
    with open(path, encoding="utf-8") as fh:
        records = json.load(fh)
    rows = []
    for rec in records:
        layer, region = rec["layer"], rec["region"]
        if "feature_key" in rec:
            keys = [rec["feature_key"]]
        elif "osm_id" in rec:
            keys = find_feature_keys(db, layer, region, osm_id=rec["osm_id"])
        elif "name" in rec:
            keys = find_feature_keys(db, layer, region, name=rec["name"])
        else:
            sys.exit(f"record needs feature_key|osm_id|name: {rec!r}")
        for key in keys:
            rows.append({
                "layer": layer,
                "region": region,
                "feature_key": key,
                "field": rec["field"],
                "value": rec["value"],
                "source": rec.get("source", default_source),
                "confidence": rec.get("confidence"),
            })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", default="data/grid.db", help="SQLite path")
    parser.add_argument("--layer", choices=["substations", "lines", "plants"])
    parser.add_argument("--region")
    sel = parser.add_mutually_exclusive_group()
    sel.add_argument("--where-name", help="locate by current effective name")
    sel.add_argument("--where-osm-id", type=int, help="locate by OSM id")
    sel.add_argument("--where-feature-key", help="locate by exact feature_key")
    parser.add_argument(
        "--set", action="append", default=[], metavar="field=value",
        help="field assignment (repeatable; value parsed as JSON if valid)")
    parser.add_argument("--source", default="manual",
                        help="provenance label (default: manual)")
    parser.add_argument("--import", dest="import_path", metavar="PATH",
                        help="bulk-import a JSON fix set")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    db = GridDatabase(args.db)
    if args.import_path:
        rows = _rows_from_import(db, args.import_path, args.source)
    else:
        if not (args.layer and args.region and args.set):
            sys.exit("provide --layer/--region/--set (+a --where-* selector) "
                     "or --import PATH")
        rows = _rows_from_args(db, args)

    n = apply_enrichments(db, rows, run_id=args.run_id)
    print(f"[curate] upserted {n} enrichment row(s) into {args.db}")
    print("Run scripts/db/export.py to regenerate the GeoJSON.")


if __name__ == "__main__":
    main()
