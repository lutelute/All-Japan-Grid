"""Phase-5 power-flow physics: Q-limits, AVR setpoints, spatial loads.

Pins the three upgrades that retire the "infinite flat VAr source"
generator model:

- generators get a synchronous-machine reactive capability
  (max_q = 0.5 Pmax, min_q = -0.3 Pmax) and the AC solve enforces it
  (PV->PQ switching) on the first solver attempts;
- voltage setpoints follow an AVR-style class schedule instead of a
  flat 1.00 pu;
- load allocation can be tilted by branch degree (opt-in until external
  per-substation flow data validates it).
"""

import pandapower as pp
import pytest

pytest.importorskip("pandapower")

from src.powerflow.load_estimator import degree_factors, estimate_loads  # noqa: E402
from src.powerflow.transforms import apply_voltage_setpoints  # noqa: E402


def _two_class_net():
    net = pp.create_empty_network(f_hz=60)
    b500 = pp.create_bus(net, vn_kv=500.0)
    b154 = pp.create_bus(net, vn_kv=154.0)
    b66 = pp.create_bus(net, vn_kv=66.0)
    pp.create_line_from_parameters(net, b500, b154, 30.0, 0.028, 0.325, 12.0, 2.0)
    pp.create_line_from_parameters(net, b154, b66, 10.0, 0.05, 0.38, 9.0, 1.0)
    pp.create_gen(net, bus=b500, p_mw=100.0, vm_pu=1.0)
    pp.create_gen(net, bus=b66, p_mw=10.0, vm_pu=1.0)
    pp.create_ext_grid(net, bus=b154, vm_pu=1.0)
    return net, b500, b154, b66


def test_voltage_setpoints_follow_class_schedule():
    net, *_ = _two_class_net()
    n = apply_voltage_setpoints(net)
    assert n == 3                                  # 2 gens + 1 ext_grid
    assert net.gen.at[0, "vm_pu"] == pytest.approx(1.03)   # 500 kV
    assert net.gen.at[1, "vm_pu"] == pytest.approx(1.00)   # 66 kV
    assert net.ext_grid.at[0, "vm_pu"] == pytest.approx(1.01)  # 154 kV


def test_builder_assigns_reactive_capability():
    from src.converter.pandapower_builder import PandapowerBuilder
    from tests.conftest import make_generator, make_substation, make_transmission_line
    from src.model.grid_network import GridNetwork

    nw = GridNetwork(region="shikoku", frequency_hz=60)
    nw.add_substation(make_substation(id="s1"))
    nw.add_substation(make_substation(id="s2", name="B"))
    nw.add_transmission_line(make_transmission_line(
        id="l1", from_substation_id="s1", to_substation_id="s2"))
    nw.add_generator(make_generator(id="g1", capacity_mw=400.0,
                                    connected_bus_id="s1"))
    net = PandapowerBuilder().build(nw).net
    assert net.gen.at[0, "max_q_mvar"] == pytest.approx(200.0)   # 0.5 Pmax
    assert net.gen.at[0, "min_q_mvar"] == pytest.approx(-120.0)  # -0.3 Pmax


def test_ac_solve_enforces_q_limits():
    """A weak radial whose PV bus would need more VArs than the machine
    has: with enforcement the gen must sit AT its limit, not beyond."""
    net = pp.create_empty_network(f_hz=60)
    b1 = pp.create_bus(net, vn_kv=154.0)
    b2 = pp.create_bus(net, vn_kv=154.0)
    pp.create_ext_grid(net, bus=b1, vm_pu=1.0)
    pp.create_line_from_parameters(net, b1, b2, 80.0, 0.05, 0.38, 9.0, 1.0)
    pp.create_gen(net, bus=b2, p_mw=20.0, vm_pu=1.08,
                  max_q_mvar=15.0, min_q_mvar=-10.0)
    pp.create_load(net, bus=b2, p_mw=60.0, q_mvar=25.0)

    from src.powerflow.batch_solve import run_powerflow
    res = run_powerflow(net, "ac")
    assert res["converged"] is True
    assert res["q_lims_enforced"] is True
    assert float(net.res_gen.at[0, "q_mvar"]) <= 15.0 + 1e-6
    # at the limit the machine loses voltage control (PV -> PQ)
    assert float(net.res_bus.at[1, "vm_pu"]) < 1.08


