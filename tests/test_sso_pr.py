"""SSO 段 B(公表例 REAL20HZ2022 の試験系統)の 3 つの道と、本文との突き合わせ(2026-11-01).

報告: docs/reports/sso_ibr_stage_b_2026-11-01.md。模型: src/dynamics/sso/gfl_pr.py。
"""
import math

import numpy as np
import pytest

from src.dynamics.sso import gfl_pr as m
from src.dynamics.sso.gfl import pair_from_modes

SLOW = dict(kp_cc=0.35, kr_cc=2.0, t_d=200e-6)
PLL_C1 = dict(kp_pll=100.0, ki_pll=2000.0, lpf_order=1)
PLL2 = dict(kp_pll=60.0, ki_pll=1400.0, lpf_order=2)
PLL3 = dict(kp_pll=150.0, ki_pll=2000.0, lpf_order=1)
PLL4 = dict(kp_pll=150.0, ki_pll=2000.0, lpf_order=2)
CASE3 = dict(x_g=0.37, r_g=0.37 / 8, t_d=50e-6, **PLL3)
HYP = m.PRParams(**{**SLOW, "kp_cc": 0.035}, **PLL_C1, i_d=0.1)      # Case 1 の仮説(K_p を 1/10)


def _band(lam, lo=0.5, hi=200.0):
    return lam[(lam.imag > 2 * math.pi * lo) & (lam.imag < 2 * math.pi * hi)]


@pytest.mark.parametrize("p", [m.PRParams(), m.PRParams(b_c=0.0, i_d=0.5), m.PRParams(**SLOW, **PLL_C1)])
def test_equilibrium_is_a_fixed_point(p):
    eq = m.equilibrium(p)
    assert np.abs(m._rhs(p, eq.x, eq.v_g, None)).max() < 1e-9
    assert abs(np.abs(eq.x[0] + 1j * eq.x[1]) - abs(eq.i)) < 1e-12


@pytest.mark.parametrize("p", [m.PRParams(**SLOW, **PLL_C1, i_d=0.1), m.PRParams(i_d=1.0),
                               m.PRParams(**CASE3, b_c=0.0, i_d=2.0), m.PRParams(**CASE3, i_d=1.3)])
def test_route2_zeros_equal_route1_eigenvalues(p):
    lam = _band(m.eigenvalues(p))
    z = m.loop_zeros(p)
    z = z[z.imag > 2 * math.pi * 0.5]
    assert z.size == lam.size
    for x in z:
        assert np.min(np.abs(lam - x)) < 1e-6 * abs(x)


def _pll_poles(kw):
    p = m.PRParams(**kw)
    wn = 2 * math.pi * p.f_lpf
    d_l = [1.0, wn] if p.lpf_order == 1 else [1.0, 2 * p.zeta_lpf * wn, wn * wn]
    n_l = [wn] if p.lpf_order == 1 else [wn * wn]
    r = np.roots(np.polyadd(np.polymul([1.0, 0.0, 0.0], d_l), np.polymul([p.kp_pll, p.ki_pll], n_l)))
    return r[r.imag > 0]


def test_pll_poles_against_the_paper():
    # Case 2 の式 (19) は本文の −7 ± j132 と合う
    assert np.min(np.abs(_pll_poles(dict(kp_pll=150.0, ki_pll=3000.0, lpf_order=2)) - complex(-7, 132))) < 0.2
    # Case 1 の本文の極 −47 ± j80 は、本文の Case 1 の式ではなく PLL2 の極(食い違いの記録)
    assert np.min(np.abs(_pll_poles(PLL2) - complex(-47, 80))) < 0.1
    assert np.min(np.abs(_pll_poles(PLL_C1) - complex(-47, 80))) > 15


def test_simple_example_critical_and_nonlinear_check():
    k4, f4 = m.simple_critical(m.PRParams(**PLL4))
    k3, _ = m.simple_critical(m.PRParams(**PLL3))
    assert abs(k4 - 0.5410) < 1e-3 and abs(f4 - 20.35) < 0.05      # 本文は 0.38・23 Hz(合わない)
    assert abs(k3 - 2.281) < 1e-3                                   # 本文の利得余裕は 1.87(合わない)
    p = m.PRParams(**PLL4)
    r = m.simple_roots(p, 1.05 * k4)
    lc = r[np.argmax(r.real)]
    md = max((q for q in m.simple_simulate(p, 1.05 * k4) if q[0] > 5), key=lambda q: q[2])
    assert abs(md[1] - lc.real) < 1e-4 and abs(md[0] - abs(lc.imag) / (2 * math.pi)) < 1e-4


def test_case3_critical_id_matches_the_paper():
    c_sh = m.critical_id_eig(m.PRParams(**CASE3), lo=0.05, hi=6.0)
    c_no = m.critical_id_eig(m.PRParams(**CASE3, b_c=0.0), lo=0.05, hi=6.0)
    assert abs(c_sh / 1.18 - 1) < 0.03 and abs(c_no / 3.31 - 1) < 0.03
    assert abs(m.critical_id_loop(m.PRParams(**CASE3), c_sh * 0.97, c_sh * 1.03) - c_sh) < 1e-5


def _mode(p, lo, hi):
    osc = _band(m.eigenvalues(p), lo, hi)
    return complex(osc[np.argmax(osc.real)]) if osc.size else None


def test_case1_needs_the_smaller_gain():
    assert _mode(m.PRParams(**SLOW, **PLL_C1, i_d=0.1), 15, 30) is None    # 本文の定数では 22 Hz のモードが無い
    z1, z2 = _mode(HYP, 15, 30), _mode(HYP.replace(i_d=1.0), 15, 30)
    assert -12 < z1.real < -6 and 21 < z1.imag / (2 * math.pi) < 23
    assert z2.real < z1.real                                                # 出力を上げると左へ(本文と同じ向き)


def test_route3_signature_matches_route1():
    a = m.state_matrix(HYP)
    lam, v = np.linalg.eig(a)
    k = max((j for j in range(lam.size) if 2 * math.pi * 5 < lam[j].imag < 2 * math.pi * 60), key=lambda j: lam[j].real)
    ratio = abs(v[0, k] + 1j * v[1, k]) / abs(v[0, k] - 1j * v[1, k])
    f_dq = lam[k].imag / (2 * math.pi)
    r = m.simulate(HYP, t_end=0.6)
    (fs, ss), (fp, sp) = pair_from_modes(r.modes, HYP.f0, f_dq)
    assert abs(fs - (HYP.f0 - f_dq)) < 0.01 and abs(fp - (HYP.f0 + f_dq)) < 0.01
    assert abs(ss - lam[k].real) < 0.05 and abs(sp - lam[k].real) < 0.05
    a_sub = min(r.modes, key=lambda q: abs(q[0] - fs))[2]
    a_sup = min(r.modes, key=lambda q: abs(q[0] - fp))[2]
    assert ratio > 50 and abs(a_sup / a_sub / ratio - 1) < 0.01            # super(82 Hz)が主
