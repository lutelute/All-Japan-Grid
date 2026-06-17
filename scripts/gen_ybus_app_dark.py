#!/usr/bin/env python3
"""Generate the in-app (dark-theme) national Ybus assets for the Ybus tab.

Outputs (committed under docs/assets/analysis/):
    ybus_national.png    national block-diagonal Ybus, 2-panel
                         (region-colored spy + per-region density bars) — dark
    ybus_spy.png         national Ybus spy plot, single panel (pattern only) — dark
    ybus_per_region.png  2x5 gallery of per-region spy plots — dark

All built from build_ybus_sparsity (same lightweight GeoJSON method as the
per-region "地域別 Ybus" viewer) + scipy block_diag, so the national modes stay
consistent with the per-region mode. Palette matches #ybus-panel
(背景 #0f1419 / プロット面 #0c1014 / アクセント #5dade2). This replaces the old
white ybus_national/ybus_spy/ybus_per_region PNGs that clashed with the dark UI.

Note: block-diagonal by construction (intra-region connectivity). Inter-region
連系線 は本図には含めない(各地域ブロックの構造を見るための図)。

Usage:
    PYTHONPATH=. python scripts/gen_ybus_app_dark.py
"""
from __future__ import annotations

import os
import platform
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import scipy.sparse as spsp

from scripts.gen_ybus_white import build_ybus_sparsity

if platform.system() == "Darwin":
    plt.rcParams["font.family"] = ["Hiragino Sans", "Apple SD Gothic Neo",
                                   "sans-serif"]
else:
    try:
        import japanize_matplotlib  # noqa
    except ImportError:
        pass

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "assets",
                       "analysis")

REGIONS = [
    ("hokkaido", "北海道"), ("tohoku", "東北"), ("tokyo", "東京"),
    ("chubu", "中部"), ("hokuriku", "北陸"), ("kansai", "関西"),
    ("chugoku", "中国"), ("shikoku", "四国"), ("kyushu", "九州"),
    ("okinawa", "沖縄"),
]
# 地域色: 暗背景で映える高彩度パレット
REGION_COLORS = [
    "#ff6b6b", "#ffa94d", "#ffd43b", "#69db7c", "#38d9a9",
    "#4dabf7", "#9775fa", "#f783ac", "#adb5bd", "#d4a373",
]

# ダークパレット (#ybus-panel に整合)
DK_FIG, DK_AX = "#0f1419", "#0c1014"
DK_DOT, DK_DIAG = "#5dade2", "#f5b041"
DK_TITLE, DK_SUB = "#e6e6e6", "#9fb3c8"
DK_GRID, DK_SPINE = "#1e2b38", "#2c3e50"


def _style_dark(ax):
    ax.set_facecolor(DK_AX)
    ax.tick_params(colors=DK_SUB, labelsize=7)
    for sp_ in ax.spines.values():
        sp_.set_edgecolor(DK_SPINE)


