#!/usr/bin/env python3
"""slack吸収の解剖 — 「どの成分・どの理由でスラックが電力を供給しているか」を定量化する.

背景(2026-07-05): UC 24h×全規模の整合検証で slack吸収が east median 25.5%・
okinawa 49.9% と判明。犯人候補は
  (a) 断片成分: 負荷は変電所バスへ一律按分されるが、主成分外の孤立成分には
      発電が届かない → その成分の synthetic slack が全量を供給
  (b) 主成分の需給ミスマッチ: 発電所の位置精度(最寄りバス≤20km)・容量の粗さ・
      UC注入の容量比例配分と実際の系統運用の差
のどちらが支配的かで次の一手(接続修復 vs 発電/負荷データ充填)が変わる。

本ツールは1時刻断面を UC注入で解き、ext_grid(slack)の p_mw を成分別に集計して
(a)/(b) を分解する。判断は人間(オーナー)が行う — 本ツールは材料の整形まで。

使い方:
    PYTHONPATH=. .venv/bin/python scripts/diagnose_slack.py --island east --hour 17
    PYTHONPATH=. .venv/bin/python scripts/diagnose_slack.py --island okinawa

出力: docs/reports/slack_diagnosis_<island>_t<hour>_<date>.json + コンソール表
"""
import argparse
import copy
import datetime as _dt
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandapower.topology as ptop

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from scripts.run_full_powerflow_from_db import (  # noqa: E402
    BUILT,
    ISLAND_OF,
    add_per_component_slacks,
    allocate_loads,
    attach_generators,
    build_island_net,
    solve_island,
)
from src.powerflow.load_estimator import load_demand_config  # noqa: E402
from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot  # noqa: E402
from src.uc.scenario import build_national_scenario  # noqa: E402
from src.uc.solver import solve_uc  # noqa: E402

