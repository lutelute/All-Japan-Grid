"""Tests for JEPX connector — spot_summary年度CSVの月・エリア抽出。"""

import pytest

from src.dataspace.connectors.jepx import JepxConnector


class _FakeContract:
    def __init__(self, root):
        self._root = root

    def resolve_location(self):
        return self._root


CSV = """受渡日,時刻コード,売り入札量(kWh),買い入札量(kWh),約定総量(kWh),システムプライス(円/kWh),エリアプライス北海道(円/kWh),エリアプライス東北(円/kWh),エリアプライス東京(円/kWh),エリアプライス中部(円/kWh),エリアプライス北陸(円/kWh),エリアプライス関西(円/kWh),エリアプライス中国(円/kWh),エリアプライス四国(円/kWh),エリアプライス九州(円/kWh)
2025/08/06,1,100,100,100,11.50,12.0,11.5,11.5,10.0,9.0,9.0,9.0,9.0,8.5
2025/08/06,2,100,100,100,10.80,11.5,11.0,11.0,9.8,8.8,8.8,8.8,8.8,8.0
2025/09/01,1,100,100,100,9.00,9.5,9.0,9.0,8.5,8.0,8.0,8.0,8.0,7.5
"""


@pytest.fixture
def nas(tmp_path):
    d = tmp_path / "price_raw" / "jepx"
    d.mkdir(parents=True)
    (d / "spot_summary_2025.csv").write_bytes(CSV.encode("utf-8-sig"))
    return _FakeContract(str(tmp_path))


def test_month_and_area_filter(nas):
    out = JepxConnector().fetch(
        {"fiscal_year": 2025, "month": "202508", "area": "tohoku"}, nas)
    assert out["n_rows"] == 2          # 9月の行は除外
    assert out["rows"][0]["tohoku"] == pytest.approx(11.5)
    assert out["rows"][0]["system"] == pytest.approx(11.5)
    assert "kansai" not in out["rows"][0]   # area指定時は他エリア省略


def test_all_areas_without_filter(nas):
    out = JepxConnector().fetch({"fiscal_year": 2025}, nas)
    assert out["n_rows"] == 3
    assert out["rows"][0]["kyushu"] == pytest.approx(8.5)


def test_missing_location_guides(tmp_path):
    with pytest.raises(RuntimeError, match="AJGRID_NAS03_ROOT"):
        JepxConnector().fetch({"fiscal_year": 2025}, _FakeContract(None))
