"""Solver strategy selection for adaptive unit commitment.

Maps a :class:`~src.uc.hardware_detector.HardwareProfile` and problem
size (number of generators, number of time periods) to a concrete
solver configuration.  Three tiers are supported:

- **HIGH** (>= 4 cores, >= 8 GB RAM): full MILP with tight MIP gap,
  long time limit, multi-threaded solver.
- **MID** (>= 2 cores, >= 4 GB RAM): MILP with relaxed 5 % gap,
  regional decomposition for large problems, shorter time limit.
- **LOW** (< 2 cores or < 4 GB RAM): LP relaxation via
  ``solver_options={"mip": False}``, aggressive gap tolerance,
  time-window decomposition, short time limits.

The public entry point is :func:`select_strategy`, which returns a
:class:`SolverConfig` dataclass describing all solver parameters for the
chosen tier.

Usage::

    from src.uc.hardware_detector import detect_hardware
    from src.uc.solver_strategy import select_strategy

    profile = detect_hardware()
    config = select_strategy(profile, n_generators=50, n_periods=24)
    print(config.tier, config.solver_name, config.mip_gap)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.uc.hardware_detector import HardwareProfile
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Tier thresholds (configurable at module level)
# ---------------------------------------------------------------------------

#: Minimum physical cores for HIGH tier.
HIGH_TIER_MIN_CORES: int = 4
#: Minimum available RAM (GB) for HIGH tier.
HIGH_TIER_MIN_RAM_GB: float = 8.0

#: Minimum physical cores for MID tier.
MID_TIER_MIN_CORES: int = 2
#: Minimum available RAM (GB) for MID tier.
MID_TIER_MIN_RAM_GB: float = 4.0

#: Generator count threshold above which decomposition is recommended
#: for MID-tier solves.
LARGE_PROBLEM_GENERATOR_THRESHOLD: int = 50

# ---------------------------------------------------------------------------
# Preferred solver order
# ---------------------------------------------------------------------------

#: Solver preference order (highest priority first).  Mirrors the
#: preference chain used by ``_select_solver`` in ``src/uc/solver.py``.
_SOLVER_PREFERENCE = ["HiGHS_CMD", "PULP_CBC_CMD"]


# ---------------------------------------------------------------------------
# Enum & dataclass
# ---------------------------------------------------------------------------


class SolverTier(Enum):
    """Solver strategy tier based on available hardware resources.

    Attributes:
        HIGH: Full MILP, tight gap, multi-threaded.
        MID: MILP with relaxed gap, decomposition for large problems.
        LOW: LP relaxation, aggressive gap, short time limits.
    """

    HIGH = "high"
    MID = "mid"
    LOW = "low"


@dataclass
class SolverConfig:
    """Concrete solver configuration produced by :func:`select_strategy`.

    Attributes:
        tier: The :class:`SolverTier` that was selected.
        solver_name: PuLP solver name to use (e.g., ``"HiGHS"``).
        time_limit_s: Maximum solver wall-clock time in seconds.
        mip_gap: Relative MIP optimality gap tolerance (e.g., 0.01
            for 1 %).
        threads: Number of solver threads to allocate.
        use_decomposition: Whether to decompose the problem before
            solving.
        decomposition_strategy: Decomposition strategy name (e.g.,
            ``"regional"``, ``"time_window"``).  ``None`` when
            decomposition is not used.
        use_lp_relaxation: Whether to relax integer/binary variables
            to continuous (LP relaxation).
        description: Human-readable explanation of the selected
            strategy, suitable for user-facing output.
    """

    tier: SolverTier
    solver_name: str
    time_limit_s: float
    mip_gap: float
    threads: int
    use_decomposition: bool
    decomposition_strategy: Optional[str]
    use_lp_relaxation: bool
    description: str

    def __post_init__(self) -> None:
        """Validate solver configuration parameters."""
        if self.time_limit_s <= 0:
            raise ValueError(
                f"time_limit_s must be positive, got {self.time_limit_s}"
            )
        if self.mip_gap < 0 or self.mip_gap > 1:
            raise ValueError(
                f"mip_gap must be between 0 and 1, got {self.mip_gap}"
            )
        if self.threads < 1:
            raise ValueError(
                f"threads must be >= 1, got {self.threads}"
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pick_solver(available_solvers: list) -> str:
    """Choose the best available solver from the preference list.

    Args:
        available_solvers: Solver names reported by
            :func:`~src.uc.hardware_detector.detect_available_solvers`.

    Returns:
        Solver name string.  Falls back to ``"HiGHS"`` (PuLP's default
        name mapping) when no preferred solver is found.
    """
    available_set = set(available_solvers)
    for solver in _SOLVER_PREFERENCE:
        if solver in available_set:
            return solver

    # Fallback — PuLP bundles CBC so PULP_CBC_CMD should always work
    logger.warning(
        "No preferred solver found in %s; falling back to HiGHS",
        available_solvers,
    )
    return "HiGHS"


def _classify_tier(profile: HardwareProfile) -> SolverTier:
    """Classify hardware into a solver tier.

    Args:
        profile: Detected hardware profile.

    Returns:
        The appropriate :class:`SolverTier`.
    """
    if (
        profile.physical_cores >= HIGH_TIER_MIN_CORES
        and profile.available_ram_gb >= HIGH_TIER_MIN_RAM_GB
    ):
        return SolverTier.HIGH

    if (
        profile.physical_cores >= MID_TIER_MIN_CORES
        and profile.available_ram_gb >= MID_TIER_MIN_RAM_GB
    ):
        return SolverTier.MID

    return SolverTier.LOW


def _estimate_problem_memory_mb(
    n_generators: int,
    n_periods: int,
) -> float:
    """Estimate memory footprint of the UC problem in megabytes.

    Each generator-period combination creates approximately 5 decision
    variables (commitment, power, startup, shutdown, reserve), each
    requiring ~8 bytes for a float64 coefficient plus solver overhead
    (~10x for sparse matrix storage and solver workspace).

    Args:
        n_generators: Number of generators in the problem.
        n_periods: Number of time periods.

    Returns:
        Estimated memory usage in megabytes.
    """
    n_vars = n_generators * n_periods * 5
    bytes_per_var = 8 * 10  # coefficient + solver overhead
    return (n_vars * bytes_per_var) / (1024 ** 2)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def select_strategy(
    profile: HardwareProfile,
    n_generators: int,
    n_periods: int,
) -> SolverConfig:
    """Select the optimal solver configuration for the given hardware and problem.

    Classifies the hardware into a tier (HIGH / MID / LOW) and builds a
    :class:`SolverConfig` with appropriate solver name, MIP gap,
    time limit, thread count, and decomposition settings.  Large
    problems on MID-tier hardware trigger regional decomposition.

    Args:
        profile: Detected hardware capabilities.
        n_generators: Number of generators in the UC problem.
        n_periods: Number of time periods in the planning horizon.

    Returns:
        A :class:`SolverConfig` describing the recommended solver
        configuration.

    Example::

        from src.uc.hardware_detector import detect_hardware
        config = select_strategy(detect_hardware(), 50, 24)
        print(config.tier, config.mip_gap)
    """
    tier = _classify_tier(profile)
    solver_name = _pick_solver(profile.available_solvers)
    est_mem_mb = _estimate_problem_memory_mb(n_generators, n_periods)

    logger.info(
        "Strategy selection: tier=%s, solver=%s, generators=%d, "
        "periods=%d, estimated_memory=%.1f MB",
        tier.value,
        solver_name,
        n_generators,
        n_periods,
        est_mem_mb,
    )

    # Warn if estimated memory approaches available RAM
    available_ram_mb = profile.available_ram_gb * 1024
    if est_mem_mb > available_ram_mb * 0.5:
        logger.warning(
            "Estimated problem memory (%.0f MB) exceeds 50%% of "
            "available RAM (%.0f MB); consider decomposition or "
            "reducing problem size",
            est_mem_mb,
            available_ram_mb,
        )

    if tier == SolverTier.HIGH:
        return _build_high_config(profile, solver_name, n_generators)

    if tier == SolverTier.MID:
        return _build_mid_config(profile, solver_name, n_generators)

    return _build_low_config(profile, solver_name, n_generators, n_periods)


def _build_high_config(
    profile: HardwareProfile,
    solver_name: str,
    n_generators: int,
) -> SolverConfig:
    """Build solver configuration for HIGH tier.

    Full MILP with tight gap (1 %), generous time limit, and
    multi-threaded solver.
    """
    threads = max(1, profile.physical_cores)
    description = (
        f"HIGH tier: full MILP solve with {threads} threads, "
        f"1% MIP gap, 600s time limit"
    )
    logger.info(description)

    return SolverConfig(
        tier=SolverTier.HIGH,
        solver_name=solver_name,
        time_limit_s=600.0,
        mip_gap=0.01,
        threads=threads,
        use_decomposition=False,
        decomposition_strategy=None,
        use_lp_relaxation=False,
        description=description,
    )


def _build_mid_config(
    profile: HardwareProfile,
    solver_name: str,
    n_generators: int,
) -> SolverConfig:
    """Build solver configuration for MID tier.

    MILP with relaxed gap (5 %) and shorter time limit. Enables
    regional decomposition when the generator count exceeds the
    large-problem threshold.
    """
    threads = max(1, profile.physical_cores)
    use_decomp = n_generators >= LARGE_PROBLEM_GENERATOR_THRESHOLD
    decomp_strategy = "regional" if use_decomp else None

    decomp_note = (
        f" with regional decomposition ({n_generators} generators)"
        if use_decomp
        else ""
    )
    description = (
        f"MID tier: MILP solve{decomp_note}, {threads} threads, "
        f"5% MIP gap, 300s time limit"
    )
    logger.info(description)

    return SolverConfig(
        tier=SolverTier.MID,
        solver_name=solver_name,
        time_limit_s=300.0,
        mip_gap=0.05,
        threads=threads,
        use_decomposition=use_decomp,
        decomposition_strategy=decomp_strategy,
        use_lp_relaxation=False,
        description=description,
    )


def _build_low_config(
    profile: HardwareProfile,
    solver_name: str,
    n_generators: int,
    n_periods: int,
) -> SolverConfig:
    """Build solver configuration for LOW tier.

    LP relaxation (binary variables treated as continuous [0, 1]) with
    aggressive gap tolerance (10 %) and short time limit.  Enables
    time-window decomposition for problems with many periods.
    """
    threads = max(1, profile.physical_cores)
    use_decomp = n_periods > 24 or n_generators >= LARGE_PROBLEM_GENERATOR_THRESHOLD
    decomp_strategy = "time_window" if use_decomp else None

    decomp_note = " with time-window decomposition" if use_decomp else ""
    description = (
        f"LOW tier: LP relaxation{decomp_note}, {threads} thread(s), "
        f"10% gap tolerance, 120s time limit"
    )
    logger.info(description)

    return SolverConfig(
        tier=SolverTier.LOW,
        solver_name=solver_name,
        time_limit_s=120.0,
        mip_gap=0.10,
        threads=threads,
        use_decomposition=use_decomp,
        decomposition_strategy=decomp_strategy,
        use_lp_relaxation=True,
        description=description,
    )
