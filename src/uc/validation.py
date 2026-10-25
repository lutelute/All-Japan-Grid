"""Independent numerical audit of the existing hourly UC model and its cost.

Uses input data and schedules, not PuLP constraints. The current copperplate
model has a >= balance and end-of-horizon min-up/down obligations are truncated;
the audit reports these semantics rather than claiming stricter SCUC feasibility.
"""

import math
from collections import defaultdict

from src.uc.models import UCParameters, UCResult


def schedule_cost(g, schedule, *, initial_commitment=0, initial_history_h=None,
                  skip_periods=0):
    """Hourly cost, including the exact downtime category at each startup."""
    state = initial_commitment
    streak = (initial_history_h if initial_history_h is not None else
              max(g.min_up_time_h, 1) if state else -max(g.min_down_time_h, g.cold_start_h, 1))
    cost = 0.0
    for t, (on, power) in enumerate(zip(schedule.commitment, schedule.power_output_mw)):
        event = 0.0
        if on and not state:
            if g.has_thermal_startup:
                downtime = -streak
                event = (g.hot_start_cost if downtime < g.warm_start_h else
                         g.warm_start_cost if downtime < g.cold_start_h else g.cold_start_cost)
            else:
                event = g.startup_cost
        elif state and not on:
            event = g.shutdown_cost
        if t >= skip_periods:
            cost += power * g.fuel_cost_per_mwh + on * (g.no_load_cost + g.labor_cost_per_h) + event
        streak = (max(streak, 0) + 1) if on else (min(streak, 0) - 1)
        state = on
    return cost


