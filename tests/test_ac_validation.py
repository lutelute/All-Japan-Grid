import copy

import numpy as np
import pandapower as pp
import pytest

from src.powerflow.ac_validation import (
    identity_load_trial, restore_source_branch, strict_ac, ybus_diagnosis)


def small_net():
    n = pp.create_empty_network()
    for i in range(3):
        pp.create_bus(n, 500, zone="east", name=f"b{i}", geodata=(140+i/100, 38))
    pp.create_ext_grid(n, 0)
    pp.create_line_from_parameters(n, 0, 1, length_km=2., r_ohm_per_km=.02,
                                   x_ohm_per_km=.3, c_nf_per_km=10., max_i_ka=2.)
    pp.create_line_from_parameters(n, 1, 2, length_km=1., r_ohm_per_km=.02,
                                   x_ohm_per_km=.3, c_nf_per_km=10., max_i_ka=2.)
    for b in (1, 2):
        pp.create_load(n, b, p_mw=10., q_mvar=3., name=f"load_{b}")
        pp.create_shunt(n, b, q_mvar=-2.4)
    return n


def test_source_split_preserves_dc_flow_and_parent_impedance():
    n = small_net()
    plan = dict(parent_circuit_line=0, parent_buses=[0, 1], station_bus=2,
                split_lengths_km=[.8, 1.2], tap_source=[38., 140.004],
                split_coordinates=[[[140, 38], [140.004, 38]],
                                   [[140.004, 38], [140.01, 38]]], branches=[])
    split, ledger = restore_source_branch(n, plan, add_branch=False)
    assert len(n.bus) == 3
    pp.rundcpp(n)
    pp.rundcpp(split)
    np.testing.assert_allclose(n.res_line.p_from_mw, split.res_line.loc[n.line.index].p_from_mw,
                               atol=1e-9)
    series = split.line.loc[[0, ledger["split_line"]]]
    assert np.isclose((series.length_km * series.r_ohm_per_km).sum(), .04)
    assert np.isclose((series.length_km * series.c_nf_per_km).sum(), 20.)
    stale = copy.deepcopy(plan)
    stale["parent_buses"] = [1, 0]
    with pytest.raises(ValueError, match="endpoints"):
        restore_source_branch(n, stale)


def test_identity_load_keeps_totals_and_rejects_observed_or_cross_voltage():
    n = small_net()
    pp.create_load(n, 0, 10., 3., name="load_0")
    pp.create_shunt(n, 0, -2.4)
    group = dict(osm_identity="way/1", zone="east", kv=500., buses=[1, 2])
    after, _ = identity_load_trial(n, [group])
    assert np.isclose(after.load.p_mw.sum(), 30.)
    np.testing.assert_allclose(after.load.p_mw, [7.5, 7.5, 15.])
    assert after.line.equals(n.line) and after.gen.equals(n.gen)
    np.testing.assert_allclose(n.load.p_mw, [10., 10., 10.])
    measured = copy.deepcopy(n)
    measured.load.at[0, "name"] = "load_obs_1"
    with pytest.raises(ValueError, match="unpinned"):
        identity_load_trial(measured, [group])
    wrong = dict(group, kv=275.)
    with pytest.raises(ValueError, match="Voltage"):
        identity_load_trial(n, [wrong])
    with pytest.raises(ValueError, match="Overlapping"):
        identity_load_trial(n, [group, group])


def test_q_unbounded_result_is_not_accepted_as_constraint_compliance():
    n = small_net()
    pp.create_gen(n, 1, 1., vm_pu=1.02, min_q_mvar=-.01, max_q_mvar=.01)
    _, unbounded = strict_ac(n, enforce_q_lims=False)
    assert unbounded["converged"] and unbounded["q_violations"] > 0
    assert not unbounded["ac_equations_and_q_pass"]
    _, bounded = strict_ac(n)
    assert bounded["ac_equations_and_q_pass"]
    assert bounded["max_q_violation_mvar"] <= 1e-4
    assert bounded["finite_buses"] == 3
    assert bounded["mismatch_max_mva"] <= 1e-4


def test_isolated_reference_zero_ybus_is_not_failure():
    n = small_net()
    b = pp.create_bus(n, 66, zone="east")
    pp.create_ext_grid(n, b)
    diagnostic = ybus_diagnosis(n)
    assert diagnostic["reference_buses"] == 2
    assert diagnostic["zero_diagonal_buses"] == [b]
    assert diagnostic["grounded_ybus"]["size"] == 2
    assert diagnostic["grounded_ybus"]["condition_1norm_estimate"] > 0
