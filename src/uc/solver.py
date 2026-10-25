"""Core MILP-based unit commitment (UC) solver.

Formulates and solves a mixed-integer linear programming (MILP) unit
commitment problem using PuLP.  The solver determines optimal generator
on/off schedules over a configurable time horizon to minimise total
operating cost while satisfying demand and operational constraints.

Usage::

    from src.uc.solver import solve_uc
    from src.uc.models import UCParameters, TimeHorizon, DemandProfile
    from src.model.generator import Generator

    gens = [Generator(id='g1', name='G1', capacity_mw=200,
                      fuel_type='coal', fuel_cost_per_mwh=30)]
    th = TimeHorizon(num_periods=24, period_duration_h=1.0)
    dp = DemandProfile(demands=[100.0] * 24)
    params = UCParameters(generators=gens, demand=dp, time_horizon=th)
    result = solve_uc(params)
    print(result.status, result.total_cost)
"""

import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pulp

from src.model.generator import Generator
from src.uc.constraints import (
    add_capacity_bounds_constraints,
    add_demand_balance_constraints,
    add_initial_history_constraints,
    add_maintenance_constraints,
    add_min_downtime_constraints,
    add_min_uptime_constraints,
    add_nodal_balance_constraints,
    add_ramp_constraints,
    add_reserve_margin_constraints,
    add_startup_shutdown_logic,
    add_startup_type_constraints,
    add_startup_type_shutdown_cuts,
    add_storage_soc_constraints,
    add_tight_ramp_cuts,
    add_transmission_capacity_constraints,
)
from src.uc.models import (
    GeneratorSchedule,
    Interconnection,
    InterconnectionFlow,
    UCParameters,
    UCResult,
)
from src.uc.solve_metrics import capture_solve_metrics, finalize_bounds
from src.uc.validation import validate_uc_solution
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

# PuLP status code to human-readable string mapping
# 地域余剰(spill)のペナルティ [¥/MWh]。どの燃料の限界費用よりも十分高く、
# 「余らせるくらいなら出力を下げる/停止する/輸出する」を必ず優先させる。
# spill>0 が残るのは物理的に不可避な場合のみ(最低出力・must-run と輸出上限の
# 衝突=実運用の出力制御に相当)。総コスト報告からはペナルティ分を除外する。
SPILL_PENALTY = 100_000.0

_STATUS_MAP = {
    pulp.constants.LpStatusOptimal: "Optimal",
    pulp.constants.LpStatusNotSolved: "Not Solved",
    pulp.constants.LpStatusInfeasible: "Infeasible",
    pulp.constants.LpStatusUnbounded: "Unbounded",
    pulp.constants.LpStatusUndefined: "Undefined",
}


