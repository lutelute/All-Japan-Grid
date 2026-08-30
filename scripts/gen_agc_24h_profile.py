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
    if "--replot" in sys.argv:
        # レイアウト調整用: 既存の断面JSONから作図のみやり直す(計算は不変)
        prof = json.load(open("docs/data/agc/agc_24h_profile.json"))["islands"]
        draw(prof)
        return
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
            # RoCoF は計測慣行(リレー・系統計測)に合わせて 500ms 窓で測る。
            # 解析的初期値 ΔP/2ΣHS·f0 は瞬時値で、窓計測より過大に出る
            # (オーナー指摘 2026-08-29「RoCoFの測り方」) — 両方帳簿に残す
            fzero = next(a for a in r.df_hz)      # 単/多エリアとも共通f
            fcoi = r.df_hz[fzero]
            W = 5                                  # 0.1s刻み × 5 = 500ms
            roc_w = float(((fcoi[W:] - fcoi[:-W]) / (0.1 * W)).min())
            rows.append(dict(
                hour=h,
                demand_mw=round(sum(float(scn.net_demand_r[rg][h])
                                    for rg in regions), 1),
                inertia_gws=round(m_tot * S_BASE_MVA / 2000.0, 2),
                largest_mw=round(p_mw, 1), largest=gen.name,
                rocof_hz_s=round(r.rocof_hz_s, 3),
                rocof_w500_hz_s=round(roc_w, 3),
                nadir_hz=round(r.nadir_hz, 3)))
        prof[island] = rows
        worst = min((x for x in rows if x), key=lambda x: x["nadir_hz"])
        print(f"[{island}] 最悪時刻 t={worst['hour']} "
              f"nadir={worst['nadir_hz']:+.2f}Hz "
              f"(慣性{worst['inertia_gws']}GW·s, {worst['largest']} "
              f"{worst['largest_mw']:,.0f}MW)")

    draw(prof)

    doc = {"note": ("24時間の周波数セキュリティ断面。各時刻のUCコミットメント"
                    "から慣性・最大オンラインプラント・トリップ応答(COI層・"
                    "UFLS込み)を算出。プラント粒度=ユニットN-1の上界。"
                    "連系剛性は実測(agc_chain.json)・網は時刻不変"),
           "islands": prof}
    json.dump(doc, open("docs/data/agc/agc_24h_profile.json", "w"),
              ensure_ascii=False, indent=1)
    print("-> docs/data/agc/agc_24h_profile.json")


def draw(prof):
    # ── 図: 4段 × 4島。需要・慣性はスケール差が大きいので2軸
    #    (左=east/west・右=hokkaido/okinawa)、RoCoF/ナディアは同一軸で比較 ──
    fig, axes = plt.subplots(4, 1, figsize=(11.5, 9.4), dpi=150, sharex=True)
    hours = np.arange(24)
    BIG, SMALL = ("east", "west"), ("hokkaido", "okinawa")

    def series(island, key, scale=1.0):
        return [x[key] * scale if x else np.nan for x in prof[island]]

    handles = {}
    for ax, (key, label, scale) in zip(
            axes[:2], [("demand_mw", "純需要 [GW]", 1e-3),
                       ("inertia_gws", "残存慣性 ΣH·S [GW·s]\n(脱落後)", 1.0)]):
        axr = ax.twinx()
        for island in BIG:
            h_, = ax.plot(hours, series(island, key, scale), "o-", ms=3.5,
                          lw=1.6, color=COLOR[island])
            handles[island] = h_
        for island in SMALL:
            h_, = axr.plot(hours, series(island, key, scale), "s--", ms=3.5,
                           lw=1.4, color=COLOR[island])
            handles[island] = h_
        ax.set_ylabel(f"{label}\n左軸: east/west", fontsize=9.5)
        axr.set_ylabel("右軸: hokkaido/okinawa", fontsize=9.5)
        ax.grid(alpha=0.3)
    for ax, (key, label) in zip(
            axes[2:], [("rocof_w500_hz_s", "脱落時RoCoF [Hz/s]\n(500ms窓)"),
                       ("nadir_hz", "ナディア [Hz]")]):
        for island in ISLANDS:
            style = "o-" if island in BIG else "s--"
            ax.plot(hours, series(island, key), style, ms=3.5, lw=1.6,
                    color=COLOR[island])
        ax.set_ylabel(label, fontsize=9.5)
        ax.grid(alpha=0.3)
    fig.legend(handles.values(), handles.keys(), ncol=4, fontsize=10,
               loc="upper right", bbox_to_anchor=(0.99, 0.965))
    axes[3].set_xlabel("時刻 [時] (UC 24hコミットメントの各断面)", fontsize=11)
    axes[3].set_xticks(range(0, 24, 2))
    # UFLS帯と設計域外(崩壊域=モデル外挿)の網掛け
    axes[3].axhline(-1.5, color="#C62828", lw=0.9, ls="--", alpha=0.6)
    # 破線の直下(east/west線と okinawa線の間の空白帯)に置く
    axes[3].text(23.2, -1.92, "← UFLS開始(第1段)", ha="right", fontsize=9,
                 color="#C62828")
    # 注記は最深ナディアより下に空白帯を作ってそこへ置く(データ線と重ねない)
    nadir_min = min(x["nadir_hz"] for isl in ISLANDS for x in prof[isl] if x)
    ybot = nadir_min - 1.55
    axes[3].axhspan(ybot, -2.5, color="#C62828", alpha=0.07, zorder=0)
    axes[3].text(0.2, nadir_min - 1.12,
                 "UFLS設計域外(第3段より下) — 崩壊域・モデル外挿",
                 fontsize=9, color="#8A1F1F")
    axes[3].set_ylim(ybot, axes[3].get_ylim()[1])
    # 北海道の夜間トラフに事実注記
    hn = prof["hokkaido"]
    kmin = min(range(24), key=lambda h: hn[h]["nadir_hz"])
    axes[3].annotate(
        f"北海道の最悪は深夜{kmin}時: {hn[kmin]['nadir_hz']:.1f} Hz\n"
        "実際の2018年ブラックアウトも 3:08(未明) — 構図の一致",
        xy=(kmin, hn[kmin]["nadir_hz"]), xytext=(6.8, -5.9), fontsize=10,
        color="#C62828",
        arrowprops=dict(arrowstyle="->", color="#C62828", lw=1.2))
    fig.suptitle("周波数セキュリティの24時間断面 — 各時刻のUC断面で"
                 "最大オンラインプラントを落とす(COI層・AGC30簡易・"
                 "プラント粒度=ユニットN-1の上界)", fontsize=12)
    fig.tight_layout(rect=[0.012, 0, 1, 1])
    out = "docs/slides/ajg/assets/fig_agc_24h.png"
    fig.savefig(out)
    print(f"-> {out}")


if __name__ == "__main__":
    main()
