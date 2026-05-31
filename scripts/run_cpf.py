#!/usr/bin/env python3
"""Continuation Power Flow (CPF) — voltage-stability / PV-curve analysis.

This is the "beyond a generic demo" analysis: instead of asking only "does AC
converge at the nominal load?", we trace the system's full *PV curve* (nose
curve) by continuation: scale every load by a factor lambda and solve AC at
each step, warm-started from the previous converged operating point. As lambda
rises the minimum bus voltage falls; at the *nose* the AC power-flow Jacobian
becomes singular and Newton-Raphson stops converging. The largest lambda for
which a solution exists is lambda_crit — the true static voltage-stability
margin of the network, a *measured property of the reconstructed system*, not
a textbook value.

For Kansai this reproduces the homotopy finding (convergence only up to
~lambda 0.48, i.e. ~11 GW of the ~23 GW peak): the 60 Hz west grid as
reconstructed from OSM has a genuine voltage-stability nose well below peak
demand, because OSM omits much of the reactive support / inner-loop 154-66 kV
meshing that the real grid relies on.

The network preparation mirrors ``export_powerflow_pages.build_and_solve``
(snapped topology -> PandapowerBuilder -> fix_zero_voltages ->
insert_transformers -> 5 km reconnect -> fix_topology(multi_slack) ->
select_slack_bus -> estimate_loads -> balance_power -> scale_line_ratings ->
reactive comp -> flat start) but stops *before* the final solve so we can drive
the load scale ourselves.

Usage::

    PYTHONPATH=. python3 scripts/run_cpf.py --region kansai
    PYTHONPATH=. python3 scripts/run_cpf.py --region tokyo hokkaido okinawa
    PYTHONPATH=. python3 scripts/run_cpf.py            # default set
"""

import argparse
import copy
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandapower as pp

from examples.build_snapped_topology import build_network_snapped
from examples.run_powerflow_all import (
    fix_zero_voltages, insert_transformers, fix_topology,
    select_slack_bus, balance_power, scale_line_ratings,
    prune_dc_infeasible,
)
from scripts.export_powerflow_pages import add_reactive_compensation
from src.converter.pandapower_builder import PandapowerBuilder
from src.powerflow.load_estimator import estimate_loads, load_demand_config
from src.reconstruction.config import ReconstructionConfig
from src.reconstruction.isolator import Isolator
from src.reconstruction.reconnector import Reconnector

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output", "cpf")

# Solver chain used at each continuation step. Warm-started (init='results')
# where possible; we fall back to a flat/DC start if the previous point's state
# is too far from the next one. Tolerance is loose because the reconstructed
# network is approximate — we are tracing the nose, not metering 1e-8 MVA.
def _solve_ac(net, warm):
    """Try to solve AC; return True if converged. warm=True uses prev results."""
    inits = (["results", "dc", "flat"] if warm else ["dc", "flat"])
    for init in inits:
        for tol in (1e-2, 1e-1, 1.0):
            try:
                pp.runpp(net, algorithm="nr", init=init,
                         max_iteration=100, tolerance_mva=tol, numba=False)
                if net.converged:
                    return True
            except Exception:
                continue
    return False


