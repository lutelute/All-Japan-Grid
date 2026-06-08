"""Golden tests for the canonical region registry (Phase C constant unification).

Pins the values every module previously hard-coded, so migrating those
copies to import from :mod:`src.regions` is provably behaviour-preserving.
"""

from src import regions

EXPECTED_ORDER = [
    "hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
    "kansai", "chugoku", "shikoku", "kyushu", "okinawa",
]
EXPECTED_JA = {
    "hokkaido": "北海道", "tohoku": "東北", "tokyo": "東京",
    "chubu": "中部", "hokuriku": "北陸", "kansai": "関西",
    "chugoku": "中国", "shikoku": "四国", "kyushu": "九州",
    "okinawa": "沖縄",
}
EXPECTED_EN = {
    "hokkaido": "Hokkaido", "tohoku": "Tohoku", "tokyo": "Tokyo",
    "chubu": "Chubu", "hokuriku": "Hokuriku", "kansai": "Kansai",
    "chugoku": "Chugoku", "shikoku": "Shikoku", "kyushu": "Kyushu",
    "okinawa": "Okinawa",
}
EXPECTED_FREQ = {
    "hokkaido": 50, "tohoku": 50, "tokyo": 50,
    "chubu": 60, "hokuriku": 60, "kansai": 60,
    "chugoku": 60, "shikoku": 60, "kyushu": 60, "okinawa": 60,
}


def test_region_order():
    assert regions.REGIONS == EXPECTED_ORDER


def test_japanese_names():
    assert regions.REGION_JA == EXPECTED_JA


def test_english_names():
    assert regions.REGION_EN == EXPECTED_EN


def test_frequencies():
    assert regions.REGION_FREQUENCY_HZ == EXPECTED_FREQ


def test_accessors():
    assert regions.frequency_hz("tokyo") == 50
    assert regions.frequency_hz("kansai") == 60
    assert regions.name_ja("okinawa") == "沖縄"
    assert regions.region_config("tokyo")["utility"] == "東京電力"


def test_bbox_present_for_all():
    for r in EXPECTED_ORDER:
        bbox = regions.REGION_BBOX[r]
        assert {"lat_min", "lat_max", "lon_min", "lon_max"} <= set(bbox)


def test_geojson_loader_reexports_match():
    """geojson_loader must expose the same REGIONS / REGION_JA values."""
    from src.server import geojson_loader
    assert geojson_loader.REGIONS == regions.REGIONS
    assert geojson_loader.REGION_JA == regions.REGION_JA
