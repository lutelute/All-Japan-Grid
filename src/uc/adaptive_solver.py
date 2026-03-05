"""Adaptive solver orchestrator for unit commitment.

Combines hardware detection, solver strategy selection, and graceful
degradation into a single entry point.  The orchestrator:

1. Detects hardware via :func:`~src.uc.hardware_detector.detect_hardware`.
2. Selects an appropriate solver tier via
   :func:`~src.uc.solver_strategy.select_strategy`.
3. Attempts to solve using the selected tier.
4. On failure or timeout, automatically degrades to the next lower tier
   (HIGH -> MID -> LOW).
5. Returns an :class:`AdaptiveUCResult` containing the solve result,
   hardware profile, solver configuration, tier used, and degradation
   history.

For LOW-tier solves using LP relaxation, fractional commitment values
are rounded (>= 0.5 -> 1, < 0.5 -> 0) in a post-processing step.

Usage::

    from src.uc.adaptive_solver import solve_adaptive
    from src.uc.models import UCParameters, TimeHorizon, DemandProfile
    from src.model.generator import Generator

    gens = [Generator(id='g1', name='G1', capacity_mw=200,
                      fuel_type='coal', fuel_cost_per_mwh=30)]
    th = TimeHorizon(num_periods=24, period_duration_h=1.0)
    dp = DemandProfile(demands=[100.0] * 24)
    params = UCParameters(generators=gens, demand=dp, time_horizon=th)
    result = solve_adaptive(params)
    print(result.tier_used, result.result.status, result.result.total_cost)
"""

import time
from dataclasses import dataclass, field
from typing import List, Optional

from src.uc.decomposition import create_decomposer
from src.uc.hardware_detector import HardwareProfile, detect_hardware
from src.uc.models import UCParameters, UCResult
from src.uc.solver import solve_uc
from src.uc.solver_strategy import SolverConfig, SolverTier, select_strategy
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

# Statuses that indicate a solve failure requiring degradation
_FAILURE_STATUSES = {"Infeasible", "Unbounded", "Not Solved", "Undefined", "Unknown"}

# Degradation path: ordered list from highest to lowest tier
_DEGRADATION_ORDER = [SolverTier.HIGH, SolverTier.MID, SolverTier.LOW]


@dataclass
class AdaptiveUCResult:
    """Result from an adaptive UC solve including metadata.

    Wraps the core :class:`~src.uc.models.UCResult` with additional
    context about the hardware profile, solver configuration, tier
    used, and any degradation history.

    Attributes:
        result: The underlying UC solve result.
        hardware_profile: Detected hardware capabilities used for
            strategy selection.
        solver_config: The solver configuration that produced the
            final result.
        tier_used: The :class:`~src.uc.solver_strategy.SolverTier`
            that produced the final result (may differ from the
            initially selected tier if degradation occurred).
        degradation_history: Chronological log of tier attempts and
            outcomes.  Each entry describes a tier attempt and its
            result (e.g., ``"HIGH: Infeasible, degrading to MID"``).
        total_time_s: Total wall-clock time for the adaptive solve
            including all degradation attempts.
    """

    result: UCResult = field(default_factory=UCResult)
    hardware_profile: Optional[HardwareProfile] = None
    solver_config: Optional[SolverConfig] = None
    tier_used: Optional[SolverTier] = None
    degradation_history: List[str] = field(default_factory=list)
    total_time_s: float = 0.0


