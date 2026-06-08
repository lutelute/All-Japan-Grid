"""Round-trip tests for the DB-unification GeoJSON sync (Steps 1-2).

Covers the three pillars of docs/DB_ARCHITECTURE.md:
- stable feature keys (osm id when present, geometry hash fallback),
- raw/curated decomposition driven by the legacy markers,
- golden round-trip: ingest -> export is semantically identical to the
  source file (verified on the real okinawa region).
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.db.geojson_sync import (
    LAYERS,
    apply_enrichments,
    compose_properties,
    decompose_properties,
    dump_enrichments_jsonl,
    export_geojson,
    feature_key_for,
    find_feature_keys,
    ingest_geojson,
    verify_roundtrip,
)
from src.db.grid_db import GridDatabase

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _feature(geometry=None, **props):
    return {
        "type": "Feature",
        "properties": props,
        "geometry": geometry
        or {"type": "Point", "coordinates": [127.0, 26.0]},
    }


# ======================================================================
# feature_key_for
# ======================================================================


class TestFeatureKey:
    def test_osm_id_makes_permanent_key(self):
        key, osm_type, osm_id = feature_key_for(
            _feature(osm_id=123456, osm_type="way")
        )
        assert key == "w123456"
        assert osm_type == "way"
        assert osm_id == 123456

    def test_node_prefix(self):
        key, _, _ = feature_key_for(_feature(osm_id=7, osm_type="node"))
        assert key == "n7"

    def test_geometry_hash_fallback_is_deterministic(self):
        f = _feature(name="A")
        key1, osm_type, osm_id = feature_key_for(f)
        key2, _, _ = feature_key_for(_feature(name="totally different"))
        assert key1.startswith("g:")
        assert key1 == key2  # same geometry -> same key, props irrelevant
        assert osm_type is None and osm_id is None

    def test_different_geometry_different_key(self):
        k1, _, _ = feature_key_for(
            _feature(geometry={"type": "Point", "coordinates": [130.0, 33.0]})
        )
        k2, _, _ = feature_key_for(
            _feature(geometry={"type": "Point", "coordinates": [130.0, 33.1]})
        )
        assert k1 != k2

    def test_geometry_hash_ignores_key_order(self):
        g1 = {"type": "Point", "coordinates": [127.0, 26.0]}
        g2 = {"coordinates": [127.0, 26.0], "type": "Point"}
        assert (
            feature_key_for(_feature(geometry=g1))[0]
            == feature_key_for(_feature(geometry=g2))[0]
        )


# ======================================================================
# decompose / compose
# ======================================================================


class TestDecomposeCompose:
    def test_underscore_fields_extracted_as_legacy_marker(self):
        raw, curated = decompose_properties(
            {"voltage": "66000", "_display_name": "X変電所", "_region": "okinawa"}
        )
        assert raw == {"voltage": "66000"}
        assert ("_display_name", "X変電所", "legacy_marker") in curated
        assert ("_region", "okinawa", "legacy_marker") in curated

    def test_enriched_name_extracted_with_verbatim_source(self):
        raw, curated = decompose_properties(
            {
                "name": "那覇変電所",
                "_name_source": "geocoded",
                "_enriched_by": "nominatim",
                "voltage": "132000",
            }
        )
        assert "name" not in raw
        assert ("name", "那覇変電所", "nominatim") in curated

    def test_raw_name_stays_raw_without_marker(self):
        raw, curated = decompose_properties({"name": "既存名", "power": "line"})
        assert raw == {"name": "既存名", "power": "line"}
        assert curated == []

    def test_compose_applies_source_priority(self):
        rows = [
            SimpleNamespace(
                field="name", source="nominatim", value=json.dumps("低優先")
            ),
            SimpleNamespace(
                field="name", source="manual", value=json.dumps("手動修正")
            ),
        ]
        props = compose_properties({"power": "plant"}, rows)
        assert props["name"] == "手動修正"
        assert props["power"] == "plant"

    def test_compose_inverts_decompose(self):
        original = {
            "name": "宮古発電所",
            "_name_source": "geocoded",
            "_enriched_by": "nominatim",
            "fuel_type": "oil",
            "osm_id": 99,
        }
        raw, curated = decompose_properties(original)
        rows = [
            SimpleNamespace(field=f, source=s, value=json.dumps(v, ensure_ascii=False))
            for f, v, s in curated
        ]
        assert compose_properties(raw, rows) == original


# ======================================================================
# Round-trip on real data (okinawa: 59 / 117 / 32 features)
# ======================================================================


@pytest.fixture()
def memory_db():
    return GridDatabase(":memory:")


class TestRoundTrip:
    def test_okinawa_all_layers_roundtrip(self, memory_db):
        for layer in LAYERS:
            path = DATA_DIR / f"okinawa_{layer}.geojson"
            stats = ingest_geojson(memory_db, "okinawa", layer, str(path))
            assert stats["features"] > 0
            problems = verify_roundtrip(
                memory_db, "okinawa", layer, str(path)
            )
            assert problems == [], f"{layer}: {problems[:3]}"

    def test_reingest_is_idempotent(self, memory_db):
        path = DATA_DIR / "okinawa_plants.geojson"
        first = ingest_geojson(memory_db, "okinawa", "plants", str(path))
        second = ingest_geojson(memory_db, "okinawa", "plants", str(path))
        assert first["features"] == second["features"]
        assert first["curated_rows"] == second["curated_rows"]
        assert (
            verify_roundtrip(memory_db, "okinawa", "plants", str(path)) == []
        )

    def test_dump_enrichments_is_stable_and_timestamp_free(
        self, memory_db, tmp_path
    ):
        path = DATA_DIR / "okinawa_plants.geojson"
        ingest_geojson(memory_db, "okinawa", "plants", str(path))
        out1 = tmp_path / "dump1.jsonl"
        out2 = tmp_path / "dump2.jsonl"
        n1 = dump_enrichments_jsonl(memory_db, str(out1))
        ingest_geojson(memory_db, "okinawa", "plants", str(path))
        n2 = dump_enrichments_jsonl(memory_db, str(out2))
        assert n1 == n2 > 0
        assert out1.read_text() == out2.read_text()  # no timestamp churn
        record = json.loads(out1.read_text().splitlines()[0])
        assert {"layer", "region", "feature_key", "field", "source"} <= set(
            record
        )
        assert "updated_at" not in record


# ======================================================================
# Curation write path (Step 3) — the mechanical-update loop
# ======================================================================


class TestCuration:
    # hokuriku plants carry 100% OSM ids (Overpass-sourced); okinawa
    # plants carry none (JRP-lite restore) — exercise both key regimes.
    OSM_REGION = "hokuriku"

    def _osm_id_feature(self, db):
        """Ingest hokuriku plants and return a present, unique osm_id."""
        path = DATA_DIR / f"{self.OSM_REGION}_plants.geojson"
        ingest_geojson(db, self.OSM_REGION, "plants", str(path))
        coll = export_geojson(db, self.OSM_REGION, "plants")
        from collections import Counter
        counts = Counter(f["properties"].get("osm_id")
                         for f in coll["features"])
        for f in coll["features"]:
            oid = f["properties"].get("osm_id")
            if oid not in (None, "") and counts[oid] == 1:
                return int(oid)
        pytest.skip("no unique osm_id-bearing plant in fixture")

    def test_find_requires_a_selector(self, memory_db):
        ingest_geojson(memory_db, "okinawa", "plants",
                       str(DATA_DIR / "okinawa_plants.geojson"))
        assert find_feature_keys(memory_db, "plants", "okinawa") == []

    def test_manual_edit_appears_in_export(self, memory_db):
        osm_id = self._osm_id_feature(memory_db)
        keys = find_feature_keys(
            memory_db, "plants", self.OSM_REGION, osm_id=osm_id)
        assert len(keys) == 1
        apply_enrichments(memory_db, [{
            "layer": "plants", "region": self.OSM_REGION,
            "feature_key": keys[0], "field": "operator",
            "value": "北陸電力(キュレーション)", "source": "manual",
        }])
        coll = export_geojson(memory_db, self.OSM_REGION, "plants")
        edited = [f for f in coll["features"]
                  if f["properties"].get("osm_id") == osm_id][0]
        assert edited["properties"]["operator"] == "北陸電力(キュレーション)"

    def test_manual_overrides_legacy_by_priority(self, memory_db):
        """A manual name must win over the legacy nominatim/marker name."""
        osm_id = self._osm_id_feature(memory_db)
        key = find_feature_keys(
            memory_db, "plants", self.OSM_REGION, osm_id=osm_id)[0]
        apply_enrichments(memory_db, [{
            "layer": "plants", "region": self.OSM_REGION,
            "feature_key": key, "field": "name",
            "value": "手動命名", "source": "manual",
        }])
        coll2 = export_geojson(memory_db, self.OSM_REGION, "plants")
        edited = [f for f in coll2["features"]
                  if f["properties"].get("osm_id") == osm_id][0]
        assert edited["properties"]["name"] == "手動命名"

    def test_locate_by_name_on_geometry_keyed_region(self, memory_db):
        """okinawa plants have no osm_id — curation must still work via name."""
        ingest_geojson(memory_db, "okinawa", "plants",
                       str(DATA_DIR / "okinawa_plants.geojson"))
        coll = export_geojson(memory_db, "okinawa", "plants")
        target = coll["features"][0]["properties"]["name"]
        keys = find_feature_keys(memory_db, "plants", "okinawa", name=target)
        assert keys  # geometry-keyed, located purely by effective name
        apply_enrichments(memory_db, [{
            "layer": "plants", "region": "okinawa", "feature_key": keys[0],
            "field": "fuel_type", "value": "biomass", "source": "manual",
        }])
        coll2 = export_geojson(memory_db, "okinawa", "plants")
        hit = [f for f in coll2["features"]
               if f["properties"].get("name") == target][0]
        assert hit["properties"]["fuel_type"] == "biomass"

    def test_curation_survives_reingest(self, memory_db):
        """A manual curation persists across a full legacy re-ingest.

        Mechanical-update guarantee: the edit lives in the C layer keyed
        by feature identity under a non-legacy source, so ingest (which
        only refreshes LEGACY_SOURCES) leaves it untouched and the export
        still reflects it.
        """
        osm_id = self._osm_id_feature(memory_db)
        key = find_feature_keys(
            memory_db, "plants", self.OSM_REGION, osm_id=osm_id)[0]
        apply_enrichments(memory_db, [{
            "layer": "plants", "region": self.OSM_REGION,
            "feature_key": key, "field": "operator",
            "value": "保持テスト", "source": "manual",
        }])
        # Re-ingest the same source file (stand-in for an OSM re-fetch).
        ingest_geojson(memory_db, self.OSM_REGION, "plants",
                       str(DATA_DIR / f"{self.OSM_REGION}_plants.geojson"))
        coll = export_geojson(memory_db, self.OSM_REGION, "plants")
        hit = [f for f in coll["features"]
               if f["properties"].get("osm_id") == osm_id][0]
        assert hit["properties"]["operator"] == "保持テスト"
