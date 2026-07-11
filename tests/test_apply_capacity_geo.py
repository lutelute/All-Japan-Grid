"""apply_capacity_sources の座標キー(geo:)照合の検証.

名前が全国非一意な発電所への出典適用は plant_key="geo:<region>:<lon.4f>,<lat.4f>"
で行う(1-C GEM充填の名前衝突回収)。ここで守るべき不変条件:
  1. geoレコードはキー一致のfeatureにのみ適用される(名前照合に混入しない)
  2. ファイル内で同一キーのfeatureが複数(分割片)ならどれにも適用しない
  3. 既存の名前照合レコードの挙動は不変
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from apply_capacity_sources import feature_geo_key, geo_key, main  # noqa: E402


def _feat(name, region, lon, lat, cap=-1):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"name": name, "_region": region, "capacity_mw": cap},
    }


def _rec(plant_key, name, value, conf="medium"):
    return {
        "plant_key": plant_key, "name": name, "field": "capacity_mw",
        "value": value, "unit": "MW", "source_type": "other",
        "source_url": "https://www.gem.wiki/Test_plant",
        "source_title": "Test plant — GEM wiki", "quote": f"Operating — {value} MW",
        "retrieved_at": "2026-07-11", "confidence": conf,
        "collected_by": "test", "note": "",
    }


def _run(tmp_path, feats, recs):
    d = {"type": "FeatureCollection", "features": feats}
    with open(tmp_path / "plants_all.geojson", "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    main(data_dir=str(tmp_path), records=recs)
    with open(tmp_path / "plants_all.geojson", encoding="utf-8") as f:
        return json.load(f)["features"]


def test_geo_key_format_matches_d_layer_rounding():
    # D層は4桁丸めPoint。書式が一致しないと照合できない
    assert geo_key("kyushu", 129.8354, 33.5152) == "geo:kyushu:129.8354,33.5152"
    ft = _feat("玄海原子力発電所", "kyushu", 129.8354, 33.5152)
    assert feature_geo_key(ft) == "geo:kyushu:129.8354,33.5152"


def test_geo_record_applies_to_unique_key_only(tmp_path):
    feats = [
        _feat("薩摩川内市発電所", "kyushu", 130.1234, 31.5678),  # 名前非一意想定
        _feat("薩摩川内市発電所", "kyushu", 130.2000, 31.6000),  # 同名の別発電所
    ]
    recs = [_rec("geo:kyushu:130.1234,31.5678", "薩摩川内市発電所", 2)]
    out = _run(tmp_path, feats, recs)
    assert out[0]["properties"].get("capacity_mw_sourced") == 2
    # 同名だがキー不一致のfeatureには適用されない(名前照合への混入禁止)
    assert "capacity_mw_sourced" not in out[1]["properties"]


def test_geo_ambiguous_key_applies_to_none(tmp_path):
    # 分割片: 同一4桁座標に2 feature → どれにも適用しない
    feats = [
        _feat("A太陽光", "kyushu", 130.1234, 31.5678),
        _feat("B太陽光", "kyushu", 130.1234, 31.5678),
    ]
    recs = [_rec("geo:kyushu:130.1234,31.5678", "A太陽光", 2)]
    out = _run(tmp_path, feats, recs)
    assert all("capacity_mw_sourced" not in f["properties"] for f in out)


def test_name_record_behavior_unchanged(tmp_path):
    feats = [_feat("玄海原子力発電所", "kyushu", 129.8354, 33.5152)]
    recs = [_rec("plant:玄海原子力発電所", "玄海原子力発電所", 2360)]
    out = _run(tmp_path, feats, recs)
    assert out[0]["properties"]["capacity_mw_sourced"] == 2360


def test_name_match_takes_precedence_and_geo_never_matches_by_name(tmp_path):
    # geoレコードの name と同名のfeatureがあってもキー不一致なら適用されない
    feats = [_feat("宇部市発電所", "kyushu", 131.0000, 33.0000)]
    recs = [_rec("geo:kyushu:131.9999,33.9999", "宇部市発電所", 5)]
    out = _run(tmp_path, feats, recs)
    assert "capacity_mw_sourced" not in out[0]["properties"]
