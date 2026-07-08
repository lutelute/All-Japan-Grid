#!/usr/bin/env python3
"""県別需要配分の検証プローブ — A案(territory=True既定)+pref_demandで
east full AC が回復するかを判定する(t=12, fy2023r2, 正典と同じprune ladder+ガード)。

  .venv/bin/python probe_pref_demand.py <island> <out.json>
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
    from scripts.run_full_powerflow_from_db import (
        BUILT, ISLAND_OF, add_per_component_slacks, allocate_loads,
        attach_generators, build_island_net)
    from scripts.uc_to_pf_built import ISLAND_FREQ, _bounded_ac
    from src.powerflow.load_estimator import load_demand_config
    from src.powerflow.pref_demand import pref_zone_gwh
    from src.powerflow.transforms import prune_dc_infeasible
    from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot
    from src.uc.scenario import build_national_scenario
    from src.uc.solver import solve_uc

    regions = tuple(sorted(r for r, (isl, _f) in ISLAND_OF.items()
                           if isl == island))
    t_probe = 12
    rep = {"probe": "pref-demand-recovery", "island": island, "t": t_probe,
           "config": "territory=True(既定)+dedup ON(既定)+pref_demand"}

    t0 = time.monotonic()
    built = json.load(open(BUILT))
    pw, pw_ledger = pref_zone_gwh(built["nodes"])
    rep["pref_weights"] = {"n_pref": pw_ledger["n_pref_weighted"],
                           "split_prefs": pw_ledger["split_prefs"],
                           "source": pw_ledger["source"]}
    base, bus_of, bstats = build_island_net(
        island, built["nodes"], built["edges"], ISLAND_FREQ[island], {})
    attach_generators(base, bus_of, built["nodes"], island)
    allocate_loads(base, load_demand_config(), pref_gwh=pw)
    add_per_component_slacks(base)
    led = getattr(base, "_pref_demand_ledger", None)
    rep["build"] = {"n_bus": int(len(base.bus)),
                    "n_gen": int(len(base.gen)),
                    "load_mw": round(float(base.load.p_mw.sum()), 1),
                    "build_s": round(time.monotonic() - t0, 1),
                    "ledger_zones": {z: {p: v for p, v in
                                         sorted(zl.items(),
                                                key=lambda kv: -kv[1]["target_mw"])[:6]}
                                     for z, zl in (led or {}).get("zones", {}).items()}}
    print(f"[{island}] build {rep['build']['build_s']}s "
          f"bus={rep['build']['n_bus']} load={rep['build']['load_mw']:,.0f}MW",
          flush=True)

    print(f"[{island}] UC求解中...", flush=True)
    scn = build_national_scenario(scenario="fy2023r2")
    uc = solve_uc(scn.to_uc_parameters())
    rep["uc_status"] = uc.status
    if not uc.is_optimal:
        json.dump(rep, open(out_path, "w"), ensure_ascii=False, indent=1)
        return 1

    net_t = copy.deepcopy(base)
    fuel_by_zone = {r: uc_snapshot(uc, scn.generators, t_probe, region=r)
                    for r in regions}
    demand = {r: float(scn.net_demand_r[r][t_probe]) for r in regions}
    inj = inject_dispatch_by_zone(net_t, fuel_by_zone, demand)
    rep["injection"] = {r: {"load_scale": inj[r]["load_scale"],
                            "clipped": inj[r]["injection"]["clipped"],
                            "unmatched": inj[r]["injection"]["unmatched"]}
                        for r in regions}
    pre_load = float(net_t.load.loc[net_t.load.in_service, "p_mw"].sum())
    rep["pre_load_mw"] = round(pre_load, 1)

    rungs, verdict = [], None
    for thr in (None, 45.0, 30.0, 20.0):
        tr = time.monotonic()
        net = copy.deepcopy(net_t)
        if thr is not None:
            try:
                prune_dc_infeasible(net, angle_threshold=thr)
            except Exception as e:  # noqa: BLE001
                rungs.append({"thr": thr, "error": f"prune: {e}"})
                continue
        ok = _bounded_ac(net)
        rung = {"thr": thr, "converged": bool(ok),
                "solve_s": round(time.monotonic() - tr, 1)}
        if ok:
            served = float(net.res_load.p_mw.sum())
            rung["served_frac"] = (round(served / pre_load, 4)
                                   if pre_load else None)
            rung["loss_mw"] = round(float(net.res_line.pl_mw.sum()
                                          + net.res_trafo.pl_mw.sum()), 1)
            rung["vm_min"] = round(float(net.res_bus.vm_pu.min()), 4)
            rung["vm_max"] = round(float(net.res_bus.vm_pu.max()), 4)
            if pre_load > 0 and served >= 0.95 * pre_load and verdict is None:
                verdict = {"solver": "ac", "thr": thr,
                           "served_frac": rung["served_frac"],
                           "loss_mw": rung["loss_mw"]}
        rungs.append(rung)
        print(f"[{island}] thr={thr} conv={rung['converged']} "
              f"served={rung.get('served_frac')} loss={rung.get('loss_mw')} "
              f"{rung['solve_s']}s", flush=True)
        if verdict is not None:
            break
    if verdict is None:
        verdict = {"solver": "dc_fallback"}
    rep["rungs"] = rungs
    rep["verdict"] = verdict
    json.dump(rep, open(out_path, "w"), ensure_ascii=False, indent=1)
    print(f"[{island}] VERDICT: {verdict}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
