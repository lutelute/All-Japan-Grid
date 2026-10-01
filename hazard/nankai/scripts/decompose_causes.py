#!/usr/bin/env python3
"""物理停電の原因分解(系統崩壊/変電所揺れ/変電所津波/上流孤立)を五地域・時点ごとに需要家数で出す。

    PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/decompose_causes.py --samples 30 --out <run_dir>
"""
from __future__ import annotations
import argparse, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from nankai.grid import GridCase
from nankai.montecarlo import Simulator
from nankai.hazard_field import default_field, GMPEField
from nankai.aggregate import bus_prefecture, naikakufu_region_of, customers_per_mw
from nankai import maps

CAUSES = ["blackout", "site_tsunami", "site_shaking", "isolated"]
LABEL = {"blackout": "系統崩壊(需給)", "site_tsunami": "変電所 津波", "site_shaking": "変電所 揺れ", "isolated": "上流孤立(線路/上位変電所)"}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--samples", type=int, default=30); ap.add_argument("--out", required=True)
    ap.add_argument("--field", default="auto"); ap.add_argument("--islands", nargs="*", default=["west", "east"]); a = ap.parse_args()
    ts = [0, 0.5, 1, 2, 4, 7, 14, 30, 60, 90]
    acc = {(t, c): 0.0 for t in ts for c in CAUSES}; tot_cust = 0.0
    for isl in a.islands:
        case = GridCase.load(isl); field = GMPEField() if a.field == "gmpe" else default_field(True)
        sim = Simulator(case, field=field)
        reg = naikakufu_region_of(bus_prefecture(case)); five = np.isin(reg, ["tokai", "kinki", "sanyo", "shikoku", "kyushu"])
        cpm = customers_per_mw(case.bus.groupby("zone").pd_mw.sum().to_dict()); cust = case.bus.pd_mw.to_numpy() * case.bus.zone.map(cpm).fillna(0).to_numpy()
        tot_cust += float(cust[five].sum()); rng = np.random.default_rng(11)
        for s in range(a.samples):
            d = sim.damage(rng); d.blackout_until = sim._blackout(d, rng)
            for t in ts:
                site_ok = ~(d.done_site > t); bus_alive = site_ok[sim.bus_site]; br_alive = ~(d.done_line > t); gen_ok = ~(d.done_gen > t)
                r = sim.cm.evaluate(bus_alive, br_alive, sim._gen_cap(t, gen_ok), run_pf=False)
                sc = d.site_cause[sim.bus_site]
                cause = np.full(case.n_bus, "", dtype=object)
                cause[~r.connected] = "isolated"
                cause[~bus_alive & (sc == 1)] = "site_shaking"; cause[~bus_alive & (sc == 2)] = "site_tsunami"
                cause[d.blackout_until > t] = "blackout"
                for c in CAUSES:
                    acc[(t, c)] += float(cust[(cause == c) & five].sum()) / a.samples
    rows = [{"t_days": t, **{c: acc[(t, c)] for c in CAUSES}, "total": sum(acc[(t, c)] for c in CAUSES)} for t in ts]
    df = pd.DataFrame(rows); df.to_csv(os.path.join(a.out, "cause_decomposition.csv"), index=False)
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=120)
    x = np.arange(len(ts)); bottom = np.zeros(len(ts))
    for c, col in zip(CAUSES, ["#4c72b0", "#0aa3c2", "#dd8452", "#8172b2"]):
        v = df[c].to_numpy() / 1e4; ax.bar(x, v, bottom=bottom, color=col, label=LABEL[c]); bottom += v
    ax.set_xticks(x); ax.set_xticklabels([("直後" if t == 0 else (f"{t*24:g}h" if t < 1 else f"{t:g}日")) for t in ts])
    ax.set_ylabel("停電軒数 [万軒](五地域・物理停電)"); ax.legend(fontsize=8); ax.grid(axis="y", alpha=0.3)
    ax.set_title(f"物理停電の原因分解(五地域 需要家 {tot_cust/1e4:,.0f}万・N={a.samples}・{'GMPE' if a.field=='gmpe' else 'J-SHIS'}場)", fontsize=10)
    fig.tight_layout(); fig.savefig(os.path.join(a.out, "cause_decomposition.png")); plt.close(fig)
    print(df.round(0).to_string())


if __name__ == "__main__":
    main()
