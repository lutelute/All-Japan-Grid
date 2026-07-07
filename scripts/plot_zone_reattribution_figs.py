#!/usr/bin/env python3
"""zone再属性(A案)のbefore/after図 — 事例記録(case_study_phantom_tie)の図を決定的に再生成.

出力: docs/reports/figs/fig_zone_reattr_*.png, fig_east_slack_arc.png
使い方: PYTHONPATH=. .venv/bin/python scripts/plot_zone_reattribution_figs.py
"""
import copy
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
ROOT = "/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid"
sys.path.insert(0, ROOT)
os.chdir(ROOT)
OUT = os.path.join(ROOT, "docs", "reports", "figs")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from src.powerflow.region_attribution import reattribute_node_regions

# 検証済みカテゴリカル(validate_palette ALL PASS)
COLOR = {"chubu": "#4443A6", "hokuriku": "#2C7FB8", "kansai": "#1B7837",
         "chugoku": "#B8860B", "shikoku": "#C25B70", "kyushu": "#8B2252",
         "tokyo": "#44AA99", "tohoku": "#999933", "hokkaido": "#AA4499",
         "okinawa": "#888888"}
CROSS = "#CC3311"

d = json.load(open("docs/data/built/all.json"))
nodes_before = d["nodes"]
edges = d["edges"]
nodes_after = copy.deepcopy(nodes_before)
stats = reattribute_node_regions(nodes_after)
print("reattr:", stats["n_changed"], "changed")


def crossing_edges(nodes):
    by = {}
    for n in nodes:
        by[(round(n["lat"], 5), round(n["lon"], 5), n.get("kv"))] = n["region"]
    out = []
    for e in edges:
        ra = by.get((round(e["a"][0], 5), round(e["a"][1], 5), e.get("kv")))
        rb = by.get((round(e["b"][0], 5), round(e["b"][1], 5), e.get("kv")))
        if ra and rb and ra != rb:
            out.append((e, ra, rb))
    return out


def draw_panel(ax, nodes, cross, extent, title, phantom_pairs=()):
    lat0, lat1, lon0, lon1 = extent
    xs, ys, cs = [], [], []
    for n in nodes:
        if lat0 <= n["lat"] <= lat1 and lon0 <= n["lon"] <= lon1:
            xs.append(n["lon"]); ys.append(n["lat"])
            cs.append(COLOR.get(n["region"], "#bbbbbb"))
    ax.scatter(xs, ys, c=cs, s=2.5, linewidths=0, rasterized=True)
    n_cross = 0
    for e, ra, rb in cross:
        mlat = (e["a"][0] + e["b"][0]) / 2
        mlon = (e["a"][1] + e["b"][1]) / 2
        if not (lat0 <= mlat <= lat1 and lon0 <= mlon <= lon1):
            continue
        pair = tuple(sorted((ra, rb)))
        is_ph = pair in phantom_pairs
        ax.plot([e["a"][1], e["b"][1]], [e["a"][0], e["b"][0]],
                color="#111111" if is_ph else CROSS,
                lw=2.6 if is_ph else 1.1,
                ls="--" if is_ph else "-",
                alpha=0.95 if is_ph else 0.75, zorder=5)
        n_cross += 1
    ax.set_title(f"{title}\n(この範囲の地域跨ぎ線 {n_cross}本)", fontsize=11)
    ax.set_xlim(lon0, lon1); ax.set_ylim(lat0, lat1)
    ax.set_aspect(1.2)
    ax.grid(True, lw=0.3, color="#dddddd")
    ax.tick_params(labelsize=7)
    return n_cross


plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
cross_b = crossing_edges(nodes_before)
cross_a = crossing_edges(nodes_after)

# ── 図1: west広域 before/after ──
fig, axes = plt.subplots(1, 2, figsize=(15, 7.2))
ext = (32.5, 37.2, 129.5, 137.6)
draw_panel(axes[0], nodes_before, cross_b, ext,
           "before — region=抽出bbox出所(旧)",
           phantom_pairs={("kyushu", "shikoku")})
