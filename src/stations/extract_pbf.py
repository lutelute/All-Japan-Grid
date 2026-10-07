"""Read the station inputs of :func:`all_eu_grid.stations.model` from a power PBF.

One pass over the same power-filtered PBF the R layer was ingested from
(``osmium tags-filter nwr/power r/route=power``, referenced nodes included):

* conductors: ``power=line|cable|minor_line|minor_cable|busbar|bay`` and ``line=busbar|bay``,
  with their **ordered node ids** and coordinates — kept when a vertex stands within
  ``buffer_m`` of a site footprint (the rest never reaches a station);
* devices: ``power=transformer|switch`` (nodes and ways), and supports
  (``power=pole|tower|portal``) carrying exactly one recognised ``transformer=*`` or
  ``switch=*`` (All-AU-Grid's ``hosted_kind``; the original ``power`` tag is kept);
* ``power=circuit`` and ``route=power`` relations with their members.

Not in service (``disused`` / ``construction`` ... flags) conductors are counted and left
out, as in the topology step. Sites come from the caller (the DB's substation and plant
tables) or, for a standalone run, from the PBF's own areas.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import time
from collections import Counter
from pathlib import Path

import numpy as np
import osmium
import shapely
import shapely.wkb
from shapely.geometry import mapping

from .core import CONDUCTOR_POWER, INTERNAL, _buffer_deg


def _lifecycle_state(tags) -> str | None:
    """'disused' / 'abandoned' / 'construction' / 'proposed' / 'planned' — 運用中でない設備。
    All-EU-Grid ``extract._lifecycle_state`` と同じ(接頭辞 disused:power=* とフラグの両方)。"""
    for st in ("disused", "abandoned", "construction", "proposed", "planned"):
        if tags.get(st) in ("yes", "true") or f"{st}:power" in tags:
            return st
    return None


SITE_POWER = ("substation", "converter", "plant")
TRANSFORMER = {"yes", "distribution", "main", "generator", "auxiliary", "traction", "auto", "booster",
               "converter", "phase_angle_regulator", "yes;distribution"}
SWITCH = {"yes", "disconnector", "circuit_breaker", "mechanical", "load_break_switch", "earthing",
          "fuse", "recloser"}
MEMBER = {"n": "node", "w": "way", "r": "relation"}


def hosted_kind(tags) -> str | None:
    """One explicitly tagged device on a support; composite or unknown tags stay supports."""
    if tags.get("power") not in ("pole", "tower", "portal"):
        return None
    t = tags.get("transformer") in TRANSFORMER
    s = tags.get("switch") in SWITCH
    if t == s:
        return None
    return "transformer" if t else "switch"


def md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def read_sites(pbf: Path) -> list:
    """power=substation|converter|plant areas and nodes, as features (standalone runs)."""
    wkb = osmium.geom.WKBFactory()
    sites = []
    fp = (osmium.FileProcessor(str(pbf)).with_locations()
          .with_areas(osmium.filter.KeyFilter("power")).with_filter(osmium.filter.EmptyTagFilter()))
    for o in fp:
        if o.is_area():
            if o.tags.get("power") not in SITE_POWER:
                continue
            try:
                g = shapely.wkb.loads(wkb.create_multipolygon(o), hex=True)
            except Exception:  # noqa: BLE001 - broken multipolygons are skipped, as in extract
                continue
            g = g.geoms[0] if len(g.geoms) == 1 else g
            ot, oid = ("way" if o.from_way() else "relation"), o.orig_id()
        elif o.is_node() and o.tags.get("power") in SITE_POWER and o.location.valid():
            g, ot, oid = shapely.Point(o.location.lon, o.location.lat), "node", o.id
        else:
            continue
        t = dict(o.tags)
        sites.append({"type": "Feature", "geometry": g,
                      "properties": {"osm_type": ot, "osm_id": oid, "power": t.get("power"),
                                     **{k: t[k] for k in ("voltage", "frequency", "operator", "name") if k in t}}})
    return sites


def read(pbf: Path, sites: list, buffer_m: float = 25.0) -> dict:
    """-> {lines, elements, stats}: everything within ``buffer_m`` of a site polygon."""
    reach = [_buffer_deg(f["geometry"], buffer_m + 5).envelope for f in sites
             if f["geometry"].geom_type in ("Polygon", "MultiPolygon")]
    tree = shapely.STRtree(reach)
    stats = Counter()
    lines, elements = [], []

    def near(xy) -> bool:
        if len(xy) == 1:
            return len(tree.query(shapely.points(xy[0]))) > 0
        lo, hi = np.min(xy, axis=0), np.max(xy, axis=0)
        if not len(tree.query(shapely.box(lo[0], lo[1], hi[0], hi[1]))):
            return False
        return len(tree.query(shapely.points(xy), predicate="intersects")[0]) > 0

    fp = (osmium.FileProcessor(str(pbf)).with_locations()
          .with_filter(osmium.filter.EmptyTagFilter()))
    for o in fp:
        t = o.tags
        p = t.get("power")
        if o.is_node():
            kind = p if p in ("transformer", "switch") else hosted_kind(t)
            if not kind or not o.location.valid():
                continue
            xy = np.array([[o.location.lon, o.location.lat]])
            if not near(xy):
                stats[f"{kind}_node_away"] += 1
                continue
            e = {"type": "node", "id": o.id, "lon": o.location.lon, "lat": o.location.lat, "tags": dict(t)}
            if p != kind:
                e["_equipment_kind"], e["_classification_method"] = kind, "explicit_hosted_device_tag"
                stats[f"hosted_{kind}"] += 1
            stats[f"{kind}_node"] += 1
            elements.append(e)
        elif o.is_way():
            conductor = p in CONDUCTOR_POWER or (t.get("line") in INTERNAL and p)
            if not conductor and p not in ("transformer", "switch"):
                continue
            nodes, coords = [], []
            for nr in o.nodes:
                if not nr.location.valid():
                    stats["way_missing_location"] += 1
                    break
                nodes.append(nr.ref)
                coords.append((nr.lon, nr.lat))
            else:
                if len(coords) < 2:
                    continue
                xy = np.array(coords)
                if not near(xy):
                    stats["conductor_away" if conductor else f"{p}_way_away"] += 1
                    continue
                tags = dict(t)
                if conductor:
                    if _lifecycle_state(tags):
                        stats["conductor_not_in_service"] += 1
                        continue
                    if p in ("busbar", "bay") and "line" not in tags:
                        tags["line"] = p
                    stats[f"conductor_{tags.get('line') if tags.get('line') in INTERNAL else p}"] += 1
                    lines.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
                                  "properties": {**tags, "osm_type": "way", "osm_id": o.id, "node_ids": nodes}})
                else:
                    stats[f"{p}_way"] += 1
                    elements.append({"type": "way", "id": o.id, "tags": tags, "nodes": nodes,
                                     "geometry": [{"lon": x, "lat": y} for x, y in coords]})
        elif o.is_relation() and (p == "circuit" or t.get("route") == "power"):
            stats["circuit_relation"] += 1
            elements.append({"type": "relation", "id": o.id, "tags": dict(t),
                             "members": [{"type": MEMBER[m.type], "ref": m.ref, "role": m.role} for m in o.members]})
    return {"lines": lines, "elements": elements, "stats": dict(sorted(stats.items()))}


def read_cached(pbf: Path, sites: list, cache: Path | None, buffer_m: float = 25.0) -> dict:
    """:func:`read`, kept next to the PBF's md5 and the site set it was filtered by."""
    sig = {"pbf": str(pbf), "md5": md5(pbf), "sites": len(sites), "buffer_m": buffer_m}
    if cache and cache.exists():
        with open(cache, "rb") as f:
            got = pickle.load(f)
        if got.get("signature") == sig:
            return got
    t0 = time.time()
    got = {"signature": sig, **read(pbf, sites, buffer_m)}
    got["stats"]["read_seconds"] = round(time.time() - t0)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        with open(cache, "wb") as f:
            pickle.dump(got, f, protocol=pickle.HIGHEST_PROTOCOL)
    return got


def main(argv=None):
    """Standalone: sites from the PBF itself -> model rows summary (``--json`` writes them)."""
    from .core import model
    from .views import analyse, coverage
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pbf", type=Path)
    ap.add_argument("--json", type=Path, help="write the model rows here")
    a = ap.parse_args(argv)
    t0 = time.time()
    sites = read_sites(a.pbf)
    got = read(a.pbf, sites)
    data = model(sites, got["lines"], got["elements"])
    views = analyse(data)
    cov = coverage(data, views)
    summary = {"sites": len(sites), "read": got["stats"], "seconds": round(time.time() - t0),
               "rows": {k: len(v) for k, v in data.items() if isinstance(v, list)},
               "status": dict(Counter(c["status"] for c in cov.values())),
               "issues": dict(Counter(i["code"] for i in data["issues"]))}
    print(json.dumps(summary, indent=1))
    if a.json:
        def default(o):
            return mapping(o) if hasattr(o, "geom_type") else str(o)
        a.json.write_text(json.dumps({"summary": summary, "data": {k: v for k, v in data.items() if k != "sites"},
                                      "coverage": cov, "bays": views["bays"]}, default=default))


if __name__ == "__main__":
    main()
