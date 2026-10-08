#!/usr/bin/env python3
"""同じデータから複数の答えが出る理由と、主張ごとの確からしさを一枚で示す。

上段: 187kV の「1 相あたりの電線の本数」を 3 通りの基準で逆算すると 0.9〜1.6 本に割れる。
      基準（何を正解とみなすか）を変えると答えが変わる＝絶対値は確定できない。
下段: それでも確定できることがある。主張を「確からしさ」の順に積む。
      下ほど強く、上ほど仮定に依存する。

出力: docs/reports/figs/evidence_ladder.png
"""
from __future__ import annotations
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

ROOT = Path(__file__).resolve().parent.parent
FIGS = ROOT / "docs/reports/figs"
for _f in ("Hiragino Sans", "Hiragino Kaku Gothic ProN", "YuGothic"):
    plt.rcParams["font.family"] = _f
    break
plt.rcParams["axes.unicode_minus"] = False
BG = "#faf8f1"

fig = plt.figure(figsize=(13.6, 9.4), facecolor=BG)
gs = fig.add_gridspec(2, 1, height_ratios=[.82, 1.18], hspace=.26)

# ===== 上段: 基準を変えると答えが変わる（横並びで重ならないように）=====
ax = fig.add_subplot(gs[0]); ax.set_facecolor("#fffdf6")
rows_top = [
    ("理論のリアクタンスを正解とみなす", 0.90, "#3a6ea5",
     "線間距離 6 m を仮定して逆算 → 線間距離の置き方で動く"),
    ("設定値を正解とみなす", 1.34, "#b3812f",
     "設定値 r=0.038 を「2 導体の値」として比を取る\n"
     "→ その設定値自体が単導体理論の 0.41 倍＝説明できない値（循環参照）"),
    ("理論の抵抗を正解とみなす", 1.60, "#cf4f5f",
     "単導体 ACSR 330mm² の理論抵抗 0.0918 Ω/km と比べる → 導電率の置き方で動く"),
]
ys = [2.0, 1.0, 0.0]
for (label, v, c, note), y in zip(rows_top, ys):
    ax.plot([0.6, v], [y, y], color=c, lw=1.4, ls=(0, (3, 2)), zorder=2, alpha=.5)
    ax.plot([v], [y], "o", color=c, ms=15, mec="white", mew=1.8, zorder=5)
    ax.text(v, y+.30, f"{v:.2f} 本", ha="center", fontsize=14, color=c, fontweight="bold")
    ax.text(0.58, y, label, ha="right", va="center", fontsize=11.5, color=c)
    ax.text(2.62, y, note, ha="left", va="center", fontsize=9, color="#52504a")
for v, lab in ((1, "1 本"), (2, "2 本")):
    ax.axvline(v, color="#dcd8cc", lw=1.4, zorder=1)
    ax.text(v, -.62, lab, ha="center", fontsize=11, color="#928f84")
ax.axvline(2.0, color="#1a1a17", lw=2.2, zorder=3)
ax.text(2.0, 2.62, "★ 設定ファイルの仮定 2 本", ha="center", fontsize=11.5,
        color="#1a1a17", fontweight="bold")
ax.axvspan(0.90, 1.60, color="#cf4f5f", alpha=.10, zorder=0)
ax.text(1.25, -.42, "同じ実測データなのに、答えは 0.9 〜 1.6 本に散る",
        ha="center", fontsize=12, color="#cf4f5f", fontweight="bold")
ax.set_xlim(0.05, 5.0); ax.set_ylim(-.85, 2.95)
ax.axis("off")
ax.set_title("なぜ「電線の本数」を確定できないのか\n"
             "— 逆算には必ず「何を正解とみなすか」が要り、それを変えると答えが変わる",
             fontsize=13.5, loc="left", color="#1a1a17", pad=10)

# ===== 下段: 確からしさの階層 =====
ax2 = fig.add_subplot(gs[1]); ax2.set_facecolor("#fffdf6")
ax2.set_xlim(0, 10); ax2.set_ylim(0, 5.2); ax2.axis("off")
rows = [
    (4.05, "#cf4f5f", "×", "実効的な電線の本数（絶対値）",
     "逆算には「線間距離」「導電率」という外から与えた仮定が要り、\n"
     "基準を変えると 0.9〜1.6 本に動く。小数第 1 位まで論じられない",
     "確定できない"),
    (2.85, "#b3812f", "△", "ずれの原因は導体構成の仮定である",
     "抵抗もリアクタンスも同じ向きにずれており、単導体なら両方説明できる。\n"
     "ただし 220・500・66 kV は同じ説明では合わず、未解決",
     "有力だが未確定"),
    (1.65, "#1f9e8a", "○", "187 kV の「2 導体」という仮定は誤り",
     "2 導体だと線間距離 42 m が必要になる（実際の鉄塔は約 6 m）。\n"
     "42 m 対 6 m は桁が違うので、仮定の精度では覆らない",
     "物理的に頑健"),
    (0.45, "#3a6ea5", "◎", "実測値は設定値と有意に異なる",
     "154・187・220・500 kV は、不確かさの幅（95%）が 1.0 をまたがない。\n"
     "110・275 kV はまたぐ＝差があるとは言えない（対照として機能）",
     "統計的に確実"),
]
for y, c, mark, title, body, tag in rows:
    ax2.add_patch(FancyBboxPatch((.5, y), 8.2, 1.0, boxstyle="round,pad=.06",
                                 fc="white", ec=c, lw=2.0))
    ax2.text(.85, y+.72, mark, fontsize=17, color=c, fontweight="bold", va="center")
    ax2.text(1.45, y+.74, title, fontsize=12.5, color="#1a1a17",
             fontweight="bold", va="center")
    ax2.text(1.45, y+.28, body, fontsize=9.5, color="#52504a", va="center")
    ax2.add_patch(FancyBboxPatch((8.85, y+.32), 1.0, .38, boxstyle="round,pad=.05",
                                 fc=c, alpha=.16, ec=c, lw=1.1))
    ax2.text(9.35, y+.51, tag, fontsize=9.5, color=c, ha="center", va="center",
             fontweight="bold")
ax2.add_patch(FancyArrowPatch((.28, .45), (.28, 4.9), arrowstyle="-|>",
                              color="#928f84", lw=2.2, mutation_scale=18))
ax2.text(.06, 2.7, "仮定への依存が強くなる →", rotation=90, fontsize=10.5,
         color="#928f84", va="center", ha="center")
ax2.set_title("それでも確定できることがある — 主張を確からしさの順に積む\n"
              "下ほど強く、上ほど仮定に依存する。下 2 段だけを結論として使う",
              fontsize=13.5, loc="left", color="#1a1a17", pad=10)
fig.savefig(FIGS/"evidence_ladder.png", dpi=180, facecolor=BG, bbox_inches="tight")
plt.close(fig)
print("  evidence_ladder.png")
