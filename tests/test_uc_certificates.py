"""Independent regression cases for bounds, physical boundaries and cost history."""

import numpy as np
import pulp
import pytest

from src.model.generator import Generator
from src.uc.benchmark_cases import synthetic_case
from src.uc.models import DemandProfile, GeneratorSchedule, TimeHorizon, UCParameters, UCResult
from src.uc.rolling import RollingUCConfig, solve_rolling_uc
from src.uc.solver import solve_uc
from src.uc.validation import validate_uc_solution


def unit(**kw):
    values = dict(id="g", name="g", capacity_mw=100, fuel_type="lng",
                  fuel_cost_per_mwh=10, startup_cost=100, min_up_time_h=1, min_down_time_h=1)
    values.update(kw)
    return Generator(**values)


def case(generators, demand, **kw):
    return UCParameters(generators=generators, demand=DemandProfile(demands=demand),
                        time_horizon=TimeHorizon(num_periods=len(demand)), **kw)


@pytest.mark.parametrize("solver", ["HiGHS", "SCIP"])
def test_native_bounds_bracket_known_cost(solver):
    if solver == "SCIP":
        pytest.importorskip("pyscipopt")
    r = solve_uc(case([unit()], [40., 60.], solver_name=solver))
    assert r.feasibility_verified
    assert r.primal_bound == pytest.approx(1100)
    assert r.dual_bound == pytest.approx(1100)
    assert r.gap == pytest.approx(0)
    assert r.effective_solver == ("SCIP_PY" if solver == "SCIP" else "HiGHS")


@pytest.mark.parametrize("history,expected", [(-2, 100), (-4, 300), (-12, 700)])
def test_pre_horizon_downtime_controls_startup_cost(history, expected):
    g = unit(hot_start_cost=100, warm_start_cost=300, cold_start_cost=700,
             warm_start_h=4, cold_start_h=12)
    r = solve_uc(case([g], [50.], initial_history_h={"g": history}))
    assert r.feasibility_verified
    assert r.total_cost == pytest.approx(500 + expected)
    assert r.schedules[0].startup_cost == pytest.approx(expected)


def test_initial_output_limits_dispatch():
    cheap = unit(ramp_up_mw_per_h=10)
    backup = unit(id="b", name="b", fuel_cost_per_mwh=100)
    p = case([cheap, backup], [80.], initial_commitment={"g": 1},
             initial_history_h={"g": 4}, initial_power_mw={"g": 20})
    r = solve_uc(p)
    assert r.feasibility_verified
    assert next(s for s in r.schedules if s.generator_id == "g").power_output_mw == pytest.approx([30.])
    # A deliberately corrupted schedule still balances demand but violates the ramp.
    for s in r.schedules:
        s.power_output_mw = [80.] if s.generator_id == "g" else [0.]
    checked = validate_uc_solution(p, r, check_objective=False)
    assert not checked["passed"]
    assert checked["max_residuals"]["ramp_up"] == pytest.approx(50)


def test_objective_check_is_one_sided():
    p = case([unit()], [40., 60.])
    r = solve_uc(p)
    exact = r.solver_objective
    r.solver_objective = exact + 3500      # e.g. a phantom start-up + shut-down in one hour
    checked = validate_uc_solution(p, r)
    assert checked["passed"]
    assert checked["objective_overstatement"] == pytest.approx(3500)
    r.solver_objective = exact - 3500      # the model would under-price the plan
    assert not validate_uc_solution(p, r)["passed"]


def test_rolling_carries_ramp_and_does_not_claim_annual_optimality():
    g = unit(ramp_up_mw_per_h=10, startup_cost=0)
    b = unit(id="b", name="b", fuel_cost_per_mwh=100, startup_cost=0)
    r = solve_rolling_uc([g, b], np.array([20., 80., 80.]), None, [],
                        RollingUCConfig(window_h=1, step_h=1, reserve_margin=0), progress=False)
    assert r.is_complete and not r.is_optimal
    assert r.status == "Feasible" and r.dual_bound is None and r.gap is None
    assert r.schedules["g"].power_output_mw == pytest.approx([20., 30., 40.])
    assert r.primal_bound == pytest.approx(9900)


def test_rolling_cost_uses_cold_history():
    g = unit(hot_start_cost=100, warm_start_cost=300, cold_start_cost=700,
             warm_start_h=4, cold_start_h=12)
    r = solve_rolling_uc([g], np.full(4, 50.), None, [],
                        RollingUCConfig(window_h=2, step_h=1, reserve_margin=0), progress=False)
    assert r.is_complete
    assert r.total_cost == pytest.approx(2700)


