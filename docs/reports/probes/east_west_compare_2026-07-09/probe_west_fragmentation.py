#!/usr/bin/env python3
"""west factor=0.9 AC解の正体 — 主成分の実解か断片化アーティファクトか.

問い: 99.8%給電は「主成分7065バスがちゃんと解けた」からか、それとも
「2531個の小片が各々ローカルslackで釣り合っただけ」か。
成分別に load/gen/slack吸収を分解する。同じ分解を east(0.6)にも当てて比較。
  .venv/bin/python probe_west_fragmentation.py <island> <factor> <out.json>
"""
from __future__ import annotations
import copy, json, os, sys
REPO = "/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid"
sys.path.insert(0, REPO); os.chdir(REPO)


def main():
    island, factor, out_path = sys.argv[1], float(sys.argv[2]), sys.argv[3]
    import pandapower as pp
    import pandapower.topology as ptop
    import networkx as nx
    from scripts.run_full_powerflow_from_db import (
        BUILT, ISLAND_OF, add_per_component_slacks, allocate_loads,
        attach_generators, build_island_net)
    from scripts.uc_to_pf_built import ISLAND_FREQ, _bounded_ac
    from src.powerflow.load_estimator import load_demand_config
    from src.powerflow.pipeline import add_reactive_compensation
    from src.powerflow.pref_demand import pref_zone_gwh
    from src.powerflow.transforms import prune_dc_infeasible
    from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot
    from src.uc.scenario import build_national_scenario
    from src.uc.solver import solve_uc

    regions = tuple(sorted(r for r, (i, _f) in ISLAND_OF.items() if i == island))
    t = 12
    built = json.load(open(BUILT))
    pw, _ = pref_zone_gwh(built["nodes"])
    base, bus_of, _ = build_island_net(island, built["nodes"], built["edges"],
                                       ISLAND_FREQ[island], {})
    attach_generators(base, bus_of, built["nodes"], island)
    allocate_loads(base, load_demand_config(), pref_gwh=pw)
    add_per_component_slacks(base)
    add_reactive_compensation(base, factor=factor)
    scn = build_national_scenario(scenario="fy2023r2")
    uc = solve_uc(scn.to_uc_parameters())
    fbz = {r: uc_snapshot(uc, scn.generators, t, region=r) for r in regions}
    dem = {r: float(scn.net_demand_r[r][t]) for r in regions}
    inject_dispatch_by_zone(base, fbz, dem)
    pre = float(base.load.loc[base.load.in_service, "p_mw"].sum())

    net = None
    for thr in (None, 45.0, 30.0, 20.0):
        n = copy.deepcopy(base)
        if thr is not None:
            try: prune_dc_infeasible(n, angle_threshold=thr)
            except Exception: pass
        if _bounded_ac(n):
            if n.res_load.p_mw.sum() >= 0.95 * pre:
                net = n; used = thr; break
    if net is None:
        json.dump({"island": island, "factor": factor, "no_ac": True},
                  open(out_path, "w")); print("no AC"); return 1

    # 成分分解
    g = ptop.create_nxgraph(net, respect_switches=False,
                            include_out_of_service=False)
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    bus2comp = {b: i for i, c in enumerate(comps) for b in c}
    load_by_c, slack_by_c = {}, {}
    for _, r in net.res_load.iterrows():
        pass
    # load per component
    for li in net.load.index:
        if not net.load.at[li, "in_service"]: continue
        b = int(net.load.at[li, "bus"]); ci = bus2comp.get(b)
        p = float(net.res_load.at[li, "p_mw"]) if li in net.res_load.index else 0.0
        load_by_c[ci] = load_by_c.get(ci, 0.0) + p
    for ei in net.ext_grid.index:
        b = int(net.ext_grid.at[ei, "bus"]); ci = bus2comp.get(b)
        p = float(net.res_ext_grid.at[ei, "p_mw"]) if ei in net.res_ext_grid.index else 0.0
        slack_by_c[ci] = slack_by_c.get(ci, 0.0) + p

    total_load = sum(load_by_c.values())
    total_slack_abs = sum(abs(v) for v in slack_by_c.values())
    main_load = load_by_c.get(0, 0.0)
    # 各成分の |slack|/load 比(局所自給度の逆)
    frag_load = total_load - main_load
    rep = {"island": island, "factor": factor, "used_thr": used,
           "n_comp": len(comps), "main_comp_bus": len(comps[0]),
           "n_bus": int(len(net.bus)),
           "total_load_mw": round(total_load, 1),
           "main_comp_load_mw": round(main_load, 1),
           "main_comp_load_frac": round(main_load / total_load, 4) if total_load else None,
           "fragment_load_mw": round(frag_load, 1),
           "n_slack": int(len(net.ext_grid)),
           "total_slack_abs_mw": round(total_slack_abs, 1),
           "slack_abs_frac_of_load": round(total_slack_abs / total_load, 4) if total_load else None,
           "loss_mw": round(float(net.res_line.pl_mw.sum()
                                  + net.res_trafo.pl_mw.sum()), 1)}
    json.dump(rep, open(out_path, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
