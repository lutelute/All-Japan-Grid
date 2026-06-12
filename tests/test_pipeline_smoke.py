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
    # Pinned from the multi-voltage + evidence-based snapped build
    # (2026-06-10): one bus per voltage class with intra-substation
    # transformer stubs (no line swallowing), circuits/cables tags drive
    # parallel counts, fixed 20 km plant lookup (gens 16 -> 22).
    # 2026-06-12 OSM-faithful binding ON (ledger 85): polygon-first
    # binding keeps out-of-radius mid-vertices as junction buses instead
    # of fusing them into substations (89 -> 102 buses, 79 -> 92 lines).
    # 2026-06-12 name-evidence tip binding (ledger 91): named tips join
    # their substations, absorbing stub junctions (102 -> 96 buses,
    # 92 -> 84 lines; ledger 98: name-claimed class adoption joins one more tip) and adding two class nodes' trafos (14 -> 16).
    assert info["topology"] == "snapped"
    assert info["n_buses"] == 96
    assert info["n_lines"] == 84
    assert info["n_gens"] == 22
    assert info["n_trafos"] == 16


def test_dc_and_ac_converge(okinawa_solved):
    _dc, dc_res, net_ac, ac_res, _info, _geom = okinawa_solved
    assert dc_res["converged"] is True
    assert ac_res["converged"] is True
    assert len(net_ac.bus) == 96
    vmin = float(net_ac.res_bus.vm_pu.min())
    # 0.647 measured: voltage propagation typed the northern 66 kV spur
    # that previously hid at an inferred higher class — honest sag on an
    # uncompensated radial (the backbone product model sits at 1.006)
    assert 0.60 < vmin <= 1.05
