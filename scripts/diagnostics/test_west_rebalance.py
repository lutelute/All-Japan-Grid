#!/usr/bin/env python3
"""Region-wise re-balance to unlock west-island AC convergence.

Root cause (proven): balance_power scales generation uniformly across the whole
west island. Because the island as a whole has surplus capacity (chubu etc.),
the uniform scale < 1 pushes kansai/kyushu local generation BELOW their local
load, even though those regions' OWN capacity is sufficient. The deficit
component then prevents NR convergence.

Fix under test: re-balance PER ZONE — set each zone's gen p_mw so the zone meets
its own load (x reserve), capped at the zone's capacity. Then solve the WHOLE
west island. If this converges, the cure is per-region balancing, which we then
fold into solve_island.

Loads cached base from /tmp/west_base.pkl.

Usage::
    PYTHONPATH=. python scripts/test_west_rebalance.py
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


def rebalance_per_zone(net, reserve=0.10):
    cap_col = "max_p_mw" if "max_p_mw" in net.gen.columns else "p_mw"
    rep = []
    for zone in sorted(net.bus["zone"].dropna().unique()):
        zb = set(net.bus.index[net.bus["zone"] == zone])
        lidx = net.load.index[net.load["bus"].isin(zb) & net.load["in_service"]]
        gidx = net.gen.index[net.gen["bus"].isin(zb)]
        if len(gidx) == 0:
            continue
        zl = float(net.load.loc[lidx, "p_mw"].sum())
        zcap = float(net.gen.loc[gidx, cap_col].sum())
        if zcap <= 0:
            continue
        target = zl * (1.0 + reserve)
        scale = min(target / zcap, 1.0)
        net.gen.loc[gidx, "p_mw"] = net.gen.loc[gidx, cap_col] * scale
        pg = float(net.gen.loc[gidx, "p_mw"].sum())
        rep.append(f"{zone}:load={zl:.0f},gen={pg:.0f}{'(capped)' if scale>=1 and pg<target else ''}")
    return rep


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
        ml = sub.res_line["loading_percent"].dropna()
        return True, len(sub.bus), float(vm.min()), float(vm.max()), float(ml.max() if len(ml) else 0)
    except Exception as e:
        return False, len(sub.bus), None, None, str(e)[:50]


def main():
    if not os.path.exists(PICKLE):
        print("ERROR: no cached base; run test_west_connectivity.py first", flush=True)
        return
    with open(PICKLE, "rb") as fh:
        base = pickle.load(fh)
    print(f"loaded base: {len(base.bus)} buses, {len(base.line)} lines", flush=True)

    for reserve in (0.10, 0.30):
        net = copy.deepcopy(base)
        rep = rebalance_per_zone(net, reserve=reserve)
        ok, nb, lo, hi, ml = island_ac(net)
        print(f"--- reserve={reserve} ---", flush=True)
        print("  " + " | ".join(rep), flush=True)
        if ok:
            print(f"  west island AC=OK buses={nb} vm=[{lo:.3f},{hi:.3f}] maxload={ml:.0f}%", flush=True)
        else:
            print(f"  west island AC=FAIL buses={nb} {hi}", flush=True)
    print("DONE_REBAL", flush=True)


if __name__ == "__main__":
    main()
