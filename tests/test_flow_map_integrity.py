"""潮流マップ(docs/flow_map.html)のデータの整合を検査する。

2026-10-03 に見つかった事故の再発防止:
- 日別断面が「線順不一致」で島ごと出力されず、8/27〜10/03 は沖縄しか入っていなかった
  (線に一意な鍵が無く、並び順で結合していた)
- 表示側は値の無い線を黙って UC の値に戻していた
- インライン JS の括弧の閉じ忘れでページ全体が動かなくなった(ブラウザで確認するまで気づけない)
- 観測(公表潮流実績)は年統計 3 値しか公開できない(生の時系列は非公開)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FM = ROOT / "docs" / "data" / "flow_map"
ISLANDS = ("hokkaido", "east", "west", "okinawa")


def _flows(island: str) -> list[dict]:
    return json.loads((FM / f"flows_{island}.geojson").read_text(encoding="utf-8"))["features"]


@pytest.mark.parametrize("island", ISLANDS)
def test_base_lines_have_unique_keys(island):
    ks = [f["properties"].get("k") for f in _flows(island)]
    assert all(ks), f"{island}: 鍵(k)の無い線がある — export_flow_map_data.py で作り直す"
    assert len(set(ks)) == len(ks), f"{island}: 鍵が重複している"


@pytest.mark.parametrize("island", ISLANDS)
def test_meta_signature_matches_base(island):
    from src.powerflow.line_keys import keys_signature
    meta = json.loads((FM / "meta.json").read_text(encoding="utf-8"))
    ks = [f["properties"]["k"] for f in _flows(island)]
    assert meta[island]["sig"] == keys_signature(ks), \
        f"{island}: meta.json の sig が flows_{island}.geojson と合わない(片方だけ作り直した?)"


def test_latest_day_archives_cover_all_islands():
    """直近 3 日の日別断面は、4 島とも今の基準と同じ線構成で入っていること。"""
    meta = json.loads((FM / "meta.json").read_text(encoding="utf-8"))
    days = sorted((FM / "days").glob("2*.json"))[-3:]
    assert days, "日別断面が無い"
    for p in days:
        d = json.loads(p.read_text(encoding="utf-8"))
        for isl in ISLANDS:
            D = (d.get("islands") or {}).get(isl)
            assert D, f"{p.name}: {isl} が無い(線順不一致の再発?)"
            assert D.get("base_sig") == meta[isl]["sig"], f"{p.name}: {isl} が古い線構成で計算されている"
            n = len(_flows(isl))
            assert len(D["p"]) == n and len(D["ld"]) == n


def test_obs_compare_publishes_only_annual_stats():
    """観測側は年統計 3 値だけ。生の時系列(リスト)を書き出していないこと(ライセンス)。"""
    p = FM / "obs_compare.json"
    if not p.exists():
        pytest.skip("obs_compare.json が無い")
    d = json.loads(p.read_text(encoding="utf-8"))
    for r in d["lines"]:
        assert set(r["obs"]) <= {"mean", "p95", "max"}, r["obs"]
        assert not any(isinstance(v, list) for v in r["obs"].values())
        assert r["conf"] in ("A", "B", "C")
        if r["conf"] == "C":
            assert "dir_uc" not in r and "dir_act" not in r, "片端照合は向きを判定しない"


def test_obs_name_helpers():
    from scripts.export_obs_compare import clean_station, line_base, station_stem
    assert line_base("奥秩父線1･2L") == ("奥秩父線", 2)
    assert line_base("三岐幹2号線") == ("三岐幹線", 1)
    assert line_base("関西幹線（犬山～新奈良）")[0] == "関西幹線"
    assert clean_station("'能代変電所") == "能代変電所"
    assert clean_station("阿波根変電所/真壁変電所") == "阿波根変電所"
    assert clean_station("山崎開閉所（開4）") == "山崎開閉所"
    assert station_stem("天童変電所") == "天童"
    assert station_stem("奥秩父(変)") == "奥秩父"


def test_slim_keeps_empty_rows(tmp_path, monkeypatch):
    """基準の線に対応しなかった行(None)を軽量化が壊さないこと。"""
    import importlib
    days = tmp_path / "docs/data/flow_map/days"
    days.mkdir(parents=True)
    (days / "20990101.json").write_text(json.dumps(
        {"islands": {"okinawa": {"p": [[1.4, None], None], "ld": [[2.6, 3.1], None],
                                 "base_sig": "x"}}}))
    monkeypatch.chdir(tmp_path)
    slim = importlib.import_module("scripts.slim_flow_map")
    slim.main()
    d = json.loads((days / "20990101.json").read_text())
    assert d["islands"]["okinawa"]["p"] == [[1, None], None]
    assert d["islands"]["okinawa"]["base_sig"] == "x"


@pytest.mark.skipif(shutil.which("node") is None, reason="node が無い")
@pytest.mark.parametrize("page", sorted(p.name for p in (ROOT / "docs").glob("*.html")))
def test_pages_inline_scripts_parse(page, tmp_path):
    """Pages のインライン JS が構文として正しいこと(閉じ括弧の抜けでページ全体が止まる事故の防止)。"""
    html = (ROOT / "docs" / page).read_text(encoding="utf-8")
    for i, js in enumerate(re.findall(r"<script(?![^>]*\bsrc=)(?![^>]*type=\"(?:application/json|text/template)\")"
                                      r"[^>]*>(.*?)</script>", html, re.S)):
        if not js.strip():
            continue
        f = tmp_path / f"{page}.{i}.mjs" if "type=\"module\"" in html else tmp_path / f"{page}.{i}.js"
        f.write_text(js, encoding="utf-8")
        r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
        assert r.returncode == 0, f"{page} の {i} 番目のスクリプト: {r.stderr[-400:]}"
