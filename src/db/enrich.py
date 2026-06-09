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

#: Source for DB-native reverse-geocoded display names (Nominatim). Distinct
#: from the legacy 'nominatim'/'geocode_promotion' markers so re-ingest of
#: raw OSM keeps it. The exported _name_source value stays 'geocoded'/'name:en'.
GEOCODE_SOURCE = "geocode_db"


def enrich_geocode(db: GridDatabase, region: str, layer: str,
                   suffix: str, geocoder=None) -> Dict[str, int]:
    """Reverse-geocode unnamed substations/plants into the C layer.

    The DB-native form of ``enrich_substations_geocode`` /
    ``enrich_plants_geocode``: for each feature with no effective name and
    no ``_display_name``, fall back to ``name:en`` or a reverse-geocoded
    ``{area}{suffix}`` (e.g. ``{area}変電所``), writing ``_display_name`` /
    ``_name_source`` ``geocode_db`` enrichments instead of editing the
    GeoJSON.

    ``geocoder`` is a ``(lat, lon) -> address_dict`` callable — defaults to
    the live Nominatim reverse-geocoder (network, 1.1 s/req rate limit, so
    real runs belong on the server) and is injected as a stub in tests.
    """
    from scripts.enrich_substations_geocode import (
        construct_name as _construct,
        reverse_geocode as _default_geocoder,
    )

    geocoder = geocoder or _default_geocoder
    # construct_name hard-codes 変電所; honour the requested suffix.
    def name_from(addr):
        n = _construct(addr)
        return n[:-3] + suffix if n.endswith("変電所") else n

    rows = []
    total = enriched = 0
    for fkey, props, geom in iter_composed(db, region, layer):
        total += 1
        if (props.get("name") or props.get("name:ja") or "").strip():
            continue
        if (props.get("_display_name") or "").strip():
            continue

        name_en = (props.get("name:en") or "").strip()
        if name_en:
            disp, src = name_en, "name:en"
        else:
            lat, lon = _centroid(geom)
            if lat is None:
                continue
            disp = name_from(geocoder(lat, lon))
            if not disp:
                continue
            src = "geocoded"

        rows.append({"layer": layer, "region": region, "feature_key": fkey,
                     "field": "_display_name", "value": disp,
                     "source": GEOCODE_SOURCE})
        rows.append({"layer": layer, "region": region, "feature_key": fkey,
                     "field": "_name_source", "value": src,
                     "source": GEOCODE_SOURCE})
        enriched += 1

    if rows:
        apply_enrichments(db, rows, run_id=f"enrich_geocode_{layer}")
    return {"total": total, "enriched": enriched}


def _centroid(geom):
    """(lat, lon) of a Point/Polygon/MultiPolygon geometry, or (None, None)."""
    from scripts.enrich_substations_geocode import get_centroid
    return get_centroid({"geometry": geom, "properties": {}})


#: Source for DB-native Overpass tag enrichment (name/operator/fuel from OSM).
OVERPASS_SOURCE = "overpass_db"


def enrich_overpass(db: GridDatabase, region: str, layer: str,
                    fetcher=None) -> Dict[str, int]:
    """Fill missing name/operator/fuel from OSM tags into the C layer.

    The DB-native form of ``enrich_overpass_tags``: for each feature that
    has an ``osm_id`` but is missing name/operator/fuel_type, fetch the
    live OSM tags and write the resolved fields as ``overpass_db``
    enrichments (reusing ``apply_tags_to_feature`` to compute exactly the
    same fields the GeoJSON enricher would set).

    ``fetcher`` is an ``(osm_ids) -> {osm_id: tags_dict}`` callable —
    defaults to the live Overpass batch query (network / rate-limited, so
    real runs belong on the server) and is stubbed in tests.
    """
    from scripts.enrich_overpass_tags import (
        apply_tags_to_feature,
        fetch_overpass_batch,
        needs_enrichment,
    )

    def _default_fetcher(osm_ids):
        elements = fetch_overpass_batch(osm_ids) or []
        return {e["id"]: e.get("tags", {}) for e in elements if "id" in e}

    fetcher = fetcher or _default_fetcher

    pending = [(fkey, props) for fkey, props, _g in iter_composed(db, region, layer)
               if needs_enrichment(props)]
    osm_ids = [int(p["osm_id"]) for _k, p in pending if p.get("osm_id")]
    if not osm_ids:
        return {"pending": 0, "enriched": 0}
    tags_by_id = fetcher(osm_ids) or {}

    rows = []
    enriched = 0
    for fkey, props in pending:
        oid = int(props["osm_id"]) if props.get("osm_id") else None
        tags = tags_by_id.get(oid)
        if not tags:
            continue
        work = dict(props)
        if apply_tags_to_feature(work, tags, {}):
            for k, v in work.items():
                if props.get(k) != v:
                    rows.append({
                        "layer": layer, "region": region, "feature_key": fkey,
                        "field": k, "value": v, "source": OVERPASS_SOURCE})
            enriched += 1
    if rows:
        apply_enrichments(db, rows, run_id=f"enrich_overpass_{layer}")
    return {"pending": len(pending), "enriched": enriched}


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
