#!/usr/bin/env python3
"""Fix the ill-conditioned transformers that block kansai/kyushu AC convergence.

Diagnosis proved: removing transformers (no-trafo) or keeping only >=154 kV makes
kansai converge, while gs(3000) still fails => the culprit is the transformers
feeding the non-standard low-voltage buses (22/25/30/33/100 kV). Their parameters
make Ybus ill-conditioned.

This tries, on the kansai (or DIAG_ZONE) largest component after per-zone
re-balance, several targeted repairs and reports which one yields AC convergence:

  baseline        confirm FAIL
  vk-floor        clip trafo vk_percent into [8,25], vkr into [0.3,5]
  drop-nonstd     de-energise buses whose vn_kv is not a standard JP class
  drop-belowtap   de-energise buses < 66 kV (distribution tail)
  vk+dropnonstd   vk-floor AND drop non-standard-voltage buses

Loads cached base from /tmp/west_base.pkl.

Usage::
    DIAG_ZONE=kansai PYTHONPATH=. python scripts/test_kansai_trafo.py
"""
import copy
import os
import pickle
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import networkx as nx
import pandapower as pp
import pandapower.topology as top

from scripts.test_west_rebalance import rebalance_per_zone

PICKLE = "/tmp/west_base.pkl"
ZONE = os.environ.get("DIAG_ZONE", "kansai")
STD_KV = [66, 77, 110, 132, 154, 187, 220, 275, 500]


def largest(net):
    g = top.create_nxgraph(net, respect_switches=False)
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    return pp.select_subnet(net, list(comps[0]), include_results=False) if comps else net


def prep(net):
    net = largest(net)
    if len(net.ext_grid) == 0 and len(net.bus) > 0:
        pp.create_ext_grid(net, bus=int(net.bus["vn_kv"].idxmax()), vm_pu=1.0)
    net.bus["vm_pu"] = 1.0
    if len(net.gen) > 0:
        net.gen["vm_pu"] = 1.0
    return net


def ac(net, label):
    try:
        pp.runpp(net, algorithm="nr", init="dc", max_iteration=100,
                 tolerance_mva=1e-1, numba=True)
        vm = net.res_bus["vm_pu"].dropna()
        return f"  {label:<14}: OK   buses={len(net.bus)} vm=[{vm.min():.3f},{vm.max():.3f}]"
    except Exception as e:
        return f"  {label:<14}: FAIL buses={len(net.bus)} {type(e).__name__}"


def vk_floor(net):
    if len(net.trafo):
        net.trafo["vk_percent"] = net.trafo["vk_percent"].clip(8.0, 25.0)
        net.trafo["vkr_percent"] = net.trafo["vkr_percent"].clip(0.3, 5.0)


def drop_nonstd(net):
    bad = net.bus.index[~net.bus["vn_kv"].round().isin(STD_KV)]
    net.bus.loc[bad, "in_service"] = False


def drop_below(net, kv=66):
    bad = net.bus.index[net.bus["vn_kv"] < kv]
    net.bus.loc[bad, "in_service"] = False


def main():
    if not os.path.exists(PICKLE):
        print("ERROR: no cached base", flush=True)
        return
    with open(PICKLE, "rb") as fh:
        base = pickle.load(fh)
    rebalance_per_zone(base, reserve=0.10)
    kb = base.bus.index[base.bus["zone"] == ZONE].tolist()
    sub = pp.select_subnet(base, kb, include_results=False)

    # transformer condition report
    k = largest(copy.deepcopy(sub))
    tr = k.trafo
    if len(tr):
        ratio = (tr["vn_hv_kv"] / tr["vn_lv_kv"]).replace([np.inf, -np.inf], np.nan)
        print(f"{ZONE}: {len(k.bus)} buses, {len(tr)} trafos | "
              f"vk_percent[min={tr['vk_percent'].min():.2f} max={tr['vk_percent'].max():.2f}] "
              f"ratio[min={ratio.min():.2f} max={ratio.max():.2f}] "
              f"lv_kv set={sorted(set(round(v) for v in tr['vn_lv_kv'].unique()))}", flush=True)
    nonstd = sorted(set(round(v) for v in k.bus['vn_kv'].unique() if round(v) not in STD_KV))
    print(f"  non-standard bus kV present: {nonstd}", flush=True)
    print(f"=== {ZONE} transformer-repair trials ===", flush=True)

    print(ac(prep(copy.deepcopy(sub)), "baseline"), flush=True)
    n = copy.deepcopy(sub); vk_floor(n); print(ac(prep(n), "vk-floor"), flush=True)
    n = copy.deepcopy(sub); drop_nonstd(n); print(ac(prep(n), "drop-nonstd"), flush=True)
    n = copy.deepcopy(sub); drop_below(n, 66); print(ac(prep(n), "drop<66kV"), flush=True)
    n = copy.deepcopy(sub); vk_floor(n); drop_nonstd(n); print(ac(prep(n), "vk+dropnonstd"), flush=True)
    print("DONE_TRAFO", flush=True)


if __name__ == "__main__":
    main()
