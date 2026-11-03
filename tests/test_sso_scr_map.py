"""SSO 段 C(`src/dynamics/sso/scr_map.py` と `short_circuit.thevenin_matrix`)のゲート。

1. 複数点のテブナンの行列: 対角が short_circuit_mva の Z_th と一致し、2 バス系の解析解とも合う
2. 一般化 SCR: 1 点なら S_sc/S、容量を k 倍すると 1/k、結合の無い 2 点は小さい方
3. 力率の電流: 大きさ 1 pu、i_q > 0 で網から無効電力を吸う
4. 臨界 SCR: 道 1(固有値)と道 2(アドミタンス)が一致し、f_dq は臨界のモードの周波数
5. 要約: SSO の帯の最大は f_dq < f0 の組だけから取り、全体の最大を超えない
6. X/R の補間: 格子の上では表の値、外は端の値
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.dynamics.sso import gfl, scr_map as sm  # noqa: E402

pp = pytest.importorskip("pandapower")


def _radial(base_mva=100.0):
    """bus0 に同期機(xd'' 0.25・100 MVA)、bus0–bus1–bus2 に x 0.1 pu の線を 2 本。"""
    net = pp.create_empty_network(sn_mva=base_mva)
    b = [pp.create_bus(net, vn_kv=100.0) for _ in range(3)]
    pp.create_gen(net, b[0], p_mw=80.0, max_p_mw=100.0, vm_pu=1.0)
    for u, v in ((0, 1), (1, 2)):
        pp.create_line_from_parameters(net, b[u], b[v], length_km=1.0, r_ohm_per_km=1.0,
                                       x_ohm_per_km=10.0, c_nf_per_km=0.0, max_i_ka=1.0)
    pp.create_ext_grid(net, b[0])
    return net, b


def test_thevenin_matrix_diag_matches_short_circuit():
    from src.powerflow.short_circuit import short_circuit_mva, thevenin_matrix
    net, b = _radial()
    sc = short_circuit_mva(net)
    z, base = thevenin_matrix(net, b)
    for k, lbl in enumerate(b):
        assert z[k, k] == pytest.approx(sc.z_th_pu[sc.bus_row_of_label[lbl]], rel=1e-12)
    # 放射状: 電源から見た共通の道の Z が非対角に出る(bus1 と bus2 の共通部分 = 電源 + 1 本目)
    assert z[1, 2] == pytest.approx(z[1, 1], rel=1e-12)
    assert z[0, 2] == pytest.approx(z[0, 0], rel=1e-12)
    assert base == pytest.approx(100.0)


def test_gscr_single_point_scaling_and_decoupled():
    z1 = np.array([[0.02 + 0.2j]])
    lam, w = sm.gscr(z1, np.array([50.0]), 100.0)
    assert lam[0] == pytest.approx(100.0 / abs(z1[0, 0]) / 50.0, rel=1e-12)   # = S_sc / S
    assert w[0, 0] == pytest.approx(1.0)
    lam2, _ = sm.gscr(z1, np.array([100.0]), 100.0)
    assert lam2[0] == pytest.approx(lam[0] / 2, rel=1e-12)
    z = np.diag([0.02 + 0.2j, 0.01 + 0.1j])
    lam, w = sm.gscr(z, np.array([50.0, 50.0]), 100.0)
    assert lam[0] == pytest.approx(100.0 / abs(z[0, 0]) / 50.0, rel=1e-12)    # 弱い方
    assert w[0, 0] == pytest.approx(1.0, abs=1e-12)


def test_gscr_coupled_is_below_single_point_scr():
    """近くに集まると、1 点ずつの SCR より一般化 SCR が小さくなる(GSCR2018)。"""
    net, b = _radial()
    from src.powerflow.short_circuit import thevenin_matrix
    z, base = thevenin_matrix(net, b[1:])
    s = np.array([30.0, 30.0])
    lam, _ = sm.gscr(z, s, base)
    single = base / np.abs(np.diag(z)) / s
    assert lam[0] < single.min()


@pytest.mark.parametrize("pf,sign", [(1.0, 0), (0.95, 1), (0.9, 1), (0.95, -1)])
def test_currents_rated_and_q_sign(pf, sign):
    i_d, i_q = sm.currents(pf, sign)
    assert math.hypot(i_d, i_q) == pytest.approx(1.0)
    eq = gfl.equilibrium(gfl.GFLParams(scr=5.0, i_d_ref=i_d, i_q_ref=i_q))
    q = (eq.v_pcc * np.conj(eq.i_c)).imag                 # 網へ出す無効電力
    assert np.sign(round(q, 9)) == -sign                   # +1 は吸う(q < 0)


@pytest.mark.parametrize("f0", [50.0, 60.0])
def test_critical_point_eig_matches_admittance(f0):
    p = gfl.GFLParams(f0=f0, xr_g=5.0, f_pll=100.0, f_cc=300.0, k_ff=1.0)
    c, f_dq = sm.critical_point(p)
    assert sm.SCR_LO < c < sm.SCR_HI
    assert gfl.critical_scr_admittance(p, c * 0.97, c * 1.03) == pytest.approx(c, rel=1e-6)
    lc = gfl.critical_mode(gfl.eigenvalues(p.replace(scr=c)))
    assert abs(lc.real) < 1e-4 and f_dq == pytest.approx(lc.imag / (2 * math.pi))


def test_critical_scr_returns_lower_bound_when_stable_to_static_limit():
    p = gfl.GFLParams(f0=50.0, xr_g=5.0, f_pll=8.0, f_cc=300.0, k_ff=1.0)
    c, f_dq = sm.critical_point(p)
    assert c == sm.SCR_LO and math.isnan(f_dq)


def test_summarize_sub_band_uses_only_low_modes():
    scr = np.array([[[4.0]], [[2.0]], [[sm.SCR_LO]]])
    fdq = np.array([[[140.0]], [[4.0]], [[np.nan]]])
    out = sm.summarize(scr, fdq, 50.0)
    assert out["max"][0, 0] == 4.0 and out["max_sub"][0, 0] == 2.0
    assert out["median"][0, 0] == 2.0 and out["min"][0, 0] == sm.SCR_LO
    none = sm.summarize(scr[:1], fdq[:1], 50.0)            # sub の組が無ければ下限
    assert none["max_sub"][0, 0] == sm.SCR_LO


def test_at_xr_on_grid_and_clipped():
    curve = np.arange(len(sm.XR_GRID), dtype=float)
    assert sm.at_xr(curve, sm.XR_GRID) == pytest.approx(curve)
    assert sm.at_xr(curve, [0.5, 1e3]) == pytest.approx([curve[0], curve[-1]])
    assert sm.onset_mva([400.0], [2.0])[0] == pytest.approx(200.0)
