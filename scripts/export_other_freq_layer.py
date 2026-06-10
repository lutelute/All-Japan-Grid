#!/usr/bin/env python3
"""Export the OTHER-frequency equipment of each region as a reference layer.

The power-flow model rightly excludes equipment that belongs to the other
synchronous system (frequency-tag-first, see snapped_topology._freq_excluded)
— but that equipment physically exists in the region's geography, and a map
that simply drops it understates reality (user review, 2026-06-10). This
script emits those excluded features as
``docs/data/powerflow/{region}_other_freq_lines.geojson`` so the live map can
render them as a clearly-labelled, NOT-solved reference overlay.

No solving involved — pure data pass. Usage::

    PYTHONPATH=. python scripts/export_other_freq_layer.py [--out-dir DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.powerflow.snapped_topology import DATA_DIR, _freq_excluded
from src.regions import REGION_FREQUENCY_HZ, REGIONS


def export_region(region: str, out_dir: str) -> int:
    path = os.path.join(DATA_DIR, f"{region}_lines.geojson")
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    hz = REGION_FREQUENCY_HZ.get(region, 50)
    feats = []
    for ft in data.get("features", []):
        p = ft.get("properties", {})
        if not _freq_excluded(p, hz):
            continue
        feats.append({
            "type": "Feature",
            "geometry": ft.get("geometry"),
            "properties": {
                "name": p.get("name"),
                "operator": p.get("operator"),
                "voltage": p.get("voltage"),
                "frequency": p.get("frequency"),
                # why it is reference-only, for the tooltip
                "note": f"other synchronous system (region grid is {hz} Hz); "
                        f"present geographically, not part of this AC solve",
            },
        })
    out = {"type": "FeatureCollection",
           "name": f"{region}_other_freq_reference",
           "features": feats}
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{region}_other_freq_lines.geojson")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    return len(feats)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir",
                    default=os.path.join("docs", "data", "powerflow"))
    args = ap.parse_args()
    total = 0
    for r in REGIONS:
        n = export_region(r, args.out_dir)
        total += n
        print(f"  {r:9s} {n:5d} other-frequency features")
    print(f"total {total} -> {args.out_dir}/<region>_other_freq_lines.geojson")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
