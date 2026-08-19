#!/usr/bin/env python3
"""「線間距離 42 m が必要」がどれほど非現実的かを、鉄塔の実寸で示す。

観測リアクタンスから逆算される等価線間距離 D_eq は、
導体構成の仮定によって 6.0 m（単導体）と 42.4 m（2 導体）に分かれる。
数字だけでは実感しにくいので、鉄塔の模式図として同一縮尺で並べる。

出力: docs/reports/figs/tower_scale.png
"""
from __future__ import annotations
import math
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle, FancyArrowPatch

ROOT = Path(__file__).resolve().parent.parent
FIGS = ROOT / "docs/reports/figs"
for _f in ("Hiragino Sans", "Hiragino Kaku Gothic ProN", "YuGothic"):
    plt.rcParams["font.family"] = _f
    break
plt.rcParams["axes.unicode_minus"] = False
BG = "#faf8f1"
C_T, C_C, C_NG = "#52504a", "#3a6ea5", "#cf4f5f"


def tower(ax, x0, D, h_base, col, label, sub, ok):
    """三角配置の 3 相を持つ鉄塔を、線間距離 D [m] で描く。"""
    h = h_base
    ax.plot([x0, x0], [0, h], color=C_T, lw=3, zorder=2, solid_capstyle="round")
    for i in range(1, 5):                      # トラス風の斜材
        y0, y1 = h*(i-1)/5, h*i/5
        w0, w1 = D*.28*(1-(i-1)/6), D*.28*(1-i/6)
        ax.plot([x0-w0, x0+w1], [y0, y1], color=C_T, lw=.9, alpha=.55, zorder=1)
        ax.plot([x0+w0, x0-w1], [y0, y1], color=C_T, lw=.9, alpha=.55, zorder=1)
    arms = [(h*0.97, 0), (h*0.80, -D/2), (h*0.80, D/2)]   # 三角配置
    for (ay, ax_off) in arms:
        if ax_off:
            ax.plot([x0, x0+ax_off], [ay, ay], color=C_T, lw=2.4, zorder=3)
        ax.add_patch(Circle((x0+ax_off, ay), max(D*.028, .35), color=col, zorder=4))
    # 線間距離の寸法線
    ax.add_patch(FancyArrowPatch((x0-D/2, h*0.72), (x0+D/2, h*0.72),
                                 arrowstyle="<->", color=col, lw=1.6, zorder=5,
                                 mutation_scale=13))
    ax.text(x0, h*0.72 - h*.05, f"線間距離 {D:.1f} m", ha="center", fontsize=11,
            color=col, fontweight="bold")
    ax.text(x0, -h*.07, label, ha="center", fontsize=12, fontweight="bold",
            color="#1a1a17")
    ax.text(x0, -h*.14, sub, ha="center", fontsize=9.5, color="#52504a")
    ax.text(x0, h*1.06, "○ 実在する" if ok else "× 存在しない", ha="center",
            fontsize=12, fontweight="bold", color=("#1f9e8a" if ok else C_NG))


def main():
    fig, ax = plt.subplots(figsize=(13.2, 7.0), facecolor=BG)
    ax.set_facecolor("#fffdf6")
    H1, H2 = 30.0, 75.0        # 鉄塔高さ（線間距離に見合う目安）
    tower(ax, 14, 6.0, H1, C_C, "単導体と仮定した場合", "187kV 鉄塔の実寸に一致", True)
    tower(ax, 62, 42.4, H2, C_NG, "2 導体と仮定した場合",
          "観測リアクタンスを説明するには\nこの幅が必要になる", False)

    # 人間とビルでスケールを示す
    ax.add_patch(Rectangle((100, 0), 3.2, 1.7, color="#52504a"))
    ax.text(101.6, 2.4, "人 1.7 m", ha="center", fontsize=9, color="#52504a")
    for f in range(5):
        ax.add_patch(Rectangle((108, f*3.0), 9, 2.7, fc="#dfe5ea", ec="#c8d3dd"))
    ax.text(112.5, 16.0, "5 階建て\n15 m", ha="center", fontsize=9, color="#52504a")
    ax.annotate("", xy=(96, 42.4), xytext=(96, 0),
                arrowprops=dict(arrowstyle="<->", color=C_NG, lw=1.4))
    ax.text(94, 21, "42 m\n≒ 14 階建ての高さ", ha="right", va="center",
            fontsize=10.5, color=C_NG, fontweight="bold")

    ax.set_xlim(-6, 125); ax.set_ylim(-14, 88)
    ax.set_aspect("equal"); ax.axis("off")
    ax.set_title("観測されたリアクタンスから逆算した「必要な線間距離」を、同じ縮尺で並べる\n"
                 "187 kV の実際の鉄塔は腕の幅がおよそ 6 m。42 m の鉄塔は存在しない",
                 fontsize=13, loc="left", color="#1a1a17", pad=14)
    ax.text(-4, -12,
            "線間距離＝隣り合う相（電線）どうしの間隔。リアクタンスは ln(線間距離 ÷ 電線の電気的な太さ) に比例するので、\n"
            "「電線を 2 本束ねている」と仮定すると電気的な太さが 7 倍になり、同じリアクタンスを説明するには線間距離を極端に広げるしかなくなる。",
            fontsize=9.5, color="#52504a", va="top")
    fig.tight_layout()
    out = FIGS/"tower_scale.png"
    fig.savefig(out, dpi=180, facecolor=BG, bbox_inches="tight"); plt.close(fig)
    print(f"  {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