def test_degree_factors_tilt_allocation():
    net, b500, b154, b66 = _two_class_net()
    f = degree_factors(net)
    assert f[b154] > f[b500]                       # degree 2 vs 1
    cfg = {"regional_peak_demand_mw": {"shikoku": 100.0},
           "load_factor": 1.0, "power_factor": 0.95,
           "voltage_weights": {500: 1.0, 154: 1.0, 66: 1.0}}
    total_flat = estimate_loads(net, "shikoku", demand_config=cfg)
    flat = net.load.set_index("bus")["p_mw"].to_dict()
    net.load.drop(net.load.index, inplace=True)
    total_deg = estimate_loads(net, "shikoku", demand_config=cfg, spatial="degree")
    deg = net.load.set_index("bus")["p_mw"].to_dict()
    assert total_flat == pytest.approx(total_deg) == pytest.approx(100.0)
    # equal voltage weights: flat is uniform, degree tilts to the hub
    assert flat[b154] == pytest.approx(flat[b500])
    assert deg[b154] > deg[b500]


def test_merit_order_dispatch_by_fuel():
    """LNG runs near its CF share; rooftop solar no longer crowds out
    baseload (the uniform-scaling distortion measured against TEPCO)."""
    import pandas as pd
    from src.powerflow.transforms import _dispatch_cf, balance_power

    net = pp.create_empty_network(f_hz=50)
    b = pp.create_bus(net, vn_kv=275.0)
    pp.create_ext_grid(net, bus=b, vm_pu=1.0)
    pp.create_load(net, bus=b, p_mw=1000.0, q_mvar=100.0)
    pp.create_gen(net, bus=b, p_mw=0.0, vm_pu=1.0, max_p_mw=2000.0, type="gas")
    pp.create_gen(net, bus=b, p_mw=0.0, vm_pu=1.0, max_p_mw=2000.0, type="solar")
    balance_power(net, {"reserve_margin": 0.05}, mode="proportional")
    p_gas = float(net.gen.at[0, "p_mw"])
    p_solar = float(net.gen.at[1, "p_mw"])
    assert p_gas + p_solar == pytest.approx(1050.0, rel=1e-6)
    # 0.55 vs 0.15 capacity factors -> gas carries ~78.6% of the dispatch
    assert p_gas / (p_gas + p_solar) == pytest.approx(0.55 / 0.70, rel=1e-6)
    # first-token rule: legacy oil plants with partial gas repowering
    # follow the oil factor (鹿島 over-dispatch fix, measured rho 0.657->0.691)
    assert _dispatch_cf("oil;gas") == 0.1
    assert _dispatch_cf("gas;coal") == 0.55
    assert _dispatch_cf(None) == 0.3


def test_balance_power_uniform_without_fuel_types():
    """Nets built without the type column keep the legacy uniform scaling."""
    net = pp.create_empty_network(f_hz=50)
    b = pp.create_bus(net, vn_kv=275.0)
    pp.create_ext_grid(net, bus=b, vm_pu=1.0)
    pp.create_load(net, bus=b, p_mw=1000.0, q_mvar=100.0)
    pp.create_gen(net, bus=b, p_mw=0.0, vm_pu=1.0, max_p_mw=1500.0)
    pp.create_gen(net, bus=b, p_mw=0.0, vm_pu=1.0, max_p_mw=1500.0)
    net.gen["type"] = None
    from src.powerflow.transforms import balance_power
    balance_power(net, {"reserve_margin": 0.05}, mode="proportional")
    assert float(net.gen.at[0, "p_mw"]) == pytest.approx(float(net.gen.at[1, "p_mw"]))
    assert float(net.gen["p_mw"].sum()) == pytest.approx(1050.0, rel=1e-6)


def test_junction_buses_receive_no_load():
    """Vertex-snap junctions are tap points, not delivery substations:
    the builder types them 'n' and load allocation skips them (measured:
    okinawa full-model vm 0.647 -> 0.923 once mid-span demand was gone)."""
    from src.converter.pandapower_builder import PandapowerBuilder
    from src.model.grid_network import GridNetwork
    from src.model.substation import Substation
    from src.model.transmission_line import TransmissionLine
    from tests.conftest import make_substation, make_transmission_line

    nw = GridNetwork(region="shikoku", frequency_hz=60)
    nw.add_substation(make_substation(id="s1"))
    nw.add_substation(make_substation(
        id="shikoku_jct_33.9:133.5", name="shikoku junction", voltage_kv=275.0))
    nw.add_transmission_line(make_transmission_line(
        id="l1", from_substation_id="s1",
        to_substation_id="shikoku_jct_33.9:133.5"))
    net = PandapowerBuilder().build(nw).net
    assert net.bus.at[0, "type"] == "b"
    assert net.bus.at[1, "type"] == "n"

    cfg = {"regional_peak_demand_mw": {"shikoku": 100.0}, "load_factor": 1.0,
           "power_factor": 0.95, "voltage_weights": {275: 1.0}}
    total = estimate_loads(net, "shikoku", demand_config=cfg)
    assert total == pytest.approx(100.0)
    loaded_types = net.load["bus"].map(net.bus["type"])
    assert (loaded_types == "b").all()      # all demand on real substations


