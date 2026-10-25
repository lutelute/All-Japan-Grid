"""Modular constraint builders for the unit commitment MILP formulation.

Each function adds a specific class of constraints to a PuLP model,
keeping the solver code decomposed and testable.  Constraint names
follow the pattern ``<type>_<generator>_t<period>`` so that
infeasibility diagnostics can pinpoint which constraint is violated.

Usage::

    import pulp
    from src.uc.constraints import (
        add_demand_balance_constraints,
        add_capacity_bounds_constraints,
        add_startup_shutdown_logic,
        add_min_uptime_constraints,
        add_min_downtime_constraints,
        add_ramp_constraints,
        add_maintenance_constraints,
        add_reserve_margin_constraints,
        add_storage_soc_constraints,
        add_transmission_capacity_constraints,
        add_nodal_balance_constraints,
    )

    model = pulp.LpProblem("UC", pulp.LpMinimize)
    # ... create variables u, p, v, w ...
    add_demand_balance_constraints(model, p, generators, timesteps, demand)
    add_capacity_bounds_constraints(model, u, p, generators, timesteps)
    # ... etc ...
"""

from typing import Dict, List, Optional, Tuple

import pulp

from src.model.generator import Generator
from src.uc.models import Interconnection
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


def add_demand_balance_constraints(
    model: pulp.LpProblem,
    p: Dict[Tuple[str, int], pulp.LpVariable],
    generators: List[Generator],
    timesteps: List[int],
    demand: List[float],
) -> int:
    """Add system-wide demand balance constraints.

    Ensures that total generation meets or exceeds demand at every
    time step:

        ``Σ_g p[g,t] >= demand[t]``  for all *t*

    Args:
        model: PuLP model to add constraints to.
        p: Power output variables indexed by ``(generator_id, timestep)``.
        generators: List of generators available for commitment.
        timesteps: List of time period indices.
        demand: Demand values (MW) indexed to match *timesteps*.

    Returns:
        Number of constraints added.
    """
    gen_ids = [g.id for g in generators]
    count = 0
    for idx, t in enumerate(timesteps):
        model += (
            pulp.lpSum(p[(g_id, t)] for g_id in gen_ids) >= demand[idx],
            f"demand_balance_t{t}",
        )
        count += 1
    logger.info(
        "Added %d demand balance constraints (%d timesteps)",
        count,
        len(timesteps),
    )
    return count


def add_capacity_bounds_constraints(
    model: pulp.LpProblem,
    u: Dict[Tuple[str, int], pulp.LpVariable],
    p: Dict[Tuple[str, int], pulp.LpVariable],
    generators: List[Generator],
    timesteps: List[int],
) -> int:
    """Add per-generator capacity bound constraints.

    When a generator is committed (``u=1``), its output must lie between
    its minimum and maximum capacity.  When off (``u=0``), output is
    forced to zero:

        ``p_min[g] * u[g,t] <= p[g,t] <= p_max[g] * u[g,t]``

    Args:
        model: PuLP model to add constraints to.
        u: Binary commitment variables indexed by ``(generator_id, timestep)``.
        p: Power output variables indexed by ``(generator_id, timestep)``.
        generators: List of generators available for commitment.
        timesteps: List of time period indices.

    Returns:
        Number of constraints added.
    """
    count = 0
    n_skipped = 0
    for g in generators:
        # Storage generators are bounded by charge/discharge limit
        # constraints instead of standard capacity bounds (which assume p >= 0).
        if hasattr(g, "is_storage") and g.is_storage:
            n_skipped += 1
            continue
        for t in timesteps:
            # Lower bound: p >= p_min * u
            model += (
                p[(g.id, t)] >= g.p_min_mw * u[(g.id, t)],
                f"cap_lb_{g.id}_t{t}",
            )
            count += 1
            # Upper bound: p <= p_max * u
            model += (
                p[(g.id, t)] <= g.capacity_mw * u[(g.id, t)],
                f"cap_ub_{g.id}_t{t}",
            )
            count += 1
    logger.info(
        "Added %d capacity bound constraints (%d generators × %d timesteps × 2, %d storage skipped)",
        count,
        len(generators) - n_skipped,
        len(timesteps),
        n_skipped,
    )
    return count


