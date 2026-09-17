"""介入#27（187kV線路抵抗の実測較正）と #46（線種標準値の実測較正 第2弾）の回帰テスト。

守りたいのは3つ:
  1. 既定は**必ず**未較正（標準表がベースラインであり続ける）
  2. 較正は台帳に載せた階級・パラメータだけに効き、他（275/132/110kV・b）を巻き込まない
  3. 最近傍フォールバックでも kind/calibrated が落ちない

#27 は「x は据え置き」としたが、#46 で実線形長ベース（n=31）の逆算により
187kV の x も較正した。そのため 187kV の X/R は公表中央値 5.83 には固定しない。

根拠は docs/MODEL_INTERVENTIONS.md #27・#46 /
docs/reports/system_disclosure_survey_2026-08-11.md §4.5 /
docs/reports/impedance_validation_2026-08-19.md §11。
"""

import pytest

from src.converter.line_parameters import (
    get_line_parameters,
    get_line_parameters_safe,
)

# 事業者公表の様式5・187kV 107本（北海道65 + 四国42）の実測 X/R 中央値
OBSERVED_XR_187 = 5.83
STANDARD_XR_187 = 0.350 / 0.038  # = 9.21

# kv -> (標準 r, 標準 x, 較正 r, 較正 x)  [Ω/km]
CALIBRATED = {
    187: (0.038, 0.350, 0.060, 0.416),  # #27 r / #46 x
    500: (0.012, 0.290, 0.012, 0.326),  # #46 x のみ
    220: (0.032, 0.335, 0.032, 0.377),  # #46 x のみ
    154: (0.050, 0.380, 0.081, 0.425),  # #46 r・x
    66: (0.120, 0.400, 0.141, 0.437),   # #46 r・x（標本少）
}


def test_default_is_uncalibrated():
    """既定で較正が勝手に効いてはいけない。"""
    p = get_line_parameters(187, 50)
    assert p["r_ohm_per_km"] == pytest.approx(0.038)
    assert p["x_ohm_per_km"] / p["r_ohm_per_km"] == pytest.approx(
        STANDARD_XR_187, rel=1e-3
    )


@pytest.mark.parametrize("kv", sorted(CALIBRATED))
def test_calibrated_values_match_ledger(kv):
    """較正を要求したときだけ、台帳どおりの r/x になる。"""
    r0, x0, r1, x1 = CALIBRATED[kv]
    base = get_line_parameters(kv, 50)
    cal = get_line_parameters(kv, 50, calibrated=True)
    assert base["r_ohm_per_km"] == pytest.approx(r0)
    assert base["x_ohm_per_km"] == pytest.approx(x0)
    assert cal["r_ohm_per_km"] == pytest.approx(r1)
    assert cal["x_ohm_per_km"] == pytest.approx(x1)


def test_calibrated_xr_moves_toward_published():
    """187kV の X/R は標準表から公表実測の側へ動く（#46 以降は一致までは求めない）。"""
    p = get_line_parameters(187, 50, calibrated=True)
    xr = p["x_ohm_per_km"] / p["r_ohm_per_km"]
    assert OBSERVED_XR_187 <= xr < STANDARD_XR_187


@pytest.mark.parametrize("kv", [275, 132, 110])
def test_other_voltage_classes_untouched(kv):
    """台帳に無い階級は較正フラグの有無で1ビットも変わらない。"""
    assert get_line_parameters(kv, 50) == get_line_parameters(kv, 50, calibrated=True)


@pytest.mark.parametrize("kv", sorted(CALIBRATED))
def test_susceptance_is_not_moved(kv):
    """較正は r/x だけ。対地容量 b は据え置く。"""
    base = get_line_parameters(kv, 50)
    cal = get_line_parameters(kv, 50, calibrated=True)
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
