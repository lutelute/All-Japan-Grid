#!/usr/bin/env python3
"""AGCの「事故→復帰」ドラマを1枚で見せる注釈付き波形図(全史デッキ用).

苫東厚真(北海道・1,650MW)と富津(東・5,040MW)のプラント脱落を同じ軸に描き、
「小さい系統は死にかける / 大きい系統は耐える」の対比と、
慣性→UFLS→ガバナ/LFC/EDC の段階を日本語注釈で追えるようにする。

数値はすべて UC→AGC チェーンの実出力(scripts/run_agc_from_uc.py と同一経路)。
連系剛性は docs/data/agc/agc_chain.json の実測値を使う。

出力: docs/slides/ajg/assets/fig_agc_story.png (注釈付き波形)
      docs/slides/ajg/assets/fig_agc_map.png   (同期島別に着色した地図 —
      波形の線色と島の色を一致させ、脱落プラントの実座標にマーカー)
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

from src.uc.scenario import build_national_scenario  # noqa: E402
from src.uc.solver import solve_uc  # noqa: E402
from src.dynamics.agc import (  # noqa: E402
    MultiAreaLFC, Disturbance, build_area_from_uc, largest_online_unit,
    remove_unit_from_area, UFLS_STEPS_HZ)

ISLANDS = {  # island -> (regions, f0)
    "hokkaido": (["hokkaido"], 50.0),
    "east": (["tohoku", "tokyo"], 50.0),
}


def main():
    chain = json.load(open("docs/data/agc/agc_chain.json"))["islands"]
    print("UC求解中...")
    scn = build_national_scenario(scenario="fy2023r2")
    uc = solve_uc(scn.to_uc_parameters())
    assert uc.is_optimal

    results = {}
    for island, (regions, f0) in ISLANDS.items():
        h = chain[island]["peak_hour"]
        tie = {tuple(k.split("-")): v
               for k, v in chain[island]["tie_pu_per_rad"].items()}
        areas = [build_area_from_uc(r, uc, scn.generators, h,
                                    float(scn.net_demand_r[r][h]))
                 for r in regions]
        gen, p_mw = largest_online_unit(uc, scn.generators, h, regions)
        areas = [remove_unit_from_area(a, gen, p_mw) if a.name == gen.region
                 else a for a in areas]
        model = MultiAreaLFC(f0, areas, tie, mode="tbc", ufls=True)
        r = model.simulate(Disturbance(area=gen.region, dp_mw=p_mw,
                                       label=gen.name), t_end=900.0)
        results[island] = (r, gen, p_mw)
        print(f"  {island}: {gen.name} {p_mw:,.0f}MW nadir={r.nadir_hz:+.2f}Hz")

    fig, ax = plt.subplots(figsize=(10.8, 6.2), dpi=150)
    rh, gh, ph = results["hokkaido"]
    re_, ge, pe = results["east"]
    a_h = gh.region
    a_e = ge.region
    ax.plot(re_.t, re_.df_hz[a_e], lw=2.4, color="#FF9500",
            label=f"東日本(需要59GW): 富津 −{pe:,.0f} MW")
    ax.plot(rh.t, rh.df_hz[a_h], lw=2.8, color="#D62728",
            label=f"北海道(需要4.4GW): 苫東厚真 −{ph:,.0f} MW")
    ax.axhline(0, color="#999", lw=0.8)
    # UFLS帯
    ax.axhline(UFLS_STEPS_HZ[0], color="#C62828", lw=0.9, ls="--", alpha=0.6)
    ax.text(895, UFLS_STEPS_HZ[0] - 0.13,
            "この線から下は負荷遮断(UFLS)の領域 — 客の電気を切って系統を守る",
            ha="right", fontsize=10.5, color="#C62828")
    # 注釈: 段階
    ax.annotate("① 発電所が落ちる(t=1s)\n数秒は慣性だけが支える\n北海道は −2.9 Hz/s で急落",
                xy=(6, -2.1), xytext=(60, -2.42), fontsize=11,
                color="#1A1A1A",
                arrowprops=dict(arrowstyle="->", color="#555", lw=1.2))
    ax.annotate("② UFLSが3段で負荷を切り\n落下がようやく止まる(−2.5 Hz)",
                xy=(30, -2.49), xytext=(210, -2.75), fontsize=11,
                arrowprops=dict(arrowstyle="->", color="#555", lw=1.2))
    ax.annotate("③ ガバナ→LFC→EDCの三段構えが\n15分かけてじわじわ戻す",
                xy=(620, rh.df_hz[a_h][6200]), xytext=(430, -1.98),
                fontsize=11,
                arrowprops=dict(arrowstyle="->", color="#555", lw=1.2))
    ax.annotate("大きい系統は同じ事故でも耐える:\n5,040 MW失っても −1.4 Hz で踏みとどまり回復",
                xy=(120, re_.df_hz[a_e][1200]), xytext=(300, -0.6),
                fontsize=11, color="#8A5200",
                arrowprops=dict(arrowstyle="->", color="#FF9500", lw=1.2))
    ax.set_xlim(-15, 900)
    ax.set_ylim(-3.0, 0.35)
    ax.set_xlabel("事故からの時間 [秒]", fontsize=12)
    ax.set_ylabel("周波数のずれ Δf [Hz]", fontsize=12)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=11, loc="lower right")
    fig.tight_layout()
    out = "docs/slides/ajg/assets/fig_agc_story.png"
    fig.savefig(out)
    print(f"-> {out}")
    make_map(results)


ISLAND_OF = {"hokkaido": "hokkaido", "tohoku": "east", "tokyo": "east",
             "chubu": "west", "hokuriku": "west", "kansai": "west",
             "chugoku": "west", "shikoku": "west", "kyushu": "west",
             "okinawa": "okinawa"}
ISLAND_COLOR = {"hokkaido": "#D62728", "east": "#FF9500",
                "west": "#4A5A8A", "okinawa": "#4A5A8A"}
TRIP_XY = {  # 実プラント座標(P03/OSM由来の代表点)
    "苫東厚真": (141.766, 42.533), "富津": (139.796, 35.322)}


def make_map(results):
    """同期島別着色の暗背景地図。波形と同じ色 = 地図上のどの島の話かが繋がる."""
    import math
    from matplotlib.collections import LineCollection
    b = json.load(open("docs/data/built/all.json"))
    k5 = lambda la, lo: (round(la, 5), round(lo, 5))
    isl_of_node = {}
    for nd in b["nodes"]:
        i = ISLAND_OF.get(nd.get("region"))
        if i:
            isl_of_node.setdefault(k5(nd["lat"], nd["lon"]), i)
    segs = {}
    for e in b["edges"]:
        path = e.get("path")
        if not path or len(path) < 2:
            continue
        try:
            a = k5(*e["a"]) if isinstance(e["a"], list) else None
        except Exception:  # noqa: BLE001
            a = None
        isl = isl_of_node.get(a) or isl_of_node.get(
            k5(path[0][0], path[0][1])) or "west"
        segs.setdefault(isl, []).append([(p[1], p[0]) for p in path])
    BG = "#0A0D1A"
    fig = plt.figure(figsize=(9.6, 12.0), dpi=140)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(BG)
    ax.set_xlim(128.3, 146.6)
    ax.set_ylim(30.0, 46.2)
    ax.set_aspect(1.0 / math.cos(math.radians(38.0)))
    ax.axis("off")
    for isl, ss in segs.items():
        ax.add_collection(LineCollection(
            ss, colors=ISLAND_COLOR[isl], linewidths=0.55,
            alpha=0.75 if isl in ("hokkaido", "east") else 0.4, zorder=3))
    # 島ラベル
    for txt, x, y, c in [("北海道 50 Hz", 138.9, 43.6, "#FF6B6B"),
                          ("東日本 50 Hz", 142.9, 37.3, "#FFB84D"),
                          ("西日本 60 Hz", 130.0, 37.8, "#8A97C4")]:
        ax.text(x, y, txt, color=c, fontsize=20, fontweight="bold", zorder=10)
    # 脱落プラントのマーカー(実座標)
    for name, (x, y) in TRIP_XY.items():
        ax.scatter([x], [y], marker="*", s=900, c="#FFFFFF",
                   edgecolors="#D62728", linewidths=2.0, zorder=12)
    ax.annotate("苫東厚真 −1,650 MW\n(2018年に実際の北海道を\n全域停電させた発電所)",
                xy=TRIP_XY["苫東厚真"], xytext=(139.6, 45.3), fontsize=15,
                color="#FFFFFF", zorder=12,
                arrowprops=dict(arrowstyle="->", color="#D62728", lw=2))
    ax.annotate("富津 −5,040 MW", xy=TRIP_XY["富津"],
                xytext=(141.8, 33.4), fontsize=15, color="#FFFFFF", zorder=12,
                arrowprops=dict(arrowstyle="->", color="#FF9500", lw=2))
    out = "docs/slides/ajg/assets/fig_agc_map.png"
    fig.savefig(out, facecolor=BG)
    plt.close(fig)
    print(f"-> {out}")


if __name__ == "__main__":
    main()