def add_startup_shutdown_logic(
    model: pulp.LpProblem,
    u: Dict[Tuple[str, int], pulp.LpVariable],
    v: Dict[Tuple[str, int], pulp.LpVariable],
    w: Dict[Tuple[str, int], pulp.LpVariable],
    generators: List[Generator],
    timesteps: List[int],
    initial_commitment: Optional[Dict[str, int]] = None,
) -> int:
    """Add startup/shutdown indicator linking constraints.

    Links the binary startup (*v*) and shutdown (*w*) indicators to
    commitment status changes:

        ``v[g,t] - w[g,t] = u[g,t] - u[g,t-1]``  for all *g*, *t*

    For the first time step, ``u[g,t-1]`` comes from
    ``initial_commitment`` (1 = was on just before the horizon, 0 = was
    off).  Generators missing from the mapping default to 0 (offline) —
    the historical behaviour.  Rolling-horizon callers must pass the
    final committed state of the previous window here, otherwise every
    window re-pays startup costs for units that were already running.

    Args:
        model: PuLP model to add constraints to.
        u: Binary commitment variables indexed by ``(generator_id, timestep)``.
        v: Binary startup indicator variables indexed by
            ``(generator_id, timestep)``.
        w: Binary shutdown indicator variables indexed by
            ``(generator_id, timestep)``.
        generators: List of generators available for commitment.
        timesteps: List of time period indices (must be sorted).
        initial_commitment: Optional mapping ``generator_id -> 0/1`` of
            the commitment state immediately before the first period.

    Returns:
        Number of constraints added.
    """
    initial_commitment = initial_commitment or {}
    count = 0
    for g in generators:
        u_init = int(initial_commitment.get(g.id, 0))
        for i, t in enumerate(timesteps):
            if i == 0:
                model += (
                    v[(g.id, t)] - w[(g.id, t)] == u[(g.id, t)] - u_init,
                    f"startup_shutdown_{g.id}_t{t}",
                )
            else:
                t_prev = timesteps[i - 1]
                model += (
                    v[(g.id, t)] - w[(g.id, t)]
                    == u[(g.id, t)] - u[(g.id, t_prev)],
                    f"startup_shutdown_{g.id}_t{t}",
                )
            count += 1
    logger.info(
        "Added %d startup/shutdown logic constraints (%d generators × %d timesteps)",
        count,
        len(generators),
        len(timesteps),
    )
    return count


def add_initial_history_constraints(
    model: pulp.LpProblem,
    u: Dict[Tuple[str, int], pulp.LpVariable],
    generators: List[Generator],
    timesteps: List[int],
    initial_history_h: Dict[str, int],
) -> int:
    """Enforce minimum up/down time remaining from pre-horizon history.

    For rolling-horizon solves the commitment history does not reset at
    the window boundary.  Given ``initial_history_h[g] = +h`` (unit has
    been continuously ON for *h* hours) or ``-h`` (continuously OFF), the
    unit must remain ON for ``max(0, min_up_time_h - h)`` further periods
    (resp. OFF for ``max(0, min_down_time_h - h)``).

    Args:
        model: PuLP model to add constraints to.
        u: Binary commitment variables indexed by ``(generator_id, timestep)``.
        generators: List of generators available for commitment.
        timesteps: List of time period indices (must be sorted).
        initial_history_h: Mapping ``generator_id -> signed hours``
            (positive = ON streak, negative = OFF streak, 0/absent = no
            binding history).

    Returns:
        Number of constraints added.
    """
    count = 0
    for g in generators:
        hist = int(initial_history_h.get(g.id, 0))
        if hist > 0:
            must_on = max(0, int(g.min_up_time_h) - hist)
            for t in timesteps[:must_on]:
                model += (
                    u[(g.id, t)] == 1,
                    f"init_must_on_{g.id}_t{t}",
                )
                count += 1
        elif hist < 0:
            must_off = max(0, int(g.min_down_time_h) + hist)  # hist is negative
            for t in timesteps[:must_off]:
                model += (
                    u[(g.id, t)] == 0,
                    f"init_must_off_{g.id}_t{t}",
                )
                count += 1
    if count:
        logger.info("Added %d initial-history must-run/stay-off constraints", count)
    return count


def add_min_uptime_constraints(
    model: pulp.LpProblem,
    u: Dict[Tuple[str, int], pulp.LpVariable],
    v: Dict[Tuple[str, int], pulp.LpVariable],
    generators: List[Generator],
    timesteps: List[int],
) -> int:
    """Add minimum up-time constraints.

    Once started, a generator must remain on for at least
    ``min_up_time_h`` consecutive periods:

        ``Σ_{τ=t-MUT+1}^{t} v[g,τ] <= u[g,t]``  for all *g*, *t*

    This ensures that if any startup occurred in the look-back window
    of length *MUT*, the generator must still be committed at *t*.

    Generators with ``min_up_time_h <= 1`` are skipped (no constraint
    needed beyond the single-period startup).

    Args:
        model: PuLP model to add constraints to.
        u: Binary commitment variables indexed by ``(generator_id, timestep)``.
        v: Binary startup indicator variables indexed by
            ``(generator_id, timestep)``.
        generators: List of generators available for commitment.
        timesteps: List of time period indices (must be sorted).

    Returns:
        Number of constraints added.
    """
    count = 0
    for g in generators:
        mut = g.min_up_time_h
        if mut <= 1:
            continue
        for i, t in enumerate(timesteps):
            # Look-back window: indices [max(0, i-mut+1), i]
            start_idx = max(0, i - mut + 1)
            window = timesteps[start_idx : i + 1]
            model += (
                pulp.lpSum(v[(g.id, tau)] for tau in window) <= u[(g.id, t)],
                f"min_up_{g.id}_t{t}",
            )
            count += 1
    n_skipped = sum(1 for g in generators if g.min_up_time_h <= 1)
    logger.info(
        "Added %d min-uptime constraints (%d generators active, %d skipped with MUT<=1)",
        count,
        len(generators) - n_skipped,
        n_skipped,
    )
    return count


