#!/usr/bin/env python3
"""Fuse near-zero-impedance (very short) lines to fix west-island AC convergence.

Diagnosis: the largest component (98% of buses) fails AC because 2480/7589 lines
are <0.5 km (min 4 m, X as low as 0.0015 ohm). These near-zero-impedance branches
make Ybus ill-conditioned and the NR Jacobian near-singular, so power flow never
converges. They are vertex-snap / reconnect artefacts: the two endpoints are
electrically the SAME node.

Fix: union-find the buses joined by very short lines and fuse each group into one
bus (pp.fuse_buses), removing the degenerate branch. Sweep the fuse threshold and
test AC on the largest component each time.

Loads the cached base from /tmp/west_base.pkl (built by test_west_connectivity).

Usage::
    PYTHONPATH=. python scripts/test_west_fuse.py
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


def fuse_short_lines(net, thr_km):
    """Union-find buses linked by lines shorter than thr_km, fuse each group."""
    short = net.line[(net.line["length_km"] < thr_km) & net.line["in_service"]]
    if len(short) == 0:
        return 0, 0
    gg = nx.Graph()
    for fb, tb in zip(short["from_bus"].to_numpy(), short["to_bus"].to_numpy()):
        gg.add_edge(int(fb), int(tb))
    n_groups = 0
    n_fused = 0
    for grp in nx.connected_components(gg):
        grp = sorted(int(b) for b in grp if b in net.bus.index)
        if len(grp) < 2:
            continue
        keep = grp[0]
        # fuse the rest into keep (drops degenerate lines automatically)
        pp.fuse_buses(net, keep, grp[1:], drop=True)
        n_groups += 1
        n_fused += len(grp) - 1
    return n_groups, n_fused


def largest_comp_ac(net):
    g = top.create_nxgraph(net, respect_switches=False)
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    keep = list(comps[0])
    sub = pp.select_subnet(net, keep, include_results=False)
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
        return (True, len(sub.bus), len(comps), float(vm.min()), float(vm.max()))
    except Exception as e:
        return (False, len(sub.bus), len(comps), None, str(e)[:50])


def main():
    if not os.path.exists(PICKLE):
        print("ERROR: no cached base at", PICKLE,
              "- run test_west_connectivity.py first", flush=True)
        return
    with open(PICKLE, "rb") as fh:
        base = pickle.load(fh)
    print(f"loaded base: {len(base.bus)} buses, {len(base.line)} lines", flush=True)
    print("=== fuse-threshold sweep (AC nr/dc on largest comp) ===", flush=True)
    for thr in (0.05, 0.1, 0.3, 0.5, 1.0):
        net = copy.deepcopy(base)
        ng, nf = fuse_short_lines(net, thr)
        ok, nb, ncomp, lo, hi = largest_comp_ac(net)
        if ok:
            print(f"thr={thr:<4}km: fused {nf} buses in {ng} groups -> "
                  f"buses={nb} comps={ncomp} AC=OK vm=[{lo:.3f},{hi:.3f}]", flush=True)
        else:
            print(f"thr={thr:<4}km: fused {nf} buses in {ng} groups -> "
                  f"buses={nb} comps={ncomp} AC=FAIL {hi}", flush=True)
    print("DONE_FUSE", flush=True)


if __name__ == "__main__":
    main()
