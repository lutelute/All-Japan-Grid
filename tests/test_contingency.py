"""N-1 スクリーニング（`src/powerflow/contingency.py`）のゲート。

  (a) LODF の一括評価が「実際に枝を落として rundcpp した値」と 1e-6 で一致する
  (b) 放射枝（橋）は islanding として別勘定になり、分離側の負荷が正しく数えられる
  (c) 並列回線の 1 回線開放が「parallel を 1 減らして解き直した値」と一致する（単位ゲート）
  (d) CLI が JSON/MD を書く（built が無ければ skip）
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILT = ROOT / "docs" / "data" / "built" / "all.json"
CLI = ROOT / "scripts" / "sensitivity" / "n1_screening.py"

pp = pytest.importorskip("pandapower")
from pandapower.pypower.idx_brch import BR_STATUS, F_BUS, T_BUS  # noqa: E402
from pandapower.pypower.makePTDF import makePTDF  # noqa: E402

from src.powerflow import contingency as cg  # noqa: E402


def _ptdf_of(net):
    pp.rundcpp(net)
    ppc = net._ppc
    ref = int(net._pd2ppc_lookups["bus"][int(net.ext_grid.bus.iloc[0])])
    ptdf = makePTDF(ppc["baseMVA"], ppc["bus"], ppc["branch"], slack=ref)
    return ppc, ptdf, ref


def _resolve_without(net, tbl, eid):
    tab = getattr(net, tbl)
    tab.loc[eid, "in_service"] = False
    try:
        pp.rundcpp(net)
        return cg.ppc_flows_mw(net._ppc)
    finally:
        tab.loc[eid, "in_service"] = True


# ── (a) LODF の一括評価 = 解き直し ────────────────────────────────────────
def test_screen_matches_resolve_on_case14():
    import pandapower.networks as pn
    net = pn.case14()
    net.gen["slack"] = False
    ppc, ptdf, ref = _ptdf_of(net)
    f0 = cg.ppc_flows_mw(ppc)
    elems = cg.branch_elements(net)
    par = cg.branch_parallel(net, len(f0))
    cap = cg.branch_capacity_mw(net, len(f0))
    res = cg.screen(ptdf, ppc["branch"], f0, cap, par, single_circuit=False)
    assert res.n_branch == len(f0) and res.outage_ok.sum() >= 15
    n_checked = 0
    for k in np.where(res.outage_ok)[0]:
        tbl, eid = elems[k]
        f_pred = cg.post_contingency_flows(ptdf, ppc["branch"], f0, int(k), par, single_circuit=False)
        f_true = _resolve_without(net, tbl, eid)
        msk = np.ones(len(f0), bool); msk[k] = False
        assert np.abs(f_pred[msk] - f_true[msk]).max() < 1e-6, f"branch {k} ({tbl}:{eid})"
        assert f_pred[k] == pytest.approx(0.0)
        # 一括評価の最大負荷率が、個別に計算した値と一致する（監視=全枝）
        capf = np.where(np.isfinite(cap), cap, np.inf)
        L = np.abs(f_pred) / capf * 100.0
        assert res.post_max_loading[k] == pytest.approx(L.max(), rel=1e-9)
        # 「基準で過負荷でない枝」側の最大と増分も個別計算と一致
        Ln = np.where(res.base_over, 0.0, L)
        assert res.post_max_new[k] == pytest.approx(Ln.max(), rel=1e-9)
        assert res.post_max_new[k] <= res.post_max_loading[k] + 1e-9
        if res.post_worst_new[k] >= 0:
            assert not res.base_over[res.post_worst_new[k]]
        assert res.post_max_delta[k] == pytest.approx((L - res.base_loading * res.monitor).max(), rel=1e-9)
        n_checked += 1
    assert n_checked >= 15
    # 一括評価にかかる時間が枝数分の解き直しより明らかに短いこと（桁のゲート）
    assert res.sec < 1.0


# ── (b) 橋（放射枝）は islanding・分離側の負荷を数える ──────────────────
def _radial_net():
    """0(ext)—1—2—3 の放射線 + 1–2 に並列で戻る枝は無い。2,3 に負荷。"""
    net = pp.create_empty_network()
    b = [pp.create_bus(net, vn_kv=110.0) for _ in range(4)]
    pp.create_ext_grid(net, b[0])
    for i in range(3):
        pp.create_line_from_parameters(net, b[i], b[i + 1], length_km=10.0,
                                       r_ohm_per_km=0.05, x_ohm_per_km=0.3,
                                       c_nf_per_km=0.0, max_i_ka=0.5)
    pp.create_load(net, b[2], p_mw=30.0)
    pp.create_load(net, b[3], p_mw=20.0)
    pp.create_gen(net, b[3], p_mw=5.0, vm_pu=1.0)
    return net


def test_radial_branches_are_islanding_with_isolated_load():
    net = _radial_net()
    ppc, ptdf, ref = _ptdf_of(net)
    f0 = cg.ppc_flows_mw(ppc)
    par = cg.branch_parallel(net, len(f0))
    cap = cg.branch_capacity_mw(net, len(f0))
    res = cg.screen(ptdf, ppc["branch"], f0, cap, par, single_circuit=True)
    assert res.islanding.all(), "放射線は全枝が橋"
    assert not res.outage_ok.any()
    assert np.isnan(res.post_max_loading).all()
    load, gen = cg.bus_load_gen_mw(ppc)
    side = cg.islanded_side(ppc["branch"], len(ppc["bus"]), ref, res.islanding, load, gen)
    assert set(side) == {0, 1, 2}
    # 1–2 を切ると 2,3 が孤立: 負荷 50MW・発電 5MW・2バス
    assert side[1]["n_bus"] == 2
    assert side[1]["load_mw"] == pytest.approx(50.0)
    assert side[1]["gen_mw"] == pytest.approx(5.0)
    assert side[2]["load_mw"] == pytest.approx(20.0) and side[2]["n_bus"] == 1
    assert side[0]["load_mw"] == pytest.approx(50.0) and side[0]["n_bus"] == 3
    with pytest.raises(ValueError):
        cg.post_contingency_flows(ptdf, ppc["branch"], f0, 1, par, single_circuit=True)


def test_case14_bridges_agree_with_graph():
    """PTDF 判定の橋 = グラフ上の橋（case14 は 7–8 の変圧器が唯一の橋）。"""
    import networkx as nx
    import pandapower.networks as pn
    import pandapower.topology as top
    net = pn.case14()
    net.gen["slack"] = False
    ppc, ptdf, ref = _ptdf_of(net)
    h = cg.self_sensitivity(ptdf, ppc["branch"])
    par = cg.branch_parallel(net, len(h))
    isl = cg.islanding_mask(h, par, single_circuit=False,
                            status=ppc["branch"][:, BR_STATUS].real.astype(float))
    g = top.create_nxgraph(net, respect_switches=False)
    nb = {frozenset(e) for e in nx.bridges(nx.Graph(g))}
    fb = ppc["branch"][:, F_BUS].real.astype(int)
    tb = ppc["branch"][:, T_BUS].real.astype(int)
    lbl = {int(v): int(k) for k, v in enumerate(net._pd2ppc_lookups["bus"]) if v >= 0}
    got = {frozenset((lbl[fb[k]], lbl[tb[k]])) for k in np.where(isl)[0]}
    assert got == nb and len(nb) == 1


# ── (c) 並列回線の 1 回線開放 = parallel−1 で解き直し ───────────────────
def _meshed_parallel_net():
    """三角形 0–1–2（0 に ext_grid）。0–1 は 3 回線、他は 1 回線。"""
    net = pp.create_empty_network()
    b = [pp.create_bus(net, vn_kv=220.0) for _ in range(3)]
    pp.create_ext_grid(net, b[0])
    pp.create_line_from_parameters(net, b[0], b[1], length_km=40.0, r_ohm_per_km=0.05,
                                   x_ohm_per_km=0.3, c_nf_per_km=0.0, max_i_ka=1.0, parallel=3)
    pp.create_line_from_parameters(net, b[1], b[2], length_km=30.0, r_ohm_per_km=0.05,
                                   x_ohm_per_km=0.3, c_nf_per_km=0.0, max_i_ka=1.0)
    pp.create_line_from_parameters(net, b[0], b[2], length_km=60.0, r_ohm_per_km=0.05,
                                   x_ohm_per_km=0.3, c_nf_per_km=0.0, max_i_ka=1.0)
    pp.create_load(net, b[1], p_mw=300.0)
    pp.create_load(net, b[2], p_mw=200.0)
    return net


def test_single_circuit_outage_matches_parallel_minus_one():
    net = _meshed_parallel_net()
    ppc, ptdf, ref = _ptdf_of(net)
    f0 = cg.ppc_flows_mw(ppc)
    par = cg.branch_parallel(net, len(f0))
    cap = cg.branch_capacity_mw(net, len(f0))
    assert par[0] == 3
    f_pred = cg.post_contingency_flows(ptdf, ppc["branch"], f0, 0, par, single_circuit=True)
    # 真値: 0–1 の parallel を 2 にして解き直す
    net.line.at[0, "parallel"] = 2
    pp.rundcpp(net)
    f_true = cg.ppc_flows_mw(net._ppc)
    net.line.at[0, "parallel"] = 3
    assert np.abs(f_pred - f_true).max() < 1e-6, "1回線開放の潮流が解き直しと不一致（残回線含む）"
    # 一括評価: 残回線の負荷率 = |f'| / (cap·2/3)
    res = cg.screen(ptdf, ppc["branch"], f0, cap, par, single_circuit=True)
    assert not res.islanding[0]
    lk = abs(f_true[0]) / (cap[0] * 2 / 3) * 100.0
    others = np.abs(f_true[1:]) / cap[1:] * 100.0
    assert res.post_max_loading[0] == pytest.approx(max(lk, others.max()), rel=1e-9)
    # 全回線開放モードなら 0–1 を丸ごと落とす（残回線 0・潮流は 0–2 経由）
    res_all = cg.screen(ptdf, ppc["branch"], f0, cap, par, single_circuit=False)
    f_all = cg.post_contingency_flows(ptdf, ppc["branch"], f0, 0, par, single_circuit=False)
    assert f_all[0] == pytest.approx(0.0)
    assert f_all[2] == pytest.approx(-500.0 * 1.0, abs=1e-6) or abs(f_all[2]) == pytest.approx(500.0, abs=1e-6)
    assert res_all.post_max_loading[0] >= res.post_max_loading[0]


def test_capacity_counts_parallel_circuits():
    """容量が回線数を数え落とさない（hosting_capacity と同じ定義）。"""
    net = _meshed_parallel_net()
    _ptdf_of(net)
    cap = cg.branch_capacity_mw(net, len(net._ppc["branch"]))
    assert cap[0] == pytest.approx(np.sqrt(3) * 220.0 * 1.0 * 3)
    assert cap[1] == pytest.approx(np.sqrt(3) * 220.0 * 1.0)
    assert cg.branch_capacity_mw(net, 3, cap_factor=0.5)[0] == pytest.approx(cap[0] / 2)


# ── (d) CLI ──────────────────────────────────────────────────────────────
@pytest.mark.skipif(not BUILT.exists(), reason="built DB が無い")
def test_cli_writes_json_and_md(tmp_path):
    out = subprocess.run(
        [sys.executable, str(CLI), "--islands", "okinawa", "--top", "3",
         "--date", "test", "--out-dir", str(tmp_path), "--no-map"],
        cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]
    j = json.loads((tmp_path / "n1_screening_test.json").read_text(encoding="utf-8"))
    isl = j["islands"][0]
    assert isl["island"] == "okinawa"
    assert isl["n_outage_evaluated"] + isl["n_islanding"] <= isl["n_branch"]
    assert len(isl["top_physical"]) <= 3
    for row in isl["top_physical"]:
        assert row["post_max_loading_pct"] >= 0 and row["elem_class"]
    assert (tmp_path / "n1_screening_test.md").exists()
