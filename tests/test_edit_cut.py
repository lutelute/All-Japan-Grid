"""E8b: disconnect→builder cut機構のテスト。

切断は「誤接続(合成橋/誤スナップ/手動誤接続)の除去」=捏造の逆操作(抑制)。
端点座標(round 5・built_viewと同一精度)で枝を照合し生成しない。基底extract/supplementは不変。
編集を取消せば次回buildで枝は復活(可逆)。
"""
import json
import os
import shutil

from src.powerflow.snapped_topology import build_network_snapped, _normalize_cuts
from src.server import edit_apply, edit_log


def _first_edge_key(net):
    """netの実枝1本の端点キー(a,b)を返す(両端が変電所・座標が異なるもの)。"""
    pos = {s.id: (round(s.latitude, 5), round(s.longitude, 5)) for s in net.substations}
    for ln in net.transmission_lines:
        a = pos.get(ln.from_substation_id)
        b = pos.get(ln.to_substation_id)
        if a and b and a != b:
            return a, b
    raise AssertionError("no edge with distinct endpoints")


def _edge_present(net, a, b):
    pos = {s.id: (round(s.latitude, 5), round(s.longitude, 5)) for s in net.substations}
    return any(frozenset((pos.get(ln.from_substation_id), pos.get(ln.to_substation_id)))
               == frozenset((a, b)) for ln in net.transmission_lines)


def test_normalize_cuts_forms_equivalent():
    a, b = (35.0, 135.0), (35.1, 135.1)
    from_list = _normalize_cuts([[[35.0, 135.0], [35.1, 135.1]]])
    from_dict = _normalize_cuts([{"a": {"lat": 35.1, "lon": 135.1},
                                  "b": {"lat": 35.0, "lon": 135.0}}])
    assert from_list == from_dict          # 順序非依存・list/dict同値
    assert frozenset((a, b)) in from_list
    assert _normalize_cuts(None) == set()
    assert _normalize_cuts([{"a": {"lat": 1}}]) == set()   # 不正入力はskip(例外でなく無視)


def test_builder_cut_removes_targeted_edge():
    net = build_network_snapped("okinawa", db=None)
    a, b = _first_edge_key(net)
    n0 = len(net.transmission_lines)
    assert _edge_present(net, a, b)

    cut = build_network_snapped("okinawa", db=None, cuts=[[list(a), list(b)]])
    assert len(cut.transmission_lines) < n0                # 枝が減る
    assert cut.metadata.get("cut_lines") == str(n0 - len(cut.transmission_lines))
    assert not _edge_present(cut, a, b)                    # 当該枝が消えた


def test_cut_does_not_touch_unrelated_edges():
    """切断は指定枝のみ。無関係な枝・変電所は不変(誤って網を壊さない)。"""
    net = build_network_snapped("okinawa", db=None)
    a, b = _first_edge_key(net)
    cut = build_network_snapped("okinawa", db=None, cuts=[[list(a), list(b)]])
    assert len(cut.substations) == len(net.substations)    # 変電所は不変
    # 消えたのは1端点ペア分だけ(parallelを含むので >=1)
    assert 1 <= len(net.transmission_lines) - len(cut.transmission_lines) <= 4


def test_cuts_file_autoloaded_from_data_dir(tmp_path):
    """{region}_cuts.json をbuilderが自動読込(adopt→本番反映の経路)。"""
    for layer in ("lines", "substations", "plants"):
        src = f"data/okinawa_{layer}.geojson"
        if os.path.exists(src):
            shutil.copy(src, tmp_path / f"okinawa_{layer}.geojson")
    base = build_network_snapped("okinawa", db=None, data_dir=str(tmp_path))
    a, b = _first_edge_key(base)
    (tmp_path / "okinawa_cuts.json").write_text(json.dumps(
        {"cuts": [{"a": {"lat": a[0], "lon": a[1]},
                   "b": {"lat": b[0], "lon": b[1]}, "edit_id": "e_test"}]}),
        encoding="utf-8")
    cut = build_network_snapped("okinawa", db=None, data_dir=str(tmp_path))
    assert len(cut.transmission_lines) < len(base.transmission_lines)
    assert not _edge_present(cut, a, b)


def test_absent_cuts_file_is_noop(tmp_path):
    """cuts.json が無ければ本番モデルは完全に不変(切断機構の安全性)。"""
    for layer in ("lines", "substations", "plants"):
        src = f"data/okinawa_{layer}.geojson"
        if os.path.exists(src):
            shutil.copy(src, tmp_path / f"okinawa_{layer}.geojson")
    n_no_dir = len(build_network_snapped("okinawa", db=None).transmission_lines)
    n_tmp = len(build_network_snapped("okinawa", db=None, data_dir=str(tmp_path)).transmission_lines)
    assert n_no_dir == n_tmp                                # cutファイル無し=不変


def test_cut_entries_requires_coordinates():
    edits = [
        {"action": "disconnect", "a": {"lat": 1, "lon": 2}, "b": {"lat": 3, "lon": 4}, "id": "e1"},
        {"action": "disconnect", "line_key": "x", "id": "e2"},     # 座標なし=skip
        {"action": "connect", "a": {"lat": 1, "lon": 2}, "b": {"lat": 3, "lon": 4}, "id": "e3"},
    ]
    out = edit_apply._cut_entries(edits)
    assert len(out) == 1 and out[0]["edit_id"] == "e1"


def test_verify_applies_disconnect(monkeypatch):
    """verify() が disconnect を一時適用し、枝削減で島が増える(>=0)ことを確認。"""
    net = build_network_snapped("okinawa", db=None)
    a, b = _first_edge_key(net)
    fake = [{"action": "disconnect", "region": "okinawa", "status": "pending", "id": "ed1",
             "a": {"lat": a[0], "lon": a[1]}, "b": {"lat": b[0], "lon": b[1]}}]
    monkeypatch.setattr(edit_log, "list_edits",
                        lambda region=None, status=None, path=None:
                        [e for e in fake if not region or e["region"] == region])
    res = edit_apply.verify("okinawa")
    assert res["applied"]["disconnect"] == 1
    assert res["delta_islands"] >= 0          # 枝の除去は成分を分割しうる(減らさない)
