"""Valid inequalities must keep the optimum and may only raise the LP bound."""

import pytest

from src.uc.benchmark_cases import synthetic_case
from src.uc.solver import solve_uc

OPTIONS = [("startup_type",), ("ramp",), ("startup_type", "ramp")]


def solve(seed, strengthen=(), lp=False):
    p = synthetic_case(units=8, hours=24, seed=seed)
    p.strengthen = strengthen
    p.mip_gap = 1e-6
    if lp:
        p.solver_options = {"mip": False}
    return solve_uc(p)


@pytest.mark.parametrize("seed", [3, 17, 41])
@pytest.mark.parametrize("strengthen", OPTIONS)
def test_optimum_unchanged(seed, strengthen):
    base, strong = solve(seed), solve(seed, strengthen)
    assert base.feasibility_verified and strong.feasibility_verified
    assert strong.primal_bound == pytest.approx(base.primal_bound, rel=1e-5)


@pytest.mark.parametrize("seed", [3, 17, 41])
def test_startup_cuts_raise_lp_bound(seed):
    base = solve(seed, lp=True).dual_bound
    strong = solve(seed, ("startup_type",), lp=True).dual_bound
    optimum = solve(seed).primal_bound
    assert base <= strong + 1e-6 * abs(base)
    assert strong <= optimum * (1 + 1e-5)
    assert strong > base  # the base LP prices cold starts as hot in these cases


def test_unknown_option_rejected():
    with pytest.raises(ValueError, match="strengthen"):
        p = synthetic_case(units=4, hours=2)
        p.strengthen = ("magic",)
        p.__post_init__()
