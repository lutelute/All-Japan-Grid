"""Tests for nas03 connector — エリア需給実績CSVの新形式パーサ。

実フォーマット（2026-06-12実地調査）を合成CSVで再現し、列名マップ・
hokkaido変種（制御量+2列）・日付フィルタ・欠測の扱いを検証する。
"""

import pytest

from src.dataspace.connectors.nas03 import COMPANY_TO_REGION, Nas03Connector


class _FakeContract:
    def __init__(self, root):
        self._root = root

    def resolve_location(self):
        return self._root


CSV_STD = """単位[MW平均],,,供給力,,,,,,,,,,,,,,,,
DATE,TIME,エリア需要,原子力,火力(LNG),火力(石炭),火力(石油),火力(その他),水力,地熱,バイオマス,太陽光発電実績,太陽光出力制御量,風力発電実績,風力出力制御量,揚水,蓄電池,連系線,その他,合計
2025/8/6,0:00,2315,0,124,788,0,15,1308,0,68,0,0,3,0,0,0,-50,59,2315
2025/8/6,0:30,2289,0,120,743,0,15,1324,0,66,0,0,3,0,0,0,-38,57,2289
2025/8/7,0:00,2400,0,130,800,0,15,1300,0,70,0,0,3,0,0,0,-40,60,2400
"""

# hokkaido変種: 火力出力制御量・バイオマス出力制御量の2列が追加
CSV_HOKKAIDO = """単位[MW平均],,,供給力,,,,,,,,,,,,,,,,,,
DATE,TIME,エリア需要,原子力,火力(LNG),火力(石炭),火力(石油),火力(その他),火力出力制御量,水力,地熱,バイオマス,バイオマス出力制御量,太陽光発電実績,太陽光出力制御量,風力発電実績,風力出力制御量,揚水,蓄電池,連系線,その他,合計
2025/8/6,0:00,2800,0,500,900,10,20,0,400,30,100,0,0,0,150,5,-20,10,695,0,2800
"""


@pytest.fixture
def nas(tmp_path):
    """ローカルパス所在のフェイクPWS_DBを組み立てる。"""
    for company, text in (("hokuriku", CSV_STD), ("hokkaido", CSV_HOKKAIDO)):
        d = tmp_path / "demand_raw" / company
        d.mkdir(parents=True)
        (d / "202508.csv").write_bytes(text.encode("cp932"))
    # tepco実態: 月次はUTF-8-SIG（CP932固定読みだと列名が化ける）
    d = tmp_path / "demand_raw" / "tepco"
    d.mkdir(parents=True)
    (d / "202508.csv").write_bytes(CSV_STD.encode("utf-8-sig"))
    return _FakeContract(str(tmp_path))


class TestParser:
    def test_standard_format_and_date_filter(self, nas):
        out = Nas03Connector().fetch(
            {"company": "hokuriku", "month": "202508", "date": "2025-08-06"},
            nas)
        assert out["region"] == "hokuriku"
        assert out["n_rows"] == 2          # 8/7の行は除外
        r0 = out["rows"][0]
        assert r0["demand"] == pytest.approx(2315.0)
        assert r0["coal"] == pytest.approx(788.0)
        assert r0["hydro"] == pytest.approx(1308.0)
        assert r0["interconnector"] == pytest.approx(-50.0)
        # 「その他」と「火力(その他)」が区別される
        assert r0["other"] == pytest.approx(59.0)
        assert r0["thermal_other"] == pytest.approx(15.0)

    def test_hokkaido_extra_columns(self, nas):
        out = Nas03Connector().fetch(
            {"company": "hokkaido", "month": "202508"}, nas)
        r0 = out["rows"][0]
        # 制御量列のズレに惑わされず本体列が正しく取れる
        assert r0["hydro"] == pytest.approx(400.0)
        assert r0["biomass"] == pytest.approx(100.0)
        assert r0["wind"] == pytest.approx(150.0)
        assert r0["wind_curtailed"] == pytest.approx(5.0)

    def test_tepco_utf8_sig(self, nas):
        out = Nas03Connector().fetch(
            {"company": "tepco", "month": "202508", "date": "2025-08-06"},
            nas)
        assert out["region"] == "tokyo"
        assert out["n_rows"] == 2
        assert out["rows"][0]["demand"] == pytest.approx(2315.0)

    def test_unknown_company_raises(self, nas):
        with pytest.raises(ValueError, match="unknown company"):
            Nas03Connector().fetch({"company": "nowhere", "month": "202508"},
                                   nas)

    def test_missing_location_guides(self):
        with pytest.raises(RuntimeError, match="AJGRID_NAS03_ROOT"):
            Nas03Connector().fetch(
                {"company": "hokuriku", "month": "202508"},
                _FakeContract(None))