draw_panel(axes[1], nodes_after, cross_a, ext,
           "after — region=領土(座標→県→エリア)")
handles = [Line2D([], [], marker="o", ls="", color=COLOR[r], label=r, ms=7)
           for r in ["chubu", "hokuriku", "kansai", "chugoku",
                     "shikoku", "kyushu"]]
handles += [Line2D([], [], color=CROSS, lw=1.6, label="地域跨ぎ線(tie集計対象)"),
            Line2D([], [], color="#111111", lw=2.6, ls="--",
                   label="幻tie kyushu↔shikoku")]
fig.legend(handles=handles, loc="lower center", ncol=8, fontsize=9,
           frameon=False)
fig.suptitle("zone再属性(A案) before/after — west島の地域ラベルと跨ぎ線"
             "(物理接続は不変)", fontsize=13)
fig.tight_layout(rect=[0, 0.05, 1, 1])
p1 = os.path.join(OUT, "fig_zone_reattr_west_before_after.png")
fig.savefig(p1, dpi=150); plt.close(fig)
print("->", p1)

# ── 図2: 山口県ズーム(幻tieの現場) ──
fig, axes = plt.subplots(1, 2, figsize=(14, 6.4))
ext2 = (33.6, 34.6, 130.7, 132.6)
draw_panel(axes[0], nodes_before, cross_b, ext2,
           "before — 山口県にkyushu/shikokuラベルが混入",
           phantom_pairs={("kyushu", "shikoku")})
draw_panel(axes[1], nodes_after, cross_a, ext2,
           "after — 山口県=chugoku・跨ぎ線は関門のみ")
fig.legend(handles=handles, loc="lower center", ncol=8, fontsize=9,
           frameon=False)
fig.suptitle("幻tie「kyushu↔shikoku 445MW」の現場(山口県) — "
             "黒破線=幻tieの実体(中国電力の域内系統)", fontsize=13)
fig.tight_layout(rect=[0, 0.05, 1, 1])
p2 = os.path.join(OUT, "fig_zone_reattr_yamaguchi.png")
fig.savefig(p2, dpi=150); plt.close(fig)
print("->", p2)

# ── 図3: east slackの弧 ──
fig, ax = plt.subplots(figsize=(9, 4.6))
steps = [("full v4銘板\n(07-05)", 25.5),
         ("backbone\n断片電源復帰(07-05)", 9.2),
         ("+bridge\n容量較正(07-07)", 7.41),
         ("+境界注入\nFC/北本(07-07)", 3.06)]
xs = range(len(steps))
vals = [v for _, v in steps]
bars = ax.bar(xs, vals, width=0.55, color="#4443A6", zorder=3)
ax.bar(xs[-1], vals[-1], width=0.55, color="#1B7837", zorder=4)
ax.axhline(3.03, color="#B8860B", lw=2, ls="--", zorder=2)
ax.annotate("損失 3.03%(物理的に正当)", xy=(0.02, 3.03),
            xytext=(0.02, 4.2), fontsize=10, color="#7a5a08")
for x, v in zip(xs, vals):
    ax.annotate(f"{v:.2f}%" if v < 10 else f"{v:.1f}%",
                xy=(x, v), xytext=(0, 4), textcoords="offset points",
                ha="center", fontsize=11, fontweight="bold")
ax.set_xticks(list(xs))
ax.set_xticklabels([s for s, _ in steps], fontsize=9.5)
ax.set_ylabel("mean |slack| / 需要 (%)", fontsize=10)
ax.set_title("east島 slackの弧 — UC断面とOSM由来PF網の需給整合"
             "(最終: slack 3.06% ≒ 損失3.03%・残差+0.02%)", fontsize=12)
ax.grid(axis="y", lw=0.3, color="#dddddd", zorder=0)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
p3 = os.path.join(OUT, "fig_east_slack_arc.png")
fig.savefig(p3, dpi=150); plt.close(fig)
print("->", p3)
