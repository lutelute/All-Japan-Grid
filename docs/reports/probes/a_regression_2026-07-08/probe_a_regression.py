#!/usr/bin/env python3
"""A案回帰の切り分けプローブ — east full AC (t=12, fy2023r2注入).

territory=True が east 全規模AC を壊す(07-07プローブ: False→thr45で99.0%給電AC /
True→10.8%見せかけ)原因を、A案の2成分を独立に切って特定する:

  T0          build(territory=False) + attach(territory=False)   … 旧挙動(良基準)
  T1          build(True)            + attach(True)               … A案(悪基準)
  T1_nodedup  build(True)            + attach(False)              … 再属性のみ(dedup切)
  T1_noseikan build(True/島跨ぎskip) + attach(True)               … 青函除外(dedup生き)

判定: T1_nodedup が回復→dedupが犯人 / T1_noseikan が回復→青函が犯人。
計器: prune ladder 各段の (converged, served_frac, loss) を全記録(ハマり⑩対応)。
実行: 1変種=1プロセス(ハマり⑨ BLAS abort隔離)。
  .venv/bin/python probe_a_regression.py <variant> <out.json>
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

VARIANTS = ("T0", "T1", "T1_nodedup", "T1_noseikan")


def _patch_reattr_skip_cross_island():
    """reattribute_node_regions を「島を跨ぐ移動(青函=hokkaido↔tohoku)だけ
    スキップする」版に差し替える。ロジックは原本(region_attribution.py)の写しに
    島跨ぎガードを1条件足したもの。"""
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
                key = f"{src}->{area}"
                skipped[key] = skipped.get(key, 0) + 1
                continue
            # ★ 追加ガード: 同期島を跨ぐ移動(青函)はスキップ
            if (ISLAND_OF.get(src, (None,))[0]
                    != ISLAND_OF.get(area, (None,))[0]):
                key = f"{src}->{area}"
                skipped_isl[key] = skipped_isl.get(key, 0) + 1
                continue
            key = f"{src}->{area}"
            changes[key] = changes.get(key, 0) + 1
            n["region"] = area
            n_changed += 1
        return {"n_nodes": len(nodes), "n_changed": n_changed,
                "changes": dict(sorted(changes.items(), key=lambda kv: -kv[1])),
                "skipped_freq": skipped,
                "skipped_island": skipped_isl}

    ra.reattribute_node_regions = reattr_no_cross_island


def main():
    variant, out_path = sys.argv[1], sys.argv[2]
    assert variant in VARIANTS, variant

    if variant == "T1_noseikan":
        _patch_reattr_skip_cross_island()

    build_territory = (variant != "T0")
    attach_territory = variant in ("T1", "T1_noseikan")

    from scripts.run_full_powerflow_from_db import (
        add_per_component_slacks, allocate_loads, attach_generators,
        build_island_net, BUILT)
    from scripts.uc_to_pf_built import _bounded_ac
    from src.powerflow.load_estimator import load_demand_config
    from src.powerflow.transforms import prune_dc_infeasible
    from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot
    from src.uc.scenario import build_national_scenario
    from src.uc.solver import solve_uc

    import networkx as nx
    import pandapower as pp
    import pandapower.topology as ptop

    island, regions, t_probe = "east", ("tohoku", "tokyo"), 12
    rep = {"variant": variant,
           "build_territory": build_territory,
           "attach_territory(dedup)": attach_territory,
           "island": island, "t": t_probe, "scenario": "fy2023r2"}

    t0 = time.monotonic()
    built = json.load(open(BUILT))
    base, bus_of, bstats = build_island_net(
        island, built["nodes"], built["edges"], 50.0, {},
        territory=build_territory)
    n_gen = attach_generators(base, bus_of, built["nodes"], island,
                              territory=attach_territory)
    allocate_loads(base, load_demand_config())
    add_per_component_slacks(base)
    rep["build_s"] = round(time.monotonic() - t0, 1)
    rs = bstats.get("region_reattribution") or {}
    rep["build"] = {
        "n_bus": int(len(base.bus)), "n_line": int(len(base.line)),
        "n_trafo": int(len(base.trafo)), "n_gen": int(n_gen),
        "gen_cap_mw": round(float(base.gen.max_p_mw.sum()), 1),
        "load_mw": round(float(base.load.p_mw.sum()), 1),
        "n_slack": int(len(base.ext_grid)),
        "reattr_changes": rs.get("changes"),
        "reattr_skipped_island": rs.get("skipped_island"),
    }
    # 主成分と発電容量の分布(構造変化の計器)
    g = ptop.create_nxgraph(base, respect_switches=False,
                            include_out_of_service=False)
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    main_comp = comps[0] if comps else set()
    gen_in_main = base.gen[base.gen.bus.isin(main_comp)]
    rep["build"]["n_components"] = len(comps)
    rep["build"]["main_comp_bus"] = len(main_comp)
    rep["build"]["gen_cap_in_main_mw"] = round(
        float(gen_in_main.max_p_mw.sum()), 1)

    print(f"[{variant}] build {rep['build_s']}s bus={rep['build']['n_bus']} "
          f"gen={n_gen}({rep['build']['gen_cap_mw']:,.0f}MW, "
          f"main={rep['build']['gen_cap_in_main_mw']:,.0f}MW) "
          f"comp={len(comps)}(main {len(main_comp)})", flush=True)

    print(f"[{variant}] UC求解中...", flush=True)
    scn = build_national_scenario(scenario="fy2023r2")
    uc = solve_uc(scn.to_uc_parameters())
    rep["uc_status"] = uc.status
    if not uc.is_optimal:
        json.dump(rep, open(out_path, "w"), ensure_ascii=False, indent=1)
        print(f"[{variant}] UC not optimal — 中止", flush=True)
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

    # 計器付き prune ladder(solve_hour と同じ閾値列・有界ACチェーン)
    rungs = []
    verdict = None
    for thr in (None, 45.0, 30.0, 20.0):
        tr = time.monotonic()
        net = copy.deepcopy(net_t)
        if thr is not None:
            try:
                prune_dc_infeasible(net, angle_threshold=thr)
            except Exception as e:  # noqa: BLE001
                rungs.append({"thr": thr, "error": f"prune: {e}"})
                continue
        n_off = int((~net.line.in_service).sum()) if len(net.line) else 0
        ok = _bounded_ac(net)
        rung = {"thr": thr, "n_line_off": n_off, "converged": bool(ok),
                "solve_s": round(time.monotonic() - tr, 1)}
        if ok:
            served = float(net.res_load.p_mw.sum())
            rung["served_mw"] = round(served, 1)
            rung["served_frac"] = round(served / pre_load, 4) if pre_load else None
            rung["loss_mw"] = round(float(net.res_line.pl_mw.sum()
                                          + net.res_trafo.pl_mw.sum()), 1)
            rung["slack_abs_mw"] = round(float(net.res_ext_grid.p_mw.sum()), 1)
            if pre_load > 0 and served >= 0.95 * pre_load and verdict is None:
                verdict = {"solver": "ac", "thr": thr,
                           "served_frac": rung["served_frac"],
                           "loss_mw": rung["loss_mw"]}
        rungs.append(rung)
        print(f"[{variant}] thr={thr} conv={rung['converged']} "
              f"served={rung.get('served_frac')} loss={rung.get('loss_mw')} "
              f"{rung['solve_s']}s", flush=True)
        if verdict is not None:
            break  # solve_hour と同じ: 最初の正当なAC解で確定
    if verdict is None:
        verdict = {"solver": "dc_fallback"}
    rep["rungs"] = rungs
    rep["verdict"] = verdict

    json.dump(rep, open(out_path, "w"), ensure_ascii=False, indent=1)
    print(f"[{variant}] VERDICT: {verdict}", flush=True)
    print(f"-> {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
