#!/usr/bin/env python3
"""観測リアクタンスから導体構成の仮説を検定する（原因の究明）。

観測: 187kV の実効 x が標準値の 1.19 倍（r は 1.49 倍）過小。
仮説: `line_types.yaml` の「ACSR 330mm² **×2導体**」という仮定が誤りで、実態は単導体。
理論: 架空送電線の作用リアクタンスは

    x = 2πf · 2×10⁻⁷ · ln(D_eq / GMR)   [Ω/m]

  GMR は導体の等価半径。束導体は GMR が大きくなるので x が下がる。
  → 観測 x から D_eq を逆算し、**その電圧階級の設計線間距離と整合するか**で仮説を判定する。

出力: docs/reports/figs/conductor_hypothesis.png
"""
from __future__ import annotations
import math
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
FIGS = ROOT / "docs/reports/figs"
for _f in ("Hiragino Sans", "Hiragino Kaku Gothic ProN", "YuGothic"):
    plt.rcParams["font.family"] = _f
    break
plt.rcParams["axes.unicode_minus"] = False
BG = "#faf8f1"
K50 = 2*math.pi*50*2e-7*1000        # Ω/km


def gmr_single(area_mm2):
    d = 2*math.sqrt(area_mm2/math.pi)
    return 0.78*d/2


def gmr_bundle(g1, n, s=400.0):
    return {1: g1, 2: math.sqrt(g1*s), 3: (g1*s*s)**(1/3),
            4: 1.09*(g1*s**3)**0.25}[n]


OBS = {66: (0.436, 160, 1), 110: (0.373, 240, 1), 154: (0.425, 330, 1),
       187: (0.416, 330, 2), 220: (0.377, 410, 2), 275: (0.322, 410, 2),
       500: (0.326, 810, 4)}
DRANGE = {66: (2.0, 3.5), 110: (3.0, 4.5), 154: (4.0, 6.0), 187: (4.5, 6.5),
          220: (5.0, 7.5), 275: (6.0, 9.0), 500: (9.0, 13.0)}


