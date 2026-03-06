#!/usr/bin/env python3
"""Export power flow results as GeoJSON for GitHub Pages visualization.

Runs DC and AC power flow on all 10 regions and exports per-region results
containing bus voltage, line loading, and generation data as GeoJSON files.

Usage::

    PYTHONPATH=. python scripts/export_powerflow_pages.py
"""

import copy
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandapower as pp

from examples.run_powerflow_all import (
    REGIONS, REGION_JA, REGION_FREQ,
    build_network_from_geojson,
    fix_zero_voltages, insert_transformers, fix_topology,
    select_slack_bus, balance_power, scale_line_ratings,
    prune_dc_infeasible, run_powerflow,
)
from src.converter.pandapower_builder import PandapowerBuilder
from src.powerflow.load_estimator import estimate_loads, load_demand_config

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "data", "powerflow")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def build_and_solve(region, demand_cfg):
    """Build network, solve DC+AC, return (net_dc, dc_result, net_ac, ac_result, build_info)."""
    network = build_network_from_geojson(region)
    if not network or not network.has_elements:
        return None

    builder = PandapowerBuilder()
    build_result = builder.build(network)
    net = build_result.net

    fix_zero_voltages(net)
    n_trafos = insert_transformers(net)
    diag = fix_topology(net)
    select_slack_bus(net)

    total_load = estimate_loads(net, region=region, demand_config=demand_cfg)
    inactive_buses = set(net.bus.index[~net.bus["in_service"]])
    if len(net.load) > 0:
        mask = net.load["bus"].isin(inactive_buses)
        net.load.loc[mask, "in_service"] = False
        total_load = net.load[net.load["in_service"]]["p_mw"].sum()

    balance_power(net, demand_cfg)
    scale_line_ratings(net)
    net.bus["vm_pu"] = 1.0
    if len(net.gen) > 0:
        net.gen["vm_pu"] = 1.0
    if len(net.ext_grid) > 0:
        net.ext_grid["vm_pu"] = 1.0

    # DC
    net_dc = copy.deepcopy(net)
    dc_result = run_powerflow(net_dc, "dc")

    # AC with pruning
    ac_result = {"mode": "ac", "converged": False}
    net_ac = None
    for threshold in [45.0, 30.0, 20.0]:
        net_ac = copy.deepcopy(net)
        n_pruned = prune_dc_infeasible(net_ac, angle_threshold=threshold)
        if n_pruned > 0:
            fix_topology(net_ac)
            select_slack_bus(net_ac)
            scale_line_ratings(net_ac)
        ac_result = run_powerflow(net_ac, "ac")
        if ac_result["converged"]:
            break

    build_info = {
        "n_buses": len(net.bus),
        "n_lines": len(net.line),
        "n_gens": len(net.gen),
        "n_trafos": n_trafos,
        "n_active_buses": diag["n_active_buses"],
        "n_components": diag["n_components"],
        "total_load_mw": float(total_load),
        "total_gen_mw": float(net.gen[net.gen["in_service"]]["p_mw"].sum()) if len(net.gen) > 0 else 0,
    }

    return net_dc, dc_result, net_ac, ac_result, build_info


def _parse_bus_coords(net, idx):
    """Extract (lon, lat) from pandapower bus geo column."""
    if "geo" in net.bus.columns:
        geo_raw = net.bus.at[idx, "geo"]
        if isinstance(geo_raw, str):
            try:
                geo_obj = json.loads(geo_raw)
                coords = geo_obj.get("coordinates", [])
                if len(coords) >= 2:
                    return float(coords[0]), float(coords[1])
            except (json.JSONDecodeError, TypeError):
                pass
        elif hasattr(geo_raw, '__len__') and len(geo_raw) >= 2:
            return float(geo_raw[0]), float(geo_raw[1])
    if hasattr(net, "bus_geodata") and not net.bus_geodata.empty and idx in net.bus_geodata.index:
        row = net.bus_geodata.loc[idx]
        return float(row["x"]), float(row["y"])
    return None, None


def export_bus_geojson(net, mode_label):
    """Export bus results as GeoJSON FeatureCollection."""
    features = []
    for idx in net.bus.index:
        if not net.bus.at[idx, "in_service"]:
            continue
        lon, lat = _parse_bus_coords(net, idx)
        if lon is None or (lon == 0 and lat == 0):
            continue

        vm_pu = float(net.res_bus.at[idx, "vm_pu"]) if idx in net.res_bus.index else 1.0
        va_deg = float(net.res_bus.at[idx, "va_degree"]) if idx in net.res_bus.index else 0.0
        vn_kv = float(net.bus.at[idx, "vn_kv"])

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "name": str(net.bus.at[idx, "name"]),
                "vn_kv": round(vn_kv, 1),
                "vm_pu": round(vm_pu, 4),
                "va_deg": round(va_deg, 2),
            }
        })

    return {"type": "FeatureCollection", "features": features}


