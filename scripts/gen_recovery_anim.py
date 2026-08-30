#!/usr/bin/env python3
"""周波数が戻るさまGIF — 北海道トリップ→UFLS→LFC/EDCで50.00Hzへ(2026-08-30).

COI制御層(src/dynamics/agc.py・AGC30 LFC/EDC)による回復の実シミュレーション。
多機層(AGC-N)は動揺の道具でLFC回復を再現しない(既知の限界・要調査) — 回復は
制御層で描くのが正直な役割分担。

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
def render(ts):
    k = min(len(t) - 1, int(np.searchsorted(t, ts)))
    fig = plt.figure(figsize=(12.8, 7.2), dpi=110)
    fig.patch.set_facecolor(BG)
    # 上: 全景(0..2400s) / 下: 直後ズーム(0..40s)
    ax = fig.add_axes([0.07, 0.40, 0.90, 0.46]); ax.set_facecolor("#11152A")
    ax2 = fig.add_axes([0.07, 0.075, 0.40, 0.24]); ax2.set_facecolor("#11152A")
    for a_, xl in ((ax, (0, T_END)), (ax2, (0, 40))):
        a_.plot(t[:k + 1], f[:k + 1], lw=2.0, color="#4E9BFF")
        a_.axhline(f0, color="#69F0AE", lw=0.9, ls="--", alpha=0.8)
        for th in UFLS_STEPS_HZ:
            a_.axhline(f0 + th, color="#C62828", lw=0.7, ls=":", alpha=0.6)
        for te, nm in ev:
            if te <= xl[1]:
                a_.axvline(te, color="#C62828", lw=0.8, ls=":", alpha=0.7)
        a_.axvline(min(ts, xl[1]), color="#FFD60A", lw=1.4)
        a_.set_xlim(*xl); a_.set_ylim(47.2, 50.35)
        a_.tick_params(colors="#8E96B8", labelsize=8.5)
        for sp in a_.spines.values():
            sp.set_color("#3A4266")
    ax.set_title("北海道 — 苫東厚真1,650MWトリップからの復帰(全2,400秒)",
                 color="#8E96B8", fontsize=10, loc="left", pad=4)
    ax2.set_title("最初の40秒(慣性→UFLS 3段→GF)", color="#8E96B8", fontsize=10)
    ax.set_xlabel("時間 [s]", color="#8E96B8", fontsize=9)
    # 段階バナー
    if ts < 1.5: stage = ("① 慣性 — 回転体が最初の数秒を買う", "#4E9BFF")
    elif ts < 4: stage = ("② UFLS — 3段ラッチで落下を受け止める(遮断は戻らない)", "#FF8A80")
    elif ts < 60: stage = ("③ ガバナフリー — 数十秒スケールで支える", "#FFD60A")
    else: stage = ("④ LFC/EDC — レート制限の登坂で50.00Hzへ(AGC30定数)", "#69F0AE")
    fig.text(0.07, 0.945, "周波数が戻るさま — 事故から復帰までの4段構え",
             color="#FFFFFF", fontsize=19, fontweight="bold", va="top")
    fig.text(0.07, 0.895, stage[0], color=stage[1], fontsize=14.5,
             fontweight="bold", va="top")
    mins = ts / 60
    fig.text(0.97, 0.945, f"t = {ts:6.0f} s ({mins:4.1f}分)   f = {f[k]:.3f} Hz",
             color="#C8CDD8", fontsize=13.5, va="top", ha="right")
    fig.text(0.52, 0.075,
             "COI制御層(AGC30: GF+LFC+EDC・ラッチUFLS)の実シミュレーション\n"
             "回復速度はLFCレート(0.012-0.047 pu/min)が支配 — 約35分で復帰\n"
             "多機層(AGC-N)は動揺専用でLFC回復は再現しない(役割分担・既知の限界)\n"
             "終端の+0.1Hzの行き過ぎはLFC積分が戻し中(そのまま開示)",
             color="#5A648F", fontsize=9.5, va="bottom")
    fig.canvas.draw()
    img = np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()
    plt.close(fig)
    return img

frames, durs = [], []
TL = ([(0.5, 800)] + [(1.0 + 0.5 * i, 450) for i in range(8)]
      + [(5.0 + 3 * i, 300) for i in range(9)]
      + [(40.0 + 40 * i, 250) for i in range(10)]
      + [(480 + 160 * i, 300) for i in range(12)])
for ts, du in TL:
    if ts > T_END - 1:
        break
    frames.append(render(ts)); durs.append(du)
frames.append(render(T_END - 1)); durs.append(3500)
from PIL import Image
ims = [Image.fromarray(f_) for f_ in frames]
out = "docs/slides/ajg/assets/freq_recovery.gif"
ims[0].save(out, save_all=True, append_images=ims[1:], duration=durs, loop=0,
            optimize=True)
print(f"-> {out} ({len(ims)}フレーム, {os.path.getsize(out)/1e6:.1f}MB)")
