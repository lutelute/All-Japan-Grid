"""stitch_slice_boundaries: cross-region duplicate fusion at slice edges.

Regional OSM slices overlap, so a boundary corridor exists in both
member networks as disconnected parallel copies. Stitching fuses buses
of the same voltage class within ~110 m ACROSS regions (same-region
duplicates are intentional data-quality signals and stay), preferring a
real substation over a junction as the survivor.

Measured on real data (2026-06-10): west island fused 2,171 duplicate
buses (components 561 -> 428), east 131 (283 -> 271).
"""

import pytest

from src.model.grid_network import GridNetwork
from src.model.substation import Substation
from src.model.transmission_line import TransmissionLine
from src.powerflow.national import stitch_slice_boundaries


def _sub(sid, region, lat, lon, kv=275.0, name=None):
    return Substation(id=sid, name=name or sid, region=region,
                      latitude=lat, longitude=lon, voltage_kv=kv)


def _line(lid, a, b, kv=275.0):
    return TransmissionLine(id=lid, name=lid, from_substation_id=a,
                            to_substation_id=b, voltage_kv=kv,
                            length_km=10.0, region="x")


def test_fuses_cross_region_junction_onto_real_substation():
    net = GridNetwork(region="east", frequency_hz=50)
    net.add_substation(_sub("tokyo_jct_37.38:140.80", "tokyo", 37.3800, 140.8000))
    net.add_substation(_sub("tohoku_sub_5", "tohoku", 37.3801, 140.8001,
                            name="新いわき変電所"))
    net.add_substation(_sub("tokyo_sub_1", "tokyo", 36.0, 139.0))
    net.add_transmission_line(_line("l1", "tokyo_sub_1", "tokyo_jct_37.38:140.80"))

    n = stitch_slice_boundaries(net)
    assert n == 1
    ids = {s.id for s in net.substations}
    assert "tokyo_jct_37.38:140.80" not in ids        # junction fused away
    assert "tohoku_sub_5" in ids                      # real substation survives
    ln = net.transmission_lines[0]
    assert ln.to_substation_id == "tohoku_sub_5"      # endpoint rewired
    assert net.get_substation("tokyo_jct_37.38:140.80") is None


def test_same_region_duplicates_untouched():
    net = GridNetwork(region="east", frequency_hz=50)
    net.add_substation(_sub("tokyo_sub_1", "tokyo", 37.0, 140.0))
    net.add_substation(_sub("tokyo_sub_2", "tokyo", 37.0, 140.0))   # same spot
    assert stitch_slice_boundaries(net) == 0
    assert len(net.substations) == 2


def test_different_voltage_classes_not_fused():
    net = GridNetwork(region="east", frequency_hz=50)
    net.add_substation(_sub("tokyo_jct_a", "tokyo", 37.0, 140.0, kv=275.0))
    net.add_substation(_sub("tohoku_jct_b", "tohoku", 37.0, 140.0, kv=154.0))
    assert stitch_slice_boundaries(net) == 0
    assert len(net.substations) == 2


def test_generator_connection_rewired():
    from src.model.generator import Generator
    net = GridNetwork(region="east", frequency_hz=50)
    net.add_substation(_sub("tokyo_jct_x", "tokyo", 37.0, 140.0))
    net.add_substation(_sub("tohoku_sub_y", "tohoku", 37.0001, 140.0001))
    net.add_generator(Generator(id="g1", name="g1", capacity_mw=100.0,
                                fuel_type="gas", connected_bus_id="tokyo_jct_x",
                                region="tokyo"))
    assert stitch_slice_boundaries(net) == 1
    assert net.generators[0].connected_bus_id == "tohoku_sub_y"
