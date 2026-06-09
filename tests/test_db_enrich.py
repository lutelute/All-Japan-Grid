"""DB-native endpoint line enricher (DB unification Step 3b).

Real data/*.geojson is already enriched, so this tests on a *fresh raw*
synthetic region: ingest unnamed lines + named substations, run the DB
enricher, and assert the exported GeoJSON gains the same endpoint-based
names the in-place script would produce — proving enrich -> DB -> export.
"""

import json

import pytest

from src.db.enrich import apply_audit_fixes, enrich_lines_endpoints
from src.db.geojson_sync import export_geojson, ingest_geojson
from src.db.grid_db import GridDatabase

# Two named substations and an unnamed line between them.
SUB_A = {"type": "Feature",
         "properties": {"name": "嶺南変電所", "voltage": "500000",
                        "operator": "関西電力"},
         "geometry": {"type": "Point", "coordinates": [135.90, 35.55]}}
SUB_B = {"type": "Feature",
         "properties": {"name": "京北変電所", "voltage": "500000"},
         "geometry": {"type": "Point", "coordinates": [135.70, 35.30]}}
LINE_AB = {"type": "Feature",
           "properties": {"voltage": "500000"},  # unnamed
           "geometry": {"type": "LineString",
                        "coordinates": [[135.90, 35.55], [135.70, 35.30]]}}
LINE_ORPHAN = {"type": "Feature",
               "properties": {"voltage": "154000", "operator": "関西電力"},
               "geometry": {"type": "LineString",
                            "coordinates": [[120.0, 20.0], [120.1, 20.1]]}}


def _fc(feats):
    return json.dumps({"type": "FeatureCollection", "features": feats})


@pytest.fixture()
def seeded_db(tmp_path, monkeypatch):
    # Point both the GeoJSON enricher helpers and the builder at tmp data.
    import scripts.enrich_lines_endpoints as eli
    monkeypatch.setattr(eli, "DATA_DIR", str(tmp_path))
    (tmp_path / "kansai_substations.geojson").write_text(
        _fc([SUB_A, SUB_B]), encoding="utf-8")
    (tmp_path / "kansai_lines.geojson").write_text(
        _fc([LINE_AB, LINE_ORPHAN]), encoding="utf-8")
    db = GridDatabase(":memory:")
    ingest_geojson(db, "kansai", "substations",
                   str(tmp_path / "kansai_substations.geojson"))
    ingest_geojson(db, "kansai", "lines",
                   str(tmp_path / "kansai_lines.geojson"))
    return db


def _lines(db):
    return export_geojson(db, "kansai", "lines")["features"]


class TestDbLineEnricher:
    def test_endpoint_name_written_and_exported(self, seeded_db):
        before = _lines(seeded_db)
        assert all(not f["properties"].get("name") for f in before)

        stats = enrich_lines_endpoints(seeded_db, "kansai")
        assert stats == {"total": 2, "enriched": 2}

        after = {tuple(f["geometry"]["coordinates"][0]): f["properties"]
                 for f in _lines(seeded_db)}
        ab = after[(135.90, 35.55)]
        assert ab["name"] == "嶺南変電所~京北変電所線"
        assert ab["_enriched_by"] == "endpoint_matching"
        assert ab["_name_source"] == "endpoints"

    def test_operator_voltage_fallback(self, seeded_db):
        enrich_lines_endpoints(seeded_db, "kansai")
        orphan = [f for f in _lines(seeded_db)
                  if f["geometry"]["coordinates"][0] == [120.0, 20.0]][0]
        # far from any substation -> operator + voltage fallback
        assert orphan["properties"]["_name_source"] == "operator_voltage"
        assert "kV線" in orphan["properties"]["name"]

    def test_idempotent_and_survives_reingest(self, seeded_db, tmp_path):
        enrich_lines_endpoints(seeded_db, "kansai")
        once = _lines(seeded_db)
        # Re-ingest the raw file (OSM re-fetch stand-in): names persist
        # because endpoint_matching is not a legacy_marker source.
        ingest_geojson(seeded_db, "kansai", "lines",
                       str(tmp_path / "kansai_lines.geojson"))
        twice = _lines(seeded_db)
        names_once = sorted(f["properties"].get("name", "") for f in once)
        names_twice = sorted(f["properties"].get("name", "") for f in twice)
        assert names_once == names_twice
        assert all(n for n in names_twice)

    def test_already_named_line_is_skipped(self, seeded_db):
        # Manually name the AB line first; enricher must leave it alone.
        from src.db.geojson_sync import apply_enrichments, find_feature_keys
        # locate by the (now empty) name is impossible; use geometry key:
        from src.db.geojson_sync import iter_composed
        key = next(k for k, p, g in iter_composed(seeded_db, "kansai", "lines")
                   if g["coordinates"][0] == [135.90, 35.55])
        apply_enrichments(seeded_db, [{
            "layer": "lines", "region": "kansai", "feature_key": key,
            "field": "name", "value": "既存線", "source": "manual"}])
        stats = enrich_lines_endpoints(seeded_db, "kansai")
        assert stats["enriched"] == 1  # only the orphan, AB already named
        ab = [f for f in _lines(seeded_db)
              if f["geometry"]["coordinates"][0] == [135.90, 35.55]][0]
        assert ab["properties"]["name"] == "既存線"


