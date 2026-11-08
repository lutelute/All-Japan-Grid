"""介入#37(仮の給電)のつなぐ点の選び方が、バスの番号の順に依らないこと(2026-11-07)。

天草の 66 kV の塊で、志岐変電所と浄南町変電所の需要が同点で、どちらにつなぐかがバスの番号の順で決まっていた。
正典の点の数が変わるだけで(介入#58 の試算)つなぐ点が入れ替わり、西の最大負荷率が 605% ↔ 432% と動いた。
"""
import json

import pytest

pp = pytest.importorskip("pandapower")

from src.powerflow.compensation import add_provisional_infeed  # noqa: E402

UP = ("上位 500kV", 500.0, 130.00, 32.50)
LV = [("遠い変電所", 130.10, 32.50, 60.0),     # 上位まで約 9 km
      ("近い変電所", 130.03, 32.50, 60.0),     # 上位まで約 3 km(需要は同点)
      ("小さい変電所", 130.06, 32.52, 20.0)]


def _net(order):
    net = pp.create_empty_network()
    ids = {}
    up = pp.create_bus(net, vn_kv=UP[1], name=UP[0], geodata=(UP[2], UP[3]))
    for k in order:
        nm, lon, lat, mw = LV[k]
        ids[nm] = pp.create_bus(net, vn_kv=66.0, name=nm, geodata=(lon, lat))
        pp.create_load(net, bus=ids[nm], p_mw=mw)
    pp.create_ext_grid(net, bus=up)
    names = [x[0] for x in LV]
    for a, b in ((names[0], names[2]), (names[2], names[1])):
        pp.create_line_from_parameters(net, ids[a], ids[b], length_km=3.0, r_ohm_per_km=0.1, x_ohm_per_km=0.4,
                                       c_nf_per_km=0.0, max_i_ka=1.0)
    return net


@pytest.mark.parametrize("order", [(0, 1, 2), (1, 0, 2), (2, 1, 0), (2, 0, 1)])
def test_tied_anchor_is_the_one_nearer_to_the_upper_bus(order):
    net = _net(order)
    led = add_provisional_infeed(net, min_load_mw=100.0, max_dist_km=40.0)
    assert len(led) == 1 and len(net.trafo) == 1
    lv = int(net.trafo.lv_bus.iloc[0])
    assert net.bus.at[lv, "name"] == "近い変電所"          # バスを作る順に依らず、上位に近い方
    assert led[0]["dist_km"] < 5
