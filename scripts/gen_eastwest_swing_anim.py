#!/usr/bin/env python3
"""東西動揺GIF — 50Hz東系統(183機)と60Hz西系統(298機)、各最大機N-1(2026-08-30).

オーナー指摘(2026-08-30)への応答: 4島合成は「沖縄は無関係・北海道は連系線の
話になる」ため東西2系統のみに絞る。東西はFC(周波数変換所)経由の直流連系のみで
動揺は互いに伝わらない — 各島独立の実験を同時刻表示(その旨明記)。

出力: docs/slides/ajg/assets/eastwest_swing.gif
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

ISLANDS = ["east", "west"]
COL = {"east": "#FFB300", "west": "#4E9BFF"}
data = {}
for isl in ISLANDS:
    z = np.load(f"docs/data/agc/mm_traces_{isl}.npz", allow_pickle=True)
    t, w, f0, M = z["t"], z["w"], float(z["f0"]), z["M"]
    fin = np.isfinite(w)
    coi = np.array([f0 + (M[m] * w[m, i]).sum() / M[m].sum() * f0
                    if (m := fin[:, i]).any() else np.nan
                    for i in range(len(t))])
    data[isl] = dict(t=t, w=w, f0=f0, lon=z["lon"], lat=z["lat"], S=z["S"],
                     coi=coi, trip=int(z["trip"]),
                     name=str(z["names"][int(z["trip"])]))

X0, X1, Y0, Y1 = 128.9, 142.9, 30.7, 41.9
b = json.load(open("docs/data/built/all.json"))
segs = [[(p[1], p[0]) for p in e["path"]] for e in b["edges"]
        if e.get("path") and len(e["path"]) >= 2
        and Y0 <= e["path"][0][0] <= Y1 and X0 <= e["path"][0][1] <= X1]

BG = "#0A0D1A"
def fcol(df, span=0.6):
    x = min(max(-df / span, 0.0), 1.0)
    if x < 0.5:
        u = x / 0.5
        c0, c1 = np.array([0.56, 0.72, 1.0]), np.array([1.0, 0.97, 0.85])
    else:
        u = (x - 0.5) / 0.5
        c0, c1 = np.array([1.0, 0.97, 0.85]), np.array([0.88, 0.1, 0.1])
    return c0 + (c1 - c0) * u

frames, durs = [], []
TL = ([(0.5, 900)] + [(1.0 + 0.25 * i, 350) for i in range(16)]
      + [(5.0 + 1.0 * i, 300) for i in range(10)]
      + [(15.0 + 5.0 * i, 350) for i in range(4)])
for ts, du in TL:
    fig = plt.figure(figsize=(12.8, 7.2), dpi=110)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.0, 0.0, 0.68, 1.0]); ax.set_facecolor(BG)
    ax.set_xlim(X0, X1); ax.set_ylim(Y0, Y1)
    ax.set_aspect(1.0 / math.cos(math.radians(36.0))); ax.axis("off")
    ax.add_collection(LineCollection(segs, colors="#232A45", linewidths=0.4,
                                     alpha=0.75, zorder=1))
    for isl in ISLANDS:
        d = data[isl]
        k = min(len(d["t"]) - 1, int(np.searchsorted(d["t"], ts)))
        ms = 17.0 * np.sqrt(np.maximum(d["S"], 5.0) / 500.0)
        for i in range(d["w"].shape[0]):
            if not np.isfinite(d["lon"][i]):
                continue
            v = d["w"][i, k]
            if not np.isfinite(v):
                if i == d["trip"] and ts >= 1.0:
                    ax.scatter([d["lon"][i]], [d["lat"][i]], marker="X",
                               s=230, c="#D62728", edgecolors="#FFFFFF",
                               linewidths=0.8, zorder=8)
                continue
            ax.scatter([d["lon"][i]], [d["lat"][i]], s=ms[i],
                       color=fcol(v * d["f0"]), zorder=5,
                       edgecolors="#FFFFFF", linewidths=0.22, alpha=0.95)
    ax.text(0.02, 0.965, "東西動揺 — 50Hz系統と60Hz系統、それぞれの最大機N-1",
            transform=ax.transAxes, color="#FFFFFF", fontsize=17.5,
            fontweight="bold", va="top")
    ax.text(0.02, 0.912,
            f"事故から {ts-1.0:5.1f} 秒 — ●の色=その機の周波数偏差"
            "(青=定格 → 白 → 赤=−0.6Hz以深)",
            transform=ax.transAxes, color="#A7B0CB", fontsize=11.5, va="top")
    ax.text(0.33, 0.13, "西日本(60Hz・298機)", transform=ax.transAxes,
            color="#4E9BFF", fontsize=12.5, fontweight="bold")
    ax.text(0.72, 0.60, "東日本(50Hz・183機)", transform=ax.transAxes,
            color="#FFB300", fontsize=12.5, fontweight="bold")
    ax.text(0.02, 0.045,
            "東西はFC(周波数変換所)経由の直流連系のみ — 動揺は互いに伝わらない\n"
            "各系統独立の実験を同時刻表示。×=脱落: 富津3,893MW(東)/川越3,990MW(西)",
            transform=ax.transAxes, color="#5A648F", fontsize=9.5, va="bottom")
    axw = fig.add_axes([0.715, 0.12, 0.265, 0.76]); axw.set_facecolor("#11152A")
    for isl in ISLANDS:
        d = data[isl]
        axw.plot(d["t"], d["coi"] - d["f0"], lw=1.8, color=COL[isl],
                 label={"east": "東日本 COI", "west": "西日本 COI"}[isl])
    axw.axvline(ts, color="#FFD60A", lw=1.5)
    axw.set_xlim(0, 30); axw.set_ylim(-0.6, 0.15)
    axw.tick_params(colors="#8E96B8", labelsize=8)
    for sp in axw.spines.values():
        sp.set_color("#3A4266")
    axw.legend(loc="lower right", fontsize=9, facecolor="#11152A",
               labelcolor="#C8CDD8", edgecolor="#3A4266")
    axw.set_title("東西のCOI周波数偏差 [Hz] — 同規模の事故・同じ沈み方",
                  color="#C8CDD8", fontsize=10)
    axw.set_xlabel("時間 [s]", color="#8E96B8", fontsize=9)
    fig.canvas.draw()
    frames.append(np.asarray(fig.canvas.buffer_rgba())[..., :3].copy())
    plt.close(fig)
    durs.append(du)
durs[-1] = 3000
from PIL import Image
ims = [Image.fromarray(f) for f in frames]
out = "docs/slides/ajg/assets/eastwest_swing.gif"
ims[0].save(out, save_all=True, append_images=ims[1:], duration=durs, loop=0,
            optimize=True)
print(f"-> {out} ({len(ims)}フレーム, {os.path.getsize(out)/1e6:.1f}MB)")