def validate_uc_solution(params: UCParameters, result: UCResult, *, spill_penalty=100000.0,
                         check_objective=True, absolute_tolerance=1e-4,
                         relative_tolerance=1e-8):
    """Audit every period, including t=0 ramp/history and final storage SOC."""
    errors = []
    maxima = defaultdict(float)
    count = 0

    def check(kind, residual, scale=1.0, where=""):
        nonlocal count
        residual = max(0.0, float(residual)) if math.isfinite(residual) else math.inf
        maxima[kind] = max(maxima[kind], residual)
        if residual > absolute_tolerance + relative_tolerance * max(1.0, abs(scale)):
            count += 1
            if len(errors) < 50:
                errors.append({"constraint": kind, "where": where, "residual": residual})

    T = params.time_horizon.num_periods
    check("hourly_resolution", abs(params.time_horizon.period_duration_h - 1))
    schedules = {s.generator_id: s for s in result.schedules}
    expected = {g.id for g in params.generators}
    check("schedule_ids", len(expected.symmetric_difference(schedules))
          + len(result.schedules) - len(schedules))
    for g in params.generators:
        if g.id not in schedules:
            continue
        s = schedules[g.id]
        arrays = [s.commitment, s.power_output_mw]
        if g.is_storage:
            arrays.extend([s.soc_mwh, s.charge_mw, s.discharge_mw])
        for a in arrays:
            check("schedule_length", abs(len(a) - T), where=g.id)
            check("finite_values", sum(not math.isfinite(v) for v in a), where=g.id)
    if count:
        return {"passed": False, "violation_count": count, "errors": errors,
                "max_residuals": dict(maxima), "economic_cost": None, "objective": None}

    initial_u = params.initial_commitment or {}
    initial_hist = params.initial_history_h or {}
    initial_p = params.initial_power_mw or {}
    economic = 0.0
    for g in params.generators:
        s = schedules[g.id]
        prev_u = initial_u.get(g.id, 0)
        streak = initial_hist.get(g.id, max(g.min_up_time_h, 1) if prev_u
                                  else -max(g.min_down_time_h, g.cold_start_h, 1))
        economic += schedule_cost(g, s, initial_commitment=prev_u, initial_history_h=streak)
        prev_p = initial_p.get(g.id)
        prev_soc = g.initial_soc_fraction * g.storage_capacity_mwh
        for t, (on, power) in enumerate(zip(s.commitment, s.power_output_mw)):
            where = f"{g.id}:t{t}"
            check("binary", min(abs(on), abs(on - 1)), where=where)
            if on != prev_u:
                required = g.min_up_time_h if prev_u else g.min_down_time_h
                check("minimum_time", required - abs(streak), where=where)
            if not g.is_storage:
                check("capacity_min", g.p_min_mw * on - power, g.capacity_mw, where)
                check("capacity_max", power - g.capacity_mw * on, g.capacity_mw, where)
            if prev_p is not None:
                if g.ramp_up_mw_per_h is not None:
                    check("ramp_up", power - prev_p - g.ramp_up_mw_per_h
                          - g.capacity_mw * (1 - prev_u), g.capacity_mw, where)
                if g.ramp_down_mw_per_h is not None:
                    check("ramp_down", prev_p - power - g.ramp_down_mw_per_h
                          - g.capacity_mw * (1 - on), g.capacity_mw, where)
            for start, end in g.maintenance_windows:
                if start <= params.time_horizon.period_indices[t] < end:
                    check("maintenance", on, where=where)
            if g.is_storage:
                ch, dis, soc = s.charge_mw[t], s.discharge_mw[t], s.soc_mwh[t]
                chmax = g.charge_rate_mw if g.charge_rate_mw is not None else g.capacity_mw
                dismax = g.discharge_rate_mw if g.discharge_rate_mw is not None else g.capacity_mw
                check("charge_nonnegative", -ch, where=where)
                check("discharge_nonnegative", -dis, where=where)
                check("charge_limit", ch - chmax * on, chmax, where)
                check("discharge_limit", dis - dismax * on, dismax, where)
                check("charge_discharge_exclusion", min(ch, dis), max(chmax, dismax), where)
                check("net_storage_power", abs(power - dis + ch), g.capacity_mw, where)
                check("soc_balance", abs(soc - prev_soc - g.charge_efficiency * ch
                      + dis / g.discharge_efficiency), g.storage_capacity_mwh, where)
                check("soc_min", -soc, g.storage_capacity_mwh, where)
                check("soc_max", soc - g.storage_capacity_mwh, g.storage_capacity_mwh, where)
                prev_soc = soc
            streak = max(streak, 0) + 1 if on else min(streak, 0) - 1
            prev_u, prev_p = on, power
        if g.is_storage:
            check("terminal_soc", g.min_terminal_soc_fraction * g.storage_capacity_mwh
                  - s.soc_mwh[-1], g.storage_capacity_mwh, g.id)

    for t, demand in enumerate(params.demand.demands):
        if not params.interconnections:
            supply = sum(s.power_output_mw[t] for s in result.schedules)
            check("demand_balance", demand - supply, demand, f"t{t}")
        if params.reserve_requirement_mw is not None or params.reserve_margin > 0:
            available = sum(g.capacity_mw * schedules[g.id].commitment[t] for g in params.generators)
            required = (params.reserve_requirement_mw[t] if params.reserve_requirement_mw is not None
                        else demand * (1 + params.reserve_margin))
            check("capacity_reserve", required - available, demand, f"t{t}")

    if params.interconnections:
        flows = {f.interconnection_id: f.flow_mw for f in result.interconnection_flows}
        check("flow_ids", len(set(flows).symmetric_difference(ic.id for ic in params.interconnections)))
        for ic in params.interconnections:
            values = flows.get(ic.id, [])
            check("flow_length", abs(len(values) - T), where=ic.id)
            for t, value in enumerate(values):
                check("flow_forward", value - ic.cap_fwd, ic.cap_fwd, f"{ic.id}:t{t}")
                check("flow_reverse", -value - ic.cap_rev, ic.cap_rev, f"{ic.id}:t{t}")
        regions = params.regional_demands
        if not regions:
            capacities = defaultdict(float)
            for g in params.generators:
                capacities[g.region or "_unassigned"] += g.capacity_mw
            total = sum(capacities.values())
            regions = {r: [d * (cap / total if total > 0 else 1 / len(capacities))
                           for d in params.demand.demands] for r, cap in capacities.items()}
        if all(len(flows.get(ic.id, [])) == T for ic in params.interconnections):
            for region, demands in regions.items():
                spill = result.regional_spill_mw.get(region, [0.0] * T)
                check("spill_length", abs(len(spill) - T), where=region)
                if len(spill) != T:
                    continue
                for t, demand in enumerate(demands):
                    net = sum(schedules[g.id].power_output_mw[t] for g in params.generators
                              if (g.region or "_unassigned") == region)
                    for ic in params.interconnections:
                        if ic.to_region == region:
                            net += flows[ic.id][t]
                        if ic.from_region == region:
                            net -= flows[ic.id][t]
                    check("spill_nonnegative", -spill[t], where=f"{region}:t{t}")
                    check("regional_balance", abs(net - spill[t] - demand), demand, f"{region}:t{t}")

    objective = economic + spill_penalty * sum(sum(v) for v in result.regional_spill_mw.values())
    overstatement = None
    if check_objective and result.solver_objective is not None:
        # Only an objective below the exact cost of its own schedule is wrong (the model would
        # under-price a plan). Above it, the bound still holds: a gap-limited incumbent may keep
        # a start-up and shut-down booked in the same hour, or a dearer start-up category.
        check("objective", objective - result.solver_objective, objective)
        overstatement = max(0.0, result.solver_objective - objective)
    return {"passed": count == 0, "violation_count": count, "errors": errors,
            "max_residuals": dict(maxima), "economic_cost": economic, "objective": objective,
            "objective_overstatement": overstatement,
            "scope": "existing_hourly_uc", "copperplate_balance": ">=",
            "terminal_minimum_time": "residual_obligations_not_enforced_beyond_horizon",
            "absolute_tolerance": absolute_tolerance, "relative_tolerance": relative_tolerance}
