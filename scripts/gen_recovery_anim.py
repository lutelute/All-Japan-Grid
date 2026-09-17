#!/usr/bin/env python3
"""周波数が戻るさまGIF — 北海道トリップ→UFLS→LFC/EDCで50.00Hzへ(2026-08-30).

COI制御層(src/dynamics/agc.py・AGC30 LFC/EDC)による回復の実シミュレーション。
多機層(AGC-N)も第10波のLFCバイアス修正(ace=B·ω)で回復を再現する(900s検証:
47.29→49.81Hz)が、数十分スケールの完全復帰はCOI制御層で描く(計算コストの分担)。

2幕構成(オーナー指摘 2026-08-30「最初の慣性の40秒が見れない/登坂は早送りで
よい/この深さの異常さが伝わらない」への応答):
  第1幕 = 0〜40秒をフルスクリーン超スロー(慣性→UFLS 3段→GF底打ち)
  第2幕 = 40秒→2,400秒を早送り(倍速バッジ表示、LFC/EDC登坂→50.00Hz)

出力: docs/slides/ajg/assets/freq_recovery.gif
"""
import os
import numpy as np
os.chdir("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False
import json, sys
sys.path.insert(0, os.getcwd())
from src.uc.scenario import build_national_scenario
from src.uc.solver import solve_uc
from src.dynamics.agc import (MultiAreaLFC, Disturbance, build_area_from_uc,
                              largest_online_unit, remove_unit_from_area,
                              UFLS_STEPS_HZ)

T_END = 2400.0
scn = build_national_scenario(scenario="fy2023r2")
uc = solve_uc(scn.to_uc_parameters()); assert uc.is_optimal
chain = json.load(open("docs/data/agc/agc_chain.json"))["islands"]
tie = {tuple(k.split("-")): v
       for k, v in chain["hokkaido"]["tie_pu_per_rad"].items()}
nd = np.asarray(scn.net_demand_r["hokkaido"])
h = int(np.argmax(nd))
area = build_area_from_uc("hokkaido", uc, scn.generators, h, float(nd[h]))
gen, p_mw = largest_online_unit(uc, scn.generators, h, ["hokkaido"])
area_t = remove_unit_from_area(area, gen, p_mw)
m = MultiAreaLFC(50.0, [area_t], tie, mode="tbc", ufls=True)
r = m.simulate(Disturbance(area="hokkaido", dp_mw=p_mw), t_end=T_END)
f0 = 50.0
fz = next(iter(r.df_hz)); f = f0 + r.df_hz[fz]; t = r.t
print(f"nadir={f.min():.3f} 終端={f[-1]:.3f}")
# UFLS段の発動時刻(しきい値の下向き交差)
ev = []
for k, th in enumerate(UFLS_STEPS_HZ):
    idx = np.where((f[:-1] > f0 + th) & (f[1:] <= f0 + th))[0]
    if len(idx):
        ev.append((float(t[idx[0]]), f"UFLS第{k+1}段"))

BG = "#0A0D1A"
ACT1_END = 40.0


def render(ts, speed=None, transition=False):
    """1フレーム描画。ts<=40は第1幕(0-40sフルスクリーン)、それ以降は第2幕."""
    k = min(len(t) - 1, int(np.searchsorted(t, ts)))
    act1 = ts <= ACT1_END and not transition
    fig = plt.figure(figsize=(12.8, 7.2), dpi=110)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.07, 0.175, 0.90, 0.655])
    ax.set_facecolor("#11152A")
    xl = (0, ACT1_END) if act1 else (0, T_END)
    ax.plot(t[:k + 1], f[:k + 1], lw=2.2, color="#4E9BFF")
    ax.axhline(f0, color="#69F0AE", lw=0.9, ls="--", alpha=0.8)
    for j, th in enumerate(UFLS_STEPS_HZ):
        ax.axhline(f0 + th, color="#C62828", lw=0.7, ls=":", alpha=0.6)
        if act1:
            ax.text(xl[1] * 0.99, f0 + th + 0.03,
                    f"UFLS第{j+1}段 {f0+th:.1f} Hz", ha="right", va="bottom",
                    color="#C62828", fontsize=8.5, alpha=0.9)
    for te, _nm in ev:
        if te <= xl[1]:
            ax.axvline(te, color="#C62828", lw=0.8, ls=":", alpha=0.7)
    if not act1:
        # 第1幕の窓を淡くシェード — 「さっきの40秒はここ」
        ax.axvspan(0, ACT1_END, color="#4E9BFF", alpha=0.10)
        ax.text(ACT1_END + 25, 47.32, "◀ 第1幕の40秒", color="#5A78B8",
                fontsize=9, va="bottom")
    ax.axvline(min(ts, xl[1]), color="#FFD60A", lw=1.4)
    ax.set_xlim(*xl); ax.set_ylim(47.2, 50.35)
    ax.tick_params(colors="#8E96B8", labelsize=9)
    for sp in ax.spines.values():
        sp.set_color("#3A4266")
    ax.set_xlabel("時間 [s]", color="#8E96B8", fontsize=9)
    ax.set_title("北海道 — 苫東厚真1,650MWトリップからの復帰"
                 + ("(第1幕: 最初の40秒)" if act1 else "(第2幕: 全2,400秒)"),
                 color="#8E96B8", fontsize=10, loc="left", pad=4)
    # 段階バナー
    if ts < 1.5: stage = ("① 慣性 — 回転体が最初の数秒を買う", "#4E9BFF")
    elif ts < 4: stage = ("② UFLS — 3段ラッチで落下を受け止める(遮断は戻らない)",
                          "#FF8A80")
    elif act1: stage = ("③ ガバナフリー — 数十秒スケールで底を支える", "#FFD60A")
    else: stage = ("④ LFC/EDC — レート制限の登坂で50.00Hzへ(AGC30定数)",
                   "#69F0AE")
    fig.text(0.07, 0.955, "周波数が戻るさま — 事故から復帰までの4段構え",
             color="#FFFFFF", fontsize=19, fontweight="bold", va="top")
    fig.text(0.07, 0.905, stage[0], color=stage[1], fontsize=14.5,
             fontweight="bold", va="top")
    mins = ts / 60
    fig.text(0.97, 0.955, f"t = {ts:6.0f} s ({mins:4.1f}分)   f = {f[k]:.3f} Hz",
             color="#C8CDD8", fontsize=13.5, va="top", ha="right")
    if act1:
        # 深さの異常さ — 第1幕の主注記(プロット中央右の空き領域に置く)
        ax.text(0.975, 0.60,
                "実系統でこの深さ(47.5 Hz)は極めて稀 —\n"
                "UFLSが3段すべて発動する、ブラックアウト一歩手前の事態",
                transform=ax.transAxes, ha="right", va="top",
                color="#FF8A80", fontsize=11.5, fontweight="bold",
                linespacing=1.5)
    else:
        badge = "▶▶ 早送り" + (f" ×約{speed:,.0f}" if speed else "")
        fig.text(0.97, 0.895, badge, color="#0A0D1A", fontsize=12,
                 fontweight="bold", va="top", ha="right",
                 bbox=dict(boxstyle="round,pad=0.45", fc="#FFD60A",
                           ec="none"))
    if transition:
        fig.text(0.5, 0.52, "ここから早送り", color="#FFD60A", fontsize=30,
                 fontweight="bold", ha="center", va="center")
        fig.text(0.5, 0.43, "実時間 約40分の登坂を数秒で", color="#C8CDD8",
                 fontsize=14, ha="center", va="center")
    fig.text(0.07, 0.015,
             "COI制御層(AGC30: GF+LFC+EDC・ラッチUFLS)の実シミュレーション / "
             "回復速度はLFCレート(0.012-0.047 pu/min)が支配 — 約35分で復帰\n"
             "多機層(AGC-N)も第10波LFC修正で回復するが長時間はCOI層が担当 / "
             "終端の+0.1Hzの行き過ぎはLFC積分が戻し中(そのまま開示) / "
             "実系統でこの深さは極めて稀",
             color="#5A648F", fontsize=9.0, va="bottom")
    fig.canvas.draw()
    img = np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()
    plt.close(fig)
    return img


