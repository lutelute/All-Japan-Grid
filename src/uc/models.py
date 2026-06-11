"""Data models for unit commitment (UC) analysis.

Defines dataclasses for specifying UC problem inputs (time horizon,
demand profile, solver parameters) and capturing optimisation results
(generator schedules, costs, solve metrics).

Usage::

    from src.uc.models import UCParameters, TimeHorizon, DemandProfile, UCResult

    th = TimeHorizon(num_periods=24, period_duration_h=1.0)
    dp = DemandProfile(demands=[100.0] * 24)
    params = UCParameters(generators=gens, demand=dp, time_horizon=th)
    # ... run solver ...
    result = UCResult(status="Optimal", total_cost=12345.0)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.model.generator import Generator


@dataclass
class TimeHorizon:
    """Time horizon specification for a UC problem.

    Attributes:
        num_periods: Number of time periods in the planning horizon.
        period_duration_h: Duration of each period in hours (e.g., 1.0
            for hourly, 0.5 for 30-minute intervals).
        start_period: Index of the first period (default 0). Useful for
            rolling-horizon or warm-start scenarios.
    """

    num_periods: int
    period_duration_h: float = 1.0
    start_period: int = 0

    def __post_init__(self) -> None:
        """Validate time horizon parameters."""
        if self.num_periods < 1:
            raise ValueError(
                f"num_periods must be >= 1, got {self.num_periods}"
            )
        if self.period_duration_h <= 0:
            raise ValueError(
                f"period_duration_h must be positive, got {self.period_duration_h}"
            )
        if self.start_period < 0:
            raise ValueError(
                f"start_period must be non-negative, got {self.start_period}"
            )

    @property
    def total_hours(self) -> float:
        """Total duration of the planning horizon in hours."""
        return self.num_periods * self.period_duration_h

    @property
    def period_indices(self) -> List[int]:
        """List of period indices from start_period."""
        return list(range(self.start_period, self.start_period + self.num_periods))


@dataclass
class DemandProfile:
    """Demand profile specifying load requirements per time period.

    Attributes:
        demands: List of demand values (MW) indexed by period.
            Length must match ``TimeHorizon.num_periods`` when used
            together in a ``UCParameters`` instance.
    """

    demands: List[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate demand values."""
        for i, d in enumerate(self.demands):
            if d < 0:
                raise ValueError(
                    f"Demand at period {i} must be non-negative, got {d}"
                )

    @property
    def peak_demand(self) -> float:
        """Maximum demand across all periods."""
        if not self.demands:
            return 0.0
        return max(self.demands)

    @property
    def total_energy_mwh(self) -> float:
        """Total energy demand (MW * periods). Accurate when period = 1h."""
        return sum(self.demands)


@dataclass
class Interconnection:
    """An inter-regional transmission interconnection.

    Attributes:
        id: Unique identifier (e.g., ``'ic_001'``).
        name_en: English name of the interconnection.
        from_region: Source region identifier.
        to_region: Destination region identifier.
        capacity_mw: Maximum transfer capacity in MW.
        type: Interconnection type (``'AC'``, ``'HVDC'``, ``'FC'``).
    """

    id: str
    name_en: str
    from_region: str
    to_region: str
    capacity_mw: float
    type: str = "AC"

    def __post_init__(self) -> None:
        """Validate interconnection parameters."""
        if not self.id:
            raise ValueError("Interconnection id must not be empty")
        if self.capacity_mw <= 0:
            raise ValueError(
                f"Interconnection capacity_mw must be positive, got {self.capacity_mw}"
            )
        if self.from_region == self.to_region:
            raise ValueError(
                f"from_region and to_region must differ, both are '{self.from_region}'"
            )


@dataclass
class InterconnectionFlow:
    """Flow results for a single interconnection across the planning horizon.

    Positive flow indicates power transfer from ``from_region`` to
    ``to_region``. Negative flow indicates the reverse direction.

    Attributes:
        interconnection_id: ID of the interconnection this flow belongs to.
        flow_mw: Power flow (MW) per period. Positive = from_region to
            to_region direction.
    """

    interconnection_id: str = ""
    flow_mw: List[float] = field(default_factory=list)


