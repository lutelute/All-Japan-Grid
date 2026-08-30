#!/usr/bin/env python3
"""周波数が戻るさま(東N-3・900秒)GIF — 回復の物語を1本のチャートで(2026-08-30).

オーナー指摘「p25(北海道COI層2,400s版)は前後の東N-3の文脈から飛んでいて
わからない」への応答 — 同じ mm_traces_east_n3pk.npz に一本化し、COI曲線が
左から描かれ、到達した局面ごとにバナーが出る進行描画。地図なしチャート主体。

出力: docs/slides/ajg/assets/freq_recovery_east.gif
"""
import os
import numpy as np
os.chdir("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

z = np.load("docs/data/agc/mm_traces_east_n3pk.npz", allow_pickle=True)
t, w, f0, M = z["t"], z["w"], float(z["f0"]), z["M"]
finite = np.isfinite(w)
coi = np.full(len(t), np.nan)
for i in range(len(t)):
    m = finite[:, i]
    if m.any():
        coi[i] = f0 + (M[m] * w[m, i]).sum() / M[m].sum() * f0
T_LAST = float(t[-1])
floor_hz = float(np.nanmin(coi))
k60 = min(len(t) - 1, int(np.searchsorted(t, 60.0)))
f60 = float(coi[k60])
f_end = float(coi[np.isfinite(coi)][-1])
end_min = (T_LAST - 1.0) / 60.0

BG = "#0A0D1A"
# (発現時刻s, 帯開始, 帯終了, 番号+題, 色)
PHASES = [
    (1.0, 1.0, 5.3, "① 慣性で急落", "#FF8A80"),
    (5.3, None, None, f"② UFLS第1段が底を打つ({floor_hz:.2f} Hz)", "#FF5252"),
    (8.0, 5.3, 60.0, "③ 高速登坂 — ガバナ+水力LFC(速い余力)", "#8FD3A5"),
    (60.0, 60.0, 180.0, "④ 停滞 — 速い余力が尽きる", "#FFD60A"),
    (180.0, 180.0, T_LAST, "⑤ 緩やかな回復 — 遅い火力が仕上げる", "#9EC1FF"),
]

def render(tc, final=False):
    k = min(len(t) - 1, int(np.searchsorted(t, tc)))
    fig = plt.figure(figsize=(12.8, 7.2), dpi=110)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.085, 0.13, 0.885, 0.66])
    ax.set_facecolor("#11152A")
    # 到達済み局面の帯シェード+小ラベル
    cur = None
    for t_on, x0, x1, lb, c in PHASES:
        if tc + 1e-9 >= t_on:
            cur = (lb, c)
            if x0 is not None:
                xe = min(x1, max(tc, x0))
                ax.axvspan(x0, xe, color=c, alpha=0.07)
                if (tc >= x1 or final) and (x1 - x0) > 40.0:
                    # 幅の狭い帯(①急落)はラベル省略 — 左端での重なり防止
                    ax.text((x0 + x1) / 2, 50.28, lb.split(" — ")[0],
                            ha="center", color=c, fontsize=10,
                            fontweight="bold")
    # COI進行描画
    ax.plot(t[:k + 1], coi[:k + 1], lw=2.6, color="#FFFFFF", zorder=6)
    if not final:
        ax.scatter([t[k]], [coi[k]], s=60, color="#FFD60A", zorder=7)
    ax.axhline(50.0, color="#69F0AE", lw=1.0, ls="--", alpha=0.8)
    ax.axhline(48.5, color="#C62828", lw=0.9, ls="--", alpha=0.7)
    ax.text(T_LAST * 0.985, 48.53, "UFLS第1段しきい値", ha="right",
            color="#C62828", fontsize=9)
    ax.text(T_LAST * 0.985, 50.03, "定格 50.00 Hz", ha="right",
            color="#69F0AE", fontsize=9)
    ax.set_xlim(0, T_LAST); ax.set_ylim(48.3, 50.45)
    ax.tick_params(colors="#8E96B8", labelsize=10)
    for sp in ax.spines.values():
        sp.set_color("#3A4266")
    ax.set_xlabel("事故からの時間 [s]", color="#8E96B8", fontsize=11)
    ax.set_ylabel("系統平均(COI)周波数 [Hz]", color="#8E96B8", fontsize=11)
    # ヘッダ
    fig.text(0.085, 0.955, "周波数が戻るさま — 東N-3(10.9GW脱落)から15分",
             color="#FFFFFF", fontsize=20, fontweight="bold", va="top")
    tt = tc - 1.0
    tl = ("事故前" if tt < 0 else
          f"t = {tt:5.1f} 秒" if tt < 90 else
          f"t = {int(tt)//60}分{int(tt)%60:02d}秒")
    fig.text(0.973, 0.955, f"{tl}   f = {coi[k]:.3f} Hz", color="#C8CDD8",
             fontsize=13.5, va="top", ha="right")
    # 現在局面バナー
    if cur is not None and not final:
        fig.text(0.085, 0.885, "▸ " + cur[0], color=cur[1], fontsize=16.5,
                 fontweight="bold", va="top")
    if final:
        fig.text(0.085, 0.885,
                 f"{end_min:.0f}分で {f_end:.2f} Hz — 50.00 Hzへの完全復帰は"
                 "さらに数十分先(遅い火力のランプとLFCの仕事)",
                 color="#69F0AE", fontsize=15, fontweight="bold", va="top")
    fig.text(0.085, 0.035,
             f"底 {floor_hz:.2f} Hz → 60秒 {f60:.2f} Hz → "
             f"{end_min:.0f}分 {f_end:.2f} Hz — "
             "多機層(AGC-N)・第10波LFC修正済みの実シミュレーション"
             "(東N-3・UCピーク断面・ラッチUFLS)",
             color="#5A648F", fontsize=9.5, va="bottom")
    fig.canvas.draw()
    img = np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()
    plt.close(fig)
    return img

frames, durs = [], []
TL = ([(0.4, 900)] + [(1.0 + 1.0 * i, 550) for i in range(10)]
      + [(15.0 + 10.0 * i, 450) for i in range(5)]
      + [(65.0 + 20.0 * i, 450) for i in range(6)]
      + [(190.0 + 60.0 * i, 400) for i in range(12)])
for tc, du in TL:
    if tc > T_LAST:
        break
    frames.append(render(tc)); durs.append(du)
frames.append(render(T_LAST - 0.02, final=True)); durs.append(4200)

from PIL import Image
ims = [Image.fromarray(f) for f in frames]
out = "docs/slides/ajg/assets/freq_recovery_east.gif"
ims[0].save(out, save_all=True, append_images=ims[1:], duration=durs, loop=0,
            optimize=True)
print(f"-> {out} ({len(ims)}フレーム, {os.path.getsize(out)/1e6:.1f}MB)")
