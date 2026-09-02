"""テブナン短絡容量と SCR 連系可能量(トラックC②・`src/powerflow/short_circuit.py`)のゲート。

1. 2 バス系で解析解と一致(S_sc = base·V²/|Z_th|、x_sys = xd''·base/S)
2. 単位ゲート: baseMVA を変えても MVA の答えは変わらない(機械ベース→系統ベース換算)
3. pandapower.shortcircuit.calc_sc(IEC 60909, c=1.1)との突合 — ext_grid 等価化で厳密一致
4. 既設 IBR の控除と SCR_min の意味(P_max_scr = S_sc/SCR_min − 既設)
5. CLI が JSON を書く(built が無ければ skip・沖縄 94 バスで数秒)
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

pp = pytest.importorskip("pandapower")


def _two_bus(base_mva=100.0, s_gen=100.0, x_line_pu=0.1, ibr_mw=0.0):
    """bus0 に同期機(型式不明 ≥2MW → xd''=0.25 機械ベース)、bus1 まで x=10Ω(=0.1pu@100MVA)の線。"""
    net = pp.create_empty_network(sn_mva=base_mva)
    b0 = pp.create_bus(net, vn_kv=100.0)
    b1 = pp.create_bus(net, vn_kv=100.0)
    pp.create_gen(net, b0, p_mw=0.8 * s_gen, max_p_mw=s_gen, vm_pu=1.0)
    # 線は**物理量(Ω)で固定**する: 0.1pu@100MVA・100kV = 10Ω。base を変えても同じ線
    pp.create_line_from_parameters(net, b0, b1, length_km=1.0, r_ohm_per_km=0.0,
                                   x_ohm_per_km=x_line_pu * 100.0, c_nf_per_km=0.0, max_i_ka=1.0)
    if ibr_mw > 0:
        pp.create_gen(net, b1, p_mw=ibr_mw, max_p_mw=ibr_mw, vm_pu=1.0, type="solar")
    pp.create_ext_grid(net, b0)                              # slack(既定では電流源にしない)
    return net, b0, b1


def test_two_bus_matches_analytic_solution():
    from src.powerflow.short_circuit import short_circuit_mva
    net, b0, b1 = _two_bus()
    r = short_circuit_mva(net)
    # x_sys = 0.25·100/100 = 0.25 pu → S_sc(b0)=100/0.25=400, S_sc(b1)=100/0.35
    assert r.s_sc_mva[r.bus_row_of_label[b0]] == pytest.approx(400.0, rel=1e-9)
    assert r.s_sc_mva[r.bus_row_of_label[b1]] == pytest.approx(100.0 / 0.35, rel=1e-9)
    assert r.n_source == 1 and r.source_mva == pytest.approx(100.0)


def test_unit_gate_base_mva_does_not_change_mva_answer():
    """機械ベース→系統ベース換算の単位ゲート: base を 10 倍にしても MVA は同じ。"""
    from src.powerflow.short_circuit import short_circuit_mva
    a, b0, b1 = _two_bus(base_mva=100.0)
    b, c0, c1 = _two_bus(base_mva=1000.0)
    ra, rb = short_circuit_mva(a), short_circuit_mva(b)
    for lbl_a, lbl_b in ((b0, c0), (b1, c1)):
        assert ra.s_sc_mva[ra.bus_row_of_label[lbl_a]] == pytest.approx(
            rb.s_sc_mva[rb.bus_row_of_label[lbl_b]], rel=1e-9)
    # 系統ベース pu の Z は base に比例して変わる(=換算が効いている証拠)
    assert abs(rb.z_th_pu[rb.bus_row_of_label[c0]]) == pytest.approx(
        10.0 * abs(ra.z_th_pu[ra.bus_row_of_label[b0]]), rel=1e-9)


def test_matches_pandapower_calc_sc_on_case9():
    """calc_sc(IEC 60909, case=max, c=1.1)と、同期機を等価 ext_grid(s_sc=c·S/xd'')で置いた
    参照網が**厳密に一致**すること(線路充電・負荷を無視する前提が calc_sc と同じ)。"""
    import pandapower.networks as pn
    from pandapower.shortcircuit import calc_sc
    from src.dynamics.machine_agg import aggregate_machines
    from src.powerflow.short_circuit import short_circuit_mva
    c9 = pn.case9()
    agg = aggregate_machines(c9)
    ref = copy.deepcopy(c9)
    ref.ext_grid = ref.ext_grid.iloc[0:0]
    ref.gen = ref.gen.iloc[0:0]
    for m in agg["sync"]:
        pp.create_ext_grid(ref, int(m["bus"]), s_sc_max_mva=1.1 * m["S_mva"] / m["xd2"], rx_max=0.0)
    calc_sc(ref, fault="3ph", case="max", ip=False, ith=False)
    skss = ref.res_bus_sc["skss_mw"].to_numpy()
    r = short_circuit_mva(c9)
    mine = np.array([r.s_sc_mva[r.bus_row_of_label[b]] for b in c9.bus.index])
    assert np.abs(mine * 1.1 / skss - 1).max() < 1e-9
    # 線路充電を入れると IEC 60909 からずれる(前提の違いを固定しておく)
    r2 = short_circuit_mva(c9, include_shunts=True)
    mine2 = np.array([r2.s_sc_mva[r2.bus_row_of_label[b]] for b in c9.bus.index])
    assert np.abs(mine2 * 1.1 / skss - 1).max() > 1e-2


def test_ext_grid_sources_reproduce_calc_sc_with_rx():
    """検証用 ext_grid 電流源(rx_max 込み)も calc_sc と一致。"""
    from pandapower.shortcircuit import calc_sc
    from src.powerflow.short_circuit import short_circuit_mva
    net = pp.create_empty_network(sn_mva=100)
    bs = [pp.create_bus(net, vn_kv=110) for _ in range(3)]
    pp.create_ext_grid(net, bs[0], s_sc_max_mva=1500, rx_max=0.15)
    for a, b, km in ((0, 1, 10), (1, 2, 20)):
        pp.create_line_from_parameters(net, bs[a], bs[b], length_km=km, r_ohm_per_km=0.1,
                                       x_ohm_per_km=0.4, c_nf_per_km=10, max_i_ka=1)
    pp.create_load(net, bs[2], p_mw=30)
    calc_sc(net, fault="3ph", case="max", ip=False, ith=False)
    skss = net.res_bus_sc["skss_mw"].to_numpy()
    r = short_circuit_mva(net, sources={}, include_ext_grid=True)
    mine = np.array([r.s_sc_mva[r.bus_row_of_label[b]] for b in bs])
    assert np.abs(mine * 1.1 / skss - 1).max() < 1e-9


def test_existing_ibr_is_deducted_and_not_a_source():
    """既設 IBR は短絡電流源にならず(S_sc 不変)、連系可能量から控除される。"""
    from src.powerflow.short_circuit import existing_ibr_mw, scr_hosting, short_circuit_mva
    base, b0, b1 = _two_bus()
    with_ibr, c0, c1 = _two_bus(ibr_mw=50.0)
    r0, r1 = short_circuit_mva(base), short_circuit_mva(with_ibr)
    s1 = r1.s_sc_mva[r1.bus_row_of_label[c1]]
    assert s1 == pytest.approx(r0.s_sc_mva[r0.bus_row_of_label[b1]], rel=1e-9)
    ibr = existing_ibr_mw(with_ibr)
    assert ibr == {c1: pytest.approx(50.0)}
    pmax, scr_now = scr_hosting(np.array([s1]), np.array([50.0]), scr_min=3.0)
    assert pmax[0] == pytest.approx(s1 / 3.0 - 50.0)
    assert scr_now[0] == pytest.approx(s1 / 50.0)
    # 既設が S_sc/SCR_min を超えていれば 0 で止まる(負にしない)
    pmax2, _ = scr_hosting(np.array([s1]), np.array([s1]), scr_min=3.0)
    assert pmax2[0] == 0.0
    # 電源に繋がらない地点は NaN のまま
    pmax3, scr3 = scr_hosting(np.array([np.nan]), np.array([0.0]))
    assert np.isnan(pmax3[0]) and np.isnan(scr3[0])


def test_unpowered_component_is_nan_not_huge():
    """電源のない孤立成分は正則化痕(巨大 |Z|)ではなく NaN で返す。"""
    from src.powerflow.short_circuit import short_circuit_mva
    net, b0, b1 = _two_bus()
    b2 = pp.create_bus(net, vn_kv=100.0)
    b3 = pp.create_bus(net, vn_kv=100.0)
    pp.create_line_from_parameters(net, b2, b3, length_km=1.0, r_ohm_per_km=0.0,
                                   x_ohm_per_km=10.0, c_nf_per_km=0.0, max_i_ka=1.0)
    pp.create_ext_grid(net, b2)          # rundcpp のための slack(電流源にはしない)
    r = short_circuit_mva(net)
    assert np.isnan(r.s_sc_mva[r.bus_row_of_label[b2]])
    assert np.isnan(r.s_sc_mva[r.bus_row_of_label[b3]])
    assert r.s_sc_mva[r.bus_row_of_label[b0]] == pytest.approx(400.0, rel=1e-9)


@pytest.mark.skipif(not (ROOT / "docs" / "data" / "built" / "all.json").exists(), reason="built DB が無い")
def test_cli_writes_json_for_okinawa(tmp_path):
    """CLI が沖縄(主成分 94 バス)で JSON/MD を書き、必須キーを持つこと。"""
    date = "test-9999-99-99"
    out_json = ROOT / "docs" / "reports" / f"ibr_hosting_scr_{date}.json"
    out_md = ROOT / "docs" / "reports" / f"ibr_hosting_scr_{date}.md"
    try:
        cp = subprocess.run([sys.executable, "scripts/sensitivity/ibr_hosting_scr.py",
                             "--islands", "okinawa", "--no-thermal", "--no-map", "--no-validate",
                             "--date", date],
                            cwd=ROOT, capture_output=True, text=True, timeout=600,
                            env={**__import__("os").environ, "PYTHONPATH": str(ROOT)})
        assert cp.returncode == 0, cp.stderr[-2000:]
        d = json.load(open(out_json, encoding="utf-8"))
        isl = d["islands"][0]
        assert isl["island"] == "okinawa"
        for k in ("n_bus_main", "n_sync_sources", "sync_source_mva", "ibr_existing_total_mw",
                  "band_stats", "binding_counts", "buses", "sc_note"):
            assert k in isl, k
        assert isl["n_bus_main"] >= 50 and isl["n_sync_sources"] >= 1
        assert isl["buses"] and all("s_sc_mva" in b and "pmax_scr_mw" in b for b in isl["buses"])
        assert out_md.exists()
    finally:
        for p in (out_json, out_md):
            if p.exists():
                p.unlink()
