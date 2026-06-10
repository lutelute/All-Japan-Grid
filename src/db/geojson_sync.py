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
- :func:`apply_enrichments` / :func:`find_feature_keys` — the C-layer
  write path (Step 3): mechanical curation that survives OSM re-fetch
  because it is keyed by feature identity, not stored in the raw file.
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
import os
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
    "p03_db",                  # DB-native enrichers (src.db.enrich)
    "enrich_lines_endpoints",
    "overpass_db",
    "geocode_db",
    "endpoint_matching",       # legacy marker (ingest-extracted)
    "geocode_promotion",
    "nominatim",
    "legacy_marker",
)

_OSM_PREFIX = {"node": "n", "way": "w", "relation": "r"}
_INSERT_CHUNK = 2000

#: Enrichment sources that the legacy ingest owns and refreshes. Manual /
#: audit / external curation uses other source labels and is never touched
#: by ingest, so it survives an OSM re-fetch (docs/DB_ARCHITECTURE.md).
LEGACY_SOURCES: Tuple[str, ...] = (
    "legacy_marker", "nominatim", "endpoint_matching",
    "geocode_promotion", "p03", "overpass", "jrp_lite",
)


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

    Re-runs are idempotent. Ingest replaces all ``raw_features`` for the
    ``(layer, region)`` slice but deletes only the **legacy-derived**
    enrichments it owns (:data:`LEGACY_SOURCES`); ``manual`` / external
    curation is preserved, so it survives both a re-ingest and a future
    OSM re-fetch. (A real Overpass fetch path will likewise replace only
    raw features.)

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
        # Only clear the legacy-derived enrichments this ingest re-writes;
        # manual / external curation (other sources) is preserved.
        session.execute(
            delete(Enrichment).where(
                Enrichment.layer == layer,
                Enrichment.region == region,
                Enrichment.source.in_(LEGACY_SOURCES),
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


def iter_composed(
    db: GridDatabase, region: str, layer: str
) -> List[Tuple[str, Dict[str, Any], Any]]:
    """Composed features for one (region, layer), in original file order.

    Returns a list of ``(feature_key, properties, geometry)`` tuples — the
    raw ⟕ enrichments effective view, keyed by feature identity so a
    DB-native enricher (:mod:`src.db.enrich`) can write its results back to
    the right feature. Used internally by :func:`export_geojson`.
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
    by_key: Dict[str, List[Enrichment]] = {}
    for row in enr:
        by_key.setdefault(row.feature_key, []).append(row)
    return [
        (
            r.feature_key,
            compose_properties(json.loads(r.tags), by_key.get(r.feature_key, ())),
            json.loads(r.geometry),
        )
        for r in raw
    ]


def export_geojson(
    db: GridDatabase, region: str, layer: str
) -> Dict[str, Any]:
    """Compose the D-layer FeatureCollection for one (region, layer).

    Features come back in original file order (``seq``); the collection
    envelope (``name``, ``crs``) is restored from the latest snapshot.
    """
    with db.session_factory() as session:
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

    features = [
        {"type": "Feature", "properties": props, "geometry": geom}
        for _key, props, geom in iter_composed(db, region, layer)
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


def find_feature_keys(
    db: GridDatabase,
    layer: str,
    region: str,
    *,
    name: Optional[str] = None,
    osm_id: Optional[int] = None,
) -> List[str]:
    """Locate feature_keys by human-friendly attributes (curation helper).

    ``name`` matches the *effective* name (raw tag or any enrichment),
    so a feature already renamed by a previous curation step is still
    found.  Returns every match (names are not unique).  Passing neither
    selector returns ``[]`` rather than the whole layer, so a curation
    edit can never accidentally fan out to every feature.
    """
    if name is None and osm_id is None:
        return []
    with db.session_factory() as session:
        raw = (
            session.execute(
                select(RawFeature).where(
                    RawFeature.layer == layer, RawFeature.region == region
                )
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
    by_key: Dict[str, List[Enrichment]] = {}
    for row in enr:
        by_key.setdefault(row.feature_key, []).append(row)

    hits: List[str] = []
    for r in raw:
        if osm_id is not None and r.osm_id != osm_id:
            continue
        if name is not None:
            props = compose_properties(json.loads(r.tags), by_key.get(r.feature_key, ()))
            if props.get("name") != name:
                continue
        hits.append(r.feature_key)
    return hits


def apply_enrichments(
    db: GridDatabase,
    rows: Sequence[Dict[str, Any]],
    run_id: Optional[str] = None,
) -> int:
    """Upsert curated field values into the C layer (Step 3 write path).

    Each row is ``{layer, region, feature_key, field, value}`` with an
    optional ``source`` (default ``'manual'``) and ``confidence``.  The
    primary key is ``(layer, region, feature_key, field, source)`` so a
    manual override coexists with — and, per :data:`SOURCE_PRIORITY`,
    wins over — the legacy markers; it is never written into the raw
    feature, so a later OSM re-fetch re-applies it automatically.

    Returns:
        Number of rows upserted.
    """
    now = _now_iso()
    with db.session_factory() as session:
        for row in rows:
            source = row.get("source", "manual")
            existing = session.get(
                Enrichment,
                {
                    "layer": row["layer"],
                    "region": row["region"],
                    "feature_key": row["feature_key"],
                    "field": row["field"],
                    "source": source,
                },
            )
            value = _dumps(row["value"]) if "value" in row else None
            if existing is None:
                session.add(
                    Enrichment(
                        layer=row["layer"],
                        region=row["region"],
                        feature_key=row["feature_key"],
                        field=row["field"],
                        source=source,
                        value=value,
                        confidence=row.get("confidence"),
                        run_id=run_id,
                        updated_at=now,
                    )
                )
            else:
                existing.value = value
                existing.confidence = row.get("confidence", existing.confidence)
                existing.run_id = run_id
                existing.updated_at = now
        session.commit()
    return len(rows)


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


def load_enrichments_jsonl(db: GridDatabase, path: str, regions=None) -> int:
    """Load a curation backup written by :func:`dump_enrichments_jsonl` back
    into the C layer — the *restore* half of the tracked backup.

    Each JSONL record (``{layer, region, feature_key, field, source, value,
    [confidence]}``) is upserted via :func:`apply_enrichments`, so the load is
    idempotent and the restored curation is keyed by feature identity (it
    survives a later OSM re-fetch). This is what makes committed curation —
    P03 authoritative data, manual fixes — actually take effect on a fresh
    ``ingest`` rebuild instead of being a write-only backup.

    ``regions`` optionally restricts the load to a set/list of region names
    (so a single-region ingest doesn't apply orphan rows for other regions).

    Returns the number of enrichment rows applied (0 if the file is absent).
    """
    if not os.path.exists(path):
        return 0
    keep = set(regions) if regions is not None else None
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if keep is None or rec.get("region") in keep:
                rows.append(rec)
    if rows:
        apply_enrichments(db, rows, run_id="load_enrichments_jsonl")
    return len(rows)
