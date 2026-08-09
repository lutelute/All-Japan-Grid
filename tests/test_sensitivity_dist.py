"""感度行列の出荷物の品質ゲート。

行列本体（npz）は git 管理外で再生成する前提なので、**索引表だけが同梱される**。
索引表が壊れると行列を解釈できなくなるため、そこを固定する。
行列がローカルに再生成されていれば、行列と索引表の整合まで確認する。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "sensitivity"
META = DIST / "meta.json"

pytestmark = pytest.mark.skipif(not META.exists(), reason="dist/sensitivity 未生成")


def _meta() -> dict:
    return json.load(open(META))


def _rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def islands() -> list[str]:
    return [r["island"] for r in _meta()["islands"]]


def test_meta_has_version_and_changelog():
    m = _meta()
    assert m["sensitivity_version"] in m["changelog"], "版が changelog に無い"
    assert m["islands"], "島の記録が空"
    for r in m["islands"]:
        assert r["n_bus"] > 0 and r["n_branch"] > 0
        assert 0.0 <= r["bridge_share"] <= 1.0
        assert len(r["sha256"]) == 64, "行列の指紋が無い＝再生成の同一性を検証できない"


@pytest.mark.parametrize("island", islands())
def test_index_tables_match_meta(island):
    """索引表の行数が行列の形と一致すること。ここがずれると全ての解釈が狂う。"""
    m = {r["island"]: r for r in _meta()["islands"]}[island]
    bus = _rows(DIST / f"{island}_bus.csv")
    br = _rows(DIST / f"{island}_branch.csv")
    assert len(bus) == m["n_bus"], f"バス表 {len(bus)} != 行列の列 {m['n_bus']}"
    assert len(br) == m["n_branch"], f"枝表 {len(br)} != 行列の行 {m['n_branch']}"
    # 行番号は 0..n-1 が欠けずに並ぶ
    assert [int(r["col"]) for r in bus] == list(range(len(bus)))
    assert [int(r["row"]) for r in br] == list(range(len(br)))


@pytest.mark.parametrize("island", islands())
def test_branch_table_is_usable(island):
    """容量と橋フラグが揃っていること（screening がこの2列に依存する）。"""
    m = {r["island"]: r for r in _meta()["islands"]}[island]
    br = _rows(DIST / f"{island}_branch.csv")
    with_cap = [r for r in br if r["capacity_mva"] not in ("", None)]
    assert len(with_cap) == len(br), "容量が欠けている枝がある"
    assert all(float(r["capacity_mva"]) > 0 for r in with_cap)
    n_bridge = sum(1 for r in br if r["is_bridge"] == "1")
    assert n_bridge == m["n_bridge"], f"橋の数が meta と不一致 {n_bridge} != {m['n_bridge']}"


@pytest.mark.parametrize("island", islands())
def test_bus_table_traces_back_to_built(island):
    """列が built のノードまで辿れること。辿れないと結果を地図に戻せない。"""
    bus = _rows(DIST / f"{island}_bus.csv")
    named = [r for r in bus if r["built_node_id"]]
    assert len(named) / len(bus) > 0.99, "built ノード ID に紐づかない列が多い"
    assert all(r["lat"] and r["lon"] for r in named), "座標が欠けている列がある"


@pytest.mark.parametrize("island", islands())
def test_matrix_shapes_when_present(island):
    """行列がローカルに再生成されていれば、索引表と形が合うこと。"""
    npz = DIST / f"{island}_sensitivity.npz"
    if not npz.exists():
        pytest.skip("行列は git 管理外。再生成されていない環境ではスキップ")
    m = {r["island"]: r for r in _meta()["islands"]}[island]
    d = np.load(npz)
    assert d["ptdf"].shape == (m["n_branch"], m["n_bus"])
    if "lodf" in d:
        assert d["lodf"].shape == (m["n_branch"], m["n_branch"])
        assert d["is_bridge"].shape == (m["n_branch"],)
        assert int(d["is_bridge"].sum()) == m["n_bridge"]
    # 参照バスの列は定義上ゼロ（そこへの注入は潮流を動かさない）
    assert np.allclose(d["ptdf"][:, int(d["slack_col"][0])], 0.0, atol=1e-6)


@pytest.mark.parametrize("island", islands())
def test_lodf_diagonal_is_minus_one(island):
    """LODF の対角は自分自身への影響＝−1。実装が入れ替わったら気づけるようにする。"""
    npz = DIST / f"{island}_sensitivity.npz"
    if not npz.exists():
        pytest.skip("行列は git 管理外")
    d = np.load(npz)
    if "lodf" not in d:
        pytest.skip("LODF 無しで生成された")
    lodf, bridge = d["lodf"], d["is_bridge"].astype(bool)
    diag = np.diag(lodf)[~bridge]
    assert np.allclose(diag, -1.0, atol=1e-4), f"対角が −1 でない: {diag[:5]}"
