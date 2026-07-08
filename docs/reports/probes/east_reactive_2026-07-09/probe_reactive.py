#!/usr/bin/env python3
"""east full AC = 無効電力仮説の検証 — シャント補償率を振ってAC収束を測る.

診断(diag_east)で判明: DC角度は健全(prune 0本)なのにAC発散 → 電圧崩壊/無効不足。
既存 add_reactive_compensation(負荷バスへ容量性シャント)を正典built経路に適用し、
補償率factor∈{0,0.3,0.6,0.9}でAC収束・給電率・電圧・損失を測る。
prune ladderは正典と同じ(None→45→30→20)。給電率ガード95%。
  .venv/bin/python probe_reactive.py <island> <out.json>
"""
from __future__ import annotations

import copy
import json
import os
import sys
import time

REPO = "/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid"
sys.path.insert(0, REPO)
os.chdir(REPO)


def main():
    island, out_path = sys.argv[1], sys.argv[2]
    import pandapower as pp

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

    regions = tuple(sorted(r for r, (isl, _f) in ISLAND_OF.items()
                           if isl == island))
    t = 12
    rep = {"probe": "reactive-compensation", "island": island, "t": t,
           "config": "A案+pref-demand(誠実な需要地理)、シャント補償率を振る"}

    t0 = time.monotonic()
    built = json.load(open(BUILT))
    pw, _ = pref_zone_gwh(built["nodes"])
    base, bus_of, _ = build_island_net(
        island, built["nodes"], built["edges"], ISLAND_FREQ[island], {})
    attach_generators(base, bus_of, built["nodes"], island)
    allocate_loads(base, load_demand_config(), pref_gwh=pw)
    add_per_component_slacks(base)
    scn = build_national_scenario(scenario="fy2023r2")
    uc = solve_uc(scn.to_uc_parameters())
    fbz = {r: uc_snapshot(uc, scn.generators, t, region=r) for r in regions}
    dem = {r: float(scn.net_demand_r[r][t]) for r in regions}
    net_base = copy.deepcopy(base)
    inject_dispatch_by_zone(net_base, fbz, dem)
    pre_load = float(net_base.load.loc[net_base.load.in_service, "p_mw"].sum())
    q_load = float(net_base.load.loc[net_base.load.in_service, "q_mvar"].sum())
    rep["pre_load_mw"] = round(pre_load, 1)
    rep["q_load_mvar"] = round(q_load, 1)
    print(f"build {round(time.monotonic()-t0,1)}s pre_load={pre_load:,.0f}MW "
          f"q_load={q_load:,.0f}MVar", flush=True)

    def solve_with_ladder(net):
        for thr in (None, 45.0, 30.0, 20.0):
            n = copy.deepcopy(net)
            if thr is not None:
                try:
                    prune_dc_infeasible(n, angle_threshold=thr)
                except Exception:
                    pass
            if _bounded_ac(n):
                served = float(n.res_load.p_mw.sum())
                if pre_load <= 0 or served >= 0.95 * pre_load:
                    return {"solver": "ac", "thr": thr,
                            "served_frac": round(served / pre_load, 4),
                            "loss_mw": round(float(n.res_line.pl_mw.sum()
                                                   + n.res_trafo.pl_mw.sum()), 1),
                            "vm_min": round(float(n.res_bus.vm_pu.min()), 4),
                            "vm_max": round(float(n.res_bus.vm_pu.max()), 4),
                            "n_shunt": int(len(n.shunt))}
        return {"solver": "dc_fallback"}

    variants = []
    for factor in (0.0, 0.3, 0.6, 0.9):
        net = copy.deepcopy(net_base)
        n_shunt = add_reactive_compensation(net, factor=factor) if factor > 0 else 0
        q_comp = float(-net.shunt.q_mvar.sum()) if len(net.shunt) else 0.0
        tr = time.monotonic()
        v = solve_with_ladder(net)
        v.update({"factor": factor, "n_shunt": n_shunt,
                  "q_comp_mvar": round(q_comp, 1),
                  "solve_s": round(time.monotonic() - tr, 1)})
        variants.append(v)
        print(f"factor={factor}: shunt={n_shunt} q_comp={q_comp:,.0f}MVar "
              f"-> {v['solver']} thr={v.get('thr')} "
              f"served={v.get('served_frac')} vm=[{v.get('vm_min')},"
              f"{v.get('vm_max')}] loss={v.get('loss_mw')} {v['solve_s']}s",
              flush=True)
        rep["variants"] = variants
        json.dump(rep, open(out_path, "w"), ensure_ascii=False, indent=1)

    print(f"-> {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
