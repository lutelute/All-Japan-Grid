"""N-1 shortfall: the after-the-fact score and the near-optimal objective must agree."""

import pytest

from src.uc.benchmark_cases import synthetic_case
from src.uc.risk import congested_hours, n1_shortfall, near_optimal_hook
from src.uc.solver import solve_uc


def solved(params, **kw):
    params.solver_name, params.mip_gap = "HiGHS", 1e-6
    params.solver_options = {"threads": 1}
    for k, v in kw.items():
        setattr(params, k, v)
    return solve_uc(params)


@pytest.mark.parametrize("trip_cap", [None, 150.0])
def test_near_optimal_lowers_shortfall_within_the_cost_cap(trip_cap):
    ref_params = synthetic_case(16, 8, 17)
    ref = solved(ref_params)
    assert ref.feasibility_verified
    before = n1_shortfall(ref_params, ref, trip_cap_mw=trip_cap)
    cap = ref.solver_objective * 1.02
    params = synthetic_case(16, 8, 17)
    r = solved(params, model_hook=near_optimal_hook(cap, trip_cap_mw=trip_cap, interconnections=params.interconnections))
    assert r.feasibility_verified
    after = n1_shortfall(params, r, trip_cap_mw=trip_cap)
    assert r.solver_objective <= cap * (1 + 1e-9)
    assert r.secondary_objective == pytest.approx(after["total_mwh"], abs=1e-3)
    assert after["total_mwh"] <= before["total_mwh"] + 1e-6
    assert congested_hours(params, r) >= 0


def test_zero_slack_keeps_the_optimal_cost():
    ref_params = synthetic_case(16, 8, 17)
    ref = solved(ref_params)
    params = synthetic_case(16, 8, 17)
    r = solved(params, model_hook=near_optimal_hook(ref.solver_objective * (1 + 1e-7), interconnections=params.interconnections))
    assert r.feasibility_verified
    assert r.total_cost == pytest.approx(ref.total_cost, rel=1e-6)
