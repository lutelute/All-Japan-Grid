#!/usr/bin/env python3
"""全系統動揺GIF — 4島542機、各島の最大機N-1を同時刻表示(2026-08-30).

各島の正典多機トレース(mm_traces_{island}.npz・独立実験)を同一時間軸に
並べて国土全図で見る。合成表示であることを明記(実験は島ごとに独立・連系
線は跨がない)。右=4島のCOI周波数(規模差が一目で分かる)。

出力: docs/slides/ajg/assets/national_swing.gif
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

ISLANDS = ["hokkaido", "east", "west", "okinawa"]
COL = {"hokkaido": "#FF5252", "east": "#FFB300",
       "west": "#4E9BFF", "okinawa": "#2CD97B"}
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

b = json.load(open("docs/data/built/all.json"))
segs = [[(p[1], p[0]) for p in e["path"]] for e in b["edges"]
        if e.get("path") and len(e["path"]) >= 2]

BG = "#0A0D1A"
def fcol(df, span=1.2):
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
      + [(15.0 + 5.0 * i, 350) for i in range(10)])
for ts, du in TL:
    fig = plt.figure(figsize=(12.8, 7.2), dpi=110)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.0, 0.0, 0.66, 1.0]); ax.set_facecolor(BG)
    ax.set_xlim(128.6, 146.2); ax.set_ylim(30.2, 45.9)
    ax.set_aspect(1.0 / math.cos(math.radians(37.0))); ax.axis("off")
    ax.add_collection(LineCollection(segs, colors="#232A45", linewidths=0.4,
                                     alpha=0.75, zorder=1))
    n_tot = 0
    for isl in ISLANDS:
        d = data[isl]
        k = min(len(d["t"]) - 1, int(np.searchsorted(d["t"], ts)))
        ms = 15.0 * np.sqrt(np.maximum(d["S"], 5.0) / 500.0)
        for i in range(d["w"].shape[0]):
            if not np.isfinite(d["lon"][i]):
                continue
            v = d["w"][i, k]
            if not np.isfinite(v):
                if i == d["trip"] and ts >= 1.0:
                    ax.scatter([d["lon"][i]], [d["lat"][i]], marker="X",
                               s=190, c="#D62728", edgecolors="#FFFFFF",
                               linewidths=0.7, zorder=8)
                continue
            n_tot += 1
            ax.scatter([d["lon"][i]], [d["lat"][i]], s=ms[i],
                       color=fcol(v * d["f0"]), zorder=5,
                       edgecolors="#FFFFFF", linewidths=0.22, alpha=0.95)
    ax.text(0.025, 0.955, "全系統動揺 — 4島542機、それぞれの最大機N-1",
            transform=ax.transAxes, color="#FFFFFF", fontsize=18,
            fontweight="bold", va="top")
    ax.text(0.025, 0.90,
            f"事故から {ts-1.0:5.1f} 秒 — ●の色=その機の周波数偏差"
            "(青=定格 → 白 → 赤=−1.2Hz以深)",
            transform=ax.transAxes, color="#A7B0CB", fontsize=11.5, va="top")
    ax.text(0.025, 0.05,
            "各島の実験は独立(トリップを同時刻に揃えた合成表示・連系線は跨がない)\n"
            "×=脱落: 苫東厚真(北)/千葉(東)/最大機(西)/吉の浦(沖) — AGC-N・実網Kron縮約",
            transform=ax.transAxes, color="#5A648F", fontsize=9.5,
            va="bottom")
    axw = fig.add_axes([0.70, 0.12, 0.28, 0.76]); axw.set_facecolor("#11152A")
    for isl in ISLANDS:
        d = data[isl]
        axw.plot(d["t"], d["coi"] - d["f0"], lw=1.7, color=COL[isl],
                 label={"hokkaido": "北海道(−2.5Hz→UFLS)",
                        "east": "東日本", "west": "西日本",
                        "okinawa": "沖縄"}[isl])
    axw.axvline(ts, color="#FFD60A", lw=1.5)
    axw.axhline(-1.5, color="#C62828", lw=0.8, ls="--", alpha=0.7)
    axw.text(58, -1.44, "UFLS第1段", ha="right", color="#C62828", fontsize=7.5)
    axw.set_xlim(0, 60); axw.set_ylim(-3.0, 0.4)
    axw.tick_params(colors="#8E96B8", labelsize=8)
    for sp in axw.spines.values():
        sp.set_color("#3A4266")
    axw.legend(loc="lower right", fontsize=8.5, facecolor="#11152A",
               labelcolor="#C8CDD8", edgecolor="#3A4266")
    axw.set_title("4島のCOI周波数偏差 [Hz] — 慣性の差が沈み方の差",
                  color="#C8CDD8", fontsize=10)
    axw.set_xlabel("時間 [s]", color="#8E96B8", fontsize=9)
    fig.canvas.draw()
    frames.append(np.asarray(fig.canvas.buffer_rgba())[..., :3].copy())
    plt.close(fig)
    durs.append(du)
durs[-1] = 3000
from PIL import Image
ims = [Image.fromarray(f) for f in frames]
out = "docs/slides/ajg/assets/national_swing.gif"
ims[0].save(out, save_all=True, append_images=ims[1:], duration=durs, loop=0,
            optimize=True)
print(f"-> {out} ({len(ims)}フレーム, {os.path.getsize(out)/1e6:.1f}MB)")
