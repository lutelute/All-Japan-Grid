"""Tests for warm start — MIP start injection via HiGHS setSolution.

rolling horizon（8760h時系列UC）の前提技術:
前窓の解を ``UCParameters.warm_start_schedules`` として次窓に注入する。
不完全・時間シフトされたスタートはHiGHSがrepairするため許容される。
"""

import pytest

from src.model.generator import Generator
from src.uc.models import DemandProfile, TimeHorizon, UCParameters
from src.uc.solver import solve_uc


def _gen(gen_id, cap=100.0, cost=10.0, **kw):
    defaults = dict(
        capacity_mw=cap,
        fuel_type="lng",
        region="tokyo",
        fuel_cost_per_mwh=cost,
        no_load_cost=100,
        startup_cost=500,
        shutdown_cost=200,
        min_up_time_h=1,
        min_down_time_h=1,
        p_min_mw=0.0,
    )
    defaults.update(kw)
    return Generator(id=gen_id, name=gen_id, **defaults)


def _battery(gen_id="batt", mw=50.0, mwh=200.0):
    return Generator(
        id=gen_id, name=gen_id, capacity_mw=mw, fuel_type="battery",
        region="tokyo", fuel_cost_per_mwh=0, no_load_cost=0,
        startup_cost=0, shutdown_cost=0,
        min_up_time_h=1, min_down_time_h=1, p_min_mw=0.0,
        storage_capacity_mwh=mwh,
        charge_rate_mw=mw, discharge_rate_mw=mw,
        charge_efficiency=0.9, discharge_efficiency=0.9,
        initial_soc_fraction=0.5, min_terminal_soc_fraction=0.5,
    )


class TestWarmStart:
    def _params(self, gens, demands, schedules=None):
        return UCParameters(
            generators=gens,
            demand=DemandProfile(demands=demands),
            time_horizon=TimeHorizon(num_periods=len(demands)),
            warm_start_schedules=schedules,
        )

    def test_resolve_with_own_solution(self):
        # 同一問題に自分の解を注入 → Optimal・コスト不変
        gens = [_gen("cheap", cap=80, cost=10), _gen("exp", cap=80, cost=100)]
        demands = [60.0, 120.0, 90.0, 50.0]
        r1 = solve_uc(self._params(gens, demands))
        assert r1.is_optimal

        r2 = solve_uc(self._params(gens, demands, schedules=r1.schedules))
        assert r2.is_optimal
        assert r2.total_cost == pytest.approx(r1.total_cost, rel=1e-6)

    def test_time_shifted_start_still_solves(self):
        # rolling風: 需要が変化した次窓に前窓の解を注入 → repairされてOptimal
        gens = [_gen("cheap", cap=80, cost=10), _gen("exp", cap=80, cost=100)]
        r1 = solve_uc(self._params(gens, [60.0, 120.0, 90.0, 50.0]))
        assert r1.is_optimal

        shifted = self._params(
            gens, [120.0, 90.0, 50.0, 70.0], schedules=r1.schedules,
        )
        r2 = solve_uc(shifted)
        assert r2.is_optimal
        # 比較対象: 同問題をcold solve
        r2_cold = solve_uc(self._params(gens, [120.0, 90.0, 50.0, 70.0]))
        assert r2.total_cost == pytest.approx(r2_cold.total_cost, rel=1e-6)

    def test_storage_schedule_injected(self):
        # storage付きの解（charge/discharge/soc）も注入対象になる
        gens = [_gen("g", cap=100, cost=10), _battery()]
        demands = [40.0, 90.0, 40.0, 90.0]
        r1 = solve_uc(self._params(gens, demands))
        assert r1.is_optimal
        batt_sched = next(s for s in r1.schedules if s.generator_id == "batt")
        assert len(batt_sched.soc_mwh) == 4  # storage解が存在する前提の確認

        r2 = solve_uc(self._params(gens, demands, schedules=r1.schedules))
        assert r2.is_optimal
        assert r2.total_cost == pytest.approx(r1.total_cost, rel=1e-6)

    def test_partial_schedule_subset_ok(self):
        # 一部の発電機分しか無いスタートでも解ける
        gens = [_gen("cheap", cap=80, cost=10), _gen("exp", cap=80, cost=100)]
        demands = [60.0, 120.0]
        r1 = solve_uc(self._params(gens, demands))
        partial = [s for s in r1.schedules if s.generator_id == "cheap"]
        r2 = solve_uc(self._params(gens, demands, schedules=partial))
        assert r2.is_optimal
