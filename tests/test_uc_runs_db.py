"""Tests for UC run history DB layer — uc_runs.

実行履歴の索引（docs/reports/ のJSONが正本、DBは機械検索層）:
各ドライバ → src/uc/run_recorder.record_run → grid.db。
"""

import json

import pytest

from src.db.grid_db import GridDatabase
from src.db.schema import Base


@pytest.fixture
def db() -> GridDatabase:
    return GridDatabase(":memory:")


class TestSchema:
    def test_uc_runs_table_defined(self):
        assert "uc_runs" in set(Base.metadata.tables.keys())

    def test_migration_v4_applied(self, db):
        assert db.get_schema_version() >= 4


class TestUCRunCRUD:
    def test_record_and_list(self, db):
        db.record_uc_run(
            "docs/reports/uc_benchmark_x_2026-06-12.json",
            kind="benchmark", run_date="2026-06-12",
            scenario_id="fy2023r2", status="Optimal",
            total_cost_jpy=2.0e10, solve_time_s=12.3, l1_total_pp=23.5,
            summary_json=json.dumps({"lng": 33.1}),
        )
        runs = db.list_uc_runs()
        assert len(runs) == 1
        assert runs[0].status == "Optimal"
        assert runs[0].l1_total_pp == pytest.approx(23.5)

    def test_upsert_by_report_path(self, db):
        path = "docs/reports/uc_pf_link_tokyo_2026-06-12.json"
        db.record_uc_run(path, kind="pf_link", run_date="2026-06-12",
                         status="1/24 failed")
        db.record_uc_run(path, kind="pf_link", run_date="2026-06-12",
                         status="converged")
        runs = db.list_uc_runs(kind="pf_link")
        assert len(runs) == 1          # 再実行は重複しない
        assert runs[0].status == "converged"

    def test_filters(self, db):
        db.record_uc_run("a.json", kind="benchmark", run_date="2026-06-11",
                         scenario_id="fy2023")
        db.record_uc_run("b.json", kind="annual", run_date="2026-06-12",
                         scenario_id="fy2025r1")
        assert len(db.list_uc_runs(kind="annual")) == 1
        assert len(db.list_uc_runs(scenario_id="fy2023")) == 1
        assert len(db.list_uc_runs()) == 2


class TestRecorderBestEffort:
    def test_records_into_db(self, tmp_path):
        from src.uc.run_recorder import record_run
        dbf = str(tmp_path / "grid.db")
        ok = record_run("docs/reports/x.json", kind="benchmark",
                        run_date="2026-06-12", db_path=dbf,
                        scenario_id="fy2023r2", status="Optimal")
        assert ok is True
        assert len(GridDatabase(dbf).list_uc_runs()) == 1

    def test_failure_does_not_raise(self, tmp_path):
        from src.uc.run_recorder import record_run
        # 書込不能パス（存在しないディレクトリ）→ False、例外は出ない
        ok = record_run("docs/reports/x.json", kind="benchmark",
                        run_date="2026-06-12",
                        db_path=str(tmp_path / "no_such_dir" / "grid.db"))
        assert ok is False
