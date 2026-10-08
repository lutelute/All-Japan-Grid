"""grid_overrides: 公表台帳による変圧器容量の置き換え(合成データで検証。実台帳は使わない)。"""
import os, sqlite3, sys, tempfile
from types import SimpleNamespace
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np, pandas as pd
from nankai.grid_overrides import _norm_site, ledger_transformers, apply_transformer_capacity


def _db(rows):
    d = tempfile.mkdtemp(); p = os.path.join(d, "t.sqlite")
    con = sqlite3.connect(p)
    con.execute("create table hv_transformers (utility text, source_kind text, substation text, voltage_hi_kv real, voltage_lo_kv real, n_banks real, capacity_total real)")
    con.executemany("insert into hv_transformers values (?,?,?,?,?,?,?)", rows)
    con.commit(); con.close()
    return p


def test_norm_site_strips_bank_suffix_and_width():
    assert _norm_site("新木更津5・8B") == "新木更津"
    assert _norm_site("姉崎中央１Ｕ") == "姉崎中央"
    assert _norm_site("東山梨変電所") == "東山梨"
    assert _norm_site("新野田15-17B") == "新野田"


def test_ledger_dedups_area_files_and_sums_bank_groups():
    U, K = "東京電力パワーグリッド", "空容量一覧CSV"
    p = _db([(U, K, "甲", 500, 275, 3, 3000), (U, K, "甲", 500, 275, 3, 3000),          # 基幹と都県の両方に出る同じ行
             (U, K, "乙5・8B", 275, 154, 2, 600), (U, K, "乙6・7B", 275, 154, 2, 900),    # バンク群は足す
             (U, K, "丙", 275, 66, 3, 0)])                                               # 容量 0 は捨てる
    led = ledger_transformers(p).set_index(["site", "hi", "lo"])
    assert led.loc[("甲", 500, 275)].capacity_total == 3000 and led.loc[("甲", 500, 275)].n_banks == 3
    assert led.loc[("乙", 275, 154)].capacity_total == 1500 and led.loc[("乙", 275, 154)].n_banks == 4
    assert ("丙", 275, 66) not in led.index


def test_apply_replaces_capacity_and_scales_reactance_only_in_zone():
    U, K = "東京電力パワーグリッド", "空容量一覧CSV"
    p = _db([(U, K, "甲", 500, 275, 4, 6000)])
    bus = pd.DataFrame({"kv": [500, 275, 500, 275], "zone": ["tokyo", "tokyo", "tohoku", "tohoku"], "site": ["甲", "甲", "甲", "甲"]})
    br = pd.DataFrame({"kind": ["trafo", "trafo"], "f": [0, 2], "t": [1, 3], "cap_mw": [952.6, 952.6], "x_pu": [0.02, 0.02], "parallel": [1, 1]})
    case = SimpleNamespace(bus=bus, branch=br)
    led = apply_transformer_capacity(case, p)
    assert len(led) == 1
    assert np.isclose(case.branch.cap_mw[0], 6000) and np.isclose(case.branch.x_pu[0], 0.005)
    assert np.isclose(case.branch.cap_mw[1], 952.6) and np.isclose(case.branch.x_pu[1], 0.02)   # 東北は台帳が無いので触らない


def test_missing_db_is_noop():
    br = pd.DataFrame({"kind": ["trafo"], "f": [0], "t": [1], "cap_mw": [1.0], "x_pu": [0.1]})
    case = SimpleNamespace(bus=pd.DataFrame({"kv": [500, 275], "zone": ["tokyo"] * 2, "site": ["甲"] * 2}), branch=br)
    assert apply_transformer_capacity(case, "/nonexistent.sqlite").empty and case.branch.cap_mw[0] == 1.0
