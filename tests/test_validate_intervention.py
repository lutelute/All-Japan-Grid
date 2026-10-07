"""介入の妥当性の採点(scripts/validate_intervention.py)の計算部分。"""
from scripts.validate_intervention import model_value, norm, score_flows, truth_pairs


def test_model_value_orients_sums_parallels_and_scales_per_circuit():
    lines = {"a": [100.0, 50.0, 35.0, 139.0, 35.1, 139.1, 275.0],
             "b": [60.0, 30.0, 35.0, 139.0, 35.1, 139.1, 275.0]}
    m = {"seg0": [["a", -1, 1], ["b", -1, 1]], "n_circ_obs": None}
    v, pos = model_value(m, lines)
    assert v == -160.0 and pos == [35.0, 139.0, 35.1, 139.1]
    # 観測が 1 回線ごと(「1号線」)でモデルが 2 回線をまとめているときは按分
    m = {"seg0": [["a", 1, 2]], "n_circ_obs": 1}
    assert model_value(m, lines)[0] == 50.0


def test_score_flows_counts_lines_that_get_closer_to_observation():
    off = {"east": {"lines": {"k": [40.0, 10, 35.0, 139.0, 35.1, 139.1, 275.0]}}}
    on = {"east": {"lines": {"k": [95.0, 20, 35.0, 139.0, 35.1, 139.1, 275.0]}}}
    matched = [{"island": "east", "util": "tokyo", "name": "X線", "kv": 275, "from": "A", "to": "B", "conf": "A",
                "obs": {"p95": 100.0, "mean": 60.0}, "n_circ_obs": None, "seg0": [["k", 1, 1]]}]
    sites = [{"island": "east", "name": "A", "lat": 35.0, "lon": 139.0}]
    r = score_flows(off, on, matched, sites)
    assert r["all"]["closer"] == 1 and r["all"]["farther"] == 0
    assert r["within_15km_of_relinked"]["n"] == 1
    assert r["all"]["on"]["within_x2"] == 1.0 and r["all"]["off"]["within_x2"] == 0.0


def test_sourced_pairs_come_from_one_quote_and_existing_only():
    t = truth_pairs()
    # 西山形: 既設 275/154(計画の 500/154 は数えない)
    assert (275, 154) in t[("tohoku", norm("西山形変電所"))]["pairs"]
    assert (500, 154) not in t[("tohoku", norm("西山形変電所"))]["pairs"]
