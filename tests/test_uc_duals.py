"""Tests for dual price extraction — commitment-fixed LP re-solve.

MILPには双対が定義されないため、整数変数を最適解で固定したLPを再解し、
需給バランス制約の双対（π）を限界価格として読む（電力市場の標準手法）:
- demand_balance_t{t} → system_lambda（システム限界価格）
- nodal_bal_{region}_t{t} → regional_lmp（地域限界価格。差=連系線混雑）
"""

import pytest

from src.model.generator import Generator
from src.uc.models import (
    DemandProfile,
    Interconnection,
    TimeHorizon,
    UCParameters,
)
from src.uc.solver import solve_uc


def _gen(gen_id, region="tokyo", cap=100.0, cost=10.0, **kw):
    defaults = dict(
        capacity_mw=cap,
        fuel_type="lng",
        region=region,
        fuel_cost_per_mwh=cost,
        no_load_cost=0,
        startup_cost=0,
        shutdown_cost=0,
        min_up_time_h=1,
        min_down_time_h=1,
        p_min_mw=0.0,
    )
    defaults.update(kw)
    return Generator(id=gen_id, name=gen_id, **defaults)


class TestSystemLambda:
    def test_marginal_unit_sets_price(self):
        # cheap 50MW@10 / expensive 50MW@100。
        # t0: 需要40 → cheapが限界機で λ=10
        # t1: 需要80 → expensiveが限界機で λ=100
        gens = [
            _gen("cheap", cap=50, cost=10),
            _gen("exp", cap=50, cost=100),
        ]
        params = UCParameters(
            generators=gens,
            demand=DemandProfile(demands=[40.0, 80.0]),
            time_horizon=TimeHorizon(num_periods=2),
            extract_duals=True,
        )
        result = solve_uc(params)
        assert result.is_optimal
        assert result.system_lambda is not None
        assert result.system_lambda[0] == pytest.approx(10.0)
        assert result.system_lambda[1] == pytest.approx(100.0)
        assert result.regional_lmp == {}

    def test_no_duals_by_default(self):
        params = UCParameters(
            generators=[_gen("g", cap=100, cost=10)],
            demand=DemandProfile(demands=[50.0]),
            time_horizon=TimeHorizon(num_periods=1),
        )
        result = solve_uc(params)
        assert result.is_optimal
        assert result.system_lambda is None
        assert result.regional_lmp == {}

    def test_objective_unchanged_by_dual_extraction(self):
        # 固定LP再解は目的値を変えない（schedules/costsの整合保証）
        gens = [_gen("cheap", cap=50, cost=10), _gen("exp", cap=50, cost=100)]
        base = UCParameters(
            generators=gens,
            demand=DemandProfile(demands=[40.0, 80.0]),
            time_horizon=TimeHorizon(num_periods=2),
        )
        with_duals = UCParameters(
            generators=gens,
            demand=DemandProfile(demands=[40.0, 80.0]),
            time_horizon=TimeHorizon(num_periods=2),
            extract_duals=True,
        )
        r1 = solve_uc(base)
        r2 = solve_uc(with_duals)
        assert r2.total_cost == pytest.approx(r1.total_cost, rel=1e-6)


class TestRegionalLMP:
    def test_congestion_splits_prices(self):
        # tokyo: cheap 100MW@10 / tohoku: expensive 100MW@100
        # 需要 50/50、連系線容量20 → tohokuは30MWを自地域高コスト機で賄う
        # → λ_tokyo=10, λ_tohoku=100（混雑でLMP分離）
        gens = [
            _gen("a1", region="tokyo", cap=100, cost=10),
            _gen("b1", region="tohoku", cap=100, cost=100),
        ]
        ic = Interconnection(
            id="ic1", name_en="ic1", from_region="tokyo", to_region="tohoku",
            capacity_mw=20,
        )
        params = UCParameters(
            generators=gens,
            demand=DemandProfile(demands=[100.0]),
            time_horizon=TimeHorizon(num_periods=1),
            interconnections=[ic],
            regional_demands={"tokyo": [50.0], "tohoku": [50.0]},
            extract_duals=True,
        )
        result = solve_uc(params)
        assert result.is_optimal
        # nodalモードでは system-wide demand balance は存在しない
        assert result.system_lambda is None
        assert result.regional_lmp["tokyo"][0] == pytest.approx(10.0)
        assert result.regional_lmp["tohoku"][0] == pytest.approx(100.0)

    def test_uncongested_prices_converge(self):
        # 連系線容量が十分 → 安い機が両地域の限界機になり価格が揃う
        gens = [
            _gen("a1", region="tokyo", cap=200, cost=10),
            _gen("b1", region="tohoku", cap=100, cost=100),
        ]
        ic = Interconnection(
            id="ic1", name_en="ic1", from_region="tokyo", to_region="tohoku",
            capacity_mw=100,
        )
        params = UCParameters(
            generators=gens,
            demand=DemandProfile(demands=[100.0]),
            time_horizon=TimeHorizon(num_periods=1),
            interconnections=[ic],
            regional_demands={"tokyo": [50.0], "tohoku": [50.0]},
            extract_duals=True,
        )
        result = solve_uc(params)
        assert result.is_optimal
        assert result.regional_lmp["tokyo"][0] == pytest.approx(10.0)
        assert result.regional_lmp["tohoku"][0] == pytest.approx(10.0)
