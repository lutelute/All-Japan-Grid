#!/usr/bin/env python3
"""east full AC非収束の網側診断 — 正しい需要地理(A案+pref-demand)で何が壊れるか.

問い: pruneが刈る線はどの電圧階級か? 角度差の分布は? 66kV網が主犯か?
出力: DC角度差の階級別分布・pruneが刈る線の階級別内訳・各prune段の連結性推移。
  .venv/bin/python diag_east_network.py <out.json>
"""
from __future__ import annotations

import copy
import json
import os
import sys
import time
from collections import Counter

REPO = "/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid"
sys.path.insert(0, REPO)
os.chdir(REPO)


def main():
    island = sys.argv[1]
    out_path = sys.argv[2]
    import numpy as np
    import pandapower as pp
    import pandapower.topology as ptop
    import networkx as nx

    from scripts.run_full_powerflow_from_db import (
        BUILT, ISLAND_OF, add_per_component_slacks, allocate_loads,
        attach_generators, build_island_net)
    from scripts.uc_to_pf_built import ISLAND_FREQ, _bounded_ac
    from src.powerflow.load_estimator import load_demand_config
    from src.powerflow.pref_demand import pref_zone_gwh
    from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot
    from src.uc.scenario import build_national_scenario
    from src.uc.solver import solve_uc

    regions = tuple(sorted(r for r, (isl, _f) in ISLAND_OF.items()
                           if isl == island))
    from scripts.uc_to_pf_built import ISLAND_FREQ as _IF
    freq = _IF[island]
    t = 12
    rep = {"probe": "east-network-bottleneck", "t": t,
           "config": "A案(territory=True)+pref-demand(誠実な需要地理)"}

    t0 = time.monotonic()
    built = json.load(open(BUILT))
    pw, _ = pref_zone_gwh(built["nodes"])
    base, bus_of, bstats = build_island_net(
        island, built["nodes"], built["edges"], freq, {})
    attach_generators(base, bus_of, built["nodes"], island)
    allocate_loads(base, load_demand_config(), pref_gwh=pw)
    add_per_component_slacks(base)

    def kv_of_line(li):
        return int(round(float(base.bus.at[int(base.line.at[li, "from_bus"]),
                                            "vn_kv"])))

    # 線路の階級別本数
    line_kv = Counter(kv_of_line(li) for li in base.line.index)
    rep["line_kv_hist"] = dict(sorted(line_kv.items()))
    rep["n_bus"] = int(len(base.bus))
    rep["n_line"] = int(len(base.line))
    rep["n_trafo"] = int(len(base.trafo))
    rep["build_s"] = round(time.monotonic() - t0, 1)
    print(f"build {rep['build_s']}s bus={rep['n_bus']} line={rep['n_line']} "
          f"line_kv={rep['line_kv_hist']}", flush=True)

    # UC注入
    scn = build_national_scenario(scenario="fy2023r2")
    uc = solve_uc(scn.to_uc_parameters())
    fbz = {r: uc_snapshot(uc, scn.generators, t, region=r) for r in regions}
    dem = {r: float(scn.net_demand_r[r][t]) for r in regions}
    net_t = copy.deepcopy(base)
    inject_dispatch_by_zone(net_t, fbz, dem)
    pre_load = float(net_t.load.loc[net_t.load.in_service, "p_mw"].sum())
    rep["pre_load_mw"] = round(pre_load, 1)

    # --- DC角度差の階級別分布 ---
    net_dc = copy.deepcopy(net_t)
    pp.rundcpp(net_dc)
    va = net_dc.res_bus["va_degree"]
    ang = {}
    for li in net_dc.line.index:
        if not net_dc.line.at[li, "in_service"]:
            continue
        d = abs(float(va.at[int(net_dc.line.at[li, "from_bus"])])
                - float(va.at[int(net_dc.line.at[li, "to_bus"])]))
        ang.setdefault(kv_of_line(li), []).append(d)
    rep["dc_angle_by_kv"] = {
        kv: {"n": len(v), "p50": round(float(np.percentile(v, 50)), 1),
             "p95": round(float(np.percentile(v, 95)), 1),
             "max": round(float(np.max(v)), 1),
             "n_over_45": int(sum(1 for x in v if x > 45)),
             "n_over_90": int(sum(1 for x in v if x > 90))}
        for kv, v in sorted(ang.items())}
    print("DC角度差(階級別):", flush=True)
    for kv, s in rep["dc_angle_by_kv"].items():
        print(f"  {kv}kV: n={s['n']} p95={s['p95']}° max={s['max']}° "
              f">45°={s['n_over_45']} >90°={s['n_over_90']}", flush=True)

    # --- prune ladderで刈られる線の階級別内訳(段ごと) ---
    from src.powerflow.transforms import prune_dc_infeasible
    rungs = []
    for thr in (45.0, 30.0, 20.0):
        net = copy.deepcopy(net_t)
        before_off = set(net.line.index[~net.line.in_service])
        prune_dc_infeasible(net, angle_threshold=thr)
        after_off = set(net.line.index[~net.line.in_service])
        pruned = after_off - before_off
        pruned_kv = Counter(kv_of_line(li) for li in pruned)
        g = ptop.create_nxgraph(net, respect_switches=False,
                                include_out_of_service=False)
        comps = sorted(nx.connected_components(g), key=len, reverse=True)
        ok = _bounded_ac(net)
        served = (float(net.res_load.p_mw.sum()) if ok else None)
        rung = {"thr": thr, "n_pruned": len(pruned),
                "pruned_kv": dict(sorted(pruned_kv.items())),
                "n_comp": len(comps), "main_comp": len(comps[0]) if comps else 0,
                "ac_converged": bool(ok),
                "served_frac": (round(served / pre_load, 4)
                                if served is not None and pre_load else None)}
        rungs.append(rung)
        print(f"thr={thr}: 刈={len(pruned)}本 {dict(sorted(pruned_kv.items()))} "
              f"comp={len(comps)}(main {rung['main_comp']}) "
              f"AC={ok} served={rung['served_frac']}", flush=True)
    rep["prune_ladder"] = rungs

    json.dump(rep, open(out_path, "w"), ensure_ascii=False, indent=1)
    print(f"-> {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