def main():
    fig = plt.figure(figsize=(13.6, 6.6), facecolor=BG)
    gs = fig.add_gridspec(1, 2, width_ratios=[.82, 1.18], wspace=.18)

    # --- 左: 概念図 ---
    ax = fig.add_subplot(gs[0]); ax.set_facecolor("#fffdf6")
    ax.set_xlim(0, 10); ax.set_ylim(0, 10); ax.axis("off")
    ax.set_title("なぜ束導体だと x が下がるのか", fontsize=12.5, loc="left",
                 color="#1a1a17", pad=8)
    g1 = gmr_single(330)
    for j, (n, cx, cy, lab) in enumerate([(1, 2.4, 7.2, "単導体"), (2, 7.0, 7.2, "2 導体")]):
        g = gmr_bundle(g1, n)
        if n == 1:
            ax.add_patch(Circle((cx, cy), .42, color="#3a6ea5", zorder=3))
        else:
            for dx in (-.75, .75):
                ax.add_patch(Circle((cx+dx, cy), .42, color="#3a6ea5", zorder=3))
            ax.annotate("", xy=(cx+.75, cy-.85), xytext=(cx-.75, cy-.85),
                        arrowprops=dict(arrowstyle="<->", color="#928f84", lw=1.1))
            ax.text(cx, cy-1.35, "素導体間隔 400 mm", ha="center", fontsize=8.5,
                    color="#52504a")
        ax.add_patch(Circle((cx, cy), 1.35 if n == 2 else .55, fill=False,
                            ec="#cf4f5f", lw=1.6, ls=(0, (4, 3)), zorder=4))
        ax.text(cx, cy+1.9 if n == 2 else cy+1.15, f"GMR = {g:.0f} mm",
                ha="center", fontsize=10, color="#cf4f5f", fontweight="bold")
        ax.text(cx, cy-2.1, lab, ha="center", fontsize=11, color="#1a1a17",
                fontweight="bold")
    ax.text(5, 3.9, r"$x = 2\pi f \cdot 2\times10^{-7} \cdot \ln\!\left(\frac{D_{eq}}{GMR}\right)$",
            ha="center", fontsize=15, color="#1a1a17")
    ax.text(5, 2.6, "GMR が 7 倍になると ln の中身が 1/7 →\n"
                    "x は約 30 % 下がる（同じ線間距離なら）",
            ha="center", fontsize=10, color="#52504a")
    ax.add_patch(FancyBboxPatch((.6, .4), 8.8, 1.6, boxstyle="round,pad=.15",
                                fc="#fff", ec="#dcd8cc"))
    ax.text(5, 1.2, "→ 逆に、観測 x から D_eq を逆算すれば\n"
                    "  「その導体構成で物理的に成立するか」を判定できる",
            ha="center", va="center", fontsize=10.5, color="#1a1a17")

    # --- 右: 逆算した必要 D vs 設計範囲 ---
    ax2 = fig.add_subplot(gs[1]); ax2.set_facecolor("#fffdf6")
    ks = sorted(OBS)
    y = np.arange(len(ks))
    for i, kv in enumerate(ks):
        x_obs, area, n = OBS[kv]
        lo, hi = DRANGE[kv]
        ax2.barh(i, hi-lo, left=lo, height=.55, color="#9fd9cc", alpha=.65,
                 zorder=2, label="設計上の線間距離レンジ" if i == 0 else None)
        g = gmr_bundle(gmr_single(area), n)
        D = math.exp(x_obs/K50)*g/1000
        okc = "#1f9e8a" if lo*.85 <= D <= hi*1.15 else "#cf4f5f"
        ax2.plot([D], [i], "D", color=okc, ms=9, mec="white", mew=1.2, zorder=5,
                 label="観測 x から逆算した必要 D（現在の導体仮定）" if i == 0 else None)
        if D > hi*1.15:
            g1_ = gmr_single(area)
            D1 = math.exp(x_obs/K50)*g1_/1000
            ax2.plot([D1], [i], "o", color="#3a6ea5", ms=8, mec="white", mew=1.2,
                     zorder=5, label="単導体と仮定し直した場合" if kv == 187 else None)
            ax2.annotate("", xy=(D1, i), xytext=(D, i),
                         arrowprops=dict(arrowstyle="->", color="#3a6ea5", lw=1.3))
        ax2.text(min(D, 46)*1.03, i-.3, f"{D:.0f} m", fontsize=8.5, color=okc)
    ax2.set_yticks(y)
    ax2.set_yticklabels([f"{k} kV\n{OBS[k][1]}mm² ×{OBS[k][2]}" for k in ks], fontsize=9)
    ax2.set_xscale("log")
    ax2.set_xlim(1.5, 60)
    ax2.set_xlabel("等価線間距離 D_eq [m]（対数）", fontsize=10.5)
    ax2.grid(axis="x", alpha=.25, color="#dcd8cc", which="both")
    for s in ax2.spines.values():
        s.set_color("#dcd8cc")
    ax2.legend(fontsize=9, frameon=False, loc="lower right")
    ax2.set_title("観測 x から逆算した D_eq が設計範囲に収まるか\n"
                  "★187kV: 2導体だと 42 m が必要＝物理的にありえない／単導体なら 6.0 m で整合",
                  fontsize=12, loc="left", color="#1a1a17", pad=8)
    out = FIGS/"conductor_hypothesis.png"
    fig.savefig(out, dpi=180, facecolor=BG, bbox_inches="tight"); plt.close(fig)
    print(f"  {out.name}")
    for kv in ks:
        x_obs, area, n = OBS[kv]
        g = gmr_bundle(gmr_single(area), n)
        D = math.exp(x_obs/K50)*g/1000
        D1 = math.exp(x_obs/K50)*gmr_single(area)/1000
        lo, hi = DRANGE[kv]
        print(f"    {kv:>4}kV ×{n}: D={D:6.1f}m (設計 {lo}-{hi}m)"
              + (f" → 単導体なら {D1:.1f}m" if n > 1 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
