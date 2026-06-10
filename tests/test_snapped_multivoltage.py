"""Multi-voltage substation mechanics of build_network_snapped (synthetic).

Pins the three behaviours the refactor introduced:

1. a substation touched by two voltage classes becomes one bus per class
   plus an intra-substation transformer stub (the real busbar structure) —
   so a cross-voltage LINE is never swallowed into a transformer again;
2. two lines of different known classes crossing at a shared coordinate
   are NOT fused into a false junction;
3. an unknown-voltage segment joins the highest known class present at
   the shared coordinate (its usual continuation), keeping unlabelled
   transmission connected;
and the ``multi_voltage=False`` escape hatch preserves the legacy
single-bus-per-substation form for A/B comparison.
"""

import json

import pytest

from src.powerflow.snapped_topology import build_network_snapped


def _geojson(features):
    return {"type": "FeatureCollection", "features": features}


def _line(coords_lonlat, voltage=None, name="l"):
    props = {"name": name}
    if voltage is not None:
        props["voltage"] = voltage
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "LineString", "coordinates": coords_lonlat}}


def _sub(lon, lat, voltage=None, name="s"):
    props = {"name": name}
    if voltage is not None:
        props["voltage"] = voltage
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "Point", "coordinates": [lon, lat]}}


@pytest.fixture
def data_dir(tmp_path):
    """Substation at origin hit by a 275 kV and a 66 kV line; a 154/66
    crossing far away (>snap radius) sharing one coordinate; an unknown
    segment continuing the 154 kV line through that coordinate."""
    subs = _geojson([
        _sub(135.0, 35.0, voltage="275000", name="MainSub"),
        _sub(135.5, 35.5, name="FarSub"),
    ])
    lines = _geojson([
        _line([[135.0, 35.0], [135.08, 35.0]], voltage="275000", name="hv"),
        _line([[135.0, 35.0], [135.0, 35.08]], voltage="66000", name="lv"),
        # crossing at (135.30, 35.30): 154 kV and 66 kV share the coordinate
        _line([[135.25, 35.30], [135.30, 35.30]], voltage="154000", name="x154"),
        _line([[135.30, 35.25], [135.30, 35.30]], voltage="66000", name="x66"),
        # unlabelled continuation of the 154 kV line through the crossing
        _line([[135.30, 35.30], [135.35, 35.30]], name="x154cont"),
    ])
    d = tmp_path / "data"
    d.mkdir()
    (d / "testreg_substations.geojson").write_text(json.dumps(subs))
    (d / "testreg_lines.geojson").write_text(json.dumps(lines))
    return str(d)


def test_substation_splits_per_voltage_class_with_stub(data_dir):
    net = build_network_snapped("testreg", data_dir=data_dir)
    ids = {s.id for s in net.substations}
    assert "testreg_sub_0@275" in ids
    assert "testreg_sub_0@66" in ids
    assert "testreg_sub_0" not in ids        # plain id only for single-class
    stubs = [ln for ln in net.transmission_lines if "_xfmr_" in ln.id]
    assert len(stubs) == 1
    s = stubs[0]
    assert {s.from_substation_id, s.to_substation_id} == \
        {"testreg_sub_0@275", "testreg_sub_0@66"}
    assert s.length_km == pytest.approx(0.05)
    # the real 275 kV and 66 kV lines survive as LINES at their own class
    kv_of = {ln.voltage_kv for ln in net.transmission_lines if "_xfmr_" not in ln.id}
    assert {275.0, 66.0} <= kv_of


def test_cross_voltage_crossing_not_fused(data_dir):
    net = build_network_snapped("testreg", data_dir=data_dir)
    import networkx as nx
    g = nx.Graph()
    g.add_nodes_from(s.id for s in net.substations)
    for ln in net.transmission_lines:
        g.add_edge(ln.from_substation_id, ln.to_substation_id)
    comp_of = {}
    for ci, comp in enumerate(nx.connected_components(g)):
        for n in comp:
            comp_of[n] = ci
    j154 = [s.id for s in net.substations if "_jct_" in s.id and s.voltage_kv == 154.0]
    j66 = [s.id for s in net.substations if "_jct_" in s.id and s.voltage_kv == 66.0]
    assert j154 and j66
    # the 154-class and 66-class junction stacks at the crossing stay separate
    assert {comp_of[j] for j in j154}.isdisjoint({comp_of[j] for j in j66})


def test_unknown_segment_joins_highest_known_class(data_dir):
    net = build_network_snapped("testreg", data_dir=data_dir)
    import networkx as nx
    g = nx.Graph()
    for ln in net.transmission_lines:
        g.add_edge(ln.from_substation_id, ln.to_substation_id)
    # the unlabelled continuation must be reachable from the 154 kV line's
    # far endpoint — i.e. it merged into the 154 stack at the shared
    # coordinate, not a parallel world. (Its own far endpoint keeps class 0
    # in the id — no known class exists there — but inherits 154 kV as the
    # max incident voltage after chain collapse.)
    j154_end = "testreg_jct_35.3:135.25:154"
    unk_ends = [s.id for s in net.substations
                if "_jct_" in s.id and "135.35" in s.id]
    assert unk_ends, "unknown segment endpoint missing"
    assert nx.has_path(g, j154_end, unk_ends[0])
    unk = next(s for s in net.substations if s.id == unk_ends[0])
    assert unk.voltage_kv == 154.0


def test_multi_voltage_false_preserves_legacy_single_bus(data_dir):
    net = build_network_snapped("testreg", data_dir=data_dir, multi_voltage=False)
    ids = {s.id for s in net.substations}
    assert "testreg_sub_0" in ids
    assert not any("@" in i for i in ids)
    assert not any("_xfmr_" in ln.id for ln in net.transmission_lines)
