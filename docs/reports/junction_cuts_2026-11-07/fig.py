#!/usr/bin/env python3
"""介入#57 の前と後の図。

  fig_national.png : 全国の地図の対。左=前(分岐点の変圧器 96 台)・右=後(80 台)。外した 16 台は右で丸を付ける
  fig_points.png   : 台帳の当てる点(adopt=true)の拡大(±2.5 km)。線は電圧の色、★=前にあった分岐点の変圧器、
                     橙の太線=後で主系統(その島の最大の連結成分)から外れた線

    PYTHONPATH=. python3 docs/reports/junction_cuts_2026-11-07/fig.py
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

import src.powerflow.full_from_built as F  # noqa: E402
from src.powerflow.junction_cuts import load_cut_points  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
plt.rcParams["font.family"] = ["Hiragino Sans", "Noto Sans CJK JP", "IPAexGothic", "sans-serif"]
KV_COLOR = {500: "#d62728", 275: "#ff7f0e", 220: "#e377c2", 187: "#bcbd22", 154: "#2ca02c", 132: "#17becf",
            110: "#9467bd", 77: "#1f77b4", 66: "#7f7f7f"}


def kv_color(kv):
    if not kv:
        return "#bbbbbb"
    best = min(KV_COLOR, key=lambda k: abs(k - kv))
    return KV_COLOR[best]


def geo_of(net, b):
    g = net.bus.at[b, "geo"]
    lon, lat = (json.loads(g) if isinstance(g, str) else g)["coordinates"]
    return lat, lon


def junction_trafos(net):
    bt = net.bus["type"]
    out = []
    for _, r in net.trafo.iterrows():
        if bt[int(r.hv_bus)] == "n" and bt[int(r.lv_bus)] == "n":
            la, lo = geo_of(net, int(r.hv_bus))
            out.append((round(la, 5), round(lo, 5), float(r.vn_hv_kv), float(r.vn_lv_kv), "#43a" in str(r["name"])))
    return out


def main_component_lines(net):
    g = nx.Graph()
    g.add_nodes_from(int(b) for b in net.bus.index)
    for li, r in net.line.iterrows():
        if bool(r.in_service):
            g.add_edge(int(r.from_bus), int(r.to_bus))
    for _, r in net.trafo.iterrows():
        if bool(r.in_service):
            g.add_edge(int(r.hv_bus), int(r.lv_bus))
    main = max(nx.connected_components(g), key=len)
    return {int(li) for li, r in net.line.iterrows() if int(r.from_bus) in main}


def main():
    db = json.load(open(F.BUILT, encoding="utf-8"))
    pts = load_cut_points()
    res = {}
    for island in ("east", "west"):
        for tag, jc in (("before", False), ("after", True)):
            geom = {}
            nodes = json.loads(json.dumps(db["nodes"]))
            net, _b, st = F.build_island_net(island, nodes, db["edges"], F.ISLAND_FREQ[island], geom, junction_cuts=jc)
            res[(island, tag)] = (net, geom)
    jt = {tag: [t for isl in ("east", "west") for t in junction_trafos(res[(isl, tag)][0])] for tag in ("before", "after")}
    # 北海道・沖縄は前後で同じ(北海道 0 台・沖縄 1 台)。全国の数にそろえて足す
    extra = []
    for island in ("hokkaido", "okinawa"):
        nodes = json.loads(json.dumps(db["nodes"]))
        net, _b, _s = F.build_island_net(island, nodes, db["edges"], F.ISLAND_FREQ[island], {})
        extra += junction_trafos(net)
    for tag in jt:
        jt[tag] += extra
    removed = set((t[0], t[1]) for t in jt["before"]) - set((t[0], t[1]) for t in jt["after"])

    # ── 全国の地図の対 ──
    segs, cols, lws = [], [], []
    for e in db["edges"]:
        p = e.get("path") or [e["a"], e["b"]]
        segs.append([(q[1], q[0]) for q in p])
        cols.append("#c8c8c8" if (e.get("kv") or 0) < 150 else "#9a9a9a")
        lws.append(0.25 if (e.get("kv") or 0) < 150 else 0.5)
    fig, axs = plt.subplots(1, 2, figsize=(16, 9.5))
    for ax, tag in zip(axs, ("before", "after")):
        ax.add_collection(LineCollection(segs, colors=cols, linewidths=lws, zorder=1))
        ts = jt[tag]
        for is43 in (False, True):
            xs = [t[1] for t in ts if t[4] == is43]
            ys = [t[0] for t in ts if t[4] == is43]
            ax.scatter(xs, ys, s=22, marker="^" if is43 else "o", c="#d62728" if not is43 else "#9467bd",
                       edgecolors="white", linewidths=0.5, zorder=3,
                       label=("#43a の変圧器" if is43 else "同じ座標の変圧器") + f"({len(xs)})")
        if tag == "after":
            rx = [lo for la, lo in removed]
            ry = [la for la, lo in removed]
            ax.scatter(rx, ry, s=120, facecolors="none", edgecolors="#ff7f0e", linewidths=1.6, zorder=4,
                       label=f"介入#57 で外した({len(removed)})")
        ax.set_xlim(127.5, 146.0)
        ax.set_ylim(26.0, 45.6)
        ax.set_aspect(1 / math.cos(math.radians(36)))
        ax.set_title(("前" if tag == "before" else "後（介入#57）") + f": 潮流計算の網で変電所でない点に張られた変圧器 {len(ts)} 台",
                     fontsize=13)
        ax.legend(loc="lower right", fontsize=10, framealpha=0.9)
        ax.set_xticks([])
        ax.set_yticks([])
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig_national.png"), dpi=110)
    plt.close(fig)

    # ── 17 か所の拡大 ──
    items = sorted(pts.values(), key=lambda it: it["no"])
    n = len(items)
    ncol = 4
    nrow = math.ceil(n / ncol)
    fig, axs = plt.subplots(nrow, ncol, figsize=(4.4 * ncol, 4.6 * nrow))
    axs = axs.ravel()
    R = 2.5 / 111.0
    before_jt = {(t[0], t[1]): t for t in jt["before"]}
    for ax, it in zip(axs, items):
        la0, lo0 = it["lat"], it["lon"]
        kx = math.cos(math.radians(la0))
        for e in db["edges"]:
            p = e.get("path") or [e["a"], e["b"]]
            if not any(abs(q[0] - la0) < R * 1.4 and abs(q[1] - lo0) < R * 1.4 / kx for q in p):
                continue
            ax.plot([q[1] for q in p], [q[0] for q in p], color=kv_color(e.get("kv")), lw=1.4, zorder=2)
        # 後で主系統から外れた線(その島の網で)
        for island in ("east", "west"):
            net_a, geom_a = res[(island, "after")]
            net_b, _g = res[(island, "before")]
            main_a = main_component_lines(net_a)
            main_b = main_component_lines(net_b)
            for li, r in net_a.line.iterrows():
                li = int(li)
                if li in main_a or li not in main_b:
                    continue
                a, b = geo_of(net_a, int(r.from_bus)), geo_of(net_a, int(r.to_bus))
                if not any(abs(q[0] - la0) < R * 1.4 and abs(q[1] - lo0) < R * 1.4 / kx for q in (a, b)):
                    continue
                path = geom_a.get(((round(a[0], 5), round(a[1], 5)), (round(b[0], 5), round(b[1], 5))))
                xy = [(c[0], c[1]) for c in path] if path else [(a[1], a[0]), (b[1], b[0])]
                ax.plot([q[0] for q in xy], [q[1] for q in xy], color="#ff7f0e", lw=4.5, alpha=0.55, zorder=1)
        t = before_jt.get((round(la0, 5), round(lo0, 5)))
        ax.scatter([lo0], [la0], s=180 if t else 60, marker="*" if t else "o", c="#d62728" if t else "#555555",
                   edgecolors="white", zorder=4)
        ax.set_xlim(lo0 - R / kx, lo0 + R / kx)
        ax.set_ylim(la0 - R, la0 + R)
        ax.set_aspect(1 / kx)
        ax.set_xticks([])
        ax.set_yticks([])
        kvs = "×".join(f"{k:.0f}" for k in sorted(it["kvs"], reverse=True))
        head = f"#{it['no']} {it['region']} {kvs} kV" + ("（写し）" if it.get("kind") == "duplicate" else "")
        sub = (f"前: {t[2]:.0f}/{t[3]:.0f} kV の変圧器" + ("(#43a)" if t[4] else "")) if t else "前: 変圧器なし(別の同期系統)"
        ax.set_title(head + "\n" + sub + " → 後: なし", fontsize=9.5)
        nm = " / ".join(x[:14] for x in it["names"][:3])
        ax.text(0.01, 0.01, nm, transform=ax.transAxes, fontsize=7, color="#333333",
                bbox=dict(facecolor="white", alpha=0.75, edgecolor="none", pad=1.5))
    for ax in axs[n:]:
        ax.axis("off")
    handles = [plt.Line2D([], [], color=c, lw=2, label=f"{k} kV") for k, c in KV_COLOR.items()]
    handles += [plt.Line2D([], [], color="#ff7f0e", lw=5, alpha=0.55, label="後で主系統から外れた線"),
                plt.Line2D([], [], marker="*", color="#d62728", lw=0, markersize=12, label="前にあった分岐点の変圧器")]
    fig.legend(handles=handles, loc="lower center", ncol=6, fontsize=9, frameon=False)
    fig.suptitle(f"介入#57: 変圧器を張らない分岐点 {n} か所（航空写真と OSM の way で確かめた・±2.5 km）", fontsize=14)
    fig.tight_layout(rect=(0, 0.04, 1, 0.97))
    fig.savefig(os.path.join(HERE, "fig_points.png"), dpi=100)
    plt.close(fig)
    print("前", len(jt["before"]), "後", len(jt["after"]), "外した", len(removed))


if __name__ == "__main__":
    main()
