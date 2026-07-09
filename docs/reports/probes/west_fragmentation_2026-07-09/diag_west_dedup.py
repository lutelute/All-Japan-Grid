#!/usr/bin/env python3
"""west 断片化に対する「重複ノードdedup」と「近接変圧器/スナップ」の効果見積り.

3つの介入候補を独立に測る(実際のbuildは変えず・グラフ上で効果だけ計測):
  D  重複dedup: 同一(丸め座標,kv)の複数ノードを1つに merge(bbox重なり由来)
  Tr 近接変圧器: 同一サイト(≤200m)の別電圧ノード間に変圧器辺を足す
  Sn 近接スナップ: 孤立変電所バスを≤150mのbuilt edge端点/別バスへ接続
各々を単独/累積で適用したときの成分数を出す。
  .venv/bin/python diag_west_dedup.py <island> <out.json>
"""
from __future__ import annotations
import json, math, os, sys
from collections import defaultdict
REPO = "/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid"
sys.path.insert(0, REPO); os.chdir(REPO)


def hav(lat1, lon1, lat2, lon2):
    R = 6371000.0
    dlat = math.radians(lat2-lat1); dlon = math.radians(lon2-lon1)
    a = (math.sin(dlat/2)**2 + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))*math.sin(dlon/2)**2)
    return R*2*math.asin(math.sqrt(a))


def main():
    island = sys.argv[1]; out_path = sys.argv[2]
    import networkx as nx
    from scripts.run_full_powerflow_from_db import (
        BUILT, allocate_loads, attach_generators, build_island_net, _bus_lonlat)
    from scripts.uc_to_pf_built import ISLAND_FREQ
    from src.powerflow.load_estimator import load_demand_config
    from src.powerflow.pref_demand import pref_zone_gwh

    built = json.load(open(BUILT))
    pw, _ = pref_zone_gwh(built["nodes"])
    net, bus_of, _ = build_island_net(island, built["nodes"], built["edges"],
                                      ISLAND_FREQ[island], {})

    binfo = {}
    for b in net.bus.index:
        lon, lat = _bus_lonlat(net, b)
        binfo[b] = (lat, lon, round(float(net.bus.at[b, "vn_kv"]), 1),
                    net.bus.at[b, "type"])

    # ベースグラフ(線+変圧器)
    def base_graph():
        g = nx.Graph(); g.add_nodes_from(net.bus.index)
        for _, r in net.line.iterrows():
            if r["in_service"]: g.add_edge(int(r["from_bus"]), int(r["to_bus"]))
        for _, r in net.trafo.iterrows():
            if r["in_service"]: g.add_edge(int(r["hv_bus"]), int(r["lv_bus"]))
        return g

    def ncomp(g):
        return nx.number_connected_components(g)

    g0 = base_graph()
    base_nc = ncomp(g0)

    # D: 同一(丸め5桁座標, kv)の重複バスを縮約(union)
    def add_dedup(g):
        key2b = defaultdict(list)
        for b in net.bus.index:
            lat, lon, kv, _t = binfo[b]
            if lat is None: continue
            key2b[(round(lat, 5), round(lon, 5), kv)].append(b)
        merged = 0
        for k, bs in key2b.items():
            for b in bs[1:]:
                g.add_edge(bs[0], b); merged += 1
        return merged

    # Tr: 同一サイト(≤200m)の別電圧ノード間を接続(変圧器相当)
    def add_trafo_radius(g, radius_m=200):
        pts = [(binfo[b][0], binfo[b][1], binfo[b][2], b)
               for b in net.bus.index if binfo[b][0] is not None]
        # 粗いグリッドで近傍探索
        grid = defaultdict(list)
        cell = 0.002  # ~200m
        for lat, lon, kv, b in pts:
            grid[(round(lat/cell), round(lon/cell))].append((lat, lon, kv, b))
        added = 0
        for lat, lon, kv, b in pts:
            gx, gy = round(lat/cell), round(lon/cell)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for lat2, lon2, kv2, b2 in grid.get((gx+dx, gy+dy), ()):
                        if b2 <= b or kv2 == kv: continue
                        if hav(lat, lon, lat2, lon2) <= radius_m:
                            g.add_edge(b, b2); added += 1
        return added

    # Sn: 孤立成分(≤3バス)のバスを≤150mの他成分バスへ接続
    def add_snap(g, radius_m=150):
        comps = list(nx.connected_components(g))
        comp_of = {b: i for i, c in enumerate(comps) for b in c}
        small = [b for c in comps if len(c) <= 3 for b in c]
        pts = [(binfo[b][0], binfo[b][1], b) for b in net.bus.index
               if binfo[b][0] is not None]
        grid = defaultdict(list); cell = 0.002
        for lat, lon, b in pts:
            grid[(round(lat/cell), round(lon/cell))].append((lat, lon, b))
        added = 0
        for b in small:
            lat, lon, kv, _t = binfo[b]
            if lat is None: continue
            gx, gy = round(lat/cell), round(lon/cell)
            best = None; bestd = radius_m
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for lat2, lon2, b2 in grid.get((gx+dx, gy+dy), ()):
                        if comp_of.get(b2) == comp_of.get(b): continue
                        d = hav(lat, lon, lat2, lon2)
                        if d <= bestd:
                            bestd = d; best = b2
            if best is not None:
                g.add_edge(b, best); comp_of[b] = comp_of[best]; added += 1
        return added

    res = {"island": island, "base_n_comp": base_nc, "n_bus": int(len(net.bus))}

    g = base_graph(); m = add_dedup(g)
    res["D_dedup"] = {"merged_pairs": m, "n_comp": ncomp(g)}
    g = base_graph(); a = add_trafo_radius(g)
    res["Tr_trafo200m"] = {"edges_added": a, "n_comp": ncomp(g)}
    g = base_graph(); a = add_snap(g)
    res["Sn_snap150m"] = {"edges_added": a, "n_comp": ncomp(g)}
    # 累積 D+Tr+Sn
    g = base_graph(); md = add_dedup(g); at = add_trafo_radius(g); asn = add_snap(g)
    res["D+Tr+Sn"] = {"n_comp": ncomp(g),
                      "main_frac": round(max(len(c) for c in nx.connected_components(g))/len(net.bus), 4)}

    json.dump(res, open(out_path, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
