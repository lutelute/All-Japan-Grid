#!/usr/bin/env python3
"""Fast Q-sweep diagnostic for the west island AC convergence.

Builds the west island ONCE, then for each reactive-compensation factor makes
a SINGLE nr/dc power-flow attempt (no 8-solver fallback chain), so we can see
quickly whether the AC non-convergence is driven by over/under reactive
compensation (the user's "Q入れすぎ" hypothesis) rather than waiting through the
full gs(5000) fallback each time.

Usage::
    PYTHONPATH=. python scripts/test_west_reactive.py
"""
import copy
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandapower as pp

from examples.build_national_snapped import build_island_networks
from examples.run_powerflow_all import (
    fix_zero_voltages, insert_transformers, fix_topology,
    select_slack_bus, balance_power, scale_line_ratings, prune_dc_infeasible,
)
from src.powerflow.load_estimator import load_demand_config, estimate_loads
from src.reconstruction.config import ReconstructionConfig
from src.reconstruction.isolator import Isolator
from src.reconstruction.reconnector import Reconnector
from src.converter.pandapower_builder import PandapowerBuilder
from scripts.run_national_powerflow import add_reactive_compensation


def build_base():
    cfg = load_demand_config()
    islands, _ = build_island_networks()
    isl = islands["west"]
    net = PandapowerBuilder().build(isl["net"]).net
    fix_zero_voltages(net)
    insert_transformers(net)
    iso = Isolator().detect(net)
    Reconnector().reconnect(net, iso, ReconstructionConfig(
        mode="reconnect", max_reconnection_distance_km=5.0))
    fix_topology(net, multi_slack=True)
    select_slack_bus(net)
    estimate_loads(net, region="national", demand_config=cfg)
    inactive = set(net.bus.index[~net.bus["in_service"]])
    if len(net.load) > 0:
        net.load.loc[net.load["bus"].isin(inactive), "in_service"] = False
    balance_power(net, cfg)
    scale_line_ratings(net)
    return net


def try_reactive(base, r, prune_thr):
    net = copy.deepcopy(base)
    if prune_thr is not None:
        prune_dc_infeasible(net, prune_thr)
        fix_topology(net, multi_slack=True)
        select_slack_bus(net)
        scale_line_ratings(net)
    n_shunt = add_reactive_compensation(net, r)
    net.bus["vm_pu"] = 1.0
    if len(net.gen) > 0:
        net.gen["vm_pu"] = 1.0
    if len(net.ext_grid) > 0:
        net.ext_grid["vm_pu"] = 1.0
    conv = False
    reason = ""
    try:
        pp.runpp(net, algorithm="nr", init="dc", max_iteration=100,
                 tolerance_mva=1e-1, numba=True)
        conv = bool(net.converged)
    except Exception as e:
        reason = type(e).__name__ + ": " + str(e)[:70]
    if conv:
        vm = net.res_bus["vm_pu"].dropna()
        vmin = round(float(vm.min()), 3) if len(vm) else None
        vmax = round(float(vm.max()), 3) if len(vm) else None
        ml = net.res_line["loading_percent"].dropna()
        maxload = round(float(ml.max()), 1) if len(ml) else None
        return f"reactive={r:<4} prune={prune_thr}: AC nr/dc=OK   vm=[{vmin},{vmax}] maxload={maxload}% shunts={n_shunt}"
    return f"reactive={r:<4} prune={prune_thr}: AC nr/dc=FAIL  shunts={n_shunt} {reason}"


def main():
    print("building west island base (once)...", flush=True)
    base = build_base()
    print(f"west base: {len(base.bus)} buses, {len(base.line)} lines, "
          f"{int(base.bus['in_service'].sum())} in-service buses, "
          f"{len(base.load)} loads, gen={len(base.gen)} extgrid={len(base.ext_grid)}",
          flush=True)
    print("=== Q sweep (single nr/dc attempt each) ===", flush=True)
    # First without extra pruning, then with the thr=20 aggressive prune
    for prune_thr in (None, 20.0):
        for r in (0.0, 0.2, 0.4, 0.6, 0.8):
            print(try_reactive(base, r, prune_thr), flush=True)
    print("DONE_SWEEP", flush=True)


if __name__ == "__main__":
    main()
