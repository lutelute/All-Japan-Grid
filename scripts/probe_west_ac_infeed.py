#!/usr/bin/env python3
"""西AC第5波 — 「都心給電の必然接続(仮)」プローブ(2026-08-30・正典不変更).

根因(docs/reports/west_ac_probe2_2026-08-30.md): 大阪都心の154kVクラスタが
上位系(275/500kV)への変圧器を持たないまま数GW負荷を抱える=OSM欠測。
関西の開示系統図は実名匿名化(転載禁止)で出典つき回復が取れない。

そこでオーナー提案(2026-08-30)の**(仮)クラス**を設計する:
  論法は推定母線と同じ —「負荷が現に供給されている以上、上位系からの
  給電経路の存在は電気的必然。存在のみを主張し、経路・パラメータは(仮)と
  明記する」。適用は既定OFF・全件台帳・介入#37候補としてオーナー承認待ち。

検出: 同一電圧階級の線連結クラスタのうち、(a)どのバスも上位電圧への変圧器を
持たず (b)クラスタ負荷合計 ≥ 100MW のものを「孤立負荷クラスタ」とする。
(仮)接続: クラスタ最大負荷バス → 地理的最近傍の上位(≥275kV)バスへ
参照パラメータの変圧器を1台(sn=クラスタ負荷×1.5・vk12%・(仮)タグ)。

出力: docs/reports/west_ac_infeed_probe_2026-08-30.{md,json}
"""
from __future__ import annotations

import copy
import json
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from scripts.run_full_powerflow_from_db import (  # noqa: E402
    BUILT, ISLAND_OF, add_per_component_slacks, allocate_loads,
    attach_generators, GEN_ATTACH_DEFAULT, build_island_net)
from scripts.uc_to_pf_built import build_backbone_net, solve_hour  # noqa: E402
from src.powerflow.load_estimator import load_demand_config  # noqa: E402
from src.powerflow.pipeline import add_reactive_compensation  # noqa: E402
from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot  # noqa: E402
from src.uc.scenario import build_national_scenario  # noqa: E402
from src.uc.solver import solve_uc  # noqa: E402
import pandapower as pp


def geo_of(net, b):
    try:
        g = json.loads(net.bus.at[b, "geo"])
        return float(g["coordinates"][0]), float(g["coordinates"][1])
    except Exception:  # noqa: BLE001
        return None


def detect_isolated_clusters(net, min_load_mw=100.0):
    """上位変圧器を持たない同階級線クラスタ(負荷つき)を検出."""
    from collections import defaultdict
    import networkx as nx
    # 電圧階級ごとの線グラフ
    g = nx.Graph()
    for _, r in net.line[net.line.in_service].iterrows():
        fb, tb = int(r.from_bus), int(r.to_bus)
        if abs(net.bus.at[fb, "vn_kv"] - net.bus.at[tb, "vn_kv"]) < 0.5:
            g.add_edge(fb, tb)
    has_up = set()   # 上位(自階級より高い)へのtrafoを持つバス
    for _, r in net.trafo[net.trafo.in_service].iterrows():
        hv, lv = int(r.hv_bus), int(r.lv_bus)
        has_up.add(lv)          # lv側は上位(hv)へ繋がる
    load_at = defaultdict(float)
    for _, r in net.load[net.load.in_service].iterrows():
        load_at[int(r.bus)] += float(r.p_mw)
    out = []
    for comp in nx.connected_components(g):
        kv = float(net.bus.at[next(iter(comp)), "vn_kv"])
        if kv < 60 or kv >= 275:
            continue
        if any(b in has_up for b in comp):
            continue
        load = sum(load_at.get(b, 0.0) for b in comp)
        if load < min_load_mw:
            continue
        big = max(comp, key=lambda b: load_at.get(b, 0.0))
        names = sorted({str(net.bus.at[b, "name"])[:14] for b in comp
                        if load_at.get(b, 0) > 0})[:4]
        out.append(dict(kv=kv, n_bus=len(comp), load_mw=round(load, 1),
                        anchor_bus=int(big), names=names))
    return sorted(out, key=lambda c: -c["load_mw"])


