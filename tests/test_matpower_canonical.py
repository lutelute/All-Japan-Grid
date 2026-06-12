"""canonical_mpc + .mat round-trip — the MATPOWER-spec conversion contract.

A small meshed 3-bus net is converted with pandapower's ``to_mpc``,
reduced to the canonical MATPOWER case v2 struct, written with
``scipy.io.savemat``, read back with ``from_mpc`` and re-solved: the
round-tripped AC solution must match the original to numerical
tolerance. That property — not the mere existence of a file — is what
makes the export a faithful MATPOWER case rather than a table dump.
"""

import numpy as np
import pandapower as pp
import pytest
from pandapower.converter.matpower import from_mpc, to_mpc
from scipy.io import loadmat, savemat

from src.converter.matpower_exporter import canonical_mpc


@pytest.fixture()
def solved_net():
    """Meshed 3-bus / 2-gen / 2-load net with AC results."""
    net = pp.create_empty_network(sn_mva=100.0)
    b0 = pp.create_bus(net, vn_kv=110.0)
    b1 = pp.create_bus(net, vn_kv=110.0)
    b2 = pp.create_bus(net, vn_kv=110.0)
    pp.create_ext_grid(net, b0, vm_pu=1.02)
    for f, t, km in ((b0, b1, 30.0), (b1, b2, 20.0), (b0, b2, 40.0)):
        pp.create_line_from_parameters(
            net, f, t, length_km=km, r_ohm_per_km=0.06,
            x_ohm_per_km=0.30, c_nf_per_km=10.0, max_i_ka=0.6)
    pp.create_load(net, b1, p_mw=40.0, q_mvar=10.0)
    pp.create_load(net, b2, p_mw=25.0, q_mvar=5.0)
    pp.create_gen(net, b2, p_mw=30.0, vm_pu=1.01)
    pp.runpp(net)
    return net


class TestCanonicalMpc:
    def test_fields_and_widths(self, solved_net):
        inner = canonical_mpc(to_mpc(solved_net, mode="pf"))["mpc"]
        assert set(inner) == {"baseMVA", "version", "bus", "branch", "gen"}
        assert inner["baseMVA"] == 100.0
        assert inner["version"] == "2"
        assert inner["bus"].shape == (3, 13)
        assert inner["branch"].shape == (3, 13)
        assert inner["gen"].shape == (2, 21)  # ext_grid + gen

    def test_bus_numbering_one_based_contiguous(self, solved_net):
        inner = canonical_mpc(to_mpc(solved_net, mode="pf"))["mpc"]
        bus_i = inner["bus"][:, 0]
        assert bus_i.min() == 1.0
        assert np.array_equal(np.sort(bus_i), np.arange(1, len(bus_i) + 1))
        assert inner["branch"][:, :2].min() >= 1.0
        assert inner["gen"][:, 0].min() >= 1.0

    def test_exactly_one_ref_bus(self, solved_net):
        inner = canonical_mpc(to_mpc(solved_net, mode="pf"))["mpc"]
        assert int((inner["bus"][:, 1] == 3).sum()) == 1

    def test_solved_state_embedded(self, solved_net):
        """init='results' embeds the AC solution into VM/VA columns."""
        inner = canonical_mpc(to_mpc(solved_net, mode="pf"))["mpc"]
        np.testing.assert_allclose(
            inner["bus"][:, 7], solved_net.res_bus.vm_pu.values, atol=1e-8)
        np.testing.assert_allclose(
            inner["bus"][:, 8], solved_net.res_bus.va_degree.values,
            atol=1e-6)

    def test_accepts_wrapped_and_inner_dict(self, solved_net):
        wrapped = to_mpc(solved_net, mode="pf")
        a = canonical_mpc(wrapped)["mpc"]
        b = canonical_mpc(wrapped["mpc"])["mpc"]
        np.testing.assert_array_equal(a["bus"], b["bus"])

    def test_real_valued(self, solved_net):
        inner = canonical_mpc(to_mpc(solved_net, mode="pf"))["mpc"]
        for k in ("bus", "branch", "gen"):
            assert not np.iscomplexobj(inner[k])
            assert np.isfinite(inner[k]).all()


class TestMatRoundtrip:
    def test_savemat_struct_is_loadcase_shaped(self, solved_net, tmp_path):
        path = str(tmp_path / "case3.mat")
        savemat(path, canonical_mpc(to_mpc(solved_net, mode="pf")),
                do_compression=True)
        m = loadmat(path, squeeze_me=True, struct_as_record=False)
        assert "mpc" in m
        fields = set(m["mpc"]._fieldnames)
        assert fields == {"baseMVA", "version", "bus", "branch", "gen"}
        assert float(np.squeeze(m["mpc"].baseMVA)) == 100.0

    def test_roundtrip_resolves_to_same_state(self, solved_net, tmp_path):
        path = str(tmp_path / "case3.mat")
        savemat(path, canonical_mpc(to_mpc(solved_net, mode="pf")),
                do_compression=True)
        net2 = from_mpc(path, f_hz=50, casename_mpc_file="mpc")
        pp.runpp(net2)
        # from_mpc creates buses in mpc row order = original bus order
        np.testing.assert_allclose(net2.res_bus.vm_pu.values,
                                   solved_net.res_bus.vm_pu.values,
                                   atol=1e-6)
        np.testing.assert_allclose(net2.res_bus.va_degree.values,
                                   solved_net.res_bus.va_degree.values,
                                   atol=1e-4)
