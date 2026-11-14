"""日別断面の時刻の再利用(scripts/export_day_flows.py)の試験。

2026-11-10 に見つかった事故の再発防止: 当日に継ぎ足した時刻を、燃料別の実績があとから出ても
再利用していたので、公開中の断面は実績が当たらない時刻が混ざっていた。
"""
from __future__ import annotations

from scripts import export_day_flows as edf


def _fm(hours_by_zone: dict) -> dict:
    return {"zones": {z: {"fuels": {"demand": [1.0 if h in hs else None for h in range(24)]}}
                      for z, hs in hours_by_zone.items()}}


def test_signature_changes_when_fuel_actuals_arrive_later():
    dem = {"tokyo": {0: 1.0, 1: 1.0}, "tohoku": {0: 1.0, 1: 1.0}}
    early = edf.hour_inputs(dem, _fm({"tokyo": {0}}), None, [0, 1])
    late = edf.hour_inputs(dem, _fm({"tokyo": {0, 1}}), None, [0, 1])
    assert early["0"] == late["0"]            # 0 時は入力が同じ
    assert early["1"] != late["1"]            # 1 時は、あとから燃料別の実績が出た


def test_reusable_hours_only_when_signature_matches():
    dem = {"tokyo": {0: 1.0, 1: 1.0, 2: 1.0}}
    early = edf.hour_inputs(dem, _fm({"tokyo": {0}}), None, [0, 1])
    late = edf.hour_inputs(dem, _fm({"tokyo": {0, 1}}), None, [0, 1, 2])
    prev = {"available_hours": [0, 1], "hour_inputs": early}
    assert edf.reusable_hours(prev, late) == {0}


def test_old_sections_without_signatures_are_not_reused():
    sigs = edf.hour_inputs({"tokyo": {0: 1.0}}, None, None, [0])
    assert edf.reusable_hours({"available_hours": [0]}, sigs) == set()
    assert edf.reusable_hours(None, sigs) == set()


def test_signature_records_zone_closure_source():
    dem = {"tokyo": {0: 1.0}}
    full = {k: [100.0] * 24 for k in ("hokuhon", "soma", "fc", "kansai_chugoku", "anan_kihoku", "honshi", "kanmon",
                                      "fence_chubu", "fence_hokuriku", "fence_kansai")}
    plain = edf.hour_inputs(dem, None, None, [0])
    actual = edf.hour_inputs(dem, None, {"kind": "実績", "hourly": full}, [0])
    planned = edf.hour_inputs(dem, None, {"kind": "計画", "hourly": full}, [0])
    assert len({plain["0"], actual["0"], planned["0"]}) == 3


def test_carry_hourly_keeps_only_reused_hours():
    store = {"tokyo": {"0": {"clipped_mw": 1.0}, "1": {"clipped_mw": 2.0}}, "kansai": {"0": {"clipped_mw": 3.0}}}
    got = edf._carry_hourly(store, lambda z, h: z == "tokyo" and h == 1)
    assert got == {"tokyo": {"1": {"clipped_mw": 2.0}}}
    assert edf._carry_hourly(None, lambda z, h: True) == {}
