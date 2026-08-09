"""座標解決の正典実装のテスト。

2026-08-07〜09 に 3 つのスクリプトで同じ事故（座標→単一 ID に潰してノードが
静かに脱落する）を起こしたため、その罠をテストとして固定する。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.topology.coords import CoordIndex, ckey

ROOT = Path(__file__).resolve().parents[1]
BUILT = ROOT / "docs" / "data" / "built" / "all.json"


def test_multi_layer_substation_is_not_collapsed():
    """多層変電所は座標を共有する。両方の層が引けなければならない。"""
    nodes = [
        {"id": "a_sub_1@154", "lat": 35.0, "lon": 139.0, "kv": 154.0},
        {"id": "a_sub_1@66", "lat": 35.0, "lon": 139.0, "kv": 66.0},
    ]
    ix = CoordIndex(nodes)
    assert ix.at(35.0, 139.0) == [0, 1]
    assert ix.shared_coord_stats()["n_would_be_lost"] == 1


def test_cross_region_duplicate_is_not_collapsed():
    """地域抽出の重なりで生じる重複コピーも両方引ける。"""
    nodes = [
        {"id": "hokkaido_sub_0", "lat": 41.5, "lon": 140.1, "kv": 66.0},
        {"id": "tohoku_sub_688", "lat": 41.5, "lon": 140.1, "kv": 66.0},
    ]
    ix = CoordIndex(nodes)
    assert len(ix.at(41.5, 140.1)) == 2
    assert list(ix.colocated_pairs()) == [(0, 1)]


def test_endpoints_prefers_matching_voltage():
    """線路は自分の電圧の層に着く（全層に着けると過剰結線になる）。"""
    nodes = [
        {"id": "s@275", "lat": 35.0, "lon": 139.0, "kv": 275.0},
        {"id": "s@154", "lat": 35.0, "lon": 139.0, "kv": 154.0},
    ]
    ix = CoordIndex(nodes)
    assert ix.endpoints((35.0, 139.0), kv=154.0) == [1]
    assert ix.endpoints((35.0, 139.0), kv=275.0) == [0]
    # 一致する層が無ければ全ノードに落とす（情報を捨てない）
    assert ix.endpoints((35.0, 139.0), kv=500.0) == [0, 1]
    # 電圧を指定しなければ全ノード
    assert ix.endpoints((35.0, 139.0)) == [0, 1]


def test_missing_coordinate_returns_empty():
    ix = CoordIndex([{"id": "s", "lat": 35.0, "lon": 139.0, "kv": 66.0}])
    assert ix.at(0.0, 0.0) == []
    assert ix.endpoints((0.0, 0.0), kv=66.0) == []


def test_ckey_rounds_to_metre_scale():
    # 5桁 ≈ 1m。それ以下の差は同一地点とみなす
    assert ckey(35.123456, 139.123456) == ckey(35.1234561, 139.1234559)
    assert ckey(35.12345, 139.0) != ckey(35.12346, 139.0)


@pytest.mark.skipif(not BUILT.exists(), reason="built モデルが無い環境")
def test_built_model_actually_shares_coordinates():
    """実データで前提が成り立っていることの確認。

    ここが 0 になったらモデルの生成方法が変わったということで、
    各スクリプトの座標解決の前提も見直しが要る。
    """
    nodes = json.load(open(BUILT))["nodes"]
    st = CoordIndex(nodes).shared_coord_stats()
    assert st["n_shared_coords"] > 1000, st
    # 座標→単一IDに潰すと消えるノードが実際に大量にある
    assert st["n_would_be_lost"] > 3000, st
