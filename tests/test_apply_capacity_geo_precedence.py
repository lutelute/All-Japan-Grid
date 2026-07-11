"""名前照合×geoキー照合が同一featureで競合したときの優先規則の検証.

実事例(相浦): 同名2feature(廃止油火力跡 + P03遺物名のメガソーラー)に対し、
名前照合だけだと廃止0MWレコードがソーラー側にも塗られる。優先規則:
  - 名前レコードのplant_keyが座標を内包し当該featureを指す(±0.005°)+confidence同等以上
    → 名前レコード(公式出典の格を維持)
  - それ以外 → feature特定的に裁定済みのgeoレコード
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from apply_capacity_sources import main  # noqa: E402


def _feat(name, region, lon, lat):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"name": name, "_region": region, "capacity_mw": -1},
    }


def _rec(plant_key, name, value, conf="medium", stype="other"):
    return {
        "plant_key": plant_key, "name": name, "field": "capacity_mw",
        "value": value, "unit": "MW", "source_type": stype,
        "source_url": "https://example.com/x", "source_title": "t",
        "quote": f"Operating — {value} MW", "retrieved_at": "2026-07-11",
        "confidence": conf, "collected_by": "test", "note": "",
    }


def _run(tmp_path, feats, recs):
    d = {"type": "FeatureCollection", "features": feats}
    with open(tmp_path / "plants_all.geojson", "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    main(data_dir=str(tmp_path), records=recs)
    with open(tmp_path / "plants_all.geojson", encoding="utf-8") as f:
        return json.load(f)["features"]


def test_ainoura_case_geo_wins_when_legacy_coords_point_elsewhere(tmp_path):
    # 廃止油火力(33.196)とP03遺物名のソーラー(33.204) — 同名
    feats = [
        _feat("相浦火力発電所", "kyushu", 129.649, 33.196),
        _feat("相浦火力発電所", "kyushu", 129.6472, 33.2041),
    ]
    recs = [
        _rec("p03:相浦火力発電所:33.196,129.649", "相浦火力発電所", 0, conf="high",
             stype="wikipedia"),
        _rec("geo:kyushu:129.6472,33.2041", "相浦火力発電所", 10),
    ]
    out = _run(tmp_path, feats, recs)
    # 油火力側=名前レコード(0MW)・ソーラー側=geoレコード(10MW)
    assert out[0]["properties"]["capacity_mw_sourced"] == 0
    assert out[1]["properties"]["capacity_mw_sourced"] == 10


def test_official_name_record_wins_when_coords_confirm_feature(tmp_path):
    # 新小倉型: 名前レコード(official/high)の内包座標がこのfeatureを確証 → 公式が勝つ
    feats = [_feat("新小倉火力発電所", "kyushu", 130.8602, 33.9083)]
    recs = [
        _rec("osm:新小倉火力発電所:33.908,130.86", "新小倉火力発電所", 1200, conf="high",
             stype="official"),
        _rec("geo:kyushu:130.8602,33.9083", "新小倉火力発電所", 1200),
    ]
    out = _run(tmp_path, feats, recs)
    p = out[0]["properties"]
    assert p["capacity_mw_sourced"] == 1200
    assert p["capacity_source_type"] == "official"


def test_geo_wins_when_name_record_has_no_coords(tmp_path):
    # 座標を内包しない名前レコードはこのfeatureを確証できない → geoが勝つ
    feats = [_feat("苅田バイオマス発電所", "kyushu", 131.0068, 33.8097)]
    recs = [
        _rec("plant:苅田バイオマス発電所", "苅田バイオマス発電所", 75.0, conf="high",
             stype="official"),
        _rec("geo:kyushu:131.0068,33.8097", "苅田バイオマス発電所", 75),
    ]
    out = _run(tmp_path, feats, recs)
    assert out[0]["properties"]["capacity_source_type"] == "other"


def test_geo_applies_to_unnamed_feature(tmp_path):
    feats = [_feat("", "kyushu", 130.5, 32.5)]
    recs = [_rec("geo:kyushu:130.5000,32.5000", "(無名)kyushu:0", 3)]
    out = _run(tmp_path, feats, recs)
    assert out[0]["properties"]["capacity_mw_sourced"] == 3
