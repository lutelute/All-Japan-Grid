"""Faithful provenance roundtrip (_src: field markers) — the #8 unblock.

Baking curated values into exported GeoJSON used to DESTROY their
provenance on re-ingest (capacity_mw became a raw OSM tag; p03_db
degraded to a refetch-erasable legacy marker). With markers=True the
export carries per-field provenance (_src:capacity_mw = "p03_db") and
decompose restores the curated row with its ORIGINAL source — so the
published derived files can finally carry authoritative values without
breaking the mechanical-update loop.
"""

import json

from src.db.geojson_sync import (
    apply_enrichments,
    decompose_properties,
    export_geojson,
    ingest_geojson,
)
from src.db.grid_db import GridDatabase


def _mini_plants(tmp_path):
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "properties": {"name": "テスト発電所", "plant:source": "gas",
                        "osm_id": 123, "osm_type": "way"},
         "geometry": {"type": "Point", "coordinates": [135.0, 35.0]}},
    ]}
    p = tmp_path / "t_plants.geojson"
    p.write_text(json.dumps(fc), encoding="utf-8")
    return str(p)


def test_markers_survive_reingest_with_original_source(tmp_path):
    db = GridDatabase(":memory:")
    ingest_geojson(db, "testreg", "plants", _mini_plants(tmp_path))
    from src.db.geojson_sync import iter_composed
    keys = [k for k, _p, _g in iter_composed(db, "testreg", "plants")]
    apply_enrichments(db, [{"layer": "plants", "region": "testreg",
                            "feature_key": keys[0], "field": "capacity_mw",
                            "value": 1234.5, "source": "p03_db"}])

    out = export_geojson(db, "testreg", "plants", markers=True)
    props = out["features"][0]["properties"]
    assert props["capacity_mw"] == 1234.5
    assert props["_src:capacity_mw"] == "p03_db"

    # re-ingest the BAKED file into a fresh db: provenance must survive
    baked = tmp_path / "baked.geojson"
    baked.write_text(json.dumps(out), encoding="utf-8")
    db2 = GridDatabase(":memory:")
    ingest_geojson(db2, "testreg", "plants", str(baked))
    rows = db2.session_factory().execute(
        __import__("sqlalchemy").text(
            "select field, value, source from enrichments where field='capacity_mw'")
    ).all()
    assert rows and rows[0].source == "p03_db"
    assert json.loads(rows[0].value) == 1234.5
    # and the raw tags did NOT swallow the curated value
    raw = db2.session_factory().execute(
        __import__("sqlalchemy").text("select tags from raw_features")).all()
    assert "capacity_mw" not in json.loads(raw[0].tags)


def test_decompose_ignores_marker_transport_fields():
    raw, curated = decompose_properties(
        {"name": "X", "capacity_mw": 9.9, "_src:capacity_mw": "p03_db"})
    assert raw == {"name": "X"}
    assert ("capacity_mw", 9.9, "p03_db") in curated
    assert not any(f.startswith("_src:") for f, _v, _s in curated)


def test_default_export_unchanged_no_markers(tmp_path):
    db = GridDatabase(":memory:")
    ingest_geojson(db, "testreg", "plants", _mini_plants(tmp_path))
    out = export_geojson(db, "testreg", "plants")
    assert not any(k.startswith("_src:")
                   for k in out["features"][0]["properties"])
