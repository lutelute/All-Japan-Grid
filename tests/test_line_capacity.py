"""介入#45 線路容量の運用容量較正（2026-09-02）のゲート。

  (a) yaml の係数が読める・無い (エリア, 階級) は national → overall へフォールバックし帳簿に出る
  (b) 較正 OFF のとき線路 max_i_ka は従来と同一（係数 1.0 相当）
  (c) 単一係数 `cap_factor` と階級別係数の整合（容量関数は max_i_ka に線形）
  (d) contingency / hosting の容量関数が同じ値を返す
  (e) 既定は OFF（全国化の一致度判定を満たしていない・台帳 #45）
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PF = ROOT / "scripts" / "run_full_powerflow_from_db.py"
CFG = ROOT / "config" / "line_capacity_calibration.yaml"


def _pf():
    spec = importlib.util.spec_from_file_location("pf_cap_ut", PF)
    m = importlib.util.module_from_spec(spec)
    sys.modules["pf_cap_ut"] = m
    spec.loader.exec_module(m)
    return m


def test_config_exists_and_has_ratios_only():
    """yaml は比だけ（生値の列が無い）。"""
    import yaml
    d = yaml.safe_load(CFG.read_text(encoding="utf-8"))
    assert d["unit"] == "dimensionless"
    assert d["overall_median_factor"] and 0.1 < d["overall_median_factor"] < 1.5
    for area, recs in d["areas"].items():
        for kv, r in (recs or {}).items():
            assert set(r) <= {"factor", "n", "p25_p75"}, f"{area}/{kv} に比以外の列がある: {r}"
            assert 0.05 < r["factor"] < 2.0


def test_factor_lookup_and_fallback_ledger():
    from src.powerflow.line_capacity import capacity_factor
    led = {}
    # 2026-09-03: 未取得だった 6 社の公表容量を取得したので、national へ落ちる組が変わった
    # (chubu/275 は実測 0.911 を持つようになった)。今も公表容量が無いのは okinawa だけ
    # (PDF のみ・未判読)。fallback の 3 段が全部踏まれる組を選ぶ。
    f_area = capacity_factor(154, "kansai", led)          # エリア×階級あり
    f_nat = capacity_factor(154, "okinawa", led)          # okinawa は公表無し → 全国中央値
    f_over = capacity_factor(132, "tohoku", led)          # 132kV はどこにも無し → 全体中央値
    assert led["by_source"] == {"area": 1, "national": 1, "overall": 1}
    assert led["by_area_kv"]["kansai/154"][0] == "area"
    assert led["by_area_kv"]["okinawa/154"][0] == "national"
    assert led["by_area_kv"]["tohoku/132"][0] == "overall"
    assert all(0.05 < f < 2.0 for f in (f_area, f_nat, f_over))


def test_missing_config_gives_unity(tmp_path):
    from src.powerflow.line_capacity import capacity_factor
    led = {}
    assert capacity_factor(154, "kansai", led, path=str(tmp_path / "none.yaml")) == 1.0
    assert led["by_source"] == {"no_config": 1}


def test_default_is_off():
    """既定 OFF（3 エリア以上が同階級で ±0.1 に収まる階級が無い・500kV は 0.37〜0.95）。"""
    pf = _pf()
    assert pf.CAP_CALIB_DEFAULT is False, "既定を変えるなら台帳 #45 と一致度判定を更新すること"


def test_builder_off_equals_legacy_and_on_scales_by_factor(monkeypatch):
    """OFF=従来と同一 / ON=各線路が (エリア, 階級) の係数倍。okinawa（96 線・数秒）で実測。"""
    pytest.importorskip("pandapower")
    import json
    pf = _pf()
    if not Path(pf.BUILT).exists():
        pytest.skip("built DB が無い")
    monkeypatch.delenv("AGJ_CAP_CALIB", raising=False)
    from src.powerflow.line_capacity import capacity_factor
    db = json.load(open(pf.BUILT, encoding="utf-8"))
    nodes, edges = db["nodes"], db["edges"]
    n0, _, s0 = pf.build_island_net("okinawa", nodes, edges, 60.0, {}, cap_calib=False)
    nd, _, sd = pf.build_island_net("okinawa", nodes, edges, 60.0, {})          # 既定
    n1, _, s1 = pf.build_island_net("okinawa", nodes, edges, 60.0, {}, cap_calib=True)
    assert not s0["cap_calib"] and not sd["cap_calib"] and s1["cap_calib"]
    assert (nd.line.max_i_ka.to_numpy() == n0.line.max_i_ka.to_numpy()).all(), "既定が従来と違う"
    ratio = n1.line.max_i_ka.to_numpy() / n0.line.max_i_ka.to_numpy()
    kv = n0.bus.loc[n0.line.from_bus.to_numpy(), "vn_kv"].to_numpy()
    for r, k in zip(ratio, kv):
        assert r == pytest.approx(capacity_factor(float(k), "okinawa"), rel=1e-9)
    assert s1["cap_calib_ledger"]["by_source"].get("national", 0) + \
        s1["cap_calib_ledger"]["by_source"].get("overall", 0) == len(n0.line), "帳簿の本数が線路数と違う"


def test_env_var_switches_default(monkeypatch):
    pytest.importorskip("pandapower")
    import json
    pf = _pf()
    if not Path(pf.BUILT).exists():
        pytest.skip("built DB が無い")
    db = json.load(open(pf.BUILT, encoding="utf-8"))
    monkeypatch.setenv("AGJ_CAP_CALIB", "1")
    _, _, s = pf.build_island_net("okinawa", db["nodes"], db["edges"], 60.0, {})
    assert s["cap_calib"] is True


def test_capacity_functions_agree_and_are_linear_in_factor():
    """contingency と hosting の容量関数が一致し、単一係数は線形（階級別係数と整合）。"""
    pytest.importorskip("pandapower")
    # hosting_capacity は地図を描くため matplotlib をトップレベルで import する。
    # CI（`pip install -e ".[dev]"`）には入っていないので、無い環境ではこの照合を飛ばす
    # — 容量関数そのものは他のテストが実データ無しで押さえている。
    pytest.importorskip("matplotlib")
    import numpy as np
    import pandapower as pp
    import pandapower.networks as pn
    sys.path.insert(0, str(ROOT / "scripts" / "sensitivity"))
    from src.powerflow import contingency as cg
    import hosting_capacity as hc
    net = pn.case14()
    pp.rundcpp(net)
    nl = len(net._ppc["branch"])
    a = cg.branch_capacity_mw(net, nl)
    b = hc.branch_capacity_mw(net, nl)
    assert np.allclose(a, b, equal_nan=True)
    c = cg.branch_capacity_mw(net, nl, cap_factor=0.5)
    assert np.allclose(c, a * 0.5, equal_nan=True)
    # 階級別係数を max_i_ka に乗じた net でも、容量関数は同じ線形則で追従する
    net2 = pn.case14()
    net2.line["max_i_ka"] = net2.line["max_i_ka"] * 0.6
    pp.rundcpp(net2)
    d = cg.branch_capacity_mw(net2, nl)
    lk = net._pd2ppc_lookups["branch"]["line"]
    s, e = lk[0], lk[0] + len(net.line)
    assert np.allclose(d[s:e], a[s:e] * 0.6)


def test_calibration_script_reports_ratios_only():
    """レポート JSON に線路別の容量値（生値）が無いこと（比・本数・分布のみ）。"""
    import json
    reps = sorted((ROOT / "docs" / "reports").glob("line_capacity_calibration_*.json"))
    if not reps:
        pytest.skip("較正レポートが無い")
    d = json.load(open(reps[-1], encoding="utf-8"))
    txt = json.dumps(d, ensure_ascii=False)
    assert "by_area_voltage" in d and "license" in d
    for r in d["by_area_voltage"]:
        assert set(r) <= {"area", "kv", "n_lines", "n_with_operational", "theoretical_mva_per_circuit",
                          "model_over_equipment", "operational_over_equipment", "model_over_operational",
                          "suggested_factor", "suggested_factor_p25_p75", "usable", "constraint_reasons",
                          "files"}, f"想定外の列（生値の混入疑い）: {set(r)}"
    assert "運用容量値(MW)" not in txt


def test_calibration_does_not_change_generator_attachment():
    """較正は制約側(loading%)だけに効き、接続規則(#24 cap/capkv)の判定は理論定格で行う。

    2026-09-02 実測: 較正を max_i_ka にそのまま乗じると bus_incident_mva/class_branch_mva が
    縮み、繋ぎ先が変わって west の AC が dc_fallback に退行した。理論定格 `max_i_ka_theo` を
    残して接続規則がそれを読むことで、ON/OFF で発電機の繋ぎ先が完全一致することを固定する。
    """
    pytest.importorskip("pandapower")
    import json
    pf = _pf()
    if not Path(pf.BUILT).exists():
        pytest.skip("built DB が無い")
    db = json.load(open(pf.BUILT, encoding="utf-8"))
    nodes, edges = db["nodes"], db["edges"]
    buses = {}
    for c in (False, True):
        net, bus_of, _ = pf.build_island_net("hokkaido", nodes, edges, 50.0, {}, cap_calib=c)
        pf.attach_generators(net, bus_of, nodes, "hokkaido", attach_mode="capkv")
        buses[c] = net.gen["bus"].to_numpy().tolist()
        if c:
            assert "max_i_ka_theo" in net.line.columns
            assert (net.line["max_i_ka_theo"] >= net.line["max_i_ka"]).all()
    assert buses[False] == buses[True], "較正で発電機の繋ぎ先が変わった(接続規則が理論定格を読んでいない)"
