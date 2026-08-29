"""AGC/LFC層(src/dynamics/agc.py)の性質テスト — IEEJ AGC30簡易版.

合成2エリア島で、多エリアLFCの教科書的性質(Kundur ch.11)を固定する:
  1. 一次調整のみ: 定常偏差が解析値 −ΔP/β に一致し、連系線で応援が流れる
  2. TBC+EDC: 周波数・連系偏差ともゼロ復帰し、外乱エリアが全量を引き受ける
  3. ガバナフリー幅: 大外乱では一次応答がGF幅で飽和し、偏差が線形値より深い
"""
import numpy as np
import pytest

from src.dynamics.agc import (AGC30_CLASSES, AreaSpec, Disturbance,
                              MultiAreaLFC, ResponseGroup, S_BASE_MVA)


def _grp(area, cls, s_mva, up, dn):
    d = AGC30_CLASSES[cls]
    return ResponseGroup(area=area, fuel=cls, s_mva=s_mva, room_up_mw=up,
                         room_dn_mw=dn, R=d["R"], gf=d["gf"], rate=d["rate"],
                         Tg=d["Tg"], Tt=d["Tt"], agc=d["agc"],
                         resp_share=d["resp_share"])


@pytest.fixture()
def two_area():
    a = AreaSpec("A", M=2 * 4.0 * 12000 / S_BASE_MVA, load_mw=10000,
                 groups=[_grp("A", "coal", 8000, 1500, 3000),
                         _grp("A", "hydro", 2000, 800, 500)])
    b = AreaSpec("B", M=2 * 4.0 * 6000 / S_BASE_MVA, load_mw=5000,
                 groups=[_grp("B", "lng", 5000, 1200, 1500)])
    return [a, b], {("A", "B"): 500.0}


def test_primary_only_settles_at_analytic_qss(two_area):
    areas, tie = two_area
    m = MultiAreaLFC(50.0, areas, tie, mode="off")
    r = m.simulate(Disturbance(area="A", dp_mw=600.0), t_end=300.0)
    # 定常偏差 = −ΔP/β (GF幅が拘束しない規模の外乱)
    assert r.df_hz["A"][-1] == pytest.approx(r.qss_hz, abs=2e-3)
    # 両エリアは同期(連系が硬い) — 周波数は共通に落ち着く
    assert r.df_hz["A"][-1] == pytest.approx(r.df_hz["B"][-1], abs=1e-3)
    # B→Aへ応援潮流(Aの受電偏差は負=輸入)
    assert r.ptie_mw["A"][-1] < -50.0


def test_tbc_edc_restores_and_assigns_to_disturbed_area(two_area):
    areas, tie = two_area
    m = MultiAreaLFC(50.0, areas, tie, mode="tbc")
    r = m.simulate(Disturbance(area="A", dp_mw=600.0), t_end=900.0)
    assert r.restore_s is not None and r.restore_s < 600.0
    assert abs(r.df_hz["A"][-1]) < 0.01
    assert abs(r.ptie_mw["A"][-1]) < 30.0          # 連系偏差もゼロ復帰
    # 外乱エリアAが全量を引き受け、Bの指令は小さい
    assert r.agc_mw["A"][-1] == pytest.approx(600.0, rel=0.10)
    assert abs(r.agc_mw["B"][-1]) < 60.0


def test_governor_free_width_saturates_primary(two_area):
    areas, tie = two_area
    m = MultiAreaLFC(50.0, areas, tie, mode="off")
    small = m.simulate(Disturbance(area="A", dp_mw=200.0), t_end=240.0)
    big = m.simulate(Disturbance(area="A", dp_mw=3000.0), t_end=240.0)
    # 小外乱は線形域: 実測定常偏差 ≈ 解析値。大外乱はGF幅飽和で解析値より深い
    assert small.df_hz["A"][-1] == pytest.approx(small.qss_hz, abs=2e-3)
    assert big.df_hz["A"][-1] < big.qss_hz * 1.5   # 線形予測より有意に深い


def test_ufls_bounds_small_island_collapse():
    # 単エリア小島(需要1,700MW)で30%喪失 — UFLS無しでは非物理的な深さまで
    # 落ち、UFLS(典型3段)ありでは −3 Hz 以内に留まる
    a = AreaSpec("O", M=2 * 3.5 * 1500 / S_BASE_MVA, load_mw=1700,
                 groups=[_grp("O", "lng", 1200, 200, 400)])
    d = Disturbance(area="O", dp_mw=500.0)
    off = MultiAreaLFC(60.0, [a], {}, mode="tbc", ufls=False).simulate(
        d, t_end=120.0)
    on = MultiAreaLFC(60.0, [a], {}, mode="tbc", ufls=True).simulate(
        d, t_end=120.0)
    assert off.nadir_hz < -4.0
    assert -3.0 < on.nadir_hz < -1.0
