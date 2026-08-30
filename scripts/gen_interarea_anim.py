#!/usr/bin/env python3
"""逆位相動揺(inter-areaモード)GIF — 九州側と関西側の綱引き(2026-08-30).

west正典多機トレース(最大機トリップ)のCOI相対周波数に、西G(lon<132.5・61機)と
東G(lon>134.5・190機)の完全逆位相(相関-0.999・周期2.4s)が出る。
実網から測った連系剛性T_abが決める固有モードの可視化。

出力: docs/slides/ajg/assets/interarea_mode.gif
"""
import json, math, os
import numpy as np
os.chdir("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

z = np.load("docs/data/agc/mm_traces_west.npz", allow_pickle=True)
t, w, f0 = z["t"], z["w"], float(z["f0"])
dlt = z["d"]                            # 各機の位相角δ [rad]
lon, lat, S, M = z["lon"], z["lat"], z["S"], z["M"]
trip = int(z["trip"])
fin = np.isfinite(w)
coi = np.array([(M[m] * w[m, i]).sum() / M[m].sum()
                if (m := fin[:, i]).any() else np.nan for i in range(len(t))])
rel = (w - coi[None, :]) * f0          # COI相対周波数[Hz]
gW = np.where(np.isfinite(lon) & (lon < 132.5))[0]
gE = np.where(np.isfinite(lon) & (lon > 134.5))[0]
def gmean(idx):
    x = rel[idx]
    return np.nansum(M[idx][:, None] * x, axis=0) / np.maximum(
        (M[idx][:, None] * np.isfinite(x)).sum(axis=0), 1e-9)
a, b = gmean(gW), gmean(gE)

def gang(idx):
    """群のM加重平均位相角 [rad]。"""
    x = dlt[idx]
    return np.nansum(M[idx][:, None] * x, axis=0) / np.maximum(
        (M[idx][:, None] * np.isfinite(x)).sum(axis=0), 1e-9)
ddeg = np.degrees(gang(gW) - gang(gE))
ddeg = ddeg - ddeg[0]                   # 初期潮流分を除いた角度差の偏差 [deg]
dmax = float(np.nanmax(np.abs(ddeg[:int(8.7 / (t[1] - t[0]))])))
cW = (float(np.average(lon[gW], weights=M[gW])),
      float(np.average(lat[gW], weights=M[gW])))
cE = (float(np.average(lon[gE], weights=M[gE])),
      float(np.average(lat[gE], weights=M[gE])))

bjs = json.load(open("docs/data/built/all.json"))
X0, X1, Y0, Y1 = 128.8, 137.8, 30.6, 37.4
segs = [[(p[1], p[0]) for p in e["path"]] for e in bjs["edges"]
        if e.get("path") and len(e["path"]) >= 2
        and Y0 <= e["path"][0][0] <= Y1 and X0 <= e["path"][0][1] <= X1]

BG = "#0A0D1A"
SPAN = 0.12   # ±0.12Hzで彩度飽和(振幅maxに合わせる)
def rcol(v):
    x = max(-1.0, min(1.0, v / SPAN))
    if x >= 0:   # 進み=青
        c0, c1 = np.array([0.16, 0.19, 0.33]), np.array([0.30, 0.62, 1.0])
        return c0 + (c1 - c0) * x
    c0, c1 = np.array([0.16, 0.19, 0.33]), np.array([1.0, 0.32, 0.28])
    return c0 + (c1 - c0) * (-x)

ms = 26.0 * np.sqrt(np.maximum(S, 5.0) / 500.0)
frames, durs = [], []
for ts in np.arange(1.0, 8.62, 0.12):
    k = min(len(t) - 1, int(np.searchsorted(t, ts)))
    fig = plt.figure(figsize=(12.8, 7.2), dpi=110)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.0, 0.0, 0.64, 1.0]); ax.set_facecolor(BG)
    ax.set_xlim(X0, X1); ax.set_ylim(Y0, Y1)
    ax.set_aspect(1.0 / math.cos(math.radians(34.0))); ax.axis("off")
    ax.add_collection(LineCollection(segs, colors="#242B49", linewidths=0.45,
                                     alpha=0.85, zorder=1))
    for i in range(w.shape[0]):
        if not np.isfinite(lon[i]) or not np.isfinite(rel[i, k]):
            continue
        ax.scatter([lon[i]], [lat[i]], s=ms[i], color=rcol(rel[i, k]),
                   zorder=5, linewidths=0.3, edgecolors="#FFFFFF", alpha=0.95)
    ax.scatter([lon[trip]], [lat[trip]], marker="X", s=260, c="#D62728",
               edgecolors="#FFFFFF", linewidths=0.9, zorder=8)
    # 綱引き矢印: 進んだ群(Δδ大)→遅れた群へ、sin(Δδ)に比例した電力が流れる
    dv = ddeg[k]
    if abs(dv) > 0.02 * dmax:
        src, dst = (cW, cE) if dv > 0 else (cE, cW)
        acol = "#FF6B5E" if dv > 0 else "#4E9BFF"
        ax.annotate("", xy=dst, xytext=src, zorder=9,
                    arrowprops=dict(arrowstyle="-|>", color=acol,
                                    lw=1.0 + 5.0 * abs(dv) / dmax,
                                    mutation_scale=18 + 26 * abs(dv) / dmax,
                                    alpha=0.9,
                                    connectionstyle="arc3,rad=-0.18"))
        mx, my = (cW[0] + cE[0]) / 2, (cW[1] + cE[1]) / 2 + 1.15
        ax.text(mx, my, "電力 西→東" if dv > 0 else "電力 東→西",
                color=acol, fontsize=11.5, fontweight="bold",
                ha="center", zorder=9)
    ax.text(0.03, 0.955, "逆位相動揺 — 九州側と関西側の綱引き",
            transform=ax.transAxes, color="#FFFFFF", fontsize=19,
            fontweight="bold", va="top")
    ax.text(0.03, 0.895,
            f"西日本{w.shape[0]}機・最大機トリップ後のCOI相対周波数(青=進み/赤=遅れ)",
            transform=ax.transAxes, color="#A7B0CB", fontsize=12, va="top")
    ax.text(0.03, 0.845, f"事故から {ts-1.0:4.2f} 秒",
            transform=ax.transAxes, color="#FFD60A", fontsize=15,
            fontweight="bold", va="top")
    ax.text(0.03, 0.05,
            "しくみ: 2つの慣性群が中間の長い送電回廊(=ばね)で繋がれた2重り系。\n"
            "進んだ群からは位相差に応じた電力が流れ出して減速し、遅れた群は受けて加速 —\n"
            f"この引き合いの繰り返しが綱引き。西G(九州側{len(gW)}機)×東G(関西以東{len(gE)}機)、\n"
            "相関 −0.999 / 周期 2.4 s(慣性と連系剛性T_abが決める固有値・実網から測定)",
            transform=ax.transAxes, color="#8E96B8", fontsize=9.5, va="bottom")
    # 右上: 2グループの綱引き波形
    axw = fig.add_axes([0.68, 0.50, 0.30, 0.40]); axw.set_facecolor("#11152A")
    axw.plot(t, a, lw=1.8, color="#FF6B5E", label=f"西G(九州側 {len(gW)}機)")
    axw.plot(t, b, lw=1.8, color="#4E9BFF", label=f"東G(関西側 {len(gE)}機)")
    axw.axvline(t[k], color="#FFD60A", lw=1.5)
    axw.axhline(0, color="#3A4266", lw=0.8)
    axw.set_xlim(0.8, 8.6); axw.set_ylim(-0.14, 0.14)
    axw.tick_params(colors="#8E96B8", labelsize=8)
    for sp in axw.spines.values():
        sp.set_color("#3A4266")
    axw.legend(loc="upper right", fontsize=9, facecolor="#11152A",
               labelcolor="#C8CDD8", edgecolor="#3A4266")
    axw.set_title("グループ平均のCOI相対周波数 [Hz]", color="#C8CDD8",
                  fontsize=10.5)
    # 右下: 綱=群間の位相角差Δδ。進んだ側から遅れた側へ電力(ばね力)が流れ、
    # 引き戻される — この繰り返しが逆位相動揺
    axg = fig.add_axes([0.68, 0.09, 0.30, 0.33]); axg.set_facecolor("#11152A")
    axg.plot(t, ddeg, lw=1.7, color="#E8C36A")
    axg.axvline(t[k], color="#FFD60A", lw=1.5)
    axg.axhline(0, color="#3A4266", lw=0.8)
    axg.set_xlim(0.8, 8.6); axg.set_ylim(-1.25 * dmax, 1.25 * dmax)
    axg.tick_params(colors="#8E96B8", labelsize=8)
    for sp in axg.spines.values():
        sp.set_color("#3A4266")
    axg.set_title("綱の張り = 群間の位相角差Δδ [deg](初期潮流分を除く)",
                  color="#C8CDD8", fontsize=10)
    axg.text(0.03, 0.86,
             "Δδ>0: 西G進み → 電力 西→東 → 西G減速(引き戻し)",
             transform=axg.transAxes, color="#FF6B5E", fontsize=8.2)
    axg.text(0.03, 0.08,
             "Δδ<0: 東G進み → 電力 東→西 → 東G減速(引き戻し)",
             transform=axg.transAxes, color="#4E9BFF", fontsize=8.2)
    axg.set_xlabel("時間 [s]", color="#8E96B8", fontsize=9)
    fig.canvas.draw()
    frames.append(np.asarray(fig.canvas.buffer_rgba())[..., :3].copy())
    plt.close(fig)
    durs.append(170)
durs[-1] = 2500
from PIL import Image
ims = [Image.fromarray(f) for f in frames]
out = "docs/slides/ajg/assets/interarea_mode.gif"
ims[0].save(out, save_all=True, append_images=ims[1:], duration=durs, loop=0,
            optimize=True)
print(f"-> {out} ({len(ims)}フレーム, {os.path.getsize(out)/1e6:.1f}MB)")
