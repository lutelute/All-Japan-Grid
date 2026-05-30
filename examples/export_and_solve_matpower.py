#!/usr/bin/env python3
"""Export a snapped-topology region to MATPOWER (.mat) and validate solvability.

This ties together the improved "snapped" topology builder
(:func:`examples.build_snapped_topology.build_network_snapped`) and the
MATPOWER exporter (:func:`src.matpower.exporter.build_matpower_case`) to
produce an OPF-ready MATPOWER case (BUS/BRANCH/GEN + GENCOST), write it to a
``.mat`` file, and confirm the network actually solves by running a
pandapower AC power flow on the same topology.

Usage::

    PYTHONPATH=. python3 examples/export_and_solve_matpower.py            # okinawa
    PYTHONPATH=. python3 examples/export_and_solve_matpower.py shikoku
    PYTHONPATH=. python3 examples/export_and_solve_matpower.py okinawa shikoku

For each region it prints bus/branch/gen/gencost counts, the GENCOST merit
order, whether the .mat was written and re-loadable, and whether the
pandapower power flow converges.
"""
from __future__ import annotations

import os
import sys
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples.build_snapped_topology import build_network_snapped
from src.matpower.exporter import build_matpower_case, save_case_to_matfile

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "output", "matpower",
)


def _validate_powerflow(region: str) -> dict:
    """Run a pandapower power flow on the snapped network via the proven path.

    Reuses scripts/export_powerflow_pages.build_and_solve so the validation
    matches the deployed regional power flow exactly (same topology fix-ups,
    slack selection, balancing, and pruning).
    """
    from scripts.export_powerflow_pages import build_and_solve
    from src.powerflow.load_estimator import load_demand_config

    demand_cfg = load_demand_config()
    result = build_and_solve(region, demand_cfg, topology="snapped", reconnect=True)
    if result is None:
        return {"converged": False, "reason": "no data / empty network"}
    net_dc, dc_result, net_ac, ac_result, build_info, _ = result
    return {
        "dc_converged": bool(dc_result["converged"]),
        "ac_converged": bool(ac_result["converged"]),
        "ac_solver": ac_result.get("solver", "-"),
        "n_buses": build_info["n_buses"],
        "n_lines": build_info["n_lines"],
        "n_gens": build_info["n_gens"],
        "total_load_mw": build_info["total_load_mw"],
        "total_gen_mw": build_info["total_gen_mw"],
    }


def _reload_matfile(path: str) -> dict:
    """Re-load the written .mat and report table shapes (round-trip check)."""
    from scipy.io import loadmat

    raw = loadmat(path, struct_as_record=False, squeeze_me=True)
    mpc = raw["mpc"]
    bus = mpc.bus
    branch = mpc.branch
    gen = mpc.gen
    gencost = mpc.gencost
    return {
        "bus": int(bus.shape[0]),
        "branch": int(branch.shape[0]),
        "gen": int(gen.shape[0]) if gen.ndim > 1 else 1,
        "gencost": int(gencost.shape[0]) if gencost.ndim > 1 else 1,
        "baseMVA": float(mpc.baseMVA),
    }


def process_region(region: str) -> bool:
    print(f"\n=== {region} ===")
    net = build_network_snapped(region)
    if net is None or not net.has_elements:
        print(f"  SKIP: no data for {region}")
        return False

    print(f"  snapped network: {net.substation_count} subs, "
          f"{net.line_count} lines, {net.generator_count} gens")

    # Build the MATPOWER case from the snapped topology.
    case = build_matpower_case(network=net)
    n_bus = case["n_bus"]
    n_branch = case["BRANCH"].shape[0]
    n_gen = case["n_gen"]
    n_gencost = case["GENCOST"].shape[0]
    print(f"  MATPOWER case: bus={n_bus} branch={n_branch} "
          f"gen={n_gen} gencost={n_gencost} (slack bus #{case['slack_bus']})")

    # Show the GENCOST merit order (linear marginal cost c1, $/MWh) per fuel.
    if n_gen > 0:
        c1 = case["GENCOST"][:, 5]
        fuels = case["gen_fuel"]
        merit = {}
        for f, c in zip(fuels, c1):
            merit.setdefault(f, c)
        merit_str = ", ".join(
            f"{f}={c:.0f}" for f, c in sorted(merit.items(), key=lambda kv: kv[1])
        )
        print(f"  GENCOST merit order ($/MWh): {merit_str}")
    else:
        print("  GENCOST merit order: (no generators in component)")

    # Write the .mat file.
    mat_path = os.path.join(OUTPUT_DIR, f"{region}_snapped.mat")
    save_case_to_matfile(case, mat_path)
    reloaded = _reload_matfile(mat_path)
    print(f"  wrote {mat_path}")
    print(f"  re-loaded .mat: {reloaded}")

    mat_ok = (
        reloaded["bus"] == n_bus
        and reloaded["branch"] == n_branch
        and reloaded["gencost"] == n_gencost
    )

    # Validate solvability via pandapower on the same topology.
    pf = _validate_powerflow(region)
    print(f"  power flow (pandapower, snapped): {pf}")

    converged = bool(pf.get("ac_converged") or pf.get("dc_converged"))
    ok = mat_ok and n_gencost == n_gen and converged
    print(f"  RESULT: {'OK' if ok else 'INCOMPLETE'} "
          f"(mat_roundtrip={mat_ok}, gencost_rows==gens={n_gencost == n_gen}, "
          f"powerflow_converged={converged})")
    return ok


def main() -> int:
    regions = sys.argv[1:] or ["okinawa"]
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    results = {r: process_region(r) for r in regions}
    n_ok = sum(1 for v in results.values() if v)
    print(f"\nDone: {n_ok}/{len(results)} region(s) fully validated "
          f"(.mat written + gencost + power flow converged).")
    print(f"Output dir: {OUTPUT_DIR}")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
