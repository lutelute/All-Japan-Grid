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


from src.powerflow.pipeline import add_provisional_infeed  # noqa: E402
# 検出+適用の実装は介入#37として src/powerflow/pipeline.py に正典化
# (2026-08-30 オーナー承認)。本プローブは再現ハーネスとして残す


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
        ledger = add_provisional_infeed(net)
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