def solve_uc(params: UCParameters, *, progress_callback=None) -> UCResult:
    """Solve a unit commitment optimisation problem.

    Formulates a MILP using PuLP with binary commitment, startup, and
    shutdown variables plus continuous power output variables.  The
    objective minimises total operating cost (fuel, no-load, labour,
    startup, and shutdown costs).  Constraints are added via modular
    builders from ``src.uc.constraints``.

    Args:
        params: UC problem specification including generators, demand
            profile, time horizon, and solver configuration.

    Returns:
        UCResult with per-generator schedules, total cost, solver
        status, and solve time.  On infeasibility, diagnostic
        warnings identify which timesteps have insufficient capacity.
    """
    result = UCResult()
    build_start = time.monotonic()
    def progress(stage, **metrics):
        if progress_callback is not None:
            progress_callback(stage, **metrics)

    progress("build")

    # --- Validate inputs ---------------------------------------------------
    if not params.generators:
        result.status = "Infeasible"
        result.warnings.append("No generators provided")
        logger.warning("UC solve aborted: no generators provided")
        return result

    if params.demand is None or params.time_horizon is None:
        result.status = "Not Solved"
        result.warnings.append("Demand profile and time horizon are required")
        logger.warning("UC solve aborted: missing demand or time horizon")
        return result

    generators = params.generators
    if params.time_horizon.period_duration_h != 1.0:
        raise ValueError("UC currently supports 1-hour periods only; costs and minimum times are hourly")
    if len({g.id for g in generators}) != len(generators):
        raise ValueError("Generator IDs must be unique")
    timesteps = params.time_horizon.period_indices
    demand = params.demand.demands

    logger.info(
        "UC problem: %d generators, %d timesteps, peak demand=%.1f MW",
        len(generators),
        len(timesteps),
        params.demand.peak_demand,
    )

    # --- Pre-solve feasibility check ---------------------------------------
    _preflight_check(generators, timesteps, demand, result)

    # --- Create model ------------------------------------------------------
    model = pulp.LpProblem("UnitCommitment", pulp.LpMinimize)

    # --- Decision variables ------------------------------------------------
    gen_ids = [g.id for g in generators]
    indices = [(g_id, t) for g_id in gen_ids for t in timesteps]

    # Identify storage generators
    storage_ids = {g.id for g in generators if g.is_storage}
    storage_map = {g.id: g for g in generators if g.is_storage}

    u = pulp.LpVariable.dicts("u", indices, cat="Binary")
    v = pulp.LpVariable.dicts("v", indices, cat="Binary")
    w = pulp.LpVariable.dicts("w", indices, cat="Binary")

    # 3-state startup type variables (only for thermal generators)
    thermal_ids = {g.id for g in generators if g.has_thermal_startup}
    thermal_indices = [(g_id, t) for g_id in thermal_ids for t in timesteps]
    y_hot  = pulp.LpVariable.dicts("y_hot",  thermal_indices, cat="Binary") if thermal_indices else {}
    y_warm = pulp.LpVariable.dicts("y_warm", thermal_indices, cat="Binary") if thermal_indices else {}
    y_cold = pulp.LpVariable.dicts("y_cold", thermal_indices, cat="Binary") if thermal_indices else {}
    if thermal_indices:
        logger.info(
            "Created %d×3 thermal startup variables (%d thermal generators)",
            len(thermal_indices), len(thermal_ids),
        )

    # Split p variable creation: non-storage (lowBound=0), storage (lowBound=None)
    non_storage_p_indices = [
        (g_id, t) for g_id in gen_ids if g_id not in storage_ids for t in timesteps
    ]
    storage_p_indices = [
        (g_id, t) for g_id in gen_ids if g_id in storage_ids for t in timesteps
    ]

    p = {}
    if non_storage_p_indices:
        p.update(
            pulp.LpVariable.dicts("p", non_storage_p_indices, lowBound=0)
        )
    if storage_p_indices:
        p.update(
            pulp.LpVariable.dicts("p", storage_p_indices, lowBound=None)
        )

    # Storage-specific variables
    if storage_ids:
        storage_indices = [
            (g_id, t) for g_id in storage_ids for t in timesteps
        ]
        p_ch = pulp.LpVariable.dicts("p_ch", storage_indices, lowBound=0)
        p_dis = pulp.LpVariable.dicts("p_dis", storage_indices, lowBound=0)
        z_ch = pulp.LpVariable.dicts("z_ch", storage_indices, cat="Binary")
        soc = pulp.LpVariable.dicts("soc", storage_indices, lowBound=0)

        # Set SOC upper bounds per generator
        for g_id, t in storage_indices:
            soc[(g_id, t)].upBound = storage_map[g_id].storage_capacity_mwh

        logger.info(
            "Created %d storage variables (%d storage generators × %d timesteps × 4: p_ch, p_dis, z_ch, soc)",
            len(storage_indices) * 4,
            len(storage_ids),
            len(timesteps),
        )
    else:
        p_ch = {}
        p_dis = {}
        z_ch = {}
        soc = {}

    # Interconnection flow variables
    interconnections = params.interconnections
    f: Dict[Tuple[str, int], pulp.LpVariable] = {}
    if interconnections:
        ic_indices = [
            (ic.id, t) for ic in interconnections for t in timesteps
        ]
        f = pulp.LpVariable.dicts(
            "f", ic_indices, lowBound=None, cat="Continuous"
        )
        logger.info(
            "Created %d flow variables (%d interconnections × %d timesteps)",
            len(ic_indices),
            len(interconnections),
            len(timesteps),
        )

    logger.info(
        "Created %d decision variables (%d generators × %d timesteps × 4)",
        len(indices) * 4,
        len(gen_ids),
        len(timesteps),
    )

    # --- Objective function ------------------------------------------------
    _build_objective(model, u, p, v, w, generators, timesteps,
                     y_hot=y_hot, y_warm=y_warm, y_cold=y_cold)

    # --- Constraints -------------------------------------------------------
    spill = _add_all_constraints(
        model, u, p, v, w, generators, timesteps, demand, params.reserve_margin,
        p_ch=p_ch, p_dis=p_dis, z_ch=z_ch, soc=soc,
        period_duration_h=params.time_horizon.period_duration_h,
        interconnections=interconnections, f=f,
        y_hot=y_hot, y_warm=y_warm, y_cold=y_cold,
        regional_demands=params.regional_demands,
        initial_commitment=params.initial_commitment,
        initial_history_h=params.initial_history_h,
        initial_power_mw=params.initial_power_mw,
        strengthen=params.strengthen,
        reserve_requirement=params.reserve_requirement_mw,
    )
    cost_expression = model.objective
    if params.model_hook is not None:
        params.model_hook(model, {
            "u": u, "p": p, "v": v, "w": w, "f": f, "spill": spill,
            "y_hot": y_hot, "y_warm": y_warm, "y_cold": y_cold,
            "p_ch": p_ch, "p_dis": p_dis, "soc": soc,
            "generators": generators, "timesteps": timesteps, "cost": cost_expression,
        })

    if params.model_export_path:
        export_path = Path(params.model_export_path)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        model.writeMPS(str(export_path))
    result.build_time_s = time.monotonic() - build_start
    progress("native_solve", variables=model.numVariables(), constraints=model.numConstraints(),
             build_time_s=result.build_time_s)

    # --- Select and run solver ---------------------------------------------
    solver = _select_solver(params)

    # Inject previous solution as a MIP start (rolling horizon, re-solves)
    if params.warm_start_schedules:
        n_ws = _apply_warm_start(
            params.warm_start_schedules, u, p,
            p_ch or {}, p_dis or {}, soc or {}, timesteps,
        )
        logger.info("Warm start: %d initial values injected", n_ws)

    start_time = time.monotonic()

    logger.info("Solving UC problem...")
    status_code = model.solve(solver)
    elapsed = time.monotonic() - start_time

    result.solve_time_s = elapsed
    result.status = _STATUS_MAP.get(status_code, "Unknown")
    capture_solve_metrics(model, solver, result)

    logger.info(
        "Solver finished: status=%s, time=%.2fs",
        result.status,
        elapsed,
    )

    # --- Extract results ---------------------------------------------------
    if result.has_incumbent:
        progress("validation")
        _extract_solution(
            result, model, u, p, v, w, generators, timesteps,
            p_ch=p_ch, p_dis=p_dis, soc=soc, storage_ids=storage_ids,
            interconnections=interconnections, f=f, spill=spill,
            y_hot=y_hot, y_warm=y_warm, y_cold=y_cold, cost_expression=cost_expression,
        )
        if model.objective is not cost_expression:
            result.secondary_objective = pulp.value(model.objective)
        result.validation = validate_uc_solution(params, result, spill_penalty=SPILL_PENALTY)
        raw_valid = model.valid(1e-4)
        result.validation["raw_model_valid"] = raw_valid
        result.feasibility_verified = result.validation["passed"] and raw_valid
        if not result.feasibility_verified:
            result.status = "Invalid Solution"
            result.warnings.append("Independent solution validation failed")
        finalize_bounds(result)
        if params.extract_duals:
            _extract_duals(result, model, solver, timesteps)
    elif result.status == "Infeasible":
        _diagnose_infeasibility(result, generators, timesteps, demand)

    logger.info("UC result summary: %s", result.summary)
    progress("complete", termination_reason=result.termination_reason,
             feasibility_verified=result.feasibility_verified)
    return result


