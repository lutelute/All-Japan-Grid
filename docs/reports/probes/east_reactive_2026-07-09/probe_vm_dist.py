#!/usr/bin/env python3
"""east full + 無効補償(factor=0.6) の電圧分布と過電圧バスの正体を特定する.

問い: vm_max≈1.7 は何バスか? 局所か広域か? どの階級か? 主成分か断片か?
  .venv/bin/python probe_vm_dist.py <out.json>
"""
from __future__ import annotations

import copy
import json
import os
import sys

REPO = "/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid"
sys.path.insert(0, REPO)
os.chdir(REPO)


def main():
    out_path = sys.argv[1]
    import numpy as np
    import pandapower as pp
    import pandapower.topology as ptop
    import networkx as nx

    from scripts.run_full_powerflow_from_db import (
        BUILT, ISLAND_OF, add_per_component_slacks, allocate_loads,
        attach_generators, build_island_net)
    from scripts.uc_to_pf_built import _bounded_ac
    from src.powerflow.load_estimator import load_demand_config
    from src.powerflow.pipeline import add_reactive_compensation
    from src.powerflow.pref_demand import pref_zone_gwh
    from src.powerflow.transforms import prune_dc_infeasible
    from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot
    from src.uc.scenario import build_national_scenario
    from src.uc.solver import solve_uc

    regions, t = ("tohoku", "tokyo"), 12
    built = json.load(open(BUILT))
    pw, _ = pref_zone_gwh(built["nodes"])
    base, bus_of, _ = build_island_net("east", built["nodes"], built["edges"],
                                       50.0, {})
    attach_generators(base, bus_of, built["nodes"], "east")
    allocate_loads(base, load_demand_config(), pref_gwh=pw)
    add_per_component_slacks(base)
    scn = build_national_scenario(scenario="fy2023r2")
    uc = solve_uc(scn.to_uc_parameters())
    fbz = {r: uc_snapshot(uc, scn.generators, t, region=r) for r in regions}
    dem = {r: float(scn.net_demand_r[r][t]) for r in regions}
    inject_dispatch_by_zone(base, fbz, dem)
    add_reactive_compensation(base, factor=0.6)

    net = None
    for thr in (None, 45.0, 30.0, 20.0):
        n = copy.deepcopy(base)
        if thr is not None:
            try:
                prune_dc_infeasible(n, angle_threshold=thr)
            except Exception:
                pass
        if _bounded_ac(n):
            served = float(n.res_load.p_mw.sum())
            pre = float(base.load.loc[base.load.in_service, "p_mw"].sum())
            if served >= 0.95 * pre:
                net = n
                used_thr = thr
                break
    if net is None:
        json.dump({"error": "no AC"}, open(out_path, "w"))
        print("no AC", flush=True)
        return 1

    vm = net.res_bus.vm_pu
    bins = {"<0.85": int((vm < 0.85).sum()),
            "0.85-0.95": int(((vm >= 0.85) & (vm < 0.95)).sum()),
            "0.95-1.05": int(((vm >= 0.95) & (vm <= 1.05)).sum()),
            "1.05-1.10": int(((vm > 1.05) & (vm <= 1.10)).sum()),
            ">1.10": int((vm > 1.10).sum())}
    rep = {"thr": used_thr, "n_bus": int(len(vm)),
           "vm_min": round(float(vm.min()), 4),
           "vm_max": round(float(vm.max()), 4),
           "vm_p05": round(float(np.percentile(vm, 5)), 4),
           "vm_p50": round(float(np.percentile(vm, 50)), 4),
           "vm_p95": round(float(np.percentile(vm, 95)), 4),
           "in_band_0.9_1.1_frac": round(float(((vm >= 0.9) & (vm <= 1.1)).mean()), 4),
           "vm_bins": bins}

    # 過電圧バス(>1.1)の正体
    g = ptop.create_nxgraph(net, respect_switches=False,
                            include_out_of_service=False)
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    main_comp = comps[0] if comps else set()
    gen_bus = set(net.gen.bus)
    over = vm.index[vm > 1.10]
    ov_info = {"n": int(len(over)),
               "in_main_comp": int(sum(1 for b in over if b in main_comp)),
               "has_gen": int(sum(1 for b in over if b in gen_bus)),
               "kv_hist": {}}
    from collections import Counter
    ov_info["kv_hist"] = dict(sorted(Counter(
        int(round(float(net.bus.at[b, "vn_kv"]))) for b in over).items()))
    under = vm.index[vm < 0.85]
    un_info = {"n": int(len(under)),
               "in_main_comp": int(sum(1 for b in under if b in main_comp)),
               "kv_hist": dict(sorted(Counter(
                   int(round(float(net.bus.at[b, "vn_kv"]))) for b in under).items()))}
    rep["overvoltage_gt_1.10"] = ov_info
    rep["undervoltage_lt_0.85"] = un_info
    rep["n_comp"] = len(comps)
    rep["main_comp_bus"] = len(main_comp)

    json.dump(rep, open(out_path, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(rep, ensure_ascii=False, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
