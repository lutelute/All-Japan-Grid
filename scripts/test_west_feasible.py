#!/usr/bin/env python3
"""Test whether load-feasibility capping makes the west island AC-converge.

Per-region SOLO test proved the rule: regions with P_load < P_gen converge,
regions with P_load > P_gen (kansai 21.8>16.4 GW, kyushu 12.6>11.3 GW) fail.
The OSM-derived generation capacity is simply below the allocated peak demand
there, so power flow is physically infeasible.

Fix under test: cap each zone's total load to a fraction of its in-zone
generation capacity (so generation >= load everywhere), then solve the WHOLE
west island (largest component) — checking that feasibility, not topology
tweaks, is what unlocks convergence.

Loads cached base from /tmp/west_base.pkl.

Usage::
    PYTHONPATH=. python scripts/test_west_feasible.py
"""
import copy
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


def cap_loads_to_gen(net, headroom=0.9):
    """Scale down each zone's loads so zone P_load <= headroom * zone P_gen_cap."""
    gen_cap_col = "max_p_mw" if "max_p_mw" in net.gen.columns else "p_mw"
    report = []
    for zone in sorted(net.bus["zone"].dropna().unique()):
        zb = set(net.bus.index[net.bus["zone"] == zone])
        lidx = net.load.index[net.load["bus"].isin(zb)]
        gidx = net.gen.index[net.gen["bus"].isin(zb)]
        pl = float(net.load.loc[lidx, "p_mw"].sum())
        pgc = float(net.gen.loc[gidx, gen_cap_col].sum())
        if pl > headroom * pgc and pl > 0:
            scale = headroom * pgc / pl
            net.load.loc[lidx, "p_mw"] *= scale
            net.load.loc[lidx, "q_mvar"] *= scale
            report.append(f"{zone}:{pl:.0f}->{headroom*pgc:.0f}MW(x{scale:.2f})")
    return report


def island_ac(net):
    g = top.create_nxgraph(net, respect_switches=False)
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    sub = pp.select_subnet(net, list(comps[0]), include_results=False)
    if len(sub.ext_grid) == 0 and len(sub.bus) > 0:
        hv = sub.bus["vn_kv"].idxmax()
        pp.create_ext_grid(sub, bus=int(hv), vm_pu=1.0)
    sub.bus["vm_pu"] = 1.0
    if len(sub.gen) > 0:
        sub.gen["vm_pu"] = 1.0
    try:
        pp.runpp(sub, algorithm="nr", init="dc", max_iteration=100,
                 tolerance_mva=1e-1, numba=True)
        vm = sub.res_bus["vm_pu"].dropna()
        return True, len(sub.bus), len(comps), float(vm.min()), float(vm.max())
    except Exception as e:
        return False, len(sub.bus), len(comps), None, str(e)[:50]


def main():
    if not os.path.exists(PICKLE):
        print("ERROR: no cached base; run test_west_connectivity.py first", flush=True)
        return
    with open(PICKLE, "rb") as fh:
        base = pickle.load(fh)
    print(f"loaded base: {len(base.bus)} buses, {len(base.line)} lines", flush=True)

    # Baseline: whole west island, no capping
    ok, nb, nc, lo, hi = island_ac(copy.deepcopy(base))
    print(f"baseline (no cap): largest-comp AC={'OK' if ok else 'FAIL'} "
          f"buses={nb} comps={nc}" + (f" vm=[{lo:.3f},{hi:.3f}]" if ok else f" {hi}"),
          flush=True)

    # Capping sweep
    for hr in (0.9, 0.7, 0.5):
        net = copy.deepcopy(base)
        rep = cap_loads_to_gen(net, headroom=hr)
        ok, nb, nc, lo, hi = island_ac(net)
        tag = "OK" if ok else "FAIL"
        extra = f" vm=[{lo:.3f},{hi:.3f}]" if ok else f" {hi}"
        print(f"headroom={hr}: capped[{', '.join(rep) if rep else 'none'}] -> "
              f"west island AC={tag} buses={nb}{extra}", flush=True)
    print("DONE_FEASIBLE", flush=True)


if __name__ == "__main__":
    main()