def export_line_geojson(net):
    """Export line results as GeoJSON FeatureCollection."""
    features = []
    for idx in net.line.index:
        if not net.line.at[idx, "in_service"]:
            continue

        from_bus = net.line.at[idx, "from_bus"]
        to_bus = net.line.at[idx, "to_bus"]

        from_lon, from_lat = _parse_bus_coords(net, from_bus)
        to_lon, to_lat = _parse_bus_coords(net, to_bus)

        if from_lon is None or to_lon is None:
            continue

        loading = 0.0
        p_mw = 0.0
        if idx in net.res_line.index:
            loading = float(net.res_line.at[idx, "loading_percent"]) if "loading_percent" in net.res_line.columns else 0.0
            p_mw = float(net.res_line.at[idx, "p_from_mw"]) if "p_from_mw" in net.res_line.columns else 0.0

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[from_lon, from_lat], [to_lon, to_lat]]
            },
            "properties": {
                "name": str(net.line.at[idx, "name"]),
                "loading_pct": round(min(loading, 200), 1),
                "p_mw": round(p_mw, 1),
            }
        })

    return {"type": "FeatureCollection", "features": features}


def main():
    demand_cfg = load_demand_config()
    summary = {}

    for region in REGIONS:
        print(f"  Processing {region}...", end=" ", flush=True)
        result = build_and_solve(region, demand_cfg)
        if result is None:
            print("SKIP")
            continue

        net_dc, dc_result, net_ac, ac_result, build_info = result

        # Export DC results
        if dc_result["converged"]:
            dc_buses = export_bus_geojson(net_dc, "dc")
            dc_lines = export_line_geojson(net_dc)
            with open(os.path.join(OUTPUT_DIR, f"{region}_dc_buses.geojson"), "w") as f:
                json.dump(dc_buses, f, separators=(",", ":"))
            with open(os.path.join(OUTPUT_DIR, f"{region}_dc_lines.geojson"), "w") as f:
                json.dump(dc_lines, f, separators=(",", ":"))

        # Export AC results
        if ac_result["converged"]:
            ac_buses = export_bus_geojson(net_ac, "ac")
            ac_lines = export_line_geojson(net_ac)
            with open(os.path.join(OUTPUT_DIR, f"{region}_ac_buses.geojson"), "w") as f:
                json.dump(ac_buses, f, separators=(",", ":"))
            with open(os.path.join(OUTPUT_DIR, f"{region}_ac_lines.geojson"), "w") as f:
                json.dump(ac_lines, f, separators=(",", ":"))

        dc_status = "OK" if dc_result["converged"] else "FAIL"
        ac_status = "OK" if ac_result["converged"] else "FAIL"
        ac_solver = ac_result.get("solver", "-")

        summary[region] = {
            "name_ja": REGION_JA[region],
            "dc_converged": dc_result["converged"],
            "ac_converged": ac_result["converged"],
            "ac_solver": ac_solver,
            "dc_loss_mw": round(dc_result.get("total_loss_mw", 0), 1),
            "ac_loss_mw": round(ac_result.get("total_loss_mw", 0), 1),
            "ac_vm_min": round(ac_result.get("vm_pu_min", 0), 4),
            "ac_vm_max": round(ac_result.get("vm_pu_max", 0), 4),
            "dc_va_min": round(dc_result.get("va_deg_min", 0), 1),
            "dc_va_max": round(dc_result.get("va_deg_max", 0), 1),
            "dc_max_loading": round(dc_result.get("max_loading_pct", 0), 1),
            "ac_max_loading": round(ac_result.get("max_loading_pct", 0), 1),
            **build_info,
        }

        print(f"DC={dc_status} AC={ac_status}")

    # Write summary JSON
    with open(os.path.join(OUTPUT_DIR, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    dc_ok = sum(1 for v in summary.values() if v["dc_converged"])
    ac_ok = sum(1 for v in summary.values() if v["ac_converged"])
    print(f"\nDone: DC {dc_ok}/{len(summary)}, AC {ac_ok}/{len(summary)}")
    print(f"Output: {os.path.abspath(OUTPUT_DIR)}")


if __name__ == "__main__":
    main()
