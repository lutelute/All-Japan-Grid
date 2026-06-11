"""Measured-flow calibration layer: store and read disclosure aggregates.

Write side: ``scripts/db/calibrate.py`` parses the locally fetched
disclosure CSVs (data/external/, not redistributable) and lands one row
per corridor in ``measured_line_stats``. Read side: the boundary
injector and the flow validator consume the aggregates from the DB so
the pipeline no longer needs the raw CSVs at solve time — the DB is the
machine-updatable asset, CSV parsing stays available as the fallback.

Band semantics mirror the matcher (``external_tepco``): a corridor name
is assigned the floor of the FIRST file set that mentions it, in trunk
(200) -> 154 kV (140) -> 66 kV (60) order, so trunk supply lines listed
again in lower-class files stay trunk truths.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

DEFAULT_DB = "data/grid.db"
SOURCE_TEPCO = "tepco_jisseki"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert_measured_stats(db, region: str, rows) -> int:
    """Upsert calibration rows; returns the row count written.

    ``rows``: iterables of dicts with line_key / kv_floor / q50_mw /
    p95_mw and optional window, source.
    """
    from src.db.schema import MeasuredLineStat

    n = 0
    now = _now_iso()
    with db.session_factory() as session:
        for r in rows:
            session.merge(MeasuredLineStat(
                region=region,
                line_key=r["line_key"],
                kv_floor=float(r["kv_floor"]),
                source=r.get("source", SOURCE_TEPCO),
                q50_mw=float(r["q50_mw"]),
                p95_mw=float(r["p95_mw"]),
                window=r.get("window"),
                updated_at=now,
            ))
            n += 1
        session.commit()
    return n


def load_measured_line_stats(db_path: str = DEFAULT_DB,
                             region: str = "tokyo") -> dict | None:
    """{line_key: {"kv_floor", "q50", "p95"}} or None when absent.

    Returns None (never raises) when the DB file or table is missing or
    empty for the region — callers fall back to CSV parsing. On the
    (theoretical) same name at two floors the higher class wins,
    mirroring the matcher's trunk-first rule.
    """
    if not db_path or not os.path.exists(db_path):
        return None
    try:
        from src.db.grid_db import GridDatabase
        from src.db.schema import MeasuredLineStat

        db = GridDatabase(db_path)
        with db.session_factory() as session:
            rows = session.query(MeasuredLineStat).filter_by(
                region=region).all()
            out = {}
            for r in rows:
                cur = out.get(r.line_key)
                if cur is None or r.kv_floor > cur["kv_floor"]:
                    out[r.line_key] = {"kv_floor": r.kv_floor,
                                       "q50": r.q50_mw, "p95": r.p95_mw}
        return out or None
    except Exception:
        return None


def boundary_stats_from_db(db_path: str = DEFAULT_DB,
                           region: str = "tokyo") -> dict | None:
    """{line_key: q50_mw} for the boundary injector's corridor
    weighting (it looks corridors up by name), or None when absent."""
    stats = load_measured_line_stats(db_path, region)
    if not stats:
        return None
    return {k: v["q50"] for k, v in stats.items()}
