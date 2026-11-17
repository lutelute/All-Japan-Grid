"""潮流マップの基準を作り直したとき、過去の日別断面を線の鍵で並べ直す(scripts/rekey_day_flows.py)。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rekey_day_flows", ROOT / "scripts" / "rekey_day_flows.py")
rk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rk)


def test_values_follow_keys_and_new_lines_are_blank():
    old = ["a", "b", "c"]
    new = ["c", "x", "a"]                 # b は消え、x は新しい
    day = {"p": [[1] * 24, [2] * 24, [None] * 24], "ld": [[10] * 24, [20] * 24, [None] * 24],
           "base_sig": "old", "coverage": 0.67, "ac_hours": [0]}
    out = rk.remap(day, old, new, "new", "2026-11-17")
    assert out["p"] == [[None] * 24, None, [1] * 24]
    assert out["ld"][2] == [10] * 24 and out["ld"][1] is None
    assert out["base_sig"] == "new"
    assert out["rekey"]["from_sig"] == "old" and out["rekey"]["n_mapped"] == 2
    assert out["coverage"] == round(1 / 3, 4)      # 値の入った行は a だけ
    assert day["base_sig"] == "old"                 # 元は変えない