def _preflight_check(
    generators: List[Generator],
    timesteps: List[int],
    demand: List[float],
    result: UCResult,
) -> None:
    """Run quick feasibility checks before model construction.

    Checks that total available capacity can meet demand at each
    timestep, accounting for maintenance windows.  Issues are
    recorded as warnings but do not prevent solve (the solver
    will report infeasibility definitively).
    """
    for idx, t in enumerate(timesteps):
        available_cap = 0.0
        for g in generators:
            in_maintenance = any(
                start_h <= t < end_h for start_h, end_h in g.maintenance_windows
            )
            if not in_maintenance:
                available_cap += g.capacity_mw
        if available_cap < demand[idx]:
            shortfall = demand[idx] - available_cap
            msg = (
                f"Timestep {t}: demand ({demand[idx]:.1f} MW) exceeds "
                f"available capacity ({available_cap:.1f} MW) by "
                f"{shortfall:.1f} MW"
            )
            result.warnings.append(msg)
            logger.warning(msg)


def _build_objective(
    model: pulp.LpProblem,
    u: Dict[Tuple[str, int], pulp.LpVariable],
    p: Dict[Tuple[str, int], pulp.LpVariable],
    v: Dict[Tuple[str, int], pulp.LpVariable],
    w: Dict[Tuple[str, int], pulp.LpVariable],
    generators: List[Generator],
    timesteps: List[int],
    *,
    y_hot: Optional[Dict[Tuple[str, int], pulp.LpVariable]] = None,
    y_warm: Optional[Dict[Tuple[str, int], pulp.LpVariable]] = None,
    y_cold: Optional[Dict[Tuple[str, int], pulp.LpVariable]] = None,
) -> None:
    """Build the cost-minimisation objective function.

    For generators with ``has_thermal_startup=True``, the startup cost
    term is replaced by the 3-state formulation:
        hot_start_cost * y_hot + warm_start_cost * y_warm + cold_start_cost * y_cold

    For all others, the legacy ``startup_cost * v[g,t]`` term is used.
    """
    y_hot  = y_hot  or {}
    y_warm = y_warm or {}
    y_cold = y_cold or {}

    terms = []
    for g in generators:
        for t in timesteps:
            terms.append(g.fuel_cost_per_mwh * p[(g.id, t)])
            terms.append((g.no_load_cost + g.labor_cost_per_h) * u[(g.id, t)])
            terms.append(g.shutdown_cost * w[(g.id, t)])
            if g.has_thermal_startup and (g.id, t) in y_hot:
                terms.append(g.hot_start_cost  * y_hot [(g.id, t)])
                terms.append(g.warm_start_cost * y_warm[(g.id, t)])
                terms.append(g.cold_start_cost * y_cold[(g.id, t)])
            else:
                terms.append(g.startup_cost * v[(g.id, t)])

    model += pulp.lpSum(terms)
    n_thermal = sum(1 for g in generators if g.has_thermal_startup)
    logger.info(
        "Objective built: %d generators (%d thermal 3-state, %d single-cost)",
        len(generators), n_thermal, len(generators) - n_thermal,
    )