# ======================================================================
# Audit Category-C tag-error fix (audit --fix -> DB)
# ======================================================================


class TestDbAuditFix:
    def test_category_c_tag_error_cleared_to_db(self, tmp_path, monkeypatch):
        import scripts.audit_substation_plant_overlap as audit
        monkeypatch.setattr(audit, "DATA_DIR", str(tmp_path))

        # A Category-C substation: the `substation` tag holds a facility
        # name instead of a valid type -> should be cleared to null.
        bad = {"type": "Feature",
               "properties": {"name": "諏訪町変電所",
                              "substation": "関西電力株式会社八鹿変電所"},
               "geometry": {"type": "Point", "coordinates": [135.5, 34.7]}}
        ok = {"type": "Feature",
              "properties": {"name": "正常変電所", "substation": "transmission"},
              "geometry": {"type": "Point", "coordinates": [135.6, 34.8]}}
        fc = lambda fe: json.dumps({"type": "FeatureCollection", "features": fe})
        (tmp_path / "kansai_substations.geojson").write_text(fc([bad, ok]), encoding="utf-8")
        (tmp_path / "kansai_plants.geojson").write_text(fc([]), encoding="utf-8")
        (tmp_path / "kansai_lines.geojson").write_text(fc([]), encoding="utf-8")

        db = GridDatabase(":memory:")
        ingest_geojson(db, "kansai", "substations",
                       str(tmp_path / "kansai_substations.geojson"))

        stats = apply_audit_fixes(db, ["kansai"])
        assert stats["fixed"] == 1

        subs = export_geojson(db, "kansai", "substations")["features"]
        bad_after = [f for f in subs if f["properties"]["name"] == "諏訪町変電所"][0]
        ok_after = [f for f in subs if f["properties"]["name"] == "正常変電所"][0]
        assert bad_after["properties"]["substation"] is None  # cleared
        assert ok_after["properties"]["substation"] == "transmission"  # untouched

    def test_no_false_positives_on_clean_data(self, tmp_path, monkeypatch):
        import scripts.audit_substation_plant_overlap as audit
        monkeypatch.setattr(audit, "DATA_DIR", str(tmp_path))
        ok = {"type": "Feature",
              "properties": {"name": "正常", "substation": "transmission"},
              "geometry": {"type": "Point", "coordinates": [135.6, 34.8]}}
        fc = lambda fe: json.dumps({"type": "FeatureCollection", "features": fe})
        for layer in ("substations", "plants", "lines"):
            (tmp_path / f"kansai_{layer}.geojson").write_text(
                fc([ok] if layer == "substations" else []), encoding="utf-8")
        db = GridDatabase(":memory:")
        ingest_geojson(db, "kansai", "substations",
                       str(tmp_path / "kansai_substations.geojson"))
        assert apply_audit_fixes(db, ["kansai"])["fixed"] == 0
