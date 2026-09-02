"""介入#43(降圧点欠損の是正)のゲート — 合成系統で構造を固定する。

  #43a 異階級直結線の暗黙降圧: 線 kv の端点に同階級ノードが無く別階級バスへ直結している
       箇所へ kv_L バス+kv_H/kv_L 変圧器を挿入し線を付け替える(存在は電気的必然)
  #43b 降圧点無し 66/77kV 網の帳簿付き縮約: 変圧器も電源も無い低圧成分の負荷を最近傍の
       ≥110kV バスへ移し成分を非通電化(需要保存・R 超は未給電網として開示)
"""
from __future__ import annotations

import json

import pytest

pp = pytest.importorskip("pandapower")

from src.powerflow import stepdown_gap as sg  # noqa: E402


def _bus(net, kv, lat, lon, name, typ="b"):
    b = pp.create_bus(net, vn_kv=kv, name=name, type=typ, geodata=(lon, lat))
    net.bus.at[b, "zone"] = "tokyo"
    return b


def _line(net, a, b, kv, km=5.0, name="L"):
    ika = {66.0: 0.6, 154.0: 1.2, 275.0: 2.0}[kv]
    return pp.create_line_from_parameters(net, a, b, length_km=km, r_ohm_per_km=0.1,
                                          x_ohm_per_km=0.3, c_nf_per_km=0.0,
                                          max_i_ka=ika, name=name)


def _mismatch_net():
    """275kV 母線 S(新宿相当)に 66kV 線が直結しているサイト。66kV 側に負荷バス L。"""
    net = pp.create_empty_network()
    hv = _bus(net, 275.0, 35.69, 139.70, "新宿変電所 275kV")
    src = _bus(net, 275.0, 35.75, 139.60, "源")
    lv_far = _bus(net, 66.0, 35.70, 139.72, "淀橋変電所")
    _line(net, src, hv, 275.0, km=12.0, name="幹線")
    li = _line(net, hv, lv_far, 66.0, km=2.0, name="新淀線")     # 66kV 線が 275kV 母線に直結
    net.line["kv_class"] = 0.0
    net.line.at[li, "kv_class"] = 66.0
    net.line.at[0, "kv_class"] = 275.0
    pp.create_ext_grid(net, bus=src)
    pp.create_load(net, bus=lv_far, p_mw=50.0, q_mvar=10.0)
    return net, hv, lv_far, li


def test_mismatch_is_detected_and_implicit_stepdown_inserted():
    net, hv, lv_far, li = _mismatch_net()
    mism = sg.find_class_mismatch(net)
    assert len(mism) == 1 and mism[0]["line"] == li and mism[0]["bus"] == hv
    n_bus, n_line, n_trafo = len(net.bus), len(net.line), len(net.trafo)
    led = sg.apply_implicit_stepdown(net)
    assert len(led) == 1 and led[0]["capacity"] == "estimated"
    assert len(net.bus) == n_bus + 1 and len(net.line) == n_line and len(net.trafo) == n_trafo + 1
    # 線の両端が 66kV になった(付け替え)・変圧器は 275/66
    fb, tb = int(net.line.at[li, "from_bus"]), int(net.line.at[li, "to_bus"])
    assert float(net.bus.at[fb, "vn_kv"]) == 66.0 and float(net.bus.at[tb, "vn_kv"]) == 66.0
    t = net.trafo.iloc[0]
    assert (t.vn_hv_kv, t.vn_lv_kv) == (275.0, 66.0) and int(t.hv_bus) == hv
    assert "#43a" in t["name"] and "推定" in t["name"]
    assert sg.find_class_mismatch(net) == []            # 是正後は不整合ゼロ
    # 解ける(AC)
    pp.runpp(net)
    assert net.converged


def test_nameplate_capacity_wins_when_site_has_a_plate():
    net, hv, _lv, _li = _mismatch_net()
    plates = {("tokyo", "新宿変電所"): [{"hv_kv": 275.0, "lv_kv": 66.0, "sn_mva": 300.0, "n_parallel": 3}]}
    led = sg.apply_implicit_stepdown(net, nameplates=plates)
    assert led[0]["capacity"] == "nameplate" and led[0]["sn_mva"] == 300.0 and led[0]["parallel"] == 3
    assert "@nameplate" in net.trafo.iloc[0]["name"]


def test_estimated_capacity_covers_attached_lines():
    """推定容量は取付線の熱容量合計以上(変圧器を偽の隘路にしない)・100MVA 刻み。"""
    net, hv, _lv, li = _mismatch_net()
    led = sg.apply_implicit_stepdown(net)
    line_mva = 3 ** 0.5 * 66.0 * float(net.line.at[li, "max_i_ka"])
    assert led[0]["sn_mva"] >= max(100.0, line_mva) and led[0]["sn_mva"] % 100 == 0


def _lv_island_net(dist_km):
    """電源つき 154kV 網と、変圧器の無い孤立 66kV 成分(負荷 30+20MW)。"""
    net = pp.create_empty_network()
    hv1 = _bus(net, 154.0, 35.00, 139.00, "上位A")
    hv2 = _bus(net, 154.0, 35.10, 139.00, "上位B")
    _line(net, hv1, hv2, 154.0, km=11.0)
    pp.create_ext_grid(net, bus=hv1)
    pp.create_load(net, bus=hv2, p_mw=100.0, q_mvar=20.0)
    dlon = dist_km / 91.0                     # 東へずらす(上位A/B は南北に並ぶ)
    a = _bus(net, 66.0, 35.00, 139.00 + dlon, "孤立a")
    b = _bus(net, 66.0, 35.005, 139.00 + dlon, "孤立b")
    _line(net, a, b, 66.0, km=0.6)
    pp.create_load(net, bus=a, p_mw=30.0, q_mvar=6.0)
    pp.create_load(net, bus=b, p_mw=20.0, q_mvar=4.0)
    pp.create_shunt(net, bus=b, q_mvar=-2.0)
    net.line["kv_class"] = [154.0, 66.0]
    return net, hv1, (a, b)


