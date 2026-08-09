"""修復候補探索（`scripts/capacity/repair_search.py`）のゲート。

この探索は「捏造量ともっともらしさ」の非劣解を出すので、**測り方が狂うと結論が狂う**。
特にこの診断系列は並列回線数の取り違えを 4 回踏んでいるので、
負荷率の独立経路（電力基準）が pandapower の電流基準と一致することを固定する。

2026-08-09 に実際に捕まえた測定器の誤り:
  混在電圧線（110/66kV）で from 側の電圧から定格を組むと負荷率を過小評価する
  （hokkaido で 21.9% vs 36.5% ＝ 14.6pt）。pandapower は max(i_from, i_to) を採るので
  **両端の低い方**の電圧が正しい。
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "scripts" / "capacity" / "repair_search.py"

pytestmark = pytest.mark.skipif(not SRC.exists(), reason="repair_search.py が無い")


def _mod():
    spec = importlib.util.spec_from_file_location("repair_search_under_test", SRC)
    m = importlib.util.module_from_spec(spec)
    sys.modules["repair_search_under_test"] = m
    spec.loader.exec_module(m)
    return m


def _net(vn_to: float, parallel: int):
    """1 線 2 バスの最小系統。vn_to を変えると混在電圧線になる。"""
    import pandapower as pp
    net = pp.create_empty_network()
    b1 = pp.create_bus(net, vn_kv=110.0)
    b2 = pp.create_bus(net, vn_kv=vn_to)
    pp.create_line_from_parameters(net, b1, b2, length_km=10.0, r_ohm_per_km=0.1,
                                   x_ohm_per_km=0.3, c_nf_per_km=0.0, max_i_ka=0.4,
                                   parallel=parallel)
    pp.create_ext_grid(net, b1)
    pp.create_load(net, b2, p_mw=40.0)
    pp.rundcpp(net)
    return net


# ── パレート境界 ──────────────────────────────────────────────────────────
def test_pareto_front_keeps_only_nondominated():
    m = _mod()
    rows = [{"a": 1.0, "b": 5.0},      # 0: 非劣
            {"a": 5.0, "b": 1.0},      # 1: 非劣
            {"a": 3.0, "b": 3.0},      # 2: 非劣
            {"a": 4.0, "b": 4.0}]      # 3: 2 に全項目で負ける
    assert m.pareto_front(rows, ["a", "b"]) == [0, 1, 2]


def test_pareto_front_is_three_objective_capable():
    """捏造容量・捏造設備・超過潮流の 3 目的で重み付けをしないことが要点。"""
    m = _mod()
    rows = [{"u": 100.0, "t": 0.0, "e": 50.0},
            {"u": 10.0, "t": 900.0, "e": 20.0},
            {"u": 100.0, "t": 900.0, "e": 60.0}]   # 0 にも 1 にも劣る
    assert m.pareto_front(rows, ["u", "t", "e"]) == [0, 1]


def test_pareto_front_dedups_identical_points():
    """同値の構成は互いに支配しない（片方だけ落とすと非劣解が欠ける）。"""
    m = _mod()
    rows = [{"a": 1.0, "b": 1.0}, {"a": 1.0, "b": 1.0}]
    assert m.pareto_front(rows, ["a", "b"]) == [0, 1]


# ── 負荷率の独立経路 ──────────────────────────────────────────────────────
def test_power_basis_matches_pandapower_on_same_voltage_line():
    pytest.importorskip("pandapower")
    m = _mod()
    net = _net(vn_to=110.0, parallel=1)
    assert m.overload_stats_power(net)["max_gap_pt"] == pytest.approx(0.0, abs=0.01)


def test_power_basis_matches_pandapower_on_mixed_voltage_line():
    """2026-08-09 に踏んだ誤り。from 側の電圧で組むと 14.6pt ずれた。"""
    pytest.importorskip("pandapower")
    m = _mod()
    net = _net(vn_to=66.0, parallel=1)
    gap = m.overload_stats_power(net)["max_gap_pt"]
    assert gap == pytest.approx(0.0, abs=0.05), \
        f"混在電圧線で電力基準と電流基準が {gap}pt ずれる（低圧側の電圧を使うこと）"


def test_power_basis_counts_parallel_circuits():
    """並列回線を数え落とすと負荷率が 2 倍に出る — この系列で 4 回踏んだ罠。"""
    pytest.importorskip("pandapower")
    m = _mod()
    one = m.overload_stats_power(_net(vn_to=110.0, parallel=1))["max_pct"]
    two = m.overload_stats_power(_net(vn_to=110.0, parallel=2))["max_pct"]
    assert two == pytest.approx(one / 2.0, rel=0.02), \
        f"2 回線の負荷率が 1 回線の半分になっていない（{one}% → {two}%）"


def test_rating_uses_root_three_and_kv():
    """定格 MVA の組み立てが |P| 基準として正しいこと（√3・kV・並列数）。"""
    pytest.importorskip("pandapower")
    m = _mod()
    net = _net(vn_to=110.0, parallel=1)
    rating = 0.4 * 110.0 * math.sqrt(3.0)
    expect = 40.0 / rating * 100.0
    assert m.overload_stats_power(net)["max_pct"] == pytest.approx(expect, rel=0.03)


# ── 実装の一本化 ──────────────────────────────────────────────────────────
def test_operators_are_reused_not_reimplemented():
    """修復オペレータは what-if 本体を呼ぶこと。

    「診断と本番の実装が食い違って二度誤った」を三度目にしないための構造的ゲート。
    """
    src = SRC.read_text(encoding="utf-8")
    assert "whatif_gen_voltage.py" in src and "whatif_stepdown.py" in src, \
        "what-if 本体を読み込んでいない"
    assert "wgv.attach_generators_variant" in src, "接続規則を自前で書き直している"
    assert "wsd.add_stepdowns" in src, "降圧点の補充を自前で書き直している"


def test_solar_default_is_restored_after_each_config():
    """`_DEFAULT_CAP` はモジュール大域なので、構成間で漏らすと後続が汚染される。"""
    src = SRC.read_text(encoding="utf-8")
    assert "finally:" in src and 'pf._DEFAULT_CAP["solar"] = saved' in src, \
        "太陽光既定値の復元が finally に無い"
