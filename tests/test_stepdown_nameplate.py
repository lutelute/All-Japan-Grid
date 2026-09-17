"""介入#43a の変圧器容量: 銘板照合と出典帯による事前分布（2026-09-03・F4）。

背景: #43a が挿入した 71 台は全件が推定容量だった。原因を調べると **銘板索引が全国で
13 サイトしかなく**、#43a のサイトは 1 つも含まれない = 照合の失敗ではなく収集の不足
（`docs/reports/stepdown_nameplate_worklist_2026-09-03.md`）。
さらに推定規則（取付線の熱容量を 100MVA 刻みで切上げ）は、出典つき銘板の帯を電圧対
ごとに 2〜5 倍上回っていた（線の熱容量とバンク容量の取り違え）。
本テストは (1) 銘板があれば銘板が勝つこと (2) 出典帯モードが帯に収まること
(3) 出典DB の様式 (4) 事前分布が壊れないこと を固定する。
"""
from __future__ import annotations

import json

import pytest

from src.powerflow import stepdown_gap as sg


def _net_with_mismatch(hv_kv=275.0, lv_kv=66.0, ika=2.0):
    """kv_H 母線に kv_L 線が直結した最小系統（#43a の対象そのもの）。"""
    pp = pytest.importorskip("pandapower")
    net = pp.create_empty_network()
    b_hv = pp.create_bus(net, vn_kv=hv_kv, name="試験変電所")
    b_far = pp.create_bus(net, vn_kv=lv_kv, name="末端変電所")
    li = pp.create_line_from_parameters(
        net, b_hv, b_far, length_km=3.0, r_ohm_per_km=0.1, x_ohm_per_km=0.3,
        c_nf_per_km=0.0, max_i_ka=ika, name="試験線")
    net.line["kv_class"] = float(lv_kv)
    net.bus["zone"] = "tokyo"
    return net, int(b_hv), int(li)


def test_nameplate_wins_over_estimate():
    """銘板があれば銘板容量が使われ、capacity=nameplate と記録される。"""
    pytest.importorskip("pandapower")
    net, b_hv, _ = _net_with_mismatch()
    plates = {("tokyo", "試験変電所"): [
        {"hv_kv": 275.0, "lv_kv": 66.0, "sn_mva": 200.0, "n_parallel": 2}]}
    led = sg.apply_implicit_stepdown(net, nameplates=plates,
                                     region_of_bus=lambda b: "tokyo")
    assert len(led) == 1
    assert led[0]["capacity"] == "nameplate"
    assert led[0]["sn_mva"] == 200.0 and led[0]["parallel"] == 2


def test_kv_pair_must_match_for_nameplate():
    """電圧対が違う銘板は使わない（別バンクの容量を流用しない）。"""
    pytest.importorskip("pandapower")
    net, _, _ = _net_with_mismatch(hv_kv=275.0, lv_kv=66.0)
    plates = {("tokyo", "試験変電所"): [
        {"hv_kv": 275.0, "lv_kv": 154.0, "sn_mva": 450.0, "n_parallel": 1}]}
    led = sg.apply_implicit_stepdown(net, nameplates=plates,
                                     region_of_bus=lambda b: "tokyo")
    assert led[0]["capacity"] == "estimated", "別の電圧対の銘板が流用された"


def test_prior_rule_stays_inside_the_sourced_band():
    """出典帯モードは、線の熱容量ではなく出典中央値に寄る（過大推定の是正）。"""
    pytest.importorskip("pandapower")
    prior = sg.sourced_capacity_prior()
    pair = (275.0, 66.0)
    if pair not in prior:
        pytest.skip("275/66 の出典が無い")
    net, _, li = _net_with_mismatch(ika=2.0)          # 太い線 → 推定は大きく出る
    line_mva = sg._line_mva(net, li)
    led_line = sg.apply_implicit_stepdown(net, capacity_rule="line")
    net2, _, _ = _net_with_mismatch(ika=2.0)
    led_prior = sg.apply_implicit_stepdown(net2, capacity_rule="prior")
    assert led_line[0]["capacity"] == "estimated"
    assert led_prior[0]["capacity"] == "prior"
    # 線の熱容量は 275kV×2kA≈953MVA。出典帯(150〜300)に収まること
    assert line_mva > 500, "前提: 試験線の熱容量は出典帯より十分大きい"
    assert led_prior[0]["sn_mva"] <= prior[pair]["max"], "出典帯の最大を超えた"
    assert led_prior[0]["sn_mva"] < led_line[0]["sn_mva"], "出典帯モードが是正になっていない"


