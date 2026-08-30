#!/usr/bin/env python3
"""動揺の波が系統を走るアニメGIF — 実インピーダンスの見せ所(2026-08-29).

オーナー指示「せっかくインピーダンス出してあるので、系統端っこで動揺は
遅れたりするはず。全体もっと動きが見たい」「地図右上に横軸時系列の波形も」。

多機共シミュレーション(run_multimachine_national.py が dump した
mm_traces_<island>.npz)から:
  - 左: 実座標の各機を丸で描き、色=その機のローカル周波数(青=定格/赤=低下)。
    事故点から電気的距離に応じて色変化が「遅れて」伝わる様子が見える。
    背景は実系統の線形(暗色)。
  - 右上: 全機の周波数波形(細線)+COI(黒太)+現在時刻カーソル — 地図と同期。
時間軸は可変速(事故直後は超スロー: 電気機械波が見える速度)。

出力: docs/slides/ajg/assets/agc_<island>_wave.gif
Usage: PYTHONPATH=. python scripts/gen_swing_wave_anim.py [--island east]
"""
from __future__ import annotations

import argparse
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

BG = "#0A0D1A"
BBOX = {"east": (136.5, 142.7, 34.4, 41.8, 38.0),
        "hokkaido": (139.2, 146.3, 41.3, 45.9, 43.0),
        "west": (129.3, 138.2, 30.8, 37.6, 34.0),
        "okinawa": (127.5, 128.4, 26.0, 26.95, 26.5)}


