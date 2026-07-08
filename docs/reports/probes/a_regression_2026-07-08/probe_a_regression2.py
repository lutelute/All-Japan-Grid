#!/usr/bin/env python3
"""A案回帰プローブ第2弾 — 同一島内zone貼り替えの機構分解 (east, t=12).

第1弾の確定事実: 青函(島構成)もplants dedupも犯人でない。物理トポロジがT0と
完全同一(6205バス・517成分)でも、同一島内の貼り替え(tokyo→tohoku 233 /
tohoku→tokyo 117)があると破綻する。注入の集計(load_scale/clip)は全変種同一
→ 空間配置の変化が犯人。

zone は2箇所で使われる: ①allocate_loads(需要の空間配分) ②inject_dispatch_by_zone
(需要スケール/発電注入のマスク)。本プローブは同一ネットで zone だけ外科的に
差し替えて分解する:

  Z_sanity      loads=旧zone / inject=旧zone   … T0を再現するはず(手法検証)
  Z_loads_new   loads=新zone / inject=旧zone   … 壊れれば需要配分が犯人
  Z_inject_new  loads=旧zone / inject=新zone   … 壊れれば注入マスクが犯人

ビルドは1回(再属性=島跨ぎスキップ版・dedup OFF = T0とトポロジ/発電機完全同一)。
1プロセス・変種ごとにJSON逐次書き出し(BLAS abort耐性)。
  .venv/bin/python probe_a_regression2.py <out.json>
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


def _patch_reattr_skip_cross_island():
    import src.powerflow.region_attribution as ra
    from scripts.run_full_powerflow_from_db import ISLAND_OF

    def reattr_no_cross_island(nodes):
        n_changed = 0
        changes, skipped, skipped_isl = {}, {}, {}
        for n in nodes:
            src = n.get("region")
            if "region_src" not in n:
                n["region_src"] = src
            area = ra.area_of_coord(float(n["lat"]), float(n["lon"]))
            if not area or area == src:
                continue
            if (src in ra.AREA_FREQ and ra.AREA_FREQ.get(area) is not None
                    and ra.AREA_FREQ[src] != ra.AREA_FREQ[area]):
                skipped[f"{src}->{area}"] = skipped.get(f"{src}->{area}", 0) + 1
                continue
            if (ISLAND_OF.get(src, (None,))[0]
                    != ISLAND_OF.get(area, (None,))[0]):
                k = f"{src}->{area}"
                skipped_isl[k] = skipped_isl.get(k, 0) + 1
                continue
            k = f"{src}->{area}"
            changes[k] = changes.get(k, 0) + 1
            n["region"] = area
            n_changed += 1
        return {"n_nodes": len(nodes), "n_changed": n_changed,
                "changes": dict(sorted(changes.items(), key=lambda kv: -kv[1])),
                "skipped_freq": skipped, "skipped_island": skipped_isl}

    ra.reattribute_node_regions = reattr_no_cross_island


def main():
    out_path = sys.argv[1]
    _patch_reattr_skip_cross_island()

    from scripts.run_full_powerflow_from_db import (
        BUILT, add_per_component_slacks, allocate_loads, attach_generators,
        build_island_net)
    from scripts.uc_to_pf_built import _bounded_ac
    from src.powerflow.load_estimator import load_demand_config
    from src.powerflow.transforms import prune_dc_infeasible
    from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot
    from src.uc.scenario import build_national_scenario
    from src.uc.solver import solve_uc

    island, regions, t_probe = "east", ("tohoku", "tokyo"), 12
    report = {"probe": "zone-mechanism-decomposition", "island": island,
              "t": t_probe, "variants": {}}

    t0 = time.monotonic()
    built = json.load(open(BUILT))
    base, bus_of, bstats = build_island_net(
        island, built["nodes"], built["edges"], 50.0, {}, territory=True)
    attach_generators(base, bus_of, built["nodes"], island, territory=False)
    zone_new = base.bus["zone"].copy()
    zone_old = zone_new.copy()
    n_relabel = 0
    for i, b in bus_of.items():
        old = built["nodes"][i].get("region_src") or built["nodes"][i]["region"]
        if zone_old.at[b] != old:
            n_relabel += 1
        zone_old.at[b] = old
    report["build"] = {
        "n_bus": int(len(base.bus)), "n_gen": int(len(base.gen)),
        "gen_cap_mw": round(float(base.gen.max_p_mw.sum()), 1),
        "n_relabel_bus": n_relabel,
        "reattr": bstats.get("region_reattribution"),
        "build_s": round(time.monotonic() - t0, 1)}
    print(f"build {report['build']['build_s']}s bus={len(base.bus)} "
          f"gen={len(base.gen)} relabel_bus={n_relabel}", flush=True)

    print("UC求解中...", flush=True)
    scn = build_national_scenario(scenario="fy2023r2")
    uc = solve_uc(scn.to_uc_parameters())
    report["uc_status"] = uc.status
    if not uc.is_optimal:
        json.dump(report, open(out_path, "w"), ensure_ascii=False, indent=1)
        return 1
    fuel_by_zone = {r: uc_snapshot(uc, scn.generators, t_probe, region=r)
                    for r in regions}
    demand = {r: float(scn.net_demand_r[r][t_probe]) for r in regions}
    cfg = load_demand_config()

    VARIANTS = {
        "Z_sanity":     ("old", "old"),
        "Z_loads_new":  ("new", "old"),
        "Z_inject_new": ("old", "new"),
    }

    def zser(tag):
        return zone_old if tag == "old" else zone_new

    for name, (z_loads, z_inject) in VARIANTS.items():
        print(f"\n== {name} (loads={z_loads} inject={z_inject}) ==", flush=True)
        net = copy.deepcopy(base)
        net.bus["zone"] = zser(z_loads).values
        allocate_loads(net, cfg)
        add_per_component_slacks(net)
        net.bus["zone"] = zser(z_inject).values
        inj = inject_dispatch_by_zone(net, fuel_by_zone, demand)
        vrep = {"z_loads": z_loads, "z_inject": z_inject,
                "injection": {r: {"load_scale": inj[r]["load_scale"],
                                  "clipped": inj[r]["injection"]["clipped"],
                                  "unmatched": inj[r]["injection"]["unmatched"]}
                              for r in regions}}
        pre_load = float(net.load.loc[net.load.in_service, "p_mw"].sum())
        vrep["pre_load_mw"] = round(pre_load, 1)

        rungs, verdict = [], None
        for thr in (None, 45.0, 30.0, 20.0):
            tr = time.monotonic()
            nt = copy.deepcopy(net)
            if thr is not None:
                try:
                    prune_dc_infeasible(nt, angle_threshold=thr)
                except Exception as e:  # noqa: BLE001
                    rungs.append({"thr": thr, "error": f"prune: {e}"})
                    continue
            ok = _bounded_ac(nt)
            rung = {"thr": thr, "converged": bool(ok),
                    "solve_s": round(time.monotonic() - tr, 1)}
            if ok:
                served = float(nt.res_load.p_mw.sum())
                rung["served_frac"] = (round(served / pre_load, 4)
                                       if pre_load else None)
                rung["loss_mw"] = round(float(nt.res_line.pl_mw.sum()
                                              + nt.res_trafo.pl_mw.sum()), 1)
                if pre_load > 0 and served >= 0.95 * pre_load and verdict is None:
                    verdict = {"solver": "ac", "thr": thr,
                               "served_frac": rung["served_frac"],
                               "loss_mw": rung["loss_mw"]}
            rungs.append(rung)
            print(f"  thr={thr} conv={rung['converged']} "
                  f"served={rung.get('served_frac')} "
                  f"loss={rung.get('loss_mw')} {rung['solve_s']}s", flush=True)
            if verdict is not None:
                break
        if verdict is None:
            verdict = {"solver": "dc_fallback"}
        vrep["rungs"] = rungs
        vrep["verdict"] = verdict
        report["variants"][name] = vrep
        json.dump(report, open(out_path, "w"), ensure_ascii=False, indent=1)
        print(f"  VERDICT[{name}]: {verdict}", flush=True)

    print(f"-> {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
