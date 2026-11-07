"""src.topology.osm_routes: OSM の way を路線にまとめる規則(2026-11-07)。

つなぐのは 3 つの規則だけで、併架・電圧の食い違い・名前の違うまとまりの橋渡しはつながない。
"""
from src.topology import osm_routes as R


def _way(wid, nodes, **tags):
    tags.setdefault("power", "line")
    return {"type": "way", "id": wid, "nodes": nodes, "tags": tags}


def _ways(*ws):
    return {w["id"]: w for w in ws}


def test_same_name_joins_and_route_id_is_min_way_id():
    ws = _ways(_way(30, [1, 2, 3], name="東海幹線", voltage="154000"),
               _way(10, [3, 4, 5], name="東海幹線", voltage="154000"))
    route_of, joins = R.assemble(ws)
    assert route_of[30] == route_of[10] == 10
    assert joins[10]["same_name"] == 1


def test_parallel_lines_on_shared_towers_are_not_joined():
    # 併架: 別の名前の線が同じ鉄塔(2, 3)を通る。点は共有するが電気的には別の線
    ws = _ways(_way(1, [1, 2, 3, 4], name="A線", voltage="154000"),
               _way(2, [5, 2, 3, 6], name="B線", voltage="154000"))
    route_of, _ = R.assemble(ws)
    assert route_of[1] != route_of[2]


def test_different_voltage_is_not_joined_even_with_same_name():
    ws = _ways(_way(1, [1, 2], name="X線", voltage="154000"),
               _way(2, [2, 3], name="X線", voltage="66000"))
    route_of, _ = R.assemble(ws)
    assert route_of[1] != route_of[2]


def test_unnamed_continuation_only_at_two_way_endpoint():
    ws = _ways(_way(1, [1, 2], voltage="77000"), _way(2, [2, 3], voltage="77000"))
    route_of, joins = R.assemble(ws)
    assert route_of[1] == route_of[2]
    assert joins[1]["continuation"] == 1
    # 3 本が会う点(分岐)では名前なしはつながない
    ws = _ways(_way(1, [1, 2], voltage="77000"), _way(2, [2, 3], voltage="77000"), _way(3, [2, 4], voltage="77000"))
    route_of, _ = R.assemble(ws)
    assert len({route_of[1], route_of[2], route_of[3]}) == 3


def test_unnamed_does_not_join_at_mid_point():
    # way 2 の途中の点で 1 の端が会う(T 字)。端点どうしでないのでつながない
    ws = _ways(_way(1, [1, 2], voltage="77000"), _way(2, [5, 2, 6], voltage="77000"))
    route_of, _ = R.assemble(ws)
    assert route_of[1] != route_of[2]


def test_half_named_needs_known_voltage():
    ws = _ways(_way(1, [1, 2], name="Y線", voltage="66000"), _way(2, [2, 3], voltage="66000"))
    route_of, joins = R.assemble(ws)
    assert route_of[1] == route_of[2] and joins[1]["half_named"] == 1
    ws = _ways(_way(1, [1, 2], name="Y線"), _way(2, [2, 3]))
    route_of, _ = R.assemble(ws)
    assert route_of[1] != route_of[2]


def test_unnamed_piece_does_not_bridge_two_different_names():
    # A線 ─ 名前なし ─ B線 と並ぶとき、A と B を 1 つの路線にしない
    ws = _ways(_way(1, [1, 2], name="A線", voltage="154000"),
               _way(2, [2, 3], voltage="154000"),
               _way(3, [3, 4], name="B線", voltage="154000"))
    route_of, _ = R.assemble(ws)
    assert route_of[1] != route_of[3]


def test_way_with_two_line_names_does_not_merge_the_two_lines():
    # 「上群線/群馬幹線」(1 列の鉄塔に 2 路線)を介して上群線と群馬幹線を 1 つにしない
    ws = _ways(_way(1, [1, 2], name="上群線", voltage="154000"),
               _way(2, [2, 3], name="上群線/群馬幹線", voltage="154000"),
               _way(3, [3, 4], name="群馬幹線", voltage="154000"),
               _way(4, [4, 5], name="群馬幹線 (Gunma Kansen)", voltage="154000"))
    route_of, _ = R.assemble(ws)
    assert route_of[1] != route_of[3]
    assert route_of[2] not in (route_of[1], route_of[3])
    assert route_of[3] == route_of[4]


def test_result_does_not_depend_on_input_order():
    a = [_way(5, [1, 2], name="Z線", voltage="275000"), _way(3, [2, 3], voltage="275000"),
         _way(9, [3, 4], name="Z線", voltage="275000")]
    r1, _ = R.assemble(_ways(*a))
    r2, _ = R.assemble(_ways(*reversed(a)))
    assert r1 == r2


