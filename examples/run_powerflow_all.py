#!/usr/bin/env python3
"""Run DC and AC power flow on all 10 Japanese regional grids.

Builds pandapower networks from OSM-derived GeoJSON data, runs power flow,
and produces a summary dashboard with voltage profiles and line loading.

Usage::

    PYTHONPATH=. python examples/run_powerflow_all.py
"""

import copy
import json
import math
import os
import sys
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandapower as pp
import pandapower.topology as top
import networkx as nx
import yaml

# Japanese font support
plt.rcParams["font.family"] = ["Hiragino Sans", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.converter.pandapower_builder import PandapowerBuilder
from src.model.grid_network import GridNetwork
from src.model.generator import Generator
from src.model.substation import Substation
from src.model.transmission_line import TransmissionLine
from src.powerflow.load_estimator import estimate_loads, load_demand_config, scale_generation

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output", "powerflow_regional")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Canonical region constants (config/regions.yaml via src.regions).
from src.regions import (  # noqa: E402
    REGIONS,
    REGION_JA,
    REGION_FREQUENCY_HZ as REGION_FREQ,
)

# Default capacity estimates (MW) by fuel type when capacity_mw is missing
_DEFAULT_CAPACITY_MW = {
    "nuclear": 900, "coal": 600, "gas": 400, "oil": 200,
    "oil;gas": 300, "gas;oil": 300, "coal;gas": 400, "gas;coal": 400,
    "coal;gas;oil": 400,
    "hydro": 30, "wind": 20, "solar": 10, "geothermal": 30,
    "biomass": 20, "waste": 5,
}
_DEFAULT_CAPACITY_FALLBACK = 10.0

# _TRAFO_PARAMS moved with insert_transformers into src.powerflow.transforms.


# ── GeoJSON → GridNetwork conversion ─────────────────────────────────────────

def _haversine_km(lat1, lon1, lat2, lon2):
    # Canonical impl in src.utils.geo_utils (same (lat, lon) order).
    from src.utils.geo_utils import haversine_distance
    return haversine_distance(lat1, lon1, lat2, lon2)


def _get_centroid(feature):
    geom = feature["geometry"]
    if geom is None:
        return None, None
    gtype = geom["type"]
    if gtype == "Point":
        return geom["coordinates"][1], geom["coordinates"][0]
    elif gtype == "Polygon":
        coords = geom["coordinates"][0]
    elif gtype == "MultiPolygon":
        coords = geom["coordinates"][0][0]
    else:
        return None, None
    lat = sum(c[1] for c in coords) / len(coords)
    lon = sum(c[0] for c in coords) / len(coords)
    return lat, lon


def _parse_voltage_kv(voltage_raw):
    """Parse OSM voltage string (in volts) to kV; 0.0 if none.

    Canonical max-voltage parser in src.utils.voltage.
    """
    from src.utils.voltage import parse_voltage_kv
    return parse_voltage_kv(voltage_raw) or 0.0


def _get_line_coords(feature):
    """Extract coordinates from a LineString or MultiLineString."""
    geom = feature.get("geometry")
    if not geom:
        return []
    gtype = geom["type"]
    if gtype == "LineString":
        return [(c[1], c[0]) for c in geom["coordinates"]]
    elif gtype == "MultiLineString":
        return [(c[1], c[0]) for c in geom["coordinates"][0]]
    return []


def _find_nearest_sub(lat, lon, sub_coords, max_km):
    """Find nearest substation within max_km."""
    best_id = None
    best_dist = float("inf")
    for slat, slon, sid in sub_coords:
        if abs(slat - lat) > 0.5:  # quick filter
            continue
        d = _haversine_km(lat, lon, slat, slon)
        if d < best_dist:
            best_dist = d
            best_id = sid
    return best_id if best_dist <= max_km else None


def build_network_from_geojson(region):
    """Build a GridNetwork from OSM GeoJSON files for a region."""
    freq = REGION_FREQ.get(region, 50)
    network = GridNetwork(region=region, frequency_hz=freq)

    # Load substations
    sub_path = os.path.join(DATA_DIR, f"{region}_substations.geojson")
    if not os.path.exists(sub_path):
        return None
    with open(sub_path, encoding="utf-8") as f:
        subs_data = json.load(f)

    sub_id_map = {}  # feature index → substation id
    for i, feat in enumerate(subs_data["features"]):
        lat, lon = _get_centroid(feat)
        if lat is None:
            continue
        props = feat["properties"]
        name = props.get("name") or f"{region}_sub_{i}"
        voltage_kv = _parse_voltage_kv(props.get("voltage"))
        sub_id = f"{region}_sub_{i}"
        sub_id_map[i] = sub_id

        sub = Substation(
            id=sub_id,
            name=name,
            region=region,
            latitude=lat,
            longitude=lon,
            voltage_kv=max(voltage_kv, 0),
        )
        network.add_substation(sub)

    # Build spatial index of substations for endpoint matching
    sub_coords = []
    for sub in network.substations:
        sub_coords.append((sub.latitude, sub.longitude, sub.id))

    # Load lines and match endpoints to nearest substations
    lines_path = os.path.join(DATA_DIR, f"{region}_lines.geojson")
    if os.path.exists(lines_path):
        with open(lines_path, encoding="utf-8") as f:
            lines_data = json.load(f)

        for i, feat in enumerate(lines_data["features"]):
            props = feat["properties"]
            name = props.get("name") or props.get("_display_name") or f"{region}_line_{i}"
            voltage_kv = _parse_voltage_kv(props.get("voltage"))

            coords = _get_line_coords(feat)
            if len(coords) < 2:
                continue

            start_lat, start_lon = coords[0]
            end_lat, end_lon = coords[-1]

            from_sub_id = _find_nearest_sub(start_lat, start_lon, sub_coords, 50.0)
            to_sub_id = _find_nearest_sub(end_lat, end_lon, sub_coords, 50.0)

            if not from_sub_id or not to_sub_id or from_sub_id == to_sub_id:
                continue

            length_km = 0.0
            for j in range(1, len(coords)):
                length_km += _haversine_km(coords[j-1][0], coords[j-1][1],
                                            coords[j][0], coords[j][1])

            if length_km <= 0:
                continue

            line_id = f"{region}_line_{i}"
            line = TransmissionLine(
                id=line_id,
                name=name,
                from_substation_id=from_sub_id,
                to_substation_id=to_sub_id,
                voltage_kv=max(voltage_kv, 0),
                length_km=length_km,
                region=region,
            )
            try:
                network.add_transmission_line(line)
            except ValueError:
                pass  # duplicate ID, skip

    # Step 1: Load generators from plants GeoJSON
    plants_path = os.path.join(DATA_DIR, f"{region}_plants.geojson")
    if os.path.exists(plants_path):
        with open(plants_path, encoding="utf-8") as f:
            plants_data = json.load(f)

        gen_count = 0
        for i, feat in enumerate(plants_data["features"]):
            lat, lon = _get_centroid(feat)
            if lat is None:
                continue
            props = feat["properties"]

            # Extract capacity
            capacity_mw = None
            raw_cap = props.get("capacity_mw")
            if raw_cap is not None:
                try:
                    capacity_mw = float(raw_cap)
                except (ValueError, TypeError):
                    pass

            fuel = props.get("plant:source") or props.get("fuel_type") or "unknown"
            # Clean fuel string (some have URLs)
            if fuel.startswith("http"):
                fuel = "unknown"

            if capacity_mw is None or capacity_mw <= 0:
                capacity_mw = _DEFAULT_CAPACITY_MW.get(fuel, _DEFAULT_CAPACITY_FALLBACK)

            # Match to nearest substation bus (< 5km)
            nearest_sub = _find_nearest_sub(lat, lon, sub_coords, 5.0)
            if not nearest_sub:
                # Relax to 20km for large plants
                if capacity_mw >= 100:
                    nearest_sub = _find_nearest_sub(lat, lon, sub_coords, 20.0)
                if not nearest_sub:
                    continue

            name = props.get("name") or props.get("_display_name") or f"{region}_plant_{i}"
            gen_id = f"{region}_gen_{i}"

            gen = Generator(
                id=gen_id,
                name=name,
                capacity_mw=capacity_mw,
                fuel_type=fuel,
                connected_bus_id=nearest_sub,
                region=region,
                latitude=lat,
                longitude=lon,
            )
            network.add_generator(gen)
            gen_count += 1

    return network


# ── Post-build network fixes ─────────────────────────────────────────────────
# The net-transform pipeline now lives in src.powerflow.transforms; re-exported
# here so existing `from examples.run_powerflow_all import ...` call sites work.
from src.powerflow.transforms import (  # noqa: E402,F401
    fix_zero_voltages, insert_transformers, select_slack_bus,
    fix_topology, prune_dc_infeasible, scale_line_ratings, balance_power,
)

# ── Power flow execution ─────────────────────────────────────────────────────

# run_powerflow (the batch DC/AC solver returning a summary dict) now lives
# in src.powerflow.batch_solve; re-exported here so existing
# `from examples.run_powerflow_all import run_powerflow` call sites work.
from src.powerflow.batch_solve import run_powerflow  # noqa: E402,F401


# ── Dashboard ─────────────────────────────────────────────────────────────────

def plot_dashboard(all_results):
    """Create a summary dashboard figure."""
    fig, axes = plt.subplots(2, 2, figsize=(18, 14))
    fig.suptitle("Japan Regional Power Flow Analysis (OSM GeoJSON)\n"
                 "日本電力系統 地域別潮流計算結果（OSMデータ）",
                 fontsize=16, fontweight="bold", y=0.98)

    regions_sorted = [r for r in REGIONS if r in all_results]
    n = len(regions_sorted)
    x = np.arange(n)
    labels = [f"{REGION_JA[r]}\n{r.title()}" for r in regions_sorted]

    # --- Panel 1: Network size ---
    ax = axes[0, 0]
    buses = [all_results[r]["n_buses"] for r in regions_sorted]
    lines = [all_results[r]["n_lines"] for r in regions_sorted]
    gens = [all_results[r].get("n_gens", 0) for r in regions_sorted]
    trafos = [all_results[r].get("n_trafos", 0) for r in regions_sorted]
    w = 0.2
    ax.bar(x - 1.5*w, buses, w, label="Buses", color="#2196F3", alpha=0.8)
    ax.bar(x - 0.5*w, lines, w, label="Lines", color="#FF9800", alpha=0.8)
    ax.bar(x + 0.5*w, gens, w, label="Gens", color="#4CAF50", alpha=0.8)
    ax.bar(x + 1.5*w, trafos, w, label="Trafos", color="#9C27B0", alpha=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("Count")
    ax.set_title("(a) Network Size — バス・送電線・発電機・変圧器数")
    ax.legend(fontsize=7)
    ax.grid(axis="y", alpha=0.3)

    # --- Panel 2: DC power flow - bus voltage angle ---
    ax = axes[0, 1]
    for i, r in enumerate(regions_sorted):
        dc = all_results[r].get("dc")
        if dc and dc.get("converged"):
            va_min = dc.get("va_deg_min", 0)
            va_max = dc.get("va_deg_max", 0)
            ax.barh(i, va_max - va_min, left=va_min, height=0.6, color="#4CAF50", alpha=0.7)
            ax.plot([va_min, va_max], [i, i], "k-", linewidth=1.5)
        else:
            ax.barh(i, 0, height=0.6, color="#FFCDD2")
    ax.set_yticks(range(n))
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("Voltage Angle (degrees)")
    ax.set_title("(b) DC Power Flow — Bus Voltage Angle Range")
    ax.grid(axis="x", alpha=0.3)

    # --- Panel 3: Line loading ---
    ax = axes[1, 0]
    dc_loading = []
    dc_labels_line = []
    for r in regions_sorted:
        dc = all_results[r].get("dc")
        if dc and dc.get("converged"):
            dc_loading.append(dc.get("max_loading_pct", 0))
            dc_labels_line.append(REGION_JA[r])
        else:
            dc_loading.append(0)
            dc_labels_line.append(f"{REGION_JA[r]} (N/C)")
    if dc_loading:
        colors_bar = ["#F44336" if v > 100 else "#FF9800" if v > 80 else "#4CAF50" for v in dc_loading]
        ax.barh(range(len(dc_loading)), dc_loading, color=colors_bar, alpha=0.8)
        ax.set_yticks(range(len(dc_loading)))
        ax.set_yticklabels(dc_labels_line, fontsize=9)
        ax.axvline(100, color="red", linestyle="--", linewidth=1, label="100% limit")
        ax.axvline(80, color="orange", linestyle="--", linewidth=1, label="80% warning")
    ax.set_xlabel("Max Line Loading (%)")
    ax.set_title("(c) DC Power Flow — Maximum Line Loading")
    ax.legend(fontsize=8)
    ax.grid(axis="x", alpha=0.3)

    # --- Panel 4: Convergence summary table ---
    ax = axes[1, 1]
    ax.axis("off")
    table_data = []
    headers = ["Region", "Buses", "Lines", "Gens", "Trafos", "DC", "AC", "Solver"]
    for r in regions_sorted:
        d = all_results[r]
        dc = d.get("dc", {})
        ac = d.get("ac", {})
        table_data.append([
            f"{REGION_JA[r]} ({r})",
            str(d["n_buses"]),
            str(d["n_lines"]),
            str(d.get("n_gens", 0)),
            str(d.get("n_trafos", 0)),
            "OK" if dc.get("converged") else "FAIL",
            "OK" if ac.get("converged") else "FAIL",
            ac.get("solver", "-") if ac.get("converged") else "-",
        ])

    tbl = ax.table(cellText=table_data, colLabels=headers,
                   loc="center", cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8)
    tbl.scale(1.0, 1.4)
    for i, row in enumerate(table_data):
        for j, val in enumerate(row):
            cell = tbl[i + 1, j]
            if val == "OK":
                cell.set_facecolor("#C8E6C9")
            elif val == "FAIL":
                cell.set_facecolor("#FFCDD2")
    ax.set_title("(d) Convergence Summary — 収束結果一覧", pad=20)

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    out_path = os.path.join(OUTPUT_DIR, "regional_powerflow_dashboard.png")
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nDashboard saved: {out_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    demand_cfg = load_demand_config()
    all_results = {}

    for region in REGIONS:
        print(f"\n{'='*60}")
        print(f"  {REGION_JA[region]} ({region})")
        print(f"{'='*60}")

        # Build network from GeoJSON (includes generators now)
        network = build_network_from_geojson(region)
        if not network or not network.has_elements:
            print(f"  SKIP: no GeoJSON data for {region}")
            continue

        print(f"  GeoJSON: {network.substation_count} substations, "
              f"{network.line_count} lines, "
              f"{network.generator_count} generators "
              f"({network.total_generation_mw:.0f} MW)")

        # Convert to pandapower
        builder = PandapowerBuilder()
        build_result = builder.build(network)
        net = build_result.net

        # Step 2: Fix zero-voltage buses
        n_fixed_v = fix_zero_voltages(net)
        if n_fixed_v > 0:
            print(f"  Fixed {n_fixed_v} zero-voltage buses")

        # Verify no zero-voltage buses remain
        assert (net.bus["vn_kv"] > 0).all(), "Zero-voltage buses remain!"

        # Step 3: Insert transformers at voltage boundaries
        n_trafos = insert_transformers(net)

        n_buses = len(net.bus)
        n_lines = len(net.line)
        n_gens = len(net.gen)
        print(f"  pandapower: {n_buses} buses, {n_lines} lines, "
              f"{n_gens} gens, {n_trafos} trafos, "
              f"{len(build_result.warnings)} warnings")

        # Step 5: Fix topology (keep largest component)
        diag = fix_topology(net)
        print(f"  Components: {diag['n_components']}, "
              f"isolated: {diag['n_isolated_buses']}, "
              f"active: {diag['n_active_buses']}")

        # Step 4: Select optimal slack bus
        slack_bus = select_slack_bus(net)
        if slack_bus is not None:
            slack_name = net.bus.at[slack_bus, "name"]
            slack_vn = net.bus.at[slack_bus, "vn_kv"]
            print(f"  Slack bus: {slack_bus} ({slack_name}, {slack_vn:.0f} kV)")

        # Disable loads on out-of-service buses, then estimate
        # First, remove any pre-existing loads (shouldn't be any)
        # estimate_loads creates on all buses; we'll fix after
        total_load = estimate_loads(net, region=region, demand_config=demand_cfg)
        # Disable loads on out-of-service buses
        if len(net.load) > 0:
            inactive_buses = set(net.bus.index[~net.bus["in_service"]])
            mask = net.load["bus"].isin(inactive_buses)
            net.load.loc[mask, "in_service"] = False
            active_loads = net.load[net.load["in_service"]]
            total_load = active_loads["p_mw"].sum()
        print(f"  Loads allocated: {total_load:.0f} MW across "
              f"{net.load['in_service'].sum()} active buses")

        # Step 6: Balance generation to load
        balance_power(net, demand_cfg)
        total_gen = net.gen["p_mw"].sum() if len(net.gen) > 0 else 0
        print(f"  Generation: {total_gen:.0f} MW ({len(net.gen)} units)")

        # Scale line/trafo ratings to prevent bottlenecks
        scale_line_ratings(net)

        # Set initial flat voltage profile and enforce gen voltage setpoints
        net.bus["vm_pu"] = 1.0
        if len(net.gen) > 0:
            net.gen["vm_pu"] = 1.0
        if len(net.ext_grid) > 0:
            net.ext_grid["vm_pu"] = 1.0

        # DC power flow
        net_dc = copy.deepcopy(net)
        dc_result = run_powerflow(net_dc, "dc")
        if dc_result["converged"]:
            print(f"  DC: converged, loss={dc_result.get('total_loss_mw', 0):.1f} MW, "
                  f"max_loading={dc_result.get('max_loading_pct', 0):.1f}%, "
                  f"angle=[{dc_result.get('va_deg_min', 0):.1f}, "
                  f"{dc_result.get('va_deg_max', 0):.1f}] deg")
        else:
            print(f"  DC: FAILED — {dc_result.get('error', 'unknown')}")

        # AC power flow (with solver fallback chain)
        # Try progressively tighter pruning until convergence
        ac_result = {"mode": "ac", "converged": False}
        for prune_threshold in [45.0, 30.0, 20.0]:
            net_ac = copy.deepcopy(net)
            n_pruned = prune_dc_infeasible(net_ac, angle_threshold=prune_threshold)
            if n_pruned > 0:
                diag_ac = fix_topology(net_ac)
                select_slack_bus(net_ac)
                scale_line_ratings(net_ac)
                print(f"  AC prep (threshold={prune_threshold}°): pruned {n_pruned} branches, "
                      f"{diag_ac['n_active_buses']} active buses remain")
            ac_result = run_powerflow(net_ac, "ac")
            if ac_result["converged"]:
                break
        if ac_result["converged"]:
            print(f"  AC: converged ({ac_result.get('solver','?')}), "
                  f"loss={ac_result.get('total_loss_mw', 0):.1f} MW, "
                  f"V=[{ac_result.get('vm_pu_min', 0):.4f}, "
                  f"{ac_result.get('vm_pu_max', 0):.4f}] pu")
        else:
            print(f"  AC: FAILED — {ac_result.get('error', 'unknown')[:80]}")

        all_results[region] = {
            "n_buses": n_buses,
            "n_lines": n_lines,
            "n_gens": n_gens,
            "n_trafos": n_trafos,
            "n_active_buses": diag["n_active_buses"],
            "topology": diag,
            "dc": dc_result,
            "ac": ac_result,
        }

    # Generate dashboard
    if all_results:
        print(f"\n{'='*60}")
        print("  Generating dashboard...")
        print(f"{'='*60}")
        plot_dashboard(all_results)

    # Print final summary
    print(f"\n{'='*60}")
    print("  FINAL SUMMARY — 全地域潮流計算結果")
    print(f"{'='*60}")
    total_buses = sum(r["n_buses"] for r in all_results.values())
    total_lines = sum(r["n_lines"] for r in all_results.values())
    total_gens = sum(r.get("n_gens", 0) for r in all_results.values())
    total_trafos = sum(r.get("n_trafos", 0) for r in all_results.values())
    dc_ok = sum(1 for r in all_results.values() if r["dc"].get("converged"))
    ac_ok = sum(1 for r in all_results.values() if r["ac"].get("converged"))
    print(f"  Total: {total_buses} buses, {total_lines} lines, "
          f"{total_gens} gens, {total_trafos} trafos across "
          f"{len(all_results)} regions")
    print(f"  DC convergence: {dc_ok}/{len(all_results)}")
    print(f"  AC convergence: {ac_ok}/{len(all_results)}")
    print(f"  Output: {os.path.abspath(OUTPUT_DIR)}")


if __name__ == "__main__":
    main()