def test_lv_island_detected_and_aggregated_with_load_preserved():
    net, hv1, (a, b) = _lv_island_net(dist_km=2.0)
    isl = sg.lv_islands(net)
    assert len(isl) == 1 and isl[0]["load_mw"] == 50.0 and isl[0]["anchor_bus"] == hv1
    assert isl[0]["dist_km"] == pytest.approx(2.0, abs=0.3)
    total_before = float(net.load.p_mw.sum())
    led = sg.aggregate_lv_islands(net, r_max_km=5.0)
    assert led["n_aggregated"] == 1 and led["aggregated_mw"] == 50.0 and led["n_unserved"] == 0
    assert float(net.load.p_mw.sum()) == total_before                # 需要保存
    assert set(net.load.bus) == {hv1, 1}                              # 孤立側の負荷は上位Aへ
    assert not net.bus.at[a, "in_service"] and not net.bus.at[b, "in_service"]
    assert int(net.shunt.bus.iloc[0]) == hv1                          # shunt も移設
    assert not bool(net.line.at[1, "in_service"])
    pp.runpp(net)
    assert net.converged


def test_lv_island_beyond_radius_is_left_unserved_and_disclosed():
    net, hv1, (a, b) = _lv_island_net(dist_km=8.0)
    led = sg.aggregate_lv_islands(net, r_max_km=5.0)
    assert led["n_aggregated"] == 0 and led["n_unserved"] == 1 and led["unserved_mw"] == 50.0
    assert bool(net.bus.at[a, "in_service"]) and set(net.load.bus) == {1, a, b}


def test_islands_with_transformer_or_source_are_not_islands():
    net, hv1, (a, b) = _lv_island_net(dist_km=2.0)
    pp.create_transformer_from_parameters(net, hv_bus=hv1, lv_bus=a, sn_mva=100, vn_hv_kv=154,
                                          vn_lv_kv=66, vkr_percent=0.5, vk_percent=12,
                                          pfe_kw=0, i0_percent=0)
    assert sg.lv_islands(net) == []


def test_flags_off_leave_the_production_builder_unchanged():
    """フラグ OFF ではバス/線/変圧器数が従来と完全同一(kv_class 列が付くだけ)。"""
    from pathlib import Path
    import importlib.util
    import sys
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("pf_sd", root / "scripts" / "run_full_powerflow_from_db.py")
    pf = importlib.util.module_from_spec(spec)
    sys.modules["pf_sd"] = pf
    spec.loader.exec_module(pf)
    if not Path(pf.BUILT).exists():
        pytest.skip("built DB が無い")
    assert pf.IMPLICIT_STEPDOWN_DEFAULT is False or pf.IMPLICIT_STEPDOWN_DEFAULT is True
    with open(pf.BUILT, encoding="utf-8") as f:
        db = json.load(f)
    nodes, edges = db["nodes"], db["edges"]
    net0, _, st0 = pf.build_island_net("okinawa", nodes, edges, 60.0, {}, implicit_stepdown=False)
    net1, _, st1 = pf.build_island_net("okinawa", nodes, edges, 60.0, {}, implicit_stepdown=True)
    assert "kv_class" in net0.line.columns
    assert st0["n_implicit_stepdown"] == 0
    assert len(net1.bus) - len(net0.bus) == st1["n_implicit_stepdown"]
    assert len(net1.trafo) - len(net0.trafo) == st1["n_implicit_stepdown"]
    assert len(net1.line) == len(net0.line)
    assert sg.find_class_mismatch(net1) == []


def test_unknown_kv_junction_is_reclassed_not_transformed():
    """電圧不明ノード(仮置き 66kV)に 154kV 幹線が繋がる junction は降圧点ではない → 階級を置き直す。"""
    net = pp.create_empty_network()
    s0 = _bus(net, 154.0, 42.0, 140.0, "源")
    j = _bus(net, 66.0, 42.1, 140.0, "junction(kv不明)", typ="n")     # ビルダーの仮置き
    e = _bus(net, 154.0, 42.2, 140.0, "端")
    _line(net, s0, j, 154.0, km=11.0, name="幹線1")
    _line(net, j, e, 154.0, km=11.0, name="幹線2")
    net.line["kv_class"] = [154.0, 154.0]
    pp.create_ext_grid(net, bus=s0)
    pp.create_load(net, bus=e, p_mw=10.0)
    led = sg.apply_implicit_stepdown(net, unknown_kv_buses={j})
    assert led == [] and len(net.trafo) == 0
    assert float(net.bus.at[j, "vn_kv"]) == 154.0
    assert net._stepdown_reclass and net._stepdown_reclass[0]["mixed"] is False
    # 混在(154 と 66 が集まる不明ノード)は最上位へ置き直し、66kV 線は暗黙降圧へ
    lv = _bus(net, 66.0, 42.1, 140.05, "配電")
    li = _line(net, j, lv, 66.0, km=4.0, name="配電線")
    net.line.at[li, "kv_class"] = 66.0
    led = sg.apply_implicit_stepdown(net, unknown_kv_buses={j})
    assert len(led) == 1 and (led[0]["hv_kv"], led[0]["lv_kv"]) == (154.0, 66.0)
    assert sg.find_class_mismatch(net) == []
