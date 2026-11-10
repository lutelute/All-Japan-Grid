"""同時刻の採点(scripts/score_sync_flows.py)の物差しの試験。"""
from __future__ import annotations

import pytest

from scripts import score_sync_flows as ss


def test_line_score_perfect_match():
    obs = [100.0, 200.0, 300.0, 250.0, 150.0, 120.0]
    s = ss.line_score(obs, list(obs), single_ended=False)
    assert s["ratio"] == pytest.approx(1.0)
    assert s["r_time"] == pytest.approx(1.0)
    assert s["sign_ok"] is True
    assert s["rmse"] == pytest.approx(0.0)


def test_line_score_reversed_direction_is_caught_unless_single_ended():
    obs = [100.0, 200.0, 300.0, 250.0, 150.0, 120.0]
    rev = [-x for x in obs]
    s = ss.line_score(obs, rev, single_ended=False)
    assert s["sign_ok"] is False
    assert s["r_time"] == pytest.approx(-1.0)
    assert s["nrmse_obs"] == pytest.approx(2.0, rel=0.1)
    c = ss.line_score(obs, rev, single_ended=True)       # 片端の照合は大きさだけ比べる
    assert c["sign_ok"] is None
    assert c["rmse"] == pytest.approx(0.0)


def test_line_score_needs_enough_hours():
    assert ss.line_score([1.0] * 5, [1.0] * 5, single_ended=False) is None


def test_model_value_orients_and_shares_parallel_circuits():
    model = {"east": {"k1": {("2026-11-09", 3): 400.0}, "k2": {("2026-11-09", 3): -100.0}}}
    rec = {"island": "east", "segs": [[["k1", 1, 2], ["k2", -1, 2]]], "n_circ_obs": None}
    assert ss.model_value(rec, model, ("2026-11-09", 3)) == pytest.approx(500.0)
    rec["n_circ_obs"] = 1            # 観測が 1 回線ぶんなら、4 回線の束を按分する
    assert ss.model_value(rec, model, ("2026-11-09", 3)) == pytest.approx(125.0)
    assert ss.model_value(rec, model, ("2026-11-09", 4)) is None


def test_observed_hourly_uses_trapezoid():
    today = {"days": ["2026-11-09"], "times": ["2026-11-09 00:00", "2026-11-09 00:30", "2026-11-09 01:00"],
             "lines": {"a|b|c": {"kv": 500, "v": [100, 200, 400]}}}
    got = ss.observed_hourly(today)["a|b|c"]
    assert got[("2026-11-09", 0)] == pytest.approx(225.0)
    assert ("2026-11-09", 1) not in got


def test_capacity_ignores_fence_marker():
    today = {"cap": {"2026-11-09": {"x": [None, 1200.0, "熱容量", 99999.0]}}}
    assert ss.capacity_of(today, "x") == 1200.0
    assert ss.capacity_of(today, "y") is None


def test_summarize_shares():
    rows = [{"ratio": 1.0, "r_time": 0.9, "sign_ok": True, "nrmse_obs": 0.1, "nrmse_cap": 0.05, "rmse": 10.0, "obs_absmean": 100.0},
            {"ratio": 3.0, "r_time": 0.1, "sign_ok": False, "nrmse_obs": 2.0, "nrmse_cap": None, "rmse": 200.0, "obs_absmean": 100.0}]
    s = ss.summarize(rows)
    assert s["n"] == 2 and s["within_x2"] == 0.5 and s["within_x125"] == 0.5
    assert s["sign_ok"] == 0.5 and s["r_time_gt05"] == 0.5
    assert s["sum_rmse_over_sum_obs"] == pytest.approx(1.05)
