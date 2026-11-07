#!/usr/bin/env python3
"""介入#59(案)の図。帳簿(region_dedup_ledger.json の ends)の寄せた点を、全国の地図と 4 か所の前と後で示す。

    PYTHONPATH=. python3 docs/reports/canon_region_dedup_ends_2026-11-07/fig.py [基準の ref(既定 b70cd295)]
→ fig_points.png(全国・種類ごと)・fig_cases.png(4 か所の前と後)
"""
import collections
import json
import math
import os
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
REF = sys.argv[1] if len(sys.argv) > 1 else "b70cd295"
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
k5 = lambda la, lo: (round(la, 5), round(lo, 5))
KIND = {"dangling": ("写しだけが付く行き止まりの端", "#1f77b4"),
        "same_substation": ("同じ変電所の 2 つの点", "#d62728"),
        "substation_pair": ("名前の違う 2 つの変電所の点（同じ線が付く）", "#9467bd"),
        "junction_to_substation": ("線の端の分岐点 → 変電所の点", "#ff7f0e"),
        "other": ("その他", "#7f7f7f")}
REG_C = {"hokkaido": "#8c564b", "tohoku": "#2ca02c", "tokyo": "#d62728", "chubu": "#1f77b4", "hokuriku": "#17becf",
         "kansai": "#ff7f0e", "chugoku": "#9467bd", "shikoku": "#bcbd22", "kyushu": "#e377c2", "okinawa": "#7f7f7f"}
# 4 か所: (帳簿の寄せる点に付く線の名前の一部, 見出し)
CASES = [("山代線", "大聖寺（南郷町）変電所 8 m"), ("屋敷ノ入変電所~花咲変電所線", "花咲変電所 342 m（分岐点→変電所）"),
         ("阿波変電所~鉢変電所線", "阿南周波数変換所 96 m（行き止まり）"), ("足柄線", "扇町五丁目変電所 294 m")]


def shapes(d):
    by = collections.defaultdict(list)
    for e in d["edges"]:
        if e.get("tie"):
            continue
        p = tuple(k5(*q) for q in (e.get("path") or [e["a"], e["b"]]))
        by[min(p, p[::-1])].append(e)
    return by


def draw(ax, d, c, r_m, title):
    lat0, lon0 = c
    dla = r_m / 111320.0
    dlo = r_m / (111320.0 * math.cos(math.radians(lat0)))
    box = (lat0 - dla, lat0 + dla, lon0 - dlo, lon0 + dlo)
    inb = lambda q: box[0] <= q[0] <= box[1] and box[2] <= q[1] <= box[3]
    by = shapes(d)
    dup = {id(e) for es in by.values() if len(es) > 1 for e in es}
    segs, cols, lws = [], [], []
    for e in d["edges"]:
        p = e.get("path") or [e["a"], e["b"]]
        pts = [e["a"]] + p + [e["b"]]
        if not any(inb(q) for q in pts):
            continue
        # 線の端の点と頂点の並びのずれも見えるように、端の点から頂点の並びへつないで描く
        seq = [e["a"]] + p + [e["b"]] if math.dist(e["a"], p[0]) <= math.dist(e["a"], p[-1]) else [e["a"]] + p[::-1] + [e["b"]]
        segs.append([(q[1], q[0]) for q in seq])
        cols.append("#d62728" if id(e) in dup else "#555555")
        lws.append(2.2 if id(e) in dup else 0.9)
    ax.add_collection(LineCollection(segs, colors=cols, linewidths=lws, zorder=1))
    seen = set()
    for n in d["nodes"]:
        q = (n["lat"], n["lon"])
        if not inb(q):
            continue
        key = (k5(*q), n.get("region"))
        if key in seen:
            continue
        seen.add(key)
        ax.scatter([q[1]], [q[0]], s=70 if n.get("sub") else 18, marker="s" if n.get("sub") else "o",
                   facecolors=REG_C.get(n.get("region"), "#000") if n.get("sub") else "white",
                   edgecolors=REG_C.get(n.get("region"), "#000"), linewidths=1.4, zorder=3, alpha=0.85)
    ax.set_xlim(box[2], box[3])
    ax.set_ylim(box[0], box[1])
    ax.set_aspect(1 / math.cos(math.radians(lat0)))
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(title, fontsize=10)


def main():
    b = json.loads(subprocess.run(["git", "show", f"{REF}:docs/data/built/all.json"], cwd=ROOT,
                                  capture_output=True, text=True, check=True).stdout)
    a = json.load(open(os.path.join(ROOT, "docs/data/built/all.json"), encoding="utf-8"))
    led = json.load(open(os.path.join(ROOT, "docs/data/fragments/region_dedup_ledger.json"), encoding="utf-8"))["ends"]
    rows = led["rows"]
    # 全国
    fig, ax = plt.subplots(figsize=(9, 9.5))
    segs = [[(q[1], q[0]) for q in (e.get("path") or [e["a"], e["b"]])] for e in a["edges"]]
    ax.add_collection(LineCollection(segs, colors="#d0d0d0", linewidths=0.3, zorder=1))
    cnt = collections.Counter(r["kind"] for r in rows)
    for k, (lab, col) in KIND.items():
        rs = [r for r in rows if r["kind"] == k]
        if rs:
            ax.scatter([r["to"][1] for r in rs], [r["to"][0] for r in rs], s=40, c=col, edgecolors="k", linewidths=0.4,
                       zorder=3, label=f"{lab}（{cnt[k]}）")
    ax.set_xlim(129.5, 142.5)
    ax.set_ylim(31.0, 39.5)
    ax.set_aspect(1 / math.cos(math.radians(35)))
    ax.set_xticks([])
    ax.set_yticks([])
    ax.legend(loc="lower right", fontsize=9)
    ax.set_title(f"端の点を寄せた所 {len(rows)} か所（地域の境）。形が同じで端の違う写しの組: "
                 f"前 {sum(1 for es in shapes(b).values() if len(es) > 1 and len({frozenset((k5(*e['a']), k5(*e['b']))) for e in es}) > 1)}"
                 f" → 後 {sum(1 for es in shapes(a).values() if len(es) > 1 and len({frozenset((k5(*e['a']), k5(*e['b']))) for e in es}) > 1)}",
                 fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig_points.png"), dpi=100)
    # 4 か所
    fig, axs = plt.subplots(2, 4, figsize=(18, 9.5))
    for j, (needle, title) in enumerate(CASES):
        r = next(r for r in rows if any(needle in x for x in r["lines"]))
        c = ((r["from"][0] + r["to"][0]) / 2, (r["from"][1] + r["to"][1]) / 2)
        rad = max(250.0, r["gap_m"] * 1.6)
        draw(axs[0][j], b, c, rad, f"前: {title}")
        draw(axs[1][j], a, c, rad, f"後: {title}")
    handles = [plt.Line2D([], [], color="#d62728", lw=2.2, label="同じ形の枝が 2 本（地域の写し）"),
               plt.Line2D([], [], color="#555555", lw=0.9, label="枝（端の点から頂点の並びへ）")]
    handles += [plt.Line2D([], [], marker="s", ls="", color=REG_C[g], label=f"{g} の変電所の点")
                for g in ("tohoku", "tokyo", "chubu", "hokuriku", "chugoku", "shikoku", "kansai")]
    fig.legend(handles=handles, loc="lower center", ncol=5, fontsize=9)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(os.path.join(HERE, "fig_cases.png"), dpi=100)
    print("ok")


if __name__ == "__main__":
    main()