def _add_all_constraints(
    model: pulp.LpProblem,
    u: Dict[Tuple[str, int], pulp.LpVariable],
    p: Dict[Tuple[str, int], pulp.LpVariable],
    v: Dict[Tuple[str, int], pulp.LpVariable],
    w: Dict[Tuple[str, int], pulp.LpVariable],
    generators: List[Generator],
    timesteps: List[int],
    demand: List[float],
    reserve_margin: float,
    *,
    p_ch: Optional[Dict[Tuple[str, int], pulp.LpVariable]] = None,
    p_dis: Optional[Dict[Tuple[str, int], pulp.LpVariable]] = None,
    z_ch: Optional[Dict[Tuple[str, int], pulp.LpVariable]] = None,
    soc: Optional[Dict[Tuple[str, int], pulp.LpVariable]] = None,
    period_duration_h: float = 1.0,
    interconnections: Optional[List[Interconnection]] = None,
    f: Optional[Dict[Tuple[str, int], pulp.LpVariable]] = None,
    y_hot: Optional[Dict[Tuple[str, int], pulp.LpVariable]] = None,
    y_warm: Optional[Dict[Tuple[str, int], pulp.LpVariable]] = None,
    y_cold: Optional[Dict[Tuple[str, int], pulp.LpVariable]] = None,
    regional_demands: Optional[Dict[str, List[float]]] = None,
    initial_commitment: Optional[Dict[str, int]] = None,
    initial_history_h: Optional[Dict[str, int]] = None,
    initial_power_mw: Optional[Dict[str, float]] = None,
    strengthen: Tuple[str, ...] = (),
    reserve_requirement: Optional[List[float]] = None,
) -> Optional[Dict[Tuple[str, int], pulp.LpVariable]]:
    """Add all constraint classes to the model.

    When interconnections are present, uses per-region nodal balance
    constraints instead of system-wide demand balance, and adds
    transmission capacity constraints on flow variables.
    ``initial_commitment`` / ``initial_history_h`` carry pre-horizon state
    for rolling-horizon solves.

    Returns:
        The spill variable dict ``(region, t) -> LpVariable`` when nodal
        balance is active (等式化に伴う地域余剰の明示変数), else ``None``.
    """
    spill: Optional[Dict[Tuple[str, int], pulp.LpVariable]] = None
    if interconnections and f:
        # Nodal balance replaces system-wide demand balance.
        # Use caller-supplied regional demands when available (physically
        # correct); fall back to capacity-fraction split otherwise.
        regional_demand = (
            regional_demands
            if regional_demands
            else _split_demand_by_region(generators, demand)
        )
        # 2026-08-19: 地域収支を等式化し、余剰は明示spill変数(ペナルティ
        # 課金)へ。従来の >= は余剰の自由廃棄=連系制約が発電を拘束しない
        # 抜け穴だった(九州昼間に純需要+輸出上限を5.7GW超えて発電)。
        spill_indices = [
            (r, t) for r in regional_demand for t in timesteps
        ]
        spill = pulp.LpVariable.dicts(
            "spill", spill_indices, lowBound=0, cat="Continuous"
        )
        model.objective += SPILL_PENALTY * pulp.lpSum(spill.values())
        add_nodal_balance_constraints(
            model, p, f, generators, interconnections, timesteps,
            regional_demand, spill=spill,
        )
        add_transmission_capacity_constraints(
            model, f, interconnections, timesteps,
        )
    else:
        add_demand_balance_constraints(model, p, generators, timesteps, demand)
    add_capacity_bounds_constraints(model, u, p, generators, timesteps)
    add_startup_shutdown_logic(
        model, u, v, w, generators, timesteps,
        initial_commitment=initial_commitment,
    )
    if initial_history_h:
        add_initial_history_constraints(
            model, u, generators, timesteps, initial_history_h,
        )
    add_min_uptime_constraints(model, u, v, generators, timesteps)
    add_min_downtime_constraints(model, u, w, generators, timesteps)
    add_ramp_constraints(model, p, u, generators, timesteps,
                         initial_power_mw=initial_power_mw,
                         initial_commitment=initial_commitment)
    add_maintenance_constraints(model, u, generators, timesteps)
    add_reserve_margin_constraints(
        model, u, generators, timesteps, demand, reserve_margin, requirement=reserve_requirement
    )
    add_storage_soc_constraints(
        model, p, p_ch or {}, p_dis or {}, z_ch or {}, soc or {},
        u, generators, timesteps, period_duration_h,
    )
    if y_hot is not None and y_warm is not None and y_cold is not None:
        add_startup_type_constraints(
            model, u, v, y_hot, y_warm, y_cold, generators, timesteps,
            initial_history_h=initial_history_h,
            initial_commitment=initial_commitment,
        )
        if "startup_type" in strengthen:
            add_startup_type_shutdown_cuts(
                model, w, y_hot, y_warm, generators, timesteps,
                initial_history_h=initial_history_h,
                initial_commitment=initial_commitment,
            )
    if "ramp" in strengthen:
        add_tight_ramp_cuts(model, p, u, v, w, generators, timesteps)
    return spill


