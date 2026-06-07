"""Round-trip regression tests for the Level-2 CGMES export.

Guards the P0 defects fixed in Phase B (REVIEW_FINDINGS / commit log):

- #1 parallel circuits & transformer banks must survive the export
  (effective impedance, not per-circuit values),
- #2 in_service flags must propagate (ACDCTerminal.connected), so the
  round-trip never re-energizes pruned lines or disabled loads,
- #8 Conductor.length is km (the old metres value came back 1000x),
- #3 generation rebalancing after demand scaling keeps the SSH
  physically balanced.

The core assertion is electrical identity: ``runpp`` on the cim2pp
round-trip of a synthetic network reproduces the original bus voltages.
"""

import pytest

pp = pytest.importorskip("pandapower")

from src.cim.boundary import generate_boundary  # noqa: E402
from src.cim.level2 import net_to_cgmes  # noqa: E402


def _build_reference_net():
    """Synthetic net containing every fixed failure mode."""
    net = pp.create_empty_network(sn_mva=100.0, f_hz=60.0)
    b1 = pp.create_bus(net, vn_kv=110.0, name="b1")
    b2 = pp.create_bus(net, vn_kv=110.0, name="b2")
    b3 = pp.create_bus(net, vn_kv=110.0, name="b3")
    b4 = pp.create_bus(net, vn_kv=20.0, name="b4")
    pp.create_ext_grid(net, b1, vm_pu=1.02, name="slack")
    # double-circuit line (P0 #1)
    pp.create_line_from_parameters(
        net, b1, b2, length_km=50.0, r_ohm_per_km=0.06, x_ohm_per_km=0.4,
        c_nf_per_km=11.0, max_i_ka=1.0, parallel=2, name="l12")
    pp.create_line_from_parameters(
        net, b2, b3, length_km=30.0, r_ohm_per_km=0.06, x_ohm_per_km=0.4,
        c_nf_per_km=11.0, max_i_ka=1.0, name="l23")
    # out-of-service line that must NOT re-energize (P0 #2)
    pp.create_line_from_parameters(
        net, b1, b3, length_km=40.0, r_ohm_per_km=0.06, x_ohm_per_km=0.4,
        c_nf_per_km=11.0, max_i_ka=1.0, in_service=False, name="l13_off")
    # 3-bank parallel transformer (P0 #1)
    pp.create_transformer_from_parameters(
        net, b3, b4, sn_mva=40.0, vn_hv_kv=110.0, vn_lv_kv=20.0,
        vk_percent=10.0, vkr_percent=0.5, pfe_kw=30.0, i0_percent=0.1,
        parallel=3, name="t34")
    pp.create_load(net, b4, p_mw=30.0, q_mvar=10.0, name="ld4")
    # poison load: 999 MW, disabled — must stay disconnected (P0 #2)
    pp.create_load(net, b2, p_mw=999.0, q_mvar=300.0, in_service=False,
                   name="poison")
    pp.create_gen(net, b3, p_mw=20.0, vm_pu=1.01, max_p_mw=50.0,
                  min_p_mw=0.0, name="g3")
    pp.runpp(net)
    return net


def _roundtrip(net, out_dir, region="okinawa"):
    """Export ``net`` as CGMES and import it back via cim2pp."""
    from pandapower.converter.cim.cim2pp.from_cim import from_cim

    summary = net_to_cgmes(net, region, out_dir, f_hz=60.0)
    generate_boundary(out_dir, summary["base_voltages"])
    files = [f"{out_dir}/{region}_L2_{p}.xml"
             for p in ["EQ", "TP", "SSH", "SV", "GL"]]
    files += [f"{out_dir}/AllJapan_EQ_BD.xml", f"{out_dir}/AllJapan_TP_BD.xml"]
    return from_cim(file_list=files)


@pytest.fixture(scope="module")
def nets(tmp_path_factory):
    """(original solved net, solved round-trip net) — built once."""
    net = _build_reference_net()
    net2 = _roundtrip(net, str(tmp_path_factory.mktemp("cgmes")))
    pp.runpp(net2)
    return net, net2


def _by_name(net, table):
    df = getattr(net, table)
    return {str(df.at[i, "name"]): i for i in df.index}


