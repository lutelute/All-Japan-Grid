#!/usr/bin/env python3
"""N-1 single-line outage contingency screening per region.

For each region's snapped network with reconnect (the AC-converging build), trip
each backbone line one at a time, re-solve AC, and report the worst contingencies
by post-outage max line loading. Skips kansai (documented AC non-convergence).

Outputs:
    output/n1/<region>_n1.csv   per-region table (line_name, vmax, vmin, max_loading_pct, delta)
    output/n1/n1_summary.csv    one-row-per-region summary (base / worst / top contingency)
    output/n1/n1_worst_top.png  bar chart of the worst Top-1 contingency per region

Usage:
    PYTHONPATH=. python scripts/run_n1_contingency.py [--regions tokyo chubu ...]
                                                       [--voltage-min-kv 220]
                                                       [--top 20]
"""
from __future__ import annotations

import argparse
import copy
import csv
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandapower as pp

from scripts.export_powerflow_pages import build_and_solve
from src.powerflow.load_estimator import load_demand_config

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output", "n1")
SKIP_AC = {"kansai"}  # documented sub-network limit (docs/WEST_AC_ANALYSIS.md)
DEFAULT_REGIONS = [
    "hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
    "chugoku", "shikoku", "kyushu", "okinawa",
]


def solve_ac(net) -> bool:
    try:
        pp.runpp(net, algorithm="nr", init="dc", max_iteration=100,
                 tolerance_mva=1e-1, numba=True)
        return bool(getattr(net, "converged", False))
    except Exception:
        return False


def collect_metrics(net):
    vm = net.res_bus["vm_pu"].dropna()
    ml = net.res_line["loading_percent"].dropna()
    return {
        "vmin": float(vm.min()),
        "vmax": float(vm.max()),
        "max_loading_pct": float(ml.max()) if len(ml) else 0.0,
        "n_overload": int((ml > 100).sum()) if len(ml) else 0,
    }


def candidate_lines(net, v_min_kv: float):
    """Backbone lines: both ends >= v_min_kv, in service, not synthetic recon."""
    in_serv = net.line["in_service"]
    name = net.line["name"].astype(str)
    fb_kv = net.bus.loc[net.line["from_bus"], "vn_kv"].to_numpy()
    tb_kv = net.bus.loc[net.line["to_bus"], "vn_kv"].to_numpy()
    backbone = (fb_kv >= v_min_kv) & (tb_kv >= v_min_kv)
    real = ~name.str.startswith("recon_line").to_numpy()
    mask = in_serv.to_numpy() & backbone & real
    return list(net.line.index[mask])


def run_region(region: str, v_min_kv: float, top_n: int, demand_cfg):
    print(f"\n=== {region} ===", flush=True)
    result = build_and_solve(region, demand_cfg, topology="snapped",
                             reconnect=True, reactive=0.6)
    if result is None:
        print(f"  build_and_solve returned None for {region} -> skip", flush=True)
        return None
    # build_and_solve returns (net_dc, dc_result, net_ac, ac_result, build_info, snap_geom).
    # Use the AC-solved net as base (already converged in regen).
    _, _, net_ac, ac_result, _, _ = result
    if net_ac is None or not ac_result.get("converged"):
        print(f"  base AC=FAIL -> skip {region}", flush=True)
        return None
    net = net_ac
    base_m = collect_metrics(net)
    print(f"  base: vm=[{base_m['vmin']:.3f},{base_m['vmax']:.3f}] "
          f"max_load={base_m['max_loading_pct']:.1f}% overloads={base_m['n_overload']}",
          flush=True)
    base = net  # alias for clarity

    cands = candidate_lines(net, v_min_kv)
    print(f"  candidate backbone lines (>={v_min_kv:.0f} kV both ends): {len(cands)}",
          flush=True)
    rows = []
    fail_count = 0
    for idx in cands:
        n2 = copy.deepcopy(net)
        n2.line.at[idx, "in_service"] = False
        if not solve_ac(n2):
            fail_count += 1
            rows.append({
                "line_idx": int(idx),
                "name": str(net.line.at[idx, "name"]),
                "voltage_kv": float(net.bus.at[net.line.at[idx, "from_bus"], "vn_kv"]),
                "ac_converged": False,
                "vmin": None, "vmax": None,
                "max_loading_pct": None, "n_overload": None,
                "delta_max_load": None,
            })
            continue
        m = collect_metrics(n2)
        rows.append({
            "line_idx": int(idx),
            "name": str(net.line.at[idx, "name"]),
            "voltage_kv": float(net.bus.at[net.line.at[idx, "from_bus"], "vn_kv"]),
            "ac_converged": True,
            "vmin": round(m["vmin"], 4),
            "vmax": round(m["vmax"], 4),
            "max_loading_pct": round(m["max_loading_pct"], 2),
            "n_overload": m["n_overload"],
            "delta_max_load": round(m["max_loading_pct"] - base_m["max_loading_pct"], 2),
        })

    # sort: AC-fail first (cascading risk), then by delta_max_load desc
    rows.sort(key=lambda r: (
        0 if not r["ac_converged"] else 1,
        -(r.get("delta_max_load") or 0.0),
    ))
    if rows:
        print(f"  results: AC-fail outages={fail_count}, top1: "
              f"{rows[0]['name']} (Δmax_load={rows[0].get('delta_max_load')})",
              flush=True)
    else:
        print(f"  results: no candidate lines at >= {v_min_kv:.0f} kV "
              f"(region lacks backbone) — skip", flush=True)
    return base_m, rows[:top_n]


