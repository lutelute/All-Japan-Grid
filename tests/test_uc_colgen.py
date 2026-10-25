"""The UC-specific solver: the unit DP against the production formulation, and the bound against the MILP."""

import numpy as np
import pulp
import pytest

from src.uc import constraints as C
from src.uc.benchmark_cases import synthetic_case
from src.uc.colgen import best_schedules, schedule_cost, solve_colgen, unit_table
from src.uc.solver import _build_objective, solve_uc


def unit_milp(g, steps, price, sigma, initial_commitment=None, initial_history_h=None):
    """One unit, no ramps, against prices: the production constraints, solved by HiGHS."""
    m = pulp.LpProblem("one", pulp.LpMinimize)
    idx = [(g.id, t) for t in steps]
    u, v, w = (pulp.LpVariable.dicts(n, idx, cat="Binary") for n in ("u", "v", "w"))
    p = pulp.LpVariable.dicts("p", idx, lowBound=0)
    ys = {n: pulp.LpVariable.dicts(n, idx, cat="Binary") for n in ("yh", "yw", "yc")} if g.has_thermal_startup else {}
    _build_objective(m, u, p, v, w, [g], steps, y_hot=ys.get("yh"), y_warm=ys.get("yw"), y_cold=ys.get("yc"))
    m.objective += -pulp.lpSum(price[i] * p[(g.id, t)] + sigma[i] * g.capacity_mw * u[(g.id, t)] for i, t in enumerate(steps))
    C.add_capacity_bounds_constraints(m, u, p, [g], steps)
    C.add_startup_shutdown_logic(m, u, v, w, [g], steps, initial_commitment=initial_commitment)
    if initial_history_h:
        C.add_initial_history_constraints(m, u, [g], steps, initial_history_h)
    C.add_min_uptime_constraints(m, u, v, [g], steps)
    C.add_min_downtime_constraints(m, u, w, [g], steps)
    if ys:
        C.add_startup_type_constraints(m, u, v, ys["yh"], ys["yw"], ys["yc"], [g], steps,
                                       initial_history_h=initial_history_h, initial_commitment=initial_commitment)
    m.solve(pulp.HiGHS(msg=0, gapRel=0))
    assert pulp.LpStatus[m.status] == "Optimal"
    return pulp.value(m.objective)


@pytest.mark.parametrize("state", ["cold", "on2", "off3"])
def test_unit_dp_matches_the_production_formulation(state):
    params = synthetic_case(12, 24, 17)
    if state == "on2":
        params.initial_commitment = {g.id: 1 for g in params.generators}
        params.initial_history_h = {g.id: 2 for g in params.generators}
    elif state == "off3":
        params.initial_history_h = {g.id: -3 for g in params.generators}
    units = unit_table(params)
    rng = np.random.default_rng(5)
    T = 24
    price = units.fuel[:, None] * rng.uniform(0.7, 1.6, size=(len(units.ids), T))
    sigma = rng.uniform(0, 300, size=T)
    margin = units.fuel[:, None] - price
    p = np.where(margin < 0, units.cap[:, None], units.pmin[:, None])
    oncost = units.fixed[:, None] + margin * p - sigma[None, :] * units.cap[:, None]
    value, u = best_schedules(units, oncost)
    pu = np.where(u, p, 0.0)
    walk = schedule_cost(units, u, pu) - (price * pu).sum(1) - (sigma[None, :] * units.cap[:, None] * u).sum(1)
    np.testing.assert_allclose(walk, value, rtol=1e-9, atol=1e-6)
    gens = {g.id: g for g in params.generators}
    steps = list(range(T))
    for i, gid in enumerate(units.ids):
        ref = unit_milp(gens[gid], steps, price[i], sigma, params.initial_commitment, params.initial_history_h)
        assert value[i] == pytest.approx(ref, rel=1e-7, abs=1e-3), gid


def test_bound_lies_between_the_lp_and_the_optimum():
    def case():
        params = synthetic_case(16, 24, 17)
        for g in params.generators:
            g.ramp_up_mw_per_h = g.ramp_down_mw_per_h = None    # the pricing leaves ramps out
        params.solver_name, params.mip_gap = "HiGHS", 0.0
        params.solver_options = {"threads": 1}
        params.strengthen = ("startup_type",)
        return params

    opt = solve_uc(case())
    lp_params = case()
    lp_params.solver_options = {"threads": 1, "mip": False}
    lp = solve_uc(lp_params)
    cg = solve_colgen(case(), tol=1e-9, log=lambda *_: None)
    assert opt.gap is not None and opt.gap < 1e-9
    assert cg.lower_bound <= opt.total_cost * (1 + 1e-7)
    assert cg.lower_bound >= lp.total_cost * (1 - 1e-7)
    assert cg.trace[-1]["gap"] < 1e-6


def test_with_ramps_the_bound_and_the_band_bracket_the_optimum():
    def case():
        params = synthetic_case(16, 24, 17)
        params.solver_name, params.mip_gap = "HiGHS", 0.0
        params.solver_options = {"threads": 1}
        params.strengthen = ("startup_type",)
        return params

    from src.uc.colgen import solve_band
    opt = solve_uc(case())
    cg = solve_colgen(case(), tol=1e-9, log=lambda *_: None)
    band, _ = solve_band(case(), cg, gap=0.0)
    assert opt.gap is not None and opt.gap < 1e-9
    assert cg.lower_bound <= opt.total_cost * (1 + 1e-7)
    assert band.feasibility_verified
    assert band.total_cost >= opt.total_cost * (1 - 1e-7)
