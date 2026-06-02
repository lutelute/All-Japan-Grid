#!/usr/bin/env python3
"""Localise WHY kansai still fails AC after per-zone re-balance.

kansai has P_gen>P_load after re-balance yet nr/dc fails. This isolates the
cause by toggling one thing at a time on the kansai largest component:

  baseline   nr/dc                       (confirm FAIL)
  gs         Gauss-Seidel, 3000 it       (robust solver -> is it just NR Jacobian?)
  flat       nr/flat init                (bad dc-init?)
  no-trafo   disable transformers        (ill-conditioned trafo?)
  fuse0.5    fuse <0.5km lines           (near-zero-Z branches?)
  hv>=154    drop buses below 154 kV     (low-voltage distribution tail?)
  half-load  load x0.5                   (loadability margin?)
  qlim-off   enforce_q_lims=False        (gen Q-limit oscillation?)

Loads cached base from /tmp/west_base.pkl.

Usage::
    PYTHONPATH=. python scripts/test_kansai_diag.py
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

from scripts.test_west_rebalance import rebalance_per_zone
from scripts.test_west_fuse import fuse_short_lines

PICKLE = "/tmp/west_base.pkl"
ZONE = os.environ.get("DIAG_ZONE", "kansai")


def largest_comp(net):
    g = top.create_nxgraph(net, respect_switches=False)
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    return pp.select_subnet(net, list(comps[0]), include_results=False) if comps else net


def prep(net):
    if len(net.ext_grid) == 0 and len(net.bus) > 0:
        hv = net.bus["vn_kv"].idxmax()
        pp.create_ext_grid(net, bus=int(hv), vm_pu=1.0)
    net.bus["vm_pu"] = 1.0
    if len(net.gen) > 0:
        net.gen["vm_pu"] = 1.0
    return net


def tr(net, label, **kw):
    kw.setdefault("numba", True)
    try:
        pp.runpp(net, **kw)
        vm = net.res_bus["vm_pu"].dropna()
        return f"  {label:<12}: OK   vm=[{vm.min():.3f},{vm.max():.3f}] iters~{net._ppc['iterations'] if '_ppc' in dir(net) and net._ppc else '?'}"
    except Exception as e:
        return f"  {label:<12}: FAIL {type(e).__name__}: {str(e)[:45]}"


def main():
    if not os.path.exists(PICKLE):
        print("ERROR: no cached base", flush=True)
        return
    with open(PICKLE, "rb") as fh:
        base = pickle.load(fh)
    rebalance_per_zone(base, reserve=0.10)
    kb = base.bus.index[base.bus["zone"] == ZONE].tolist()
    sub = pp.select_subnet(base, kb, include_results=False)
    k = largest_comp(sub)
    print(f"{ZONE} largest comp: {len(k.bus)} buses, {len(k.line)} lines, "
          f"{len(k.trafo)} trafos, {len(k.gen)} gens, "
          f"vn_kv in {sorted(set(round(v) for v in k.bus['vn_kv'].unique()))}", flush=True)
    print(f"=== {ZONE} AC diagnostics (one toggle each) ===", flush=True)

    n = prep(copy.deepcopy(k)); print(tr(n, "baseline", algorithm="nr", init="dc", max_iteration=100, tolerance_mva=1e-1), flush=True)
    n = prep(copy.deepcopy(k)); print(tr(n, "gs", algorithm="gs", max_iteration=3000, tolerance_mva=1e-1), flush=True)
    n = prep(copy.deepcopy(k)); print(tr(n, "flat", algorithm="nr", init="flat", max_iteration=100, tolerance_mva=1e-1), flush=True)
    n = copy.deepcopy(k); n.trafo["in_service"] = False; n = prep(largest_comp(n)); print(tr(n, "no-trafo", algorithm="nr", init="dc", max_iteration=100, tolerance_mva=1e-1), flush=True)
    n = copy.deepcopy(k); fuse_short_lines(n, 0.5); n = prep(largest_comp(n)); print(tr(n, "fuse0.5", algorithm="nr", init="dc", max_iteration=100, tolerance_mva=1e-1), flush=True)
    n = copy.deepcopy(k); lowb = n.bus.index[n.bus["vn_kv"] < 154]; n.bus.loc[lowb, "in_service"] = False; n = prep(largest_comp(n)); print(tr(n, "hv>=154", algorithm="nr", init="dc", max_iteration=100, tolerance_mva=1e-1), flush=True)
    n = copy.deepcopy(k); n.load["p_mw"] *= 0.5; n.load["q_mvar"] *= 0.5; n = prep(n); print(tr(n, "half-load", algorithm="nr", init="dc", max_iteration=100, tolerance_mva=1e-1), flush=True)
    n = prep(copy.deepcopy(k)); print(tr(n, "qlim-off", algorithm="nr", init="dc", max_iteration=100, tolerance_mva=1e-1, enforce_q_lims=False), flush=True)
    print("DONE_DIAG", flush=True)


if __name__ == "__main__":
    main()
