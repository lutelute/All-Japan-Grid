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


def render_region(region: str, label: str):
    """Build Ybus spy plot for one region; return stats dict."""
    Y, nb, nnz = build_ybus_sparsity(region)
    if Y is None or nb == 0:
        return None

    Y_dense = Y.toarray()
    nzr, nzc = np.where(Y_dense > 0)

    fig, ax = plt.subplots(figsize=(6.4, 6.4), facecolor="white")
    ax.set_facecolor("white")
    ax.scatter(nzc, nzr, c="#1f77b4", s=0.7, marker=",",
               alpha=0.7, linewidths=0, rasterized=True)
    ax.set_xlim(0, nb)
    ax.set_ylim(nb, 0)
    ax.set_aspect("equal")
    density = nnz / (nb * nb) * 100 if nb > 0 else 0.0
    ax.set_title(f"{label}  Ybus  ({nb} buses, nnz={nnz:,}, "
                 f"density={density:.3f}%)",
                 fontsize=11, pad=8)
    ax.set_xlabel("bus index")
    ax.set_ylabel("bus index")
    ax.grid(True, color="#dddddd", lw=0.4)
    for spine in ax.spines.values():
        spine.set_edgecolor("#999")

    os.makedirs(OUT_DIR, exist_ok=True)
    out_png = os.path.join(OUT_DIR, f"{region}.png")
    fig.savefig(out_png, dpi=130, bbox_inches="tight", facecolor="white")
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
