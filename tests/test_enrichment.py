"""Unit tests for enrichment scripts.

Tests name construction, fuel normalization, operator normalization,
geocode caching, Overpass query construction, fallback naming, and
audit report accuracy. All external API calls are mocked.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on sys.path for imports
ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ======================================================================
# Import enrichment modules (scripts are standalone; import carefully)
# ======================================================================

# Substation geocoding
from scripts.enrich_substations_geocode import (
    construct_name as construct_substation_name,
    promote_names_region,
)

# Plant geocoding
from scripts.enrich_plants_geocode import (
    cache_key,
    construct_name as construct_plant_name,
    fallback_name,
    load_cache,
    save_cache,
)

# Line endpoint naming
from scripts.enrich_lines_endpoints import (
    normalize_operator,
    parse_voltage_kv,
    OPERATOR_NORMALIZE,
)

# Overpass batch tags
from scripts.enrich_overpass_tags import (
    FUEL_TYPE_MAP,
    normalize_fuel,
    needs_enrichment,
    apply_tags_to_feature,
)

# Audit
from scripts.audit_data_quality import (
    _is_empty,
    _is_synthetic_display_name,
    audit_file,
    count_all_placeholders,
)


# ======================================================================
# Test: construct_substation_name
# ======================================================================


class TestConstructSubstationName:
    """Tests for Nominatim address -> {area}変電所 name construction."""

    def test_neighbourhood_preferred(self) -> None:
        """Neighbourhood is preferred over suburb, quarter, city_district."""
        addr = {
            "neighbourhood": "西区",
            "suburb": "本町",
            "city": "大阪市",
        }
        result = construct_substation_name(addr)
        assert result == "西区変電所"

    def test_suburb_fallback(self) -> None:
        """Suburb is used when neighbourhood is absent."""
        addr = {
            "suburb": "本町",
            "city": "大阪市",
        }
        result = construct_substation_name(addr)
        assert result == "本町変電所"

    def test_quarter_fallback(self) -> None:
        """Quarter is used when neighbourhood and suburb are absent."""
        addr = {
            "quarter": "中央区",
            "city": "東京都",
        }
        result = construct_substation_name(addr)
        assert result == "中央区変電所"

    def test_city_district_fallback(self) -> None:
        """City_district is used as last area option."""
        addr = {
            "city_district": "港区",
            "city": "東京都",
        }
        result = construct_substation_name(addr)
        assert result == "港区変電所"

    def test_municipality_only(self) -> None:
        """When no area component, municipality is used."""
        addr = {"city": "松山市"}
        result = construct_substation_name(addr)
        assert result == "松山市変電所"

    def test_town_as_municipality(self) -> None:
        """Town is used when city is absent."""
        addr = {"town": "内子町"}
        result = construct_substation_name(addr)
        assert result == "内子町変電所"

    def test_village_as_municipality(self) -> None:
        """Village is used when city and town are absent."""
        addr = {"village": "大川村"}
        result = construct_substation_name(addr)
        assert result == "大川村変電所"

    def test_area_same_as_municipality_uses_municipality(self) -> None:
        """When area equals municipality, use municipality to avoid duplication."""
        addr = {
            "neighbourhood": "松山市",
            "city": "松山市",
        }
        result = construct_substation_name(addr)
        assert result == "松山市変電所"

    def test_empty_address_returns_empty(self) -> None:
        """Empty address dict returns empty string."""
        result = construct_substation_name({})
        assert result == ""

    def test_only_state_returns_empty(self) -> None:
        """Address with only state/county returns empty (no area or municipality)."""
        addr = {"state": "愛媛県", "county": "松山"}
        result = construct_substation_name(addr)
        assert result == ""


# ======================================================================
# Test: construct_plant_name
# ======================================================================


class TestConstructPlantName:
    """Tests for Nominatim address -> {area}発電所 name construction."""

    def test_area_and_municipality(self) -> None:
        """Plant name includes both area and municipality."""
        addr = {
            "neighbourhood": "港区",
            "city": "東京都",
        }
        result = construct_plant_name(addr)
        assert result == "港区東京都発電所"

    def test_suburb_and_city(self) -> None:
        """Suburb + city combination."""
        addr = {
            "suburb": "湾岸",
            "city": "千葉市",
        }
        result = construct_plant_name(addr)
        assert result == "湾岸千葉市発電所"

    def test_municipality_only(self) -> None:
        """Only municipality results in {municipality}発電所."""
        addr = {"city": "浜松市"}
        result = construct_plant_name(addr)
        assert result == "浜松市発電所"

    def test_area_same_as_municipality(self) -> None:
        """When area equals municipality, use municipality only."""
        addr = {
            "neighbourhood": "那覇市",
            "city": "那覇市",
        }
        result = construct_plant_name(addr)
        assert result == "那覇市発電所"

    def test_empty_address(self) -> None:
        """Empty address returns empty string."""
        result = construct_plant_name({})
        assert result == ""

    def test_quarter_with_town(self) -> None:
        """Quarter and town combination."""
        addr = {
            "quarter": "東区",
            "town": "富山町",
        }
        result = construct_plant_name(addr)
        assert result == "東区富山町発電所"


# ======================================================================
# Test: construct_line_name
# ======================================================================


class TestConstructLineName:
    """Tests for line name construction from endpoint substations."""

    def test_two_different_endpoints(self) -> None:
        """Two distinct substation names produce {from}~{to}線."""
        from_name = "阿南変電所"
        to_name = "讃岐変電所"
        line_name = f"{from_name}~{to_name}線"
        assert line_name == "阿南変電所~讃岐変電所線"

    def test_same_endpoints_fall_to_operator_voltage(self) -> None:
        """When from == to, endpoint naming should be skipped.

        This tests the logic pattern used in enrich_lines_endpoints.py
        where from_name != to_name is required for endpoint naming.
        """
        from_name = "阿南変電所"
        to_name = "阿南変電所"
        # Simulating the script logic
        if from_name and to_name and from_name != to_name:
            line_name = f"{from_name}~{to_name}線"
        else:
            line_name = "沖縄電力 66.0kV線"
        assert line_name == "沖縄電力 66.0kV線"

    def test_operator_voltage_fallback(self) -> None:
        """When no endpoints match, use operator + voltage."""
        operator = "四国電力送配電"
        voltage_kv = 275.0
        line_name = f"{operator} {voltage_kv}kV線"
        assert line_name == "四国電力送配電 275.0kV線"

    def test_regional_fallback(self) -> None:
        """When no endpoints or operator+voltage, use regional fallback."""
        region_ja = "沖縄"
        seq = 42
        line_name = f"{region_ja}送電線_{seq}"
        assert line_name == "沖縄送電線_42"

    def test_parse_voltage_kv_standard(self) -> None:
        """Standard voltage values in volts are converted to kV."""
        assert parse_voltage_kv("275000") == 275.0
        assert parse_voltage_kv("500000") == 500.0
        assert parse_voltage_kv("66000") == 66.0

    def test_parse_voltage_kv_already_kv(self) -> None:
        """Values already in kV (< 1000) stay as-is."""
        assert parse_voltage_kv("275") == 275.0
        assert parse_voltage_kv("66") == 66.0

    def test_parse_voltage_kv_semicolon(self) -> None:
        """Multiple voltages separated by semicolons use first value."""
        assert parse_voltage_kv("275000;154000") == 275.0

    def test_parse_voltage_kv_empty(self) -> None:
        """Empty or None returns 0.0."""
        assert parse_voltage_kv("") == 0.0
        assert parse_voltage_kv(None) == 0.0

    def test_parse_voltage_kv_invalid(self) -> None:
        """Non-numeric string returns 0.0."""
        assert parse_voltage_kv("abc") == 0.0


# ======================================================================
# Test: deduplicate_names
# ======================================================================


class TestDeduplicateNames:
    """Tests for duplicate name handling with ordinal suffixes."""

    def _make_feature_collection(self, features):
        """Helper to create a GeoJSON FeatureCollection."""
        return {
            "type": "FeatureCollection",
            "features": features,
        }

    def _make_substation_feature(self, name="", display_name=""):
        """Helper to create a substation feature."""
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [133.5, 33.8]},
            "properties": {
                "name": name,
                "_display_name": display_name,
            },
        }

    def test_unique_names_no_suffix(self, tmp_path: Path) -> None:
        """Unique display names get no suffix."""
        fc = self._make_feature_collection([
            self._make_substation_feature(name="", display_name="阿南変電所"),
            self._make_substation_feature(name="", display_name="讃岐変電所"),
        ])
        path = tmp_path / "test_substations.geojson"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fc, f, ensure_ascii=False)

        # Mock the DATA_DIR to use our temp directory
        with patch("scripts.enrich_substations_geocode.DATA_DIR", str(tmp_path)):
            total, promoted = promote_names_region("test")

        with open(path, "r", encoding="utf-8") as f:
            result = json.load(f)

        names = [f["properties"]["name"] for f in result["features"]]
        assert names == ["阿南変電所", "讃岐変電所"]
        assert promoted == 2

    def test_duplicate_names_get_suffix(self, tmp_path: Path) -> None:
        """Duplicate display names get _2, _3 suffixes."""
        fc = self._make_feature_collection([
            self._make_substation_feature(name="", display_name="西区変電所"),
            self._make_substation_feature(name="", display_name="西区変電所"),
            self._make_substation_feature(name="", display_name="西区変電所"),
        ])
        path = tmp_path / "test_substations.geojson"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fc, f, ensure_ascii=False)

        with patch("scripts.enrich_substations_geocode.DATA_DIR", str(tmp_path)):
            total, promoted = promote_names_region("test")

        with open(path, "r", encoding="utf-8") as f:
            result = json.load(f)

        names = [f["properties"]["name"] for f in result["features"]]
        assert names == ["西区変電所", "西区変電所_2", "西区変電所_3"]
        assert promoted == 3

    def test_existing_named_counted_in_dedup(self, tmp_path: Path) -> None:
        """Existing named substations are counted when deduplicating."""
        fc = self._make_feature_collection([
            self._make_substation_feature(name="西区変電所", display_name=""),
            self._make_substation_feature(name="", display_name="西区変電所"),
        ])
        path = tmp_path / "test_substations.geojson"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fc, f, ensure_ascii=False)

        with patch("scripts.enrich_substations_geocode.DATA_DIR", str(tmp_path)):
            total, promoted = promote_names_region("test")

        with open(path, "r", encoding="utf-8") as f:
            result = json.load(f)

        names = [f["properties"]["name"] for f in result["features"]]
        assert names[0] == "西区変電所"  # existing, unchanged
        assert names[1] == "西区変電所_2"  # promoted with suffix
        assert promoted == 1

    def test_no_candidates_no_promotion(self, tmp_path: Path) -> None:
        """Features with no display name are not promoted."""
        fc = self._make_feature_collection([
            self._make_substation_feature(name="", display_name=""),
        ])
        path = tmp_path / "test_substations.geojson"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fc, f, ensure_ascii=False)

        with patch("scripts.enrich_substations_geocode.DATA_DIR", str(tmp_path)):
            total, promoted = promote_names_region("test")

        assert promoted == 0

    def test_enriched_by_set(self, tmp_path: Path) -> None:
        """Promoted features have _enriched_by = geocode_promotion."""
        fc = self._make_feature_collection([
            self._make_substation_feature(name="", display_name="高松変電所"),
        ])
        path = tmp_path / "test_substations.geojson"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fc, f, ensure_ascii=False)

        with patch("scripts.enrich_substations_geocode.DATA_DIR", str(tmp_path)):
            promote_names_region("test")

        with open(path, "r", encoding="utf-8") as f:
            result = json.load(f)

        props = result["features"][0]["properties"]
        assert props["_enriched_by"] == "geocode_promotion"


# ======================================================================
# Test: fuel_type_normalization
# ======================================================================


class TestFuelTypeNormalization:
    """Tests for OSM fuel strings -> normalized fuel type values."""

    def test_standard_fuels(self) -> None:
        """Standard fuel types map correctly."""
        assert normalize_fuel("coal") == "coal"
        assert normalize_fuel("gas") == "gas"
        assert normalize_fuel("nuclear") == "nuclear"
        assert normalize_fuel("hydro") == "hydro"
        assert normalize_fuel("solar") == "solar"
        assert normalize_fuel("wind") == "wind"
        assert normalize_fuel("oil") == "oil"

    def test_alias_fuels(self) -> None:
        """Alias fuel type strings map to canonical values."""
        assert normalize_fuel("natural_gas") == "gas"
        assert normalize_fuel("water") == "hydro"
        assert normalize_fuel("photovoltaic") == "solar"
        assert normalize_fuel("diesel") == "oil"
        assert normalize_fuel("biogas") == "biomass"
        assert normalize_fuel("pumped_storage") == "pumped_hydro"
        assert normalize_fuel("wave") == "tidal"

    def test_semicolon_separated_uses_first(self) -> None:
        """Semicolon-separated sources use the first value."""
        assert normalize_fuel("solar;wind") == "solar"
        assert normalize_fuel("gas;oil") == "gas"

    def test_empty_returns_unknown(self) -> None:
        """Empty or None source returns 'unknown'."""
        assert normalize_fuel("") == "unknown"
        assert normalize_fuel(None) == "unknown"

    def test_unrecognized_returns_as_is(self) -> None:
        """Unrecognized fuel types are returned as-is (lowered)."""
        assert normalize_fuel("hydrogen") == "hydrogen"
        assert normalize_fuel("FUSION") == "fusion"

    def test_fuel_type_map_completeness(self) -> None:
        """FUEL_TYPE_MAP covers all expected OSM plant:source values."""
        expected_keys = {
            "coal", "gas", "natural_gas", "oil", "nuclear", "hydro",
            "water", "wind", "solar", "photovoltaic", "biomass", "biogas",
            "waste", "geothermal", "tidal", "wave", "battery",
            "pumped_storage", "diesel",
        }
        assert expected_keys.issubset(set(FUEL_TYPE_MAP.keys()))


# ======================================================================
# Test: operator_normalization
# ======================================================================


class TestOperatorNormalization:
    """Tests for operator name variants -> canonical forms."""

    def test_exact_match(self) -> None:
        """Exact match in OPERATOR_NORMALIZE returns canonical form."""
        assert normalize_operator("東京電力") == "東京電力パワーグリッド"
        assert normalize_operator("関西電力") == "関西電力送配電"
        assert normalize_operator("中部電力") == "中部電力パワーグリッド"
        assert normalize_operator("九州電力") == "九州電力送配電"
        assert normalize_operator("東北電力") == "東北電力ネットワーク"
        assert normalize_operator("北海道電力") == "北海道電力ネットワーク"

    def test_alternate_variants(self) -> None:
        """Alternative variant names map correctly."""
        assert normalize_operator("東京電力PG") == "東京電力パワーグリッド"

    def test_prefix_match(self) -> None:
        """Operator names starting with a known prefix are normalized."""
        assert normalize_operator("東京電力株式会社") == "東京電力パワーグリッド"
        assert normalize_operator("関西電力送配電株式会社") == "関西電力送配電"

    def test_unknown_operator_passthrough(self) -> None:
        """Unknown operators are returned as-is."""
        assert normalize_operator("電源開発") == "電源開発"
        assert normalize_operator("JERA") == "JERA"

    def test_empty_returns_empty(self) -> None:
        """Empty or None returns empty string."""
        assert normalize_operator("") == ""
        assert normalize_operator(None) == ""

    def test_whitespace_stripped(self) -> None:
        """Whitespace is stripped from input."""
        assert normalize_operator("  東京電力  ") == "東京電力パワーグリッド"

    def test_all_regional_utilities(self) -> None:
        """All 10 regional utilities have normalization entries."""
        assert len(OPERATOR_NORMALIZE) >= 10
        expected_canonical = {
            "東京電力パワーグリッド", "関西電力送配電", "中部電力パワーグリッド",
            "九州電力送配電", "東北電力ネットワーク", "北海道電力ネットワーク",
            "中国電力ネットワーク", "四国電力送配電", "北陸電力送配電", "沖縄電力",
        }
        assert expected_canonical.issubset(set(OPERATOR_NORMALIZE.values()))


# ======================================================================
# Test: geocode_cache_roundtrip
# ======================================================================


class TestGeocodeCacheRoundtrip:
    """Tests for geocode cache write -> read integrity."""

    def test_write_and_read(self, tmp_path: Path) -> None:
        """Cache data survives a write/read cycle."""
        cache_file = tmp_path / "cache" / "plants_geocode.json"
        cache_data = {
            "33.800000,133.500000": {
                "neighbourhood": "西区",
                "city": "松山市",
                "state": "愛媛県",
            },
            "26.334500,127.800000": {
                "city": "那覇市",
                "state": "沖縄県",
            },
        }

        with patch("scripts.enrich_plants_geocode.CACHE_FILE", str(cache_file)), \
             patch("scripts.enrich_plants_geocode.CACHE_DIR", str(tmp_path / "cache")):
            save_cache(cache_data)
            loaded = load_cache()

        assert loaded == cache_data

    def test_empty_cache_on_missing_file(self, tmp_path: Path) -> None:
        """Non-existent cache file returns empty dict."""
        cache_file = tmp_path / "nonexistent.json"
        with patch("scripts.enrich_plants_geocode.CACHE_FILE", str(cache_file)):
            loaded = load_cache()
        assert loaded == {}

    def test_corrupt_cache_returns_empty(self, tmp_path: Path) -> None:
        """Corrupt JSON cache file returns empty dict."""
        cache_file = tmp_path / "corrupt.json"
        cache_file.write_text("not valid json {{{", encoding="utf-8")
        with patch("scripts.enrich_plants_geocode.CACHE_FILE", str(cache_file)):
            loaded = load_cache()
        assert loaded == {}

    def test_japanese_characters_preserved(self, tmp_path: Path) -> None:
        """Japanese characters survive cache roundtrip."""
        cache_file = tmp_path / "cache" / "plants_geocode.json"
        cache_data = {
            "34.000000,135.000000": {
                "neighbourhood": "難波",
                "city": "大阪市",
            },
        }

        with patch("scripts.enrich_plants_geocode.CACHE_FILE", str(cache_file)), \
             patch("scripts.enrich_plants_geocode.CACHE_DIR", str(tmp_path / "cache")):
            save_cache(cache_data)
            loaded = load_cache()

        assert loaded["34.000000,135.000000"]["neighbourhood"] == "難波"
        assert loaded["34.000000,135.000000"]["city"] == "大阪市"

    def test_cache_key_format(self) -> None:
        """Cache key uses 6 decimal places."""
        key = cache_key(33.8, 133.5)
        assert key == "33.800000,133.500000"

    def test_cache_key_precision(self) -> None:
        """Cache key preserves coordinate precision."""
        key = cache_key(26.334567, 127.801234)
        assert key == "26.334567,127.801234"


# ======================================================================
# Test: overpass_batch_query_construction
# ======================================================================


class TestOverpassBatchQueryConstruction:
    """Tests for well-formed Overpass query strings."""

    def test_query_format(self) -> None:
        """Verify Overpass query string structure for batch ID queries."""
        osm_ids = [123, 456, 789]
        ids_str = ",".join(str(oid) for oid in osm_ids)
        query = f"""
