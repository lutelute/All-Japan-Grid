#!/usr/bin/env python3
"""west 単一バス島(≥154kV変電所)の根本原因分類 — 修正方針の決定.

各 単一バス断片(size=1・sub=1・named・≥154kV) について近傍を調べ、分類する:
  T = 変圧器ギャップ: ~150m以内に別電圧のbuilt nodeがある(同一変電所の別階級)
      → build_island_netの変圧器生成が繋げていない = コード修正候補
  S = スナップギャップ: ~600m以内にbuilt edge端点がある(線は近くまで来ている)
      → 短い引込線の欠落/座標ズレ = スナップ許容 or 手動短橋
  M = OSM欠落: ~2km以内に線も別ノードも無い = 連系線が本当に欠落
      → GridStitch編集(A-census)・手動 or 出典付き補完
  R = 鉄道/別事業者の可能性: 名前や近傍から(参考情報)
出力: 分類集計 + 各カテゴリの代表例(名前つき)。
  .venv/bin/python diag_west_lever.py <island> <out.json>
"""
from __future__ import annotations
import json, math, os, sys
from collections import Counter
REPO = "/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid"
sys.path.insert(0, REPO); os.chdir(REPO)


def hav(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1); dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))


def main():
    island = sys.argv[1]; out_path = sys.argv[2]
    import networkx as nx
    from scripts.run_full_powerflow_from_db import (
        BUILT, ISLAND_OF, allocate_loads, attach_generators, build_island_net)
    from scripts.uc_to_pf_built import ISLAND_FREQ
    from src.powerflow.load_estimator import load_demand_config
    from src.powerflow.pref_demand import pref_zone_gwh

    built = json.load(open(BUILT))
    pw, _ = pref_zone_gwh(built["nodes"])
    net, bus_of, _ = build_island_net(island, built["nodes"], built["edges"],
                                      ISLAND_FREQ[island], {})

    # bus -> (lat,lon,kv,name,type)  via geo
    from scripts.run_full_powerflow_from_db import _bus_lonlat
    binfo = {}
    for b in net.bus.index:
        lon, lat = _bus_lonlat(net, b)
        binfo[b] = (lat, lon, float(net.bus.at[b, "vn_kv"]),
                    str(net.bus.at[b, "name"]), net.bus.at[b, "type"])

    g = nx.Graph(); g.add_nodes_from(net.bus.index)
    for _, r in net.line.iterrows():
        if r["in_service"]: g.add_edge(int(r["from_bus"]), int(r["to_bus"]))
    for _, r in net.trafo.iterrows():
        if r["in_service"]: g.add_edge(int(r["hv_bus"]), int(r["lv_bus"]))
    comps = list(nx.connected_components(g))

    # 全built node座標(この島内)と全edge端点座標を準備
    node_pts = [(binfo[b][0], binfo[b][1], binfo[b][2], b)
                for b in net.bus.index if binfo[b][0] is not None]
    edge_pts = []
    for e in built["edges"]:
        edge_pts.append((e["a"][0], e["a"][1]))
        edge_pts.append((e["b"][0], e["b"][1]))

    # 対象: size=1 の変電所(sub, named, ≥154kV)
    targets = []
    for c in comps:
        if len(c) != 1: continue
        (b,) = tuple(c)
        lat, lon, kv, nm, ty = binfo[b]
        if lat is None or kv < 154 or ty == "n" or nm in ("None", ""): continue
        targets.append((b, lat, lon, kv, nm))

    cats = Counter(); examples = {"T": [], "S": [], "M": []}
    for b, lat, lon, kv, nm in targets:
        # T: 150m以内の別電圧built node
        near_node = None
        for nlat, nlon, nkv, nb in node_pts:
            if nb == b: continue
            if hav(lat, lon, nlat, nlon) <= 0.15 and abs(nkv - kv) > 0.5:
                near_node = (nkv, round(hav(lat, lon, nlat, nlon)*1000)); break
        # S: 600m以内のedge端点
        near_edge_km = min((hav(lat, lon, ea, eo) for ea, eo in edge_pts),
                           default=9e9)
        if near_node is not None:
            cat = "T"
        elif near_edge_km <= 0.6:
            cat = "S"
        else:
            cat = "M"
        cats[cat] += 1
        if len(examples[cat]) < 15:
            examples[cat].append({"name": nm, "kv": int(kv),
                                   "near_edge_m": round(near_edge_km*1000),
                                   "near_diffkv_node": near_node})

    rep = {"island": island, "n_targets_ge154_singlebus_sub": len(targets),
           "categories": dict(cats),
           "legend": {"T": "変圧器ギャップ(同一変電所別電圧が150m内・コード修正候補)",
                      "S": "スナップギャップ(edge端点600m内・短橋/座標ズレ)",
                      "M": "OSM欠落(2km内に線なし・GridStitch編集)"},
           "examples": examples}
    json.dump(rep, open(out_path, "w"), ensure_ascii=False, indent=1)
    print(f"[{island}] ≥154kV単一バス変電所島 = {len(targets)}件")
    print(f"  分類: {dict(cats)}")
    for cat in ("T", "S", "M"):
        print(f"  --- {cat}: {rep['legend'][cat]} ---")
        for e in examples[cat][:8]:
            print(f"    {e['name']} {e['kv']}kV near_edge={e['near_edge_m']}m "
                  f"diffkv={e['near_diffkv_node']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
