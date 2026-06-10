#!/usr/bin/env python3
"""National zonal power flow: solve each synchronous AC island as ONE network
(with inter-regional AC tie-lines + residual reconnection + reactive shunt
compensation), so cross-regional transfer is modelled, then export per-region
GeoJSON slices from the island solution (existing live-map files, now solved
nationally) plus a summary.

Heavy compute (the west island is ~12k buses) -> run on pws-160core.

Usage:
  PYTHONPATH=. python scripts/run_national_powerflow.py --output-dir docs/data/powerflow_national
  PYTHONPATH=. python scripts/run_national_powerflow.py --islands east --reactive 0.6
"""
import argparse
import copy
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandapower as pp

from src.powerflow.national import ISLANDS, build_island_networks
from src.powerflow.transforms import (
    apply_voltage_setpoints,
    balance_power,
    balance_power_by_zone,
    fix_topology,
    fix_zero_voltages,
    insert_transformers,
    prune_dc_infeasible,
    scale_line_ratings,
    select_slack_bus,
)
from src.powerflow.batch_solve import run_powerflow
from scripts.export_powerflow_pages import _parse_bus_coords
from src.converter.pandapower_builder import PandapowerBuilder
from src.powerflow.load_estimator import estimate_loads, load_demand_config
from src.reconstruction.config import ReconstructionConfig
from src.reconstruction.isolator import Isolator
from src.reconstruction.reconnector import Reconnector

OUT_DEFAULT = os.path.join(os.path.dirname(__file__), "..", "docs", "data", "powerflow_national")


def add_reactive_compensation(net, factor):
    """Add capacitive shunts at load buses to counter undervoltage.

    factor = fraction of each load's reactive demand supplied locally by a
    shunt capacitor (q_mvar negative = injects Q into the bus).
    """
    if factor <= 0 or len(net.load) == 0:
        return 0
    by_bus = net.load[net.load["in_service"]].groupby("bus")["q_mvar"].sum()
    n = 0
    for bus, q in by_bus.items():
        if q > 0:
            pp.create_shunt(net, bus=int(bus), q_mvar=-factor * float(q), p_mw=0.0)
            n += 1
    return n


def solve_island(island_id, isl, demand_cfg, reactive):
    """Build + reconnect + reactive-compensate + solve one synchronous island."""
    net = PandapowerBuilder().build(isl["net"]).net
    fix_zero_voltages(net)
    insert_transformers(net)
    iso = Isolator().detect(net)
    # Only bridge tiny same-landmass gaps; tie-lines already connect regions.
    rec = Reconnector().reconnect(net, iso, ReconstructionConfig(
        mode="reconnect", max_reconnection_distance_km=5.0))
    # multi_slack: keep every component (incl. far parts of a region) solved in
    # place — avoids the previous bug where distant Tohoku buses were disabled.
    diag = fix_topology(net, multi_slack=True)
    select_slack_bus(net)
    # per-region demand allocation via bus 'zone'
    estimate_loads(net, region="national", demand_config=demand_cfg)
    inactive = set(net.bus.index[~net.bus["in_service"]])
    if len(net.load) > 0:
        net.load.loc[net.load["bus"].isin(inactive), "in_service"] = False
    balance_power_by_zone(net, demand_cfg)
    scale_line_ratings(net)
    n_shunt = add_reactive_compensation(net, reactive)
    net.bus["vm_pu"] = 1.0
    # AVR-style class schedule (matches src.powerflow.pipeline phase 5)
    apply_voltage_setpoints(net)

    net_dc = copy.deepcopy(net)
    dc = run_powerflow(net_dc, "dc")
    ac = {"mode": "ac", "converged": False}
    net_ac = None
    for thr in (45.0, 30.0, 20.0):
        net_ac = copy.deepcopy(net)
        if prune_dc_infeasible(net_ac, angle_threshold=thr) > 0:
            fix_topology(net_ac, multi_slack=True); select_slack_bus(net_ac); scale_line_ratings(net_ac)
        ac = run_powerflow(net_ac, "ac")
        if ac["converged"]:
            break
    return net_dc, dc, net_ac, ac, rec.lines_created, n_shunt, diag


def _region_of_bus(net, idx):
    z = net.bus.at[idx, "zone"]
    return z if isinstance(z, str) else None