def write_region_csv(region, rows):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{region}_n1.csv")
    keys = ["line_idx", "name", "voltage_kv", "ac_converged",
            "vmin", "vmax", "max_loading_pct", "n_overload", "delta_max_load"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


def write_summary_and_plot(region_results):
    os.makedirs(OUT_DIR, exist_ok=True)
    summary_path = os.path.join(OUT_DIR, "n1_summary.csv")
    with open(summary_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["region", "base_max_load", "worst_max_load",
                    "worst_delta", "worst_ac_fail", "worst_line"])
        for region, (base_m, top_rows) in region_results.items():
            if not top_rows:
                continue
            top = top_rows[0]
            w.writerow([
                region,
                round(base_m["max_loading_pct"], 2),
                top.get("max_loading_pct") if top["ac_converged"] else "AC_FAIL",
                top.get("delta_max_load") if top["ac_converged"] else "",
                "yes" if not top["ac_converged"] else "no",
                top["name"],
            ])

    # bar plot of worst Top-1 delta per region (AC-fail bars get a sentinel height)
    labels, deltas, fail_flags = [], [], []
    for region, (_, top_rows) in region_results.items():
        if not top_rows:
            continue
        labels.append(region)
        top = top_rows[0]
        if top["ac_converged"]:
            deltas.append(top["delta_max_load"] or 0.0)
            fail_flags.append(False)
        else:
            deltas.append(0.0)  # plotted separately
            fail_flags.append(True)
    if labels:
        fig, ax = plt.subplots(figsize=(10, 4.5))
        colors = ["#d35400" if f else "#2980b9" for f in fail_flags]
        ax.bar(labels, deltas, color=colors)
        ax.set_ylabel("Worst Top-1 Δmax_loading (%)\n(AC-fail outages in orange, plotted at 0)")
        ax.set_title("N-1 contingency: worst single-line outage per region")
        ax.axhline(0, color="#999", lw=0.6)
        for i, f in enumerate(fail_flags):
            if f:
                ax.text(i, 1.5, "AC FAIL", ha="center", color="#d35400",
                        fontsize=8, fontweight="bold")
        fig.tight_layout()
        fig.savefig(os.path.join(OUT_DIR, "n1_worst_top.png"), dpi=140)
        plt.close(fig)
    return summary_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--regions", nargs="*", default=DEFAULT_REGIONS)
    ap.add_argument("--voltage-min-kv", type=float, default=220.0,
                    help="Only outage lines whose both endpoints are >= this kV")
    ap.add_argument("--top", type=int, default=20,
                    help="Keep top-N per region in the CSV (sorted worst first)")
    args = ap.parse_args()

    demand_cfg = load_demand_config()
    region_results = {}
    for region in args.regions:
        if region in SKIP_AC:
            print(f"\n=== {region} skipped (documented AC non-convergence) ===",
                  flush=True)
            continue
        res = run_region(region, args.voltage_min_kv, args.top, demand_cfg)
        if res is None:
            continue
        base_m, top_rows = res
        write_region_csv(region, top_rows)
        region_results[region] = (base_m, top_rows)

    if not region_results:
        print("\nNo regions analysed", flush=True)
        return

    summary_path = write_summary_and_plot(region_results)
    print(f"\n=== done -> {summary_path} ===", flush=True)


if __name__ == "__main__":
    main()
