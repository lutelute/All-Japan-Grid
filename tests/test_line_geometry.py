"""src.topology.line_geometry: 地図の線を OSM の経路で描き直す(2026-11-07)。"""
from src.topology import line_geometry as LG


def _net(*ways):
    net = LG.OsmNet()
    for coords, kv in ways:
        net.add_way(coords, LG.kv_set(kv))
    net.add_bridges()
    return net


# 経度 0.01 度 ≈ 900 m(北緯 35 度)
W1 = [[135.00, 35.0], [135.01, 35.0], [135.02, 35.005], [135.03, 35.0], [135.04, 35.0]]


def test_gap_is_filled_along_the_osm_line():
    net = _net((W1, "154000"))
    # 正典の形が 135.00 → 135.04 を直線で飛んでいる
    out, straight, st = LG.refine([(35.0, 135.00), (35.0, 135.04)], 154.0, net, True)
    assert not straight and st["routed"] == 1
    assert (35.005, 135.02) in out, "OSM の線の頂点(鉄塔)を通っていない"


def test_no_osm_line_leaves_a_marked_straight_segment():
    net = _net((W1, "154000"))
    out, straight, st = LG.refine([(36.0, 135.00), (36.0, 135.04)], 154.0, net, True)
    assert straight == [0] and st["unrouted"] == 1
    assert out == [(36.0, 135.00), (36.0, 135.04)]


def test_wrong_voltage_line_is_used_only_as_last_resort():
    # 66 kV の線しか無いとき、154 kV の枝は電圧を問わない最後の試しでたどる(直線よりは実際の経路に近い)
    net = _net((W1, "66000"))
    out, straight, _ = LG.refine([(35.0, 135.00), (35.0, 135.04)], 154.0, net, True)
    assert not straight and (35.005, 135.02) in out


def test_small_gap_between_ways_is_bridged():
    # OSM の線が 30 m ほど離れて 2 本に描かれている(つなぎ忘れ)
    a = [[135.00, 35.0], [135.01, 35.0], [135.02, 35.0]]
    b = [[135.0203, 35.0], [135.03, 35.0], [135.04, 35.0]]
    net = _net((a, "275000"), (b, "275000"))
    out, straight, _ = LG.refine([(35.0, 135.00), (35.0, 135.04)], 275.0, net, True)
    assert not straight and (35.0, 135.03) in out


def test_long_detour_is_not_taken():
    # 直線の何倍も遠回りする線しか無いときは、たどらない(別の線を描いてしまわない)
    loop = [[135.00, 35.0], [135.00, 35.2], [135.04, 35.2], [135.04, 35.0]]
    net = _net((loop, "154000"))
    out, straight, _ = LG.refine([(35.0, 135.00), (35.0, 135.04)], 154.0, net, True)
    assert straight == [0]
