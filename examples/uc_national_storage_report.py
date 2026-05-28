#!/usr/bin/env python3
"""National UC with 757 generators + 29 storage units — result report.

Loads all 757 real generators from OSM-derived GeoJSON, identifies pumped-storage
hydro plants (17 known sites, 27 entries across regions) and grid-scale batteries
(2 sites), solves a 24-hour unit commitment with full MILP, and prints a
comprehensive report including:

1. Fleet summary by fuel type and region
2. Solver status and cost breakdown
3. Storage SOC (State-of-Charge) profiles for all 29 units
4. Dispatch summary by fuel type per hour

This example demonstrates:
- Automatic detection of pumped-hydro from known plant names
- Battery storage identification from OSM fuel_type="battery"
- Storage parameters: capacity (MWh), charge/discharge rate, efficiency
- SOC tracking with initial/terminal constraints
- Adaptive solver with tier selection (HIGH/MID/LOW)

Usage::

    python examples/uc_national_storage_report.py

Requirements:
    - ``data/{region}_plants.geojson`` files (from OSM fetch pipeline)
    - PuLP with HiGHS or CBC solver
"""

import json
import os
import sys
import time as _time
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import ListedColormap

# Japanese font support
plt.rcParams["font.family"] = ["Hiragino Sans", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

from src.model.generator import Generator
from src.uc.adaptive_solver import solve_adaptive
from src.uc.hardware_detector import detect_hardware
from src.uc.models import DemandProfile, TimeHorizon, UCParameters
from src.uc.solver_strategy import SolverTier

# ── Configuration ─────────────────────────────────────────────────────────────

REGIONS = [
    "hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
    "kansai", "chugoku", "shikoku", "kyushu", "okinawa",
]

NUM_PERIODS = 24
DEMAND_FACTOR = 0.65
RESERVE_MARGIN = 0.05
MIN_CAPACITY_MW = 5.0

# Summer weekday demand shape (normalized, peak = 1.0)
DEMAND_SHAPE = np.array([
    0.60, 0.57, 0.55, 0.53, 0.55, 0.60,   # 00-05h: nighttime
    0.68, 0.78, 0.87, 0.93, 0.97, 1.00,   # 06-11h: morning ramp
    0.99, 0.98, 0.96, 0.93, 0.90, 0.86,   # 12-17h: afternoon
    0.82, 0.78, 0.74, 0.70, 0.66, 0.63,   # 18-23h: evening
])

# Fuel type cost mapping (yen/MWh)
FUEL_COST = {
    "coal": 4500, "gas": 7000, "lng": 7000, "oil": 9000,
    "nuclear": 1500, "hydro": 0, "pumped_hydro": 0,
    "wind": 0, "solar": 0, "biomass": 3000, "geothermal": 0,
    "waste": 5000, "battery": 0,
}

# Normalize OSM fuel types to model fuel types
FUEL_MAP = {
    "coal": "coal", "gas": "lng", "lng": "lng", "oil": "oil",
    "nuclear": "nuclear", "hydro": "hydro", "wind": "wind",
    "solar": "solar", "biomass": "biomass", "geothermal": "geothermal",
    "waste": "biomass", "battery": "pumped_hydro",
}

FUEL_ORDER = [
    "nuclear", "coal", "lng", "oil", "hydro", "pumped_hydro",
    "geothermal", "biomass", "wind", "solar", "mixed", "unknown",
]

# ── Known Pumped-Storage Hydro Plants (主要揚水発電所) ─────────────────────────
# MWh estimated as ~5h discharge at rated capacity where public data unavailable
PUMPED_STORAGE_PLANTS = {
    "京極発電所": 4000,          # 北海道電力, 400 MW
    "沼原発電所": 2700,          # 電源開発, 675 MW
    "塩原発電所": 4500,          # 東京電力, 900 MW
    "今市発電所": 5250,          # 東京電力, 1050 MW
    "玉原発電所": 6000,          # 東京電力, 1200 MW
    "城山水力発電所": 1250,      # 東京電力, 250 MW
    "神流川水力発電所": 6580,    # 東京電力, 940 MW (世界最大級の落差)
    "葛野川地下発電所": 8000,    # 東京電力, 1600 MW
    "奥清津発電所": 8000,        # 電源開発, 1600 MW
    "安曇水力発電所": 3115,      # 東京電力, 623 MW
    "水殿水力発電所": 1225,      # 東京電力, 245 MW
    "長野水力発電所": 1100,      # 東京電力, 220 MW
    "奥吉野発電所": 6030,        # 関西電力, 1206 MW
    "喜撰山発電所": 2330,        # 関西電力, 466 MW
    "大平水力発電所": 2500,      # 九州電力, 500 MW
    "天山水力発電所": 3000,      # 九州電力, 600 MW
    "小丸川水力発電所": 6000,    # 九州電力, 1200 MW
}

# Battery storage (蓄電池) — capacity in MWh
BATTERY_PLANTS = {
    "西仙台変電所周波数変動対策蓄電池システム実証事業": 40,   # 東北電力, 40 MW x 1h
    "豊前蓄電池変電所": 302,                              # 九州電力, 50.4 MW x 6h
}


# ── Data Loading ──────────────────────────────────────────────────────────────

def load_generators():
    """Load all generators from regional GeoJSON files with storage detection."""
    proj_root = os.path.join(os.path.dirname(__file__), "..")
    generators = []

    for region in REGIONS:
        path = os.path.join(proj_root, "data", f"{region}_plants.geojson")
        if not os.path.exists(path):
            continue
        with open(path) as f:
            data = json.load(f)

        for i, feat in enumerate(data["features"]):
            props = feat["properties"]
            cap = props.get("capacity_mw")
            if not cap or float(cap) < MIN_CAPACITY_MW:
                continue

            cap = float(cap)
            name = props.get("name") or props.get("_display_name") or f"{region}_gen_{i}"
            raw_fuel = (props.get("fuel_type") or props.get("plant:source") or "unknown").lower()
            fuel = FUEL_MAP.get(raw_fuel, "mixed")
            cost = FUEL_COST.get(raw_fuel, 5000)
            osm_id = props.get("osm_id", i)

            # Detect storage type
            is_pumped = name in PUMPED_STORAGE_PLANTS
            is_battery = name in BATTERY_PLANTS
            if is_pumped:
                fuel = "pumped_hydro"
                cost = FUEL_COST["pumped_hydro"]
            if is_battery:
                fuel = "pumped_hydro"
                cost = 0

            is_renewable = fuel in ("hydro", "pumped_hydro", "wind", "solar", "geothermal")

            # Storage parameters
            storage_kwds = {}
            if is_pumped:
                storage_kwds = dict(
                    storage_capacity_mwh=PUMPED_STORAGE_PLANTS[name],
                    charge_rate_mw=cap,
                    discharge_rate_mw=cap,
                    charge_efficiency=0.85,
                    discharge_efficiency=0.90,
                    initial_soc_fraction=0.5,
                )
            elif is_battery:
                storage_kwds = dict(
                    storage_capacity_mwh=BATTERY_PLANTS[name],
                    charge_rate_mw=cap,
                    discharge_rate_mw=cap,
                    charge_efficiency=0.92,
                    discharge_efficiency=0.95,
                    initial_soc_fraction=0.5,
                )

            gen = Generator(
                id=f"{region}_gen_{osm_id}",
                name=name,
                capacity_mw=cap,
                fuel_type=fuel,
                region=region,
                startup_cost=0 if is_renewable else 5000,
                shutdown_cost=0 if is_renewable else 2000,
                min_up_time_h=4 if fuel in ("coal", "nuclear") else 2,
                min_down_time_h=4 if fuel in ("coal", "nuclear") else 2,
                fuel_cost_per_mwh=cost,
                no_load_cost=0 if fuel in ("wind", "solar") else 500,
                labor_cost_per_h=300,
                **storage_kwds,
            )
            generators.append(gen)

    return generators


# ── Report Sections ───────────────────────────────────────────────────────────

def print_fleet_summary(generators):
    """Print fleet summary by fuel type and region."""
    print("=" * 80)
    print("  1. FLEET SUMMARY (発電機フリート)")
    print("=" * 80)

    # By fuel type
    fuel_counts = Counter(g.fuel_type for g in generators)
    fuel_caps = {}
    for g in generators:
        fuel_caps[g.fuel_type] = fuel_caps.get(g.fuel_type, 0) + g.capacity_mw

    print(f"\n  {'Fuel Type':<16} {'Count':>6} {'Capacity (MW)':>14} {'Share':>7}")
    print("  " + "-" * 46)
    total_cap = sum(g.capacity_mw for g in generators)
    for ft in FUEL_ORDER:
        if ft not in fuel_counts:
            continue
        pct = fuel_caps[ft] / total_cap * 100
        print(f"  {ft:<16} {fuel_counts[ft]:>6} {fuel_caps[ft]:>14,.0f} {pct:>6.1f}%")
    print(f"  {'TOTAL':<16} {len(generators):>6} {total_cap:>14,.0f} {100.0:>6.1f}%")

    # By region
    region_counts = Counter(g.region for g in generators)
    print(f"\n  {'Region':<16} {'Count':>6} {'Capacity (MW)':>14}")
    print("  " + "-" * 38)
    for region in REGIONS:
        if region not in region_counts:
            continue
        cap = sum(g.capacity_mw for g in generators if g.region == region)
        print(f"  {region:<16} {region_counts[region]:>6} {cap:>14,.0f}")

    # Storage summary
    storage = [g for g in generators if g.is_storage]
    print(f"\n  Storage units: {len(storage)}")
    print(f"    Pumped hydro: {sum(1 for g in storage if g.name in PUMPED_STORAGE_PLANTS)} "
          f"({sum(g.capacity_mw for g in storage if g.name in PUMPED_STORAGE_PLANTS):,.0f} MW / "
          f"{sum(g.storage_capacity_mwh for g in storage if g.name in PUMPED_STORAGE_PLANTS):,.0f} MWh)")
    print(f"    Battery:      {sum(1 for g in storage if g.name in BATTERY_PLANTS)} "
          f"({sum(g.capacity_mw for g in storage if g.name in BATTERY_PLANTS):,.0f} MW / "
          f"{sum(g.storage_capacity_mwh for g in storage if g.name in BATTERY_PLANTS):,.0f} MWh)")


def print_solver_report(adaptive_result, demands):
    """Print solver status and cost breakdown."""
    r = adaptive_result.result
    print("\n" + "=" * 80)
    print("  2. SOLVER RESULT (最適化結果)")
    print("=" * 80)

    print(f"\n  Status:           {r.status}")
    print(f"  Total Cost:       ¥{r.total_cost:>16,.0f}")
    print(f"  Solve Time:       {adaptive_result.total_time_s:.1f}s")
    print(f"  Solver Tier:      {adaptive_result.tier_used.value.upper()}")
    print(f"  Solver Backend:   {adaptive_result.solver_config.solver_name}")
    print(f"  MIP Gap:          {adaptive_result.solver_config.mip_gap * 100:.0f}%")
    print(f"  LP Relaxation:    {'Yes' if adaptive_result.solver_config.use_lp_relaxation else 'No'}")
    print(f"  Peak Demand:      {max(demands):>16,.0f} MW")
    print(f"  Total Energy:     {sum(demands):>16,.0f} MWh")

    # Cost breakdown from schedule-level costs
    total_fuel = sum(s.fuel_cost for s in r.schedules)
    total_noload = sum(s.no_load_cost for s in r.schedules)
    total_startup = sum(s.startup_cost for s in r.schedules)
    total_shutdown = sum(s.shutdown_cost for s in r.schedules)
    total = r.total_cost or 1
    print(f"\n  Cost Breakdown:")
    print(f"    Fuel cost:      ¥{total_fuel:>16,.0f}  ({total_fuel/total*100:.1f}%)")
    print(f"    No-load cost:   ¥{total_noload:>16,.0f}  ({total_noload/total*100:.1f}%)")
    print(f"    Startup cost:   ¥{total_startup:>16,.0f}  ({total_startup/total*100:.1f}%)")
    print(f"    Shutdown cost:  ¥{total_shutdown:>16,.0f}  ({total_shutdown/total*100:.1f}%)")


def print_storage_soc(adaptive_result, generators):
    """Print SOC profiles for all storage units."""
    r = adaptive_result.result
    storage = [g for g in generators if g.is_storage]
    if not storage:
        return

    print("\n" + "=" * 80)
    print("  3. STORAGE SOC PROFILES (蓄電・揚水 充放電状況)")
    print("=" * 80)

    # Summary table
    print(f"\n  {'Name':<24} {'MW':>6} {'MWh':>6} {'SOC_0':>7} {'min':>7} {'max':>7} "
          f"{'SOC_23':>7} {'Chg':>7} {'Dis':>7} {'Cycles':>7}")
    print("  " + "-" * 96)

    for g in storage:
        sched = next((s for s in r.schedules if s.generator_id == g.id), None)
        if not sched or not sched.soc_mwh:
            print(f"  {g.name:<24} {g.capacity_mw:>6.0f} {g.storage_capacity_mwh:>6.0f}  (no SOC data)")
            continue
        soc = sched.soc_mwh
        chg = sum(sched.charge_mw) if sched.charge_mw else 0
        dis = sum(sched.discharge_mw) if sched.discharge_mw else 0
        cap_mwh = g.storage_capacity_mwh
        cycles = dis / cap_mwh if cap_mwh > 0 else 0
        print(f"  {g.name:<24} {g.capacity_mw:>6.0f} {cap_mwh:>6.0f} {soc[0]:>7.0f} "
              f"{min(soc):>7.0f} {max(soc):>7.0f} {soc[-1]:>7.0f} {chg:>7.0f} {dis:>7.0f} "
              f"{cycles:>7.2f}")

    total_chg = 0
    total_dis = 0
    for g in storage:
        sched = next((s for s in r.schedules if s.generator_id == g.id), None)
        if sched and sched.charge_mw:
            total_chg += sum(sched.charge_mw)
        if sched and sched.discharge_mw:
            total_dis += sum(sched.discharge_mw)
    print(f"\n  Total charge:    {total_chg:>10,.0f} MWh")
    print(f"  Total discharge: {total_dis:>10,.0f} MWh")
    print(f"  Round-trip loss:  {total_chg - total_dis:>10,.0f} MWh")

    # Detailed hourly SOC for top 5 largest storage units
    top5 = sorted(storage, key=lambda g: g.storage_capacity_mwh, reverse=True)[:5]
    print(f"\n  Hourly SOC (%) — Top 5 largest storage units:")
    print(f"  {'Hour':>6}", end="")
    for g in top5:
        label = g.name[:12]
        print(f"  {label:>12}", end="")
    print()
    print("  " + "-" * (6 + 14 * len(top5)))

    for t in range(NUM_PERIODS):
        print(f"  {t:>4}h ", end="")
        for g in top5:
            sched = next((s for s in r.schedules if s.generator_id == g.id), None)
            if sched and sched.soc_mwh:
                pct = sched.soc_mwh[t] / g.storage_capacity_mwh * 100
                print(f"  {pct:>11.1f}%", end="")
            else:
                print(f"  {'---':>12}", end="")
        print()


def print_dispatch_by_fuel(adaptive_result, generators, demands):
    """Print hourly dispatch summary grouped by fuel type."""
    r = adaptive_result.result

    print("\n" + "=" * 80)
    print("  4. HOURLY DISPATCH BY FUEL TYPE (燃料種別 時間別出力)")
    print("=" * 80)

    gen_map = {g.id: g for g in generators}
    fuels_used = sorted(
        {gen_map[s.generator_id].fuel_type for s in r.schedules if s.generator_id in gen_map},
        key=lambda f: FUEL_ORDER.index(f) if f in FUEL_ORDER else 99,
    )

    # Compute hourly output by fuel
    hourly = {ft: [0.0] * NUM_PERIODS for ft in fuels_used}
    for sched in r.schedules:
        g = gen_map.get(sched.generator_id)
        if not g:
            continue
        for t in range(min(NUM_PERIODS, len(sched.power_output_mw))):
            hourly[g.fuel_type][t] += sched.power_output_mw[t]

    # Print compact table
    header_fuels = [f[:8] for f in fuels_used]
    print(f"\n  {'Hour':>6} {'Demand':>10}", end="")
    for hf in header_fuels:
        print(f" {hf:>10}", end="")
    print(f" {'Total':>10} {'Bal':>7}")
    print("  " + "-" * (28 + 11 * len(fuels_used)))

    for t in range(NUM_PERIODS):
        total_gen = sum(hourly[ft][t] for ft in fuels_used)
        bal = total_gen - demands[t]
        print(f"  {t:>4}h  {demands[t]:>10,.0f}", end="")
        for ft in fuels_used:
            print(f" {hourly[ft][t]:>10,.0f}", end="")
        print(f" {total_gen:>10,.0f} {bal:>+7.0f}")


# ── Visualization ─────────────────────────────────────────────────────────────

FUEL_COLORS = {
    "nuclear": "#7B2D8E", "coal": "#4A4A4A", "lng": "#E8832A", "oil": "#C44E52",
    "hydro": "#2196F3", "pumped_hydro": "#1565C0", "geothermal": "#FF5722",
    "biomass": "#8BC34A", "wind": "#4CAF50", "solar": "#FFD700",
    "mixed": "#9E9E9E", "unknown": "#BDBDBD",
}

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output", "uc_national")


def plot_national_dispatch_stack(adaptive_result, generators, demands, output_path):
    """Fig 1: National dispatch stack by fuel type (757 generators)."""
    r = adaptive_result.result
    gen_map = {g.id: g for g in generators}
    hours = np.arange(NUM_PERIODS)

    stacks = {ft: np.zeros(NUM_PERIODS) for ft in FUEL_ORDER}
    for sched in r.schedules:
        g = gen_map.get(sched.generator_id)
        if not g:
            continue
        ft = g.fuel_type
        if ft not in stacks:
            stacks[ft] = np.zeros(NUM_PERIODS)
        power = np.array(sched.power_output_mw[:NUM_PERIODS])
        # For storage, separate charge (negative) and discharge (positive)
        if g.is_storage and sched.charge_mw:
            charge = np.array(sched.charge_mw[:NUM_PERIODS])
            power = power - charge  # net output (can be negative)
        stacks[ft] += power

    fig, ax = plt.subplots(figsize=(16, 8))

    # Split into positive (generation) and negative (charging) stacks
    pos_fuels = [ft for ft in FUEL_ORDER if ft in stacks and np.any(stacks[ft] > 0)]
    neg_fuels = [ft for ft in FUEL_ORDER if ft in stacks and np.any(stacks[ft] < 0)]

    bottoms_pos = np.zeros(NUM_PERIODS)
    for ft in pos_fuels:
        vals = np.maximum(stacks[ft], 0)
        if vals.sum() > 0:
            ax.fill_between(hours, bottoms_pos, bottoms_pos + vals,
                            label=ft, color=FUEL_COLORS.get(ft, "#999"),
                            alpha=0.85, linewidth=0.5, edgecolor="white")
            bottoms_pos += vals

    # Negative (charging) below zero
    bottoms_neg = np.zeros(NUM_PERIODS)
    for ft in neg_fuels:
        vals = np.minimum(stacks[ft], 0)
        if vals.sum() < 0:
            ax.fill_between(hours, bottoms_neg + vals, bottoms_neg,
                            label=f"{ft} (charge)" if ft == "pumped_hydro" else ft,
                            color=FUEL_COLORS.get(ft, "#999"), alpha=0.4,
                            linewidth=0.5, edgecolor="white", hatch="//")
            bottoms_neg += vals

    ax.plot(hours, demands, "k-", linewidth=2.5, label="Demand", zorder=5)
    ax.plot(hours, demands, "ko", markersize=3, zorder=5)

    ax.set_xlim(0, 23)
    ax.set_xlabel("Hour of Day / 時刻", fontsize=13)
    ax.set_ylabel("Power Output (MW) / 出力", fontsize=13)
    ax.set_title(f"All-Japan 24h Dispatch — {len(generators)} Generators, "
                 f"Peak {max(demands):,.0f} MW\n"
                 f"全日本 起動停止計画 — 燃料種別スタック図",
                 fontsize=14, fontweight="bold")
    ax.legend(loc="upper left", fontsize=9, ncol=3, framealpha=0.9)
    ax.set_xticks(hours)
    ax.grid(axis="y", alpha=0.3)
    ax.axhline(0, color="black", linewidth=0.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {output_path}")


def plot_fleet_capacity_pie(generators, output_path):
    """Fig 2: Fleet capacity breakdown by fuel type."""
    fuel_caps = {}
    for g in generators:
        fuel_caps[g.fuel_type] = fuel_caps.get(g.fuel_type, 0) + g.capacity_mw

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))

    # Pie chart by capacity
    labels, sizes, colors = [], [], []
    for ft in FUEL_ORDER:
        if ft in fuel_caps and fuel_caps[ft] > 0:
            labels.append(f"{ft}\n{fuel_caps[ft]:,.0f} MW")
            sizes.append(fuel_caps[ft])
            colors.append(FUEL_COLORS.get(ft, "#999"))

    wedges, texts, autotexts = ax1.pie(
        sizes, labels=labels, colors=colors, autopct="%1.1f%%",
        startangle=90, textprops={"fontsize": 8}, pctdistance=0.8)
    ax1.set_title(f"Installed Capacity by Fuel Type\n設備容量 燃料種別構成 "
                  f"({sum(fuel_caps.values()):,.0f} MW total)",
                  fontsize=13, fontweight="bold")

    # Bar chart by region
    region_caps = {}
    region_fuel = {}
    for g in generators:
        region_caps[g.region] = region_caps.get(g.region, 0) + g.capacity_mw
        key = (g.region, g.fuel_type)
        region_fuel[key] = region_fuel.get(key, 0) + g.capacity_mw

    regions_sorted = [r for r in REGIONS if r in region_caps]
    x = np.arange(len(regions_sorted))
    bottoms = np.zeros(len(regions_sorted))

    for ft in FUEL_ORDER:
        vals = [region_fuel.get((r, ft), 0) for r in regions_sorted]
        if sum(vals) > 0:
            ax2.bar(x, vals, bottom=bottoms, label=ft,
                    color=FUEL_COLORS.get(ft, "#999"), alpha=0.85, edgecolor="white", linewidth=0.5)
            bottoms += np.array(vals)

    REGION_JA = {
        "hokkaido": "北海道", "tohoku": "東北", "tokyo": "東京",
        "chubu": "中部", "hokuriku": "北陸", "kansai": "関西",
        "chugoku": "中国", "shikoku": "四国", "kyushu": "九州", "okinawa": "沖縄",
    }
    ax2.set_xticks(x)
    ax2.set_xticklabels([f"{REGION_JA.get(r, r)}\n{r}" for r in regions_sorted], fontsize=8)
    ax2.set_ylabel("Capacity (MW)")
    ax2.set_title("Capacity by Region & Fuel Type\n地域別・燃料別 設備容量",
                   fontsize=13, fontweight="bold")
    ax2.legend(fontsize=7, ncol=2, loc="upper right")
    ax2.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {output_path}")


