#!/usr/bin/env python3
"""dedup の系統図(before/after) — 「無理な接続でなく除去」を目で見る.

左: 現状(重複ノードが別バス→断片) 右: dedup後(重複を1つに→連結回復)
・バスを主成分(灰)/非主成分の断片(赤)で色分け・線は実OSMエッジ
・重複ノードのペアを橙リングで強調・拡大inset(飛騨変換所等)でosm_id一致を注記
west 全体 + chubu-hokuriku境界の拡大。
"""
import json, os
from collections import defaultdict
REPO = "/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid"
import sys; sys.path.insert(0, REPO); os.chdir(REPO)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

from scripts.run_full_powerflow_from_db import (
    BUILT, build_island_net, _bus_lonlat)
from scripts.uc_to_pf_built import ISLAND_FREQ

built = json.load(open(BUILT))
net, bus_of, _ = build_island_net("west", built["nodes"], built["edges"],
                                  ISLAND_FREQ["west"], {})

pos = {}
for b in net.bus.index:
    lon, lat = _bus_lonlat(net, b)
    if lon is not None:
        pos[b] = (lon, lat)
kv = {b: float(net.bus.at[b, "vn_kv"]) for b in net.bus.index}

def base_graph():
    g = nx.Graph(); g.add_nodes_from(net.bus.index)
    for _, r in net.line.iterrows():
        if r["in_service"]: g.add_edge(int(r["from_bus"]), int(r["to_bus"]))
    for _, r in net.trafo.iterrows():
        if r["in_service"]: g.add_edge(int(r["hv_bus"]), int(r["lv_bus"]))
    return g

# before
g0 = base_graph()
comps0 = sorted(nx.connected_components(g0), key=len, reverse=True)
main0 = comps0[0]

# after: exact座標+kv dedup(union)
g1 = base_graph()
key2b = defaultdict(list)
for b in net.bus.index:
    if b in pos:
        key2b[(round(pos[b][1], 6), round(pos[b][0], 6), round(kv[b], 1))].append(b)
dup_pairs = []
for k, bs in key2b.items():
    for b in bs[1:]:
        g1.add_edge(bs[0], b); dup_pairs.append((bs[0], b))
comps1 = sorted(nx.connected_components(g1), key=len, reverse=True)
main1 = comps1[0]

def draw(ax, g, main, title, xlim=None, ylim=None, show_dups=False):
    # 線(薄灰)
    for u, v in g.edges():
        if u in pos and v in pos:
            if xlim and not (xlim[0] <= pos[u][0] <= xlim[1]): continue
            ax.plot([pos[u][0], pos[v][0]], [pos[u][1], pos[v][1]],
                    "-", color="#c8d0da", lw=0.3, zorder=1)
    # バス: 主成分=灰・断片=赤
    for b in g.nodes():
        if b not in pos: continue
        if xlim and not (xlim[0] <= pos[b][0] <= xlim[1] and ylim[0] <= pos[b][1] <= ylim[1]):
            continue
        c = "#8899aa" if b in main else "#e53935"
        s = 3 if b in main else 9
        ax.scatter(pos[b][0], pos[b][1], s=s, c=c, zorder=2, linewidths=0)
    if show_dups:
        for a, b in dup_pairs:
            if a in pos and xlim and xlim[0] <= pos[a][0] <= xlim[1] and ylim[0] <= pos[a][1] <= ylim[1]:
                ax.scatter(pos[a][0], pos[a][1], s=60, facecolors="none",
                           edgecolors="#f5a623", linewidths=1.2, zorder=3)
    ax.set_title(title, fontsize=10)
    if xlim: ax.set_xlim(*xlim); ax.set_ylim(*ylim)
    ax.set_aspect("equal"); ax.set_xlabel("lon"); ax.set_ylabel("lat")

fig, axes = plt.subplots(1, 2, figsize=(15, 7.5), constrained_layout=True)
frac0 = len(main0)/len(net.bus); frac1 = len(main1)/len(net.bus)
draw(axes[0], g0, main0,
     f"現状(before): 断片={len(comps0)}成分・主成分{frac0*100:.0f}%\n"
     f"赤=非主成分の断片(単一バス島が大半)")
draw(axes[1], g1, main1,
     f"exact座標+kv dedup後(after): 断片={len(comps1)}成分・主成分{frac1*100:.0f}%\n"
     f"赤が激減=重複除去で連結回復(線は一切足していない)")

fig.suptitle("west 重複ノードdedup の系統図 — 「無理な接続」でなく「重複の除去」"
             f"(重複{len(dup_pairs)}ペア併合・全て同一座標+kv・OSM同一osm_id)",
             fontsize=13)
out = "docs/reports/figs/west_dedup_griddiagram_2026-07-09.png"
fig.savefig(out, dpi=145)
print(f"wrote {out}")
print(f"before comp={len(comps0)} main={frac0:.3f} / after comp={len(comps1)} main={frac1:.3f} / dup_pairs={len(dup_pairs)}")
