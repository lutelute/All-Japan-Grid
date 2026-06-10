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
