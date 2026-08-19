#!/usr/bin/env python3
"""束導体の本数を変えたとき、抵抗とリアクタンスが「同じようには」変わらない理由。

抵抗は導体を n 本並列にすれば断面積が n 倍になるので単純に 1/n。
リアクタンスは磁束鎖交で決まり

    x = k · ln(D_eq / GMR)

の **対数の中** に効く。束ねると GMR は増えるが ln を通るので効果は急速に飽和し、
1/n にはならない。この非線形性のせいで、
「抵抗の比から推定した本数」と「リアクタンスの比から推定した本数」は一致しない。
**両者が同じ本数を指すかどうか自体が、仮説の検定になる。**

出力: docs/reports/figs/bundle_scaling.png
"""
from __future__ import annotations
import math
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
FIGS = ROOT / "docs/reports/figs"
for _f in ("Hiragino Sans", "Hiragino Kaku Gothic ProN", "YuGothic"):
    plt.rcParams["font.family"] = _f
    break
plt.rcParams["axes.unicode_minus"] = False
BG, C_R, C_X = "#faf8f1", "#cf4f5f", "#3a6ea5"
K50 = 2*math.pi*50*2e-7*1000


def gmr_single(area):
    return 0.78*math.sqrt(area/math.pi)


def gmr_n(g1, n, s=400.0):
    return {1: g1, 2: math.sqrt(g1*s), 3: (g1*s*s)**(1/3),
            4: 1.09*(g1*s**3)**0.25}[n]


def main():
    area, D = 330.0, 6000.0        # 187kV 想定
    g1 = gmr_single(area)
    ns = [1, 2, 3, 4]
    x = np.array([K50*math.log(D/gmr_n(g1, n)) for n in ns])
    r = np.array([1.0/n for n in ns])
    xr = x/x[0]

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12.8, 5.4), facecolor=BG,
                                 gridspec_kw={"width_ratios": [1.1, 1]})
    for a in (a1, a2):
        a.set_facecolor("#fffdf6")
        for s in a.spines.values():
            s.set_color("#dcd8cc")

    a1.plot(ns, r, "o-", color=C_R, lw=2.4, ms=9, label="抵抗 r（単導体を 1 とした比）")
    a1.plot(ns, xr, "s-", color=C_X, lw=2.4, ms=9, label="リアクタンス x（同）")
    for n, rv, xv in zip(ns, r, xr):
        a1.text(n, rv-.075, f"{rv:.2f}", ha="center", fontsize=10, color=C_R)
        a1.text(n, xv+.04, f"{xv:.2f}", ha="center", fontsize=10, color=C_X)
    a1.set_xticks(ns); a1.set_xlabel("1 相あたりの電線の本数", fontsize=11)
    a1.set_ylabel("単導体を 1 としたときの比", fontsize=11)
    a1.set_ylim(0, 1.15)
    a1.grid(alpha=.25, color="#dcd8cc")
    a1.legend(fontsize=10, frameon=False, loc="upper right")
    a1.set_title("本数を増やしたときの効き方は、抵抗とリアクタンスで違う\n"
                 "抵抗は 1/n で素直に下がるが、リアクタンスはすぐ飽和する",
                 fontsize=12, loc="left", color="#1a1a17", pad=10)
    a1.annotate("4 本にしても\nリアクタンスは半分強までしか下がらない",
                xy=(4, xr[3]), xytext=(2.5, .72), fontsize=9.5, color=C_X,
                arrowprops=dict(arrowstyle="->", color=C_X, lw=1.2))

    # 右: 抵抗とリアクタンスから独立に「実効導体本数」を逆算し、一致を見る
    g2 = gmr_n(g1, 2)
    r_ratio, x_ratio = 1.49, 1.19          # 実測 / 現在の仮定(2導体)
    r_eff = 0.5*r_ratio                    # 単導体を1としたときの実測抵抗
    x_eff = (K50*math.log(D/g2)/x[0])*x_ratio
    n_r = 1.0/r_eff

    def xrel(n):
        g = g1 + (g2-g1)*(n-1.0)
        return K50*math.log(D/g)/x[0]
    lo, hi = 1.0, 2.0
    for _ in range(60):
        m = (lo+hi)/2
        lo, hi = (m, hi) if xrel(m) > x_eff else (lo, m)
    n_x = (lo+hi)/2

    nn = np.linspace(1, 2, 200)
    a2.plot(nn, [1.0/n_ for n_ in nn], color=C_R, lw=2.2, label="抵抗から（1/n）")
    a2.plot(nn, [xrel(n_) for n_ in nn], color=C_X, lw=2.2, label="リアクタンスから（対数）")
    a2.axhline(r_eff, color=C_R, ls=":", lw=1.4)
    a2.axhline(x_eff, color=C_X, ls=":", lw=1.4)
    a2.plot([n_r], [r_eff], "o", color=C_R, ms=11, mec="white", mew=1.4, zorder=5)
    a2.plot([n_x], [x_eff], "s", color=C_X, ms=11, mec="white", mew=1.4, zorder=5)
    a2.annotate(f"抵抗が示す本数\n{n_r:.2f} 本", xy=(n_r, r_eff), xytext=(1.55, .60),
                fontsize=10, color=C_R, arrowprops=dict(arrowstyle="->", color=C_R, lw=1.2))
    a2.annotate(f"リアクタンスが示す本数\n{n_x:.2f} 本", xy=(n_x, x_eff), xytext=(1.05, .93),
                fontsize=10, color=C_X, arrowprops=dict(arrowstyle="->", color=C_X, lw=1.2))
    a2.axvspan(min(n_r, n_x)-.02, max(n_r, n_x)+.02, color="#1f9e8a", alpha=.16, zorder=1)
    a2.set_xlim(1, 2); a2.set_ylim(.45, 1.05)
    a2.set_xlabel("1 相あたりの実効的な電線の本数", fontsize=11)
    a2.set_ylabel("単導体を 1 としたときの比", fontsize=11)
    a2.grid(alpha=.25, color="#dcd8cc")
    a2.legend(fontsize=9.5, frameon=False, loc="upper right")
    a2.set_title("187 kV — 独立な 2 つの量が、同じ本数を指す\n"
                 f"抵抗 {n_r:.2f} 本 / リアクタンス {n_x:.2f} 本（差 {abs(n_r-n_x):.2f} 本）",
                 fontsize=12, loc="left", color="#1a1a17", pad=10)
    fig.tight_layout()
    out = FIGS/"bundle_scaling.png"
    fig.savefig(out, dpi=180, facecolor=BG); plt.close(fig)
    print(f"  {out.name}")
    print(f"  単導体基準: r = {list(np.round(r,3))} / x = {list(np.round(xr,3))}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
