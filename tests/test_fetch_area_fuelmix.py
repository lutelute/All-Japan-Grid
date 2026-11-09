"""scripts/fetch_area_fuelmix.py: 毎時の取り込みでは東北を取りに行かず、--date では取りに行く(2026-11-09)。"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location("fetch_area_fuelmix", ROOT / "scripts" / "fetch_area_fuelmix.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _run(monkeypatch, tmp_path, argv):
    m = _mod()
    asked = []
    monkeypatch.setattr(m, "_get", lambda url: asked.append(url) or None)   # 網には出ない
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    monkeypatch.setattr(m, "fetch_kansai_today", lambda: (None, None))
    monkeypatch.setattr(m, "merge_kohyo04", lambda cur, date: None)
    monkeypatch.setattr(m, "STORE", tmp_path)
    monkeypatch.setattr(sys, "argv", ["fetch_area_fuelmix.py", *argv])
    assert m.main() == 0
    return asked


def test_hourly_run_does_not_ask_tohoku(monkeypatch, tmp_path):
    asked = _run(monkeypatch, tmp_path, [])
    assert asked                                            # ほかのエリアは取りに行く
    assert not any("tohoku-epco" in u for u in asked)       # 東北の当月・前月のファイルはまだ無い


def test_dated_run_asks_tohoku(monkeypatch, tmp_path):
    asked = _run(monkeypatch, tmp_path, ["--date", "20260915"])
    assert any(u.endswith("eria_jukyu_202609_02.csv") for u in asked)
