#!/usr/bin/env python3
"""Adaptive solver demo: tier selection, LP relaxation, and fallback behavior.

Demonstrates the adaptive UC solver's behavior across three scenarios:

1. **Normal solve** — Auto-detects hardware and selects the appropriate tier
   (HIGH/MID/LOW). Runs a 24-hour unit commitment on a small fleet.
2. **Forced LOW tier** — Simulates a low-resource environment by forcing the
   LOW tier.  Uses LP relaxation (binary variables relaxed to [0,1]) and
   rounds fractional commitments in post-processing.
3. **Tier comparison** — Solves the same problem at all three tiers and
   compares cost, solve time, and solution quality side by side.

This example focuses on the *solver intelligence layer* — hardware detection,
tier selection logic, and graceful degradation — rather than advanced
generator modelling (see ``uc_advanced_demo.py`` for storage/ramp demos).

Usage::

    python examples/uc_adaptive_solver_demo.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.model.generator import Generator
from src.uc.models import UCParameters, TimeHorizon, DemandProfile
from src.uc.adaptive_solver import AdaptiveUCResult, solve_adaptive
from src.uc.hardware_detector import HardwareProfile, detect_hardware
from src.uc.solver_strategy import SolverTier, SolverConfig, select_strategy

# ── Constants ─────────────────────────────────────────────────────
NUM_PERIODS = 24
RESERVE_MARGIN = 0.05


# ── Generator fleet ──────────────────────────────────────────────


def make_generators():
    """Create a compact 6-generator fleet for tier comparison demos.

    Includes a mix of fuel types (nuclear, coal, LNG, oil, hydro)
    with representative cost and constraint parameters.
    """
    gens = [
        Generator(
            id="tokyo_nuc_01", name="柏崎刈羽原発", capacity_mw=1100,
            fuel_type="nuclear", region="tokyo",
            startup_cost=50000, shutdown_cost=20000,
            min_up_time_h=12, min_down_time_h=12,
            fuel_cost_per_mwh=1500, no_load_cost=800, labor_cost_per_h=500,
        ),
        Generator(
            id="tokyo_coal_01", name="磯子火力(石炭)", capacity_mw=600,
            fuel_type="coal", region="tokyo",
            startup_cost=8000, shutdown_cost=3000,
            min_up_time_h=6, min_down_time_h=4,
            ramp_up_mw_per_h=120, ramp_down_mw_per_h=120,
            fuel_cost_per_mwh=4500, no_load_cost=600, labor_cost_per_h=400,
        ),
        Generator(
            id="tokyo_lng_01", name="富津LNG-1", capacity_mw=500,
            fuel_type="lng", region="tokyo",
            startup_cost=5000, shutdown_cost=2000,
            min_up_time_h=3, min_down_time_h=2,
            ramp_up_mw_per_h=200, ramp_down_mw_per_h=200,
            fuel_cost_per_mwh=7000, no_load_cost=400, labor_cost_per_h=300,
        ),
        Generator(
            id="chubu_coal_01", name="碧南火力(石炭)", capacity_mw=700,
            fuel_type="coal", region="chubu",
            startup_cost=9000, shutdown_cost=3500,
            min_up_time_h=6, min_down_time_h=4,
            ramp_up_mw_per_h=140, ramp_down_mw_per_h=140,
            fuel_cost_per_mwh=4200, no_load_cost=650, labor_cost_per_h=400,
        ),
        Generator(
            id="chubu_hydro_01", name="奥矢作水力", capacity_mw=200,
            fuel_type="hydro", region="chubu",
            startup_cost=500, shutdown_cost=200,
            min_up_time_h=1, min_down_time_h=1,
            ramp_up_mw_per_h=200, ramp_down_mw_per_h=200,
            fuel_cost_per_mwh=0, no_load_cost=100, labor_cost_per_h=100,
        ),
        Generator(
            id="chubu_oil_01", name="知多石油火力", capacity_mw=350,
            fuel_type="oil", region="chubu",
            startup_cost=3000, shutdown_cost=1500,
            min_up_time_h=2, min_down_time_h=2,
            ramp_up_mw_per_h=250, ramp_down_mw_per_h=250,
            fuel_cost_per_mwh=9000, no_load_cost=300, labor_cost_per_h=200,
        ),
    ]
    return gens


def make_demand_profile():
    """Create a 24-hour demand curve scaled for the 6-generator fleet.

    Total fleet capacity is ~3,450 MW. Peak demand at ~70% utilization.
    """
    demand = [
        1600, 1500, 1450, 1400, 1450, 1600,   # 0-5h:  nighttime low
        1900, 2200, 2400, 2550, 2650, 2700,   # 6-11h: morning ramp
        2700, 2650, 2600, 2500, 2400, 2300,   # 12-17h: afternoon
        2200, 2100, 2000, 1900, 1800, 1700,   # 18-23h: evening decline
    ]
    return demand


# ── Display helpers ──────────────────────────────────────────────


def print_section(title):
    """Print a section header."""
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_hardware_profile(profile):
    """Print detected hardware capabilities."""
    print_section("HARDWARE PROFILE")
    print(f"  OS / Architecture:     {profile.os_name} / {profile.architecture}")
    print(f"  Physical CPU cores:    {profile.physical_cores}")
    print(f"  Logical CPU cores:     {profile.logical_cores}")
    print(f"  Available RAM:         {profile.available_ram_gb:.1f} GB")
    print(f"  Total RAM:             {profile.total_ram_gb:.1f} GB")
    print(f"  Available solvers:     {', '.join(profile.available_solvers) or 'none detected'}")


def print_tier_selection(profile, n_generators, n_periods):
    """Show how the strategy selector maps hardware to a tier."""
    config = select_strategy(profile, n_generators, n_periods)
    print()
    print(f"  Strategy selector output for {n_generators} generators, "
          f"{n_periods} periods:")
    print(f"    Tier:                {config.tier.value.upper()}")
    print(f"    Solver:              {config.solver_name}")
    print(f"    MIP Gap:             {config.mip_gap:.0%}")
    print(f"    Time Limit:          {config.time_limit_s:.0f}s")
    print(f"    Threads:             {config.threads}")
    print(f"    LP Relaxation:       {'Yes' if config.use_lp_relaxation else 'No'}")
    print(f"    Decomposition:       {'Yes (' + config.decomposition_strategy + ')' if config.use_decomposition else 'No'}")
    print(f"    Description:         {config.description}")
    return config


def print_solve_result(label, adaptive_result):
    """Print a compact summary of a solve result."""
    result = adaptive_result.result
    config = adaptive_result.solver_config

    print()
    print(f"  [{label}]")
    print(f"    Tier used:           {adaptive_result.tier_used.value.upper()}")
    print(f"    Solver status:       {result.status}")
    print(f"    Total cost:          ¥{result.total_cost:,.0f}")
    print(f"    Solve time:          {result.solve_time_s:.2f}s")
    print(f"    Adaptive time:       {adaptive_result.total_time_s:.2f}s")
    print(f"    Generators used:     {result.num_generators}")
    if result.gap is not None:
        print(f"    MIP Gap:             {result.gap:.4%}")
    print(f"    LP Relaxation:       {'Yes' if config and config.use_lp_relaxation else 'No'}")

    if adaptive_result.degradation_history:
        print(f"    Degradation history:")
        for entry in adaptive_result.degradation_history:
            print(f"      - {entry}")

    if result.warnings:
        print(f"    Warnings ({len(result.warnings)}):")
        for w in result.warnings[:3]:
            print(f"      - {w}")
        if len(result.warnings) > 3:
            print(f"      ... and {len(result.warnings) - 3} more")


def print_schedule_summary(adaptive_result, gens):
    """Print generator commitment and output summary."""
    result = adaptive_result.result
    gen_map = {g.id: g for g in gens}

    print()
    print(f"  {'Generator':<22} {'Type':<10} {'On(h)':>6} "
          f"{'Output(MWh)':>12} {'Startups':>8}")
    print("  " + "-" * 62)

    for sched in result.schedules:
        g = gen_map.get(sched.generator_id)
        if g is None:
            continue
        hours_on = sum(sched.commitment)
        energy = sum(sched.power_output_mw)
        print(
            f"  {g.name:<22} {g.fuel_type:<10} {hours_on:>6} "
            f"{energy:>12,.0f} {sched.num_startups:>8}"
        )


# ── Build UC parameters ─────────────────────────────────────────


def build_params(gens, demand):
    """Build UC parameters for the demo fleet."""
    th = TimeHorizon(num_periods=NUM_PERIODS, period_duration_h=1.0)
    dp = DemandProfile(demands=demand)
    return UCParameters(
        generators=gens,
        demand=dp,
        time_horizon=th,
        reserve_margin=RESERVE_MARGIN,
    )


# ── Scenario runners ────────────────────────────────────────────


def scenario_normal_solve(params):
    """Scenario A: Normal solve with auto-detected hardware.

    The adaptive solver detects hardware, selects the best tier, and
    solves the UC problem. On a modern machine with multiple cores and
    sufficient RAM, this will typically select HIGH tier.
    """
    print_section("SCENARIO A: Normal Solve (Auto-Detected Hardware)")
    print()
    print("  The adaptive solver detects hardware capabilities and")
    print("  automatically selects the best solver tier.")
    print()
    print("  Running solve_adaptive(params)...")

    adaptive_result = solve_adaptive(params, verbose=True)
    print_solve_result("Auto-Detected", adaptive_result)
    return adaptive_result


def scenario_forced_low_tier(params, gens):
    """Scenario B: Forced LOW tier with LP relaxation.

    Simulates a low-resource environment by forcing the LOW tier.
    LP relaxation relaxes binary commitment variables to continuous
    [0,1], producing a faster solve but potentially fractional
    commitments that need rounding.
    """
    print_section("SCENARIO B: Forced LOW Tier (LP Relaxation)")
    print()
    print("  Forcing LOW tier to demonstrate LP relaxation behavior.")
    print("  Binary commitment variables are relaxed to continuous [0,1],")
    print("  then rounded (>= 0.5 -> 1, < 0.5 -> 0) in post-processing.")
    print()
    print("  Running solve_adaptive(params, force_tier=SolverTier.LOW)...")

    adaptive_result = solve_adaptive(
        params, force_tier=SolverTier.LOW, verbose=True,
    )
    print_solve_result("Forced LOW", adaptive_result)
    print_schedule_summary(adaptive_result, gens)
    return adaptive_result


def scenario_tier_comparison(params, gens):
    """Scenario C: Side-by-side comparison of all three tiers.

    Solves the same UC problem at each tier (HIGH, MID, LOW) and
    compares cost, solve time, and solution quality.
    """
    print_section("SCENARIO C: Tier Comparison (HIGH vs MID vs LOW)")
    print()
    print("  Solving the same problem at all three tiers to compare")
    print("  cost, solve time, and solution quality.")

    results = {}
    for tier in [SolverTier.HIGH, SolverTier.MID, SolverTier.LOW]:
        print()
        print(f"  --- Solving with {tier.value.upper()} tier ---")
        adaptive_result = solve_adaptive(
            params, force_tier=tier, verbose=False,
        )
        results[tier] = adaptive_result
        print_solve_result(tier.value.upper(), adaptive_result)

    # ── Comparison table ──
    print()
    print_section("TIER COMPARISON SUMMARY")
    print()
    print(f"  {'Metric':<24} {'HIGH':>14} {'MID':>14} {'LOW':>14}")
    print("  " + "-" * 60)

    for label, getter in [
        ("Status", lambda r: r.result.status),
        ("Total Cost (¥)", lambda r: f"{r.result.total_cost:,.0f}"),
        ("Solve Time (s)", lambda r: f"{r.result.solve_time_s:.2f}"),
        ("Adaptive Time (s)", lambda r: f"{r.total_time_s:.2f}"),
        ("MIP Gap", lambda r: f"{r.result.gap:.4%}" if r.result.gap is not None else "N/A"),
        ("LP Relaxation", lambda r: "Yes" if r.solver_config and r.solver_config.use_lp_relaxation else "No"),
        ("Generators Used", lambda r: str(r.result.num_generators)),
        ("Warnings", lambda r: str(len(r.result.warnings))),
    ]:
        high_val = getter(results[SolverTier.HIGH])
        mid_val = getter(results[SolverTier.MID])
        low_val = getter(results[SolverTier.LOW])
        print(f"  {label:<24} {high_val:>14} {mid_val:>14} {low_val:>14}")

    # ── Cost delta analysis ──
    high_cost = results[SolverTier.HIGH].result.total_cost
    mid_cost = results[SolverTier.MID].result.total_cost
    low_cost = results[SolverTier.LOW].result.total_cost

    print()
    if high_cost > 0:
        mid_delta = ((mid_cost - high_cost) / high_cost) * 100
        low_delta = ((low_cost - high_cost) / high_cost) * 100
        print(f"  Cost vs HIGH tier:")
        print(f"    MID:  {mid_delta:+.2f}%")
        print(f"    LOW:  {low_delta:+.2f}%")

    return results


# ── Main ─────────────────────────────────────────────────────────


def main():
    """Run all adaptive solver demo scenarios."""
    print()
    print("=" * 70)
    print("  ADAPTIVE SOLVER DEMO")
    print("  Tier Selection, LP Relaxation, and Fallback Behavior")
    print("=" * 70)

    # ── Step 1: Detect hardware and show tier selection logic ──
    print()
    print("STEP 1: Hardware detection and tier selection logic")
    profile = detect_hardware()
    print_hardware_profile(profile)

    gens = make_generators()
    demand = make_demand_profile()
    print_tier_selection(profile, len(gens), NUM_PERIODS)

    # ── Step 2: Build shared UC parameters ──
    print()
    print("STEP 2: Building UC problem ({} generators, {} periods, "
          "peak demand {:,.0f} MW)".format(len(gens), NUM_PERIODS, max(demand)))
    params = build_params(gens, demand)

    # ── Step 3: Scenario A — Normal solve ──
    print()
    print("STEP 3: Running scenarios")
    result_a = scenario_normal_solve(params)

    # ── Step 4: Scenario B — Forced LOW tier ──
    result_b = scenario_forced_low_tier(params, gens)

    # ── Step 5: Scenario C — Tier comparison ──
    results_c = scenario_tier_comparison(params, gens)

    # ── Final summary ──
    print()
    print_section("DEMO COMPLETE")
    print()
    print(f"  Scenario A (auto-detect): tier={result_a.tier_used.value.upper()}, "
          f"status={result_a.result.status}, cost=¥{result_a.result.total_cost:,.0f}")
    print(f"  Scenario B (forced LOW):  tier={result_b.tier_used.value.upper()}, "
          f"status={result_b.result.status}, cost=¥{result_b.result.total_cost:,.0f}")
    for tier in [SolverTier.HIGH, SolverTier.MID, SolverTier.LOW]:
        r = results_c[tier]
        print(f"  Scenario C ({tier.value.upper():>4}):        tier={r.tier_used.value.upper()}, "
              f"status={r.result.status}, cost=¥{r.result.total_cost:,.0f}")
    print()


if __name__ == "__main__":
    main()
