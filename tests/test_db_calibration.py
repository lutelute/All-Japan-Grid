"""Calibration layer (M2): disclosure aggregates live in the DB.

Raw disclosure CSVs are not redistributable, so the DB keeps only the
derived per-corridor aggregates (q50/p95 + band floor + window). These
tests pin the write/read roundtrip, the trunk-first band assignment and
the fail-soft loader contract (None — never an exception — when the DB
or rows are absent, so the pipeline silently falls back).
"""

import pytest

pytest.importorskip("sqlalchemy")

from src.db.calibration import (  # noqa: E402
    boundary_stats_from_db,
    load_measured_line_stats,
    upsert_measured_stats,
)
from src.db.grid_db import GridDatabase  # noqa: E402


def _rows():
    return [
        {"line_key": "A幹線", "kv_floor": 200.0, "q50_mw": 340.0,
         "p95_mw": 610.0, "window": "2024-04..2025-03"},
        {"line_key": "B線", "kv_floor": 60.0, "q50_mw": 12.0,
         "p95_mw": 31.0, "window": "2024-04..2025-03"},
    ]


def test_upsert_load_roundtrip_and_idempotency(tmp_path):
    db_path = str(tmp_path / "x.db")
    db = GridDatabase(db_path)
    assert upsert_measured_stats(db, "tokyo", _rows()) == 2

    out = load_measured_line_stats(db_path, "tokyo")
    assert out["A幹線"] == {"kv_floor": 200.0, "q50": 340.0, "p95": 610.0}
    assert out["B線"]["kv_floor"] == 60.0

    # re-calibration updates in place (PK upsert), no duplicate rows
    rows = _rows()
    rows[0]["q50_mw"] = 350.0
    upsert_measured_stats(db, "tokyo", rows)
    out2 = load_measured_line_stats(db_path, "tokyo")
    assert len(out2) == 2 and out2["A幹線"]["q50"] == 350.0

    assert boundary_stats_from_db(db_path, "tokyo") == {"A幹線": 350.0,
                                                        "B線": 12.0}


def test_loader_fails_soft():
    assert load_measured_line_stats("/nonexistent/grid.db", "tokyo") is None
    assert boundary_stats_from_db("/nonexistent/grid.db", "tokyo") is None


def test_loader_returns_none_for_uncalibrated_region(tmp_path):
    db_path = str(tmp_path / "x.db")
    db = GridDatabase(db_path)
    upsert_measured_stats(db, "tokyo", _rows())
    assert load_measured_line_stats(db_path, "okinawa") is None


def test_calibrate_rows_trunk_first_band_assignment(tmp_path):
    """A corridor named in BOTH the trunk and a 66 kV file keeps the
    trunk floor (200) — same setdefault rule as the matcher."""
    trunk = tmp_path / "kikan.csv"
    trunk.write_bytes((
        "日時,基幹(変) - A幹線1･2L\n"
        "2024年04月01日 00時,100\n"
        "2024年04月01日 01時,300\n").encode("cp932"))
    pref = tmp_path / "chiba01.csv"
    pref.write_bytes((
        "日時,町田(変) - A幹線1･2L,町田(変) - B線1･2L\n"
        "2024年04月01日 00時,90,10\n"
        "2024年04月01日 01時,280,30\n").encode("cp932"))

    import importlib

    calibrate = importlib.import_module("scripts.db.calibrate")
    rows = {r["line_key"]: r for r in calibrate.calibrate_rows(
        str(trunk), csv66=str(pref))}
    assert rows["A幹線"]["kv_floor"] == 200.0
    assert rows["B線"]["kv_floor"] == 60.0
    # quantiles of [100, 300]: q50=200, p95=290
    assert rows["A幹線"]["q50_mw"] == pytest.approx(200.0)
    assert rows["A幹線"]["p95_mw"] == pytest.approx(290.0)
    assert "2024年04月01日" in rows["A幹線"]["window"]


def test_calibrate_main_writes_db(tmp_path):
    trunk = tmp_path / "kikan.csv"
    trunk.write_bytes((
        "日時,基幹(変) - A幹線1･2L\n"
        "2024年04月01日 00時,100\n").encode("cp932"))
    db_path = str(tmp_path / "g.db")

    import importlib

    calibrate = importlib.import_module("scripts.db.calibrate")
    rc = calibrate.main(["--db", db_path, "--region", "tokyo",
                         "--csv", str(trunk), "--csv154", "", "--csv66", ""])
    assert rc == 0
    out = load_measured_line_stats(db_path, "tokyo")
    assert out["A幹線"]["kv_floor"] == 200.0
