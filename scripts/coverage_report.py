#!/usr/bin/env python3
"""Provenance & validation coverage report for the unified grid DB.

The point of this tool is **honesty made measurable**: it reports how much
of the model is corroborated by an *authoritative* source (国土数値情報 P03
for plants) versus how much is OSM-derived or synthetic — so a user can see
the limits of the data at a glance instead of inferring them. This is the
reporting half of the provenance promise in docs/VISION.md (Pillar 5) and
the honest-current-state framing of §2.

    python scripts/coverage_report.py --db data/grid.db
    ajgrid coverage                      # same, via the unified CLI

It only reads the DB, so it is safe to run anywhere a ``grid.db`` exists
(rebuild one with ``ajgrid db ingest``). With no P03/authoritative rows it
still prints a valid report (0% validated) — that *is* the current state on
a fresh ingest.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlalchemy as sa  # noqa: E402

from src.db.grid_db import GridDatabase  # noqa: E402

LAYERS = ("substations", "lines", "plants")
#: sources that carry an *authoritative* (third-party-validated) value, as
#: opposed to OSM tags or synthetic/heuristic fill.
AUTHORITATIVE = {"p03_db": "国土数値情報 P03 (発電所)"}


def _pct(n, d):
    return f"{(100.0 * n / d):.1f}%" if d else "—"


def gather(db_path):
    db = GridDatabase(db_path)
    out = {"db": db_path}
    with db._engine.connect() as c:
        out["raw"] = dict(
            c.execute(sa.text(
                "select layer, count(*) from raw_features group by layer")).all())
        out["by_source"] = c.execute(sa.text(
            "select source, count(*) n from enrichments "
            "group by source order by n desc")).all()
        # plants corroborated by authoritative P03
        out["p03_plants"] = c.execute(sa.text(
            "select count(distinct feature_key) from enrichments "
            "where source='p03_db' and layer='plants'")).scalar() or 0
        out["p03_capacity"] = c.execute(sa.text(
            "select count(distinct feature_key) from enrichments "
            "where source='p03_db' and field='capacity_mw'")).scalar() or 0
        out["p03_operator"] = c.execute(sa.text(
            "select count(distinct feature_key) from enrichments "
            "where source='p03_db' and field='operator'")).scalar() or 0
        # plants carrying any operator at all (OSM or authoritative)
        out["any_named_plants"] = c.execute(sa.text(
            "select count(distinct feature_key) from enrichments "
            "where layer='plants' and field in ('name','_display_name')")).scalar() or 0
    return out


def render(d) -> str:
    raw = d["raw"]
    subs, lines, plants = (raw.get(k, 0) for k in LAYERS)
    L = []
    L.append(f"Provenance & validation coverage — {d['db']}")
    L.append("=" * 60)
    L.append(f"Raw features: {sum(raw.values()):,}  "
             f"(substations {subs:,} / lines {lines:,} / plants {plants:,})")
    L.append("")
    L.append(f"Plants validated against authoritative P03 (国土数値情報, ≤2 km):")
    L.append(f"  corroborated plants : {d['p03_plants']:,}  ({_pct(d['p03_plants'], plants)})")
    L.append(f"   ├ authoritative capacity_mw : {d['p03_capacity']:,}  ({_pct(d['p03_capacity'], plants)})")
    L.append(f"   └ authoritative operator    : {d['p03_operator']:,}  ({_pct(d['p03_operator'], plants)})")
    L.append(f"  → the remaining {_pct(plants - d['p03_plants'], plants)} of plants are "
             f"OSM-only (no authoritative corroboration).")
    L.append("")
    L.append("Enrichments by provenance (source):")
    for src, n in d["by_source"]:
        tag = f"   ← authoritative: {AUTHORITATIVE[src]}" if src in AUTHORITATIVE else ""
        L.append(f"  {src:22s} {n:>8,}{tag}")
    L.append("")
    L.append("KNOWN LIMITATION (do not skip): electrical parameters — line R/X/B and")
    L.append("transformer impedance/tap — are SYNTHETIC for the whole network (voltage-")
    L.append("class typicals + kV² approximations). No authoritative electrical source")
    L.append("is ingested yet; P03 corroborates plant identity/capacity, not impedances.")
    L.append("Trends and merit order are meaningful; individual-asset operation is not.")
    L.append("See docs/VISION.md §2 and docs/INTEROP.md.")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="data/grid.db", help="SQLite path")
    args = ap.parse_args(argv)
    if not os.path.exists(args.db):
        print(f"no DB at {args.db} — build one with `ajgrid db ingest`",
              file=sys.stderr)
        return 2
    print(render(gather(args.db)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
