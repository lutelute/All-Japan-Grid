"""scripts/publish_stamp.py: 公開する GeoJSON の出典表示と透かし。"""
import importlib.util
import json
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "publish_stamp", Path(__file__).resolve().parents[1] / "scripts" / "publish_stamp.py")
ps = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ps)

KEY = b"test-key"


def _fc():
    # 線の端と変電所が同じ点 (136.1747962, 36.1182192) を共有する。精度の違う書き方も混ぜる
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"name": "線"},
             "geometry": {"type": "LineString",
                          "coordinates": [[136.1747962, 36.1182192], [136.18, 36.12], [136.2225, 43.0575, 12.5]]}},
            {"type": "Feature", "properties": {"name": "変電所"},
             "geometry": {"type": "Point", "coordinates": [136.1747962, 36.1182192]}},
            {"type": "Feature", "properties": {},
             "geometry": {"type": "MultiPolygon",
                          "coordinates": [[[[136.18, 36.12], [136.19, 36.12], [136.19, 36.13], [136.18, 36.12]]]]}},
            {"type": "Feature", "properties": {}, "geometry": None},
        ],
    }


def _points(fc):
    out = []

    def walk(c):
        if ps._is_pos(c):
            out.append(c)
        elif isinstance(c, list):
            for x in c:
                walk(x)
    for ft in fc["features"]:
        if ft["geometry"]:
            walk(ft["geometry"]["coordinates"])
    return out


def test_shift_is_under_10cm_and_7_decimals():
    orig, fc = _fc(), _fc()
    assert ps.stamp_collection(fc, KEY, {})
    for a, b in zip(_points(orig), _points(fc)):
        assert abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6
        for v in b[:2]:
            assert len(repr(v).split(".")[1]) == 7  # 7 桁目が 0 にならない (1〜9)
        assert b[2:] == a[2:]  # 高さはそのまま


def test_shared_points_stay_shared():
    fc = _fc()
    ps.stamp_collection(fc, KEY, {})
    line_start = fc["features"][0]["geometry"]["coordinates"][0]
    sub = fc["features"][1]["geometry"]["coordinates"]
    assert line_start == sub
    # 別のファイル (別の cache) でも同じ値になる
    other = _fc()
    ps.stamp_collection(other, KEY, {})
    assert other["features"][1]["geometry"]["coordinates"] == sub
    # 136.18 は線にも多角形にも出る
    assert fc["features"][0]["geometry"]["coordinates"][1] == fc["features"][2]["geometry"]["coordinates"][0][0][0]


def test_attribution_first_and_idempotent():
    fc = _fc()
    assert ps.stamp_collection(fc, KEY, {})
    assert list(fc)[:2] == ["type", "attribution"]
    assert "OpenStreetMap contributors" in fc["attribution"]["attribution"]
    once = json.dumps(fc)
    assert not ps.stamp_collection(fc, KEY, {})  # 二度目は触らない
    assert json.dumps(fc) == once


def test_without_key_only_attribution():
    orig, fc = _fc(), _fc()
    assert ps.stamp_collection(fc, None, {})
    assert _points(fc) == _points(orig)
    assert fc["attribution"]["stamp"].endswith("-nokey")


def test_keyed_match_detects_and_rejects():
    fc = _fc()
    ps.stamp_collection(fc, KEY, {})
    text = json.dumps(fc)
    n, hit = ps.keyed_match(text, KEY)
    assert n > 0 and hit == n
    n2, hit2 = ps.keyed_match(text, b"other-key")
    assert hit2 < n2
    # 丸められたら印は読めない (n=0)
    assert ps.keyed_match(json.dumps(_fc()).replace("136.1747962", "136.1748"), KEY)[0] <= n


def test_keyed_match_rate_by_chance_is_low():
    import random
    rnd = random.Random(0)
    pts = [[round(rnd.uniform(130, 145), 7), round(rnd.uniform(31, 45), 7)] for _ in range(4000)]
    text = json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": {"type": "MultiPoint", "coordinates": pts}}]})
    n, hit = ps.keyed_match(text, KEY)
    assert n > 6000
    assert 0.08 < hit / n < 0.15  # 偶然なら約 1/9


def test_cmd_stamp_writes_files(tmp_path, monkeypatch):
    monkeypatch.setenv("AJG_WATERMARK_KEY", "test-key")
    p = tmp_path / "sub" / "a.geojson"
    p.parent.mkdir()
    p.write_text(json.dumps(_fc()), encoding="utf-8")
    (tmp_path / "not_fc.geojson").write_text('{"type": "Feature"}', encoding="utf-8")
    assert ps.main(["stamp", str(tmp_path)]) == 0
    out = json.loads(p.read_text(encoding="utf-8"))
    assert out["attribution"]["stamp"] == ps.STAMP_VERSION
    assert json.loads((tmp_path / "not_fc.geojson").read_text()) == {"type": "Feature"}


@pytest.mark.skipif(not list((Path(__file__).resolve().parents[1] / "data").glob("*_substations.geojson")),
                    reason="data/ が無い")
def test_ajg_generated_names_are_found():
    names = ps.ajg_generated_names()
    assert all(len(v) > 100 for v in names.values())
    # 「丁目」の変電所名は OSM の名前ではなく AJG が住所から付けたもの
    assert any("丁目変電所" in n for n in names["丁目の変電所名 (住所から)"])


def _js_tofixed(x: float, k: int) -> str:
    """JS の Number.prototype.toFixed と同じ丸め (浮動小数の中身を 10 進で正確に見て、半分は大きい方)。"""
    from decimal import ROUND_HALF_UP, Decimal
    d = abs(Decimal(x)).quantize(Decimal(1).scaleb(-k), rounding=ROUND_HALF_UP)
    return ("-" if x < 0 else "") + str(d)


def test_rounding_keys_unchanged():
    """地図の JS は toFixed(4)/(5) で座標の鍵を作り、透かしの無い built/all.json などと突き合わせる。
    6 桁目までを残す切り捨てなので、5 桁以下の丸めは元と同じになる。"""
    import random
    rnd = random.Random(1)
    vals = [round(rnd.uniform(122, 154), rnd.choice([2, 3, 4, 5, 6, 7, 8, 9])) for _ in range(20000)]
    vals += [138.24695, 136.03125, 136.1747962, 136.17485, 136.1748499, 136.1748450, 35.0000049, 35.0000051, -12.3456749, 136.0]
    cache = {}
    for v in vals:
        s, _ = ps.stamp_point(KEY, v, 35.0, cache)
        assert abs(s - v) < 1e-6
        for k in (3, 4, 5):
            assert _js_tofixed(s, k) == _js_tofixed(v, k), (v, s, k)


def test_negative_coordinates_roundtrip():
    s_lon, s_lat = ps.stamp_point(KEY, -122.4194155, -37.7749295, {})
    assert s_lon < 0 and s_lat < 0
    text = json.dumps({"c": [[s_lon, s_lat]]})
    assert ps.keyed_match(text, KEY) == (2, 2)