def add_min_downtime_constraints(
    model: pulp.LpProblem,
    u: Dict[Tuple[str, int], pulp.LpVariable],
    w: Dict[Tuple[str, int], pulp.LpVariable],
    generators: List[Generator],
    timesteps: List[int],
) -> int:
    """Add minimum down-time constraints.

    Once shut down, a generator must remain off for at least
    ``min_down_time_h`` consecutive periods:

        ``Σ_{τ=t-MDT+1}^{t} w[g,τ] <= 1 - u[g,t]``  for all *g*, *t*

    This ensures that if any shutdown occurred in the look-back window
    of length *MDT*, the generator must still be offline at *t*.

    Generators with ``min_down_time_h <= 1`` are skipped (no constraint
    needed beyond the single-period shutdown).

    Args:
        model: PuLP model to add constraints to.
        u: Binary commitment variables indexed by ``(generator_id, timestep)``.
        w: Binary shutdown indicator variables indexed by
            ``(generator_id, timestep)``.
        generators: List of generators available for commitment.
        timesteps: List of time period indices (must be sorted).

    Returns:
        Number of constraints added.
    """
    count = 0
    for g in generators:
        mdt = g.min_down_time_h
        if mdt <= 1:
            continue
        for i, t in enumerate(timesteps):
            # Look-back window: indices [max(0, i-mdt+1), i]
            start_idx = max(0, i - mdt + 1)
            window = timesteps[start_idx : i + 1]
            model += (
                pulp.lpSum(w[(g.id, tau)] for tau in window) <= 1 - u[(g.id, t)],
                f"min_down_{g.id}_t{t}",
            )
            count += 1
    n_skipped = sum(1 for g in generators if g.min_down_time_h <= 1)
    logger.info(
        "Added %d min-downtime constraints (%d generators active, %d skipped with MDT<=1)",
        count,
        len(generators) - n_skipped,
        n_skipped,
    )
    return count


def add_ramp_constraints(
    model: pulp.LpProblem,
    p: Dict[Tuple[str, int], pulp.LpVariable],
    u: Dict[Tuple[str, int], pulp.LpVariable],
    generators: List[Generator],
    timesteps: List[int],
    initial_power_mw: Optional[Dict[str, float]] = None,
    initial_commitment: Optional[Dict[str, int]] = None,
) -> int:
    """Add ramp-rate limit constraints.

    Limits the change in power output between consecutive periods.
    Uses a big-M relaxation so that ramp constraints do not bind when
    a generator is starting up or shutting down:

        Ramp up:   ``p[g,t] - p[g,t-1] <= ramp_up[g] + Pmax[g] * (1 - u[g,t-1])``
        Ramp down: ``p[g,t-1] - p[g,t] <= ramp_down[g] + Pmax[g] * (1 - u[g,t])``

    When the generator was on in the previous period (``u[g,t-1]=1``),
    the big-M term vanishes and the ramp rate binds.  During startup or
    shutdown the constraint is relaxed.

    Generators with ``ramp_up_mw_per_h is None`` (unlimited ramp-up) or
    ``ramp_down_mw_per_h is None`` (unlimited ramp-down) skip the
    corresponding constraint.

    Args:
        model: PuLP model to add constraints to.
        p: Power output variables indexed by ``(generator_id, timestep)``.
        u: Binary commitment variables indexed by ``(generator_id, timestep)``.
        generators: List of generators available for commitment.
        timesteps: List of time period indices (must be sorted).

    Returns:
        Number of constraints added.
    """
    count = 0
    initial_power_mw = initial_power_mw or {}
    initial_commitment = initial_commitment or {}
    if timesteps:
        for g in generators:
            if g.id not in initial_power_mw:
                continue
            p0 = initial_power_mw[g.id]
            u0 = initial_commitment.get(g.id, 0)
            t0 = timesteps[0]
            if g.ramp_up_mw_per_h is not None:
                model += (p[(g.id, t0)] - p0 <= g.ramp_up_mw_per_h
                          + g.capacity_mw * (1 - u0), f"initial_ramp_up_{g.id}")
                count += 1
            if g.ramp_down_mw_per_h is not None:
                model += (p0 - p[(g.id, t0)] <= g.ramp_down_mw_per_h
                          + g.capacity_mw * (1 - u[(g.id, t0)]), f"initial_ramp_down_{g.id}")
                count += 1
    for g in generators:
        has_ramp_up = g.ramp_up_mw_per_h is not None
        has_ramp_down = g.ramp_down_mw_per_h is not None
        if not has_ramp_up and not has_ramp_down:
            continue
        for i in range(1, len(timesteps)):
            t = timesteps[i]
            t_prev = timesteps[i - 1]
            # Ramp-up constraint
            if has_ramp_up:
                model += (
                    p[(g.id, t)] - p[(g.id, t_prev)]
                    <= g.ramp_up_mw_per_h + g.capacity_mw * (1 - u[(g.id, t_prev)]),
                    f"ramp_up_{g.id}_t{t}",
                )
                count += 1
            # Ramp-down constraint
            if has_ramp_down:
                model += (
                    p[(g.id, t_prev)] - p[(g.id, t)]
                    <= g.ramp_down_mw_per_h + g.capacity_mw * (1 - u[(g.id, t)]),
                    f"ramp_down_{g.id}_t{t}",
                )
                count += 1
    n_unlimited = sum(
        1
        for g in generators
        if g.ramp_up_mw_per_h is None and g.ramp_down_mw_per_h is None
    )
    logger.info(
        "Added %d ramp constraints (%d generators with limits, %d unlimited)",
        count,
        len(generators) - n_unlimited,
        n_unlimited,
    )
    return count


