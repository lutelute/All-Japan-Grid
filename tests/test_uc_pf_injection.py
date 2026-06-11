"""Tests for src/uc/pf_injection — UC→潮流ディスパッチ注入。

容量比例配分・容量クリップ・燃料不一致・コミットメントOFF反映（zeroed）・
slack除外・負荷スケールを小さなpandapowerネットで検証する。
"""

import pandapower as pp
import pytest

from src.uc.pf_injection import (
    inject_dispatch,
    inject_dispatch_by_zone,
    normalize_fuel,
    scale_loads_to,
    uc_snapshot,
)


def _mini_net():
    net = pp.create_empty_network()
    b1 = pp.create_bus(net, vn_kv=154.0)
    b2 = pp.create_bus(net, vn_kv=154.0)
    pp.create_line_from_parameters(net, b1, b2, length_km=10,
                                   r_ohm_per_km=0.1, x_ohm_per_km=0.4,
                                   c_nf_per_km=10, max_i_ka=1.0)
    pp.create_load(net, b2, p_mw=300.0, q_mvar=30.0)
    # slack: ext_grid相当のgen（slack=True）
    pp.create_gen(net, b1, p_mw=0.0, vm_pu=1.0, slack=True, name="slack",
                  type="lng", max_p_mw=1000.0, min_p_mw=0.0)
    pp.create_gen(net, b1, p_mw=100.0, vm_pu=1.0, name="coalA",
                  type="coal", max_p_mw=300.0, min_p_mw=0.0)
    pp.create_gen(net, b2, p_mw=50.0, vm_pu=1.0, name="coalB",
                  type="coal", max_p_mw=100.0, min_p_mw=0.0)
    pp.create_gen(net, b2, p_mw=80.0, vm_pu=1.0, name="gasC",
                  type="gas", max_p_mw=200.0, min_p_mw=0.0)
    return net


class TestNormalizeFuel:
    def test_pf_gas_meets_uc_lng(self):
        # PF側 'gas' と UC側 'lng' が同じ正規形に揃う
        assert normalize_fuel("gas") == normalize_fuel("lng") == "lng"
        assert normalize_fuel(None) == "unknown"


class TestInjectDispatch:
    def test_capacity_proportional_allocation(self):
        net = _mini_net()
        rep = inject_dispatch(net, {"coal": 200.0})
        # coalA:coalB = 300:100 → 150/50
        assert net.gen.at[1, "p_mw"] == pytest.approx(150.0)
        assert net.gen.at[2, "p_mw"] == pytest.approx(50.0)
        # lng は UC断面に無い → 稼働していた gasC は 0（コミットメントOFF）
        assert net.gen.at[3, "p_mw"] == pytest.approx(0.0)
        assert rep["zeroed_gens"] == 1
        # slack は不変
        assert net.gen.at[0, "p_mw"] == pytest.approx(0.0)
        assert rep["injected_mw"] == pytest.approx(200.0)

    def test_clip_and_unmatched(self):
        net = _mini_net()
        rep = inject_dispatch(net, {"coal": 999.0, "nuclear": 50.0})
        # coal容量400でクリップ
        assert rep["clipped"]["coal"] == pytest.approx(599.0)
        assert net.gen.at[1, "p_mw"] + net.gen.at[2, "p_mw"] == pytest.approx(400.0)
        # nuclear はPF側に存在しない
        assert rep["unmatched"]["nuclear"] == pytest.approx(50.0)

    def test_uc_lng_reaches_pf_gas(self):
        net = _mini_net()
        inject_dispatch(net, {"lng": 100.0})
        assert net.gen.at[3, "p_mw"] == pytest.approx(100.0)


