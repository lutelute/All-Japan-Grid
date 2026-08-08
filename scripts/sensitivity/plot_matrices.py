#!/usr/bin/env python3
"""感度行列そのものを色で見る（Ybus のスパイ図に対応する可視化）。

Ybus は「非ゼロがどこにあるか」だけを見れば足りるので二値のスパイ図でよい。
PTDF / LODF は**符号を持つ密行列**なので、同じ描き方では何も見えない。
発散カラーマップ（負=青 / 0=白 / 正=赤）と symlog スケールで、
どの注入がどの枝を押し引きするかを絵にする。

行と列は**電圧階級の高い順**に並べ替える。ppc の並びのままでは雑音に見えるが、
電圧で揃えると基幹系が下位系をどう支配しているかが帯として現れる。

usage: python3 scripts/sensitivity/plot_matrices.py [--islands hokkaido ...]
出力: docs/assets/sensitivity/matrix_{island}_<date>.png
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(ROOT)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandapower as pp
from matplotlib.colors import SymLogNorm
from pandapower.pypower.idx_brch import F_BUS, T_BUS
from pandapower.pypower.idx_bus import BASE_KV
from pandapower.pypower.makeLODF import makeLODF
from pandapower.pypower.makePTDF import makePTDF

from benchmark_sensitivity import main_component_subnet, production_net
from scripts.run_full_powerflow_from_db import ISLAND_FREQ, load_demand_config

FIGS = ROOT / "docs" / "assets" / "sensitivity"
BUILT = ROOT / "docs" / "data" / "built" / "all.json"

plt.rcParams["font.family"] = ["Hiragino Sans", "DejaVu Sans"]
MAX_PX = 1400          # 表示解像度の上限（これを超える行列はブロック最大で間引く）


def block_reduce_absmax(M: np.ndarray, max_px: int = MAX_PX) -> np.ndarray:
    """符号を保ったままブロック内の絶対値最大を採る間引き。

    平均で間引くと正負が打ち消して構造が消えるため、絶対値最大の値をそのまま残す。
    """
    h, w = M.shape
    fy, fx = max(1, h // max_px), max(1, w // max_px)
    if fy == 1 and fx == 1:
        return M
    h2, w2 = h // fy, w // fx
    B = M[: h2 * fy, : w2 * fx].reshape(h2, fy, w2, fx)
    amax = np.abs(B).max(axis=(1, 3))
    amin = -np.abs(B).min(axis=(1, 3))
    pos = B.max(axis=(1, 3))
    neg = B.min(axis=(1, 3))
    return np.where(np.abs(pos) >= np.abs(neg), pos, neg)


def draw(ax, M, title, xlabel, ylabel, vmax=None):
    v = vmax or float(np.nanpercentile(np.abs(M), 99.9)) or 1.0
    im = ax.imshow(M, aspect="auto", cmap="RdBu_r", interpolation="nearest",
                   norm=SymLogNorm(linthresh=v * 1e-3, vmin=-v, vmax=v, base=10))
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.set_xlabel(xlabel, fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9)
    return im


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="*", default=None)
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True, text=True).stdout.strip()
    FIGS.mkdir(parents=True, exist_ok=True)

    d = json.load(open(BUILT))
    nodes, edges = d["nodes"], d["edges"]
    cfg = load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(nodes)

    for isl in (args.islands or list(ISLAND_FREQ.keys())):
        net = production_net(isl, nodes, edges, cfg, pref_gwh)
        sub, _ = main_component_subnet(net)
        pp.rundcpp(sub)
        ppc = sub._ppc
        ref = int(sub._pd2ppc_lookups["bus"][int(sub.ext_grid.bus.iloc[0])])
        ptdf = makePTDF(ppc["baseMVA"], ppc["bus"], ppc["branch"], slack=ref)
        lodf = makeLODF(ppc["branch"], ptdf)
        lodf = np.nan_to_num(lodf, nan=0.0, posinf=0.0, neginf=0.0)

        # 電圧階級の高い順に並べ替える（枝はその両端の高い方の電圧で代表させる）
        kv_bus = ppc["bus"][:, BASE_KV].real.astype(float)
        fb = ppc["branch"][:, F_BUS].real.astype(int)
        tb = ppc["branch"][:, T_BUS].real.astype(int)
        kv_br = np.maximum(kv_bus[fb], kv_bus[tb])
        obus = np.argsort(-kv_bus, kind="stable")
        obr = np.argsort(-kv_br, kind="stable")
        P = ptdf[np.ix_(obr, obus)]
        Lo = lodf[np.ix_(obr, obr)]

        fig, ax = plt.subplots(1, 3, figsize=(17.5, 5.6),
                               gridspec_kw={"width_ratios": [1.25, 1.25, 0.85]})
        fig.suptitle(f"感度行列の構造 — {isl}（主成分 {len(ppc['bus'])} バス × {ptdf.shape[0]} 枝・電圧階級順）",
                     fontsize=13.5, fontweight="bold", y=0.99)

        im0 = draw(ax[0], block_reduce_absmax(P), "PTDF — バス注入が枝潮流を動かす量",
                   "バス（電圧の高い順 →）", "枝（電圧の高い順 ↓）", vmax=1.0)
        fig.colorbar(im0, ax=ax[0], fraction=0.046, label="潮流の感度 [MW/MW]")

        im1 = draw(ax[1], block_reduce_absmax(Lo), "LODF — 枝の停止が他の枝を動かす量",
                   "停止する枝（電圧の高い順 →）", "影響を受ける枝（↓）", vmax=1.0)
        fig.colorbar(im1, ax=ax[1], fraction=0.046, label="転送率 [MW/MW]")

        # 3枚目: 電圧階級ごとの感度の強さ（行ノルム）
        band_edges = [500, 275, 220, 187, 154, 132, 110, 77, 66, 0]
        rows, labels = [], []
        for i, hi in enumerate(band_edges[:-1]):
            lo = band_edges[i + 1]
            m = (kv_br[obr] <= hi + 0.5) & (kv_br[obr] > lo + 0.5)
            if m.sum() >= 3:
                rows.append(float(np.abs(P[m]).max(axis=0).mean()))
                labels.append(f"{int(hi)}kV ({int(m.sum())}枝)")
        ax[2].barh(range(len(rows)), rows, color=plt.cm.RdBu_r(np.linspace(0.62, 0.95, len(rows))))
        ax[2].set_yticks(range(len(rows))); ax[2].set_yticklabels(labels, fontsize=9)
        ax[2].invert_yaxis()
        ax[2].set_xlabel("その階級の枝が受ける感度の平均（|PTDF| の列最大の平均）", fontsize=8.5)
        ax[2].set_title("電圧階級別の感度の強さ", fontsize=11, fontweight="bold")
        ax[2].grid(axis="x", alpha=0.3)

        fig.tight_layout(rect=(0, 0, 1, 0.95))
        out = FIGS / f"matrix_{isl}_{date}.png"
        fig.savefig(out, dpi=125)
        plt.close(fig)
        print(f"→ {out.relative_to(ROOT)}  (PTDF {ptdf.shape} / LODF {lodf.shape})")


if __name__ == "__main__":
    main()
