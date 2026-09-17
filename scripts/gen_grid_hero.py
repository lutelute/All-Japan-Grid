#!/usr/bin/env python3
"""全国系統のヒーロー画像(暗背景・電圧クラス発光) — 全史デッキの「掴み」用.

built正典(docs/data/built/all.json)の実線形19,895本を、暗背景に電圧クラス色の
二度描き(太い低α + 細い高α)でグロー風に描く。左側にタイトル用の余白を残した
16:9。沖縄は枠外のため左下にインセットで入れる(10エリア全部を描く)。

出力: docs/slides/ajg/assets/hero_grid.png (3200x1800)
      docs/slides/ajg/assets/hero_grid_raw.png (同構図・単色細線 = 「素材」比較用)

捏造ゼロ: 描いているのは built モデルの実線形と実ノードのみ。装飾は色と線幅だけ。
"""
from __future__ import annotations

import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection

BG = "#0A0D1A"
KV_STYLE = [  # (min_kv, color, lw_glow, lw_core, alpha_core, zorder)
    (400, "#FF3B30", 3.2, 1.1, 0.95, 6),   # 500級
    (250, "#FF9500", 2.4, 0.9, 0.90, 5),   # 275級
    (140, "#BF5AF2", 1.6, 0.7, 0.80, 4),   # 154/187級
    (90,  "#34C759", 1.2, 0.55, 0.65, 3),  # 110級
    (40,  "#32ADE6", 0.9, 0.45, 0.45, 2),  # 66/77級
    (0,   "#8E8E93", 0.0, 0.35, 0.30, 1),  # 不明・配電
]


def style_of(kv):
    for mn, c, lg, lc, a, z in KV_STYLE:
        if kv >= mn:
            return c, lg, lc, a, z
    return KV_STYLE[-1][1:]


def draw(ax, edges, nodes, raw=False):
    segs_by_style = {}
    for e in edges:
        try:
            kv = float(e.get("kv") or 0)
        except ValueError:
            kv = 0.0
        path = e.get("path")
        if not path or len(path) < 2:
            continue
        xy = [(p[1], p[0]) for p in path]
        key = style_of(kv)
        segs_by_style.setdefault(key, []).append(xy)
    for (c, lg, lc, a, z), segs in sorted(segs_by_style.items(),
                                          key=lambda kv_: kv_[0][4]):
        if raw:
            ax.add_collection(LineCollection(
                segs, colors="#C8CDD8", linewidths=0.35, alpha=0.8, zorder=2))
            continue
        if lg > 0:   # グロー(太い低α)
            ax.add_collection(LineCollection(
                segs, colors=c, linewidths=lg, alpha=0.16, zorder=z,
                capstyle="round"))
        ax.add_collection(LineCollection(
            segs, colors=c, linewidths=lc, alpha=a, zorder=z + 6,
            capstyle="round"))
    if not raw:
        xs = [n["lon"] for n in nodes if n.get("sub")]
        ys = [n["lat"] for n in nodes if n.get("sub")]
        ax.scatter(xs, ys, s=0.5, c="#FFFFFF", alpha=0.22, zorder=20,
                   linewidths=0)


def main():
    b = json.load(open("docs/data/built/all.json"))
    edges, nodes = b["edges"], b["nodes"]
    for raw, name in ((False, "hero_grid.png"), (True, "hero_grid_raw.png")):
        fig = plt.figure(figsize=(32, 18), dpi=100)
        fig.patch.set_facecolor(BG)
        # 本土: 右寄せ(左にタイトル余白)。緯度圧縮は cos(38°)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_facecolor(BG)
        ax.set_xlim(114.5, 148.5)
        ax.set_ylim(30.0, 46.2)
        ax.set_aspect(1.0 / math.cos(math.radians(38.0)))
        ax.axis("off")
        draw(ax, edges, nodes, raw=raw)
        # 沖縄インセット(左下)
        axo = fig.add_axes([0.045, 0.06, 0.14, 0.22])
        axo.set_facecolor(BG)
        axo.set_xlim(127.5, 128.4)
        axo.set_ylim(26.0, 26.95)
        axo.set_aspect(1.0 / math.cos(math.radians(26.5)))
        axo.axis("off")
        draw(axo, edges, nodes, raw=raw)
        for sp in axo.spines.values():
            sp.set_visible(True)
            sp.set_color("#2A3050")
        axo.text(0.03, 0.95, "OKINAWA", transform=axo.transAxes,
                 color="#5A648F", fontsize=15, family="Helvetica Neue",
                 va="top")
        out = f"docs/slides/ajg/assets/{name}"
        fig.savefig(out, facecolor=BG)
        plt.close(fig)
        print(f"-> {out}")


if __name__ == "__main__":
    main()
