"""zone_extract — 島のネットから電力会社エリアを切り出す(合成の 2 エリア網)."""
import pytest

pp = pytest.importorskip("pandapower")

from src.powerflow.zone_extract import extract_zone  # noqa: E402


@pytest.fixture()
def net():
    """A(3 バス・スラックあり)— B(2 バス)を 2 本で連系。A ラベルの孤立片 1 バスが B にだけ繋がる。"""
    n = pp.create_empty_network()
    a = [pp.create_bus(n, 154.0, zone="A") for _ in range(3)]
    b = [pp.create_bus(n, 154.0, zone="B") for _ in range(2)]
    islet = pp.create_bus(n, 154.0, zone="A")
    ln = dict(r_ohm_per_km=0.05, x_ohm_per_km=0.4, c_nf_per_km=9.0, max_i_ka=1.0)
    for f, t in ((a[0], a[1]), (a[1], a[2]), (a[0], a[2]), (b[0], b[1]),
                 (a[2], b[0]), (a[1], b[1]), (b[1], islet)):
        pp.create_line_from_parameters(n, f, t, length_km=20.0, **ln)
    pp.create_ext_grid(n, a[0], vm_pu=1.01)
    pp.create_gen(n, b[0], p_mw=150.0, vm_pu=1.0, max_p_mw=300.0)
    pp.create_gen(n, a[2], p_mw=40.0, vm_pu=1.0, max_p_mw=80.0)
    for bus, p in ((a[1], 60.0), (b[1], 90.0), (islet, 10.0), (a[2], 30.0)):
        pp.create_load(n, bus, p_mw=p, q_mvar=0.2 * p)
    pp.runpp(n, calculate_voltage_angles=True)
    return n


def _reproduces(sub, net):
    pp.runpp(sub, calculate_voltage_angles=True)
    b = sub.res_bus.index
    assert (sub.res_bus.vm_pu - net.res_bus.vm_pu[b]).abs().max() < 1e-6
    assert (sub.res_bus.va_degree - net.res_bus.va_degree[b]).abs().max() < 1e-4


def test_zone_with_island_slack(net):
    sub, bd, info = extract_zone(net, "A")
    assert info["n_bus"] == 3 and info["n_fragments"] == 1 and info["fragment_buses"] == 1
    assert len(bd) == 2 and set(bd.neighbor_zone) == {"B"} and info["added_slack_bus"] is None
    # 境界の潮流は内側の端の、エリアから出る向き(元の解の値そのもの)
    for x in bd.itertuples():
        r = net.res_line.loc[x.index]
        assert x.p_out_mw == pytest.approx(
            r.p_from_mw if net.line.at[x.index, "from_bus"] == x.inner_bus else r.p_to_mw)
    assert (sub.gen.type == "boundary").sum() == 2
    _reproduces(sub, net)


def test_zone_without_slack_gets_one(net):
    sub, bd, info = extract_zone(net, "B")
    assert info["n_bus"] == 2 and len(bd) == 3  # A へ 2 本 + 孤立片へ 1 本
    assert info["added_slack_bus"] == int(net.gen.bus[0])
    _reproduces(sub, net)


def test_unknown_zone_raises(net):
    with pytest.raises(ValueError):
        extract_zone(net, "C")


def test_trafo_boundary_inner_lv():
    """境界が変圧器で、内側が lv 側: p_out は p_lv_mw、容量は sn_mva × parallel。"""
    n = pp.create_empty_network()
    hv = pp.create_bus(n, 275.0, zone="H")
    lv = pp.create_bus(n, 154.0, zone="L")
    lv2 = pp.create_bus(n, 154.0, zone="L")
    pp.create_ext_grid(n, hv)
    t = pp.create_transformer_from_parameters(
        n, hv, lv, sn_mva=300.0, vn_hv_kv=275.0, vn_lv_kv=154.0, vkr_percent=0.3,
        vk_percent=12.0, pfe_kw=0.0, i0_percent=0.0, parallel=2)
    pp.create_line_from_parameters(n, lv, lv2, length_km=10.0, r_ohm_per_km=0.05,
                                   x_ohm_per_km=0.4, c_nf_per_km=9.0, max_i_ka=1.0)
    pp.create_gen(n, lv2, p_mw=20.0, vm_pu=1.0)
    pp.create_load(n, lv2, p_mw=120.0, q_mvar=20.0)
    pp.runpp(n, calculate_voltage_angles=True)
    sub, bd, _ = extract_zone(n, "L")
    x = bd.iloc[0]
    assert len(bd) == 1 and x.kind == "trafo" and x.inner_bus == lv
    assert x.p_out_mw == pytest.approx(n.res_trafo.at[t, "p_lv_mw"]) and x.p_out_mw < 0
    assert x.rate_mva == pytest.approx(600.0)
    _reproduces(sub, n)


def test_zone_that_is_the_whole_island_has_no_boundary(net):
    """エリア = 島全体(北海道・沖縄)なら境界は 0 本。数の列は数のままで、隣接エリア別の集計も落ちない。"""
    net.bus["zone"] = "A"
    sub, bd, info = extract_zone(net, "A")
    assert len(bd) == 0 and info["n_boundary"] == 0 and info["boundary_net_out_mw"] == 0.0
    assert bd["p_out_mw"].dtype == float and bd["inner_bus"].dtype == int
    assert bd.groupby("neighbor_zone")["p_out_mw"].sum().round(1).to_dict() == {}
    _reproduces(sub, net)