def solve_adaptive(
    params: UCParameters,
    force_tier: Optional[SolverTier] = None,
    verbose: bool = True,
) -> AdaptiveUCResult:
    """Solve a UC problem with adaptive strategy selection and graceful degradation.

    Detects hardware, selects the optimal solver tier, attempts the
    solve, and automatically degrades to a lower tier on failure or
    timeout.  The degradation path is HIGH -> MID -> LOW.

    When LP relaxation is used (LOW tier), binary commitment variables
    are treated as continuous [0, 1].  Post-processing rounds fractional
    commitments >= 0.5 to 1 and < 0.5 to 0.

    Args:
        params: UC problem specification including generators, demand
            profile, time horizon, and solver configuration.
        force_tier: If provided, overrides the auto-detected tier.
            Useful for testing or when the user wants to force a
            specific strategy.
        verbose: If ``True``, logs tier selection details at INFO level.

    Returns:
        :class:`AdaptiveUCResult` containing the solve result, hardware
        profile, solver configuration, tier used, and degradation
        history.
    """
    start_time = time.monotonic()
    adaptive_result = AdaptiveUCResult()

    # --- Step 1: Detect hardware -------------------------------------------
    profile = detect_hardware()
    adaptive_result.hardware_profile = profile

    if verbose:
        logger.info(
            "Adaptive solver: %d cores, %.1f GB RAM, solvers=%s",
            profile.physical_cores,
            profile.available_ram_gb,
            profile.available_solvers,
        )

    # --- Step 2: Determine problem size ------------------------------------
    n_generators = len(params.generators)
    n_periods = (
        params.time_horizon.num_periods if params.time_horizon else 0
    )

    # --- Step 3: Select initial strategy -----------------------------------
    if force_tier is not None:
        initial_config = _build_config_for_tier(
            force_tier, profile, n_generators, n_periods,
        )
        adaptive_result.degradation_history.append(
            f"Forced tier: {force_tier.value}"
        )
        if verbose:
            logger.info(
                "Adaptive solver: forced to %s tier", force_tier.value,
            )
    else:
        initial_config = select_strategy(profile, n_generators, n_periods)
        if verbose:
            logger.info(
                "Adaptive solver: auto-selected %s tier — %s",
                initial_config.tier.value,
                initial_config.description,
            )

    # --- Step 4: Build degradation path ------------------------------------
    start_idx = _DEGRADATION_ORDER.index(initial_config.tier)
    tiers_to_try = _DEGRADATION_ORDER[start_idx:]

    # --- Step 5: Attempt solve with degradation ----------------------------
    last_result: Optional[UCResult] = None
    last_config: Optional[SolverConfig] = None

    for i, tier in enumerate(tiers_to_try):
        if i == 0:
            config = initial_config
        else:
            config = _build_config_for_tier(
                tier, profile, n_generators, n_periods,
            )
            adaptive_result.degradation_history.append(
                f"Degrading to {tier.value} tier — {config.description}"
            )
            if verbose:
                logger.warning(
                    "Adaptive solver: degrading to %s tier — %s",
                    tier.value,
                    config.description,
                )

        # Apply solver configuration to parameters
        solve_params = _apply_config(params, config)

        # Execute solve
        try:
            uc_result = _execute_solve(solve_params, config)
        except Exception as exc:
            msg = (
                f"{tier.value.upper()} tier: solve raised {type(exc).__name__}: "
                f"{exc}"
            )
            adaptive_result.degradation_history.append(msg)
            logger.warning("Adaptive solver: %s", msg)
            last_result = UCResult(
                status="Not Solved",
                warnings=[msg],
            )
            last_config = config
            continue

        last_result = uc_result
        last_config = config

        # Check if solve succeeded
        if uc_result.status == "Optimal":
            adaptive_result.degradation_history.append(
                f"{tier.value.upper()} tier: Optimal (cost={uc_result.total_cost:.2f})"
            )
            if verbose:
                logger.info(
                    "Adaptive solver: %s tier succeeded — status=%s, "
                    "cost=%.2f, time=%.2fs",
                    tier.value.upper(),
                    uc_result.status,
                    uc_result.total_cost,
                    uc_result.solve_time_s,
                )
            break

        # Solve did not produce optimal — record and try next tier
        msg = (
            f"{tier.value.upper()} tier: {uc_result.status}"
        )
        if i < len(tiers_to_try) - 1:
            next_tier = tiers_to_try[i + 1]
            msg += f", degrading to {next_tier.value.upper()}"
        else:
            msg += ", no further tiers available"

        adaptive_result.degradation_history.append(msg)
        if verbose:
            logger.warning("Adaptive solver: %s", msg)

    # --- Step 6: Post-process LP relaxation results ------------------------
    if (
        last_result is not None
        and last_config is not None
        and last_config.use_lp_relaxation
        and last_result.schedules
    ):
        _postprocess_lp_relaxation(last_result)

    # --- Step 7: Assemble final result -------------------------------------
    if last_result is None:
        last_result = UCResult(
            status="Not Solved",
            warnings=["No solve attempted"],
        )
    if last_config is None:
        last_config = initial_config

    adaptive_result.result = last_result
    adaptive_result.solver_config = last_config
    adaptive_result.tier_used = last_config.tier
    adaptive_result.total_time_s = time.monotonic() - start_time

    if verbose:
        logger.info(
            "Adaptive solver complete: tier_used=%s, status=%s, "
            "cost=%.2f, total_time=%.2fs, degradations=%d",
            adaptive_result.tier_used.value,
            adaptive_result.result.status,
            adaptive_result.result.total_cost,
            adaptive_result.total_time_s,
            max(0, len(adaptive_result.degradation_history) - 1),
        )

    return adaptive_result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_config_for_tier(
    tier: SolverTier,
    profile: HardwareProfile,
    n_generators: int,
    n_periods: int,
) -> SolverConfig:
    """Build a solver configuration for a specific tier.

    Uses :func:`select_strategy` with a synthetic hardware profile
    that maps to the requested tier, or directly constructs the
    configuration when the tier is forced.

    Args:
        tier: The desired solver tier.
        profile: Actual hardware profile (used for thread count and
            solver availability).
        n_generators: Number of generators in the problem.
        n_periods: Number of time periods.

    Returns:
        A :class:`SolverConfig` for the requested tier.
    """
    from src.uc.solver_strategy import (
        _build_high_config,
        _build_low_config,
        _build_mid_config,
        _pick_solver,
    )

    solver_name = _pick_solver(profile.available_solvers)

    if tier == SolverTier.HIGH:
        return _build_high_config(profile, solver_name, n_generators)
    if tier == SolverTier.MID:
        return _build_mid_config(profile, solver_name, n_generators)
    return _build_low_config(profile, solver_name, n_generators, n_periods)