def _split_demand_by_region(
    generators: List[Generator],
    demand: List[float],
) -> Dict[str, List[float]]:
    """Split total demand proportionally by region capacity.

    Each region receives a fraction of total demand proportional to its
    share of total generation capacity.  Follows the same pattern as
    ``_split_demand_by_capacity`` in ``decomposition.py``.

    Args:
        generators: List of generators with ``region`` and
            ``capacity_mw`` attributes.
        demand: System-wide demand values (MW) per period.

    Returns:
        Mapping of region identifier to demand series for that region.
    """
    # Group generators by region
    groups: Dict[str, List[Generator]] = {}
    for g in generators:
        key = g.region if g.region else "_unassigned"
        groups.setdefault(key, []).append(g)

    total_cap = sum(g.capacity_mw for g in generators)
    if total_cap <= 0:
        # Equal split if no capacity info
        n = len(groups) or 1
        return {key: [d / n for d in demand] for key in groups}

    result: Dict[str, List[float]] = {}
    for key, gens in groups.items():
        group_cap = sum(g.capacity_mw for g in gens)
        fraction = group_cap / total_cap
        result[key] = [d * fraction for d in demand]

    return result


class _HiGHSWarmStart(pulp.HiGHS):
    """HiGHS (highspy API) with user MIP start injection.

    ``pulp.HiGHS`` ignores ``LpVariable.setInitialValue()``.  This subclass
    collects initial values right before ``run()`` — ``var.index`` is
    assigned by ``buildSolverModel`` — and hands them to HiGHS via
    ``setSolution`` as a user MIP start.  Only the columns that carry an
    initial value are passed (sparse form): HiGHS fixes the given discrete
    values and solves a sub-MIP for the rest (``mip_max_start_nodes``).
    A dense vector would pin the unset startup/shutdown binaries to 0,
    which contradicts any start-up in ``u`` and makes HiGHS reject the
    whole start.  With no initial values set, the behaviour is identical
    to ``pulp.HiGHS``.

    HiGHS keeps one thread pool per process.  A solve that asks for a
    different ``threads`` value than an earlier solve in the same process
    stops with model status "Not Set", so the pool is rebuilt before each
    run.  Solves in one process must therefore not run concurrently.
    """

    def callSolver(self, lp):  # noqa: N802 (PuLP API name)
        import highspy
        import numpy as np

        index, value = [], []
        for var in lp.variables():
            if var.varValue is not None and hasattr(var, "index"):
                index.append(var.index)
                value.append(float(var.varValue))
        if index:
            lp.solverModel.setSolution(len(index), np.asarray(index, dtype=np.int32),
                                       np.asarray(value, dtype=np.float64))
            logger.info("HiGHS MIP start injected (%d of %d columns set)",
                        len(index), lp.solverModel.getNumCol())
        highspy.Highs.resetGlobalScheduler(True)
        lp.solverModel.run()