def build_cpf_net(region, reactive=0.6, snap_km=1.5, prune=True):
    """Build the prepared (but UNSOLVED) pandapower net + base load P0/Q0.

    Returns (net, p0, q0, info) where p0/q0 are numpy arrays of the nominal
    in-service load demand indexed by net.load.index order, captured BEFORE any
    scaling so lambda=1.0 reproduces the nominal operating point.

    prune: run the DC-infeasibility pruning once (as build_and_solve does)
    to drop the few extreme-angle bottleneck branches that otherwise block AC
    convergence entirely; this is a fixed network cleanup, NOT part of the
    continuation (the same pruned network is used at every lambda).
    """
    network, _ = build_network_snapped(region, snap_km=snap_km, return_geom=True)
    if not network or not network.has_elements:
        raise RuntimeError(f"no network for {region}")

    net = PandapowerBuilder().build(network).net
    fix_zero_voltages(net)
    insert_transformers(net)

    iso = Isolator().detect(net)
    Reconnector().reconnect(net, iso, ReconstructionConfig(
        mode="reconnect", max_reconnection_distance_km=5.0))

    diag = fix_topology(net, multi_slack=True)
    select_slack_bus(net)

    demand_cfg = load_demand_config()
    estimate_loads(net, region=region, demand_config=demand_cfg)
    inactive = set(net.bus.index[~net.bus["in_service"]])
    if len(net.load) > 0:
        net.load.loc[net.load["bus"].isin(inactive), "in_service"] = False
    balance_power(net, demand_cfg)
    scale_line_ratings(net)
    add_reactive_compensation(net, factor=reactive)

    if prune:
        n_pruned = prune_dc_infeasible(net, angle_threshold=30.0)
        if n_pruned > 0:
            fix_topology(net, multi_slack=True)
            select_slack_bus(net)
            scale_line_ratings(net)

    net.bus["vm_pu"] = 1.0
    if len(net.gen) > 0:
        net.gen["vm_pu"] = 1.0
    if len(net.ext_grid) > 0:
        net.ext_grid["vm_pu"] = 1.0

    # Capture nominal demand (lambda=1.0 baseline). Out-of-service loads stay 0.
    p0 = net.load["p_mw"].to_numpy(dtype=float).copy()
    q0 = net.load["q_mvar"].to_numpy(dtype=float).copy()
    p0[~net.load["in_service"].to_numpy()] = 0.0
    q0[~net.load["in_service"].to_numpy()] = 0.0

    info = {
        "region": region,
        "n_buses": int(len(net.bus)),
        "n_active_buses": int(net.bus["in_service"].sum()),
        "n_lines": int(len(net.line)),
        "n_gens": int(len(net.gen)),
        "n_components": int(diag.get("n_components", 0)),
        "nominal_load_mw": float(p0.sum()),
        "reactive": reactive,
    }
    return net, p0, q0, info


def _set_load_scale(net, p0, q0, lam):
    net.load["p_mw"] = p0 * lam
    net.load["q_mvar"] = q0 * lam