def add_provisional_infeed(net, clusters):
    """(仮)給電変圧器を追加。全件台帳を返す(正典不変更・このnet限り)."""
    ups = [b for b in net.bus.index
           if net.bus.at[b, "in_service"] and net.bus.at[b, "vn_kv"] >= 275]
    up_geo = [(b, geo_of(net, b)) for b in ups]
    up_geo = [(b, g) for b, g in up_geo if g]
    ledger = []
    for c in clusters:
        a = c["anchor_bus"]
        ga = geo_of(net, a)
        if not ga:
            continue
        best = min(up_geo, key=lambda bg: (bg[1][0]-ga[0])**2 +
                   (bg[1][1]-ga[1])**2)
        ub, ug = best
        dist_km = math.hypot((ug[0]-ga[0])*91, (ug[1]-ga[1])*111)
        sn = max(300.0, 1.5 * c["load_mw"])
        pp.create_transformer_from_parameters(
            net, hv_bus=int(ub), lv_bus=int(a), sn_mva=sn,
            vn_hv_kv=float(net.bus.at[ub, "vn_kv"]), vn_lv_kv=c["kv"],
            vkr_percent=0.5, vk_percent=12.0, pfe_kw=0.0, i0_percent=0.0,
            name=f"(仮)都心給電 {c['kv']:.0f}kV #37candidate")
        ledger.append(dict(
            kv=c["kv"], load_mw=c["load_mw"], n_bus=c["n_bus"],
            cluster_names=c["names"],
            to_upper=str(net.bus.at[ub, "name"])[:20],
            upper_kv=float(net.bus.at[ub, "vn_kv"]),
            dist_km=round(dist_km, 1), sn_mva=round(sn, 0)))
    return ledger


def main():
    print("UC求解...")
    scn = build_national_scenario(scenario="fy2023r2")
    uc = solve_uc(scn.to_uc_parameters()); assert uc.is_optimal
    regions = sorted(r for r, (i, _f) in ISLAND_OF.items() if i == "west")
    h = int(np.argmax(sum(np.asarray(scn.net_demand_r[r]) for r in regions)))
    built = json.load(open(BUILT)); cfg = load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(built["nodes"])
    geom = {}
    base, bus_of, _ = build_island_net("west", built["nodes"], built["edges"],
                                       60.0, geom)
    attach_generators(base, bus_of, built["nodes"], "west",
                      attach_mode=GEN_ATTACH_DEFAULT)
    allocate_loads(base, cfg, pref_gwh=pref_gwh)
    add_reactive_compensation(base, factor=0.8)
    fuel_by_zone = {r: uc_snapshot(uc, scn.generators, h, region=r)
                    for r in regions}
    for r in regions:
        sp = (uc.regional_spill_mw.get(r) or [])
        v = float(sp[h]) if h < len(sp) else 0.0
        if v > 1e-6:
            tot = sum(fuel_by_zone[r].values())
            if tot > v:
                fuel_by_zone[r] = {k: mw*(tot-v)/tot
                                   for k, mw in fuel_by_zone[r].items()}
    demand = {r: float(scn.net_demand_r[r][h]) for r in regions}

    results = {}
    for tag, thr in (("backbone154", 154.0), ("full", None)):
        t0 = time.monotonic()
        net = copy.deepcopy(base)
        if thr:
            net, _led = build_backbone_net(net, threshold_kv=thr)
        clusters = detect_isolated_clusters(net)
        ledger = add_provisional_infeed(net, clusters)
        add_per_component_slacks(net)
        inject_dispatch_by_zone(net, fuel_by_zone, demand)
        pre = float(net.load.loc[net.load.in_service, "p_mw"].sum())
        net_s, mode = solve_hour(net, "ac")
        served = float(net_s.res_load.p_mw.sum())
        vm = net_s.res_bus.vm_pu.dropna()
        results[tag] = dict(
            mode=mode, n_infeed=len(ledger),
            infeed_ledger=ledger[:40],
            served_frac=round(served/max(pre, 1e-9), 4),
            vm_min=round(float(vm.min()), 3) if len(vm) else None,
            vm_max=round(float(vm.max()), 3) if len(vm) else None,
            elapsed_s=round(time.monotonic()-t0, 1))
        print(f"[{tag}] (仮)接続 {len(ledger)}件 → mode={mode} "
              f"served={results[tag]['served_frac']:.1%} "
              f"vm[{results[tag]['vm_min']},{results[tag]['vm_max']}] "
              f"({results[tag]['elapsed_s']:.0f}s)")
        for l in ledger[:8]:
            print(f"    {l['kv']:.0f}kV {l['load_mw']:8,.0f}MW "
                  f"{l['cluster_names']} → {l['to_upper']}"
                  f"({l['upper_kv']:.0f}kV, {l['dist_km']}km)")

    doc = {"note": ("(仮)都心給電プローブ。正典不変更。論法=推定母線と同じ"
                    "『存在は必然・経路とパラメータは(仮)明記』。適用可否は"
                    "オーナー承認(介入#37候補)"),
           "peak_hour": h, "results": results}
    json.dump(doc, open("docs/reports/west_ac_infeed_probe_2026-08-30.json",
                        "w"), ensure_ascii=False, indent=1)
    print("-> docs/reports/west_ac_infeed_probe_2026-08-30.json")


if __name__ == "__main__":
    main()