def test_company_region_map_covers_10():
    assert len(COMPANY_TO_REGION) == 10
    assert COMPANY_TO_REGION["tepco"] == "tokyo"


CSV_KANSAI_LEGACY = """,,,,,,,太陽光,太陽光,風力,風力,,
DATE_TIME,エリア需要〔MWh〕,原子力〔MWh〕,火力〔MWh〕,水力〔MWh〕,地熱〔MWh〕,バイオマス〔MWh〕,実績〔MWh〕,抑制量〔MWh〕,実績〔MWh〕,抑制量〔MWh〕,揚水〔MWh〕,連系線〔MWh〕
2023/12/13 0:00,11734,4961,6364,1114,0,80,0,0,4,0,33,-823
2023/12/13 1:00,11512,4961,6580,1155,0,80,0,0,2,0,-453,-813
2023/12/14 0:00,12000,4961,6500,1200,0,80,0,0,3,0,40,-800
"""


def test_kansai_legacy_format(tmp_path):
    d = tmp_path / "demand_raw" / "kansai"
    d.mkdir(parents=True)
    (d / "202312.csv").write_bytes(CSV_KANSAI_LEGACY.encode("cp932"))
    out = Nas03Connector().fetch(
        {"company": "kansai", "month": "202312", "date": "2023-12-13"},
        _FakeContract(str(tmp_path)))
    assert out["format"] == "legacy_datetime"
    assert out["region"] == "kansai"
    assert out["n_rows"] == 2          # 12/14は除外
    r0 = out["rows"][0]
    assert r0["nuclear"] == pytest.approx(4961.0)
    assert r0["thermal_combined"] == pytest.approx(6364.0)
    assert r0["pumped_hydro"] == pytest.approx(33.0)
    assert r0["interconnector"] == pytest.approx(-823.0)


CSV_CHUGOKU = """供給区域の需給実績,,,,,,,,,,,,,
,,需要実績(MWh),供給実績(MWh),,,,,,,,,,
DATE,TIME,需要,原子力,火力,水力,地熱,バイオマス,太陽光(実績),太陽光(抑制量),風力(実績),風力(抑制量),揚水,連系線潮流
2023/12/13,0:00,5000,0,4523,249,0,186,0,－,2,－,129,-88
2023/12/13,1:00,4900,0,4400,250,0,186,0,－,2,－,100,-80
"""


def test_chugoku_aliases(tmp_path):
    d = tmp_path / "demand_raw" / "chugoku"
    d.mkdir(parents=True)
    (d / "202312.csv").write_bytes(CSV_CHUGOKU.encode("cp932"))
    out = Nas03Connector().fetch(
        {"company": "chugoku", "month": "202312", "date": "2023-12-13"},
        _FakeContract(str(tmp_path)))
    r0 = out["rows"][0]
    assert r0["demand"] == pytest.approx(5000.0)
    assert r0["thermal_combined"] == pytest.approx(4523.0)
    assert r0["solar"] == pytest.approx(0.0)
    assert r0["interconnector"] == pytest.approx(-88.0)
    assert "solar_curtailed" not in r0    # 「－」欠測はスキップ


def test_kyushu_quarter_file_resolution(tmp_path):
    d = tmp_path / "demand_raw" / "kyushu"
    d.mkdir(parents=True)
    # 202312.csv は無く、FY四半期ファイル 2023_3Q.csv のみ存在
    (d / "2023_3Q.csv").write_bytes(CSV_KANSAI_LEGACY.encode("cp932"))
    out = Nas03Connector().fetch(
        {"company": "kyushu", "month": "202312", "date": "2023-12-13"},
        _FakeContract(str(tmp_path)))
    assert out["format"] == "legacy_datetime"
    assert out["n_rows"] == 2