def test_kv_set_and_style():
    assert R.kv_set({"voltage": "154000;66000"}) == {154.0, 66.0}
    assert R.kv_set({"voltage": "6600"}) == {6.6}
    assert R.kv_set({}) == set()
    assert R.way_style({"power": "cable", "location": "underground"}) == "u"
    assert R.way_style({"power": "cable", "location": "underwater"}) == "s"
    assert R.way_style({"power": "cable"}) == "c"
    assert R.way_style({"power": "line"}) == ""


def test_polyline_round_trip():
    c = [(35.12345, 136.54321), (35.2, 136.0), (34.99999, 137.00001)]
    assert R.decode_polyline(R.encode_polyline(c)) == c


def test_edge_key_matches_js_format():
    # docs/js/osm_routes.js の edgeKey() と同じ書き方(×1e4 の整数・始点・終点・頂点数)
    assert R.edge_key([[136.1234, 35.5678], [136.2, 35.6], [136.3001, 35.7]]) == "1361234,355678,1363001,357000,3"


def test_romaji_suffix_and_slash_are_ignored_in_names():
    assert R.name_set({"name": "東海幹線 (Tōkai-kansen)"}) == {"東海幹線"}
    assert R.name_set({"name": "上群線/群馬幹線"}) == {"上群線", "群馬幹線"}
    assert R.name_set({"name": "北方開閉所 (Kitakata Kaiheisho)"}) == {"北方開閉所"}
    # 括弧の中が日本語なら名前の一部として残す
    assert R.name_set({"name": "宗谷線（2号）"}) == {"宗谷線（2号）"}


def test_published_edge_routes_still_match_the_map():
    """地図の正典の線から路線を引く鍵(edge_routes.json)が、今の地図の線に当たっているか。

    正典を作り直しても形の変わらない枝は引ける。大きく外れたら export_osm_routes.py を流し直す合図。
    """
    import json
    from pathlib import Path
    docs = Path(__file__).resolve().parents[1] / "docs" / "data"
    er = docs / "osm_routes" / "edge_routes.json"
    lines = docs / "map" / "lines_all.geojson"
    if not er.exists() or not lines.exists():
        import pytest
        pytest.skip("地図のデータが無いチェックアウト")
    keys = json.loads(er.read_text(encoding="utf-8"))["map"]
    feats = json.loads(lines.read_text(encoding="utf-8"))["features"]
    shaped = [f for f in feats if len(f["geometry"]["coordinates"]) > 2]
    hit = sum(1 for f in shaped if R.edge_key(f["geometry"]["coordinates"]) in keys)
    assert hit / len(shaped) >= 0.6, f"地図の線のうち路線に引けるのが {hit}/{len(shaped)} しかない"


def test_ref_number_parses_only_plain_numbers():
    assert R.ref_number("55") == 55 and R.ref_number("No. 71") == 71 and R.ref_number("12号") == 12
    assert R.ref_number("376 / 320") is None and R.ref_number("12A") is None and R.ref_number(None) is None


def test_numbers_are_filled_only_when_the_count_matches():
    seq = [1, 2, 3, 4, 5, 6]
    num = {1: 10, 4: 13, 6: 20}.get
    out = R.infer_numbers(seq, lambda n: True, num)
    assert out == {2: 11, 3: 12}           # 10 と 13 の間に 2 基 → 11・12。13 と 20 の間は 1 基で数が合わない


def test_chain_order_follows_shared_endpoints():
    ws = _ways(_way(5, [3, 4]), _way(2, [1, 2, 3]))
    seqs, linear = R.chains([5, 2], ws)
    assert linear and seqs == [[1, 2, 3, 4]]
    ws = _ways(_way(1, [1, 2]), _way(2, [2, 3]), _way(3, [2, 4]))
    _, linear = R.chains([1, 2, 3], ws)
    assert not linear


def test_circuits_estimate_marks_its_basis():
    assert R.circuits_estimate({"cables": "6"}) == (2, "cables")
    assert R.circuits_estimate({"cables": "4"}) is None
    assert R.circuits_estimate({"cables": "2", "frequency": "0"}) == (1, "cables_dc")
    assert R.circuits_estimate({}, 2) == (2, "relations")
    assert R.circuits_estimate({"circuits": "2", "cables": "6"}) is None


def test_default_raw_dir_reads_nas_not_mac(monkeypatch, tmp_path):
    """鉄塔の生データの既定の場所は NAS(nas03 の 20261105 の抽出)か環境変数で、Mac の data/osm_raw_towers ではない。"""
    from src.topology import osm_routes as R
    monkeypatch.delenv("AJG_OSM_RAW_TOWERS", raising=False)
    monkeypatch.delenv("AGJ_OSM_RAW_TOWERS", raising=False)
    d = R.default_raw_dir()
    assert "osm_raw_towers" not in d and "20261105_agj_transmission" in d
    monkeypatch.setenv("AGJ_OSM_RAW_TOWERS", str(tmp_path))          # 旧名もしばらく読む
    assert R.default_raw_dir() == str(tmp_path)
    monkeypatch.setenv("AJG_OSM_RAW_TOWERS", str(tmp_path / "new"))  # 新名が先
    assert R.default_raw_dir() == str(tmp_path / "new")