def add_maintenance_constraints(
    model: pulp.LpProblem,
    u: Dict[Tuple[str, int], pulp.LpVariable],
    generators: List[Generator],
    timesteps: List[int],
) -> int:
    """Add maintenance window constraints.

    Forces a generator offline during its scheduled maintenance
    windows:

        ``u[g,t] = 0``  for all *g*, *t* where *t* falls within a
        maintenance window of generator *g*.

    A time step *t* falls within window ``(start_h, end_h)`` when
    ``start_h <= t < end_h``.

    Args:
        model: PuLP model to add constraints to.
        u: Binary commitment variables indexed by ``(generator_id, timestep)``.
        generators: List of generators available for commitment.
        timesteps: List of time period indices.

    Returns:
        Number of constraints added.
    """
    count = 0
    for g in generators:
        if not g.maintenance_windows:
            continue
        # Build a set of timesteps under maintenance for fast lookup
        maint_periods = set()
        for start_h, end_h in g.maintenance_windows:
            for t in timesteps:
                if start_h <= t < end_h:
                    maint_periods.add(t)
        for t in sorted(maint_periods):
            model += (
                u[(g.id, t)] == 0,
                f"maint_{g.id}_t{t}",
            )
            count += 1
        if maint_periods:
            logger.info(
                "Generator %s: forced offline for %d maintenance periods",
                g.id,
                len(maint_periods),
            )
    logger.info("Added %d maintenance constraints in total", count)
    return count


def add_reserve_margin_constraints(
    model: pulp.LpProblem,
    u: Dict[Tuple[str, int], pulp.LpVariable],
    generators: List[Generator],
    timesteps: List[int],
    demand: List[float],
    reserve_margin: float,
    requirement: Optional[List[float]] = None,
) -> int:
    """Add spinning-reserve margin constraints.

    Ensures that committed capacity headroom exceeds demand by the
    required reserve margin at every time step:

        ``Σ_g Pmax[g] * u[g,t] >= demand[t] * (1 + reserve_margin)``

    This guarantees that committed generators have enough total
    capacity to absorb demand spikes without requiring additional
    startups.

    When *reserve_margin* is 0.0 (or negative), no constraints are
    added.

    Args:
        model: PuLP model to add constraints to.
        u: Binary commitment variables indexed by ``(generator_id, timestep)``.
        generators: List of generators available for commitment.
        timesteps: List of time period indices.
        demand: Demand values (MW) indexed to match *timesteps*.
        reserve_margin: Required reserve as a fraction of demand
            (e.g., 0.10 for 10%).

    Returns:
        Number of constraints added.
    """
    if requirement is None and reserve_margin <= 0:
        logger.info("Reserve margin is %.2f; skipping reserve constraints", reserve_margin)
        return 0

    count = 0
    for idx, t in enumerate(timesteps):
        # A per-period requirement (MW of committed capacity) replaces demand*(1+margin),
        # e.g. a region's share of the system reserve in a staged solve.
        required = requirement[idx] if requirement is not None else demand[idx] * (1.0 + reserve_margin)
        model += (
            pulp.lpSum(g.capacity_mw * u[(g.id, t)] for g in generators)
            >= required,
            f"reserve_margin_t{t}",
        )
        count += 1
    logger.info(
        "Added %d reserve margin constraints (margin=%.1f%%)",
        count,
        reserve_margin * 100,
    )
    return count


