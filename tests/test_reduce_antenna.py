"""アンテナ集約(reduce_antenna)— 要る木だけ畳む縮約と、その帳簿。

配布ケースは、素朴 NR で解けない島だけ、電圧降下の見積もりが大きい木から順に
畳む(fold_until)。小さな網で、(1) 帳簿の負荷が重複しない、(2) only= で畳む
範囲を絞れる、(3) 重い木が先に並ぶ、(4) 収束した時点で止まる、を確かめる。
"""

import pandapower as pp
import pytest

from src.powerflow.reduce_antenna import (
    aggregate_antennas, antenna_trees, fold_until)


@pytest.fixture()
def net():
    """110kV の三角形の幹線に、66kV のアンテナが 2 本ぶら下がる網。

    A: b1 ─変圧器→ a1 ─ a2 ─ a3(軽い負荷・短い線)
    C: b2 ─変圧器→ c1 ─ c2(重い負荷・長い線)
    """
    n = pp.create_empty_network(sn_mva=100.0)
    b0, b1, b2 = (pp.create_bus(n, vn_kv=110.0, name=f"b{i}") for i in range(3))
    pp.create_ext_grid(n, b0)
    for f, t in ((b0, b1), (b1, b2), (b0, b2)):
        pp.create_line_from_parameters(n, f, t, length_km=20.0, r_ohm_per_km=0.05,
                                       x_ohm_per_km=0.38, c_nf_per_km=10.0, max_i_ka=1.0)
    a1, a2, a3 = (pp.create_bus(n, vn_kv=66.0, name=f"a{i}") for i in (1, 2, 3))
    c1, c2 = (pp.create_bus(n, vn_kv=66.0, name=f"c{i}") for i in (1, 2))
    for hv, lv in ((b1, a1), (b2, c1)):
        pp.create_transformer_from_parameters(n, hv, lv, sn_mva=100.0, vn_hv_kv=110.0,
                                              vn_lv_kv=66.0, vkr_percent=0.3,
                                              vk_percent=10.0, pfe_kw=0.0, i0_percent=0.0)
    for f, t, km in ((a1, a2, 2.0), (a2, a3, 2.0), (c1, c2, 30.0)):
        pp.create_line_from_parameters(n, f, t, length_km=km, r_ohm_per_km=0.12,
                                       x_ohm_per_km=0.40, c_nf_per_km=10.0, max_i_ka=0.6)
    pp.create_load(n, a2, p_mw=5.0, q_mvar=1.0)
    pp.create_load(n, a3, p_mw=5.0, q_mvar=1.0)
    pp.create_load(n, c2, p_mw=60.0, q_mvar=20.0)
    pp.create_load(n, b1, p_mw=10.0, q_mvar=2.0)
    return n


def _bus(n, name):
    return int(n.bus.index[n.bus.name == name][0])


def test_moved_load_is_counted_once(net):
    # a3 の負荷は a3→a2→a1→b1 と 3 段運ばれる。段ごとに足すと 15 MW 以上に化ける
    led = aggregate_antennas(net)
    assert led["n_removed"] == 5
    assert led["moved_load_mw"] == pytest.approx(70.0)
    assert net.load.p_mw.sum() == pytest.approx(80.0)


def test_only_limits_what_is_folded(net):
    c = {_bus(net, "c1"), _bus(net, "c2")}
    led = aggregate_antennas(net, only=c)
    assert led["n_removed"] == 2
    assert {"a1", "a2", "a3"} <= set(net.bus.name)
    assert not ({"c1", "c2"} & set(net.bus.name))
    assert net.load.p_mw.sum() == pytest.approx(80.0)


def test_antenna_trees_rank_the_heavy_tree_first(net):
    trees = antenna_trees(net)
    assert [t["root_name"] for t in trees] == ["b2", "b1"]
    assert trees[0]["load_mw"] == pytest.approx(60.0)
    assert trees[1]["load_mw"] == pytest.approx(10.0)
    assert trees[0]["drop_pu"] > trees[1]["drop_pu"] > 0
    assert sorted(trees[1]["names"]) == ["a1", "a2", "a3"]


def test_fold_until_stops_at_the_first_tree_that_suffices(net):
    folded, led = fold_until(net, lambda n: "c2" not in set(n.bus.name))
    assert led["n_trees"] == 1 and led["n_trees_total"] == 2
    assert led["n_removed"] == 2 and led["moved_load_mw"] == pytest.approx(60.0)
    assert {"a1", "a2", "a3"} <= set(folded.bus.name)
    assert folded.load.p_mw.sum() == pytest.approx(80.0)
    # 元の網には手を付けない
    assert "c2" in set(net.bus.name)


def test_fold_until_reports_failure(net):
    folded, led = fold_until(net, lambda n: False)
    assert folded is None
    assert led["converged"] is False


def test_folded_net_still_solves(net):
    folded, _ = fold_until(net, lambda n: True)
    pp.runpp(folded)
    assert folded.converged
