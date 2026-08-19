#!/usr/bin/env python3
"""線ごとに逆算した「実効導体本数」を、抵抗基準 × リアクタンス基準の散布図で見る。

抵抗とリアクタンスは別々の物理法則で導体本数に効くので、それぞれから独立に
本数を逆算できる。**両者が一致するなら点は対角線 y=x に乗る。**
設定ファイルの仮定（★）が点群のどこにあるかも同時に見える。

逆算はいずれも **理論値との絶対比較**（設定値を基準にしない）:
  抵抗       n = r_単導体理論 / r_実測      （抵抗は本数に反比例）
  リアクタンス x = k·ln(D/GMR(n)) を n について解く（対数なので飽和する）

出力: docs/reports/figs/effective_bundle_scatter.png
"""
from __future__ import annotations
import math, os, re
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
NORM = Path(os.environ.get("AGJ_DISCLOSURE_NORM",
                           ROOT / "data/external/system_disclosure/normalized"))
FIGS = ROOT / "docs/reports/figs"
for _f in ("Hiragino Sans", "Hiragino Kaku Gothic ProN", "YuGothic"):
    plt.rcParams["font.family"] = _f
    break
plt.rcParams["axes.unicode_minus"] = False
BG = "#faf8f1"
K50 = 2*math.pi*50*2e-7*1000
CIRC = re.compile(r"[0-9０-９]*[LＬ]$|[0-9０-９]+回線$|[0-9０-９]+号線$")
base = lambda s: CIRC.sub("", str(s)).strip()
# 電圧: (素導体断面積 mm², 設定ファイルの仮定本数, 等価線間距離 m, 色)
SPEC = {154: (330, 1, 5.0, "#3a6ea5"), 187: (330, 2, 6.0, "#cf4f5f"),
        220: (410, 2, 6.5, "#b3812f"), 275: (410, 2, 7.5, "#1f9e8a"),
        500: (810, 4, 11.0, "#6f54c4")}


def gmr1(a): return 0.78*math.sqrt(a/math.pi)


def gmr_of(g1, n, s=400.0):
    g2 = math.sqrt(g1*s); g4 = 1.09*(g1*s**3)**0.25
    if n <= 1: return g1
    if n <= 2: return g1 + (g2-g1)*(n-1)
    return g2 + (g4-g2)*(n-2)/2


def n_from_x(x_obs, area, D_m):
    g1 = gmr1(area); lo, hi = 0.8, 4.5
    for _ in range(80):
        m = (lo+hi)/2
        lo, hi = (m, hi) if K50*math.log(D_m*1000/gmr_of(g1, m)) > x_obs else (lo, m)
    return (lo+hi)/2


def main():
    rl = pd.read_csv(ROOT/"docs/reports/route_len.csv")
    cm = pd.read_csv(NORM/"compare_observed_derived_impedance.csv")
    rl["k"] = list(zip(rl.utility, rl.line_name.map(base)))
    cm["k"] = list(zip(cm.utility, cm.line_name.map(base)))
    rlm = rl.drop_duplicates("k").set_index("k").route_km
    d = cm[(cm.X_pct > 0) & (cm.X_derived_pct > 0)].copy()
    d["route_km"] = d.k.map(rlm)
    d = d[d.route_km.notna() & (d.route_km > 0.5)].copy()
    d["x_eff"] = d.X_ohm_obs/d.route_km
    d["r_eff"] = d.R_ohm_obs/d.route_km
    d = d[~d.line_name.astype(str).str.contains("地中|ケーブル|洞道")]
    d = d[(d.x_eff > 0.15) & (d.x_eff < 0.9) & (d.r_eff > 0)]

    fig, ax = plt.subplots(figsize=(9.6, 8.6), facecolor=BG)
    ax.set_facecolor("#fffdf6")
    lim = (0.7, 4.6)
    ax.plot(lim, lim, color="#52504a", ls="--", lw=1.6, zorder=2,
            label="対角線 y=x（2 つの推定が一致する線）")
    for n_ in (1, 2, 4):
        ax.axvline(n_, color="#dcd8cc", lw=1.0, zorder=1)
        ax.axhline(n_, color="#dcd8cc", lw=1.0, zorder=1)
        ax.text(n_, lim[0]+.05, f"{n_}本", fontsize=9, color="#928f84", ha="center")
        ax.text(lim[0]+.03, n_, f"{n_}本", fontsize=9, color="#928f84", va="center")
    for kv, (area, n_as, D_m, col) in SPEC.items():
        g = d[d.voltage_kv == kv]
        if len(g) < 4:
            continue
        r_single = 1000.0/(33.0*area)
        nr = np.clip(r_single/g.r_eff.values, .6, 4.6)
        nx = np.array([n_from_x(v, area, D_m) for v in g.x_eff.values])
        ax.scatter(nr, nx, s=46, color=col, alpha=.62, edgecolor="white", lw=.6,
                   zorder=4, label=f"{kv} kV（n={len(g)}・仮定 {n_as} 本）")
        ax.scatter([np.median(nr)], [np.median(nx)], marker="D", s=150, color=col,
                   edgecolor="#1a1a17", lw=1.6, zorder=6)
        ax.scatter([n_as], [n_as], marker="*", s=340, color=col, edgecolor="#1a1a17",
                   lw=1.2, zorder=7)
        ax.annotate("", xy=(np.median(nr), np.median(nx)), xytext=(n_as, n_as),
                    arrowprops=dict(arrowstyle="->", color=col, lw=1.5, alpha=.75))
    ax.set_xlim(lim); ax.set_ylim(lim); ax.set_aspect("equal")
    ax.set_xlabel("抵抗から逆算した実効本数　（抵抗は本数に反比例）", fontsize=11.5)
    ax.set_ylabel("リアクタンスから逆算した実効本数　（対数なので飽和する）", fontsize=11.5)
    ax.grid(alpha=.18, color="#dcd8cc")
    for s in ax.spines.values():
        s.set_color("#dcd8cc")
    ax.legend(fontsize=9.5, frameon=True, facecolor="white", edgecolor="#dcd8cc",
              loc="upper left")
    ax.set_title("2 つの独立な物理量から逆算した「1 相あたりの電線の本数」\n"
                 "★＝設定ファイルの仮定　◆＝実測の中央値　矢印＝仮定から実測へのずれ",
                 fontsize=13, loc="left", color="#1a1a17", pad=12)
    ax.text(.985, .02,
            "対角線より上 = リアクタンスの方が本数を多く見積もる\n"
            "対角線より下 = 抵抗の方が本数を多く見積もる",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=9.5,
            color="#52504a", bbox=dict(boxstyle="round,pad=.35", fc="white",
                                       ec="#dcd8cc"))
    fig.tight_layout()
    out = FIGS/"effective_bundle_scatter.png"
    fig.savefig(out, dpi=180, facecolor=BG); plt.close(fig)
    print(f"  {out.name}")
    for kv, (area, n_as, D_m, _) in SPEC.items():
        g = d[d.voltage_kv == kv]
        if len(g) < 4: continue
        r_single = 1000.0/(33.0*area)
        nr = np.median(np.clip(r_single/g.r_eff.values, .6, 4.6))
        nx = np.median([n_from_x(v, area, D_m) for v in g.x_eff.values])
        print(f"    {kv:>3}kV n={len(g):>2}  仮定 {n_as} 本 → 抵抗 {nr:.2f} / リアクタンス {nx:.2f} 本")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