def _apply_config(
    params: UCParameters,
    config: SolverConfig,
) -> UCParameters:
    """Create a copy of UCParameters with solver configuration applied.

    Applies solver name, time limit, MIP gap, thread count, and
    LP relaxation settings from the :class:`SolverConfig` onto the
    UC parameters without mutating the original.

    Args:
        params: Original UC parameters.
        config: Solver configuration to apply.

    Returns:
        New :class:`UCParameters` with updated solver settings.
    """
    solver_options = dict(params.solver_options)

    # Set thread count
    if config.threads > 1:
        solver_options["threads"] = config.threads

    # Set LP relaxation (disable MIP)
    if config.use_lp_relaxation:
        solver_options["mip"] = False

    return UCParameters(
        generators=params.generators,
        demand=params.demand,
        time_horizon=params.time_horizon,
        reserve_margin=params.reserve_margin,
        solver_name=config.solver_name,
        solver_time_limit_s=config.time_limit_s,
        mip_gap=config.mip_gap,
        solver_options=solver_options,
        interconnections=params.interconnections,
    )


def _execute_solve(
    params: UCParameters,
    config: SolverConfig,
) -> UCResult:
    """Execute a solve using the appropriate method for the configuration.

    When decomposition is enabled, uses :func:`create_decomposer`
    to partition and solve.  Otherwise, calls :func:`solve_uc` directly.

    Args:
        params: UC parameters with solver configuration applied.
        config: Solver configuration describing the solve strategy.

    Returns:
        :class:`UCResult` from the solve.
    """
    if config.use_decomposition and config.decomposition_strategy:
        logger.info(
            "Executing decomposed solve: strategy=%s",
            config.decomposition_strategy,
        )
        decomposer = create_decomposer(config.decomposition_strategy)
        return decomposer.solve_decomposed(params)

    logger.info("Executing direct solve: solver=%s", config.solver_name)
    return solve_uc(params)


def _postprocess_lp_relaxation(result: UCResult) -> None:
    """Round fractional commitment values from LP relaxation.

    When LP relaxation is used, binary commitment variables become
    continuous [0, 1] and may produce fractional values.  This
    post-processing step rounds commitment values >= 0.5 to 1 and
    < 0.5 to 0.

    The rounded solution is not guaranteed to satisfy min up/down time
    constraints.  A warning is logged when rounding is applied.

    Args:
        result: UC result with potentially fractional commitments
            (modified in place).
    """
    rounded_count = 0
    total_values = 0

    for schedule in result.schedules:
        original_commitment = list(schedule.commitment)
        rounded_commitment = []

        for c in original_commitment:
            total_values += 1
            if isinstance(c, float) and c != int(c):
                rounded_count += 1
                rounded_commitment.append(1 if c >= 0.5 else 0)
            else:
                rounded_commitment.append(int(c) if c >= 0.5 else 0)

        schedule.commitment = rounded_commitment

    if rounded_count > 0:
        msg = (
            f"LP relaxation: rounded {rounded_count}/{total_values} "
            f"fractional commitment values. Solution is approximate "
            f"and may violate min up/down time constraints."
        )
        result.warnings.append(msg)
        logger.warning(msg)
    else:
        logger.info(
            "LP relaxation: all %d commitment values were integral "
            "(no rounding needed)",
            total_values,
        )