ISLAND_FREQ = {"hokkaido": 50.0, "east": 50.0, "west": 60.0, "okinawa": 60.0}
ISLAND_MODE = {"hokkaido": "ac", "east": "ac", "west": "dc", "okinawa": "ac"}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--island", default="east")
    ap.add_argument("--hour", type=int, default=None,
                    help="UC時刻(0-23)。省略=島純需要ピーク")
    ap.add_argument("--scenario", default="fy2023r2")
    ap.add_argument("--top", type=int, default=15, help="表示する成分数")
    args = ap.parse_args()
    island = args.island
    mode = ISLAND_MODE[island]

    print(f"UC求解中... ({args.scenario})")
    scn = build_national_scenario(scenario=args.scenario)
    uc = solve_uc(scn.to_uc_parameters())
    if not uc.is_optimal:
        print("UCがOptimalでない")
        return 1
    regions = sorted(r for r, (isl, _f) in ISLAND_OF.items() if isl == island)
    net_dem = sum(np.asarray(scn.net_demand_r[r]) for r in regions)
    t = args.hour if args.hour is not None else int(np.argmax(net_dem))

    print(f"島ネット構築中... ({island})")
    built = json.load(open(BUILT))
    cfg = load_demand_config()
    base, bus_of, bstats = build_island_net(
        island, built["nodes"], built["edges"], ISLAND_FREQ[island], {})
    attach_generators(base, bus_of, built["nodes"], island)
    allocate_loads(base, cfg)
    add_per_component_slacks(base)

    net = copy.deepcopy(base)
    fuel_by_zone = {r: uc_snapshot(uc, scn.generators, t, region=r)
                    for r in regions}
    demand = {r: float(scn.net_demand_r[r][t]) for r in regions}
    inject_dispatch_by_zone(net, fuel_by_zone, demand)

    print(f"解いています... (mode={mode}, t={t})")
    net_dc, dc, net_ac, ac = solve_island(
        net, max_ac_buses=10**9 if mode == "ac" else 0)
    net_s = net_ac if (mode == "ac" and ac.get("converged")) else net_dc
    solved = "ac" if (mode == "ac" and ac.get("converged")) else "dc"
    if not (ac.get("converged") or dc.get("converged")):
        print("非収束 — 診断不能")
        return 1

    # ── 成分分解(in-service 要素のグラフ。solve後の実効トポロジ) ──
    g = ptop.create_nxgraph(net_s, respect_switches=False,
                            include_out_of_service=False)
    import networkx as nx
    comp_of = {}
    comps = []
    for ci, nodes_set in enumerate(nx.connected_components(g)):
        comps.append(nodes_set)
        for b in nodes_set:
            comp_of[b] = ci

    res_eg = net_s.res_ext_grid
    zone = net_s.bus["zone"]
    rows = []
    for ci, nodes_set in enumerate(comps):
        bus_list = list(nodes_set)
        loads = net_s.load[net_s.load.bus.isin(bus_list)
                           & net_s.load.in_service]
        gens = net_s.gen[net_s.gen.bus.isin(bus_list)
                         & net_s.gen.in_service] if len(net_s.gen) else []
        egs = net_s.ext_grid[net_s.ext_grid.bus.isin(bus_list)]
        slack_p = float(res_eg.loc[egs.index, "p_mw"].sum()) if len(egs) else 0.0
        zones = zone.loc[bus_list].dropna()
        rows.append({
            "comp": ci, "n_bus": len(bus_list),
            "load_mw": round(float(loads.p_mw.sum()), 1) if len(loads) else 0.0,
            "gen_inj_mw": round(float(gens.p_mw.sum()), 1) if len(gens) else 0.0,
            "n_gen": int(len(gens)) if len(gens) else 0,
            "slack_mw": round(slack_p, 1),
            "zone_top": zones.mode().iloc[0] if len(zones) else None,
        })
    rows.sort(key=lambda r: -abs(r["slack_mw"]))

    total_slack_pos = sum(r["slack_mw"] for r in rows if r["slack_mw"] > 0)
    total_slack_neg = sum(r["slack_mw"] for r in rows if r["slack_mw"] < 0)
    total_load = sum(r["load_mw"] for r in rows)
    main = max(rows, key=lambda r: r["n_bus"])
    frag_pos = sum(r["slack_mw"] for r in rows
                   if r is not main and r["slack_mw"] > 0)
    frag_noGen = sum(r["slack_mw"] for r in rows
                     if r is not main and r["n_gen"] == 0 and r["slack_mw"] > 0)

    print(f"\n=== slack解剖: {island} t={t} solved={solved} "
          f"(成分{len(comps)}・負荷計{total_load:,.0f}MW) ===")
    print(f"slack供給(+)合計: {total_slack_pos:,.0f} MW "
          f"({total_slack_pos/total_load*100:.1f}% of load)")
    print(f"slack吸収(-)合計: {total_slack_neg:,.0f} MW")
    print(f"\n[分解]")
    print(f"  (a) 断片成分のslack供給: {frag_pos:,.0f} MW "
          f"({frag_pos/max(total_slack_pos,1e-9)*100:.1f}% of slack+) "
          f"— うち発電ゼロ成分: {frag_noGen:,.0f} MW")
    print(f"  (b) 主成分({main['n_bus']}バス)のslack: {main['slack_mw']:,.0f} MW "
          f"(load {main['load_mw']:,.0f} / gen注入 {main['gen_inj_mw']:,.0f})")
    print(f"\n[成分別 上位{args.top}] (|slack|順)")
    print(f"{'comp':>5} {'n_bus':>6} {'load':>9} {'gen注入':>9} "
          f"{'slack':>9} {'n_gen':>5}  zone")
    for r in rows[:args.top]:
        tag = " ←主成分" if r is main else ("  [発電ゼロ]" if r["n_gen"] == 0 else "")
        print(f"{r['comp']:>5} {r['n_bus']:>6} {r['load_mw']:>9,.0f} "
              f"{r['gen_inj_mw']:>9,.0f} {r['slack_mw']:>9,.0f} "
              f"{r['n_gen']:>5}  {r['zone_top']}{tag}")

    out = {
        "meta": {"date": _dt.date.today().isoformat(), "island": island,
                 "hour": t, "scenario": args.scenario, "solved": solved,
                 "n_components": len(comps), "total_load_mw": round(total_load, 1)},
        "decomposition": {
            "slack_supply_total_mw": round(total_slack_pos, 1),
            "slack_supply_frac_of_load": round(total_slack_pos / total_load, 4),
            "slack_absorb_total_mw": round(total_slack_neg, 1),
            "fragments_supply_mw": round(frag_pos, 1),
            "fragments_supply_frac_of_slack": round(
                frag_pos / max(total_slack_pos, 1e-9), 4),
            "fragments_zero_gen_supply_mw": round(frag_noGen, 1),
            "main_component": main,
        },
        "components_top50": rows[:50],
        "note": "判断は人間が行う(2026-07-05オーナー方針)。本レポートは材料の整形。"
                "(a)断片slack=負荷按分が孤立変電所にも載る構造の症状(接続修復か"
                "按分ポリシーの選択は要オーナー判断)。(b)主成分slack=発電位置/容量/"
                "UC容量比例注入の粗さ。",
    }
    path = (f"docs/reports/slack_diagnosis_{island}_t{t}_"
            f"{_dt.date.today().isoformat()}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n-> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
