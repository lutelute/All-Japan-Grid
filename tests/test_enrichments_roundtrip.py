"""The curation backup must round-trip: dump → load restores the C layer.

This guards the fix that makes ``enrichments.jsonl`` a real restore point
(committed P03 / manual fixes take effect on a fresh ``ingest`` rebuild),
not a write-only backup. Without the load path, curation saved to the
tracked backup silently never re-applied.
"""

import sqlalchemy as sa

from src.db.geojson_sync import (
    apply_enrichments,
    dump_enrichments_jsonl,
    load_enrichments_jsonl,
)
from src.db.grid_db import GridDatabase

ROWS = [
    {"layer": "plants", "region": "okinawa", "feature_key": "w1",
     "field": "capacity_mw", "value": 50, "source": "p03_db", "confidence": 0.9},
    {"layer": "plants", "region": "okinawa", "feature_key": "w1",
     "field": "operator", "value": "沖縄電力", "source": "p03_db"},
    {"layer": "substations", "region": "tokyo", "feature_key": "g:abc",
     "field": "name", "value": "テスト変電所", "source": "manual"},
]


def _count(db, **where):
    clause = " and ".join(f"{k}=:{k}" for k in where)
    with db._engine.connect() as c:
        return c.execute(
            sa.text(f"select count(*) from enrichments where {clause}"), where
        ).scalar()


def test_dump_then_load_restores_curation(tmp_path):
    src = GridDatabase(str(tmp_path / "src.db"))
    apply_enrichments(src, ROWS, run_id="seed")
    backup = str(tmp_path / "enrichments.jsonl")
    assert dump_enrichments_jsonl(src, backup) == len(ROWS)

    # a fresh DB has nothing until the backup is loaded
    fresh = GridDatabase(str(tmp_path / "fresh.db"))
    assert _count(fresh, source="p03_db") == 0
    applied = load_enrichments_jsonl(fresh, backup)
    assert applied == len(ROWS)
    assert _count(fresh, source="p03_db") == 2
    assert _count(fresh, source="manual") == 1
    # authoritative value survived with its source intact
    with fresh._engine.connect() as c:
        v = c.execute(sa.text(
            "select value from enrichments where field='capacity_mw' "
            "and source='p03_db'")).scalar()
    assert "50" in v


def test_load_is_idempotent_and_region_filtered(tmp_path):
    src = GridDatabase(str(tmp_path / "s.db"))
    apply_enrichments(src, ROWS)
    backup = str(tmp_path / "b.jsonl")
    dump_enrichments_jsonl(src, backup)

    db = GridDatabase(str(tmp_path / "d.db"))
    load_enrichments_jsonl(db, backup)
    load_enrichments_jsonl(db, backup)  # twice → upsert, no duplication
    with db._engine.connect() as c:
        total = c.execute(sa.text("select count(*) from enrichments")).scalar()
    assert total == len(ROWS)

    # region filter restricts what is restored
    only = GridDatabase(str(tmp_path / "o.db"))
    n = load_enrichments_jsonl(only, backup, regions=["okinawa"])
    assert n == 2
    assert _count(only, region="tokyo") == 0


def test_missing_backup_is_a_noop(tmp_path):
    db = GridDatabase(str(tmp_path / "x.db"))
    assert load_enrichments_jsonl(db, str(tmp_path / "nope.jsonl")) == 0
