"""介入#27（187kV線路抵抗の実測較正）の回帰テスト。

守りたいのは3つ:
  1. 既定は**必ず**未較正（標準表がベースラインであり続ける）
  2. 較正は187kVだけに効き、他の電圧階級を巻き込まない
  3. 最近傍フォールバックでも kind/calibrated が落ちない

根拠は docs/MODEL_INTERVENTIONS.md #27 /
docs/reports/system_disclosure_survey_2026-08-11.md §4.5。
"""

import pytest

from src.converter.line_parameters import (
    get_line_parameters,
    get_line_parameters_safe,
)

# 事業者公表の様式5・187kV 107本（北海道65 + 四国42）の実測 X/R 中央値
OBSERVED_XR_187 = 5.83
STANDARD_XR_187 = 0.350 / 0.038  # = 9.21


def test_default_is_uncalibrated():
    """既定で較正が勝手に効いてはいけない。"""
    p = get_line_parameters(187, 50)
    assert p["r_ohm_per_km"] == pytest.approx(0.038)
    assert p["x_ohm_per_km"] / p["r_ohm_per_km"] == pytest.approx(
        STANDARD_XR_187, rel=1e-3
    )


def test_calibrated_matches_published_xr():
    """較正を要求したとき、X/R が公表実測に一致する。"""
    p = get_line_parameters(187, 50, calibrated=True)
    assert p["r_ohm_per_km"] == pytest.approx(0.060)
    assert p["x_ohm_per_km"] / p["r_ohm_per_km"] == pytest.approx(
        OBSERVED_XR_187, rel=1e-2
    )


@pytest.mark.parametrize("kv", [500, 275, 220, 154, 132, 110, 66])
def test_other_voltage_classes_untouched(kv):
    """187kV以外は較正フラグの有無で1ビットも変わらない。"""
    assert get_line_parameters(kv, 50) == get_line_parameters(kv, 50, calibrated=True)


def test_reactance_is_not_moved():
    """x は据え置く判断（根拠が弱いため）を固定する。"""
    base = get_line_parameters(187, 50)
    cal = get_line_parameters(187, 50, calibrated=True)
    assert base["x_ohm_per_km"] == cal["x_ohm_per_km"]
    assert base["b_s_per_km"] == cal["b_s_per_km"]


def test_calibration_survives_nearest_class_fallback():
    """190kV→187kV のフォールバックでも calibrated が落ちない。"""
    p = get_line_parameters_safe(190, 50, calibrated=True)
    assert p is not None
    assert p["r_ohm_per_km"] == pytest.approx(0.060)


def test_cable_variant_still_works_with_calibration_off():
    """既存の kind='cable' 機構を壊していないこと。"""
    overhead = get_line_parameters(500, 50)
    cable = get_line_parameters(500, 50, kind="cable")
    assert cable["x_ohm_per_km"] < overhead["x_ohm_per_km"]
