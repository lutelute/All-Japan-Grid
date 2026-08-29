#!/usr/bin/env python3
"""周波数セキュリティの24時間断面 — 慣性・N-1・nadirの日内プロファイル.

オーナー指示「時間帯の断面も見れるといいね。24h」(2026-08-29)。

UCの24時間コミットメントは時刻ごとに変わる → オンライン機集合が変わる →
慣性・調整余力・最大オンライン機(=N-1外乱)が変わる。各時刻の断面で
COI層(src/dynamics/agc.py・AGC30簡易)のトリップ+UFLSシミュレーションを回し、
「1日のうち、いつ系統が周波数事故に弱いか」を描く。

多機(AGC-N)版はピーク時刻の詳細スナップショット、本スクリプトは日内の俯瞰 —
という2段構え。連系剛性は agc_chain.json の実測値(網は時刻不変)。

出力:
  docs/slides/ajg/assets/fig_agc_24h.png
  docs/data/agc/agc_24h_profile.json
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
    remove_unit_from_area, S_BASE_MVA)

ISLANDS = {"hokkaido": (["hokkaido"], 50.0),
           "east": (["tohoku", "tokyo"], 50.0),
           "west": (["chubu", "hokuriku", "kansai", "chugoku",
                     "shikoku", "kyushu"], 60.0),
           "okinawa": (["okinawa"], 60.0)}
COLOR = {"hokkaido": "#D62728", "east": "#FF9500",
         "west": "#4A5A8A", "okinawa": "#2CA02C"}


def main():
    print("UC求解...")
    scn = build_national_scenario(scenario="fy2023r2")
    uc = solve_uc(scn.to_uc_parameters())
    assert uc.is_optimal
    chain = json.load(open("docs/data/agc/agc_chain.json"))["islands"]

    prof = {}
    for island, (regions, f0) in ISLANDS.items():
        tie = {tuple(k.split("-")): v
               for k, v in chain[island]["tie_pu_per_rad"].items()}
        rows = []
        for h in range(24):
            areas = [build_area_from_uc(r, uc, scn.generators, h,
                                        float(scn.net_demand_r[r][h]))
                     for r in regions]
            big = largest_online_unit(uc, scn.generators, h, regions)
            if big is None:
                rows.append(None)
                continue
            gen, p_mw = big
            areas_t = [remove_unit_from_area(a, gen, p_mw)
                       if a.name == gen.region else a for a in areas]
            m_tot = sum(a.M for a in areas_t)
            model = MultiAreaLFC(f0, areas_t, tie, mode="tbc", ufls=True)
            r = model.simulate(Disturbance(area=gen.region, dp_mw=p_mw),
                               t_end=90.0)
            rows.append(dict(
                hour=h,
                demand_mw=round(sum(float(scn.net_demand_r[rg][h])
                                    for rg in regions), 1),
                inertia_gws=round((m_tot + 2 * 0) * S_BASE_MVA / 2000.0, 2),
                largest_mw=round(p_mw, 1), largest=gen.name,
                rocof_hz_s=round(r.rocof_hz_s, 3),
                nadir_hz=round(r.nadir_hz, 3)))
        prof[island] = rows
        worst = min((x for x in rows if x), key=lambda x: x["nadir_hz"])
        print(f"[{island}] 最悪時刻 t={worst['hour']} "
              f"nadir={worst['nadir_hz']:+.2f}Hz "
              f"(慣性{worst['inertia_gws']}GW·s, {worst['largest']} "
              f"{worst['largest_mw']:,.0f}MW)")

    # ── 図: 4段(需要・慣性・RoCoF・nadir) × 4島 ──
    fig, axes = plt.subplots(4, 1, figsize=(11.5, 9.2), dpi=150, sharex=True)
    hours = np.arange(24)
    panels = [("demand_mw", "需要 [GW]", 1e-3),
              ("inertia_gws", "慣性 ΣH·S [GW·s]", 1.0),
              ("rocof_hz_s", "脱落時RoCoF [Hz/s]", 1.0),
              ("nadir_hz", "ナディア [Hz]", 1.0)]
    for ax, (key, label, scale) in zip(axes, panels):
        for island in ISLANDS:
            ys = [x[key] * scale if x else np.nan for x in prof[island]]
            ax.plot(hours, ys, "o-", ms=3.5, lw=1.6, color=COLOR[island],
                    label=island)
        ax.set_ylabel(label, fontsize=10)
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=9.5, ncol=4, loc="upper left")
    axes[3].set_xlabel("時刻 [時] (UC 24hコミットメントの各断面)", fontsize=11)
    axes[3].set_xticks(range(0, 24, 2))
    # UFLS帯
    axes[3].axhline(-1.5, color="#C62828", lw=0.9, ls="--", alpha=0.6)
    axes[3].text(23.6, -1.35, "UFLS開始", ha="right", fontsize=9,
                 color="#C62828")
    # 北海道の夜間トラフに事実注記
    hn = prof["hokkaido"]
    kmin = min(range(24), key=lambda h: hn[h]["nadir_hz"])
    axes[3].annotate(
        f"北海道の最悪は深夜{kmin}時: {hn[kmin]['nadir_hz']:.1f} Hz —\n"
        "UFLS3段でも止まらない崩壊域。\n"
        "実際の2018年ブラックアウトは 3:08 に発生した",
        xy=(kmin, hn[kmin]["nadir_hz"]), xytext=(6.2, -6.6), fontsize=10,
        color="#C62828",
        arrowprops=dict(arrowstyle="->", color="#C62828", lw=1.2))
    fig.suptitle("周波数セキュリティの24時間断面 — 各時刻のUC断面で"
                 "最大オンラインプラントを落とす(COI層・AGC30簡易・"
                 "プラント粒度=ユニットN-1の上界)", fontsize=12)
    fig.tight_layout()
    out = "docs/slides/ajg/assets/fig_agc_24h.png"
    fig.savefig(out)
    print(f"-> {out}")

    doc = {"note": ("24時間の周波数セキュリティ断面。各時刻のUCコミットメント"
                    "から慣性・最大オンラインプラント・トリップ応答(COI層・"
                    "UFLS込み)を算出。プラント粒度=ユニットN-1の上界。"
                    "連系剛性は実測(agc_chain.json)・網は時刻不変"),
           "islands": prof}
    json.dump(doc, open("docs/data/agc/agc_24h_profile.json", "w"),
              ensure_ascii=False, indent=1)
    print("-> docs/data/agc/agc_24h_profile.json")


if __name__ == "__main__":
    main()