def plot_storage_soc_chart(adaptive_result, generators, output_path):
    """Fig 3: Storage SOC profiles for top units."""
    r = adaptive_result.result
    storage = [g for g in generators if g.is_storage]
    top_units = sorted(storage, key=lambda g: g.storage_capacity_mwh, reverse=True)[:8]

    fig, axes = plt.subplots(2, 1, figsize=(16, 10))
    hours = np.arange(NUM_PERIODS)

    # Panel 1: SOC %
    ax = axes[0]
    for g in top_units:
        sched = next((s for s in r.schedules if s.generator_id == g.id), None)
        if not sched or not sched.soc_mwh:
            continue
        soc_pct = [s / g.storage_capacity_mwh * 100 for s in sched.soc_mwh[:NUM_PERIODS]]
        ax.plot(hours, soc_pct, "o-", markersize=3, linewidth=1.5,
                label=f"{g.name} ({g.capacity_mw:.0f}MW/{g.storage_capacity_mwh:.0f}MWh)")

    ax.set_xlim(0, 23)
    ax.set_ylim(0, 105)
    ax.set_xlabel("Hour of Day / 時刻")
    ax.set_ylabel("SOC (%)")
    ax.set_title("Storage SOC Profiles — Top 8 Units\n蓄電・揚水 充電状態推移（上位8ユニット）",
                  fontsize=13, fontweight="bold")
    ax.legend(fontsize=7, ncol=2, loc="lower left")
    ax.set_xticks(hours)
    ax.grid(alpha=0.3)
    ax.axhline(50, color="gray", linestyle="--", alpha=0.4, linewidth=0.8)

    # Panel 2: Charge/Discharge power
    ax = axes[1]
    for g in top_units:
        sched = next((s for s in r.schedules if s.generator_id == g.id), None)
        if not sched:
            continue
        discharge = np.array(sched.discharge_mw[:NUM_PERIODS]) if sched.discharge_mw else np.zeros(NUM_PERIODS)
        charge = np.array(sched.charge_mw[:NUM_PERIODS]) if sched.charge_mw else np.zeros(NUM_PERIODS)
        net = discharge - charge
        ax.plot(hours, net, "o-", markersize=3, linewidth=1.5,
                label=f"{g.name}")

    ax.set_xlim(0, 23)
    ax.set_xlabel("Hour of Day / 時刻")
    ax.set_ylabel("Net Power (MW) — positive=discharge, negative=charge")
    ax.set_title("Storage Charge/Discharge Power\n充放電出力（正=放電, 負=充電）",
                  fontsize=13, fontweight="bold")
    ax.legend(fontsize=7, ncol=2, loc="upper right")
    ax.set_xticks(hours)
    ax.grid(alpha=0.3)
    ax.axhline(0, color="black", linewidth=0.8)

    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {output_path}")


