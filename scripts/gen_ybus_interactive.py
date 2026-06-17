#!/usr/bin/env python3
"""Generate per-region Ybus sparsity PNGs + a stats JSON for interactive viewing.

Output (committed under docs/assets/analysis/ybus/):
    docs/assets/analysis/ybus/<region>.png   per-region spy plot (white bg)
    docs/assets/analysis/ybus/stats.json     {region: {n_buses, n_lines, nnz,
                                              density_pct, degree_max,
                                              degree_avg}}

Reuses build_ybus_sparsity from gen_ybus_white.py.

Usage:
    PYTHONPATH=. python scripts/gen_ybus_interactive.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from scripts.gen_ybus_white import build_ybus_sparsity

REGIONS = [
    ("hokkaido", "北海道"),
    ("tohoku", "東北"),
    ("tokyo", "東京"),
    ("chubu", "中部"),
    ("hokuriku", "北陸"),
    ("kansai", "関西"),
    ("chugoku", "中国"),
    ("shikoku", "四国"),
    ("kyushu", "九州"),
    ("okinawa", "沖縄"),
]

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "assets",
                      "analysis", "ybus")

# ── ダークパレット (Ybusタブ #ybus-panel の配色に整合) ──────────────
#   背景 #0f1419 / プロット面 #0c1014 / アクセント #5dade2 (cyan) /
#   見出し #e6e6e6 / 補助文字 #9fb3c8 / 枠 #2c3e50。白PNGが暗UIから
#   浮く問題を解消し「貼り付けただけ」感を払拭する。
DK_FIG = "#0f1419"
DK_AX = "#0c1014"
DK_DOT = "#5dade2"
DK_DIAG = "#f5b041"   # 対角(自己アドミタンス)を暖色で識別しやすく
DK_TITLE = "#e6e6e6"
DK_SUB = "#9fb3c8"
DK_GRID = "#1e2b38"
DK_SPINE = "#2c3e50"


def render_region(region: str, label: str):
    """Build Ybus spy plot for one region; return stats dict."""
    Y, nb, nnz = build_ybus_sparsity(region)
    if Y is None or nb == 0:
        return None

    Y_dense = Y.toarray()
    nzr, nzc = np.where(Y_dense > 0)
    # 対角(自己アドミタンス)と非対角(バス間結合)を色分けして可読性を上げる
    diag = nzr == nzc
    off = ~diag

    fig, ax = plt.subplots(figsize=(6.4, 6.4), facecolor=DK_FIG)
    ax.set_facecolor(DK_AX)
    ax.scatter(nzc[off], nzr[off], c=DK_DOT, s=0.8, marker=",",
               alpha=0.85, linewidths=0, rasterized=True, label="非対角(結合)")
    ax.scatter(nzc[diag], nzr[diag], c=DK_DIAG, s=0.8, marker=",",
               alpha=0.9, linewidths=0, rasterized=True, label="対角(自己)")
    ax.set_xlim(0, nb)
    ax.set_ylim(nb, 0)
    ax.set_aspect("equal")
    density = nnz / (nb * nb) * 100 if nb > 0 else 0.0
    ax.set_title(f"{label}  Ybus  ({nb} buses, nnz={nnz:,}, "
                 f"density={density:.3f}%)",
                 fontsize=11, pad=8, color=DK_TITLE)
    ax.set_xlabel("bus index", color=DK_SUB)
    ax.set_ylabel("bus index", color=DK_SUB)
    ax.tick_params(colors=DK_SUB, labelsize=8)
    ax.grid(True, color=DK_GRID, lw=0.4)
    for spine in ax.spines.values():
        spine.set_edgecolor(DK_SPINE)
    leg = ax.legend(loc="upper right", fontsize=7, framealpha=0.0,
                    labelcolor=DK_SUB, markerscale=6, handletextpad=0.3)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_png = os.path.join(OUT_DIR, f"{region}.png")
    fig.savefig(out_png, dpi=130, bbox_inches="tight", facecolor=DK_FIG)
    plt.close(fig)

    # degree (バスごとの非ゼロ非対角要素数)
    deg = np.asarray((Y_dense > 0).sum(axis=1)).flatten() - 1
    deg = deg[deg >= 0]

    return {
        "name_ja": label,
        "n_buses": int(nb),
        "nnz": int(nnz),
        "n_offdiag": int(2 * nnz),
        "density_pct": round(density, 4),
        "degree_max": int(deg.max()) if len(deg) else 0,
        "degree_avg": round(float(deg.mean()), 2) if len(deg) else 0.0,
    }


def main():
    stats = {}
    for region, label in REGIONS:
        print(f"  rendering {region} ({label}) ...", flush=True)
        s = render_region(region, label)
        if s is not None:
            stats[region] = s
            print(f"    -> {s['n_buses']} buses, nnz={s['nnz']}, "
                  f"density={s['density_pct']}%", flush=True)

    out_json = os.path.join(OUT_DIR, "stats.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"\nWrote stats.json with {len(stats)} regions -> {out_json}",
          flush=True)


if __name__ == "__main__":
    main()