@dataclass
class UCParameters:
    """Input parameters for a unit commitment optimisation problem.

    Attributes:
        generators: List of Generator instances available for commitment.
        demand: Demand profile specifying load per period.
        time_horizon: Time horizon defining the planning window.
        reserve_margin: Required reserve margin as a fraction of demand
            (e.g., 0.10 for 10% reserve). Default is 0.0 (no reserve).
        solver_name: Name of the MIP solver to use (default ``"HiGHS"``).
        solver_time_limit_s: Maximum solver wall-clock time in seconds.
            ``None`` means no limit.
        mip_gap: Relative MIP optimality gap tolerance (e.g., 0.01 for 1%).
            ``None`` uses the solver default.
        solver_options: Additional solver-specific options passed through
            to the backend.
        interconnections: List of inter-regional interconnections for
            transmission capacity constraints. Empty list disables
            interconnection modelling.
        regional_demands: Optional per-region demand series (MW) keyed by
            region identifier.  When provided alongside interconnections,
            used directly for nodal balance constraints instead of the
            capacity-fraction split of the total demand.
        extract_duals: When ``True``, after an optimal MILP solve the
            integer variables are fixed at their solution and the model is
            re-solved as an LP to extract dual prices (marginal prices).
            Results land in ``UCResult.system_lambda`` (system-wide demand
            balance) or ``UCResult.regional_lmp`` (nodal balance), in
            currency units per MWh.  Adds one LP solve of overhead.
        warm_start_schedules: Optional previous solution (e.g. the
            schedules of a prior, similar solve such as the preceding
            rolling-horizon window) injected as a user MIP start.
            Schedules are matched by ``generator_id`` and period index;
            extra periods are ignored, missing values are left free.
            Supported by the HiGHS (highspy API) backend; other backends
            ignore the hint.  An imperfect start is repaired by the
            solver, so time-shifted solutions are acceptable.
        initial_commitment: Commitment state (``generator_id -> 0/1``)
            immediately before the first period.  Used by the
            startup/shutdown logic at t=0 so that units already running
            do not incur a phantom startup cost.  Missing units default
            to 0 (offline) — the legacy single-shot assumption.
        initial_history_h: Signed pre-horizon streak per generator
            (``+h`` = continuously ON for h hours, ``-h`` = OFF).
            Enforces remaining minimum up/down time at the window head.
            Both fields are the state-carrying interface for
            rolling-horizon solves (src/uc/rolling.py).
    """

    generators: List[Generator] = field(default_factory=list)
    demand: Optional[DemandProfile] = None
    time_horizon: Optional[TimeHorizon] = None
    reserve_margin: float = 0.0
    solver_name: str = "HiGHS"
    solver_time_limit_s: Optional[float] = None
    mip_gap: Optional[float] = None
    solver_options: Dict[str, Any] = field(default_factory=dict)
    interconnections: List[Interconnection] = field(default_factory=list)
    regional_demands: Optional[Dict[str, List[float]]] = None
    extract_duals: bool = False
    warm_start_schedules: Optional[List["GeneratorSchedule"]] = None
    initial_commitment: Optional[Dict[str, int]] = None
    initial_history_h: Optional[Dict[str, int]] = None

    def __post_init__(self) -> None:
        """Validate UC parameters."""
        if self.reserve_margin < 0:
            raise ValueError(
                f"reserve_margin must be non-negative, got {self.reserve_margin}"
            )
        if self.solver_time_limit_s is not None and self.solver_time_limit_s <= 0:
            raise ValueError(
                f"solver_time_limit_s must be positive, got {self.solver_time_limit_s}"
            )
        if self.mip_gap is not None and (self.mip_gap < 0 or self.mip_gap > 1):
            raise ValueError(
                f"mip_gap must be between 0 and 1, got {self.mip_gap}"
            )
        # Validate demand length matches time horizon
        if (
            self.demand is not None
            and self.time_horizon is not None
            and len(self.demand.demands) != self.time_horizon.num_periods
        ):
            raise ValueError(
                f"Demand profile length ({len(self.demand.demands)}) "
                f"does not match time horizon periods ({self.time_horizon.num_periods})"
            )


