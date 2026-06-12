"""Rebuild the live map's national bus layer from the current model (D7).

    PYTHONPATH=. python scripts/gen_all_ac_buses.py

docs/data/powerflow/all_ac_buses.geojson — the bus layer powerflow.js
draws at the national zoom — was a legacy artifact of the 2,189-bus
psdat case with its own coordinate lineage (81.3 % route contact,
ledger 82/87). This recipe replaces it with the union of the current
per-region island slices (docs/data/powerflow_national/*_ac_buses
.geojson — the all-islands-AC model, endpoint-snapped), which carry
the same property schema (name / vn_kv / vm_pu / va_deg) so the
viewer needs no change. Run after scripts/run_national_powerflow.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SRC_DIR = "docs/data/powerflow_national"
OUT = "docs/data/powerflow/all_ac_buses.geojson"
REGIONS = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
           "kansai", "chugoku", "shikoku", "kyushu", "okinawa"]


def main() -> int:
    feats = []
    missing = []
    for r in REGIONS:
        path = os.path.join(SRC_DIR, f"{r}_ac_buses.geojson")
        if not os.path.exists(path):
            missing.append(r)
            continue
        with open(path, encoding="utf-8") as f:
            feats.extend(json.load(f)["features"])
    if missing:
        print(f"warning: missing regions {missing} — layer is partial")
    if not feats:
        print("no source slices — run scripts/run_national_powerflow.py first")
        return 2
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f,
                  ensure_ascii=False)
    print(f"{OUT}: {len(feats):,} buses from {len(REGIONS) - len(missing)} "
          f"region slices (current all-islands-AC model)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