def _measured_net():
    """3 named substations; 庚申塚 split across two voltage classes."""
    net = pp.create_empty_network(f_hz=50)
    pp.create_bus(net, vn_kv=154.0, name="庚申塚変電所 154kV", type="b")
    pp.create_bus(net, vn_kv=66.0, name="庚申塚変電所 66kV", type="b")
    pp.create_bus(net, vn_kv=66.0, name="角筈変電所 66kV", type="b")
    pp.create_bus(net, vn_kv=66.0, name="不在変電所 66kV", type="b")
    return net


def test_measured_loads_pin_buses_and_residual_fills_rest():
    """M3 placement: name-matched subs get the measured statistic as an
    absolute load on their LOWEST >=50 kV bus; the synthetic rule fills
    only the residual on the remaining buses; the regional total holds."""
    net = _measured_net()
    cfg = {"regional_peak_demand_mw": {"tokyo": 200.0}, "load_factor": 1.0,
           "power_factor": 0.95, "voltage_weights": {154: 0.3, 66: 0.5}}
    measured = {"庚申塚": {"q50": 46.0, "p95": 80.0},
                "角筈": {"q50": 38.0, "p95": 60.0},
                "別地域": {"q50": 999.0, "p95": 999.0}}   # no such bus
    total = estimate_loads(net, "tokyo", demand_config=cfg,
                           measured_bus_loads=measured)
    assert total == pytest.approx(200.0)

    by_name = {net.load.at[i, "name"]: net.load.loc[i]
               for i in net.load.index}
    pinned = by_name["measured_庚申塚"]
    assert float(pinned["p_mw"]) == pytest.approx(80.0)     # p95 default
    assert int(pinned["bus"]) == 1                          # 66 kV bus wins
    assert float(by_name["measured_角筈"]["p_mw"]) == pytest.approx(60.0)
    # residual 200-140=60 lands on the unmatched buses only
    synth = net.load[~net.load["name"].astype(str).str.startswith("measured_")]
    assert float(synth["p_mw"].sum()) == pytest.approx(60.0)
    assert 1 not in set(synth["bus"]) and 2 not in set(synth["bus"])


def test_radialize_band_opens_highest_impedance_loop_edge():
    """M5 experiment transform: a 66 kV triangle keeps its 2 lowest-
    impedance corridors (MST) and opens the heaviest one — parallel
    circuits on the opened corridor go out together; out-of-band loops
    are untouched; no bus is disconnected."""
    from src.powerflow.transforms import radialize_band

    net = pp.create_empty_network(f_hz=50)
    b = [pp.create_bus(net, vn_kv=66.0) for _ in range(3)]
    hv = [pp.create_bus(net, vn_kv=275.0) for _ in range(3)]
    pp.create_ext_grid(net, bus=b[0], vm_pu=1.0)

    def line(f, t, x, n=1, **kw):
        return pp.create_line_from_parameters(
            net, f, t, length_km=1.0, r_ohm_per_km=0.1, x_ohm_per_km=x,
            c_nf_per_km=0.0, max_i_ka=1.0, parallel=n, **kw)

    line(b[0], b[1], x=0.1)
    line(b[1], b[2], x=0.2)
    heavy1 = line(b[2], b[0], x=0.9)
    heavy2 = line(b[2], b[0], x=0.9)          # parallel circuit, same corridor
    hv_loop = [line(hv[0], hv[1], x=0.1), line(hv[1], hv[2], x=0.1),
               line(hv[2], hv[0], x=0.1)]      # 275 kV ring stays closed

    info = radialize_band(net, lo_kv=60.0, hi_kv=140.0)
    assert info["n_band_corridors"] == 3
    assert info["n_opened"] == 1 and info["n_lines_opened"] == 2
    assert not net.line.at[heavy1, "in_service"]
    assert not net.line.at[heavy2, "in_service"]
    assert all(net.line.at[i, "in_service"] for i in hv_loop)
    # connectivity preserved on the 66 kV layer
    import networkx as nx
    G = nx.Graph((int(net.line.at[i, "from_bus"]), int(net.line.at[i, "to_bus"]))
                 for i in net.line.index if net.line.at[i, "in_service"]
                 and net.bus.at[int(net.line.at[i, "from_bus"]), "vn_kv"] < 140)
    assert nx.is_connected(G.subgraph(b))


def test_measured_loads_capped_at_regional_target():
    net = _measured_net()
    cfg = {"regional_peak_demand_mw": {"tokyo": 100.0}, "load_factor": 1.0,
           "power_factor": 0.95, "voltage_weights": {154: 0.3, 66: 0.5}}
    measured = {"庚申塚": 90.0, "角筈": 110.0}    # bare-MW form, sum 200
    total = estimate_loads(net, "tokyo", demand_config=cfg,
                           measured_bus_loads=measured)
    assert total == pytest.approx(100.0)
    meas = net.load[net.load["name"].astype(str).str.startswith("measured_")]
    assert float(meas["p_mw"].sum()) == pytest.approx(100.0)  # scaled 0.5
    assert sorted(meas["p_mw"]) == pytest.approx([45.0, 55.0])


