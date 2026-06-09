"""Parallel-circuit counting for the vertex-snap topology builder.

Guards REVIEW_FINDINGS #6 (examples/build_snapped_topology.py):
- a single OSM way is ONE circuit even when its vertices zig-zag across a
  node pair (snapping back and forth) — must not inflate ``parallel``;
- genuine parallels (separate ways between the same nodes) must sum;
- a degree-2 junction chain (e.g. a double circuit sharing towers) must
  carry its circuit count through contraction instead of resetting to 1.

Exercised on synthetic single-corridor regions via a monkeypatched
DATA_DIR, asserting the resulting TransmissionLine.num_parallel.
"""

import importlib
import json

build_snapped = importlib.import_module("examples.build_snapped_topology")

# [lon, lat] (GeoJSON order). B is ~5.5 km east of A; MID ~2.7 km from each,
# beyond snap_km=2 so it stays an (unsnapped) junction enabling contraction.
A = [139.000, 35.000]
B = [139.060, 35.000]
MID = [139.030, 35.000]


def _sub(lonlat, name):
    return {"type": "Feature",
            "properties": {"voltage": "154000", "name": name},
            "geometry": {"type": "Point", "coordinates": lonlat}}


def _line(coords):
    return {"type": "Feature",
            "properties": {"voltage": "154000"},
            "geometry": {"type": "LineString", "coordinates": coords}}


def _build(tmp_path, monkeypatch, region, subs, lines, **kw):
    fc = lambda feats: json.dumps({"type": "FeatureCollection", "features": feats})
    (tmp_path / f"{region}_substations.geojson").write_text(fc(subs), encoding="utf-8")
    (tmp_path / f"{region}_lines.geojson").write_text(fc(lines), encoding="utf-8")
    (tmp_path / f"{region}_plants.geojson").write_text(fc([]), encoding="utf-8")
    # build_network_snapped now takes an injectable data_dir (it moved to
    # src.powerflow.snapped_topology in the Phase C pipeline promotion).
    net = build_snapped.build_network_snapped(
        region, snap_km=2.0, keep_stubs=True, data_dir=str(tmp_path), **kw)
    return sorted(ln.num_parallel for ln in net.transmission_lines)


SUBS = [_sub(A, "A"), _sub(B, "B")]


class TestParallelCounting:
    def test_zigzag_single_way_counts_one(self, tmp_path, monkeypatch):
        # one way A -> B -> A: the pair is revisited but it is ONE circuit
        assert _build(tmp_path, monkeypatch, "zz", SUBS, [_line([A, B, A])]) == [1]

    def test_two_separate_ways_sum_to_two(self, tmp_path, monkeypatch):
        pars = _build(tmp_path, monkeypatch, "par", SUBS,
                      [_line([A, B]), _line([A, B])])
        assert pars == [2]

    def test_single_chain_is_one(self, tmp_path, monkeypatch):
        # one way through an unsnapped junction -> single circuit after collapse
        pars = _build(tmp_path, monkeypatch, "single", SUBS, [_line([A, MID, B])])
        assert pars == [1]

    def test_chain_contraction_carries_parallel(self, tmp_path, monkeypatch):
        # double circuit sharing a tower: two ways A -> MID -> B, MID a junction
        pars = _build(tmp_path, monkeypatch, "chain", SUBS,
                      [_line([A, MID, B]), _line([A, MID, B])])
        assert pars == [2]