def freq_cmap(f_rel, span):
    """Δf(Hz) → 色。0=氷青 → −span=深赤(白経由)."""
    x = min(max(-f_rel / span, 0.0), 1.0)
    if x < 0.5:
        u = x / 0.5
        c0, c1 = np.array([0.55, 0.75, 1.0]), np.array([1.0, 0.97, 0.85])
    else:
        u = (x - 0.5) / 0.5
        c0, c1 = np.array([1.0, 0.97, 0.85]), np.array([0.88, 0.10, 0.10])
    return c0 + (c1 - c0) * u


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--island", default="east")
    args = ap.parse_args()
    island = args.island
    z = np.load(f"docs/data/agc/mm_traces_{island}.npz", allow_pickle=True)
    t, w, f0 = z["t"], z["w"], float(z["f0"])
    lon, lat, S = z["lon"], z["lat"], z["S"]
    trip = int(z["trip"])
    live = z["live"]
    M = z["M"]
    ev_t, ev_s = z["ev_t"], z["ev_s"]
    n = w.shape[0]
    fmach = f0 + w * f0                       # 各機の周波数 [Hz]
    coi = f0 + (M[live][:, None] * w[live]).sum(0) / M[live].sum() * f0
    # 色スパンは0.25Hz固定 — 初期の伝播(数十mHz差)を見せるための感度。
    # ナディア近傍では全機が深赤に飽和する(=「系統全体が沈んだ」の表現)
    span = 0.25

    # 背景の線形
    b = json.load(open("docs/data/built/all.json"))
    x0, x1, y0, y1, latc = BBOX[island]
    segs = []
    for e in b["edges"]:
        path = e.get("path")
        if path and len(path) >= 2 and y0 <= path[0][0] <= y1 and \
                x0 <= path[0][1] <= x1:
            segs.append([(p[1], p[0]) for p in path])

    # 可変速タイムライン(事故=1.0s)
    TL = ([(0.0, 3)] +
          [(1.0 + 0.04 * i, 2) for i in range(50)] +    # 0-2s: 超スロー(波)
          [(3.0 + 0.2 * i, 2) for i in range(20)] +     # 〜7s
          [(7.0 + 1.0 * i, 1) for i in range(23)])      # 〜30s
    frames = []
    ms = 26.0 * np.sqrt(np.maximum(S, 5.0) / 500.0)
    for t_sim, hold in TL:
        k = min(len(t) - 1, int(t_sim / 0.02))
        fig = plt.figure(figsize=(9.6, 7.2), dpi=100)
        fig.patch.set_facecolor(BG)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_facecolor(BG)
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        ax.set_aspect(1.0 / math.cos(math.radians(latc)))
        ax.axis("off")
        ax.add_collection(LineCollection(segs, colors="#2A3050",
                                         linewidths=0.5, alpha=0.8, zorder=1))
        # 各機: ローカル周波数で着色(切離し済みはNaN→描かない)
        for i in range(n):
            fi = fmach[i, k]
            if not np.isfinite(fi) or not np.isfinite(lon[i]):
                continue
            c = freq_cmap(fi - f0, span)
            ax.scatter([lon[i]], [lat[i]], s=ms[i], color=c, zorder=5,
                       edgecolors="#FFFFFF", linewidths=0.3, alpha=0.95)
        # 事故点
        if t_sim < 1.0:
            ax.scatter([lon[trip]], [lat[trip]], marker="*", s=650,
                       c="#FFE28A", edgecolors="#FF9500", linewidths=1.4,
                       zorder=8)
        else:
            ax.scatter([lon[trip]], [lat[trip]], marker="X", s=380,
                       c="#D62728", edgecolors="#FFFFFF", linewidths=1.1,
                       zorder=8)
        # HUD(左上)
        tt = t_sim - 1.0
        lbl = ("事故前" if tt < 0 else
               f"事故から {tt*1000:5.0f} ミリ秒" if tt < 2.0 else
               f"事故から {tt:5.1f} 秒")
        ax.text(0.025, 0.965, f"{island}系統 — 動揺の波の伝播(モデル実験)",
                transform=ax.transAxes, color="#C8CDD8", fontsize=14,
                fontweight="bold", va="top")
        ax.text(0.025, 0.912, lbl, transform=ax.transAxes, color="#FFFFFF",
                fontsize=19, fontweight="bold", va="top")
        ax.text(0.025, 0.856, f"系統平均 {coi[k]:6.2f} Hz",
                transform=ax.transAxes,
                color=freq_cmap(coi[k] - f0, span), fontsize=15,
                fontweight="bold", va="top")
        # 右下の波形パネル(x≥0.585)の下に潜らない幅に折り返す
        ax.text(0.025, 0.075,
                "丸=発電機(実座標・大きさ=定格)\n"
                "色=その機のローカル周波数\n"
                "  (青=50Hz → 赤=−0.25Hz以深で飽和)\n"
                "事故点から遠い機ほど遅れて落ち始める\n"
                "  (実網インピーダンス由来)",
                transform=ax.transAxes, color="#6E79A8", fontsize=8.5,
                va="bottom", linespacing=1.45)
        # 右下(太平洋上): 同期波形パネル — 東北の機と重ならない位置
        axw = fig.add_axes([0.585, 0.09, 0.385, 0.30])
        axw.set_facecolor("#11152A")
        for i in range(n):
            if i == trip:
                continue
            axw.plot(t, fmach[i], lw=0.4, color="#5A78B8", alpha=0.35)
        axw.plot(t, coi, lw=1.6, color="#FFFFFF")
        axw.axvline(t[k], color="#FFD60A", lw=1.4)
        for te in ev_t:
            axw.axvline(te, color="#C62828", lw=0.7, ls=":", alpha=0.8)
        axw.set_xlim(0, min(30.0, float(t[-1])))
        axw.set_ylim(float(np.nanmin(coi)) - 0.35, f0 + 0.25)
        axw.tick_params(colors="#8E96B8", labelsize=8)
        for sp in axw.spines.values():
            sp.set_color("#3A4266")
        axw.set_title("全機の周波数と現在時刻", color="#C8CDD8", fontsize=10)
        axw.set_xlabel("時間 [s]", color="#8E96B8", fontsize=9)
        fig.canvas.draw()
        img = np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()
        plt.close(fig)
        frames.extend([img] * hold)

    from PIL import Image
    ims = [Image.fromarray(f) for f in frames]
    out = f"docs/slides/ajg/assets/agc_{island}_wave.gif"
    ims[0].save(out, save_all=True, append_images=ims[1:], duration=100,
                loop=0, optimize=True)
    print(f"-> {out} ({len(ims)}フレーム, {os.path.getsize(out)/1e6:.1f}MB)")


if __name__ == "__main__":
    main()
