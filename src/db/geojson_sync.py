"""GeoJSON <-> DB synchronisation — DB unification Steps 1-2.

Implements the R/C/D decomposition of ``docs/DB_ARCHITECTURE.md`` for
the legacy per-region GeoJSON files:

- :func:`ingest_geojson` — ``data/{region}_{layer}.geojson`` →
  ``raw_features`` + ``enrichments`` (provenance recovered from the
  legacy ``_enriched_by`` / ``_name_source`` markers) + a ``snapshots``
  row holding the FeatureCollection-level metadata (``name``, ``crs``).
- :func:`export_geojson` — raw ⟕ enrichments → a FeatureCollection
  semantically identical to the source file, golden-tested by
  :func:`verify_roundtrip` and ``tests/test_db_geojson_sync.py``.
- :func:`dump_enrichments_jsonl` — diff-readable, timestamp-free text
  dump of the C layer: the *tracked* backup of all curation work.

Identity (:func:`feature_key_for`): ``n/w/r{osm_id}`` when the OSM id
is known (plants carry ``osm_id``/``osm_type`` properties), otherwise a
provisional ``g:{sha1[:12]}`` of the normalized geometry — the legacy
substations/lines files carry no OSM id at all (measured 2026-06-08:
okinawa 0/59 and 0/117).  Identical-geometry duplicates within one
(region, layer) file are disambiguated with a deterministic ``#N``
suffix in file order.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import delete, insert, select

from src.db.grid_db import GridDatabase
from src.db.schema import Enrichment, RawFeature, Snapshot

#: Data layers, in the canonical file-name order.
LAYERS: Tuple[str, ...] = ("substations", "lines", "plants")

#: Resolution priority when several sources provide the same field —
#: earlier wins.  Legacy marker values are adopted verbatim
#: (docs/DB_ARCHITECTURE.md, C layer).
SOURCE_PRIORITY: Tuple[str, ...] = (
    "manual",
    "audit_fix",
    "p03",
    "overpass",
    "jrp_lite",
    "endpoint_matching",
    "geocode_promotion",
    "nominatim",
    "legacy_marker",
)

_OSM_PREFIX = {"node": "n", "way": "w", "relation": "r"}
_INSERT_CHUNK = 2000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dumps(value: Any) -> str:
    """JSON-encode preserving key order and non-ASCII characters."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _canonical_geometry(geometry: Any) -> str:
    """Key-order-independent canonical form, used only for hashing."""
    return json.dumps(
        geometry, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def source_rank(source: str) -> int:
    """Rank of an enrichment source; unknown sources sort last."""
    try:
        return SOURCE_PRIORITY.index(source)
    except ValueError:
        return len(SOURCE_PRIORITY)


def feature_key_for(
    feature: Dict[str, Any],
) -> Tuple[str, Optional[str], Optional[int]]:
    """Stable identity for a GeoJSON feature.

    Returns:
        ``(feature_key, osm_type, osm_id)`` — osm fields are ``None``
        when the feature carries no usable OSM id and the provisional
        geometry key is used.
    """
    props = feature.get("properties") or {}
    osm_id_raw = props.get("osm_id")
    osm_type = props.get("osm_type")
    if osm_id_raw is not None:
        try:
            osm_id = int(osm_id_raw)
        except (TypeError, ValueError):
            osm_id = None
        if osm_id is not None:
            prefix = _OSM_PREFIX.get(str(osm_type or "").lower(), "x")
            return (
                f"{prefix}{osm_id}",
                str(osm_type) if osm_type else None,
                osm_id,
            )
    digest = hashlib.sha1(
        _canonical_geometry(feature.get("geometry")).encode("utf-8")
    ).hexdigest()[:12]
    return f"g:{digest}", None, None


def decompose_properties(
    props: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[Tuple[str, Any, str]]]:
    """Split legacy properties into raw tags and curated rows.

    Extraction rules (legacy marker conventions, measured 2026-06-08):

    1. every ``_``-prefixed field → C layer with
       ``source='legacy_marker'`` (``_enriched_by``, ``_name_source``,
       ``_display_name``, ``_fuel_color``, …);
    2. ``name`` → C layer when ``_name_source`` marks it as enriched,
       with the feature's ``_enriched_by`` value adopted verbatim as
       the source;
    3. everything else stays in raw tags.

    Curated values hiding in *unmarked* fields cannot be told apart
    from raw OSM values yet; they are rescued by the reconciliation
    pass at the first real Overpass re-fetch
    (docs/DB_ARCHITECTURE.md §3.1).

    Returns:
        ``(raw_tags, curated)`` where ``curated`` is a list of
        ``(field, value, source)`` tuples (fields unique per feature).
    """
    name_enriched = "_name_source" in props
    enriched_by = props.get("_enriched_by")
    raw_tags: Dict[str, Any] = {}
    curated: List[Tuple[str, Any, str]] = []
    for key, value in props.items():
        if key.startswith("_"):
            curated.append((key, value, "legacy_marker"))
        elif key == "name" and name_enriched:
            source = (
                enriched_by
                if isinstance(enriched_by, str) and enriched_by
                else "legacy_marker"
            )
            curated.append((key, value, source))
        else:
            raw_tags[key] = value
    return raw_tags, curated


def compose_properties(
    raw_tags: Dict[str, Any], enrichment_rows: Sequence[Any]
) -> Dict[str, Any]:
    """raw ⟕ curated → effective properties (D layer).

    Args:
        raw_tags: Decoded raw tag dict.
        enrichment_rows: Objects with ``field`` / ``source`` / ``value``
            attributes (ORM rows or equivalents).  When several sources
            provide the same field the :data:`SOURCE_PRIORITY` winner
            is applied.
    """
    best: Dict[str, Any] = {}
    for row in enrichment_rows:
        current = best.get(row.field)
        if current is None or source_rank(row.source) < source_rank(
            current.source
        ):
            best[row.field] = row
    props = dict(raw_tags)
    for field, row in best.items():
        props[field] = json.loads(row.value) if row.value is not None else None
    return props


def ingest_geojson(
    db: GridDatabase,
    region: str,
    layer: str,
    path: str,
    source: str = "ingest-legacy",
    run_id: Optional[str] = None,
) -> Dict[str, int]:
    """Ingest one legacy GeoJSON file into the R/C layers.

    Legacy ingest replaces the whole ``(layer, region)`` slice of both
    ``raw_features`` and ``enrichments`` so re-runs are idempotent.
    Real Overpass fetches must use a different code path that replaces
    only raw features and *never* deletes enrichments.

    Returns:
        ``{'features': n, 'curated_rows': m}``
    """
    with open(path, encoding="utf-8") as fh:
        collection = json.load(fh)
    features = collection.get("features") or []
    meta = {k: v for k, v in collection.items() if k != "features"}

    now = _now_iso()
    # uuid suffix: snapshots are an append-only history log, and two
    # ingest runs within the same second must not collide on the PK.
    snapshot_id = f"{now}_{region}_{layer}_{uuid.uuid4().hex[:8]}"
    seen: Dict[str, int] = {}
    raw_rows: List[Dict[str, Any]] = []
    enr_rows: List[Dict[str, Any]] = []

    for seq, feature in enumerate(features):
        key, osm_type, osm_id = feature_key_for(feature)
        count = seen.get(key, 0)
        seen[key] = count + 1
        if count:
            key = f"{key}#{count + 1}"
        raw_tags, curated = decompose_properties(
            feature.get("properties") or {}
        )
        raw_rows.append(
            {
                "layer": layer,
                "region": region,
                "feature_key": key,
                "osm_type": osm_type,
                "osm_id": osm_id,
                "tags": _dumps(raw_tags),
                "geometry": _dumps(feature.get("geometry")),
                "seq": seq,
                "first_seen": now,
                "last_seen": now,
                "active": 1,
                "snapshot_id": snapshot_id,
            }
        )
        for field, value, src in curated:
            enr_rows.append(
                {
                    "layer": layer,
                    "region": region,
                    "feature_key": key,
                    "field": field,
                    "source": src,
                    "value": _dumps(value),
                    "confidence": None,
                    "run_id": run_id,
                    "updated_at": now,
                }
            )

    with db.session_factory() as session:
        session.execute(
            delete(RawFeature).where(
                RawFeature.layer == layer, RawFeature.region == region
            )
        )
        session.execute(
            delete(Enrichment).where(
                Enrichment.layer == layer, Enrichment.region == region
            )
        )
        for i in range(0, len(raw_rows), _INSERT_CHUNK):
            session.execute(insert(RawFeature), raw_rows[i : i + _INSERT_CHUNK])
        for i in range(0, len(enr_rows), _INSERT_CHUNK):
            session.execute(insert(Enrichment), enr_rows[i : i + _INSERT_CHUNK])
        session.add(
            Snapshot(
                snapshot_id=snapshot_id,
                region=region,
                layer=layer,
                fetched_at=now,
                source=source,
                feature_count=len(features),
                collection_meta=_dumps(meta),
            )
        )
        session.commit()

    return {"features": len(raw_rows), "curated_rows": len(enr_rows)}


def export_geojson(
    db: GridDatabase, region: str, layer: str
) -> Dict[str, Any]:
    """Compose the D-layer FeatureCollection for one (region, layer).

    Features come back in original file order (``seq``); the collection
    envelope (``name``, ``crs``) is restored from the latest snapshot.
    """
    with db.session_factory() as session:
        raw = (
            session.execute(
                select(RawFeature)
                .where(
                    RawFeature.layer == layer, RawFeature.region == region
                )
                .order_by(RawFeature.seq)
            )
            .scalars()
            .all()
        )
        enr = (
            session.execute(
                select(Enrichment).where(
                    Enrichment.layer == layer, Enrichment.region == region
                )
            )
            .scalars()
            .all()
        )
        snap = (
            session.execute(
                select(Snapshot)
                .where(Snapshot.region == region, Snapshot.layer == layer)
                .order_by(
                    Snapshot.fetched_at.desc(), Snapshot.snapshot_id.desc()
                )
            )
            .scalars()
            .first()
        )

    by_key: Dict[str, List[Enrichment]] = {}
    for row in enr:
        by_key.setdefault(row.feature_key, []).append(row)

    features = [
        {
            "type": "Feature",
            "properties": compose_properties(
                json.loads(r.tags), by_key.get(r.feature_key, ())
            ),
            "geometry": json.loads(r.geometry),
        }
        for r in raw
    ]

    if snap is not None and snap.collection_meta:
        collection: Dict[str, Any] = json.loads(snap.collection_meta)
    else:
        collection = {"type": "FeatureCollection"}
    collection["features"] = features
    return collection


def verify_roundtrip(
    db: GridDatabase, region: str, layer: str, path: str, max_report: int = 10
) -> List[str]:
    """Golden check: exported collection vs the original file.

    Compares the collection envelope and every feature as decoded JSON
    (dict equality — key order independent, float-exact because both
    sides pass through the same JSON round-trip).

    Returns:
        A list of human-readable problems; empty means equivalent.
    """
    with open(path, encoding="utf-8") as fh:
        original = json.load(fh)
    exported = export_geojson(db, region, layer)

    problems: List[str] = []
    orig_meta = {k: v for k, v in original.items() if k != "features"}
    exp_meta = {k: v for k, v in exported.items() if k != "features"}
    if orig_meta != exp_meta:
        problems.append(
            f"collection metadata differs: {orig_meta!r} != {exp_meta!r}"
        )

    orig_feats = original.get("features") or []
    exp_feats = exported.get("features") or []
    if len(orig_feats) != len(exp_feats):
        problems.append(
            f"feature count {len(orig_feats)} != {len(exp_feats)}"
        )
    for i, (a, b) in enumerate(zip(orig_feats, exp_feats)):
        if a != b:
            problems.append(f"feature[{i}] differs")
            if len(problems) >= max_report:
                problems.append("… (further diffs suppressed)")
                break
    return problems


def dump_enrichments_jsonl(db: GridDatabase, path: str) -> int:
    """Write the C layer as sorted JSONL (the tracked curation backup).

    Volatile fields (``updated_at``, ``run_id``) are deliberately
    omitted so re-ingest runs do not churn the tracked diff; the full
    detail stays in the database itself.
    """
    with db.session_factory() as session:
        rows = (
            session.execute(
                select(Enrichment).order_by(
                    Enrichment.layer,
                    Enrichment.region,
                    Enrichment.feature_key,
                    Enrichment.field,
                    Enrichment.source,
                )
            )
            .scalars()
            .all()
        )
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            record = {
                "layer": r.layer,
                "region": r.region,
                "feature_key": r.feature_key,
                "field": r.field,
                "source": r.source,
                "value": json.loads(r.value) if r.value is not None else None,
            }
            if r.confidence is not None:
                record["confidence"] = r.confidence
            fh.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            )
    return len(rows)
