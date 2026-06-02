#!/usr/bin/env python3
"""Final check: per-zone re-balance + per-region AC for ALL six west regions.

Established so far:
  * Q, short-line fusion, fragmentation: not the cause.
  * Root cause: uniform balance starves kansai/kyushu local generation.
  * Whole-island AC fails even after per-zone re-balance (8238-bus, 6-region
    single AC is too ill-conditioned).
  * 4/6 regions already converge SOLO; kansai/kyushu failed SOLO only because
    P_load > P_gen.

This applies per-zone re-balance (gen meets local load) THEN solves each region
SOLO. If all six converge, the deliverable is per-region AC (+ whole-island DC),
which is what we can honestly publish.

Loads cached base from /tmp/west_base.pkl.

Usage::
    PYTHONPATH=. python scripts/test_west_final.py
"""
import os
import pickle
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.test_west_rebalance import rebalance_per_zone
from scripts.test_west_byregion import solo_ac

PICKLE = "/tmp/west_base.pkl"


def main():
    if not os.path.exists(PICKLE):
        print("ERROR: no cached base; run test_west_connectivity.py first", flush=True)
        return
    with open(PICKLE, "rb") as fh:
        base = pickle.load(fh)
    print(f"loaded base: {len(base.bus)} buses", flush=True)
    rep = rebalance_per_zone(base, reserve=0.10)
    print("re-balanced per zone:", flush=True)
    print("  " + " | ".join(rep), flush=True)
    print("=== per-region SOLO AC after re-balance ===", flush=True)
    n_ok = 0
    for z in sorted(base.bus["zone"].dropna().unique()):
        line = solo_ac(base, z)
        print(line, flush=True)
        if "AC=OK" in line:
            n_ok += 1
    print(f"=== {n_ok}/6 regions converge SOLO after re-balance ===", flush=True)
    print("DONE_FINAL", flush=True)


if __name__ == "__main__":
    main()
