"""出典容量の名前照合に対する燃料種ゲート(2026-09-02)。

背景: 高崎市の太陽光「高浜発電所」(25MW×4 地物)に関電 高浜発電所(原子力 3,392MW)の
公式容量が名前照合で塗られ、PF の出典付き容量経路(sourced_capacity_index)で east に
13,569MW の幻の太陽光が立っていた(trackC2 の IBR 連系可能量レポートで発覚)。
姫路第二(gas 4,119MW)の隣接ソーラー・松浦火力の隣接ソーラーも同型。

規則(scripts/apply_capacity_sources.fuel_compatible):
  1. レコードに fuel_type があれば feature と完全一致のときだけ適用
  2. 無ければ IBR(太陽光/風力/蓄電)の feature には IBR を指す語を含むレコードだけ
  3. 不整合でも「値 <= OSM 値」(容量を増やさない是正)なら適用 — 大間・浪江小高のように
     OSM が計画原子力の敷地を solar と誤タグした feature を公式の「運転容量 0」で消す経路
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "apply_capacity_sources.py"


def _mod():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("apply_capacity_sources_ut", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _feat(name, fuel, cap, lon, lat, region="tokyo"):
    return {"type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"_region": region, "_display_name": name,
                           "fuel_type": fuel, "capacity_mw": cap}}


def _rec(name, value, **kw):
    r = {"plant_key": f"plant:{name}", "name": name, "field": "capacity_mw",
         "value": value, "unit": "MW", "source_type": "official",
         "source_url": "https://example.invalid/", "confidence": "high"}
    r.update(kw)
    return r


def _run(tmp_path, feats, recs):
    m = _mod()
    with open(tmp_path / "plants_all.geojson", "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f, ensure_ascii=False)
    m.main(data_dir=str(tmp_path), records=recs)
    with open(tmp_path / "plants_all.geojson", encoding="utf-8") as f:
        return [ft["properties"] for ft in json.load(f)["features"]]


def test_same_name_solar_does_not_receive_nuclear_capacity(tmp_path):
    """高浜: 名前だけの一致で太陽光 25MW に 3,392MW を塗ってはいけない。"""
    props = _run(tmp_path,
                 [_feat("高浜発電所", "solar", 25.0, 138.9326, 36.3721),
                  _feat("高浜原子力発電所", "nuclear", 3392.0, 135.5040, 35.5230, "kansai")],
                 [_rec("高浜原子力発電所", 3392, fuel_type="nuclear")])
    solar, nuke = props
    assert "capacity_mw_sourced" not in solar, "太陽光に原子力の容量が塗られた"
    assert nuke["capacity_mw_sourced"] == 3392


def test_record_without_fuel_type_needs_ibr_word_for_ibr_feature(tmp_path):
    """fuel_type 無しのレコードは、IBR feature には IBR を指す語が無ければ適用しない。"""
    props = _run(tmp_path,
                 [_feat("姫路第二発電所", "solar", 250.0, 134.6954, 34.7787, "kansai"),
                  _feat("姫路第二発電所", "gas", 4119.0, 134.6917, 34.7738, "kansai")],
                 [_rec("姫路第二発電所", 4119.0)])
    solar, gas = props
    assert "capacity_mw_sourced" not in solar
    assert gas["capacity_mw_sourced"] == 4119.0


def test_ibr_record_with_solar_word_applies_to_solar(tmp_path):
    props = _run(tmp_path,
                 [_feat("瀬戸内Kirei太陽光発電所", "solar", 235.0, 134.05, 34.69, "chugoku")],
                 [_rec("瀬戸内Kirei太陽光発電所", 231.44,
                       note="国内最大級のメガソーラー(太陽光)")])
    assert props[0]["capacity_mw_sourced"] == 231.44


def test_downward_correction_is_allowed_despite_fuel_mismatch(tmp_path):
    """大間: OSM が計画原子力の敷地を solar 138.3MW と誤タグ → 公式「運転容量 0」で消せる。"""
    props = _run(tmp_path,
                 [_feat("大間原子力発電所", "solar", 138.3, 140.9042, 41.5197, "hokkaido")],
                 [_rec("大間原子力発電所", 0)])
    assert props[0]["capacity_mw_sourced"] == 0


def test_upward_mismatch_with_unknown_osm_capacity_is_vetoed(tmp_path):
    """松浦: OSM 値不明(-1)の隣接ソーラーに火力 2,000MW は塗らない。"""
    props = _run(tmp_path,
                 [_feat("松浦火力発電所", "solar", -1.0, 129.6810, 33.3468, "kyushu")],
                 [_rec("松浦火力発電所", 2000)])
    assert "capacity_mw_sourced" not in props[0]


def test_explicit_fuel_type_must_match_exactly(tmp_path):
    props = _run(tmp_path,
                 [_feat("X発電所", "coal", 500.0, 130.0, 33.0, "kyushu")],
                 [_rec("X発電所", 700, fuel_type="gas")])
    assert "capacity_mw_sourced" not in props[0]


def test_real_d_layer_has_no_large_sourced_ibr():
    """正典 D 層に「出典付き 100MW 超の太陽光/風力/蓄電」が実在メガソーラー以外に無いこと。"""
    p = ROOT / "docs" / "data" / "plants_all.geojson"
    if not p.exists():
        import pytest
        pytest.skip("D層が無い")
    with open(p, encoding="utf-8") as f:
        feats = json.load(f)["features"]
    big = [(ft["properties"].get("_display_name"), ft["properties"]["capacity_mw_sourced"])
           for ft in feats
           if ft["properties"].get("fuel_type") in ("solar", "wind", "battery")
           and (ft["properties"].get("capacity_mw_sourced") or 0) >= 300]
    assert big == [], f"IBR に桁外れの出典容量: {big}"