def add_storage_soc_constraints(
    model: pulp.LpProblem,
    p: Dict[Tuple[str, int], pulp.LpVariable],
    p_ch: Dict[Tuple[str, int], pulp.LpVariable],
    p_dis: Dict[Tuple[str, int], pulp.LpVariable],
    z_ch: Dict[Tuple[str, int], pulp.LpVariable],
    soc: Dict[Tuple[str, int], pulp.LpVariable],
    u: Dict[Tuple[str, int], pulp.LpVariable],
    generators: List[Generator],
    timesteps: List[int],
    period_duration_h: float = 1.0,
) -> int:
    """Add state-of-charge (SOC) constraints for storage generators.

    Implements time-coupled energy storage constraints for both pumped
    hydro and battery generators.  Non-storage generators (where
    ``g.is_storage`` is False) are skipped.

    For each storage generator *g* at each timestep *t*, the following
    constraints are added:

    1. **SOC balance** (time-coupled):
        ``soc[g,t] = soc[g,t-1] + η_ch × p_ch[g,t] × Δt
        - (1/η_dis) × p_dis[g,t] × Δt``
        For t=0, ``soc[g,t-1]`` is the initial SOC
        (``initial_soc_fraction × storage_capacity_mwh``).

    2. **SOC bounds**: Enforced via variable bounds
        (``lowBound=0, upBound=storage_capacity_mwh``).

    3. **Charge power limit**:
        ``p_ch[g,t] <= charge_rate_mw × z_ch[g,t]``

    4. **Discharge power limit**:
        ``p_dis[g,t] <= discharge_rate_mw × (1 - z_ch[g,t])``

    5. **Net power linking**:
        ``p[g,t] = p_dis[g,t] - p_ch[g,t]``

    6. **Commitment linking**:
        ``p_ch[g,t] <= charge_rate_mw × u[g,t]``
        ``p_dis[g,t] <= discharge_rate_mw × u[g,t]``

    7. **Terminal SOC** (one per storage generator):
        ``soc[g,T] >= min_terminal_soc_fraction × storage_capacity_mwh``

    Args:
        model: PuLP model to add constraints to.
        p: Net power output variables indexed by
            ``(generator_id, timestep)``.
        p_ch: Charging power variables indexed by
            ``(generator_id, timestep)``.
        p_dis: Discharging power variables indexed by
            ``(generator_id, timestep)``.
        z_ch: Binary charge-mode indicator variables indexed by
            ``(generator_id, timestep)``.
        soc: State-of-charge variables indexed by
            ``(generator_id, timestep)``.
        u: Binary commitment variables indexed by
            ``(generator_id, timestep)``.
        generators: List of generators (storage and non-storage).
        timesteps: List of time period indices (must be sorted).
        period_duration_h: Duration of each period in hours.

    Returns:
        Number of constraints added.
    """
    count = 0
    n_storage = 0
    n_skipped = 0

    for g in generators:
        if not (hasattr(g, "is_storage") and g.is_storage):
            n_skipped += 1
            continue

        n_storage += 1

        # Resolve charge/discharge rates (None defaults to capacity_mw)
        charge_rate = g.charge_rate_mw if g.charge_rate_mw is not None else g.capacity_mw
        discharge_rate = (
            g.discharge_rate_mw if g.discharge_rate_mw is not None else g.capacity_mw
        )
        eta_ch = g.charge_efficiency
        eta_dis = g.discharge_efficiency
        capacity_mwh = g.storage_capacity_mwh
        initial_soc = g.initial_soc_fraction * capacity_mwh
        dt = period_duration_h

        for i, t in enumerate(timesteps):
            # (1) SOC balance
            if i == 0:
                # First period: use initial SOC as soc[g, t-1]
                model += (
                    soc[(g.id, t)]
                    == initial_soc
                    + eta_ch * p_ch[(g.id, t)] * dt
                    - (1.0 / eta_dis) * p_dis[(g.id, t)] * dt,
                    f"soc_balance_{g.id}_t{t}",
                )
            else:
                t_prev = timesteps[i - 1]
                model += (
                    soc[(g.id, t)]
                    == soc[(g.id, t_prev)]
                    + eta_ch * p_ch[(g.id, t)] * dt
                    - (1.0 / eta_dis) * p_dis[(g.id, t)] * dt,
                    f"soc_balance_{g.id}_t{t}",
                )
            count += 1

            # (2) SOC bounds — enforced via variable bounds (set externally)

            # (3) Charge power limit: p_ch <= charge_rate * z_ch
            model += (
                p_ch[(g.id, t)] <= charge_rate * z_ch[(g.id, t)],
                f"charge_limit_{g.id}_t{t}",
            )
            count += 1

            # (4) Discharge power limit: p_dis <= discharge_rate * (1 - z_ch)
            model += (
                p_dis[(g.id, t)] <= discharge_rate * (1 - z_ch[(g.id, t)]),
                f"discharge_limit_{g.id}_t{t}",
            )
            count += 1

            # (5) Net power linking: p = p_dis - p_ch
            model += (
                p[(g.id, t)] == p_dis[(g.id, t)] - p_ch[(g.id, t)],
                f"net_power_{g.id}_t{t}",
            )
            count += 1

            # (6) Commitment linking: charge and discharge require commitment
            model += (
                p_ch[(g.id, t)] <= charge_rate * u[(g.id, t)],
                f"commit_ch_{g.id}_t{t}",
            )
            count += 1
            model += (
                p_dis[(g.id, t)] <= discharge_rate * u[(g.id, t)],
                f"commit_dis_{g.id}_t{t}",
            )
            count += 1

        # (7) Terminal SOC: soc[g,T] >= min_terminal_soc_fraction * capacity
        if timesteps and g.min_terminal_soc_fraction > 0:
            t_last = timesteps[-1]
            model += (
                soc[(g.id, t_last)]
                >= g.min_terminal_soc_fraction * capacity_mwh,
                f"terminal_soc_{g.id}",
            )
            count += 1

    logger.info(
        "Added %d storage SOC constraints (%d storage generators, %d non-storage skipped)",
        count,
        n_storage,
        n_skipped,
    )
    return count


