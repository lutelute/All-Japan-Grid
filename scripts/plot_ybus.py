#!/usr/bin/env python3
"""数値 Ybus の可視化 — dist/ybus/ の出荷物から図一式を dist/ybus/figs/ に生成.

出荷物(.npz/csv/meta.json)だけから描く(=行列を再計算しない)。決定的に再生成可能。

    PYTHONPATH=. .venv/bin/python scripts/plot_ybus.py

生成物(dist/ybus/figs/):
  ybus_spy_all.png          4島フル Ybus スパーシティ(@nameplate 変圧器を赤で重畳)
  ybus_spy_backbone.png     4島バックボーン(Kron縮約 ≥154kV)スパーシティ
  ybus_diag_hist.png        対角要素 |Y_ii| の分布(島別・自己アドミタンスの姿)
  ybus_v4_nameplate.png     v4 銘板適用の before/after(位置図+容量比較)
"""
import csv
import json
import math
import os

import numpy as np
import scipy.sparse as sp
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = "Hiragino Sans"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YB = os.path.join(ROOT, "dist", "ybus")
FIGS = os.path.join(YB, "figs")
ISLANDS = ["hokkaido", "east", "west", "okinawa"]


def load_npz(island, backbone=False):
    path = os.path.join(YB, f"{island}_backbone.npz" if backbone else f"{island}.npz")
    d = np.load(path, allow_pickle=True)
    Y = sp.csr_matrix((d["data"], d["indices"], d["indptr"]), shape=tuple(d["shape"]))
    return Y, d


def nameplate_positions(island):
    """@nameplate 変圧器枝の (from,to) ybus_index を枝表から引く。"""
    pos = []
    with open(os.path.join(YB, f"{island}_branch.csv")) as f:
        for r in csv.DictReader(f):
            if "@nameplate" in r["name"]:
                pos.append((int(r["from_ybus_index"]), int(r["to_ybus_index"]),
                            r["name"], int(r["par"])))
    return pos


def fig_spy_all(meta):
    fig, axes = plt.subplots(2, 2, figsize=(13, 13), dpi=130)
    fig.suptitle(f"数値 Ybus v{meta['ybus_version']} — 4周波数島スパーシティ"
                 f"(非同期のため別行列。全国=直和)", fontsize=14, fontweight="bold")
    for ax, isl in zip(axes.flat, ISLANDS):
        Y, _ = load_npz(isl)
        m = meta["islands"][isl]
        ax.spy(Y, markersize=0.4 if Y.shape[0] > 2000 else 1.5,
               color="#333333", rasterized=True)
        for fr, to, _nm, _par in nameplate_positions(isl):
            ax.plot([to, fr], [fr, to], "o", ms=7, mfc="none", mec="#d62728", mew=1.6)
        npl = m["trafo_nameplate"]["n_applied"]
        ax.set_title(f"{isl}  {m['n_bus']}バス nnz={m['nnz']:,} "
                     f"密度={m['density']:.2e}\n"
                     f"銘板変圧器={npl}(赤丸)  指紋={m['fingerprint']}", fontsize=10)
        ax.tick_params(labelsize=8)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out = os.path.join(FIGS, "ybus_spy_all.png")
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def fig_spy_backbone(meta):
    fig, axes = plt.subplots(2, 2, figsize=(13, 13), dpi=130)
    fig.suptitle(f"バックボーン(Kron縮約 154kV以上 / 沖縄132kV) v{meta['ybus_version']} — "
                 f"下位網を回路論的に厳密に畳んだ基幹行列", fontsize=14, fontweight="bold")
    for ax, isl in zip(axes.flat, ISLANDS):
        Y, _ = load_npz(isl, backbone=True)
        m = meta["islands"][isl]["backbone"]
        ax.spy(Y, markersize=1.0 if Y.shape[0] > 500 else 2.5,
               color="#1f77b4", rasterized=True)
        ax.set_title(f"{isl}  {m['n_bus']}バス nnz={m['nnz']:,} "
                     f"fill={m['fill_density']:.3f}\n"
                     f"縮約={m['n_dropped_buses']}バス  指紋={m['fingerprint']}",
                     fontsize=10)
        ax.tick_params(labelsize=8)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out = os.path.join(FIGS, "ybus_spy_backbone.png")
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def fig_diag_hist(meta):
    fig, ax = plt.subplots(figsize=(10, 6), dpi=130)
    colors = {"hokkaido": "#1f77b4", "east": "#d62728",
              "west": "#9467bd", "okinawa": "#2ca02c"}
    for isl in ISLANDS:
        Y, _ = load_npz(isl)
        diag = np.abs(Y.diagonal())
        diag = diag[diag > 0]
        ax.hist(np.log10(diag), bins=80, histtype="step", lw=1.8,
                color=colors[isl], label=f"{isl} ({len(diag)}バス)")
    ax.set_xlabel("log10 |Y_ii|  [pu, 100MVAベース]")
    ax.set_ylabel("バス数")
    ax.set_title(f"自己アドミタンス対角 |Y_ii| の分布 v{meta['ybus_version']}"
                 f"(右裾=変圧器・短距離高圧の強結合バス)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out = os.path.join(FIGS, "ybus_diag_hist.png")
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def main():
    os.makedirs(FIGS, exist_ok=True)
    meta = json.load(open(os.path.join(YB, "meta.json")))
    outs = [fig_spy_all(meta), fig_spy_backbone(meta), fig_diag_hist(meta)]
    for o in outs:
        print("saved:", os.path.relpath(o, ROOT))


if __name__ == "__main__":
    main()