def _bus_map(net, net2):
    """original bus index -> round-trip bus index.

    cim2pp does not carry TopologicalNode names onto buses, but line and
    transformer names survive, so the mapping is recovered through their
    endpoints (terminal sequence 1/2 -> from/to and hv/lv).
    """
    mapping = {}
    lines2 = _by_name(net2, "line")
    for i in net.line.index:
        j = lines2[str(net.line.at[i, "name"])]
        mapping[int(net.line.at[i, "from_bus"])] = int(net2.line.at[j, "from_bus"])
        mapping[int(net.line.at[i, "to_bus"])] = int(net2.line.at[j, "to_bus"])
    trafos2 = _by_name(net2, "trafo")
    for i in net.trafo.index:
        j = trafos2[str(net.trafo.at[i, "name"])]
        mapping[int(net.trafo.at[i, "hv_bus"])] = int(net2.trafo.at[j, "hv_bus"])
        mapping[int(net.trafo.at[i, "lv_bus"])] = int(net2.trafo.at[j, "lv_bus"])
    return mapping


class TestElectricalIdentity:
    def test_bus_voltages_match(self, nets):
        net, net2 = nets
        mapping = _bus_map(net, net2)
        assert len(mapping) == len(net.bus), "round-trip lost buses"
        for i, j in mapping.items():
            vm1 = float(net.res_bus.at[i, "vm_pu"])
            vm2 = float(net2.res_bus.at[j, "vm_pu"])
            assert abs(vm1 - vm2) < 1e-4, f"bus{i}: {vm1} != {vm2}"

    def test_bus_angles_match(self, nets):
        net, net2 = nets
        mapping = _bus_map(net, net2)
        for i, j in mapping.items():
            a1 = float(net.res_bus.at[i, "va_degree"])
            a2 = float(net2.res_bus.at[j, "va_degree"])
            assert abs(a1 - a2) < 1e-3, f"bus{i}: {a1} != {a2}"


class TestParallelPreserved:
    def test_line_effective_impedance(self, nets):
        """P0 #1: parallel=2 line must come back with half the per-circuit Z."""
        net, net2 = nets
        row = net2.line[net2.line.name == "l12"].iloc[0]
        eff_r = (float(row.r_ohm_per_km) * float(row.length_km)
                 / max(int(row.get("parallel", 1)), 1))
        assert abs(eff_r - 0.06 * 50.0 / 2) < 1e-4  # 1.5 ohm effective

    def test_trafo_bank_rating_and_vk(self, nets):
        """P0 #1: 3x40 MVA bank -> 120 MVA combined, vk unchanged."""
        net, net2 = nets
        row = net2.trafo.iloc[0]
        par = max(int(row.get("parallel", 1)), 1)
        assert abs(float(row.sn_mva) * par - 120.0) < 0.5
        assert abs(float(row.vk_percent) - 10.0) < 0.2


class TestInServicePreserved:
    def test_open_line_stays_open(self, nets):
        """P0 #2: the in_service=False line must not re-energize."""
        net, net2 = nets
        row = net2.line[net2.line.name == "l13_off"]
        assert len(row) == 1
        assert not bool(row.iloc[0].in_service)

    def test_poison_load_stays_off(self, nets):
        """P0 #2: the disabled 999 MW load must not contribute demand."""
        net, net2 = nets
        active = net2.load[net2.load.in_service]
        assert abs(float(active.p_mw.sum()) - 30.0) < 1e-3


class TestLengthUnits:
    def test_length_km_roundtrip(self, nets):
        """P0 #8: 50 km must come back as 50 km, not 50,000."""
        net, net2 = nets
        row = net2.line[net2.line.name == "l12"].iloc[0]
        assert abs(float(row.length_km) - 50.0) < 0.01


class TestRebalanceGeneration:
    def test_dispatch_follows_scaled_demand(self):
        """P0 #3: after load scaling, gen+sgen total = load * 1.05."""
        from scripts.export_cim_level2 import _rebalance_generation

        net = pp.create_empty_network(sn_mva=100.0)
        b1 = pp.create_bus(net, vn_kv=110.0)
        b2 = pp.create_bus(net, vn_kv=110.0)
        pp.create_ext_grid(net, b1)
        pp.create_line_from_parameters(
            net, b1, b2, length_km=10.0, r_ohm_per_km=0.06,
            x_ohm_per_km=0.4, c_nf_per_km=11.0, max_i_ka=1.0)
        pp.create_load(net, b2, p_mw=100.0, q_mvar=30.0)
        pp.create_gen(net, b2, p_mw=300.0, vm_pu=1.0)
        pp.create_sgen(net, b2, p_mw=60.0)
        # scale demand to 30% then rebalance
        net.load["p_mw"] *= 0.3
        net.load["q_mvar"] *= 0.3
        _rebalance_generation(net)
        total_gen = float(net.gen.p_mw.sum() + net.sgen.p_mw.sum())
        assert abs(total_gen - 30.0 * 1.05) < 1e-6