def continuation(net, p0, q0, lam_start=0.10, lam_step=0.05, lam_max=3.0,
                 refine=4, verbose=True):
    """Trace the PV curve by load continuation.

    Increase lambda from lam_start by lam_step, warm-starting AC from the last
    converged point. At the first failure, bisect the step ``refine`` times to
    pin the nose. Returns (pv_table, lam_crit).

    pv_table rows: {lambda, total_mw, vm_min, vm_mean, converged}.
    """
    pv = []
    last_good_net = None
    lam_crit = 0.0

    def _record(n, lam):
        vm_min = float(n.res_bus.loc[n.bus["in_service"], "vm_pu"].min())
        vm_mean = float(n.res_bus.loc[n.bus["in_service"], "vm_pu"].mean())
        total = float((p0 * lam).sum())
        pv.append({"lambda": round(lam, 5), "total_mw": round(total, 2),
                   "vm_min": round(vm_min, 5), "vm_mean": round(vm_mean, 5),
                   "converged": True})
        if verbose:
            print(f"    lam={lam:.4f} MW={total:9.1f} vm_min={vm_min:.4f} OK")

    # Find an anchor: a lambda that cold-starts. A lightly loaded reconstructed
    # network can fail the flat/DC start (poor initial guess) even though it is
    # perfectly stable; so we scan a spread of candidate anchors near mid-load
    # rather than assuming lam_start converges.
    anchor_candidates = [lam_start, 0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8, 1.0, 0.15]
    seen = set()
    lam = None
    for cand in anchor_candidates:
        c = round(cand, 5)
        if c in seen or c > lam_max:
            continue
        seen.add(c)
        _set_load_scale(net, p0, q0, c)
        if _solve_ac(net, warm=False):
            lam = c
            last_good_net = copy.deepcopy(net)
            lam_crit = c
            break

    if last_good_net is None:
        return pv, 0.0

    anchor_net = copy.deepcopy(last_good_net)

    # Walk DOWN from the anchor (warm start) to fill the low-load branch of the
    # PV curve. Lightly loaded points may fail the (well-known) numerical
    # difficulty of a near-no-load AC solve; we simply stop the down-walk there.
    seq = []
    walk = anchor_net
    d = lam
    while d - lam_step >= lam_start - 1e-9 and d - lam_step > 0:
        t = round(d - lam_step, 5)
        nt = copy.deepcopy(walk)
        _set_load_scale(nt, p0, q0, t)
        if _solve_ac(nt, warm=True):
            seq.append((t, nt)); walk = nt; d = t
        else:
            break
    for t, nt in sorted(seq, key=lambda x: x[0]):
        _record(nt, t)
    _record(anchor_net, lam)
    last_good_net = anchor_net

    # Coarse forward sweep with warm start (toward the nose).
    step = lam_step
    while lam + step <= lam_max:
        trial = round(lam + step, 5)
        net_try = copy.deepcopy(last_good_net)
        _set_load_scale(net_try, p0, q0, trial)
        ok = _solve_ac(net_try, warm=True)
        if ok:
            lam = trial
            lam_crit = trial
            last_good_net = net_try
            _record(net_try, trial)
        else:
            # Hit the nose between lam and trial; bisect the step to refine.
            if verbose:
                print(f"    lam={trial:.4f} FAIL -> bisecting around nose")
            lo, hi = lam, trial
            for _ in range(refine):
                mid = round(0.5 * (lo + hi), 5)
                net_mid = copy.deepcopy(last_good_net)
                _set_load_scale(net_mid, p0, q0, mid)
                if _solve_ac(net_mid, warm=True):
                    lo = mid
                    lam_crit = mid
                    last_good_net = net_mid
                    _record(net_mid, mid)
                else:
                    hi = mid
            break

    pv.sort(key=lambda r: r["lambda"])
    return pv, lam_crit


def run_region_cpf(region, reactive=0.6, lam_start=0.10, lam_step=0.05,
                   lam_max=3.0, verbose=True):
    if verbose:
        print(f"  CPF {region} (reactive={reactive})...")
    net, p0, q0, info = build_cpf_net(region, reactive=reactive)
    pv, lam_crit = continuation(net, p0, q0, lam_start=lam_start,
                                lam_step=lam_step, lam_max=lam_max,
                                verbose=verbose)
    crit_mw = float(info["nominal_load_mw"] * lam_crit)
    result = {
        **info,
        "lambda_crit": round(lam_crit, 5),
        "critical_load_mw": round(crit_mw, 2),
        "pv_curve": pv,
    }
    if verbose:
        print(f"  -> lambda_crit={lam_crit:.4f}  critical_load={crit_mw:.1f} MW "
              f"(nominal {info['nominal_load_mw']:.1f} MW)")
    return result