def add_transmission_capacity_constraints(
    model: pulp.LpProblem,
    f: Dict[Tuple[str, int], pulp.LpVariable],
    interconnections: List[Interconnection],
    timesteps: List[int],
) -> int:
    """Add transmission capacity constraints for interconnections.

    Limits the power flow on each interconnection to its rated capacity,
    direction-aware (2026-08-19 — OCCTO運用容量は方向非対称: 例 関門
    順850/逆2,850MW):

        ``f[ic,t] <= cap_fwd[ic]``    (from→to 方向の上限)
        ``f[ic,t] >= -cap_rev[ic]``   (to→from 方向の上限)

    Positive flow represents power transfer from ``from_region`` to
    ``to_region``; negative flow represents the reverse direction.
    ``cap_fwd``/``cap_rev`` fall back to the legacy symmetric
    ``capacity_mw`` when per-direction values are absent.

    Args:
        model: PuLP model to add constraints to.
        f: Flow variables indexed by ``(interconnection_id, timestep)``.
        interconnections: List of interconnections to constrain.
        timesteps: List of time period indices.

    Returns:
        Number of constraints added.
    """
    count = 0
    for ic in interconnections:
        cap_fwd = getattr(ic, "cap_fwd", ic.capacity_mw)
        cap_rev = getattr(ic, "cap_rev", ic.capacity_mw)
        for t in timesteps:
            # Upper bound: f <= forward capacity
            model += (
                f[(ic.id, t)] <= cap_fwd,
                f"tx_cap_ub_{ic.id}_t{t}",
            )
            count += 1
            # Lower bound: f >= -reverse capacity
            model += (
                f[(ic.id, t)] >= -cap_rev,
                f"tx_cap_lb_{ic.id}_t{t}",
            )
            count += 1
    logger.info(
        "Added %d transmission capacity constraints (%d interconnections × %d timesteps × 2)",
        count,
        len(interconnections),
        len(timesteps),
    )
    return count


def add_startup_type_constraints(
    model: pulp.LpProblem,
    u: Dict[Tuple[str, int], pulp.LpVariable],
    v: Dict[Tuple[str, int], pulp.LpVariable],
    y_hot: Dict[Tuple[str, int], pulp.LpVariable],
    y_warm: Dict[Tuple[str, int], pulp.LpVariable],
    y_cold: Dict[Tuple[str, int], pulp.LpVariable],
    generators: List[Generator],
    timesteps: List[int],
    initial_history_h: Optional[Dict[str, int]] = None,
    initial_commitment: Optional[Dict[str, int]] = None,
) -> int:
    """Add cold/warm/hot startup-type partitioning constraints.

    For generators with ``has_thermal_startup=True``, each startup event
    ``v[g,t]=1`` is classified as hot, warm, or cold depending on how long
    the unit has been offline:

    - **Hot**  : offline for fewer than ``warm_start_h`` consecutive periods.
    - **Warm** : offline >= ``warm_start_h`` but < ``cold_start_h`` periods.
    - **Cold** : offline >= ``cold_start_h`` consecutive periods.

    Constraints added per generator per timestep:

    1. **Partition**      : ``y_hot + y_warm + y_cold = v``
    2. **Upper bounds**   : ``y_hot, y_warm, y_cold <= v``
    3. **Cold detection** : ``y_cold >= v - Σ_{τ∈Tc} u[g,τ]``
    4. **Warm detection** : ``y_warm + y_cold >= v - Σ_{τ∈Tw} u[g,τ]``

    Generators with ``has_thermal_startup=False`` are skipped (they use
    the single ``startup_cost`` via ``v[g,t]`` in the objective).

    Returns:
        Number of constraints added.
    """
    count = 0
    initial_history_h = initial_history_h or {}
    initial_commitment = initial_commitment or {}
    n_thermal = 0
    n_skipped = 0
    for g in generators:
        if not g.has_thermal_startup:
            n_skipped += 1
            continue
        n_thermal += 1
        Tw = g.warm_start_h
        Tc = g.cold_start_h

        for i, t in enumerate(timesteps):
            # 1. Partition: y_hot + y_warm + y_cold == v
            model += (
                y_hot[(g.id, t)] + y_warm[(g.id, t)] + y_cold[(g.id, t)]
                == v[(g.id, t)],
                f"su_partition_{g.id}_t{t}",
            )
            count += 1

            # 2. Upper bounds <= v
            for y_var, tag in ((y_hot, "hot"), (y_warm, "warm"), (y_cold, "cold")):
                model += (
                    y_var[(g.id, t)] <= v[(g.id, t)],
                    f"su_ub_{tag}_{g.id}_t{t}",
                )
                count += 1

            # Look-back windows (clipped to available history)
            warm_window = [timesteps[j] for j in range(max(0, i - Tw), i)]
            cold_window = [timesteps[j] for j in range(max(0, i - Tc), i)]

            # An ON in the previous L periods means downtime < L.
            # Include the last known pre-horizon ON, even when the look-back
            # reaches before this window. Missing OFF history means fully cold.
            hist = initial_history_h.get(
                g.id, 1 if initial_commitment.get(g.id, 0) else -max(Tc, 1),
            )
            for label, length, window, active in (
                ("hot", Tw, warm_window, y_hot[(g.id, t)]),
                ("not_cold", Tc, cold_window,
                 y_hot[(g.id, t)] + y_warm[(g.id, t)]),
            ):
                pre_on = int(i < length and (hist > 0 or length - i > -hist))
                recent = pulp.lpSum(u[(g.id, tau)] for tau in window) + pre_on
                model += (active <= recent, f"su_{label}_ub_{g.id}_t{t}")
                model += (max(1, length) * active >= recent
                          - max(1, length) * (1 - v[(g.id, t)]),
                          f"su_{label}_lb_{g.id}_t{t}")
                count += 2

    logger.info(
        "Added %d startup-type constraints (%d thermal generators, %d skipped)",
        count,
        n_thermal,
        n_skipped,
    )
    return count


