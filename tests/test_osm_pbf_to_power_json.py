"""scripts/osm_pbf_to_power_json.py: osmium の OPL のタグの読み方(2026-11-07)。"""
from scripts.osm_pbf_to_power_json import parse_tags, unesc


def test_opl_escapes_are_decoded():
    assert unesc("No.%20%55") == "No. 55"
    assert parse_tags("power=tower,ref=No.%20%71,name=北多摩線%20%No.%20%71") == {
        "power": "tower", "ref": "No. 71", "name": "北多摩線 No. 71"}
    assert parse_tags("name=A%2c%B,voltage=154000%3b%66000") == {"name": "A,B", "voltage": "154000;66000"}
    assert parse_tags("") == {}
