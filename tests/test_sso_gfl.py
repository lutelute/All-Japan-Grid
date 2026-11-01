"""SSO 段 A(GFL 1 台 + テブナン等価)の 3 つの道がそろうこと(2026-11-01).

報告: docs/reports/sso_ibr_stage_a_2026-11-01.md。模型: src/dynamics/sso/gfl.py。
"""
import math

import numpy as np
import pytest

from src.dynamics.sso import gfl
from src.dynamics.sso.pencil import matrix_pencil

STABLE = gfl.GFLParams(scr=1.6)       # FF なし・PLL 40 Hz
UNSTABLE = gfl.GFLParams(scr=1.3)


def test_equilibrium_is_a_fixed_point():
    for p in (STABLE, UNSTABLE, STABLE.replace(k_ff=1.0)):
        eq = gfl.equilibrium(p)
        assert np.abs(gfl._rhs(p, eq.x, None)).max() < 1e-9
        assert eq.x[5] == 0.0 and abs(eq.vc_c - (eq.v_pcc + complex(p.r_f, p.w0 * p.l_f) * eq.i_c)) < 1e-12


def test_no_equilibrium_beyond_static_limit():
    with pytest.raises(ValueError):
        gfl.equilibrium(gfl.GFLParams(scr=0.9))


@pytest.mark.parametrize("p", [STABLE, UNSTABLE, STABLE.replace(k_ff=1.0, scr=2.5), STABLE.replace(k_ff=1.0, scr=1.8)])
def test_route2_zeros_equal_route1_eigenvalues(p):
    lam = gfl.eigenvalues(p)
    lam = lam[lam.imag > 2 * math.pi * 0.5]
    z = gfl.admittance_zeros(p)
    assert z.size == lam.size
    for x in lam:
        assert np.min(np.abs(z - x)) < 1e-6 * abs(x)


def test_route2_rhp_count_matches_route1():
    assert gfl.rhp_zero_count(STABLE) == 0 == int(np.sum(gfl.eigenvalues(STABLE).real > 0))
    assert gfl.rhp_zero_count(UNSTABLE) == 2 == int(np.sum(gfl.eigenvalues(UNSTABLE).real > 0))


def test_critical_scr_routes_1_and_2_agree():
    c1 = gfl.critical_scr_eig(STABLE)
    c2 = gfl.critical_scr_admittance(STABLE, c1 * 0.97, c1 * 1.03)
    assert 1.3 < c1 < 1.6 and abs(c1 - c2) < 1e-5


def test_time_domain_stays_at_equilibrium():
    r = gfl.simulate(STABLE, t_end=0.2, d_theta=0.0)
    assert np.abs(r.di_a).max() < 1e-10


@pytest.mark.parametrize("p", [STABLE, UNSTABLE])
def test_route3_shows_sub_super_pair(p):
    lc = gfl.critical_mode(gfl.eigenvalues(p))
    f_dq = lc.imag / (2 * math.pi)
    r = gfl.simulate(p, t_end=0.5)
    (fs, ss), (fp, sp) = gfl.pair_from_modes(r.modes, p.f0, f_dq)
    assert abs(fs - (p.f0 - f_dq)) < 0.01 and abs(fp - (p.f0 + f_dq)) < 0.01
    assert abs(fs + fp - 2 * p.f0) < 0.01
    assert abs(ss - lc.real) < 0.05 and abs(sp - lc.real) < 0.05


def test_critical_mode_is_a_pll_mode():
    _, pf = gfl.participation(STABLE.replace(scr=1.43))
    assert pf["δ"] + pf["x_pll"] > 0.5


def test_matrix_pencil_recovers_known_modes():
    dt = 1e-3
    t = np.arange(0, 0.6, dt)
    y = 1.0 * np.exp(-3.0 * t) * np.cos(2 * math.pi * 31.0 * t) + 0.4 * np.exp(1.5 * t) * np.cos(2 * math.pi * 69.0 * t + 0.3)
    modes = matrix_pencil(y, dt, n_modes=4)
    got = sorted((round(f, 6), round(s, 6)) for f, s, _ in modes)
    assert got == [(31.0, -3.0), (69.0, 1.5)]