def add_startup_type_shutdown_cuts(
    model: pulp.LpProblem,
    w: Dict[Tuple[str, int], pulp.LpVariable],
    y_hot: Dict[Tuple[str, int], pulp.LpVariable],
    y_warm: Dict[Tuple[str, int], pulp.LpVariable],
    generators: List[Generator],
    timesteps: List[int],
    initial_history_h: Optional[Dict[str, int]] = None,
    initial_commitment: Optional[Dict[str, int]] = None,
) -> int:
    """Strengthen startup-type detection with shutdown windows (valid inequalities).

    ``add_startup_type_constraints`` allows a hot start when Σu over the
    look-back window is positive.  In the LP relaxation a fractional u
    (e.g. 0.5 for hours) satisfies this without any shutdown, so the bound
    prices cold starts as hot.  A start at t is hot (warm) only if the unit
    shut down within the last ``warm_start_h`` (``cold_start_h``) periods:

        ``y_hot[g,t]            <= Σ_{τ=t-Tw+1}^{t-1} w[g,τ] + pre``
        ``y_hot[g,t] + y_warm[g,t] <= Σ_{τ=t-Tc+1}^{t-1} w[g,τ] + pre``

    ``pre`` is 1 when the pre-horizon shutdown falls inside the window.
    Every integer solution of the existing model satisfies these cuts when
    v and w cannot both be 1 in one period, which the min up/down
    constraints imply for MUT >= 2 and MDT >= 2; other units are skipped.

    Returns:
        Number of constraints added.
    """
    count = 0
    initial_history_h = initial_history_h or {}
    initial_commitment = initial_commitment or {}
    for g in generators:
        if not g.has_thermal_startup or g.min_up_time_h <= 1 or g.min_down_time_h <= 1:
            continue
        u0 = int(initial_commitment.get(g.id, 0))
        hist = initial_history_h.get(g.id, 1 if u0 else -max(g.cold_start_h, 1))
        for i, t in enumerate(timesteps):
            for label, length, active in (
                ("hot", g.warm_start_h, y_hot[(g.id, t)]),
                ("not_cold", g.cold_start_h, y_hot[(g.id, t)] + y_warm[(g.id, t)]),
            ):
                window = [timesteps[j] for j in range(max(0, i - length + 1), i)]
                # A shutdown before t0 is not a w in the model: an OFF streak of
                # -hist periods, or an ON history whose t0 logic starts from u0 = 0.
                pre = int((hist <= 0 and i - hist < length) or (hist > 0 and not u0 and i < length))
                model += (active <= pulp.lpSum(w[(g.id, tau)] for tau in window) + pre,
                          f"su_{label}_sd_window_{g.id}_t{t}")
                count += 1
    logger.info("Added %d startup-type shutdown-window cuts", count)
    return count


