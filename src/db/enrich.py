"""DB-native enrichment (DB unification Step 3b).

Re-expresses the offline enrichers so they write to the C layer
(``enrichments``) instead of mutating ``data/*.geojson`` in place. The
result survives an OSM re-fetch (it is keyed by feature identity) and is
regenerated into GeoJSON by ``scripts/db/export.py`` — closing the
mechanical-update loop for a real enricher, not just manual curation.

Currently covers :func:`enrich_lines_endpoints` (pure geometry, no
network APIs). The Nominatim / Overpass / P03 enrichers follow the same
shape but must run on the compute server (live APIs / un-fetched P03 GML)
— see ``docs/DB_ARCHITECTURE.md`` Step 3b/4.

The naming algorithm itself is shared verbatim with the GeoJSON enricher
(``scripts.enrich_lines_endpoints.assign_line_name``) so both paths
produce identical names.
"""

from __future__ import annotations

from typing import Dict

from src.db.geojson_sync import apply_enrichments, iter_composed
from src.db.grid_db import GridDatabase
from src.regions import REGION_JA, region_config

#: Enrichment source for DB-native endpoint line naming. Deliberately
#: distinct from the legacy ``endpoint_matching`` marker (which ingest
#: owns and clears): a DB-native enrichment must survive an OSM re-fetch,
#: so it uses its own source not listed in geojson_sync.LEGACY_SOURCES.
#: The exported ``_enriched_by`` *value* stays ``endpoint_matching`` for
#: GeoJSON compatibility.
ENDPOINT_SOURCE = "enrich_lines_endpoints"
ENDPOINT_MARKER = "endpoint_matching"

#: Source for the Category-C tag-error fix (audit --fix → DB). Curation
#: that survives re-ingest, so it uses 'audit_fix' (already high in
#: SOURCE_PRIORITY, above the legacy markers).
AUDIT_SOURCE = "audit_fix"


def apply_audit_fixes(db: GridDatabase, regions=None) -> Dict[str, int]:
    """Clear Category-C substation tag errors into the C layer (audit --fix).

    Mirrors ``scripts/audit_substation_plant_overlap.fix_category_c`` but
    writes ``substation = null`` ``audit_fix`` enrichments instead of
    editing the GeoJSON: a substation whose ``substation`` tag holds a
    facility name (not a valid type) gets the bogus value cleared, and the
    fix survives an OSM re-fetch. ``audit_region`` detects the errors from
    the source files; the matching feature is located in the DB by its raw
    ``substation`` value.

    Returns ``{'fixed': n}``.
    """
    from scripts.audit_substation_plant_overlap import audit_region
    from src.server.geojson_loader import REGIONS as _ALL

    regions = regions or _ALL
    rows = []
    fixed = 0
    for region in regions:
        _a, _b, cat_c, _d, _coloc = audit_region(region)
        if not cat_c:
            continue
        bad_vals = {item["bad_substation_value"] for item in cat_c}
        for fkey, props, _geom in iter_composed(db, region, "substations"):
            if props.get("substation") in bad_vals:
                rows.append({
                    "layer": "substations", "region": region,
                    "feature_key": fkey, "field": "substation",
                    "value": None, "source": AUDIT_SOURCE,
                })
                fixed += 1
    if rows:
        apply_enrichments(db, rows, run_id="audit_fix")
    return {"fixed": fixed}


def _substation_candidates(db: GridDatabase, region: str):
    """(candidates, name_to_operator) from the composed substations."""
    from scripts.enrich_lines_endpoints import get_centroid, normalize_operator

    candidates = []
    name_to_operator: Dict[str, str] = {}
    for _key, props, geom in iter_composed(db, region, "substations"):
        lat, lon = get_centroid({"geometry": geom, "properties": props})
        if lat is None:
            continue
        name = (props.get("name") or props.get("name:ja") or "").strip()
        if not name:
            name = (props.get("_display_name") or "").strip()
        if not name:
            continue
        candidates.append((name, lat, lon))
        operator = (props.get("operator") or "").strip()
        if operator:
            name_to_operator[name] = normalize_operator(operator)
    return candidates, name_to_operator


def enrich_lines_endpoints(db: GridDatabase, region: str) -> Dict[str, int]:
    """Name unnamed lines from their endpoint substations, into the DB.

    Mirrors ``scripts/enrich_lines_endpoints.enrich_region`` but writes
    ``name`` / ``operator`` / ``_name_source`` / ``_enriched_by`` as
    ``endpoint_matching`` enrichments instead of editing the GeoJSON.

    Returns ``{'total': n, 'enriched': m}``.
    """
    from scripts.enrich_lines_endpoints import (
        assign_line_name,
        normalize_operator,
    )

    candidates, name_to_operator = _substation_candidates(db, region)
    regional_utility = normalize_operator(
        region_config(region).get("utility", "")
    )
    region_ja = REGION_JA.get(region, region)

    rows = []
    total = enriched = 0
    fallback_seq = 0
    for fkey, props, geom in iter_composed(db, region, "lines"):
        total += 1
        if (props.get("name") or "").strip():
            continue
        if not isinstance(geom, dict) or geom.get("type") != "LineString":
            continue
        coords = geom.get("coordinates", [])
        if len(coords) < 2:
            continue

        name, set_operator, name_source, fallback_seq = assign_line_name(
            props, coords, candidates, name_to_operator,
            regional_utility, region_ja, fallback_seq)

        def add(field, value):
            rows.append({
                "layer": "lines", "region": region, "feature_key": fkey,
                "field": field, "value": value, "source": ENDPOINT_SOURCE,
            })

        add("name", name)
        add("_name_source", name_source)
        add("_enriched_by", ENDPOINT_MARKER)
        if set_operator:
            add("operator", set_operator)
        enriched += 1

    if rows:
        apply_enrichments(db, rows, run_id="enrich_lines_endpoints")
    return {"total": total, "enriched": enriched}