def export_region_slices(net, mode, region, geom):
    """Per-region GeoJSON (buses + lines) filtered from the island solution."""
    buses = []
    bus_region = {}
    for idx in net.bus.index:
        if not net.bus.at[idx, "in_service"]:
            continue
        bus_region[idx] = _region_of_bus(net, idx)
        if bus_region[idx] != region:
            continue
        lon, lat = _parse_bus_coords(net, idx)
        if lon is None or (lon == 0 and lat == 0):
            continue
        vm = float(net.res_bus.at[idx, "vm_pu"]) if idx in net.res_bus.index else 1.0
        va = float(net.res_bus.at[idx, "va_degree"]) if idx in net.res_bus.index else 0.0
        buses.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                      "properties": {"name": str(net.bus.at[idx, "name"]),
                                     "vn_kv": round(float(net.bus.at[idx, "vn_kv"]), 1),
                                     "vm_pu": round(vm, 4), "va_deg": round(va, 2)}})
    lines = []
    for idx in net.line.index:
        if not net.line.at[idx, "in_service"]:
            continue
        fb = net.line.at[idx, "from_bus"]; tb = net.line.at[idx, "to_bus"]
        rf = bus_region.get(fb, _region_of_bus(net, fb)); rt = bus_region.get(tb, _region_of_bus(net, tb))
        if region not in (rf, rt):
            continue
        flon, flat = _parse_bus_coords(net, fb); tlon, tlat = _parse_bus_coords(net, tb)
        if flon is None or tlon is None:
            continue
        loading = float(net.res_line.at[idx, "loading_percent"]) if idx in net.res_line.index and "loading_percent" in net.res_line.columns else 0.0
        p_mw = float(net.res_line.at[idx, "p_from_mw"]) if idx in net.res_line.index and "p_from_mw" in net.res_line.columns else 0.0
        name = str(net.line.at[idx, "name"])
        coords = geom.get(((round(flat, 5), round(flon, 5)), (round(tlat, 5), round(tlon, 5))))
        if not coords:
            coords = [[flon, flat], [tlon, tlat]]
        lines.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
                      "properties": {"name": name, "loading_pct": round(min(loading, 200), 1),
                                     "p_mw": round(p_mw, 1),
                                     "synthetic": name.startswith("recon_line"),
                                     "tie": name.startswith("tie_") or rf != rt}})
    return ({"type": "FeatureCollection", "features": buses},
            {"type": "FeatureCollection", "features": lines})


def region_summary(net, region):
    idx = [i for i in net.bus.index if net.bus.at[i, "in_service"] and _region_of_bus(net, i) == region and i in net.res_bus.index]
    if not idx:
        return {}
    vm = [float(net.res_bus.at[i, "vm_pu"]) for i in idx]
    return {"vm_min": round(min(vm), 4), "vm_max": round(max(vm), 4), "n_buses_region": len(idx)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="*", default=None, help="subset of islands (hokkaido east west okinawa)")
    ap.add_argument("--reactive", type=float, default=0.6, help="reactive comp factor (0=off)")
    ap.add_argument("--output-dir", default=OUT_DEFAULT)
    args = ap.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    cfg = load_demand_config()
    islands, async_links = build_island_networks()
    targets = args.islands or list(islands.keys())
    # Merge into any existing summary so running islands in separate invocations
    # (e.g. the heavy west island on its own) accumulates rather than clobbering
    # the regions written by earlier runs.
    summary = {}
    summary_path = f"{args.output_dir}/summary.json"
    if os.path.exists(summary_path):
        try:
            with open(summary_path, encoding="utf-8") as f:
                summary = json.load(f)
        except (json.JSONDecodeError, OSError):
            summary = {}
    print(f"islands={targets} reactive={args.reactive} out={args.output_dir}")
    for iid in targets:
        if iid not in islands:
            continue
        isl = islands[iid]
        net_dc, dc, net_ac, ac, n_syn, n_shunt, diag = solve_island(iid, isl, cfg, args.reactive)
        net_for_ac = net_ac if ac.get("converged") else None
        for region in isl["regions"]:
            # DC slices
            if dc.get("converged"):
                b, l = export_region_slices(net_dc, "dc", region, isl["geom"])
                json.dump(b, open(f"{args.output_dir}/{region}_dc_buses.geojson", "w"), separators=(",", ":"))
                json.dump(l, open(f"{args.output_dir}/{region}_dc_lines.geojson", "w"), separators=(",", ":"))
            if net_for_ac is not None:
                b, l = export_region_slices(net_for_ac, "ac", region, isl["geom"])
                json.dump(b, open(f"{args.output_dir}/{region}_ac_buses.geojson", "w"), separators=(",", ":"))
                json.dump(l, open(f"{args.output_dir}/{region}_ac_lines.geojson", "w"), separators=(",", ":"))
            rs = region_summary(net_for_ac if net_for_ac is not None else net_dc, region)
            summary[region] = {
                "island": iid, "ac_converged": ac.get("converged", False),
                "dc_converged": dc.get("converged", False),
                "ac_vm_min": rs.get("vm_min"), "ac_vm_max": rs.get("vm_max"),
                "n_buses": rs.get("n_buses_region"),
                "n_components": diag.get("n_components"),
                "n_synthetic_lines": n_syn, "n_shunt_comp": n_shunt,
                "topology": "national_zonal",
            }
        print(f"  island {iid:9s}: AC={'OK' if ac.get('converged') else 'FAIL'} "
              f"DC={'OK' if dc.get('converged') else 'FAIL'} synth={n_syn} shunts={n_shunt} "
              f"vm=[{ac.get('vm_pu_min')},{ac.get('vm_pu_max')}] maxload={ac.get('max_loading_pct')}")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"done -> {args.output_dir}  (summary regions: {sorted(summary.keys())})")


if __name__ == "__main__":
    main()