def build_national():
    """Per-region Ybus via build_ybus_sparsity.

    Returns (blocks, labels, sizes, edges). `edges[i]` は build_ybus_sparsity
    が返すエッジ数で、「地域別 Ybus」モード(gen_ybus_interactive.py)が
    nnz / density に用いる量と同一。viewer内のモード間で数値を一致させる。
    """
    blocks, labels, sizes, edges = [], [], [], []
    for region, label in REGIONS:
        Y, nb, nnz = build_ybus_sparsity(region)
        if Y is None or nb == 0:
            print(f"  {label}: skip (no data)", flush=True)
            continue
        blocks.append(Y)
        labels.append(label)
        sizes.append(nb)
        edges.append(nnz)
        print(f"  {label}: {nb} buses, nnz(edges)={nnz}", flush=True)
    return blocks, labels, sizes, edges


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("Building per-region Ybus (block_diag)...", flush=True)
    blocks, labels, sizes, edges = build_national()
    if not blocks:
        print("No Ybus data; abort.")
        return

    Y_nat = spsp.block_diag(blocks, format="csr")
    nb_nat = Y_nat.shape[0]
    Yd = Y_nat.toarray()
    nzr, nzc = np.where(Yd > 0)
    diag = nzr == nzc
    # 「地域別」モードと同一定義: nnz=エッジ数, density=エッジ数/バス^2
    n_edges = int(sum(edges))
    density = n_edges / (nb_nat ** 2) * 100

    offsets, off = [], 0
    for nb, lbl, col in zip(sizes, labels, REGION_COLORS):
        offsets.append((off, nb, lbl, col))
        off += nb
    print(f"National: {nb_nat:,} buses, nnz(edges)={n_edges:,}, "
          f"density={density:.4f}%", flush=True)

    # ── 1) ybus_spy.png : 全国スパイ(パターンのみ・単色) ───────────────
    fig, ax = plt.subplots(figsize=(7.0, 6.9), facecolor=DK_FIG)
    _style_dark(ax)
    ax.scatter(nzc[~diag], nzr[~diag], c=DK_DOT, s=0.5, marker=",",
               alpha=0.8, linewidths=0, rasterized=True)
    ax.scatter(nzc[diag], nzr[diag], c=DK_DIAG, s=0.5, marker=",",
               alpha=0.9, linewidths=0, rasterized=True)
    for o, nb, lbl, col in offsets:
        if o > 0:
            ax.axhline(o, color=DK_SPINE, lw=0.4, zorder=4)
            ax.axvline(o, color=DK_SPINE, lw=0.4, zorder=4)
    ax.set_xlim(0, nb_nat)
    ax.set_ylim(nb_nat, 0)
    ax.set_aspect("equal")
    ax.set_title(f"全国 Ybus スパイプロット — 非零パターン\n"
                 f"({nb_nat:,} バス, nnz={n_edges:,}, 充填率={density:.4f}%)",
                 fontsize=10.5, color=DK_TITLE, pad=8)
    ax.set_xlabel("バス番号", color=DK_SUB)
    ax.set_ylabel("バス番号", color=DK_SUB)
    fig.savefig(f"{OUT_DIR}/ybus_spy.png", dpi=140, bbox_inches="tight",
                facecolor=DK_FIG)
    plt.close(fig)
    print("  -> ybus_spy.png", flush=True)

    # ── 2) ybus_national.png : 2パネル(地域色スパイ + 充填率バー) ───────
    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(13.5, 6.6), facecolor=DK_FIG,
        gridspec_kw={"width_ratios": [3, 1.25]})
    _style_dark(ax1)
    for o, nb, lbl, col in offsets:
        m = (nzr >= o) & (nzr < o + nb) & (~diag)
        if m.any():
            ax1.scatter(nzc[m], nzr[m], c=col, s=0.5, marker=",", alpha=0.75,
                        linewidths=0, rasterized=True)
    ax1.scatter(nzc[diag], nzr[diag], c=DK_DIAG, s=0.5, marker=",", alpha=0.9,
                linewidths=0, rasterized=True)
    for o, nb, lbl, col in offsets:
        if o > 0:
            ax1.axhline(o, color=DK_SPINE, lw=0.4, zorder=4)
            ax1.axvline(o, color=DK_SPINE, lw=0.4, zorder=4)
        ax1.text(o + nb / 2, o + 2, lbl, fontsize=6.5, color=col,
                 ha="center", va="top", fontweight="bold")
    ax1.set_xlim(0, nb_nat)
    ax1.set_ylim(nb_nat, 0)
    ax1.set_aspect("equal")
    ax1.set_title(f"全国統合 Ybus(地域ブロック対角)\n"
                  f"({nb_nat:,} バス, nnz={n_edges:,}, 充填率={density:.4f}%)",
                  fontsize=10, color=DK_TITLE, pad=6)
    ax1.set_xlabel("バス番号", color=DK_SUB)
    ax1.set_ylabel("バス番号", color=DK_SUB)

    _style_dark(ax2)
    # 「地域別」モードと同一定義: density = エッジ数 / バス^2
    densities = [e / (s * s) * 100 for e, s in zip(edges, sizes)]
    y_pos = np.arange(len(labels))
    ax2.barh(y_pos, densities, color=REGION_COLORS[:len(labels)], alpha=0.9,
             height=0.62)
    ax2.set_yticks(y_pos)
    ax2.set_yticklabels(labels, fontsize=8, color=DK_SUB)
    ax2.invert_yaxis()
    ax2.set_xlabel("充填率 (%)", color=DK_SUB)
    ax2.set_title("地域別 Ybus 充填率", fontsize=10, color=DK_TITLE, pad=6)
    ax2.grid(axis="x", color=DK_GRID, lw=0.5)
    ax2.set_axisbelow(True)
    for i, d in enumerate(densities):
        ax2.text(d, i, f" {d:.3f}%", va="center", fontsize=7, color=DK_SUB)

    plt.suptitle("母線アドミタンス行列 Ybus — 全国10地域ブロック対角構造",
                 fontsize=12, y=1.00, color=DK_TITLE)
    plt.tight_layout()
    fig.savefig(f"{OUT_DIR}/ybus_national.png", dpi=140, bbox_inches="tight",
                facecolor=DK_FIG)
    plt.close(fig)
    print("  -> ybus_national.png", flush=True)

    # ── 3) ybus_per_region.png : 2x5 ギャラリー ────────────────────────
    fig, axes = plt.subplots(2, 5, figsize=(17, 6.8), facecolor=DK_FIG)
    for ax, (region, label) in zip(axes.flat, REGIONS):
        _style_dark(ax)
        Y, nb, nnz = build_ybus_sparsity(region)
        if Y is None or nb == 0:
            ax.text(0.5, 0.5, f"{label}\n(データなし)", ha="center",
                    va="center", transform=ax.transAxes, color=DK_SUB,
                    fontsize=9)
            ax.set_xticks([])
            ax.set_yticks([])
            continue
        Yd_r = Y.toarray()
        r, c = np.where(Yd_r > 0)
        dg = r == c
        ax.scatter(c[~dg], r[~dg], c=DK_DOT, s=0.5, marker=",", alpha=0.8,
                   linewidths=0, rasterized=True)
        ax.scatter(c[dg], r[dg], c=DK_DIAG, s=0.5, marker=",", alpha=0.9,
                   linewidths=0, rasterized=True)
        ax.set_xlim(0, nb)
        ax.set_ylim(nb, 0)
        ax.set_aspect("equal")
        ax.set_title(f"{label} ({nb} バス)", fontsize=8.5, color=DK_TITLE,
                     pad=3)
        ax.set_xticks([])
        ax.set_yticks([])
    plt.suptitle("地域別 Ybus スパイプロット一覧 — シアン:バス間結合 / 橙:自己アドミタンス",
                 fontsize=12, y=1.01, color=DK_TITLE)
    plt.tight_layout()
    fig.savefig(f"{OUT_DIR}/ybus_per_region.png", dpi=130, bbox_inches="tight",
                facecolor=DK_FIG)
    plt.close(fig)
    print("  -> ybus_per_region.png", flush=True)


if __name__ == "__main__":
    main()
