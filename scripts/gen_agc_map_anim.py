#!/usr/bin/env python3
"""事故→UFLS→復帰 を地図の上で見せるアニメGIF(苫東厚真トリップ・北海道).

暗背景の実系統地図(built正典の実線形)の上で:
  - 北海道の線の色が周波数に追従して変わる(正常=青白 → 深赤=UFLS域)
  - ★=苫東厚真が t=1s で消灯(X印)
  - 遮断された負荷ぶんだけ、北海道のノード(変電所)がランダム消灯
    (どの変電所を切るかは公開されていないため「量だけ本物・場所は演出」と明記)
  - HUD: 時刻 / 周波数 / 遮断量 / 段階の説明テキスト
時間軸は可変速(事故直後はスローモーション、復帰はタイムラプス)。

シミュレーションは scripts/run_agc_from_uc.py と同一経路の実出力。
出力: docs/slides/ajg/assets/agc_hokkaido_trip.gif
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

from src.uc.scenario import build_national_scenario  # noqa: E402
from src.uc.solver import solve_uc  # noqa: E402
from src.dynamics.agc import (  # noqa: E402
    MultiAreaLFC, Disturbance, build_area_from_uc, largest_online_unit,
    remove_unit_from_area)

BG = "#0A0D1A"
TRIP_XY = (141.766, 42.533)          # 苫東厚真(実座標)
# 可変速タイムライン: (シミュレーション秒, 画面に留まるフレーム数)
TIMELINE = ([(-3 + 0.5 * i, 2) for i in range(6)] +          # 事故前3秒
            [(1.0 + 0.25 * i, 3) for i in range(24)] +       # 直後6秒スロー
            [(7 + 1.5 * i, 2) for i in range(16)] +          # 〜30秒
            [(31 + 8 * i, 1) for i in range(34)] +           # 〜5分
            [(300 + 40 * i, 1) for i in range(16)])          # 〜15分


def freq_color(df_hz):
    """Δf → 線色。0=青白 → −1.5(UFLS線)=橙 → −2.5=深赤."""
    x = min(max(-df_hz / 2.5, 0.0), 1.0)
    # 3点グラデ: (0.62,0.78,1.0) → (1.0,0.55,0.1) → (0.9,0.08,0.08)
    if x < 0.6:
        u = x / 0.6
        c0, c1 = np.array([0.62, 0.78, 1.0]), np.array([1.0, 0.55, 0.1])
    else:
        u = (x - 0.6) / 0.4
        c0, c1 = np.array([1.0, 0.55, 0.1]), np.array([0.9, 0.08, 0.08])
    return tuple(c0 + (c1 - c0) * u)


def main():
    print("UC求解中...")
    scn = build_national_scenario(scenario="fy2023r2")
    uc = solve_uc(scn.to_uc_parameters())
    assert uc.is_optimal
    chain = json.load(open("docs/data/agc/agc_chain.json"))["islands"]
    h = chain["hokkaido"]["peak_hour"]
    areas = [build_area_from_uc("hokkaido", uc, scn.generators, h,
                                float(scn.net_demand_r["hokkaido"][h]))]
    gen, p_mw = largest_online_unit(uc, scn.generators, h, ["hokkaido"])
    areas = [remove_unit_from_area(areas[0], gen, p_mw)]
    model = MultiAreaLFC(50.0, areas, {}, mode="tbc", ufls=True)
    r = model.simulate(Disturbance(area="hokkaido", dp_mw=p_mw, t_step=1.0,
                                   label=gen.name), t_end=920.0)
    df = r.df_hz["hokkaido"]
    shed = r.shed_mw["hokkaido"]
    print(f"  sim: nadir {r.nadir_hz:+.2f}Hz / 遮断最終 {shed[-1]:,.0f}MW")

    # 北海道の線形とノード
    b = json.load(open("docs/data/built/all.json"))
    segs, subs = [], []
    for e in b["edges"]:
        path = e.get("path")
        if path and len(path) >= 2 and path[0][0] > 41.3 and \
                path[0][1] > 139.3:
            segs.append([(p[1], p[0]) for p in path])
    for nd in b["nodes"]:
        if nd.get("region") == "hokkaido" and nd.get("sub"):
            subs.append((nd["lon"], nd["lat"]))
    subs = np.array(subs)
    rng = np.random.default_rng(2018)
    order = rng.permutation(len(subs))   # 消灯順(演出・固定シード)
    load0 = areas[0].load_mw

    frames = []
    for t_sim, hold in TIMELINE:
        k = max(0, min(len(df) - 1, int((t_sim) / 0.1)))
        f_now = 50.0 + (df[k] if t_sim >= 0 else 0.0)
        sh_now = shed[k] if t_sim >= 0 else 0.0
        col = freq_color(f_now - 50.0)

        fig = plt.figure(figsize=(9.6, 7.2), dpi=100)
        fig.patch.set_facecolor(BG)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_facecolor(BG)
        ax.set_xlim(139.2, 146.3)
        ax.set_ylim(41.3, 45.9)
        ax.set_aspect(1.0 / math.cos(math.radians(43.0)))
        ax.axis("off")
        ax.add_collection(LineCollection(segs, colors=[col], linewidths=1.5,
                                         alpha=0.35, zorder=2))
        ax.add_collection(LineCollection(segs, colors=[col], linewidths=0.7,
                                         alpha=0.95, zorder=3))
        # 変電所: 遮断割合ぶんを消灯(量=シミュレーション実値・場所=演出)
        n_off = int(len(subs) * sh_now / max(load0, 1e-9))
        on = np.ones(len(subs), bool)
        on[order[:n_off]] = False
        ax.scatter(subs[on, 0], subs[on, 1], s=3.5, c="#FFFFFF", alpha=0.75,
                   zorder=5, linewidths=0)
        if n_off:
            ax.scatter(subs[~on, 0], subs[~on, 1], s=3.5, c="#333A55",
                       alpha=0.9, zorder=5, linewidths=0)
        # 苫東厚真
        if t_sim < 1.0:
            ax.scatter(*TRIP_XY, marker="*", s=800, c="#FFE28A",
                       edgecolors="#FF9500", linewidths=1.5, zorder=8)
        else:
            ax.scatter(*TRIP_XY, marker="X", s=420, c="#D62728",
                       edgecolors="#FFFFFF", linewidths=1.2, zorder=8)
            ax.text(TRIP_XY[0] + 0.12, TRIP_XY[1] - 0.32,
                    f"苫東厚真 −{p_mw:,.0f} MW", color="#FF6B6B",
                    fontsize=13, fontweight="bold", zorder=8)
        # HUD
        ax.text(0.03, 0.955, "北海道系統 — 最大電源の脱落(モデル実験)",
                transform=ax.transAxes, color="#C8CDD8", fontsize=15,
                fontweight="bold", va="top")
        tt = max(t_sim - 1.0, -4.0)
        label = ("事故前" if t_sim < 1.0 else
                 f"事故から {tt:5.1f} 秒" if tt < 60 else
                 f"事故から {tt/60:4.1f} 分")
        ax.text(0.03, 0.895, label, transform=ax.transAxes, color="#FFFFFF",
                fontsize=20, fontweight="bold", va="top")
        ax.text(0.03, 0.82, f"周波数  {f_now:6.2f} Hz", transform=ax.transAxes,
                color=col, fontsize=26, fontweight="bold", va="top")
        if sh_now > 5:
            ax.text(0.03, 0.745,
                    f"負荷遮断(UFLS)  −{sh_now:,.0f} MW",
                    transform=ax.transAxes, color="#FF6B6B", fontsize=15,
                    fontweight="bold", va="top")
        # 段階説明
        if t_sim < 1.0:
            note = "50.00 Hz — 平常運転(UCの実断面: 需要4,434 MW)"
        elif tt < 3:
            note = "① 慣性だけが支える数秒 — 周波数が急落(−2.9 Hz/s)"
        elif tt < 25:
            note = "② UFLSが段階的に負荷を遮断 — 落下が止まり跳ね返る"
        elif tt < 240:
            note = "③ ガバナ+LFCが引き継ぎ、周波数を戻していく"
        else:
            note = ("④ 15分後もまだ49 Hz台前半 — 小さな系統の回復は長い\n"
                    "    (実際の2018年は全域停電し、完全復旧に約45時間)")
        ax.text(0.03, 0.10, note, transform=ax.transAxes, color="#C8CDD8",
                fontsize=13.5, va="top")
        ax.text(0.03, 0.045,
                "遮断量=シミュレーション実値 / どの変電所を切るかは非公開のため消灯箇所は演出",
                transform=ax.transAxes, color="#5A648F", fontsize=9.5,
                va="top")
        fig.canvas.draw()
        img = np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()
        plt.close(fig)
        frames.extend([img] * hold)

    from PIL import Image
    ims = [Image.fromarray(f) for f in frames]
    out = "docs/slides/ajg/assets/agc_hokkaido_trip.gif"
    ims[0].save(out, save_all=True, append_images=ims[1:], duration=90,
                loop=0, optimize=True)
    print(f"-> {out} ({len(ims)}フレーム, {os.path.getsize(out)/1e6:.1f}MB)")


if __name__ == "__main__":
    main()