def _set_initial_clamped(var: pulp.LpVariable, val: float) -> None:
    """setInitialValue with clamping to the variable's bounds.

    Solution values can exceed bounds by float rounding (e.g. a previous
    window's SOC of 73.2 vs upBound 12.2*6 = 73.19999999999999), which
    PuLP's validity check rejects.  Clamping is always safe for a start
    hint.
    """
    if var.upBound is not None and val > var.upBound:
        val = var.upBound
    if var.lowBound is not None and val < var.lowBound:
        val = var.lowBound
    var.setInitialValue(val)


def _apply_warm_start(
    schedules,
    u: Dict[Tuple[str, int], pulp.LpVariable],
    p: Dict[Tuple[str, int], pulp.LpVariable],
    p_ch: Dict[Tuple[str, int], pulp.LpVariable],
    p_dis: Dict[Tuple[str, int], pulp.LpVariable],
    soc: Dict[Tuple[str, int], pulp.LpVariable],
    timesteps: List[int],
) -> int:
    """Inject a previous solution as variable initial values.

    Matches by generator_id and period index.  Periods beyond the provided
    schedule stay unset (free for the solver to repair/extend).  Values
    are clamped to variable bounds (float-rounding tolerance).

    Returns:
        Number of variable initial values set.
    """
    n = 0
    for sched in schedules:
        gid = sched.generator_id
        for idx, t in enumerate(timesteps):
            if idx >= len(sched.power_output_mw):
                break
            key = (gid, t)
            if key in u and idx < len(sched.commitment):
                _set_initial_clamped(u[key], round(sched.commitment[idx]))
                n += 1
            if key in p:
                _set_initial_clamped(p[key], float(sched.power_output_mw[idx]))
                n += 1
            if key in p_ch and idx < len(sched.charge_mw):
                _set_initial_clamped(
                    p_ch[key], max(0.0, float(sched.charge_mw[idx])))
                n += 1
            if key in p_dis and idx < len(sched.discharge_mw):
                _set_initial_clamped(
                    p_dis[key], max(0.0, float(sched.discharge_mw[idx])))
                n += 1
            if key in soc and idx < len(sched.soc_mwh):
                _set_initial_clamped(
                    soc[key], max(0.0, float(sched.soc_mwh[idx])))
                n += 1
    return n


def _select_solver(params: UCParameters) -> pulp.apis.LpSolver:
    """Select and configure the MIP solver backend.

    The requested backend must be available; there is no silent fallback.
    Applies time limit and MIP gap settings from UCParameters.

    Args:
        params: UC parameters with solver configuration.

    Returns:
        Configured PuLP solver instance.
    """
    solver_kwargs: Dict = {"msg": 0}

    if params.solver_time_limit_s is not None:
        solver_kwargs["timeLimit"] = params.solver_time_limit_s

    if params.mip_gap is not None:
        solver_kwargs["gapRel"] = params.mip_gap

    if params.solver_options:
        solver_kwargs.update(params.solver_options)

    name = params.solver_name.upper()
    classes = {"HIGHS": _HiGHSWarmStart, "HIGHS_CMD": pulp.HiGHS_CMD,
               "CBC": pulp.PULP_CBC_CMD, "PULP_CBC_CMD": pulp.PULP_CBC_CMD,
               "SCIP": pulp.SCIP_PY, "SCIP_PY": pulp.SCIP_PY}
    if name not in classes:
        raise ValueError(f"Unsupported UC solver: {params.solver_name}")
    if name in ("SCIP", "SCIP_PY"):
        solver_kwargs["warmStart"] = bool(params.warm_start_schedules)
    solver = classes[name](**solver_kwargs)
    if not solver.available():
        raise RuntimeError(f"Requested UC solver {params.solver_name} is unavailable")
    return solver


