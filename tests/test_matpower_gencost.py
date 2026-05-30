"""Unit tests for the OPF-enabling additions to src.matpower.exporter.

Covers:
    - build_gencost(): valid MATPOWER polynomial cost table, correct merit
      order, one row per generator, startup/shutdown scaling.
    - build_matpower_case(network=...): building from a model GridNetwork
      (the "snapped" topology path) including the GENCOST attachment.
    - save_case_to_matfile(): a round-trippable, standards-width .mat file.
"""

import numpy as np
import pytest

from src.matpower.exporter import (
    GC_MODEL,
    GC_NCOST,
    GC_COST0,
    POLYNOMIAL,
    build_gencost,
    build_matpower_case,
    save_case_to_matfile,
    _gencost_fuel_key,
)
from src.model.generator import Generator
from src.model.grid_network import GridNetwork
from src.model.substation import Substation
from src.model.transmission_line import TransmissionLine


# ----------------------------------------------------------------------
# build_gencost
# ----------------------------------------------------------------------


def test_gencost_shape_and_model():
    GEN = np.zeros((3, 10))
    GEN[:, 8] = [600.0, 400.0, 50.0]  # PMAX
    gc = build_gencost(GEN, ["coal", "lng", "hydro"], gen_caps_mw=[600, 400, 50])
    assert gc.shape == (3, 7)
    assert np.all(gc[:, GC_MODEL] == POLYNOMIAL)
    assert np.all(gc[:, GC_NCOST] == 3)


def test_gencost_merit_order():
    """Nuclear/hydro/renewables must be cheaper than fossil; oil dearest."""
    fuels = ["nuclear", "hydro", "solar", "wind", "coal", "lng", "oil"]
    GEN = np.zeros((len(fuels), 10))
    gc = build_gencost(GEN, fuels, gen_caps_mw=[100] * len(fuels))
    c1 = {f: gc[i, GC_COST0 + 1] for i, f in enumerate(fuels)}
    assert c1["solar"] == 0.0 and c1["wind"] == 0.0
    assert c1["nuclear"] < c1["coal"] < c1["lng"] < c1["oil"]
    assert c1["hydro"] <= c1["nuclear"]


def test_gencost_startup_scales_with_capacity():
    GEN = np.zeros((2, 10))
    gc = build_gencost(GEN, ["coal", "coal"], gen_caps_mw=[100.0, 200.0])
    # Startup cost is per-MW * capacity, so doubling capacity doubles startup.
    assert gc[1, 1] == pytest.approx(2 * gc[0, 1])


def test_gencost_unknown_fuel_falls_back():
    GEN = np.zeros((1, 10))
    gc = build_gencost(GEN, ["some-weird-source"], gen_caps_mw=[10.0])
    assert gc[0, GC_MODEL] == POLYNOMIAL
    assert gc[0, GC_COST0 + 1] > 0  # has a non-zero marginal cost


def test_gencost_fuel_key_mapping():
    assert _gencost_fuel_key("LNG/GTCC") == "lng"
    assert _gencost_fuel_key("natural gas") == "lng"
    assert _gencost_fuel_key("石炭 coal") == "coal"
    assert _gencost_fuel_key("nuclear") == "nuclear"
    assert _gencost_fuel_key("") == "unknown"


# ----------------------------------------------------------------------
# build_matpower_case(network=...) — model GridNetwork path
# ----------------------------------------------------------------------


def _toy_network():
    """A small connected 3-bus model network with two generators."""
    net = GridNetwork(region="shikoku", frequency_hz=60)
    for i in range(3):
        net.add_substation(Substation(
            id=f"s{i}", name=f"S{i}", region="shikoku",
            latitude=34.0 + i * 0.1, longitude=133.0 + i * 0.1,
            voltage_kv=275.0,
        ))
    net.add_transmission_line(TransmissionLine(
        id="l0", name="L0", from_substation_id="s0", to_substation_id="s1",
        voltage_kv=275.0, length_km=20.0, region="shikoku",
    ))
    net.add_transmission_line(TransmissionLine(
        id="l1", name="L1", from_substation_id="s1", to_substation_id="s2",
        voltage_kv=275.0, length_km=30.0, region="shikoku",
    ))
    net.add_generator(Generator(
        id="g0", name="G0", capacity_mw=600.0, fuel_type="coal",
        connected_bus_id="s0", region="shikoku",
    ))
    net.add_generator(Generator(
        id="g1", name="G1", capacity_mw=400.0, fuel_type="lng",
        connected_bus_id="s2", region="shikoku",
    ))
    return net


def test_build_case_from_model_network():
    case = build_matpower_case(network=_toy_network())
    assert case["n_bus"] == 3
    assert case["BRANCH"].shape[0] == 2
    assert case["n_gen"] == 2
    # GENCOST present, one row per generator, both naming conventions.
    assert "GENCOST" in case and "gencost" in case
    assert case["GENCOST"].shape == (2, 7)
    # BUS/BRANCH/GEN keep the legacy compact widths.
    assert case["BUS"].shape[1] == 13
    assert case["BRANCH"].shape[1] == 9
    assert case["GEN"].shape[1] == 10
    # Exactly one reference (slack) bus.
    assert np.sum(case["BUS"][:, 1] == 3) == 1


def test_legacy_keys_preserved_on_model_path():
    case = build_matpower_case(network=_toy_network())
    for k in ("BUS", "BRANCH", "GEN", "MD", "ED", "TD", "baseMVA",
              "gen_fuel", "bus_names", "n_gen", "n_bus", "slack_bus",
              "gen_buses_1idx"):
        assert k in case, f"missing legacy key {k}"


# ----------------------------------------------------------------------
# save_case_to_matfile — round trip
# ----------------------------------------------------------------------


def test_save_and_reload_matfile(tmp_path):
    from scipy.io import loadmat

    case = build_matpower_case(network=_toy_network())
    out = tmp_path / "toy.mat"
    save_case_to_matfile(case, str(out))
    assert out.exists()

    raw = loadmat(str(out), struct_as_record=False, squeeze_me=True)
    mpc = raw["mpc"]
    assert int(mpc.bus.shape[0]) == case["n_bus"]
    assert int(mpc.branch.shape[0]) == case["BRANCH"].shape[0]
    assert int(mpc.gencost.shape[0]) == case["n_gen"]
    # Branch padded to full 13-col MATPOWER width; gen to 21.
    assert mpc.branch.shape[1] == 13
    assert mpc.gen.shape[1] == 21
    assert float(mpc.baseMVA) == case["baseMVA"]


def test_matfile_loads_in_pandapower(tmp_path):
    """The written .mat must import via pandapower and carry the cost table."""
    from pandapower.converter.matpower.from_mpc import from_mpc

    case = build_matpower_case(network=_toy_network())
    out = tmp_path / "toy.mat"
    save_case_to_matfile(case, str(out))

    net = from_mpc(str(out))
    assert len(net.bus) == case["n_bus"]
    # gencost -> poly_cost: proves the OPF cost data survived the round trip.
    assert len(net.poly_cost) == case["n_gen"]
