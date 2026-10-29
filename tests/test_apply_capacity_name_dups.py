"""apply_capacity_sources の名前照合は、同じ地域・同じ名前の feature のうち 1 つだけに当てる(2026-10-29).

出典の値は発電所全体の値。同名の feature が 2 つ以上あると、従来は全部に同じ値を塗り、同じ発電所を
重ねて数えていた(正典で 5 件: 川崎火力 3,420MW が JR東日本の地物にも、敦賀原子力 1,160MW が 0.04MW の地物にも、
葛根田地熱 30MW が 10 地物に)。OSM 容量が出典の値に最も近い 1 つだけに当てる。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from apply_capacity_sources import main  # noqa: E402


def _feat(name, region, lon, lat, cap=-1, fuel="gas"):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"name": name, "_region": region, "capacity_mw": cap, "fuel_type": fuel}}


def _rec(name, value, conf="medium"):
    return {"plant_key": f"plant:{name}", "name": name, "field": "capacity_mw", "value": value, "unit": "MW",
            "source_type": "wikipedia", "source_url": "https://ja.wikipedia.org/wiki/Test",
            "source_title": "Test", "quote": f"{value} MW", "retrieved_at": "2026-10-29",
            "confidence": conf, "collected_by": "test", "note": ""}


def _run(tmp_path, feats, recs):
    with open(tmp_path / "plants_all.geojson", "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f, ensure_ascii=False)
    main(data_dir=str(tmp_path), records=recs)
    with open(tmp_path / "plants_all.geojson", encoding="utf-8") as f:
        return json.load(f)["features"]


def test_same_name_two_operators_gets_one(tmp_path):
    # 川崎火力の型: JERA(OSM 3,420)と JR東日本(OSM 807)が同じ名前
    feats = [_feat("川崎火力発電所", "tokyo", 139.75, 35.51, cap=807.0),
             _feat("川崎火力発電所", "tokyo", 139.74, 35.50, cap=3420.0)]
    out = _run(tmp_path, feats, [_rec("川崎火力発電所", 3420)])
    assert "capacity_mw_sourced" not in out[0]["properties"]
    assert out[1]["properties"]["capacity_mw_sourced"] == 3420


def test_tiny_namesake_feature_not_painted(tmp_path):
    # 敦賀原子力の型: 本体(OSM 1,160)と、同名の 0.04MW の地物
    feats = [_feat("敦賀原子力発電所", "kansai", 136.05, 35.75, cap=1160.0, fuel="nuclear"),
             _feat("敦賀原子力発電所", "kansai", 136.06, 35.76, cap=0.0357, fuel="nuclear")]
    out = _run(tmp_path, feats, [_rec("敦賀原子力発電所", 1160)])
    assert out[0]["properties"]["capacity_mw_sourced"] == 1160
    assert "capacity_mw_sourced" not in out[1]["properties"]


def test_unknown_osm_capacity_still_gets_value_when_alone(tmp_path):
    feats = [_feat("単独火力発電所", "kyushu", 130.0, 33.0, cap=-1)]
    out = _run(tmp_path, feats, [_rec("単独火力発電所", 500)])
    assert out[0]["properties"]["capacity_mw_sourced"] == 500


def test_same_name_in_other_region_is_separate(tmp_path):
    # 地域ファイルの写し(敦賀が chubu・hokuriku・kansai に)は地域ごとに 1 つずつ当てる(地域の重複の整理は別の段)
    feats = [_feat("敦賀原子力発電所", "kansai", 136.05, 35.75, cap=1160.0, fuel="nuclear"),
             _feat("敦賀原子力発電所", "hokuriku", 136.05, 35.75, cap=1160.0, fuel="nuclear")]
    out = _run(tmp_path, feats, [_rec("敦賀原子力発電所", 1160)])
    assert all(f["properties"].get("capacity_mw_sourced") == 1160 for f in out)


def test_owner_is_chosen_across_files(tmp_path):
    # plants_ipp には JR東日本の地物しか無い。全体(plants_all)で選んだ JERA の地物にだけ当てる
    jera = _feat("川崎火力発電所", "tokyo", 139.74, 35.50, cap=3420.0)
    jr = _feat("川崎火力発電所", "tokyo", 139.75, 35.51, cap=807.0)
    for name, feats in (("plants_all.geojson", [jr, jera]), ("plants_ipp.geojson", [jr]),
                        ("plants_utility.geojson", [jera])):
        with open(tmp_path / name, "w", encoding="utf-8") as f:
            json.dump({"type": "FeatureCollection", "features": feats}, f, ensure_ascii=False)
    main(data_dir=str(tmp_path), records=[_rec("川崎火力発電所", 3420)])
    def load(n):
        with open(tmp_path / n, encoding="utf-8") as f:
            return json.load(f)["features"]
    assert "capacity_mw_sourced" not in load("plants_ipp.geojson")[0]["properties"]
    assert load("plants_utility.geojson")[0]["properties"]["capacity_mw_sourced"] == 3420
    assert [f["properties"].get("capacity_mw_sourced") for f in load("plants_all.geojson")] == [None, 3420]
