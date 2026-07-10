#!/usr/bin/env python3
"""Export All-Japan-Grid GeoJSON to CIM/CGMES RDF/XML (EQ + GL profiles).

Reads ``data/<region>_{substations,lines,plants}.geojson`` and writes, per
region, a CGMES Equipment file (``<region>_EQ.xml``) and a Geographical
Location file (``<region>_GL.xml``) into the output directory, plus a
``cim_index.json`` manifest.

Usage:
    python scripts/export_cim.py                       # all 10 regions -> dist/cim
    python scripts/export_cim.py --regions okinawa     # one region
    python scripts/export_cim.py --out-dir /tmp/cim    # custom output dir
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from src.cim.boundary import BOUNDARY_VOLTAGES, generate_boundary  # noqa: E402
from src.cim.core import NS_CIM, PROFILE_EQ, PROFILE_GL  # noqa: E402
from src.cim.exporter import REGION_NAME, export_region  # noqa: E402


def main() -> int:
    """Run the CIM export over the requested regions; print a summary table."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--regions",
        nargs="*",
        default=list(REGION_NAME),
        help="Regions to export (default: all 10).",
    )
    parser.add_argument("--data-dir", default="data", help="Input GeoJSON directory.")
    parser.add_argument("--out-dir", default="dist/cim", help="Output directory.")
    args = parser.parse_args()

    summaries = []
    print(f"{'region':10s} {'subs':>6s} {'lines':>6s} {'plants':>6s} {'trafos':>6s}  {'EQ_obj':>7s} {'GL_obj':>8s}")
    print("-" * 63)
    for region in args.regions:
        summary = export_region(region, args.data_dir, args.out_dir)
        summaries.append(summary)
        counts = summary["counts"]
        print(
            f"{region:10s} "
            f"{counts.get('substations', 0):6d} "
            f"{counts.get('lines', 0):6d} "
            f"{counts.get('plants', 0):6d} "
            f"{counts.get('transformers', 0):6d}  "
            f"{summary['eq_objects']:7d} {summary['gl_objects']:8d}"
        )

    totals = {
        kind: sum(s["counts"].get(kind, 0) for s in summaries)
        for kind in ("substations", "lines", "plants", "transformers")
    }
    print("-" * 63)
    print(
        f"{'TOTAL':10s} "
        f"{totals['substations']:6d} "
        f"{totals['lines']:6d} "
        f"{totals['plants']:6d} "
        f"{totals['transformers']:6d}  "
        f"{sum(s['eq_objects'] for s in summaries):7d} "
        f"{sum(s['gl_objects'] for s in summaries):8d}"
    )

    # Shared boundary set: the Level-1 EQ no longer defines BaseVoltage
    # inline (duplicate rdf:IDs vs the boundary — REVIEW_FINDINGS P0 #9),
    # so every export must ship a boundary covering all referenced voltages.
    all_kv = sorted(
        {round(float(v), 3) for v in BOUNDARY_VOLTAGES}
        | {round(float(v), 3) for s in summaries for v in s["base_voltages"]},
        reverse=True)
    bsum = generate_boundary(args.out_dir, all_kv)
    print(f"\nBoundary: {bsum['eq_bd_objects']} BaseVoltages "
          "-> AllJapan_EQ_BD.xml / AllJapan_TP_BD.xml")

    # Relativise paths in the manifest so it is location-independent.
    out_dir = args.out_dir
    manifest = {
        "dataset": "All-Japan-Grid",
        "cim_namespace": NS_CIM,
        "profiles": {"EQ": PROFILE_EQ, "GL": PROFILE_GL,
                     "EQ_BD": "boundary", "TP_BD": "boundary"},
        "boundary_voltages_kv": all_kv,
        "totals": totals,
        "regions": [
            {
                "region": s["region"],
                "counts": s["counts"],
                "eq_objects": s["eq_objects"],
                "gl_objects": s["gl_objects"],
                "base_voltages_kv": s["base_voltages"],
                "eq_file": os.path.basename(s["eq_path"]),
                "gl_file": os.path.basename(s["gl_path"]),
            }
            for s in summaries
        ],
    }
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "cim_index.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    print(f"\nWrote {len(summaries)} region(s) + cim_index.json to {out_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
