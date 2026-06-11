"""Tests for src/dataspace — 契約カタログ・キャッシュ・出所記録・コネクタ。

設計原則の回帰ピン（docs/DATA_SPACE.md）:
- データは源泉に留める: MSMは所在未設定なら案内付きで明示失敗（暗黙取得しない）
- 全取得は provenance.jsonl に記録される
- コネクタの無い契約（p03等）は既存パイプラインへ案内する
"""

import json

import pytest

from src.dataspace import DataContract, DataSpace

CATALOG = """
providers:
  mockprov:
    title: Mock provider
    custodian: test
    location: "https://example.invalid"
    license: test
    redistribute_raw: false
    redistribute_derived: true
    connector: occto
  msm:
    title: MSM
    custodian: lab NAS
    location: "env:AJGRID_MSM_ROOT"
    license: RISH terms
    redistribute_raw: false
    redistribute_derived: true
    connector: msm
  p03:
    title: P03
    custodian: MLIT
    location: "https://nlftp.mlit.go.jp/"
    license: KSJ terms
    redistribute_raw: false
    redistribute_derived: true
    connector: null
    notes: use scripts/db/enrich.py --p03
"""


@pytest.fixture
def ds(tmp_path):
    cat = tmp_path / "catalog.yaml"
    cat.write_text(CATALOG)
    return DataSpace(catalog_path=cat, cache_dir=tmp_path / "cache")


class TestCatalog:
    def test_real_catalog_loads_with_required_contracts(self):
        real = DataSpace()  # config/dataspace.yaml
        assert {"msm", "occto_kohyo", "p03", "energy_stats"} <= set(real.providers())
        msm = real.contract("msm")
        assert msm.redistribute_raw is False   # 生GRIB2のコミット禁止が契約
        assert msm.location == "env:AJGRID_MSM_ROOT"

    def test_missing_contract_key_rejected(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("providers:\n  x:\n    title: incomplete\n")
        with pytest.raises(ValueError, match="missing contract keys"):
            DataSpace(catalog_path=bad, cache_dir=tmp_path / "c")

    def test_unknown_provider(self, ds):
        with pytest.raises(KeyError, match="unknown dataspace provider"):
            ds.contract("nope")

    def test_env_location_resolution(self, ds, monkeypatch):
        c = ds.contract("msm")
        monkeypatch.delenv("AJGRID_MSM_ROOT", raising=False)
        assert c.resolve_location() is None      # 未設定 → None（暗黙先なし）
        monkeypatch.setenv("AJGRID_MSM_ROOT", "/mnt/nas/msm")
        assert c.resolve_location() == "/mnt/nas/msm"


class TestCacheAndProvenance:
    def test_fetch_caches_and_records_provenance(self, ds, monkeypatch):
        calls = []

        class FakeConnector:
            def fetch(self, query, contract):
                calls.append(query)
                return {"tokyo": [1.0, 2.0]}

        monkeypatch.setattr(ds, "_connector", lambda c: FakeConnector())
        q = {"kind": "area_demand", "date_from": "2025-04-01"}
        r1 = ds.fetch("mockprov", q)
        r2 = ds.fetch("mockprov", q)          # キャッシュヒット
        assert r1 == r2 == {"tokyo": [1.0, 2.0]}
        assert len(calls) == 1
        ds.fetch("mockprov", q, force=True)   # 強制再取得
        assert len(calls) == 2
        # provenance に2回分の記録（custodian/license込み）
        lines = ds.store.provenance_path.read_text().strip().splitlines()
        assert len(lines) == 2
        rec = json.loads(lines[0])
        assert rec["provider"] == "mockprov"
        assert rec["custodian"] == "test"
        assert "sha256" in rec


class TestMSMGuard:
    def test_unset_root_fails_with_guidance(self, ds, monkeypatch):
        monkeypatch.delenv("AJGRID_MSM_ROOT", raising=False)
        with pytest.raises(RuntimeError, match="AJGRID_MSM_ROOT"):
            ds.fetch("msm", {"kind": "regional_cf"})

    def test_set_root_reaches_phase2_boundary(self, ds, monkeypatch, tmp_path):
        monkeypatch.setenv("AJGRID_MSM_ROOT", str(tmp_path))
        with pytest.raises(NotImplementedError, match="Phase 2"):
            ds.fetch("msm", {"kind": "regional_cf"})


class TestNoConnectorContract:
    def test_p03_points_to_existing_pipeline(self, ds):
        with pytest.raises(ValueError, match="no connector"):
            ds.fetch("p03", {})


class TestOcctoParse:
    # 実フォーマット（2026-06実測）: UPDATEスタンプ行 + ヘッダ + 行指向
    CSV = (
        '"2026/06/09 23:00 UPDATE"\n'
        '"対象年月日","時刻","ブロックNo","エリア名","広域ブロック需要(MW)","エリア需要(MW)","エリア供給力(MW)"\n'
        '"2026/06/09","00:30","1","北海道","46044","2491","2721"\n'
        '"2026/06/09","00:30","1","東京","46044","24058","26330"\n'
        '"2026/06/09","01:00","1","北海道","45800","2450","2700"\n'
        '"2026/06/09","01:00","1","東京","45800","23500","26000"\n'
        '"2026/06/09","01:00","9","九州","12000","7900","9000"\n'
    )

    def test_series_row_oriented(self):
        from src.dataspace.connectors.occto import OcctoConnector
        s = OcctoConnector.parse_area_csv(self.CSV, stat="series")
        # エリア名列でグループ化、エリア需要(MW)列を時系列化
        assert s["hokkaido"] == [2491.0, 2450.0]
        assert s["tokyo"] == [24058.0, 23500.0]
        assert s["kyushu"] == [7900.0]
        assert "kansai" not in s  # 行に無い地域は含めない
        # 広域ブロック需要(46044)を誤って拾っていない
        assert 46044.0 not in s["hokkaido"]

    def test_summary(self):
        from src.dataspace.connectors.occto import OcctoConnector
        s = OcctoConnector.parse_area_csv(self.CSV, stat="summary")
        assert s["tokyo"]["n"] == 2
        assert s["tokyo"]["max"] == 24058.0
