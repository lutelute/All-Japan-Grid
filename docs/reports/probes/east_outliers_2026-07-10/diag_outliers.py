#!/usr/bin/env python3
"""east 電圧外れ値バスの構造診断 — 正典経路(run_full)と同一のbuild+solveで外れ値を抽出し、
各バスの構造属性(成分・degree・負荷/シャント/発電・線充電・変圧器/電源への距離)をダンプする。

Usage: PYTHONPATH=. .venv/bin/python docs/reports/probes/east_outliers_2026-07-10/diag_outliers.py out.json
プロセス隔離(1ラン=1プロセス)・生JSON保存の家訓に従う。判定はJSONを読む側で行う。
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

import networkx as nx

from scripts.run_full_powerflow_from_db import (
    BUILT, ISLAND_FREQ, add_per_component_slacks, allocate_loads,
    attach_generators, balance_by_zone, build_island_net, load_demand_config,
    solve_island)

OVER, UNDER = 1.10, 0.85


def main():
    out_path = sys.argv[1]
    island = "east"
    site_trafos = "--site-trafos" in sys.argv
    deenergize = "--deenergize-unbuilt" in sys.argv

    db = json.load(open(BUILT))
    nodes, edges = db["nodes"], db["edges"]
    cfg = load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(nodes)

    geom = {}
    net, bus_of, bstats = build_island_net(island, nodes, edges,
                                           ISLAND_FREQ[island], geom,
                                           site_trafos=site_trafos,
                                           deenergize_unbuilt=deenergize)
    attach_generators(net, bus_of, nodes, island)
    allocate_loads(net, cfg, pref_gwh=pref_gwh)
    from src.powerflow.pipeline import add_reactive_compensation
    rfac = cfg.get("reactive_compensation_factor", 0.6)
    n_shunt = add_reactive_compensation(net, factor=rfac)
    add_per_component_slacks(net)
    balance_by_zone(net, cfg)
    net_dc, dc, net_ac, ac = solve_island(net, max_ac_buses=7000)
    assert ac.get("converged"), f"AC not converged: {ac}"
    n = net_ac  # pruned+solved

    # --- 解いたネットのグラフ(in-service) ---
    g = nx.Graph()
    g.add_nodes_from(n.bus.index)
    for _, r in n.line.iterrows():
        if r["in_service"]:
            g.add_edge(int(r["from_bus"]), int(r["to_bus"]))
    for _, r in n.trafo.iterrows():
        if r["in_service"]:
            g.add_edge(int(r["hv_bus"]), int(r["lv_bus"]))
    comp_of, comp_size = {}, {}
    for ci, comp in enumerate(nx.connected_components(g)):
        for b in comp:
            comp_of[b] = ci
        comp_size[ci] = len(comp)

    load_p = n.load[n.load.in_service].groupby("bus")["p_mw"].sum().to_dict()
    load_q = n.load[n.load.in_service].groupby("bus")["q_mvar"].sum().to_dict()
    shunt_q = n.shunt[n.shunt.in_service].groupby("bus")["q_mvar"].sum().to_dict() \
        if len(n.shunt) else {}
    gen_bus = set(n.gen[n.gen.in_service]["bus"]) if len(n.gen) else set()
    sgen_bus = set(n.sgen[n.sgen.in_service]["bus"]) if len(n.sgen) else set()
    ext_bus = set(n.ext_grid[n.ext_grid.in_service]["bus"])
    trafo_bus = set(n.trafo[n.trafo.in_service]["hv_bus"]) | \
        set(n.trafo[n.trafo.in_service]["lv_bus"])
    src_bus = gen_bus | ext_bus  # 電圧源(PV/slack)

    def hops_to(b, targets, cap=30):
        if b in targets:
            return 0
        seen, frontier = {b}, [b]
        for d in range(1, cap + 1):
            nxt = []
            for x in frontier:
                for y in g.neighbors(x):
                    if y in seen:
                        continue
                    if y in targets:
                        return d
                    seen.add(y)
                    nxt.append(y)
            if not nxt:
                return None
            frontier = nxt
        return None

    # 接続線の合計(km・充電容量) — 1puでの充電Q[MVar] ≈ vn_kv^2 * 2πf * C
    f_hz = ISLAND_FREQ[island]
    line_by_bus = {}
    for li, r in n.line.iterrows():
        if not r["in_service"]:
            continue
        c_total_nf = float(r["c_nf_per_km"]) * float(r["length_km"]) * \
            float(r.get("parallel", 1))
        vn = float(n.bus.at[int(r["from_bus"]), "vn_kv"])
        q_chg = (vn * 1e3) ** 2 * 2 * math.pi * f_hz * c_total_nf * 1e-9 / 1e6
        for b in (int(r["from_bus"]), int(r["to_bus"])):
            d = line_by_bus.setdefault(b, {"km": 0.0, "q_chg_mvar": 0.0, "n": 0})
            d["km"] += float(r["length_km"])
            d["q_chg_mvar"] += q_chg
            d["n"] += 1

    rows = []
    for b in n.bus.index:
        if b not in n.res_bus.index:
            continue
        vm = float(n.res_bus.at[b, "vm_pu"])
        if not (vm > OVER or vm < UNDER) or math.isnan(vm):
            continue
        ci = comp_of.get(b)
        lb = line_by_bus.get(b, {"km": 0, "q_chg_mvar": 0, "n": 0})
        rows.append({
            "bus": int(b), "name": str(n.bus.at[b, "name"]),
            "kv": float(n.bus.at[b, "vn_kv"]),
            "zone": str(n.bus.at[b, "zone"]) if "zone" in n.bus.columns else None,
            "vm": round(vm, 4), "kind": "over" if vm > OVER else "under",
            "component": ci, "comp_size": comp_size.get(ci),
            "degree": g.degree(b),
            "load_p_mw": round(load_p.get(b, 0.0), 3),
            "load_q_mvar": round(load_q.get(b, 0.0), 3),
            "shunt_q_mvar": round(shunt_q.get(b, 0.0), 3),
            "has_gen": b in gen_bus, "has_sgen": b in sgen_bus,
            "is_slack": b in ext_bus,
            "line_km": round(lb["km"], 2), "n_lines": lb["n"],
            "line_charge_mvar_1pu": round(lb["q_chg_mvar"], 3),
            "hops_to_source": hops_to(b, src_bus),
            "hops_to_trafo": hops_to(b, trafo_bus),
        })
    rows.sort(key=lambda r: r["vm"], reverse=True)

    # 外れ値同士の隣接クラスタ(同成分・グラフ距離<=2で連結)
    out_buses = {r["bus"] for r in rows}
    cg = nx.Graph()
    cg.add_nodes_from(out_buses)
    for b in out_buses:
        seen, frontier = {b}, [b]
        for _ in range(2):
            nxt = []
            for x in frontier:
                for y in g.neighbors(x):
                    if y in seen:
                        continue
                    seen.add(y)
                    nxt.append(y)
                    if y in out_buses:
                        cg.add_edge(b, y)
            frontier = nxt
    clusters = [sorted(c) for c in nx.connected_components(cg)]
    clusters.sort(key=len, reverse=True)

    result = {
        "meta": {"island": island, "factor": rfac, "n_shunt": n_shunt,
                 "site_trafos": site_trafos, "deenergize_unbuilt": deenergize,
                 "n_site_trafo": bstats.get("n_site_trafo", 0),
                 "n_deenergized": bstats.get("n_deenergized", 0),
                 "loss_mw": ac.get("total_loss_mw"),
                 "prune_thr": ac.get("prune_threshold"),
                 "served_frac": ac.get("served_frac"),
                 "vm_min": ac.get("vm_pu_min"), "vm_max": ac.get("vm_pu_max"),
                 "over_thr": OVER, "under_thr": UNDER},
        "n_over": sum(1 for r in rows if r["kind"] == "over"),
        "n_under": sum(1 for r in rows if r["kind"] == "under"),
        "clusters": clusters,
        "outliers": rows,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1, ensure_ascii=False)
    print(f"over={result['n_over']} under={result['n_under']} "
          f"clusters={len(clusters)} -> {out_path}")


if __name__ == "__main__":
    main()
