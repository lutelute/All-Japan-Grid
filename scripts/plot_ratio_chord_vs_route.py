#!/usr/bin/env python3
"""X_モデルの長さ基準を「弦距離」から「実線形長」に変えると比がどう動くか。

モデルの潮流計算は実線形長(_path_len_km)を使っているのに、検証側は弦距離で
X_モデルを作っていた。同じ 246 本で両方を計算して並べる。

入力: docs/reports/route_len.csv（実線形長）+ compare_observed_derived_impedance.csv
出力: docs/reports/figs/ratio_chord_vs_route.png
"""
from __future__ import annotations
import os, re
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
BG, C_CHORD, C_ROUTE = "#faf8f1", "#b3812f", "#1f9e8a"
CIRC = re.compile(r"[0-9０-９]*[LＬ]$|[0-9０-９]+回線$|[0-9０-９]+号線$")
base = lambda s: CIRC.sub("", str(s)).strip()


def main():
    rl = pd.read_csv(ROOT / "docs/reports/route_len.csv")
    cm = pd.read_csv(NORM / "compare_observed_derived_impedance.csv")
    rl["k"] = list(zip(rl.utility, rl.line_name.map(base)))
    cm["k"] = list(zip(cm.utility, cm.line_name.map(base)))
    rlm = rl.drop_duplicates("k").set_index("k").route_km
    d = cm[(cm.X_pct > 0) & (cm.X_derived_pct > 0)].copy()
    d["route_km"] = d.k.map(rlm)
    d = d[d.route_km.notna() & (d.route_km > 0.5)].copy()
    d["chord"] = d.X_pct / d.X_derived_pct
    d["route"] = d.chord * (d.L_straight_km / d.route_km)

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12.6, 5.4), facecolor=BG,
                                 gridspec_kw={"width_ratios": [1.25, 1]})
    for a in (a1, a2):
        a.set_facecolor("#fffdf6")
        for s in a.spines.values():
            s.set_color("#dcd8cc")
    bins = np.logspace(np.log10(.45), np.log10(3.0), 34)
    a1.hist(d.chord, bins=bins, color=C_CHORD, alpha=.6, label=f"弦距離基準（従来の評価）中央値 {d.chord.median():.3f}")
    a1.hist(d.route, bins=bins, color=C_ROUTE, alpha=.6, label=f"実線形長基準（モデルの実際）中央値 {d.route.median():.3f}")
    a1.axvline(1.0, color="#52504a", ls="--", lw=1.4)
    a1.axvline(d.chord.median(), color=C_CHORD, lw=2)
    a1.axvline(d.route.median(), color=C_ROUTE, lw=2)
    a1.set_xscale("log"); a1.set_xlabel("X 公表 / X モデル", fontsize=10.5)
    a1.set_ylabel("本数", fontsize=10.5)
    a1.legend(fontsize=9.5, frameon=False, loc="upper right")
    a1.grid(axis="y", alpha=.22, color="#dcd8cc")
    a1.set_title(f"長さの取り方だけで比が動く（n={len(d)}）\n"
                 "モデルは実線形長で潮流を解いているのに、検証は弦距離で比べていた",
                 fontsize=12, loc="left", color="#1a1a17", pad=10)

    g = d.groupby("voltage_kv").agg(n=("route", "size"), chord=("chord", "median"),
                                    route=("route", "median"))
    g = g[g.n >= 5]
    y = np.arange(len(g))
    a2.barh(y - .2, g.chord, height=.38, color=C_CHORD, label="弦距離基準")
    a2.barh(y + .2, g.route, height=.38, color=C_ROUTE, label="実線形長基準")
    a2.axvline(1.0, color="#52504a", ls="--", lw=1.4)
    a2.set_yticks(y); a2.set_yticklabels([f"{int(v)} kV (n={int(n)})"
                                          for v, n in zip(g.index, g.n)], fontsize=9.5)
    a2.set_xlabel("比の中央値", fontsize=10.5)
    a2.legend(fontsize=9.5, frameon=False, loc="lower right")
    a2.grid(axis="x", alpha=.22, color="#dcd8cc")
    a2.set_title("電圧階級別 — 軒並み 1 に寄る", fontsize=12, loc="left",
                 color="#1a1a17", pad=10)
    fig.tight_layout()
    out = FIGS / "ratio_chord_vs_route.png"
    fig.savefig(out, dpi=180, facecolor=BG); plt.close(fig)
    print(f"  {out.name}  n={len(d)} 弦={d.chord.median():.3f} 実線形={d.route.median():.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