def _extract_duals(
    result: UCResult,
    model: pulp.LpProblem,
    solver: pulp.apis.LpSolver,
    timesteps: List[int],
) -> None:
    """Extract marginal prices via a commitment-fixed LP re-solve.

    MILPs have no duals.  The standard market practice is to fix all
    integer variables (commitment, startup/shutdown, charge-mode, startup
    type) at their optimal MILP values, re-solve the remaining problem as
    an LP, and read the duals of the balance constraints:

    - ``demand_balance_t{t}``  -> ``result.system_lambda`` (system price)
    - ``nodal_bal_{region}_t{t}`` -> ``result.regional_lmp`` (zonal price;
      inter-regional differences reflect interconnector congestion)

    The objective value is unchanged by the fixing, so prices are
    consistent with the reported schedule.  On any re-solve failure a
    warning is appended and price fields stay at their defaults.
    """
    logger.info("Extracting duals via commitment-fixed LP re-solve...")
    t0 = time.monotonic()

    for var in model.variables():
        if var.cat == pulp.LpInteger:
            val = round(var.value() or 0.0)
            var.lowBound = val
            var.upBound = val
            var.cat = pulp.LpContinuous

    # The SCIP PuLP adapter does not populate LP row duals.
    lp_solver = pulp.HiGHS(msg=False) if solver.name == "SCIP_PY" else solver
    status_code = model.solve(lp_solver)
    status = _STATUS_MAP.get(status_code, "Unknown")
    if status != "Optimal":
        result.warnings.append(
            f"dual extraction skipped: commitment-fixed LP status={status}"
        )
        return

    # System-wide demand balance duals (model without interconnections)
    lambdas: Optional[List[float]] = []
    for t in timesteps:
        c = model.constraints.get(f"demand_balance_t{t}")
        if c is None:
            lambdas = None
            break
        lambdas.append(float(c.pi) if c.pi is not None else 0.0)
    if lambdas is not None:
        result.system_lambda = lambdas

    # Nodal balance duals (model with interconnections)
    regional: Dict[str, List[float]] = {}
    prefix = "nodal_bal_"
    for name, c in model.constraints.items():
        if not name.startswith(prefix):
            continue
        region, sep, t_str = name[len(prefix):].rpartition("_t")
        if not sep:
            continue
        try:
            idx = timesteps.index(int(t_str))
        except ValueError:
            continue
        series = regional.setdefault(region, [0.0] * len(timesteps))
        series[idx] = float(c.pi) if c.pi is not None else 0.0
    if regional:
        result.regional_lmp = regional

    logger.info(
        "Dual extraction LP re-solved in %.2fs (%d nodal regions)",
        time.monotonic() - t0,
        len(regional),
    )


