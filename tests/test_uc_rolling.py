"""Tests for rolling horizon UC — 窓間の状態引き継ぎが核心。

検証対象:
- 幻の起動費が出ない（initial_commitment が窓頭に効く）
- SOCが窓境界で連続する（initial_soc_fraction 引き継ぎ）
- min up/down が窓境界をまたいで効く（initial_history_h）
"""

import numpy as np
import pytest

from src.model.generator import Generator
from src.uc.models import DemandProfile, TimeHorizon, UCParameters
from src.uc.rolling import (
    RollingUCConfig,
    _update_history,
    solve_rolling_uc,
)
from src.uc.solver import solve_uc


def _gen(gen_id, cap=100.0, cost=10.0, startup=1000.0, **kw):
    defaults = dict(
        capacity_mw=cap,
        fuel_type="lng",
        region="tokyo",
        fuel_cost_per_mwh=cost,
        no_load_cost=0,
        startup_cost=startup,
        shutdown_cost=0,
        min_up_time_h=1,
        min_down_time_h=1,
        p_min_mw=0.0,
        hot_start_cost=startup,
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
        initial_soc_fraction=0.5, min_terminal_soc_fraction=0.3,
    )


class TestInitialStateInSolver:
    def test_initial_commitment_avoids_phantom_startup(self):
        # 直前ONを伝えると t=0 の継続運転に起動費がかからない
        g = _gen("base", cap=100, cost=10, startup=5000)
        common = dict(
            generators=[g],
            demand=DemandProfile(demands=[50.0, 50.0]),
            time_horizon=TimeHorizon(num_periods=2),
        )
        cold = solve_uc(UCParameters(**common))
        warm = solve_uc(UCParameters(**common, initial_commitment={"base": 1}))
        assert cold.is_optimal and warm.is_optimal
        # cold は起動費5000を払う。warm は払わない
        assert cold.total_cost - warm.total_cost == pytest.approx(5000)

    def test_initial_history_enforces_min_down(self):
        # min_down=4h の機が「1時間前に停止した」状態 → 先頭3hはOFF強制
        expensive = _gen("must_rest", cap=100, cost=1,
                         min_down_time_h=4, startup=0)
        backup = _gen("backup", cap=100, cost=50, startup=0)
        params = UCParameters(
            generators=[expensive, backup],
            demand=DemandProfile(demands=[50.0] * 4),
            time_horizon=TimeHorizon(num_periods=4),
            initial_history_h={"must_rest": -1},  # OFF 1時間目
        )
        result = solve_uc(params)
        assert result.is_optimal
        sched = next(s for s in result.schedules
                     if s.generator_id == "must_rest")
        # 残りmin_down 3時間はOFF（安くても使えない）、t=3で復帰できる
        assert sched.commitment[:3] == [0, 0, 0]
        assert sched.commitment[3] == 1  # 安いので復帰直後にON

    def test_initial_history_enforces_min_up(self):
        # min_up=4h の機が「1時間前に起動した」→ 先頭3hはON強制。
        # no_load_cost>0 でON維持に実コストを持たせ、強制期間後のOFFを
        # 厳密に最適にする（0だとON/OFFが縮退で不定）
        g = _gen("must_run", cap=100, cost=100,
                 min_up_time_h=4, startup=0, no_load_cost=100)
        cheap = _gen("cheap", cap=100, cost=1, startup=0)
        params = UCParameters(
            generators=[g, cheap],
            demand=DemandProfile(demands=[50.0] * 4),
            time_horizon=TimeHorizon(num_periods=4),
            initial_commitment={"must_run": 1},
            initial_history_h={"must_run": 1},
        )
        result = solve_uc(params)
        assert result.is_optimal
        sched = next(s for s in result.schedules
                     if s.generator_id == "must_run")
        # 高コストでも min_up の残り3hはONを強制される
        assert sched.commitment[:3] == [1, 1, 1]
        assert sched.commitment[3] == 0


