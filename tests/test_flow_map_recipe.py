"""潮流マップ(基準・NOW 断面・日別断面)が、正典と同じ組み方で網を組むかの試験。

2026-11-12 に見つかった事故の再発防止: 潮流マップの 2 本のスクリプトは `attach_mode="cap"` を書き込み、
公表の接続の台帳(介入#55)を渡さず、需給の合わせ方も旧挙動(#54 の前)だった。姉崎火力が公表の 275 kV・房総でなく
中袖 500 kV に付き、台帳の 26 機のうち 19 機が正典と違う所に付いていた(docs/reports/sync_scoreboard_2026-11-10.md §11)。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FLOW_MAP_SCRIPTS = ("scripts/export_flow_map_data.py", "scripts/export_day_flows.py")


@pytest.mark.parametrize("path", FLOW_MAP_SCRIPTS)
def test_flow_map_scripts_use_model_recipe(path):
    src = (ROOT / path).read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert 'attach_mode="cap"' not in code and "attach_mode='cap'" not in code
    assert "model_attach_kwargs(island)" in code
    calls = re.findall(r"balance_by_zone\((?:net|nt)\b[^)]*\)", code)
    assert calls
    for call in calls:
        assert "connected=CONNECTED_DISPATCH" in call, call
    calls = re.findall(r"solve_island\((?:net|nt)\b[^)]*\)", code)
    assert calls
    for call in calls:
        assert "spread=CONNECTED_DISPATCH" in call, call


def test_model_attach_kwargs_follow_model_defaults():
    import src.powerflow.full_from_built as ff
    for island in ("hokkaido", "east", "west", "okinawa"):
        kw = ff.model_attach_kwargs(island)
        assert kw["attach_mode"] == ff.attach_default_for(island)
        if ff.PLANT_CONNECTIONS:
            assert "姉崎火力発電所" in kw["plant_ledger"]
            assert kw["plant_ledger"]["姉崎火力発電所"]["kv"] == 275.0


def test_recipe_tag_changes_with_ledger(tmp_path, monkeypatch):
    import src.powerflow.full_from_built as ff
    a = tmp_path / "a.yaml"
    a.write_text("plants: []\n", encoding="utf-8")
    monkeypatch.setattr(ff, "PLANT_CONNECTIONS_PATH", str(a))
    t1 = ff.model_recipe_tag()
    a.write_text("plants:\n  - {name: x, kv: 275}\n", encoding="utf-8")
    assert ff.model_recipe_tag() != t1
    monkeypatch.setattr(ff, "CONNECTED_DISPATCH", not ff.CONNECTED_DISPATCH)
    assert ff.model_recipe_tag() != t1


def test_day_signature_carries_recipe_tag():
    from scripts import export_day_flows as edf
    from scripts.run_full_powerflow_from_db import model_recipe_tag
    sig = edf.hour_inputs({"tokyo": {0: 1.0}}, None, None, [0])["0"]
    assert sig.startswith(f"組:{model_recipe_tag()}|")