def plot_national_summary(adaptive_result, generators, demands, output_path):
    """Fig 4: National UC summary dashboard."""
    r = adaptive_result.result
    gen_map = {g.id: g for g in generators}
    hours = np.arange(NUM_PERIODS)

    fig, axes = plt.subplots(2, 2, figsize=(18, 13))

    # (a) Supply vs Demand
    ax = axes[0, 0]
    total_supply = np.zeros(NUM_PERIODS)
    committed_cap = np.zeros(NUM_PERIODS)
    for sched in r.schedules:
        g = gen_map.get(sched.generator_id)
        if not g:
            continue
        total_supply += np.array(sched.power_output_mw[:NUM_PERIODS])
        committed_cap += np.array(sched.commitment[:NUM_PERIODS]) * g.capacity_mw

    ax.fill_between(hours, committed_cap, alpha=0.15, color="#2196F3", label="Committed Capacity")
    ax.plot(hours, total_supply, "b-", linewidth=2, label="Total Supply")
    ax.plot(hours, demands, "r--", linewidth=2, label="Demand")
    reserve = np.array(demands) * (1 + RESERVE_MARGIN)
    ax.plot(hours, reserve, "g:", linewidth=1.5, label=f"Demand + {RESERVE_MARGIN*100:.0f}% Reserve")
    ax.set_xlabel("Hour"); ax.set_ylabel("MW")
    ax.set_title("(a) Demand vs Supply & Reserve / 需給バランス", fontweight="bold")
    ax.legend(fontsize=8); ax.grid(alpha=0.3); ax.set_xticks(hours)

    # (b) Cost breakdown pie
    ax = axes[0, 1]
    total_fuel = sum(s.fuel_cost for s in r.schedules)
    total_noload = sum(s.no_load_cost for s in r.schedules)
    total_startup = sum(s.startup_cost for s in r.schedules)
    total_shutdown = sum(s.shutdown_cost for s in r.schedules)

    pie_data = [(lbl, val, col) for lbl, val, col in [
        ("Fuel / 燃料費", total_fuel, "#E8832A"),
        ("No-Load / 無負荷費", total_noload, "#2196F3"),
        ("Startup / 起動費", total_startup, "#C44E52"),
        ("Shutdown / 停止費", total_shutdown, "#9C27B0"),
    ] if val > 0]

    if pie_data:
        labels_p, sizes_p, colors_p = zip(*pie_data)
        ax.pie(sizes_p, labels=labels_p, colors=colors_p, autopct="%1.1f%%",
               startangle=90, textprops={"fontsize": 9})
    ax.set_title(f"(b) Total Cost: ¥{r.total_cost:,.0f}\n総コスト内訳", fontweight="bold")

    # (c) Generation mix over time (stacked bars)
    ax = axes[1, 0]
    hourly = {ft: np.zeros(NUM_PERIODS) for ft in FUEL_ORDER}
    for sched in r.schedules:
        g = gen_map.get(sched.generator_id)
        if not g:
            continue
        power = np.array(sched.power_output_mw[:NUM_PERIODS])
        ft = g.fuel_type
        if ft not in hourly:
            hourly[ft] = np.zeros(NUM_PERIODS)
        hourly[ft] += np.maximum(power, 0)

    bottoms = np.zeros(NUM_PERIODS)
    for ft in FUEL_ORDER:
        if ft in hourly and hourly[ft].sum() > 0:
            ax.bar(hours, hourly[ft], bottom=bottoms, width=0.8,
                   label=ft, color=FUEL_COLORS.get(ft, "#999"), alpha=0.85,
                   edgecolor="white", linewidth=0.3)
            bottoms += hourly[ft]

    ax.plot(hours, demands, "k-", linewidth=2, label="Demand", zorder=5)
    ax.set_xlabel("Hour"); ax.set_ylabel("MW")
    ax.set_title("(c) Hourly Generation Mix / 時間別電源構成", fontweight="bold")
    ax.legend(fontsize=6, ncol=3, loc="upper right"); ax.grid(axis="y", alpha=0.3)
    ax.set_xticks(hours)

    # (d) Statistics table
    ax = axes[1, 1]
    ax.axis("off")

    total_energy = sum(s.total_energy_mwh for s in r.schedules)
    total_demand_mwh = sum(demands)
    avg_cost = r.total_cost / total_energy if total_energy > 0 else 0
    total_cap = sum(g.capacity_mw for g in generators)
    n_storage = sum(1 for g in generators if g.is_storage)

    stats = [
        ["Metric / 指標", "Value / 値"],
        ["Solver Status", r.status],
        ["Solve Time", f"{adaptive_result.total_time_s:.1f} s"],
        ["Solver Tier", adaptive_result.tier_used.value.upper()],
        ["Total Cost / 総コスト", f"¥{r.total_cost:,.0f}"],
        ["Total Energy / 総発電量", f"{total_energy:,.0f} MWh"],
        ["Total Demand / 総需要", f"{total_demand_mwh:,.0f} MWh"],
        ["Avg. Cost/MWh / 平均単価", f"¥{avg_cost:,.0f}/MWh"],
        ["Peak Demand / ピーク需要", f"{max(demands):,.0f} MW"],
        ["Installed Cap. / 設備容量", f"{total_cap:,.0f} MW"],
        ["Fleet Size / 発電機数", f"{len(generators)}"],
        ["Storage Units / 蓄電ユニット", f"{n_storage}"],
        ["Reserve Margin / 予備率", f"{RESERVE_MARGIN*100:.0f}%"],
    ]

    table = ax.table(cellText=stats[1:], colLabels=stats[0],
                     cellLoc="left", loc="center", colWidths=[0.50, 0.40])
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.4)
    for j in range(2):
        table[0, j].set_facecolor("#333")
        table[0, j].set_text_props(color="white", fontweight="bold")
    for i in range(1, len(stats)):
        for j in range(2):
            if i % 2 == 0:
                table[i, j].set_facecolor("#f0f0f0")

    ax.set_title("(d) UC Result Summary / 結果サマリ", fontweight="bold", y=0.98)

    fig.suptitle(f"All-Japan Unit Commitment — {len(generators)} Generators + "
                 f"{n_storage} Storage\n全日本 起動停止計画 結果ダッシュボード",
                 fontsize=15, fontweight="bold", y=1.01)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {output_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    wall_start = _time.monotonic()

    print()
    print("=" * 80)
    print("  ALL-JAPAN UNIT COMMITMENT — 757 Generators + Storage Report")
    print("  全日本 起動停止計画 — 蓄電池・揚水発電所付き レポート")
    print("=" * 80)

    # ── Step 1: Load generators ───────────────────────────────────────────
    print("\n  Loading generators from GeoJSON...")
    generators = load_generators()
    total_cap = sum(g.capacity_mw for g in generators)
    storage = [g for g in generators if g.is_storage]
    print(f"  -> {len(generators)} generators, {len(storage)} storage units, "
          f"{total_cap:,.0f} MW total capacity")

    print_fleet_summary(generators)

    # ── Step 2: Create demand ─────────────────────────────────────────────
    demands = (DEMAND_SHAPE * total_cap * DEMAND_FACTOR).tolist()

    # ── Step 3: Solve UC ──────────────────────────────────────────────────
    print("\n  Solving UC (adaptive solver, full MILP)...")
    params = UCParameters(
        generators=generators,
        demand=DemandProfile(demands=demands),
        time_horizon=TimeHorizon(num_periods=NUM_PERIODS, period_duration_h=1.0),
        reserve_margin=RESERVE_MARGIN,
        solver_time_limit_s=600,
        mip_gap=0.01,
    )

    result = solve_adaptive(params, force_tier=SolverTier.HIGH, verbose=False)

    if not result.result.is_optimal:
        print(f"\n  WARNING: Solver returned {result.result.status}")
        for w in result.result.warnings[:5]:
            print(f"    {w}")

    # ── Step 4: Print text report ─────────────────────────────────────────
    print_solver_report(result, demands)
    print_storage_soc(result, generators)
    print_dispatch_by_fuel(result, generators, demands)

    # ── Step 5: Generate visualizations ───────────────────────────────────
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("\n  Generating visualizations...")

    plot_national_dispatch_stack(result, generators, demands,
                                 os.path.join(OUTPUT_DIR, "national_dispatch_stack.png"))
    plot_fleet_capacity_pie(generators,
                            os.path.join(OUTPUT_DIR, "national_fleet_capacity.png"))
    plot_storage_soc_chart(result, generators,
                           os.path.join(OUTPUT_DIR, "national_storage_soc.png"))
    plot_national_summary(result, generators, demands,
                          os.path.join(OUTPUT_DIR, "national_summary_dashboard.png"))

    # ── Summary ───────────────────────────────────────────────────────────
    wall_elapsed = _time.monotonic() - wall_start
    print("\n" + "=" * 80)
    print(f"  REPORT COMPLETE")
    print(f"  {len(generators)} generators | {len(storage)} storage | "
          f"¥{result.result.total_cost:,.0f} | {wall_elapsed:.1f}s total")
    print(f"  Figures saved to: {os.path.abspath(OUTPUT_DIR)}")
    print("=" * 80)


if __name__ == "__main__":
    main()