class TestUpdateHistory:
    def test_streak_continues_across_windows(self):
        from src.uc.models import GeneratorSchedule, UCResult

        res = UCResult(
            status="Optimal",
            schedules=[GeneratorSchedule(
                generator_id="g", commitment=[1, 1, 1],
                power_output_mw=[50.0] * 3,
            )],
        )
        # 前史 +5h ON、確定3期間が全てON → 8h ON
        hist = _update_history({"g": 5}, res, n_commit=3)
        assert hist["g"] == 8

    def test_streak_resets_on_transition(self):
        from src.uc.models import GeneratorSchedule, UCResult

        res = UCResult(
            status="Optimal",
            schedules=[GeneratorSchedule(
                generator_id="g", commitment=[1, 0, 0],
                power_output_mw=[50.0, 0.0, 0.0],
            )],
        )
        # 確定部分の末尾はOFF×2（途中で遷移）→ -2（前史は無関係）
        hist = _update_history({"g": 10}, res, n_commit=3)
        assert hist["g"] == -2


class TestSolveRollingUC:
    def test_constant_demand_single_startup(self):
        # 4窓（96h）一定需要 → ベース機の起動は年間で1回だけ
        g = _gen("base", cap=100, cost=10, startup=5000)
        demand = np.full(96, 60.0)
        cfg = RollingUCConfig(window_h=48, step_h=24, reserve_margin=0.0,
                              warm_start=True)
        res = solve_rolling_uc([g], demand, None, [], cfg, progress=False)
        assert res.is_optimal
        assert res.n_windows == 4
        sched = res.schedules["base"]
        assert len(sched.commitment) == 96
        starts = int(np.maximum(
            np.diff(np.array(sched.commitment), prepend=0), 0).sum())
        assert starts == 1  # 窓境界の幻の再起動なし
        # コスト = fuel + startup 1回
        assert res.total_cost == pytest.approx(60 * 96 * 10 + 5000)

    def test_soc_continuous_across_boundaries(self):
        # 蓄電池のSOCが窓境界で連続する（ジャンプしない）
        g = _gen("base", cap=100, cost=10, startup=0)
        peaker = _gen("peak", cap=50, cost=200, startup=0)
        batt = _battery(mwh=200.0)
        # 2日サイクルの需要（夜安・昼高）で充放電を誘発
        day = np.array([60.0] * 8 + [130.0] * 8 + [60.0] * 8)
        demand = np.tile(day, 4)  # 96h
        cfg = RollingUCConfig(window_h=48, step_h=24, reserve_margin=0.0,
                              warm_start=False)
        res = solve_rolling_uc([g, peaker, batt], demand, None, [], cfg,
                               progress=False)
        assert res.is_optimal
        soc = np.array(res.schedules["batt"].soc_mwh)
        assert len(soc) == 96
        # SOCの時間差分は物理上限（充放電レート×効率の範囲）を超えない
        # 充電: +50MW×0.9=45MWh/h、放電: -50/0.9≈-55.6MWh/h
        dsoc = np.diff(soc)
        assert dsoc.max() <= 45.0 + 1e-6
        assert dsoc.min() >= -55.6 - 1e-6

    def test_short_tail_window(self):
        # 全長が窓割りで割り切れないケース（最終窓が短い）
        g = _gen("base", cap=100, cost=10, startup=0)
        demand = np.full(30, 50.0)  # 30h: 窓 [0:30), [24:30)
        cfg = RollingUCConfig(window_h=24, step_h=24, reserve_margin=0.0)
        res = solve_rolling_uc([g], demand, None, [], cfg, progress=False)
        assert res.is_optimal
        assert len(res.schedules["base"].commitment) == 30


class TestSliceMaintenance:
    def test_absolute_to_window_local(self):
        from src.uc.rolling import _slice_maintenance
        # 年間絶対 (2016, 2856) のメンテを各窓ローカルへ
        win = [(2016, 2856)]
        assert _slice_maintenance(win, 0, 48) == []            # 窓が手前
        assert _slice_maintenance(win, 2016, 2064) == [(0, 48)]  # 窓全体がメンテ
        assert _slice_maintenance(win, 1992, 2040) == [(24, 48)]  # 後半から開始
        assert _slice_maintenance(win, 2832, 2880) == [(0, 24)]   # 前半で終了
        assert _slice_maintenance(win, 2880, 2928) == []       # 窓が後ろ