@dataclass
class GeneratorSchedule:
    """Schedule for a single generator across the planning horizon.

    Attributes:
        generator_id: ID of the generator this schedule belongs to.
        commitment: Binary commitment status per period (1 = on, 0 = off).
        power_output_mw: Power output (MW) per period.
        startup_cost: Total startup costs incurred over the horizon.
        shutdown_cost: Total shutdown costs incurred over the horizon.
        fuel_cost: Total fuel costs incurred over the horizon.
        no_load_cost: Total no-load (fixed operating) costs over the horizon.
        soc_mwh: State of charge (MWh) per period for storage units.
        charge_mw: Charging power (MW) per period for storage units.
        discharge_mw: Discharging power (MW) per period for storage units.
    """

    generator_id: str = ""
    commitment: List[int] = field(default_factory=list)
    power_output_mw: List[float] = field(default_factory=list)
    startup_cost: float = 0.0
    shutdown_cost: float = 0.0
    fuel_cost: float = 0.0
    no_load_cost: float = 0.0
    soc_mwh: List[float] = field(default_factory=list)
    charge_mw: List[float] = field(default_factory=list)
    discharge_mw: List[float] = field(default_factory=list)

    @property
    def total_cost(self) -> float:
        """Total cost for this generator across the horizon."""
        return self.startup_cost + self.shutdown_cost + self.fuel_cost + self.no_load_cost

    @property
    def total_energy_mwh(self) -> float:
        """Total energy produced (MW * periods). Accurate when period = 1h."""
        return sum(self.power_output_mw)

    @property
    def num_startups(self) -> int:
        """Count of startup events in the commitment schedule."""
        count = 0
        for t in range(1, len(self.commitment)):
            if self.commitment[t] == 1 and self.commitment[t - 1] == 0:
                count += 1
        # First period counts as startup if unit is on
        if self.commitment and self.commitment[0] == 1:
            count += 1
        return count

    @property
    def capacity_factor(self) -> float:
        """Average capacity factor (0-1) over committed periods.

        Returns 0.0 if no periods are committed.
        """
        committed_periods = sum(self.commitment)
        if committed_periods == 0:
            return 0.0
        total_output = sum(self.power_output_mw)
        return total_output / committed_periods if committed_periods > 0 else 0.0


@dataclass
class UCResult:
    """Results from a unit commitment optimisation.

    Follows the ``PowerFlowResult`` pattern: status flag, result data,
    summary metrics, and a ``warnings`` list for non-fatal issues.

    Attributes:
        status: Solver status string (e.g., ``"Optimal"``, ``"Infeasible"``,
            ``"Unbounded"``, ``"Not Solved"``).
        schedules: List of ``GeneratorSchedule`` for each committed generator.
        total_cost: Total system cost over the planning horizon.
        solve_time_s: Wall-clock solve time in seconds.
        gap: Relative MIP optimality gap achieved (0.0 = proven optimal).
        warnings: Non-fatal issues encountered during setup or solve.
        interconnection_flows: Per-interconnection flow results across the
            planning horizon. Empty when interconnections are not modelled.
        system_lambda: Marginal system price per period (currency/MWh),
            extracted as the dual of the system-wide demand balance in the
            commitment-fixed LP re-solve.  ``None`` unless
            ``UCParameters.extract_duals`` was set and the model used the
            system-wide balance (no interconnections).
        regional_lmp: Marginal price per region per period (currency/MWh),
            duals of the nodal balance constraints in the commitment-fixed
            LP re-solve.  Empty unless ``extract_duals`` was set and nodal
            balance was active (interconnections present).  Differences
            between regions reflect interconnector congestion.
    """

    status: str = "Not Solved"
    schedules: List[GeneratorSchedule] = field(default_factory=list)
    total_cost: float = 0.0
    solve_time_s: float = 0.0
    gap: Optional[float] = None
    warnings: List[str] = field(default_factory=list)
    interconnection_flows: List[InterconnectionFlow] = field(default_factory=list)
    system_lambda: Optional[List[float]] = None
    regional_lmp: Dict[str, List[float]] = field(default_factory=dict)

    @property
    def is_optimal(self) -> bool:
        """Check if the solver found a proven optimal solution."""
        return self.status == "Optimal"

    @property
    def num_generators(self) -> int:
        """Number of generators with schedules in the result."""
        return len(self.schedules)

    @property
    def summary(self) -> dict:
        """Return a compact summary for logging."""
        return {
            "status": self.status,
            "total_cost": round(self.total_cost, 2),
            "num_generators": self.num_generators,
            "solve_time_s": round(self.solve_time_s, 2),
            "gap": round(self.gap, 6) if self.gap is not None else None,
            "warnings": len(self.warnings),
        }