def test_unknown_solver_fails_explicitly():
    with pytest.raises(ValueError, match="Unsupported UC solver"):
        solve_uc(case([unit()], [50.], solver_name="not-a-solver"))


def test_requested_scip_unavailable_does_not_fall_back(monkeypatch):
    monkeypatch.setattr(pulp.SCIP_PY, "available", lambda self: False)
    with pytest.raises(RuntimeError, match="unavailable"):
        solve_uc(case([unit()], [50.], solver_name="SCIP"))


def test_scip_solution_limit_preserves_incumbent():
    pytest.importorskip("pyscipopt")
    p = synthetic_case(units=12, hours=12)
    p.solver_name = "SCIP"
    p.solver_options = {"options": ["limits/solutions=1"]}
    r = solve_uc(p)
    assert r.termination_reason == "sollimit"
    assert r.has_incumbent and r.feasibility_verified
    assert r.status == "Feasible"
    assert r.primal_bound is not None
    assert r.gap is None or r.gap > 0


def test_no_incumbent_has_no_primal_bound():
    pytest.importorskip("pyscipopt")
    p = synthetic_case(units=12, hours=12)
    p.solver_name = "SCIP"
    p.solver_time_limit_s = 1e-9
    r = solve_uc(p)
    assert not r.has_incumbent and not r.schedules
    assert r.primal_bound is None and r.gap is None


def test_spill_cost_is_retained_in_bound_objective():
    from src.uc.models import Interconnection
    g = unit(p_min_mw=50, region="a", min_up_time_h=3)
    b = unit(id="b", name="b", region="b")
    p = case([g, b], [20.], initial_commitment={"g": 1}, initial_history_h={"g": 1},
             interconnections=[Interconnection("ic", "ic", "a", "b", 1)],
             regional_demands={"a": [10.], "b": [10.]})
    r = solve_uc(p)
    assert r.feasibility_verified
    assert r.primal_bound == pytest.approx(r.solver_objective)
    assert r.solver_objective > r.total_cost + 1e6
    assert r.dual_bound <= r.primal_bound + 1e-3


def test_nonhourly_model_rejected_until_units_are_supported():
    p = case([unit()], [50.])
    p.time_horizon = TimeHorizon(num_periods=1, period_duration_h=0.5)
    with pytest.raises(ValueError, match="1-hour"):
        solve_uc(p)


def test_invalid_rolling_window_rejected():
    with pytest.raises(ValueError, match="step_h"):
        RollingUCConfig(window_h=24, step_h=48)


def test_fractional_lp_cannot_be_reported_as_verified_uc():
    r = solve_uc(case([unit(no_load_cost=100)], [25.], solver_options={"mip": False}))
    assert not r.feasibility_verified
    assert r.primal_bound is None and r.gap is None
    assert r.dual_bound == pytest.approx(300)


def test_rounding_invalidates_old_incumbent_certificate():
    from src.uc.adaptive_solver import _postprocess_lp_relaxation
    r = UCResult(status="Optimal", feasibility_verified=True, primal_bound=10, dual_bound=9,
                 gap=0.1, schedules=[GeneratorSchedule("g", [0.6], [60.])])
    _postprocess_lp_relaxation(r)
    assert r.status == "Unverified" and not r.feasibility_verified
    assert r.primal_bound is None and r.gap is None
    assert r.dual_bound == 9


def test_highs_thread_count_can_change_within_one_process():
    # HiGHS keeps one thread pool per process; without a reset the second
    # solve stopped with "Not Set" and was reported as Not Solved (10-24).
    assert solve_uc(case([unit()], [40., 60.])).feasibility_verified
    r = solve_uc(case([unit()], [40., 60.], solver_options={"threads": 1}))
    assert r.termination_reason == "Optimal"
    assert r.feasibility_verified


def test_per_period_reserve_requirement_is_enforced_and_checked():
    # A staged solve gives each region its own share of the system reserve per hour.
    gens = [unit(id="a", name="a", capacity_mw=100), unit(id="b", name="b", capacity_mw=100, fuel_cost_per_mwh=20)]
    p = case(gens, [50., 50.], reserve_requirement_mw=[150., 50.])
    r = solve_uc(p)
    assert r.feasibility_verified
    on = [sum(100 * s.commitment[t] for s in r.schedules) for t in range(2)]
    assert on[0] >= 150 and on[1] >= 50
    short = solve_uc(case(gens, [50., 50.]))
    assert not validate_uc_solution(p, short, check_objective=False)["passed"]
