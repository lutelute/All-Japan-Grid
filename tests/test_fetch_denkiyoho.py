"""でんき予報の取得(scripts/fetch_denkiyoho.py)の読み取りの試験。値は合成(各社の公表値ではない)。

2026-11-25: 関西は未収載・四国は年次 CSV で date が毎回前の日・各社の予測値の列を捨てていた。
関西・四国を当日の CSV(他社と同じ形)に替え、予測値を forecast_mw に残すようにした。
"""
from __future__ import annotations

import json

from scripts import fetch_denkiyoho as fd

# 他社と同じ形の当日の CSV(見出し 1 行目・1 時間値のセクション・5 分値のセクション)
COMMON = """2026/11/25 19:10 UPDATE
ピーク時供給力(万kW),時間帯,供給力情報更新日,供給力情報更新時刻,ピーク時予備率(%),ピーク時使用率(%)
100,9:00～10:00,11/25,18:43,8,92

DATE,TIME,当日実績(万kW),{col4},使用率(%),供給力(万kW)
2026/11/25,0:00,10,11,80,13
2026/11/25,1:00,12,12,81,14
2026/11/25,2:00,0,13,0,15
2026/11/25,3:00,0,14,0,16

最大使用率(%),時間帯
95,18:00～19:00

DATE,TIME,当日実績(５分間隔値)(万kW),太陽光発電実績(５分間隔値)(万kW)
2026/11/25,0:00,99,0
2026/11/25,0:05,99,0
"""

YEARLY = """2026/11/25 00:00 UPDATE

DATE,TIME,実績(万kW),供給力想定値(万kW)
2026/11/23,23:00,20,30
2026/11/24,0:00,21,31
2026/11/24,1:00,22,32
"""


def test_hourly_actuals_and_forecast_column():
    p = fd.parse_hourly(COMMON.format(col4="予測値(万kW)"), "tokyo")
    assert p["date"] == "2026/11/25" and p["updated"] == "2026/11/25 19:10"
    assert p["hourly_mw"] == {0: 100.0, 1: 120.0}          # 0 は未来の時刻なので入れない
    assert p["forecast_mw"] == {0: 110.0, 1: 120.0, 2: 130.0, 3: 140.0}


def test_kansai_forecast_column_is_named_yosou():
    p = fd.parse_hourly(COMMON.format(col4="予想値(万kW)"), "kansai")
    assert p["forecast_mw"] == {0: 110.0, 1: 120.0, 2: 130.0, 3: 140.0}


def test_five_minute_section_is_not_read_as_hourly():
    # 1 時間値のセクションが無くても、5 分値のセクションを 1 時間値として読まない
    only5 = COMMON.split("DATE,TIME,当日実績(万kW)")[0] + COMMON.split("最大使用率(%),時間帯\n95,18:00～19:00\n")[1]
    p = fd.parse_hourly(only5, "tokyo")
    assert p["hourly_mw"] == {} and "forecast_mw" not in p


def test_unknown_fourth_column_keeps_actuals_without_forecast():
    p = fd.parse_hourly(COMMON.format(col4="何か(万kW)"), "tokyo")
    assert p["hourly_mw"] == {0: 100.0, 1: 120.0} and "forecast_mw" not in p


def test_yearly_fallback_reads_latest_day_only():
    p = fd.parse_hourly(YEARLY, "shikoku", yearly=True)
    assert p["date"] == "2026/11/24" and p["hourly_mw"] == {0: 210.0, 1: 220.0}
    assert "forecast_mw" not in p


def test_all_ten_areas_have_a_source():
    assert set(fd.SOURCES) == {"hokkaido", "tohoku", "tokyo", "chubu", "hokuriku", "kansai",
                               "chugoku", "shikoku", "kyushu", "okinawa"}


def test_main_writes_store_and_latest_into_out_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(fd, "fetch", lambda url: (COMMON.format(col4="予測値(万kW)"), None))
    monkeypatch.setattr(fd.time, "sleep", lambda s: None)
    day = tmp_path / f"denkiyoho_{fd.D}.json"
    day.write_text(json.dumps({"2026-11-25T00:00:00": {"tokyo": {"error": "fetch failed"}}}))
    assert fd.main(["--out-dir", str(tmp_path)]) == 0
    hist = json.loads(day.read_text())
    assert len(hist) == 2 and "2026-11-25T00:00:00" in hist      # 前のスナップショットは残る
    last = hist[max(hist)]
    assert set(last) == set(fd.SOURCES)
    assert {"hourly_mw", "forecast_mw", "updated", "date", "source"} <= set(last["kansai"])
    lat = json.loads((tmp_path / "latest.json").read_text())
    assert set(lat["zones"]) == set(fd.SOURCES)
    assert not list(tmp_path.glob(".*.tmp*"))                     # 一時ファイルは残らない


def test_shikoku_falls_back_to_yearly_csv_when_day_csv_fails(tmp_path, monkeypatch):
    def fake(url):
        if url == fd.SOURCES["shikoku"]:
            return None, "HTTP Error 404"
        if url == fd.FALLBACK["shikoku"]:
            return YEARLY, None
        if url == fd.SOURCES["tohoku"]:
            return None, "name not known"
        return COMMON.format(col4="予測値(万kW)"), None
    monkeypatch.setattr(fd, "fetch", fake)
    monkeypatch.setattr(fd.time, "sleep", lambda s: None)
    assert fd.main(["--out-dir", str(tmp_path)]) == 0
    last = next(iter(json.loads((tmp_path / f"denkiyoho_{fd.D}.json").read_text()).values()))
    assert last["shikoku"]["source"] == fd.FALLBACK["shikoku"] and last["shikoku"]["date"] == "2026/11/24"
    assert last["tohoku"] == {"error": "fetch failed", "source": fd.SOURCES["tohoku"], "reason": "name not known"}
