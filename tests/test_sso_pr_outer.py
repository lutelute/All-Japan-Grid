"""SSO 段 B の続き: 外側の制御・制限と、REAL20HZ2022 の Case 3 の EMT(27 Hz)の運転点(2026-11-01).

報告: docs/reports/sso_ibr_stage_b2_2026-11-01.md。模型: src/dynamics/sso/gfl_pr.py。
"""
import math

import numpy as np
import pytest

from src.dynamics.sso import gfl_pr as m
from src.dynamics.sso.gfl import pair_from_modes

PLL3 = dict(kp_pll=150.0, ki_pll=2000.0, lpf_order=1)
PRE = dict(x_g=0.15, r_g=0.15 / 8)
POST = dict(x_g=0.37, r_g=0.37 / 8)


def _op(net, shunt=True, p_out=0.8):
    return m.at_source(m.PRParams(**net, **PLL3, **({} if shunt else {"b_c": 0.0})), p_out, 1.0)


def _mode(p, lo=15.0, hi=45.0):
    lam = m.eigenvalues(p)
    osc = lam[(lam.imag > 2 * math.pi * lo) & (lam.imag < 2 * math.pi * hi)]
    return complex(osc[np.argmax(osc.real)])


VARIANTS = [("pq", {}), ("pq", {"f_meas": 100.0}), ("pq", {"kv_q": 7.0}), ("pv", {}), ("pv", {"f_meas": 10.0})]


@pytest.mark.parametrize("outer,kw", VARIANTS)
def test_outer_equilibrium_is_a_fixed_point(outer, kw):
    p = m.with_outer(_op(POST), outer).replace(**kw)
    eq = m.equilibrium(p)
    assert np.abs(m._rhs(p, eq.x, eq.v_g, None)).max() < 1e-8


def test_limits_do_not_act_at_the_equilibrium():
    for p in (_op(POST), m.with_outer(_op(POST), "pq").replace(f_meas=10.0)):
        a = m.eigenvalues(p)
        b = m.eigenvalues(p.replace(i_max=1.5, v_max=1.5, df_max=10.0))
        assert np.abs(np.sort_complex(a) - np.sort_complex(b)).max() < 1e-6 * np.abs(a).max()


def test_voltage_limit_branch_matches_the_unlimited_algebra():
    p = _op(POST)
    eq = m.equilibrium(p)
    x = eq.x + 1e-3 * np.random.default_rng(0).standard_normal(eq.x.size)
    a = m._rhs(p, x, eq.v_g, 0.013)
    b = m._rhs(p.replace(v_max=100.0), x, eq.v_g, 0.013)
    assert np.abs(a - b).max() < 1e-9 * np.abs(a).max()


def test_operating_point_matches_the_figure_reading():
    read = {True: (-0.55, -0.7), False: (-0.1, 0.0)}                     # 本文の図 13 の Q(目で読んだ値)
    for sh, qs in read.items():
        for net, q in zip((PRE, POST), qs):
            assert abs(m.equilibrium(_op(net, sh)).q_out - q) < 0.05


def test_paper_linear_model_gives_27hz_after_the_trip():
    z = _mode(_op(POST))
    assert z.real > 5 and 26 < z.imag / (2 * math.pi) < 28                # 本文の線形模型(外側なし)では育つ
    assert _mode(_op(POST, False)).real < -20                             # コンデンサが無ければ育たない
    zl = m.loop_zeros(_op(POST))                                          # i_q ≠ 0 でも道 2 がそろう
    assert min(abs(zl - z)) < 1e-6 * abs(z)


def test_pq_outer_loop_brings_the_mode_near_zero_damping():
    for pv in (0.7, 0.8, 0.9):
        z = _mode(m.with_outer(_op(POST, p_out=pv), "pq"))
        assert abs(z.real) < 1 and 26 < z.imag / (2 * math.pi) < 29
    with pytest.raises(ValueError):
        m.loop_zeros(m.with_outer(_op(POST), "pq"))


def test_route3_matches_route1_with_the_outer_loop():
    p = m.with_outer(_op(POST), "pq")
    z = _mode(p)
    f_dq = z.imag / (2 * math.pi)
    r = m.simulate(p, t_end=0.6)
    (fs, ss), (fp, sp) = pair_from_modes(r.modes, p.f0, f_dq)
    assert abs(fs - (p.f0 - f_dq)) < 0.01 and abs(fp - (p.f0 + f_dq)) < 0.01
    assert abs(ss - z.real) < 0.05 and abs(sp - z.real) < 0.05


def test_line_trip_oscillates_at_27hz_only_with_the_shunt():
    amp = {}
    for sh in (True, False):
        pre = m.with_outer(_op(PRE, sh), "pq").replace(kv_q=7.0)
        r = m.simulate_event(pre, pre.replace(**POST), t_event=0.1, t_end=1.1, fs=5000.0)
        sel = r.t > 0.6
        x = r.p[sel] - r.p[sel].mean()
        n = 16 * x.size                                                   # 0 を詰めて山の位置を細かく読む
        fr = np.fft.rfftfreq(n, 1 / 5000.0)
        f = fr[np.argmax(np.abs(np.fft.rfft(x * np.hanning(x.size), n))[1:]) + 1]
        amp[sh] = np.ptp(r.p[sel]) / 2
        if sh:
            assert 26 <= f <= 28
            assert abs(r.q[sel].mean() + 0.7) < 0.05 and abs(r.v[sel].mean() - 1) < 0.02
    assert amp[True] > 0.05 and amp[False] < 0.01                       # なしは電圧がゆっくり戻るだけ
