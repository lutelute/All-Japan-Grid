#!/usr/bin/env python3
"""城南チェーンの what-if 感度プローブ — 「給電変圧器の定格が律速か」を銘板収集の前に確定する。

⚠ ここで置く定格は**仮定値(what-if)であり出典なし**。正典・介入には一切使わない。
目的は感度の符号と量級だけ: 定格を実物級に上げたらチェーン電圧が回復するか？
回復しないなら律速は直列インピーダンス/給電構造(OSM欠落)であり、銘板収集では直らない。

Usage: PYTHONPATH=. python probe_rating_whatif.py out.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

import pandapower as pp

from scripts.run_full_powerflow_from_db import (
    BUILT, ISLAND_FREQ, add_per_component_slacks, allocate_loads,
    attach_generators, balance_by_zone, build_island_net, load_demand_config,
    solve_island)

CHAIN = ["洗足池変電所", "洗足変電所", "祐天寺変電所", "経堂変電所",
         "練馬変電所 66kV", "上北沢変電所"]


def build_base():
    db = json.load(open(BUILT))
    nodes, edges = db["nodes"], db["edges"]
    cfg = load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(nodes)
    geom = {}
    net, bus_of, _ = build_island_net("east", nodes, edges,
                                      ISLAND_FREQ["east"], geom,
                                      deenergize_unbuilt=True)  # 大間分離済みの土俵
    attach_generators(net, bus_of, nodes, "east")
    allocate_loads(net, cfg, pref_gwh=pref_gwh)
    from src.powerflow.pipeline import add_reactive_compensation
    add_reactive_compensation(net, factor=cfg.get("reactive_compensation_factor", 0.6))
    return net, nodes, bus_of


def measure(net, tag):
    add_per_component_slacks(net)
    balance_by_zone(net, load_demand_config())
    _nd, dc, net_ac, ac = solve_island(net, max_ac_buses=7000)
    assert ac.get("converged"), f"{tag}: AC not converged"
    n = net_ac
    name_vm = {}
    for b in n.bus.index:
        nm = str(n.bus.at[b, "name"])
        if nm in CHAIN and b in n.res_bus.index:
            name_vm[nm] = round(float(n.res_bus.at[b, "vm_pu"]), 4)
    n_under = int((n.res_bus.vm_pu < 0.85).sum())
    n_over = int((n.res_bus.vm_pu > 1.10).sum())
    return {"tag": tag, "chain_vm": name_vm, "n_under": n_under,
            "n_over": n_over, "vm_min": round(float(n.res_bus.vm_pu.min()), 4),
            "served_frac": ac.get("served_frac"),
            "loss_mw": ac.get("total_loss_mw")}


def bump_ratings(net, nodes, bus_of, sn, add_kamikitazawa):
    """what-if: 城南給電trafo(練馬275/66・和田堀154/66)の定格をsnへ。
    add_kamikitazawa=True で上北沢154-66を仮リンク(1.41km・出典なし=実験のみ)。"""
    n_bumped = 0
    for ti in net.trafo.index:
        hvb, lvb = int(net.trafo.at[ti, "hv_bus"]), int(net.trafo.at[ti, "lv_bus"])
        names = str(net.bus.at[hvb, "name"]) + str(net.bus.at[lvb, "name"])
        if "練馬変電所" in names or "和田堀変電所" in names:
            net.trafo.at[ti, "sn_mva"] = sn
            n_bumped += 1
    if add_kamikitazawa:
        k154 = [b for b in net.bus.index
                if str(net.bus.at[b, "name"]) == "上北沢変電所"
                and abs(float(net.bus.at[b, "vn_kv"]) - 154.0) < 1]
        k66 = [b for b in net.bus.index
               if str(net.bus.at[b, "name"]) == "上北沢変電所"
               and abs(float(net.bus.at[b, "vn_kv"]) - 66.0) < 1]
        if k154 and k66:
            pp.create_transformer_from_parameters(
                net, hv_bus=k154[0], lv_bus=k66[0], sn_mva=sn,
                vn_hv_kv=154.0, vn_lv_kv=66.0, vkr_percent=0.5,
                vk_percent=12.0, pfe_kw=0.0, i0_percent=0.0,
                name="WHATIF_kamikitazawa_154/66")
            n_bumped += 1
    return n_bumped


def main():
    out_path = sys.argv[1]
    results = []
    # W0: 基準(deenergize込み)
    net, nodes, bus_of = build_base()
    results.append(measure(net, "W0_base"))
    # W1: 定格450MVA相当 + 上北沢リンク
    net, nodes, bus_of = build_base()
    nb = bump_ratings(net, nodes, bus_of, sn=450.0, add_kamikitazawa=True)
    r = measure(net, "W1_sn450+kamikitazawa")
    r["n_bumped"] = nb
    results.append(r)
    # W2: 定格1000MVA(上限感度) + 上北沢リンク
    net, nodes, bus_of = build_base()
    nb = bump_ratings(net, nodes, bus_of, sn=1000.0, add_kamikitazawa=True)
    r = measure(net, "W2_sn1000+kamikitazawa")
    r["n_bumped"] = nb
    results.append(r)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"note": "what-if感度のみ(定格は仮定値・出典なし・正典不使用)",
                   "results": results}, f, indent=1, ensure_ascii=False)
    for r in results:
        print(r["tag"], "n_under=", r["n_under"], "chain=", r["chain_vm"])


if __name__ == "__main__":
    main()
