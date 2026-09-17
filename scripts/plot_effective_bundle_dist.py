#!/usr/bin/env python3
"""線 1 本ごとに「実効的な導体本数」を逆算し、その分布を見る。

中央値だけでは「約 1.3 本」という点推定しか得られない。線ごとに逆算して
**分布**を描けば、1 本と 2 本が混在しているのか（二峰）、
それとも全線が中間的な構成なのか（単峰）を区別できる。

n の逆算:
  抵抗から      r_i / r_single = 1/n          → n = r_single / r_i
  リアクタンスから x_i = k·ln(D/GMR(n))        → n を数値的に解く

出力: docs/reports/figs/effective_bundle_dist.png
"""
from __future__ import annotations
import math, os, re
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
NORM = Path(os.environ.get("AGJ_DISCLOSURE_NORM",
                           ROOT / "data/external/system_disclosure/normalized"))
FIGS = ROOT / "docs/reports/figs"
for _f in ("Hiragino Sans", "Hiragino Kaku Gothic ProN", "YuGothic"):
    plt.rcParams["font.family"] = _f
    break
plt.rcParams["axes.unicode_minus"] = False
BG, C_R, C_X = "#faf8f1", "#cf4f5f", "#3a6ea5"
K50 = 2*math.pi*50*2e-7*1000
CIRC = re.compile(r"[0-9０-９]*[LＬ]$|[0-9０-９]+回線$|[0-9０-９]+号線$")
base = lambda s: CIRC.sub("", str(s)).strip()
# 各電圧階級の想定: (素導体断面積 mm², 設定ファイルの仮定本数, 等価線間距離 m)
SPEC = {154: (330, 1, 5.0), 187: (330, 2, 6.0), 220: (410, 2, 6.5),
        275: (410, 2, 7.5), 500: (810, 4, 11.0)}


def gmr1(area):
    return 0.78*math.sqrt(area/math.pi)


def gmr_of(g1, n, s=400.0):
    """実効本数 n（連続値）に対する GMR。1→2→4 を実測点で補間する。"""
    g2 = math.sqrt(g1*s); g4 = 1.09*(g1*s**3)**0.25
    if n <= 1: return g1
    if n <= 2: return g1 + (g2-g1)*(n-1)
    return g2 + (g4-g2)*(n-2)/2


def n_from_x(x_obs, area, D_m):
    g1 = gmr1(area)
    lo, hi = 1.0, 4.0
    for _ in range(80):
        m = (lo+hi)/2
        xv = K50*math.log(D_m*1000/gmr_of(g1, m))
        lo, hi = (m, hi) if xv > x_obs else (lo, m)
    return (lo+hi)/2


def main():
    rl = pd.read_csv(ROOT/"docs/reports/route_len.csv")
    cm = pd.read_csv(NORM/"compare_observed_derived_impedance.csv")
    lt = yaml.safe_load((ROOT/"config/line_types.yaml").read_text(encoding="utf-8"))
    rl["k"] = list(zip(rl.utility, rl.line_name.map(base)))
    cm["k"] = list(zip(cm.utility, cm.line_name.map(base)))
    rlm = rl.drop_duplicates("k").set_index("k").route_km
    d = cm[(cm.X_pct > 0) & (cm.X_derived_pct > 0)].copy()
    d["route_km"] = d.k.map(rlm)
    d = d[d.route_km.notna() & (d.route_km > 0.5)].copy()
    d["x_eff"] = d.X_ohm_obs/d.route_km
    d["r_eff"] = d.R_ohm_obs/d.route_km
    d = d[~d.line_name.astype(str).str.contains("地中|ケーブル|洞道")]
    d = d[(d.x_eff > 0.15) & (d.x_eff < 0.9)]

    kvs = [kv for kv in (187, 154, 500) if kv in SPEC]
    fig, axes = plt.subplots(1, len(kvs), figsize=(4.7*len(kvs), 5.4), facecolor=BG)
    if len(kvs) == 1: axes = [axes]
    for ax, kv in zip(axes, kvs):
        area, n_assumed, D_m = SPEC[kv]
        g = d[d.voltage_kv == kv]
        # ACSR の単導体 1km あたり抵抗（アルミ導電率 35 m/Ω·mm² 相当・50℃補正込みの概算）
        r_single = 1000.0/(33.0*area)
        nr = (r_single/g.r_eff).clip(0.5, 4.5)
        nx = g.x_eff.map(lambda v: n_from_x(v, area, D_m))
        ax.set_facecolor("#fffdf6")
        bins = np.arange(0.75, 4.3, 0.25)
        ax.hist(nx, bins=bins, color=C_X, alpha=.55, label=f"リアクタンスから（中央値 {np.median(nx):.2f}）")
        ax.hist(nr, bins=bins, color=C_R, alpha=.55, label=f"抵抗から（中央値 {np.median(nr):.2f}）")
        for n_, lab, c in ((1, "単導体", "#52504a"), (2, "2 導体", "#52504a"), (4, "4 導体", "#52504a")):
            if n_ <= 4.2:
                ax.axvline(n_, color=c, ls="--", lw=1.2, alpha=.7)
                ax.text(n_, ax.get_ylim()[1]*.97, lab, rotation=90, fontsize=8.5,
                        color=c, va="top", ha="right")
        ax.axvline(n_assumed, color="#b3812f", lw=2.4, alpha=.9)
        ax.text(n_assumed, ax.get_ylim()[1]*.55, f" 設定の仮定\n {n_assumed} 本",
                fontsize=9.5, color="#b3812f", fontweight="bold")
        ax.set_xlim(0.75, 4.3)
        ax.set_xlabel("1 相あたりの実効的な電線の本数", fontsize=10.5)
        ax.set_ylabel("線の本数", fontsize=10.5)
        ax.legend(fontsize=9, frameon=False, loc="upper right")
        ax.grid(axis="y", alpha=.22, color="#dcd8cc")
        for s in ax.spines.values():
            s.set_color("#dcd8cc")
        ax.set_title(f"{kv} kV（n={len(g)}）", fontsize=12.5, loc="left",
                     color="#1a1a17", pad=8)
        print(f"  {kv}kV n={len(g)}: 抵抗から中央値 {np.median(nr):.2f} / "
              f"リアクタンスから {np.median(nx):.2f} / 仮定 {n_assumed}")
    fig.suptitle("線 1 本ごとに「実効的な電線の本数」を逆算した分布 — 設定の仮定はどこにあるか",
                 fontsize=13, x=.02, ha="left", y=.99, color="#1a1a17")
    fig.tight_layout(rect=[0, 0, 1, .95])
    out = FIGS/"effective_bundle_dist.png"
    fig.savefig(out, dpi=180, facecolor=BG); plt.close(fig)
    print(f"  {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