frames, durs = [], []
# ---- 第1幕: 0〜40秒フルスクリーン超スロー ----
act1 = ([(0.5, 800)]
        + [(1.0 + 0.25 * i, 350) for i in range(9)]        # 落下〜UFLS(1.0-3.0s)
        + [(ts, 280) for ts in (3.5, 4, 5, 6, 8, 10, 13, 16,
                                20, 25, 30, 35, 40)])       # GF底打ち
for ts, du in act1:
    frames.append(render(ts)); durs.append(du)
# ---- 幕間: 「ここから早送り」 ----
frames.append(render(ACT1_END, transition=True)); durs.append(1900)
# ---- 第2幕: 早送り(80sステップ×110ms ≒ ×730) ----
STEP, DU = 80.0, 110
speed = STEP / (DU / 1000.0)
for ts in np.arange(ACT1_END + STEP, T_END, STEP):
    frames.append(render(float(ts), speed=speed)); durs.append(DU)
frames.append(render(T_END - 1, speed=speed)); durs.append(3500)

from PIL import Image
ims = [Image.fromarray(f_) for f_ in frames]
out = "docs/slides/ajg/assets/freq_recovery.gif"
ims[0].save(out, save_all=True, append_images=ims[1:], duration=durs, loop=0,
            optimize=True)
print(f"-> {out} ({len(ims)}フレーム, {os.path.getsize(out)/1e6:.1f}MB)")