def test_prior_never_exceeds_the_line_capacity():
    """事前分布が線より太くても、線の熱容量を上限にする（偽の隘路の逆を作らない）。"""
    pytest.importorskip("pandapower")
    net, _, li = _net_with_mismatch(hv_kv=500.0, lv_kv=275.0, ika=0.2)   # 細い線
    line_mva = sg._line_mva(net, li)
    led = sg.apply_implicit_stepdown(net, capacity_rule="prior")
    assert led[0]["sn_mva"] <= max(sg.SN_STEP,
                                   -(-line_mva // sg.SN_STEP) * sg.SN_STEP) + 1e-6


def test_prior_falls_back_to_line_rule_without_sourced_data():
    """出典の無い電圧対は従来どおり線の熱容量規則（勝手に埋めない）。"""
    pytest.importorskip("pandapower")
    prior = sg.sourced_capacity_prior()
    pair = (110.0, 66.0)
    if pair in prior:
        pytest.skip("110/66 に出典が入った — テストの前提が変わった")
    net, _, _ = _net_with_mismatch(hv_kv=110.0, lv_kv=66.0)
    led = sg.apply_implicit_stepdown(net, capacity_rule="prior")
    assert led[0]["capacity"] == "estimated"


def test_default_rule_is_unchanged():
    """既定は従来の線規則のまま（既定変更は台帳とオーナー判断が要る）。"""
    assert sg.CAPACITY_RULE_DEFAULT == "line"


def test_sourced_prior_uses_only_complete_existing_records(tmp_path):
    """事前分布は status=existing かつ sn_mva+hv+lv が揃う site だけから作る。"""
    p = tmp_path / "src.jsonl"
    rows = [
        # 揃っている existing → 採用
        {"site_key": "x:A", "field": "sn_mva", "value": 200, "status": "existing"},
        {"site_key": "x:A", "field": "hv_kv", "value": 275, "status": "existing"},
        {"site_key": "x:A", "field": "lv_kv", "value": 66, "status": "existing"},
        # planned は除外
        {"site_key": "x:B", "field": "sn_mva", "value": 9999, "status": "planned"},
        {"site_key": "x:B", "field": "hv_kv", "value": 275, "status": "planned"},
        {"site_key": "x:B", "field": "lv_kv", "value": 66, "status": "planned"},
        # sn_total_mva は変電所全体でバンク容量でない → 除外
        {"site_key": "x:C", "field": "sn_total_mva", "value": 5000, "status": "existing"},
        {"site_key": "x:C", "field": "hv_kv", "value": 275, "status": "existing"},
        {"site_key": "x:C", "field": "lv_kv", "value": 66, "status": "existing"},
    ]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                 encoding="utf-8")
    got = sg.sourced_capacity_prior(str(p))
    assert got == {(275.0, 66.0): {"median": 200.0, "max": 200.0, "n": 1}}


def test_real_sources_jsonl_has_required_fields():
    """正典の出典DB が様式を保っていること（quote/URL 必須の規約）。"""
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "data" / "transformer_sources.jsonl"
    if not p.exists():
        pytest.skip("出典DB が無い")
    need = {"site_key", "field", "value", "source_type", "source_url",
            "quote", "retrieved_at", "confidence", "status"}
    n = 0
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            r = json.loads(line)
            missing = need - set(r)
            assert not missing, f"{r.get('site_key')} に {missing} が無い"
            n += 1
    assert n > 500, f"出典DB の行数が想定外に少ない: {n}"


def test_worklist_report_matches_the_measured_index_size():
    """ワークリストの主張（銘板索引 13・当たり 0）がレポートと一致していること。"""
    from pathlib import Path
    p = (Path(__file__).resolve().parents[1] / "docs" / "reports"
         / "stepdown_nameplate_worklist_2026-09-03.json")
    if not p.exists():
        pytest.skip("ワークリストが無い")
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["n_sites"] == 71
    assert d["n_in_nameplate_index"] == 0
    assert d["nameplate_index_size"] < 30, "銘板索引が増えたらレポートを更新すること"
