"""Lexicographic redispatch LP on a three-bus triangle (equal reactances, load at bus 2).

PTDF with bus 2 as reference, columns = unit at bus 0 (10 yen/MWh) and unit at bus 1 (20 yen/MWh):
line 0-1: [1/3, -1/3], line 0-2: [2/3, 1/3], line 1-2: [1/3, 2/3]. The plan puts all 100 MW on
the cheap unit.
"""

import numpy as np
import pytest

pytest.importorskip("pandapower")
from scripts.scuc_redispatch import redispatch_lp  # noqa: E402

A = np.array([[1 / 3, -1 / 3], [2 / 3, 1 / 3], [1 / 3, 2 / 3]])
P0, LO, HI, COST = np.array([100.0, 0.0]), np.zeros(2), np.full(2, 100.0), np.array([10.0, 20.0])
BIG = 1e9


def test_congestion_dual_is_the_fuel_saving_per_mw():
    r = redispatch_lp(A, np.zeros(3), np.array([BIG, 50.0, BIG]), P0, LO, HI, COST)
    assert r["least_over"] == pytest.approx(0, abs=1e-6)
    assert r["p"] == pytest.approx([50, 50], abs=1e-3)
    # one more MW on line 0-2 lets 3 MW move from the 20 to the 10 yen unit
    assert r["duals"][1] == pytest.approx(30)
    assert r["gain"][1] == pytest.approx(30)          # the dual holds over the whole MW here


def test_unclearable_overload_does_not_leak_into_the_duals():
    # Line 1-2 cannot get below 45 MW without line 0-1 going above 10 MW: 25 MW stay over in any
    # redispatch. A penalty LP would price line 0-1 at half the penalty; here it is fuel only.
    r = redispatch_lp(A, np.zeros(3), np.array([10.0, BIG, 20.0]), P0, LO, HI, COST)
    assert r["least_over"] == pytest.approx(25)
    assert r["over_after"] == pytest.approx([0, 0, 25], abs=1e-3)
    assert r["p"] == pytest.approx([65, 35], abs=1e-3)
    assert r["duals"][0] == pytest.approx(15)
    assert r["gain"][0] == pytest.approx(15)
    assert r["gain"][2] == 0                          # still over: no value reported


def test_one_more_mw_is_measured_not_extrapolated_from_the_dual():
    # The line barely feels the units (PTDF 1e-3): the dual is 10 yen / 0.002 = 5,000 per MW,
    # but one more MW only lets the cheap unit go from 60 to its maximum of 100 MW: 400 yen.
    a = np.array([[1e-3, -1e-3]])
    r = redispatch_lp(a, np.zeros(1), np.array([0.02]), np.array([0.0, 100.0]), LO, HI, COST)
    assert r["p"] == pytest.approx([60, 40], abs=1e-3)
    assert r["duals"][0] == pytest.approx(5000)
    assert r["gain"][0] == pytest.approx(400, rel=1e-5)


def test_weight_keeps_the_overload_on_the_line_that_was_over():
    # Two radial lines, one per unit: 10 MW stay over whichever way 100 MW are split. Fuel alone
    # would move the overload onto line 1, which was fine in the plan; the weight keeps it on 0.
    a = np.eye(2)
    args = (a, np.zeros(2), np.array([60.0, 30.0]), P0, LO, HI, np.array([20.0, 10.0]))
    assert redispatch_lp(*args)["over_after"] == pytest.approx([0, 10], abs=1e-3)
    assert redispatch_lp(*args, weight=[1.0, 1.001])["over_after"] == pytest.approx([10, 0], abs=1e-3)
