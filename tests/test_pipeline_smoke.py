"""End-to-end smoke test for the power-flow pipeline (build_and_solve).

This is the safety net for the Phase C (3) pipeline-promotion refactor:
it pins the current behaviour of ``build_and_solve`` on the small okinawa
region so that moving the pipeline functions from
examples/scripts into ``src/powerflow`` (with back-compat re-exports) can
be verified behaviour-preserving. The import path is the public one
``scripts.export_powerflow_pages`` which must keep working across the
refactor.
"""

import pytest

pytest.importorskip("pandapower")

from scripts.export_powerflow_pages import build_and_solve  # noqa: E402
from src.powerflow.load_estimator import load_demand_config  # noqa: E402


@pytest.fixture(scope="module")
def okinawa_solved():
    cfg = load_demand_config()
    return build_and_solve("okinawa", cfg, topology="snapped", reconnect=True)


def test_returns_six_tuple(okinawa_solved):
    assert len(okinawa_solved) == 6


def test_build_info_shape(okinawa_solved):
    _dc, _dcr, _ac, _acr, info, _geom = okinawa_solved
    # Pinned from the current snapped build (incl. the #6 parallel fix).
    assert info["topology"] == "snapped"
    assert info["n_buses"] == 81
    assert info["n_lines"] == 57
    assert info["n_gens"] == 16
    assert info["n_trafos"] == 25


def test_dc_and_ac_converge(okinawa_solved):
    _dc, dc_res, net_ac, ac_res, _info, _geom = okinawa_solved
    assert dc_res["converged"] is True
    assert ac_res["converged"] is True
    assert len(net_ac.bus) == 81
    vmin = float(net_ac.res_bus.vm_pu.min())
    assert 0.85 < vmin <= 1.05  # solved, physically sane okinawa range
