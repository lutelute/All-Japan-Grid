#!/usr/bin/env python3
"""west 2531成分の内訳診断 — 断片化の主因を特定する.

問い: 断片は「大量の小島ノイズ(1-2バス配電/鉄塔)」か「繋ぐべき大きな分断網」か?
出力:
  - 成分サイズ分布(1/2/3-5/6-20/21-100/>100バス)
  - 各成分の最大電圧・sub(変電所)有無・閉じ込め負荷/発電
  - ≥154kV(繋ぐべき)を含む非主成分の数と正体(named)
  - build段階別の成分数推移(線のみ→+変圧器)
  .venv/bin/python diag_west_fragments.py <island> <out.json>
"""
from __future__ import annotations
import json, os, sys
from collections import Counter, defaultdict
REPO = "/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid"
sys.path.insert(0, REPO); os.chdir(REPO)


def main():
    island = sys.argv[1]; out_path = sys.argv[2]
    import networkx as nx
    import pandapower as pp
    import pandapower.topology as ptop
    from scripts.run_full_powerflow_from_db import (
        BUILT, ISLAND_OF, allocate_loads, attach_generators, build_island_net)
    from scripts.uc_to_pf_built import ISLAND_FREQ
    from src.powerflow.load_estimator import load_demand_config
    from src.powerflow.pref_demand import pref_zone_gwh

    built = json.load(open(BUILT))
    pw, _ = pref_zone_gwh(built["nodes"])
    net, bus_of, bstats = build_island_net(island, built["nodes"], built["edges"],
                                           ISLAND_FREQ[island], {})
    attach_generators(net, bus_of, built["nodes"], island)
    allocate_loads(net, load_demand_config(), pref_gwh=pw)

    rep = {"island": island, "n_bus": int(len(net.bus)),
           "n_line": int(len(net.line)), "n_trafo": int(len(net.trafo))}

    # (1) 線のみのグラフ vs 線+変圧器のグラフ で成分数比較(変圧器が繋いでいる量)
    g_line = nx.Graph(); g_line.add_nodes_from(net.bus.index)
    for _, r in net.line.iterrows():
        if r["in_service"]:
            g_line.add_edge(int(r["from_bus"]), int(r["to_bus"]))
    g_full = g_line.copy()
    for _, r in net.trafo.iterrows():
        if r["in_service"]:
            g_full.add_edge(int(r["hv_bus"]), int(r["lv_bus"]))
    rep["n_comp_line_only"] = nx.number_connected_components(g_line)
    rep["n_comp_with_trafo"] = nx.number_connected_components(g_full)

    comps = sorted(nx.connected_components(g_full), key=len, reverse=True)
    rep["n_comp"] = len(comps)
    rep["main_comp_bus"] = len(comps[0])

    # (2) 成分サイズ分布
    sizes = [len(c) for c in comps]
    buckets = {"1": 0, "2": 0, "3-5": 0, "6-20": 0, "21-100": 0, ">100": 0}
    for s in sizes:
        if s == 1: buckets["1"] += 1
        elif s == 2: buckets["2"] += 1
        elif s <= 5: buckets["3-5"] += 1
        elif s <= 20: buckets["6-20"] += 1
        elif s <= 100: buckets["21-100"] += 1
        else: buckets[">100"] += 1
    rep["size_buckets"] = buckets

    # (3) 各非主成分の特性
    vn = net.bus["vn_kv"]; typ = net.bus["type"]; name = net.bus["name"]
    load_bus = net.load.groupby("bus").p_mw.sum().to_dict()
    gen_bus = net.gen.groupby("bus").max_p_mw.sum().to_dict()
    main = comps[0]
    frag_maxkv = Counter()
    frag_has_sub = 0
    frag_load = 0.0; frag_gen = 0.0
    frag_ge154 = []   # ≥154kVを含む断片(繋ぐべき候補)
    for c in comps[1:]:
        mkv = max(float(vn.at[b]) for b in c)
        frag_maxkv[int(round(mkv))] += 1
        if any(typ.at[b] != "n" for b in c):
            frag_has_sub += 1
        frag_load += sum(load_bus.get(b, 0.0) for b in c)
        frag_gen += sum(gen_bus.get(b, 0.0) for b in c)
        if mkv >= 154:
            names = [str(name.at[b]) for b in c
                     if typ.at[b] != "n" and str(name.at[b]) != "None"]
            frag_ge154.append({"size": len(c), "max_kv": int(round(mkv)),
                               "load_mw": round(sum(load_bus.get(b, 0.0) for b in c), 1),
                               "gen_mw": round(sum(gen_bus.get(b, 0.0) for b in c), 1),
                               "names": names[:5]})
    rep["fragment_max_kv_hist"] = dict(sorted(frag_maxkv.items()))
    rep["fragments_with_substation"] = frag_has_sub
    rep["fragment_trapped_load_mw"] = round(frag_load, 1)
    rep["fragment_trapped_gen_mw"] = round(frag_gen, 1)
    rep["total_load_mw"] = round(float(net.load.p_mw.sum()), 1)
    rep["total_gen_cap_mw"] = round(float(net.gen.max_p_mw.sum()), 1)
    frag_ge154.sort(key=lambda d: -d["size"])
    rep["fragments_ge154kv"] = {"count": len(frag_ge154),
                                "top": frag_ge154[:20]}

    json.dump(rep, open(out_path, "w"), ensure_ascii=False, indent=1)
    # 要点print
    print(f"[{island}] bus={rep['n_bus']} 成分={rep['n_comp']} 主成分={rep['main_comp_bus']}")
    print(f"  線のみ成分={rep['n_comp_line_only']} → +変圧器={rep['n_comp_with_trafo']}")
    print(f"  サイズ分布: {buckets}")
    print(f"  断片の最大電圧別: {rep['fragment_max_kv_hist']}")
    print(f"  変電所を含む断片: {frag_has_sub}/{len(comps)-1}")
    print(f"  閉じ込め負荷={rep['fragment_trapped_load_mw']}MW /"
          f"{rep['total_load_mw']}  発電={rep['fragment_trapped_gen_mw']}MW /"
          f"{rep['total_gen_cap_mw']}")
    print(f"  ≥154kVを含む断片(繋ぐべき候補)={len(frag_ge154)}件")
    for d in frag_ge154[:12]:
        print(f"    {d['max_kv']}kV size={d['size']} load={d['load_mw']} "
              f"gen={d['gen_mw']} {d['names']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
