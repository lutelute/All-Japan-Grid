#!/usr/bin/env python3
"""Connectivity diagnostic for the west island AC non-convergence.

The Q-sweep showed reactive compensation is NOT the cause (all reactive levels
fail). The west base has ext_grid=52 => 52 connected components. This script
inspects the topology to localise WHY nr does not converge:

  1. connected-component size distribution + largest-component coverage
  2. per-component load/gen balance (a component with load >> gen cannot solve)
  3. try AC on the LARGEST component only (isolate the offender)
  4. flag pathological branches (tiny/huge impedance, recon_line synthetics)

Builds the base once and caches it to /tmp/west_base.pkl for fast re-runs.

Usage::
    PYTHONPATH=. python scripts/test_west_connectivity.py
"""
import os
import pickle
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandapower as pp
import pandapower.topology as top

from scripts.test_west_reactive import build_base

PICKLE = "/tmp/west_base.pkl"


def get_base():
    if os.path.exists(PICKLE):
        print("loading cached base from", PICKLE, flush=True)
        with open(PICKLE, "rb") as fh:
            return pickle.load(fh)
    print("building west base (once, ~9min)...", flush=True)
    base = build_base()
    with open(PICKLE, "wb") as fh:
        pickle.dump(base, fh)
    print("cached base to", PICKLE, flush=True)
    return base


def main():
    net = get_base()
    nb = len(net.bus)
    print(f"west base: {nb} buses, {len(net.line)} lines, "
          f"gen={len(net.gen)}, ext_grid={len(net.ext_grid)}, "
          f"loads={len(net.load)}", flush=True)

    # 1) connected components
    g = top.create_nxgraph(net, respect_switches=False)
    import networkx as nx
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    sizes = [len(c) for c in comps]
    print(f"=== {len(comps)} connected components ===", flush=True)
    print(f"top-10 sizes: {sizes[:10]}", flush=True)
    big = sizes[0]
    print(f"largest covers {big}/{nb} = {100*big//max(nb,1)}%  "
          f"| singletons={sum(1 for s in sizes if s==1)} "
          f"| <=3 buses={sum(1 for s in sizes if s<=3)}", flush=True)

    # 2) per-component load/gen balance for the biggest few
    print("=== balance of top-8 components (P_load vs P_gen MW) ===", flush=True)
    load_by_bus = net.load.groupby("bus")["p_mw"].sum()
    gen_by_bus = net.gen.groupby("bus")["p_mw"].sum() if len(net.gen) else None
    for i, c in enumerate(comps[:8]):
        pl = float(load_by_bus.reindex(list(c)).fillna(0).sum())
        pg = float(gen_by_bus.reindex(list(c)).fillna(0).sum()) if gen_by_bus is not None else 0.0
        ng = int(sum(1 for b in c if gen_by_bus is not None and b in gen_by_bus.index))
        print(f"  comp{i}: buses={len(c)} P_load={pl:.0f} P_gen={pg:.0f} "
              f"gens={ng} {'<<LOAD>GEN' if pl > pg*1.2 else ''}", flush=True)

    # 3) AC on the largest component only
    print("=== AC nr/dc on LARGEST component only ===", flush=True)
    keep = set(comps[0])
    net2 = pp.select_subnet(net, list(keep), include_results=False)
    # ensure a slack in the subnet
    if len(net2.ext_grid) == 0 and len(net2.bus) > 0:
        hv = net2.bus["vn_kv"].idxmax()
        pp.create_ext_grid(net2, bus=int(hv), vm_pu=1.0)
    net2.bus["vm_pu"] = 1.0
    if len(net2.gen) > 0:
        net2.gen["vm_pu"] = 1.0
    try:
        pp.runpp(net2, algorithm="nr", init="dc", max_iteration=100,
                 tolerance_mva=1e-1, numba=True)
        vm = net2.res_bus["vm_pu"].dropna()
        print(f"  largest-comp AC=OK  buses={len(net2.bus)} "
              f"vm=[{vm.min():.3f},{vm.max():.3f}]", flush=True)
    except Exception as e:
        print(f"  largest-comp AC=FAIL  buses={len(net2.bus)} "
              f"{type(e).__name__}: {str(e)[:70]}", flush=True)

    # 4) pathological branch stats
    print("=== branch impedance stats ===", flush=True)
    li = net.line
    recon = li["name"].astype(str).str.startswith("recon_line").sum()
    tie = li["name"].astype(str).str.startswith("tie_").sum()
    xtot = li["x_ohm_per_km"] * li["length_km"]
    rtot = li["r_ohm_per_km"] * li["length_km"]
    print(f"  lines={len(li)} recon_line={recon} tie={tie}", flush=True)
    print(f"  length_km: min={li['length_km'].min():.3f} "
          f"p50={li['length_km'].median():.1f} max={li['length_km'].max():.1f}", flush=True)
    print(f"  X_total_ohm: min={xtot.min():.4f} p50={xtot.median():.2f} "
          f"max={xtot.max():.1f}", flush=True)
    print(f"  very-short lines(<0.5km)={int((li['length_km']<0.5).sum())} "
          f"very-long(>200km)={int((li['length_km']>200).sum())}", flush=True)
    print("DONE_CONN", flush=True)


if __name__ == "__main__":
    main()
