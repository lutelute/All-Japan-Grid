"""Tests for UC scenario DB layer — uc_scenarios / uc_scenario_generators.

シナリオ（発電機選定の年度断面）のDBミラー:
YAML正本 → scripts/db/ingest_uc_scenarios.py → grid.db。
"""

import json

import pytest

from src.db.grid_db import GridDatabase
from src.db.schema import Base


@pytest.fixture
def db() -> GridDatabase:
    return GridDatabase(":memory:")


class TestSchema:
    def test_uc_tables_defined(self):
        tables = set(Base.metadata.tables.keys())
        assert "uc_scenarios" in tables
        assert "uc_scenario_generators" in tables

    def test_migration_v3_applied(self, db):
        assert db.get_schema_version() >= 3


class TestUCScenarioCRUD:
    def test_upsert_and_get(self, db):
        db.upsert_uc_scenario(
            "fy2023",
            config_json='{"meta": {"name": "fy2023"}}',
            fiscal_year=2023,
            description="2023年度断面",
        )
        rec = db.get_uc_scenario("fy2023")
        assert rec is not None
        assert rec.fiscal_year == 2023
        assert json.loads(rec.config_json)["meta"]["name"] == "fy2023"

    def test_upsert_updates_existing(self, db):
        db.upsert_uc_scenario("s1", config_json="{}", description="v1")
        db.upsert_uc_scenario("s1", config_json='{"a": 1}', description="v2")
        recs = db.list_uc_scenarios()
        assert len(recs) == 1
        assert recs[0].description == "v2"
        assert json.loads(recs[0].config_json) == {"a": 1}

    def test_generators_upsert_and_filter(self, db):
        db.upsert_uc_scenario("fy2023", config_json="{}")
        db.upsert_uc_scenario_generator(
            "fy2023", "nuclear_status", "川内",
            payload_json='{"capacity_mw": 1780, "region": "kyushu"}',
        )
        db.upsert_uc_scenario_generator(
            "fy2023", "pumped_storage", "葛野川",
            payload_json='{"capacity_mw": 1200, "region": "tokyo"}',
        )
        all_rows = db.list_uc_scenario_generators("fy2023")
        assert len(all_rows) == 2
        nuc = db.list_uc_scenario_generators("fy2023", kind="nuclear_status")
        assert len(nuc) == 1
        assert json.loads(nuc[0].payload_json)["capacity_mw"] == 1780

    def test_delete_cascades_generators(self, db):
        db.upsert_uc_scenario("s1", config_json="{}")
        db.upsert_uc_scenario_generator("s1", "pumped_storage", "p1",
                                        payload_json="{}")
        assert db.delete_uc_scenario("s1") is True
        assert db.get_uc_scenario("s1") is None
        assert db.list_uc_scenario_generators("s1") == []
        # 既に無いものの削除は False
        assert db.delete_uc_scenario("s1") is False


class TestIngestRealScenario:
    def test_ingest_fy2023(self, db):
        # 実YAML（リポジトリ正本）の取り込み統合テスト
        from scripts.db.ingest_uc_scenarios import ingest_scenario

        counts = ingest_scenario(db, "fy2023")
        # nuclear/揚水は安定した参照断面、容量パッチは調査の進展で増える
        assert counts["nuclear_status"] == 6
        assert counts["pumped_storage"] == 44
        assert counts["capacity_patches"] >= 24

        rec = db.get_uc_scenario("fy2023")
        assert rec.fiscal_year == 2023
        cfg = json.loads(rec.config_json)
        assert cfg["demand"]["regional_peak_mw"]["tokyo"] == 60000

        ps = db.list_uc_scenario_generators("fy2023", kind="pumped_storage")
        total_mw = sum(json.loads(r.payload_json)["capacity_mw"] for r in ps)
        assert 26_000 <= total_mw <= 29_000
