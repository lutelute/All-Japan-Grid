"""A/B topology comparison harness.

Runs the *identical* powerflow downstream on two topology builders:

  A = build_network_from_geojson      (current: nearest-substation, drop same-sub)
  B = build_network_snapped           (vertex graph + tolerance snap)

Any difference in solution validity (fragmentation, voltage-angle range,
voltage magnitude, line loading) is therefore attributable to the topology
inference alone. Use this to decide whether B should replace A before a
(heavy) full national regeneration.

Usage::

    PYTHONPATH=. python examples/compare_topology_ab.py okinawa hokuriku
    PYTHONPATH=. python examples/compare_topology_ab.py            # default small set
"""
from __future__ import annotations

import copy
import os
import sys
import warnings

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)  # config/*.yaml paths are repo-relative

from src.powerflow.legacy_build import build_network_from_geojson
from src.powerflow.transforms import (
    balance_power,
    fix_topology,
    fix_zero_voltages,
    insert_transformers,
    prune_dc_infeasible,
    scale_line_ratings,
    select_slack_bus,
)
from src.powerflow.batch_solve import run_powerflow
from examples.build_snapped_topology import build_network_snapped
from src.converter.pandapower_builder import PandapowerBuilder
from src.powerflow.load_estimator import estimate_loads, load_demand_config


def solve(network, region, demand_cfg):
    """Identical downstream used for both A and B."""
    net = PandapowerBuilder().build(network).net
    fix_zero_voltages(net)
    insert_transformers(net)
    diag = fix_topology(net)
    select_slack_bus(net)
    estimate_loads(net, region=region, demand_config=demand_cfg)
    inactive = set(net.bus.index[~net.bus["in_service"]])
    if len(net.load) > 0:
        net.load.loc[net.load["bus"].isin(inactive), "in_service"] = False
    balance_power(net, demand_cfg)
    scale_line_ratings(net)
    net.bus["vm_pu"] = 1.0
    if len(net.gen) > 0:
        net.gen["vm_pu"] = 1.0
    if len(net.ext_grid) > 0:
        net.ext_grid["vm_pu"] = 1.0

    net_dc = copy.deepcopy(net)
    dc = run_powerflow(net_dc, "dc")

    ac = {"mode": "ac", "converged": False}
    for thr in (45.0, 30.0, 20.0):
        net_ac = copy.deepcopy(net)
        if prune_dc_infeasible(net_ac, angle_threshold=thr) > 0:
            fix_topology(net_ac)
            select_slack_bus(net_ac)
            scale_line_ratings(net_ac)
        ac = run_powerflow(net_ac, "ac")
        if ac["converged"]:
            break
    return diag, dc, ac, len(net.bus)


def _r(v):
    return round(v, 2) if isinstance(v, (int, float)) else v


def fmt(diag, dc, ac, nbus):
    return (f"buses={nbus} n_comp={diag['n_components']} active={diag['n_active_buses']} | "
            f"DC conv={dc.get('converged')} "
            f"va=[{_r(dc.get('va_deg_min'))},{_r(dc.get('va_deg_max'))}] "
            f"maxload={_r(dc.get('max_loading_pct'))} | "
            f"AC conv={ac.get('converged')} "
            f"vm=[{_r(ac.get('vm_pu_min'))},{_r(ac.get('vm_pu_max'))}] "
            f"maxload={_r(ac.get('max_loading_pct'))}")


def main():
    regions = sys.argv[1:] or ["okinawa", "hokuriku"]
    cfg = load_demand_config()
    for region in regions:
        print(f"\n========== {region} ==========")
        na = build_network_from_geojson(region)
        print(f"[A current]  subs={na.substation_count} lines={na.line_count} gens={na.generator_count}")
        print(f"  -> {fmt(*solve(na, region, cfg))}")
        nb = build_network_snapped(region, snap_km=1.5)
        print(f"[B vtx-snap] subs={nb.substation_count} lines={nb.line_count} gens={nb.generator_count}")
        print(f"  -> {fmt(*solve(nb, region, cfg))}")


if __name__ == "__main__":
    main()
