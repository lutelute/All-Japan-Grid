#!/usr/bin/env python3
"""Test AC convergence of each west region SOLO (split the zonal island).

Q-sweep and short-line fusion both failed: the 12k-bus west island will not
converge as one AC network. east island converged at ~4500 buses (tokyo 2952),
so this checks whether each west region ALONE (2-3k buses) converges — i.e.
whether per-region AC is feasible even though the zonal whole is not.

Loads cached base from /tmp/west_base.pkl. For each zone, take its buses, keep
the largest internal component, ensure a slack, and try nr/dc.

Usage::
    PYTHONPATH=. python scripts/test_west_byregion.py
"""
import os
import pickle
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import networkx as nx
import pandapower as pp
import pandapower.topology as top

PICKLE = "/tmp/west_base.pkl"


def solo_ac(base, zone):
    bidx = base.bus.index[base.bus["zone"] == zone].tolist()
    if not bidx:
        return f"  {zone:<9}: no buses"
    sub = pp.select_subnet(base, bidx, include_results=False)
    g = top.create_nxgraph(sub, respect_switches=False)
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    if not comps:
        return f"  {zone:<9}: no components"
    sub2 = pp.select_subnet(sub, list(comps[0]), include_results=False)
    cover = 100 * len(comps[0]) // max(len(sub.bus), 1)
    if len(sub2.ext_grid) == 0 and len(sub2.bus) > 0:
        hv = sub2.bus["vn_kv"].idxmax()
        pp.create_ext_grid(sub2, bus=int(hv), vm_pu=1.0)
    sub2.bus["vm_pu"] = 1.0
    if len(sub2.gen) > 0:
        sub2.gen["vm_pu"] = 1.0
    pl = float(sub2.load["p_mw"].sum()) if len(sub2.load) else 0.0
    pg = float(sub2.gen["p_mw"].sum()) if len(sub2.gen) else 0.0
    try:
        pp.runpp(sub2, algorithm="nr", init="dc", max_iteration=100,
                 tolerance_mva=1e-1, numba=True)
        vm = sub2.res_bus["vm_pu"].dropna()
        return (f"  {zone:<9}: AC=OK   buses={len(sub2.bus)}/{len(sub.bus)} "
                f"(largest {cover}%) comps={len(comps)} "
                f"vm=[{vm.min():.3f},{vm.max():.3f}] P_load={pl:.0f} P_gen={pg:.0f}")
    except Exception as e:
        return (f"  {zone:<9}: AC=FAIL buses={len(sub2.bus)}/{len(sub.bus)} "
                f"(largest {cover}%) comps={len(comps)} "
                f"P_load={pl:.0f} P_gen={pg:.0f} {type(e).__name__}")


def main():
    if not os.path.exists(PICKLE):
        print("ERROR: no cached base; run test_west_connectivity.py first", flush=True)
        return
    with open(PICKLE, "rb") as fh:
        base = pickle.load(fh)
    zones = sorted(z for z in base.bus["zone"].dropna().unique())
    print(f"loaded base: {len(base.bus)} buses; zones={zones}", flush=True)
    print("=== per-region SOLO AC (nr/dc, largest internal component) ===", flush=True)
    for z in zones:
        print(solo_ac(base, z), flush=True)
    print("DONE_BYREGION", flush=True)


if __name__ == "__main__":
    main()