def test_balance_power_by_zone_scales_each_zone_to_its_own_load():
    """Island-wide scaling starves demand-heavy zones (the historical west
    failure mode); the per-zone variant dispatches each zone's fleet to its
    own load + reserve, clipping at nameplate."""
    from src.powerflow.transforms import balance_power_by_zone

    net = pp.create_empty_network(f_hz=60)
    a = pp.create_bus(net, vn_kv=275.0)
    b = pp.create_bus(net, vn_kv=275.0)
    net.bus.loc[a, "zone"] = "kansai"
    net.bus.loc[b, "zone"] = "chugoku"
    pp.create_ext_grid(net, bus=a, vm_pu=1.0)
    pp.create_line_from_parameters(net, a, b, 50.0, 0.028, 0.325, 12.0, 2.0)
    pp.create_load(net, bus=a, p_mw=1000.0, q_mvar=100.0)   # kansai heavy
    pp.create_load(net, bus=b, p_mw=100.0, q_mvar=10.0)
    pp.create_gen(net, bus=a, p_mw=0.0, vm_pu=1.0, max_p_mw=800.0, type="gas")
    pp.create_gen(net, bus=b, p_mw=0.0, vm_pu=1.0, max_p_mw=2000.0, type="gas")
    balance_power_by_zone(net, {"reserve_margin": 0.05})
    # kansai target 1050 exceeds its nameplate -> clipped at 800 (honest
    # deficit, served over the tie), NOT padded from chugoku's fleet
    assert float(net.gen.at[0, "p_mw"]) == pytest.approx(800.0)
    # chugoku covers exactly its own load + reserve
    assert float(net.gen.at[1, "p_mw"]) == pytest.approx(105.0)


def test_stack_dispatch_fills_merit_order_to_nameplate():
    """The default stack mode: must-run renewables at CF, then thermal
    units fill to NAMEPLATE cheapest-first; the marginal unit is partial.
    (This is the fix for the uniform-59%-LNG distortion — measured
    interior rho 0.659 -> 0.721, magnitude ratio 0.65 -> 0.79.)"""
    from src.powerflow.transforms import balance_power

    net = pp.create_empty_network(f_hz=50)
    b = pp.create_bus(net, vn_kv=275.0)
    pp.create_ext_grid(net, bus=b, vm_pu=1.0)
    pp.create_load(net, bus=b, p_mw=2000.0, q_mvar=200.0)
    pp.create_gen(net, bus=b, p_mw=0.0, vm_pu=1.0, max_p_mw=1000.0, type="solar")
    pp.create_gen(net, bus=b, p_mw=0.0, vm_pu=1.0, max_p_mw=1000.0, type="coal")
    pp.create_gen(net, bus=b, p_mw=0.0, vm_pu=1.0, max_p_mw=2000.0, type="gas")
    pp.create_gen(net, bus=b, p_mw=0.0, vm_pu=1.0, max_p_mw=1000.0, type="oil")
    balance_power(net, {"reserve_margin": 0.05})        # stack is default
    # target 2100: solar must-run 150 (CF .15), coal fills 1000,
    # gas (next merit) covers 950 partial, oil stays cold
    assert float(net.gen.at[0, "p_mw"]) == pytest.approx(150.0)
    assert float(net.gen.at[1, "p_mw"]) == pytest.approx(1000.0)
    assert float(net.gen.at[2, "p_mw"]) == pytest.approx(950.0)
    assert float(net.gen.at[3, "p_mw"]) == pytest.approx(0.0)


def test_demand_config_from_occto(tmp_path):
    """Measured-demand option: regional targets become OCCTO area stats
    (actual MW, load_factor forced to 1.0), provenance recorded."""
    import json
    from src.powerflow.load_estimator import demand_config_from_occto

    stats = {"area_demand_mw": {
        a: {"median": 1000.0 + i, "p95": 2000.0 + i}
        for i, a in enumerate(["北海道", "東北", "東京", "中部", "北陸",
                               "関西", "中国", "四国", "九州", "沖縄"])}}
    p = tmp_path / "occto.json"
    p.write_text(json.dumps(stats), encoding="utf-8")
    cfg = demand_config_from_occto(str(p), quantile="p95")
    assert cfg["load_factor"] == 1.0
    assert cfg["regional_peak_demand_mw"]["tokyo"] == 2002.0
    assert cfg["regional_peak_demand_mw"]["okinawa"] == 2009.0
    assert "occto:p95" in cfg["_demand_source"]