def plot_pv_curves(results, out_path, primary="kansai"):
    """Render vm_min vs total load (the PV / nose curve) for the analysed
    regions, highlighting ``primary`` (kansai) and marking its nose."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.family"] = ["Hiragino Sans", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(9, 6))
    colors = {"kansai": "#D32F2F", "tokyo": "#1976D2",
              "hokkaido": "#388E3C", "okinawa": "#F57C00"}
    for region, res in results.items():
        pv = res.get("pv_curve", [])
        if not pv:
            continue
        mw = [p["total_mw"] for p in pv]
        vm = [p["vm_min"] for p in pv]
        is_primary = (region == primary)
        ax.plot(mw, vm, "-o",
                color=colors.get(region, "#555"),
                lw=2.4 if is_primary else 1.4,
                ms=5 if is_primary else 3,
                alpha=1.0 if is_primary else 0.6,
                label=f"{region} (λc={res['lambda_crit']:.2f})",
                zorder=5 if is_primary else 3)
        # Mark the nose (last/critical point).
        nose_mw = res["critical_load_mw"]
        nose_vm = pv[-1]["vm_min"]
        ax.plot([nose_mw], [nose_vm], marker="*",
                ms=20 if is_primary else 12,
                color=colors.get(region, "#555"),
                markeredgecolor="k", markeredgewidth=0.8, zorder=6)
        if is_primary:
            ax.annotate(
                f"nose  λ_crit={res['lambda_crit']:.2f}\n"
                f"{nose_mw:,.0f} MW critical\n"
                f"(nominal peak ≈ {res['nominal_load_mw']:,.0f} MW)",
                xy=(nose_mw, nose_vm),
                xytext=(nose_mw * 0.55, nose_vm - 0.06),
                fontsize=10, color=colors[region],
                arrowprops=dict(arrowstyle="->", color=colors[region], lw=1.5))

    ax.set_xlabel("Total served load P  [MW]", fontsize=12)
    ax.set_ylabel("Minimum bus voltage  $V_{min}$  [pu]", fontsize=12)
    ax.set_title("Continuation Power Flow — PV (nose) curves\n"
                 "電圧安定性: 連続潮流計算による P–V 曲線（鼻先 = 静的電圧安定限界）",
                 fontsize=13, fontweight="bold")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower left", fontsize=10, title="region (critical load factor)")
    ax.axhline(0.9, color="gray", ls="--", lw=1, alpha=0.6)
    ax.text(ax.get_xlim()[1], 0.9, " 0.9 pu", va="center", ha="right",
            fontsize=8, color="gray")
    plt.tight_layout()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    plt.savefig(out_path, dpi=160, bbox_inches="tight")
    plt.close()
    print(f"  figure saved {out_path}")


def main():
    ap = argparse.ArgumentParser(description="Continuation power flow (PV curve / voltage stability).")
    ap.add_argument("--region", nargs="*", default=["kansai", "tokyo", "hokkaido"],
                    help="region(s) to analyse (default: kansai tokyo hokkaido).")
    ap.add_argument("--reactive", type=float, default=0.6)
    ap.add_argument("--lam-start", type=float, default=0.10)
    ap.add_argument("--lam-step", type=float, default=0.05)
    ap.add_argument("--lam-max", type=float, default=3.0)
    ap.add_argument("--output-dir", default=OUTPUT_DIR)
    ap.add_argument("--plot", action="store_true",
                    help="also render a P-V (nose) curve figure to --figure.")
    ap.add_argument("--figure", default=os.path.join(
        os.path.dirname(__file__), "..", "docs", "assets", "cpf_kansai_pv.png"),
        help="output path for the P-V curve figure (with --plot).")
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    results = {}
    for region in args.region:
        try:
            res = run_region_cpf(region, reactive=args.reactive,
                                 lam_start=args.lam_start, lam_step=args.lam_step,
                                 lam_max=args.lam_max)
        except Exception as exc:
            print(f"  {region}: ERROR {exc}")
            continue
        results[region] = res
        out = os.path.join(args.output_dir, f"{region}_pv.json")
        with open(out, "w") as f:
            json.dump(res, f, indent=2, ensure_ascii=False)
        print(f"  saved {out}")

    print("\nCPF summary:")
    for r, res in results.items():
        print(f"  {r:10s} lambda_crit={res['lambda_crit']:.3f} "
              f"crit_load={res['critical_load_mw']:.0f} MW / "
              f"nominal={res['nominal_load_mw']:.0f} MW  "
              f"({len(res['pv_curve'])} PV points)")

    if args.plot and results:
        primary = "kansai" if "kansai" in results else next(iter(results))
        plot_pv_curves(results, os.path.abspath(args.figure), primary=primary)


if __name__ == "__main__":
    main()
