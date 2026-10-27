"""介入#54(issue #99): 出力の目標と、スラックに残った損失の配り方.

旧挙動は目標を「エリアの負荷全体 × (1 + 予備率)」にしていたので、予備率の分と、主成分から届かない
孤立片の負荷(孤立片の合成スラックが別に賄う)が主成分の出力に乗り、主成分のスラックが余りを吸っていた。
"""
import copy

import pytest

pp = pytest.importorskip("pandapower")

from src.powerflow.full_from_built import (  # noqa: E402
    add_per_component_slacks, balance_by_zone, bus_component_index, spread_slack)

CFG = {"reserve_margin": 0.05}


def _net():
    """主成分 = バス 0-1-2(zone a, a, b)、孤立片 = バス 3(zone a・発電機なし)。"""
    net = pp.create_empty_network()
    for z in ("a", "a", "b", "a"):
        pp.create_bus(net, vn_kv=110.0, zone=z)
    for f, t in ((0, 1), (1, 2)):
        pp.create_line_from_parameters(net, f, t, length_km=20.0, r_ohm_per_km=0.2,
                                       x_ohm_per_km=0.4, c_nf_per_km=0.0, max_i_ka=1.0)
    pp.create_gen(net, 0, p_mw=0.0, max_p_mw=100.0, vm_pu=1.0)
    pp.create_gen(net, 2, p_mw=0.0, max_p_mw=100.0, vm_pu=1.0)
    pp.create_load(net, 1, p_mw=40.0)
    pp.create_load(net, 2, p_mw=30.0)
    pp.create_load(net, 3, p_mw=20.0)
    add_per_component_slacks(net)
    return net


def test_components_are_numbered_largest_first():
    comp = bus_component_index(_net())
    assert comp[0] == comp[1] == comp[2] == 0 and comp[3] == 1


def test_old_target_counts_reserve_and_the_unreachable_fragment():
    net = _net()
    balance_by_zone(net, CFG)                       # 引数既定 = 旧挙動(what-if 群の基準)
    assert net.gen.p_mw.tolist() == pytest.approx([(40 + 20) * 1.05, 30 * 1.05])


def test_connected_target_is_reachable_same_zone_load_without_reserve():
    net = _net()
    balance_by_zone(net, CFG, connected=True)
    assert net.gen.p_mw.tolist() == pytest.approx([40.0, 30.0])
    pp.rundcpp(net)
    main = net.ext_grid.index[net.ext_grid.bus.map(bus_component_index(net)) == 0][0]
    assert abs(net.res_ext_grid.at[main, "p_mw"]) < 1e-6   # DC は損失なし → 主成分のスラックは 0


def test_spread_slack_hands_losses_to_generators_in_proportion():
    net = _net()
    balance_by_zone(net, CFG, connected=True)
    solved = copy.deepcopy(net)
    pp.runpp(solved)
    main = net.ext_grid.index[net.ext_grid.bus.map(bus_component_index(net)) == 0][0]
    loss = float(solved.res_ext_grid.at[main, "p_mw"])
    assert loss > 0.1                                   # AC の損失がスラックに残っている

    def resolve(nt):
        s = copy.deepcopy(nt)
        pp.runpp(s)
        return s, True
    out, info = spread_slack(net, solved, resolve, iters=8, tol_mw=1e-3)
    assert info["applied"] and abs(out.res_ext_grid.at[main, "p_mw"]) < 1e-3
    assert out.gen.p_mw[0] / out.gen.p_mw[1] == pytest.approx(40.0 / 30.0)   # 出力比を保つ
    assert net.gen.p_mw.tolist() == pytest.approx([40.0, 30.0])              # 渡したネットは変えない
    # 孤立片(発電機なし)の合成スラックは触らない
    frag = net.ext_grid.index[net.ext_grid.index != main][0]
    assert out.res_ext_grid.at[frag, "p_mw"] == pytest.approx(20.0, abs=1e-6)


def test_spread_slack_keeps_the_original_solution_when_a_resolve_fails():
    net = _net()
    balance_by_zone(net, CFG, connected=True)
    solved = copy.deepcopy(net)
    pp.runpp(solved)
    out, info = spread_slack(net, solved, lambda nt: (nt, False), tol_mw=1e-3)
    assert out is solved and not info["applied"]