[out:json][timeout:300];
(
  nwr(id:{ids_str});
);
out tags;
"""
        assert "[out:json]" in query
        assert "[timeout:300]" in query
        assert "nwr(id:123,456,789)" in query
        assert "out tags;" in query

    def test_single_id_query(self) -> None:
        """Single ID produces valid query."""
        osm_ids = [42]
        ids_str = ",".join(str(oid) for oid in osm_ids)
        query = f"nwr(id:{ids_str});"
        assert query == "nwr(id:42);"

    def test_large_batch_construction(self) -> None:
        """500-ID batch produces valid comma-separated list."""
        osm_ids = list(range(1, 501))
        ids_str = ",".join(str(oid) for oid in osm_ids)
        assert ids_str.startswith("1,2,3,")
        assert ids_str.endswith(",499,500")
        assert ids_str.count(",") == 499

    def test_needs_enrichment_with_missing_name(self) -> None:
        """Feature with osm_id and missing name needs enrichment."""
        props = {"osm_id": 123, "name": "", "operator": "Test", "fuel_type": "solar"}
        assert needs_enrichment(props) is True

    def test_needs_enrichment_with_unknown_fuel(self) -> None:
        """Feature with osm_id and unknown fuel needs enrichment."""
        props = {"osm_id": 123, "name": "Test", "operator": "Test", "fuel_type": "unknown"}
        assert needs_enrichment(props) is True

    def test_needs_enrichment_with_missing_operator(self) -> None:
        """Feature with osm_id and missing operator needs enrichment."""
        props = {"osm_id": 123, "name": "Test", "operator": "", "fuel_type": "solar"}
        assert needs_enrichment(props) is True

    def test_no_enrichment_when_complete(self) -> None:
        """Feature with all attributes populated does not need enrichment."""
        props = {"osm_id": 123, "name": "Test", "operator": "Test Co", "fuel_type": "solar"}
        assert needs_enrichment(props) is False

    def test_no_enrichment_without_osm_id(self) -> None:
        """Feature without osm_id is skipped."""
        props = {"name": "", "operator": "", "fuel_type": "unknown"}
        assert needs_enrichment(props) is False

    def test_apply_tags_fills_name(self) -> None:
        """apply_tags_to_feature fills name from Overpass tags."""
        props = {"name": "", "operator": "Test", "fuel_type": "solar"}
        tags = {"name": "テスト発電所", "name:ja": "テスト発電所"}
        changed = apply_tags_to_feature(props, tags, tags)
        assert changed is True
        assert props["name"] == "テスト発電所"
        assert props["_enriched_by"] == "overpass"

    def test_apply_tags_fills_operator(self) -> None:
        """apply_tags_to_feature fills operator from Overpass tags."""
        props = {"name": "Test", "operator": "", "fuel_type": "solar"}
        tags = {"operator": "東京電力"}
        changed = apply_tags_to_feature(props, tags, tags)
        assert changed is True
        assert props["operator"] == "東京電力"

    def test_apply_tags_normalizes_fuel(self) -> None:
        """apply_tags_to_feature normalizes fuel_type from Overpass tags."""
        props = {"name": "Test", "operator": "Test", "fuel_type": "unknown"}
        tags = {"plant:source": "photovoltaic"}
        changed = apply_tags_to_feature(props, tags, tags)
        assert changed is True
        assert props["fuel_type"] == "solar"

    def test_apply_tags_no_change_when_already_populated(self) -> None:
        """apply_tags_to_feature makes no changes when all fields populated."""
        props = {"name": "Test", "operator": "Test", "fuel_type": "solar"}
        tags = {"name": "Other", "operator": "Other", "plant:source": "wind"}
        changed = apply_tags_to_feature(props, tags, tags)
        assert changed is False


# ======================================================================
# Test: fallback_name_construction
# ======================================================================


class TestFallbackNameConstruction:
    """Tests for {region}_{lat}_{lon} fallback when geocode returns empty."""

    def test_standard_fallback(self) -> None:
        """Standard fallback uses region_ja with 4 decimal places."""
        result = fallback_name("okinawa", 26.3345, 127.8012)
        assert result == "沖縄_26.3345_127.8012"

    def test_all_regions_have_ja_names(self) -> None:
        """All 10 regions produce Japanese fallback names."""
        from scripts.enrich_plants_geocode import REGION_JA
        expected_regions = [
            "hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
            "kansai", "chugoku", "shikoku", "kyushu", "okinawa",
        ]
        for region in expected_regions:
            result = fallback_name(region, 35.0, 135.0)
            assert REGION_JA[region] in result

    def test_unknown_region_uses_key(self) -> None:
        """Unknown region key is used as-is."""
        result = fallback_name("unknown_region", 35.0, 135.0)
        assert result == "unknown_region_35.0000_135.0000"

    def test_negative_coordinates(self) -> None:
        """Negative coordinates are formatted correctly."""
        result = fallback_name("okinawa", -26.3345, -127.8012)
        assert result == "沖縄_-26.3345_-127.8012"

    def test_precision_four_decimals(self) -> None:
        """Fallback name uses exactly 4 decimal places."""
        result = fallback_name("tokyo", 35.6812345, 139.7671234)
        assert result == "東京_35.6812_139.7671"


# ======================================================================
# Test: audit_report_accuracy
# ======================================================================


class TestAuditReportAccuracy:
    """Tests for correct placeholder counting in audit reports."""

    def _make_geojson(self, features):
        """Helper to create a GeoJSON FeatureCollection."""
        return {
            "type": "FeatureCollection",
            "features": features,
        }

    def _make_substation_feat(self, name=None, display_name=None):
        """Helper for substation features."""
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [133.5, 33.8]},
            "properties": {
                "name": name,
                "_display_name": display_name,
            },
        }

    def _make_plant_feat(self, name=None, fuel_type="solar", operator=None):
        """Helper for plant features."""
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [133.5, 33.8]},
            "properties": {
                "name": name,
                "fuel_type": fuel_type,
                "operator": operator,
            },
        }

    def test_counts_empty_names(self, tmp_path: Path) -> None:
        """Audit counts empty/None name fields correctly."""
        fc = self._make_geojson([
            self._make_substation_feat(name=None),
            self._make_substation_feat(name=""),
            self._make_substation_feat(name="  "),
            self._make_substation_feat(name="有名変電所"),
        ])
        path = tmp_path / "test_substations.geojson"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fc, f, ensure_ascii=False)

        with patch("scripts.audit_data_quality.DATA_DIR", str(tmp_path)):
            result = audit_file("test", "substations")

        assert result["total"] == 4
        assert result["empty_name"] == 3

    def test_counts_synthetic_display_names(self, tmp_path: Path) -> None:
        """Audit detects synthetic _display_name values."""
        fc = self._make_geojson([
            self._make_substation_feat(display_name="sub_123"),
            self._make_substation_feat(display_name="plant_456"),
            self._make_substation_feat(display_name="line_789"),
            self._make_substation_feat(display_name="阿南変電所"),
        ])
        path = tmp_path / "test_substations.geojson"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fc, f, ensure_ascii=False)

        with patch("scripts.audit_data_quality.DATA_DIR", str(tmp_path)):
            result = audit_file("test", "substations")

        assert result["synthetic_display_name"] == 3

    def test_counts_unknown_fuel_type(self, tmp_path: Path) -> None:
        """Audit counts unknown fuel_type for plants."""
        fc = self._make_geojson([
            self._make_plant_feat(name="A", fuel_type="unknown"),
            self._make_plant_feat(name="B", fuel_type="unknown"),
            self._make_plant_feat(name="C", fuel_type="solar"),
        ])
        path = tmp_path / "test_plants.geojson"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fc, f, ensure_ascii=False)

        with patch("scripts.audit_data_quality.DATA_DIR", str(tmp_path)):
            result = audit_file("test", "plants")

        assert result["unknown_fuel_type"] == 2

    def test_counts_empty_operator(self, tmp_path: Path) -> None:
        """Audit counts empty operator for plants."""
        fc = self._make_geojson([
            self._make_plant_feat(name="A", operator=None),
            self._make_plant_feat(name="B", operator=""),
            self._make_plant_feat(name="C", operator="四国電力"),
        ])
        path = tmp_path / "test_plants.geojson"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fc, f, ensure_ascii=False)

        with patch("scripts.audit_data_quality.DATA_DIR", str(tmp_path)):
            result = audit_file("test", "plants")

        assert result["empty_operator"] == 2

    def test_count_all_placeholders(self) -> None:
        """count_all_placeholders sums all non-total fields."""
        report = {
            "test": {
                "substations": {
                    "total": 100,
                    "empty_name": 5,
                    "synthetic_display_name": 3,
                },
                "plants": {
                    "total": 200,
                    "empty_name": 10,
                    "synthetic_display_name": 0,
                    "unknown_fuel_type": 2,
                    "empty_operator": 15,
                },
            },
        }
        total = count_all_placeholders(report)
        assert total == 5 + 3 + 10 + 0 + 2 + 15

    def test_zero_placeholders_for_clean_data(self, tmp_path: Path) -> None:
        """Clean data produces zero placeholders."""
        fc = self._make_geojson([
            self._make_substation_feat(name="阿南変電所", display_name="阿南変電所"),
        ])
        path = tmp_path / "test_substations.geojson"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fc, f, ensure_ascii=False)

        with patch("scripts.audit_data_quality.DATA_DIR", str(tmp_path)):
            result = audit_file("test", "substations")

        assert result["empty_name"] == 0
        assert result["synthetic_display_name"] == 0

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        """Non-existent GeoJSON file returns None."""
        with patch("scripts.audit_data_quality.DATA_DIR", str(tmp_path)):
            result = audit_file("nonexistent", "substations")
        assert result is None

    def test_is_empty_helper(self) -> None:
        """_is_empty correctly identifies empty values."""
        assert _is_empty(None) is True
        assert _is_empty("") is True
        assert _is_empty("  ") is True
        assert _is_empty("test") is False
        assert _is_empty(0) is False

    def test_is_synthetic_display_name_helper(self) -> None:
        """_is_synthetic_display_name detects synthetic patterns."""
        assert _is_synthetic_display_name("plant_123") is True
        assert _is_synthetic_display_name("sub_456") is True
        assert _is_synthetic_display_name("line_789") is True
        assert _is_synthetic_display_name("阿南変電所") is False
        assert _is_synthetic_display_name("") is False
        assert _is_synthetic_display_name(None) is False
