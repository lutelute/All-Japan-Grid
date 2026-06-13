#!/usr/bin/env python3
"""I6-5 island classifier — build後の実態(degree・近傍build後ノード)で島を分類する。

台帳110で判明: `d4_island_audit` の line_centric座標照合は孤立変電所を「同一feature分断」と
誤判定する(母線=線終端クラスタ平均が生OSM線から離れるため)。本分類器は build後グラフの
実態だけで分類し、真に繋げる島を取り出す:

  - isolated_sub : degree-0 のみの島(線が1本も繋がっていない孤立変電所)。
                   線の吸着漏れ or OSMに線が無い → 個別調査/除外/負荷バス化
  - weld         : 線を持ち、端点が主系統に近接(< near_km)かつ同電圧 → 証拠ベース接合の対象
  - mid / far    : near_km..far_km / > far_km

物理接続=真の原則(owner 2026-06-13): 距離や line_centric座標でなく、build後の実態
(線を持つか・端点が同電圧で近接か)で「繋ぐべき島」を見極める。

    PYTHONPATH=. python3 scripts/d4_island_classify.py --region tokyo --out docs/reports/island_classify_tokyo.json
"""
import sys
import json
import math
import argparse

import numpy as np
import networkx as nx
from scipy.spatial import cKDTree

from src.powerflow.snapped_topology import build_network_snapped


def _xy(lat: float, lon: float):
    return (lon * 111.0 * math.cos(math.radians(lat)), lat * 111.0)


def classify(region: str, near_km: float = 0.3, far_km: float = 5.0):
    net = build_network_snapped(region)
    if net is None:
        return None
    pos = {s.id: (s.latitude, s.longitude) for s in net.substations}
    kv = {s.id: float(s.voltage_kv) for s in net.substations}
    g = nx.Graph()
    g.add_nodes_from(s.id for s in net.substations)
    for ln in net.transmission_lines:
        g.add_edge(ln.from_substation_id, ln.to_substation_id)
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    if not comps:
        return None
    main = set(comps[0])
    islands = comps[1:]
    main_ids = sorted(main)
    main_xy = np.array([_xy(*pos[n]) for n in main_ids])
    tree = cKDTree(main_xy)

    buckets = {"isolated_sub": [], "weld": [], "mid": [], "far": []}
    for isl in islands:
        # 線を1本も持たない島 = 孤立変電所(degree-0 のみ)
        if not any(g.degree(n) >= 1 for n in isl):
            ids = [n for n in isl if n in pos]
            buckets["isolated_sub"].append({
                "n_nodes": len(isl),
                "pt": ([round(pos[ids[0]][0], 5), round(pos[ids[0]][1], 5)]
                       if ids else None),
                "sample_id": ids[0] if ids else None,
            })
            continue
        inodes = [n for n in isl if n in pos]
        ixy = np.array([_xy(*pos[n]) for n in inodes])
        d, idx = tree.query(ixy)
        k = int(d.argmin())
        mind = float(d[k])
        inode = inodes[k]
        mnode = main_ids[idx[k]]
        same_kv = abs(kv.get(inode, 0.0) - kv.get(mnode, 0.0)) < 1
        rec = {
            "n_nodes": len(isl),
            "min_km": round(mind, 3),
            "kv": kv.get(inode, 0.0),
            "same_kv": same_kv,
            "island_node": inode,
            "main_node": mnode,
            "island_pt": [round(pos[inode][0], 5), round(pos[inode][1], 5)],
            "main_pt": [round(pos[mnode][0], 5), round(pos[mnode][1], 5)],
        }
        if mind < near_km and same_kv:
            buckets["weld"].append(rec)
        elif mind < far_km:
            buckets["mid"].append(rec)
        else:
            buckets["far"].append(rec)
    for b in ("weld", "mid", "far"):
        buckets[b].sort(key=lambda r: r["min_km"])
    summary = {
        "region": region,
        "n_islands": len(islands),
        "near_km": near_km,
        "far_km": far_km,
        "counts": {k: len(v) for k, v in buckets.items()},
    }
    return summary, buckets


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", default="tokyo")
    ap.add_argument("--near-km", type=float, default=0.3)
    ap.add_argument("--far-km", type=float, default=5.0)
    ap.add_argument("--out")
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args(argv)
    res = classify(a.region, a.near_km, a.far_km)
    if res is None:
        print("no network")
        return 1
    summary, buckets = res
    print(json.dumps(summary, ensure_ascii=False))
    print(f"\n-- weld候補(端点近接<{a.near_km}km・同電圧) top {a.top} --")
    for r in buckets["weld"][: a.top]:
        print(f"  {r['min_km'] * 1000:.0f}m kv{r['kv']:.0f} nodes={r['n_nodes']}"
              f"  {r['island_node']} -> {r['main_node']}")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump({"summary": summary, "buckets": buckets}, fh,
                      ensure_ascii=False, indent=1)
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