class TestUcSnapshot:
    def test_region_filter_and_negative_clip(self):
        from src.model.generator import Generator
        from src.uc.models import GeneratorSchedule, UCResult
        gens = [
            Generator(id="t1", name="t1", capacity_mw=100, fuel_type="lng",
                      region="tokyo", fuel_cost_per_mwh=1),
            Generator(id="k1", name="k1", capacity_mw=100, fuel_type="coal",
                      region="kansai", fuel_cost_per_mwh=1),
        ]
        uc = UCResult(status="Optimal", schedules=[
            GeneratorSchedule(generator_id="t1", commitment=[1, 1],
                              power_output_mw=[80.0, -20.0]),
            GeneratorSchedule(generator_id="k1", commitment=[1, 1],
                              power_output_mw=[60.0, 60.0]),
        ])
        snap = uc_snapshot(uc, gens, 0, region="tokyo")
        assert snap == {"lng": 80.0}
        # 負値（充電）は計上しない
        assert uc_snapshot(uc, gens, 1, region="tokyo") == {}


class TestScaleLoads:
    def test_scales_p_and_q(self):
        net = _mini_net()
        ratio = scale_loads_to(net, 600.0)
        assert ratio == pytest.approx(2.0)
        assert net.load.at[0, "p_mw"] == pytest.approx(600.0)
        assert net.load.at[0, "q_mvar"] == pytest.approx(60.0)


def _two_zone_net():
    """bus 'zone' 付きの2地域島ネット（build_island_networks の縮小模型）。"""
    net = pp.create_empty_network()
    b1 = pp.create_bus(net, vn_kv=154.0, zone="tohoku")
    b2 = pp.create_bus(net, vn_kv=154.0, zone="tokyo")
    pp.create_line_from_parameters(net, b1, b2, length_km=10,
                                   r_ohm_per_km=0.1, x_ohm_per_km=0.4,
                                   c_nf_per_km=10, max_i_ka=1.0)
    pp.create_load(net, b1, p_mw=100.0, q_mvar=10.0)   # tohoku
    pp.create_load(net, b2, p_mw=400.0, q_mvar=40.0)   # tokyo
    pp.create_gen(net, b1, p_mw=0.0, vm_pu=1.0, slack=True, name="slack",
                  type="lng", max_p_mw=1000.0, min_p_mw=0.0)
    pp.create_gen(net, b1, p_mw=50.0, vm_pu=1.0, name="tohoku_coal",
                  type="coal", max_p_mw=200.0, min_p_mw=0.0)
    pp.create_gen(net, b2, p_mw=50.0, vm_pu=1.0, name="tokyo_coal",
                  type="coal", max_p_mw=300.0, min_p_mw=0.0)
    pp.create_gen(net, b2, p_mw=80.0, vm_pu=1.0, name="tokyo_gas",
                  type="gas", max_p_mw=500.0, min_p_mw=0.0)
    return net


class TestInjectByZone:
    def test_zone_isolation(self):
        net = _two_zone_net()
        reports = inject_dispatch_by_zone(
            net,
            {"tohoku": {"coal": 100.0}, "tokyo": {"lng": 250.0}},
            {"tohoku": 150.0, "tokyo": 600.0},
        )
        # tohoku: coal 100 はtohoku機のみへ（tokyo_coalは対象外のまま0化対象でもない）
        assert net.gen.at[1, "p_mw"] == pytest.approx(100.0)
        # tokyo: lng 250 が tokyo_gas へ、tokyo断面にcoalが無い→tokyo_coalは0化
        assert net.gen.at[3, "p_mw"] == pytest.approx(250.0)
        assert net.gen.at[2, "p_mw"] == pytest.approx(0.0)
        assert reports["tokyo"]["injection"]["zeroed_gens"] == 1
        # load はゾーン別スケール: tohoku 100→150 (×1.5), tokyo 400→600 (×1.5)
        assert net.load.at[0, "p_mw"] == pytest.approx(150.0)
        assert net.load.at[1, "p_mw"] == pytest.approx(600.0)
        # slack は不変
        assert net.gen.at[0, "p_mw"] == pytest.approx(0.0)

    def test_requires_zone_column(self):
        net = _mini_net()  # zone列なし
        with pytest.raises(ValueError, match="zone"):
            inject_dispatch_by_zone(net, {"tokyo": {}}, {"tokyo": 0.0})
