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
    P = z["P"] if "P" in z.files else None
    dem = float(z["load_mw"].sum())
    Msum = float(M.sum())                       # Σ2HS/S_base [pu·s]
    dP = float(P[int(z["trip"])]) if P is not None else float("nan")
    nadir = float(np.nanmin(coi))
    data[isl] = dict(t=t, w=w, f0=f0, lon=z["lon"], lat=z["lat"], S=z["S"],
                     coi=coi, trip=int(z["trip"]),
                     name=str(z["names"][int(z["trip"])]),
                     n=w.shape[0], dem=dem, Msum=Msum, dP=dP, nadir=nadir,
                     ratio=dP / dem * 100.0,           # 脱落量/需要 [%]
                     dfpu=(nadir - f0) / f0 * 100.0)   # 最大偏差 [%](pu換算)

X0, X1, Y0, Y1 = 128.9, 142.9, 30.7, 41.9
b = json.load(open("docs/data/built/all.json"))
segs = [[(p[1], p[0]) for p in e["path"]] for e in b["edges"]
        if e.get("path") and len(e["path"]) >= 2
        and Y0 <= e["path"][0][0] <= Y1 and X0 <= e["path"][0][1] <= X1]

BG = "#0A0D1A"
def fcol(df, span=0.45):
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
    # タイトルはスライド側のテキストボックスへ(PowerPointで編集可能にするため)
    tt = ts - 1.0
    tlbl = "事故前" if tt < 0 else f"事故から {tt:5.1f} 秒"
    ax.text(0.02, 0.955,
            f"{tlbl} — ●の色=その機の周波数偏差"
            "(青=定格 → 白 → 赤=−0.45Hz以深)",
            transform=ax.transAxes, color="#A7B0CB", fontsize=11.5, va="top")
    ax.text(0.33, 0.13, "西日本(60Hz・298機)", transform=ax.transAxes,
            color="#4E9BFF", fontsize=12.5, fontweight="bold")
    ax.text(0.72, 0.60, "東日本(50Hz・183機)", transform=ax.transAxes,
            color="#FFB300", fontsize=12.5, fontweight="bold")
    ax.text(0.02, 0.045,
            "東西はFC(周波数変換所)経由の直流連系のみ — 動揺は互いに伝わらない\n"
            "各系統独立の実験を同時刻表示。×=脱落: 富津3,893MW(東)/川越3,990MW(西)",
            transform=ax.transAxes, color="#5A648F", fontsize=9.5, va="bottom")
    axw = fig.add_axes([0.715, 0.575, 0.265, 0.335]); axw.set_facecolor("#11152A")
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
    axw.set_title("東西のCOI周波数偏差 [Hz]", color="#C8CDD8", fontsize=10)
    axw.tick_params(labelbottom=True)
    # ── 下段: なぜ落ち方が違うのか(考察) ──
    axc = fig.add_axes([0.715, 0.075, 0.265, 0.375]); axc.set_facecolor("#11152A")
    axc.set_xticks([]); axc.set_yticks([])
    for sp in axc.spines.values():
        sp.set_color("#3A4266")
    de, dw = data["east"], data["west"]
    rows = [
        ("", "東 50Hz", "西 60Hz"),
        ("脱落量", f"{de['dP']:,.0f} MW", f"{dw['dP']:,.0f} MW"),
        ("需要に対する比", f"{de['ratio']:.2f} %", f"{dw['ratio']:.2f} %"),
        ("慣性 ΣM [pu·s]", f"{de['Msum']:,.0f}", f"{dw['Msum']:,.0f}"),
        ("最大偏差 [Hz]", f"{de['nadir']-de['f0']:+.3f}", f"{dw['nadir']-dw['f0']:+.3f}"),
        ("同 [%](pu換算)", f"{de['dfpu']:+.3f}", f"{dw['dfpu']:+.3f}"),
    ]
    for ri, (a, b2, c2) in enumerate(rows):
        y = 0.93 - ri * 0.118
        hd = (ri == 0)
        axc.text(0.03, y, a, transform=axc.transAxes, fontsize=8.2,
                 color="#C8CDD8" if hd else "#8E96B8", va="center",
                 fontweight="bold" if hd else "normal")
        axc.text(0.63, y, b2, transform=axc.transAxes, fontsize=8.2,
                 color="#FFB300", va="center", ha="right",
                 fontweight="bold")
        axc.text(0.985, y, c2, transform=axc.transAxes, fontsize=8.2,
                 color="#4E9BFF", va="center", ha="right", fontweight="bold")
    axc.text(0.03, 0.185,
             "西が浅いのは①系統が大きく脱落比が小さい②慣性が1.15倍\n"
             "③速い余力(水力)が1.7倍。落とし穴: 60Hz系は同じpu変化でも\n"
             "Hz表示が1.2倍大きく出る — Hzのまま直接比べると誤読する",
             transform=axc.transAxes, fontsize=7.4, color="#9EC1FF",
             va="top", linespacing=1.45)
    axc.set_title("なぜ落ち方が違うのか", color="#C8CDD8", fontsize=10, pad=3)
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