def add_tight_ramp_cuts(
    model: pulp.LpProblem,
    p: Dict[Tuple[str, int], pulp.LpVariable],
    u: Dict[Tuple[str, int], pulp.LpVariable],
    v: Dict[Tuple[str, int], pulp.LpVariable],
    w: Dict[Tuple[str, int], pulp.LpVariable],
    generators: List[Generator],
    timesteps: List[int],
) -> int:
    """Strengthen ramp limits with startup/shutdown indicators (valid inequalities).

    The big-M ramp in ``add_ramp_constraints`` relaxes by ``Pmax(1-u)``,
    which a fractional u opens wide in the LP.  With the start-up and
    shut-down capability equal to Pmax (the current model's semantics):

        ``p[g,t] - p[g,t-1] <= RU·u[g,t-1] + Pmax·v[g,t]``
        ``p[g,t-1] - p[g,t] <= RD·u[g,t]   + Pmax·w[g,t]``

    Each integer case (on→on, off→on, on→off, off→off) satisfies both,
    so the integer feasible set is unchanged.

    Returns:
        Number of constraints added.
    """
    count = 0
    for g in generators:
        if g.is_storage:
            continue
        for i in range(1, len(timesteps)):
            t, t_prev = timesteps[i], timesteps[i - 1]
            if g.ramp_up_mw_per_h is not None:
                model += (p[(g.id, t)] - p[(g.id, t_prev)]
                          <= g.ramp_up_mw_per_h * u[(g.id, t_prev)] + g.capacity_mw * v[(g.id, t)],
                          f"ramp_up_tight_{g.id}_t{t}")
                count += 1
            if g.ramp_down_mw_per_h is not None:
                model += (p[(g.id, t_prev)] - p[(g.id, t)]
                          <= g.ramp_down_mw_per_h * u[(g.id, t)] + g.capacity_mw * w[(g.id, t)],
                          f"ramp_down_tight_{g.id}_t{t}")
                count += 1
    logger.info("Added %d tight ramp cuts", count)
    return count


def add_nodal_balance_constraints(
    model: pulp.LpProblem,
    p: Dict[Tuple[str, int], pulp.LpVariable],
    f: Dict[Tuple[str, int], pulp.LpVariable],
    generators: List[Generator],
    interconnections: List[Interconnection],
    timesteps: List[int],
    regional_demand: Dict[str, List[float]],
    spill: Optional[Dict[Tuple[str, int], pulp.LpVariable]] = None,
) -> int:
    """Add nodal (per-region) power balance constraints.

    Enforces exact balance in each region at every time step:

        ``Σ_{g∈r} p[g,t] + Σ_{ic: to=r} f[ic,t]
        - Σ_{ic: from=r} f[ic,t] - spill[r,t] == demand[r][idx]``

    2026-08-19 修正: 従来は ``>=`` (不等式)で、地域余剰の自由廃棄を許して
    いた。九州の昼間断面で純需要2.5GWに対し8.2GWを発電し、スケジュール上の
    関門潮流(上限2.8GW)と5.7GWの帳尻が合わない解を「Optimal」として返して
    いた(uc_to_pf注入がこの幻の余剰をそのままPFに再現し、関門実潮流が運用
    容量の2倍になった)。等式+明示spill変数(目的関数でペナルティ)に変更し、
    余剰は帳簿(UCResult.regional_spill_mw)に必ず現れる。spill>0 は実運用の
    出力制御に相当する。

    Positive flow on an interconnection represents power transfer from
    ``from_region`` to ``to_region``.

    Args:
        model: PuLP model to add constraints to.
        p: Power output variables indexed by ``(generator_id, timestep)``.
        f: Flow variables indexed by ``(interconnection_id, timestep)``.
        generators: List of generators available for commitment.
        interconnections: List of inter-regional interconnections.
        timesteps: List of time period indices.
        regional_demand: Mapping of region identifier to demand series
            (MW) aligned with *timesteps*.
        spill: Non-negative surplus variables indexed by
            ``(region, timestep)``. ``None`` reproduces the legacy ``>=``
            relaxation (回帰比較用のみ — 新規コードでは必ず渡すこと).

    Returns:
        Number of constraints added.
    """
    # Group generator IDs by region
    region_gen_ids: Dict[str, List[str]] = {}
    for g in generators:
        region_gen_ids.setdefault(g.region, []).append(g.id)

    # Group interconnections by to_region and from_region
    ic_to_region: Dict[str, List[Interconnection]] = {}
    ic_from_region: Dict[str, List[Interconnection]] = {}
    for ic in interconnections:
        ic_to_region.setdefault(ic.to_region, []).append(ic)
        ic_from_region.setdefault(ic.from_region, []).append(ic)

    count = 0
    for region, demands in regional_demand.items():
        gen_ids = region_gen_ids.get(region, [])
        inflows = ic_to_region.get(region, [])
        outflows = ic_from_region.get(region, [])

        for idx, t in enumerate(timesteps):
            generation = pulp.lpSum(p[(g_id, t)] for g_id in gen_ids)
            imports = pulp.lpSum(f[(ic.id, t)] for ic in inflows)
            exports = pulp.lpSum(f[(ic.id, t)] for ic in outflows)

            if spill is not None:
                model += (
                    generation + imports - exports - spill[(region, t)]
                    == demands[idx],
                    f"nodal_bal_{region}_t{t}",
                )
            else:
                model += (
                    generation + imports - exports >= demands[idx],
                    f"nodal_bal_{region}_t{t}",
                )
            count += 1

    logger.info(
        "Added %d nodal balance constraints (%d regions × %d timesteps)",
        count,
        len(regional_demand),
        len(timesteps),
    )
    return count