def _extract_solution(
    result: UCResult,
    model: pulp.LpProblem,
    u: Dict[Tuple[str, int], pulp.LpVariable],
    p: Dict[Tuple[str, int], pulp.LpVariable],
    v: Dict[Tuple[str, int], pulp.LpVariable],
    w: Dict[Tuple[str, int], pulp.LpVariable],
    generators: List[Generator],
    timesteps: List[int],
    *,
    p_ch: Optional[Dict[Tuple[str, int], pulp.LpVariable]] = None,
    p_dis: Optional[Dict[Tuple[str, int], pulp.LpVariable]] = None,
    soc: Optional[Dict[Tuple[str, int], pulp.LpVariable]] = None,
    storage_ids: Optional[set] = None,
    interconnections: Optional[List[Interconnection]] = None,
    f: Optional[Dict[Tuple[str, int], pulp.LpVariable]] = None,
    spill: Optional[Dict[Tuple[str, int], pulp.LpVariable]] = None,
    y_hot=None,
    y_warm=None,
    y_cold=None,
    cost_expression=None,
) -> None:
    """Extract solution values into GeneratorSchedule objects.

    Populates the UCResult with per-generator schedules, cost
    breakdowns, and the total system cost.  For storage generators,
    also extracts SOC, charge, and discharge profiles.  For
    interconnections, extracts per-interconnection flow values and
    logs saturation summary.
    """
    result.total_cost = pulp.value(model.objective if cost_expression is None else cost_expression)
    result.solver_objective = result.total_cost

    # 地域余剰(spill)の帳簿化。総コストからはペナルティ分を除外して
    # 実コストのみ報告する(ペナルティは挙動誘導のための人工項)。
    if spill:
        by_region: Dict[str, List[float]] = {}
        total_spill_mwh = 0.0
        for (r, t) in sorted(spill.keys(), key=lambda k: (k[0], k[1])):
            sv = float(pulp.value(spill[(r, t)]) or 0.0)
            by_region.setdefault(r, []).append(sv)
            total_spill_mwh += sv
        result.regional_spill_mw = by_region
        if total_spill_mwh > 1e-6:
            result.total_cost -= SPILL_PENALTY * total_spill_mwh
            worst = max(by_region.items(),
                        key=lambda kv: max(kv[1]) if kv[1] else 0.0)
            result.warnings.append(
                f"regional spill (=出力制御相当) 合計 {total_spill_mwh:,.0f} MWh; "
                f"最大 {worst[0]} {max(worst[1]):,.0f} MW")
            logger.warning(
                "Regional spill present: total %.0f MWh (max %s %.0f MW)",
                total_spill_mwh, worst[0], max(worst[1]))

    if p_ch is None:
        p_ch = {}
    if p_dis is None:
        p_dis = {}
    if soc is None:
        soc = {}
    if storage_ids is None:
        storage_ids = set()

    for g in generators:
        commitment = []
        power_output = []
        gen_fuel_cost = 0.0
        gen_noload_cost = 0.0
        gen_startup_cost = 0.0
        gen_shutdown_cost = 0.0

        # Storage-specific result arrays
        soc_mwh = []
        charge_mw = []
        discharge_mw = []
        is_storage = g.id in storage_ids

        for t in timesteps:
            u_val = int(round(pulp.value(u[(g.id, t)])))
            p_val = float(pulp.value(p[(g.id, t)]))
            v_val = int(round(pulp.value(v[(g.id, t)])))
            w_val = int(round(pulp.value(w[(g.id, t)])))

            commitment.append(u_val)
            power_output.append(p_val)

            gen_fuel_cost += g.fuel_cost_per_mwh * p_val
            gen_noload_cost += (g.no_load_cost + g.labor_cost_per_h) * u_val
            if g.has_thermal_startup and y_hot:
                gen_startup_cost += (
                    g.hot_start_cost * pulp.value(y_hot[(g.id, t)])
                    + g.warm_start_cost * pulp.value(y_warm[(g.id, t)])
                    + g.cold_start_cost * pulp.value(y_cold[(g.id, t)])
                )
            else:
                gen_startup_cost += g.startup_cost * v_val
            gen_shutdown_cost += g.shutdown_cost * w_val

            if is_storage:
                soc_mwh.append(float(pulp.value(soc[(g.id, t)])))
                charge_mw.append(float(pulp.value(p_ch[(g.id, t)])))
                discharge_mw.append(float(pulp.value(p_dis[(g.id, t)])))

        schedule = GeneratorSchedule(
            generator_id=g.id,
            commitment=commitment,
            power_output_mw=power_output,
            startup_cost=gen_startup_cost,
            shutdown_cost=gen_shutdown_cost,
            fuel_cost=gen_fuel_cost,
            no_load_cost=gen_noload_cost,
            soc_mwh=soc_mwh,
            charge_mw=charge_mw,
            discharge_mw=discharge_mw,
        )
        result.schedules.append(schedule)

        logger.info(
            "Generator %s: committed=%d/%d periods, cost=%.1f",
            g.id,
            sum(commitment),
            len(timesteps),
            schedule.total_cost,
        )

    # --- Extract interconnection flow results ------------------------------
    if interconnections and f:
        saturated_ids = []
        for ic in interconnections:
            flow_values = []
            for t in timesteps:
                flow_val = float(pulp.value(f[(ic.id, t)]))
                flow_values.append(flow_val)

            ic_flow = InterconnectionFlow(
                interconnection_id=ic.id,
                flow_mw=flow_values,
            )
            result.interconnection_flows.append(ic_flow)

            max_abs_flow = max(abs(fv) for fv in flow_values) if flow_values else 0.0
            is_saturated = max_abs_flow >= ic.capacity_mw * 0.999
            if is_saturated:
                saturated_ids.append(ic.id)

            logger.info(
                "Interconnection %s: max_flow=%.1f MW / %.1f MW capacity%s",
                ic.id,
                max_abs_flow,
                ic.capacity_mw,
                " (SATURATED)" if is_saturated else "",
            )

        if saturated_ids:
            logger.info(
                "Saturated interconnections: %s",
                ", ".join(saturated_ids),
            )


def _diagnose_infeasibility(
    result: UCResult,
    generators: List[Generator],
    timesteps: List[int],
    demand: List[float],
) -> None:
    """Add diagnostic information when the solver reports infeasibility.

    Identifies timesteps where demand exceeds total available capacity
    (accounting for maintenance) and reports the shortfall.
    """
    infeasible_periods = []
    for idx, t in enumerate(timesteps):
        available_cap = 0.0
        maint_count = 0
        for g in generators:
            in_maintenance = any(
                start_h <= t < end_h for start_h, end_h in g.maintenance_windows
            )
            if in_maintenance:
                maint_count += 1
            else:
                available_cap += g.capacity_mw
        if available_cap < demand[idx]:
            infeasible_periods.append(
                (t, demand[idx], available_cap, maint_count)
            )

    if infeasible_periods:
        for t, d, cap, mc in infeasible_periods:
            msg = (
                f"Infeasible at t={t}: demand={d:.1f} MW, "
                f"available_capacity={cap:.1f} MW, "
                f"shortfall={d - cap:.1f} MW"
            )
            if mc > 0:
                msg += f", generators_in_maintenance={mc}"
            result.warnings.append(msg)
            logger.warning(msg)
    else:
        msg = (
            "Infeasibility detected but capacity appears sufficient at "
            "all timesteps. Check min-uptime, min-downtime, or ramp "
            "constraints for conflicting requirements."
        )
        result.warnings.append(msg)
        logger.warning(msg)
