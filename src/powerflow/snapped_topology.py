"""Vertex-graph + tolerance-snap topology builder (additive, A/B candidate).

Motivation
----------
The current ``build_network_from_geojson`` (examples/run_powerflow_all.py)
infers topology by matching each line's two *endpoints* to the nearest
substation within 50 km and **dropping any line whose endpoints resolve to
the same substation**. Empirically this discards the majority of lines
(Tokyo: 6476 / 8295) and ignores line-to-line junctions, leaving the model
fragmented into hundreds of components (Tokyo n_components = 481).

This module builds connectivity from the *full OSM line geometry* instead:

1. Every line vertex becomes a graph node. Consecutive vertices are edges,
   so two lines that share a coordinate (an OSM junction / tap) are connected
   even when no substation sits there.
2. Any vertex within ``snap_km`` of a substation is bound to that substation.
3. Degree-2 junction chains are collapsed into single branches; surviving
   junctions (degree >= 3, real taps) become synthetic buses.

Output is a :class:`GridNetwork` that is drop-in compatible with the existing
pandapower / powerflow downstream, so the two topologies can be compared
under identical solving (A/B). Nothing is fabricated: every branch traces a
real OSM line. Genuine gaps that remain are left to the reconnection step
(``src/reconstruction/reconnector.py``) and surfaced transparently.

Usage::

    python -m src.powerflow.snapped_topology shikoku --snap-km 1.5 --diagnose
    # or, programmatically:
    from src.powerflow.snapped_topology import build_network_snapped
    net = build_network_snapped("shikoku", snap_km=1.5)

(``examples/build_snapped_topology`` remains as a back-compat re-export shim.)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.model.generator import Generator
from src.model.grid_network import GridNetwork
from src.model.substation import Substation
from src.model.transmission_line import TransmissionLine
from src.regions import REGION_FREQUENCY_HZ as REGION_FREQ

# Repo data/ resolved relative to src/powerflow/ (this module was promoted
# here from examples/ — Phase C pipeline promotion).
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")

_DEFAULT_CAPACITY_MW = {
    "nuclear": 1000.0, "coal": 600.0, "gas": 400.0, "oil": 300.0,
    "hydro": 50.0, "solar": 10.0, "wind": 10.0, "biomass": 20.0,
}
_DEFAULT_CAPACITY_FALLBACK = 30.0


# ── geometry helpers ────────────────────────────────────────────────────────

def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _get_centroid(feature):
    geom = feature.get("geometry")
    if not geom:
        return None, None
    t = geom["type"]
    if t == "Point":
        return geom["coordinates"][1], geom["coordinates"][0]
    if t == "Polygon":
        cs = geom["coordinates"][0]
    elif t == "MultiPolygon":
        cs = geom["coordinates"][0][0]
    else:
        return None, None
    return sum(c[1] for c in cs) / len(cs), sum(c[0] for c in cs) / len(cs)


def _get_line_coords(feature):
    geom = feature.get("geometry")
    if not geom:
        return []
    t = geom["type"]
    if t == "LineString":
        return [(c[1], c[0]) for c in geom["coordinates"]]
    if t == "MultiLineString":
        return [(c[1], c[0]) for c in geom["coordinates"][0]]
    return []


def _parse_voltage_kv(voltage_raw):
    # Canonical max-voltage parser in src.utils.voltage; 0.0 if none.
    from src.utils.voltage import parse_voltage_kv
    return parse_voltage_kv(voltage_raw) or 0.0


VALID_VOLTAGES = [66, 77, 110, 132, 154, 187, 220, 275, 500]

# TSO operator name fragments -> home grid frequency. The regional OSM
# slices overlap, so e.g. the chubu (60 Hz) slice contains 1,000+ TEPCO
# (50 Hz) features down the Izu peninsula. Equipment of an opposite-
# frequency TSO cannot be part of this synchronous network, so such
# features are excluded at build time. Same-frequency foreign TSOs are
# KEPT (boundary corridors near ties are often neighbour-operated);
# non-TSO operators (railways, J-POWER, IPPs) are kept everywhere.
_TSO_FREQ = {
    "北海道電力": 50, "東北電力": 50, "東京電力": 50,
    "中部電力": 60, "北陸電力": 60, "関西電力": 60,
    "中国電力": 60, "四国電力": 60, "九州電力": 60, "沖縄電力": 60,
}


def _operator_freq(operator) -> int | None:
    """Home frequency of the operating TSO, or None if not a known TSO."""
    if not operator:
        return None
    for frag, hz in _TSO_FREQ.items():
        if frag in str(operator):
            return hz
    return None


def _freq_excluded(props, region_hz) -> bool:
    """True if the feature does not belong to this region's AC network.

    The OSM ``frequency`` tag is the PRIMARY evidence (map audit
    2026-06-10): an explicit 50/60 decides membership directly —
    multi-valued tags like ``50;60`` (FC station connectors) belong to
    BOTH sides; ``0`` marks DC equipment (HVDC poles such as
    飛騨信濃直流幹線), which is not an AC branch and is represented as an
    async injection instead. Operator→home-frequency inference handles
    only untagged features, so non-TSO 50 Hz assets (J-POWER's
    佐久間東幹線, JR feeders — 75 lines in the chubu slice) are excluded
    by their own tag, while TEPCO-operated ``frequency=60`` lines in the
    Nagano mixed zone are KEPT (the tag outranks the operator guess).
    """
    tokens = []
    for t in str(props.get("frequency") or "").replace("/", ";").split(";"):
        t = t.strip()
        if not t:
            continue
        try:
            tokens.append(float(t))
        except ValueError:
            pass
    if tokens:
        if any(abs(t - region_hz) < 1e-9 for t in tokens):
            return False                       # explicitly ours (incl. 50;60)
        if any(t == 0 for t in tokens):
            return True                        # DC pole
        if any(t in (50.0, 60.0) for t in tokens):
            return True                        # explicitly the other grid
    op_hz = _operator_freq(props.get("operator"))
    return op_hz is not None and op_hz != region_hz


def _clean_voltage(v_kv):
    """Snap a KNOWN voltage to the nearest standard JP transmission class.

    OSM voltage tags carry non-standard / distribution values (22/25/30/33/
    100 kV). Leaving them produces non-standard buses and extreme transformer
    voltage ratios (up to 20:1) that make Ybus ill-conditioned. Snapping to the
    standard classes keeps ratios sane. Unknown (<=0) is preserved so
    ``fix_zero_voltages`` can infer it from connected lines.
    """
    if v_kv <= 0:
        return 0.0
    if v_kv > 600:
        v_kv = (v_kv % 1000) if v_kv > 1000 else 500.0
    return float(min(VALID_VOLTAGES, key=lambda x: abs(x - v_kv)))


# ── spatial index for substation snapping ───────────────────────────────────

class _SubIndex:
    """Coarse lat/lon bucket index for fast nearest-substation snapping."""

    CELL = 0.02  # ~2.2 km latitude cells

    def __init__(self, subs):
        self.buckets = defaultdict(list)
        for slat, slon, sid in subs:
            self.buckets[(round(slat / self.CELL), round(slon / self.CELL))].append((slat, slon, sid))

    def nearest(self, lat, lon, max_km):
        ci, cj = round(lat / self.CELL), round(lon / self.CELL)
        # ring size follows the requested radius (one 0.02-deg cell is
        # ~2.2 km of latitude) so radii beyond the historical 3x3
        # neighbourhood actually search far enough
        r = max(1, int(max_km / (self.CELL * 111.0)) + 1)
        best, bd = None, float("inf")
        for di in range(-r, r + 1):
            for dj in range(-r, r + 1):
                for slat, slon, sid in self.buckets.get((ci + di, cj + dj), ()):  # noqa: E501
                    d = _haversine_km(lat, lon, slat, slon)
                    if d < bd:
                        bd, best = d, sid
        return (best, bd) if best is not None and bd <= max_km else (None, bd)


# ── core builder ─────────────────────────────────────────────────────────────

_WIRES_MAP = {"single": 1, "double": 2, "triple": 3, "quad": 4,
              "sixfold": 6, "eightfold": 8}


def _parse_wires(props):
    """Conductor-bundle count from the OSM wires tag (max across
    ';'-separated per-circuit values); 0 = no evidence."""
    raw = props.get("wires")
    if not raw:
        return 0
    best = 0
    for part in str(raw).split(";"):
        part = part.strip().lower()
        if part.isdigit():
            best = max(best, int(part))
        else:
            best = max(best, _WIRES_MAP.get(part, 0))
    return min(best, 8)


def _parse_circuits(props):
    """Parallel-circuit count from OSM evidence: circuits tag, else cables/3.

    Returns (count, source) where source is "tag" / "cables" / None (no
    evidence — caller falls back to geometric inference, counting 1 per
    way). Clamped to [1, 8] against junk values.
    """
    raw = props.get("circuits")
    if raw not in (None, ""):
        try:
            n = int(str(raw).replace(";", "/").split("/")[0])
            return max(1, min(n, 8)), "tag"
        except ValueError:
            pass
    raw = props.get("cables")
    if raw not in (None, ""):
        try:
            n = int(str(raw).replace(";", "/").split("/")[0]) // 3
            if n >= 1:
                return min(n, 8), "cables"
        except ValueError:
            pass
    return 1, None


def _resolve_db(db):
    """Accept a GridDatabase instance or a path string; None passes through."""
    if db is None or not isinstance(db, str):
        return db
    from src.db.grid_db import GridDatabase
    return GridDatabase(db)


def build_network_snapped(region, snap_km=1.5, vertex_prec=4, keep_stubs=True,
                          polygon_bind=True, poly_edge_km=0.15,
                          fallback_snap_km=0.4, fallback_endpoint_km=0.6,
                          tip_joint_km=0.12, leadin_km=1.5,
                          min_voltage_kv=22.0, return_geom=False, data_dir=None,
                          multi_voltage=True, endpoint_snap_km=2.5,
                          propagate_voltage=True, db=None, tap_snap_km=0.12):
    """Build a GridNetwork via vertex-graph + tolerance snapping.

    Args:
        region: region key.
        data_dir: directory holding ``{region}_*.geojson`` (defaults to the
            repo ``data/`` — injectable for tests).
        snap_km: bind a line vertex to a substation within this radius (km).
        vertex_prec: decimal places to merge near-coincident vertices
            (4 ~= 11 m). Lines sharing a coordinate within this precision
            are treated as electrically connected.
        keep_stubs: keep degree-1 dangling junction buses if True.
        min_voltage_kv: skip line features with a KNOWN voltage below this
            (non-transmission distribution/industrial mistags, e.g. a 2 kV
            OSM line). Lines with unknown voltage (0) are kept so legitimate
            unlabelled transmission is not lost.
        endpoint_snap_km: snap radius for a line's TERMINAL vertices.
            Measured on real data (2026-06-10): 6-8% of line endpoints sit
            1.5-2.5 km from their substation (digitisation stops at the
            yard fence) — kansai +506, tokyo +1,340 endpoints recovered at
            2.5 km. Interior vertices keep the tighter ``snap_km`` so
            corridors passing near a substation are not falsely fused.
            Both radii apply only when ``polygon_bind`` is off (or as the
            legacy path when shapely is unavailable).
        polygon_bind: OSM-faithful binding (owner directive 2026-06-12
            「まずはOSMにちゃんと忠実に系統作ってほしい」): a vertex binds to a
            substation when it lies INSIDE the substation's OSM polygon or
            within ``poly_edge_km`` of its boundary — the criterion the map
            itself draws. The blind centroid radius was the measured source
            of BOTH false binds (3,365 tokyo lines attached to substations
            their path never approaches within 1 km) and big-yard misses
            (北総 275 kV left with deg=1): it survives only as a small
            fallback (``fallback_snap_km`` interior /
            ``fallback_endpoint_km`` terminal) for point-mapped
            substations and polygon gaps.
            Measured A/B with tip_joint_km=0.12 + leadin_km=1.5 (tokyo,
            ledger 84): implicit wrong-binds 3,365 -> 0, trunk rho
            .615 -> .647, 154 kV rho .095 -> .215, 66 kV in-band.
            DEFAULT ON since ledger 85: the west-island AC loss that
            first blocked adoption was the prune ladder stopping at 20
            degrees (the de-fused island carries longer honest radials),
            cured by the 12-degree rung — not the short joint edges
            (floor A/B: bit-identical vmin with and without).
        tip_joint_km: join a degree-1 junction TIP to the nearest node of
            the SAME class within this distance (node-to-node complement
            of ``tap_snap_km``'s node-to-segment join). Owner directive:
            「物理的に明らかにそこには線が存在するのを繋げばいいだけ」 — a tip
            metres from another node is the same pole; parallel corridors
            are untouched because only dead-end tips qualify and the class
            guard blocks cross-voltage fusion.
        propagate_voltage: infer the class of voltage-untagged features
            from the corridor they continue: when ALL the known classes
            seen at a feature's vertices agree on exactly one class, the
            feature adopts it (iterated, so the inference walks through
            chains of untagged segments). This is the hokuriku case
            study's root cause — its main 154 kV corridor is 23%
            untagged, which severed the backbone cut and forced an
            11.1% synthetic-line rate. Ambiguous vertices (two classes
            present) are left unknown; inferred branches carry
            ``kv=prop`` provenance, tagged ones ``kv=tag``.
        multi_voltage: model substations as one bus PER voltage class with
            explicit intra-substation transformer stubs (the real busbar
            structure), instead of one bus at the substation's tagged
            voltage. The single-bus form made ``insert_transformers``
            swallow every cross-voltage *line* into a transformer —
            discarding the line's impedance and creating the pathological
            voltage ratios behind the west-island AC failures. Junctions
            are also keyed by voltage class, so two lines of different
            known classes crossing at a shared tower coordinate are no
            longer fused into a false electrical connection (~1% of
            vertices); unknown-voltage lines join the highest known class
            present at the coordinate (their usual continuation).

        db: a ``GridDatabase`` instance or path (e.g. ``data/grid.db``).
            When given, the three layers are composed IN MEMORY from the
            unified database (raw ⟕ enrichments effective view) instead of
            reading ``data/*.geojson`` — the whole power-flow pipeline then
            reproduces from ``ajgrid db ingest`` alone (VISION step 5).
            Round-trip equivalence with the file path is regression-tested.

    Returns:
        GridNetwork with real substations + synthetic junction buses + branches
        tracing real OSM line geometry. Returns None if data missing.
    """
    data_dir = data_dir or DATA_DIR
    db = _resolve_db(db)

    def _layer(layer):
        if db is not None:
            from src.db.geojson_sync import export_geojson
            try:
                fc = export_geojson(db, region, layer)
            except Exception:
                return None
            return fc if fc.get("features") else fc
        path = os.path.join(data_dir, f"{region}_{layer}.geojson")
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    freq = REGION_FREQ.get(region, 50)
    net = GridNetwork(region=region, frequency_hz=freq)

    subs_data = _layer("substations")
    if not subs_data:
        return None

    sub_coords = []   # (lat, lon, sub_id)
    sub_info = {}     # sub_id -> dict(name, lat, lon, own_cls)
    sub_polys = []    # (geometry dict, sub_id) for polygon-first binding
    for i, feat in enumerate(subs_data["features"]):
        lat, lon = _get_centroid(feat)
        if lat is None:
            continue
        props = feat["properties"]
        if _freq_excluded(props, freq):
            continue   # not part of this synchronous network
        sid = f"{region}_sub_{i}"
        vkv = _parse_voltage_kv(props.get("voltage"))
        # A spurious sub-transmission tag (e.g. 2 kV) on a substation that
        # actually sits on a 66+ kV line creates a huge per-unit mismatch.
        # Treat known-low voltages as unknown (0) so fix_zero_voltages infers
        # the real level from the connected transmission lines.
        if 0 < vkv < min_voltage_kv:
            vkv = 0.0
        sub_info[sid] = {"name": props.get("name") or sid, "lat": lat,
                         "lon": lon, "own_cls": _clean_voltage(vkv)}
        sub_coords.append((lat, lon, sid))
        if polygon_bind and feat.get("geometry", {}).get("type") in (
                "Polygon", "MultiPolygon"):
            sub_polys.append((feat["geometry"], sid))

    index = _SubIndex(sub_coords)

    # OSM-faithful polygon binding (see docstring). shapely is an optional
    # path: without it the legacy centroid radii apply unchanged.
    poly_tree = poly_geoms = poly_sids = None
    if polygon_bind and sub_polys:
        try:
            from shapely.geometry import box as _box
            from shapely.geometry import Point as _Pt
            from shapely.geometry import shape as _shape
            from shapely.strtree import STRtree as _STR
            poly_geoms = [_shape(g) for g, _ in sub_polys]
            poly_sids = [sid for _, sid in sub_polys]
            poly_tree = _STR(poly_geoms)
        except Exception:   # noqa: BLE001 — fail soft to the legacy radii
            poly_tree = None

    _DEG_KM = 102.0   # rough deg->km at Japanese latitudes (edge distances)
    _bind_cache = {}

    def _bind_vertex(lat, lon, terminal):
        """Vertex -> substation binding: polygon first, small radius after."""
        if poly_tree is None:
            radius = endpoint_snap_km if terminal else snap_km
            sid, _ = index.nearest(lat, lon, max(radius, snap_km))
            return sid
        key = (round(lat, 6), round(lon, 6), bool(terminal))
        if key in _bind_cache:
            return _bind_cache[key]
        # interior vertices: strict edge band (passing corridors must not
        # fuse). TERMINAL vertices: the line STOPS here — a tip within
        # fallback_endpoint_km of the yard fence is the lead-in OSM left
        # undrawn (poles end at the gantry), so the wider band applies to
        # the POLYGON distance, not the centroid (big yards: fence 0.3 km
        # away can be >0.8 km from the centroid — the gap that re-broke
        # the 438 substations in the first polygon-only A/B).
        reach = fallback_endpoint_km if terminal else poly_edge_km
        eps = reach / _DEG_KM
        pt = _Pt(lon, lat)
        best_sid, best_d = None, reach
        for pi in poly_tree.query(_box(lon - eps, lat - eps,
                                       lon + eps, lat + eps)):
            g = poly_geoms[int(pi)]
            if g.covers(pt):
                best_sid, best_d = poly_sids[int(pi)], 0.0
                break
            d = g.distance(pt) * _DEG_KM
            if d < best_d:
                best_sid, best_d = poly_sids[int(pi)], d
        if best_sid is None:
            radius = fallback_endpoint_km if terminal else fallback_snap_km
            best_sid, _ = index.nearest(lat, lon, radius)
        _bind_cache[key] = best_sid
        return best_sid
    node_coord = {}   # final bus id -> (lat, lon)

    # Build the vertex graph. Each edge carries length, voltage, and the real
    # OSM coordinate path (oriented a->b) so the true route survives chain
    # collapse and can be rendered instead of a straight bus-to-bus segment.
    adj = defaultdict(dict)            # node -> neighbor -> {len, kv, path:[(lat,lon)...]}
    jct_coord = {}                     # junction key -> (lat, lon)

    _EV_RANK = {None: 0, "cables": 1, "tag": 2}
    _KV_RANK = {"unk": 0, "prop": 1, "tag": 2}

    def add_edge(a, b, seg, kv, path, parallel=1, evidence=None, name=None,
                 kv_src="unk", cable_km=0.0, tap=False, bundle=0):
        """Insert/merge an undirected edge, accumulating parallel circuits.

        Real grids run 2-4 parallel circuits between the same two nodes. The
        vertex-snap collapses them into a single edge, so ``parallel`` carries
        the circuit multiplicity — restoring the transmission capacity the
        simplification would otherwise lose.

        ``parallel`` is the number of circuits *this call* contributes: the
        way's own circuits/cables tag value (or 1 without evidence), the
        chain's circuit count for a contracted edge. Merging the same node
        pair **sums** the contributions, because distinct ways / geometric
        routes between two nodes are physically parallel circuits. Callers
        must not count the same circuit twice — the segment loop dedups node
        pairs per way (``seen_pairs``) so a single way that zig-zags across
        the same pair counts once, not N times.

        ``evidence`` records the strongest circuit-count source seen
        ("tag" > "cables" > None=geometric) for provenance reporting.
        """
        cur = adj[a].get(b)
        if cur is None:
            p = max(int(parallel), 1)  # an edge is at least one circuit
            adj[a][b] = {"len": seg, "kv": kv, "path": list(path), "parallel": p,
                         "ev": evidence, "name": name, "kv_src": kv_src,
                         "cab": cable_km, "tap": tap, "bnd": bundle}
            adj[b][a] = {"len": seg, "kv": kv, "path": list(reversed(path)),
                         "parallel": p, "ev": evidence, "name": name,
                         "kv_src": kv_src, "cab": cable_km, "tap": tap,
                         "bnd": bundle}
            return
        kv2 = max(cur["kv"], kv)
        par = cur["parallel"] + max(int(parallel), 0)
        ev = evidence if _EV_RANK.get(evidence, 0) >= _EV_RANK.get(cur.get("ev"), 0) \
            else cur.get("ev")
        ks = kv_src if _KV_RANK.get(kv_src, 0) >= _KV_RANK.get(cur.get("kv_src"), 0) \
            else cur.get("kv_src", "unk")
        nm = cur.get("name") or name  # first real OSM name wins
        cab = max(cur.get("cab", 0.0), cable_km)  # any cable parallel marks it
        tp = bool(cur.get("tap")) or tap
        bnd = max(int(cur.get("bnd", 0)), int(bundle))
        if seg < cur["len"] or cur["len"] <= 0:
            # keep the shorter parallel connection's geometry, highest voltage
            adj[a][b] = {"len": seg, "kv": kv2, "path": list(path), "parallel": par,
                         "ev": ev, "name": nm, "kv_src": ks, "cab": cab,
                         "tap": tp, "bnd": bnd}
            adj[b][a] = {"len": seg, "kv": kv2, "path": list(reversed(path)),
                         "parallel": par, "ev": ev, "name": nm, "kv_src": ks,
                         "cab": cab, "tap": tp, "bnd": bnd}
        else:
            for side in (cur, adj[b][a]):
                side["kv"] = kv2
                side["parallel"] = par
                side["ev"] = ev
                side["name"] = nm
                side["kv_src"] = ks
                side["cab"] = cab
                side["tap"] = tp
                side["bnd"] = bnd

    lines_data = _layer("lines")
    sub_classes = defaultdict(set)   # sub_id -> incident line voltage classes
    feat_cache = []                  # (coords, cls) parsed once
    coord_cls = defaultdict(set)     # rounded coord -> known classes present
    if lines_data:

        # Pass A: parse + collect the known classes at each vertex, so an
        # unknown-voltage segment can join the class it most likely
        # continues (deterministic, order-independent).
        for feat in lines_data["features"]:
            coords = _get_line_coords(feat)
            if len(coords) < 2:
                continue
            props = feat["properties"]
            if _freq_excluded(props, freq):
                continue   # not part of this synchronous network (50/60/DC)
            kv = max(_parse_voltage_kv(props.get("voltage")), 0)
            # Skip non-transmission mistags (known voltage below threshold);
            # keep unknown (0) so unlabelled transmission survives.
            if 0 < kv < min_voltage_kv:
                continue
            kv = _clean_voltage(kv)  # snap known line voltage to a standard class
            circ, circ_src = _parse_circuits(props)
            osm_name = props.get("name") or None
            is_cab = (props.get("power") == "cable"
                      or props.get("location") == "underground")
            feat_cache.append([coords, kv, circ, circ_src, osm_name,
                               "tag" if kv > 0 else "unk", is_cab,
                               _parse_wires(props)])
            if multi_voltage and kv > 0:
                for (lat, lon) in coords:
                    coord_cls[(round(lat, vertex_prec), round(lon, vertex_prec))].add(kv)

        # Pass A.5: corridor voltage propagation. An untagged feature whose
        # vertices only ever meet ONE known class is that corridor's
        # continuation; adopting the class is iterated so it walks through
        # chains of untagged segments. Two classes at its vertices =
        # ambiguous -> stays unknown (no guessing).
        if multi_voltage and propagate_voltage:
            for _ in range(20):
                changed = False
                for feat in feat_cache:
                    coords, kv = feat[0], feat[1]
                    if kv > 0:
                        continue
                    seen = set()
                    for (lat, lon) in coords:
                        seen |= coord_cls.get(
                            (round(lat, vertex_prec), round(lon, vertex_prec)),
                            set())
                    if len(seen) == 1:
                        new_kv = next(iter(seen))
                        feat[1] = new_kv
                        feat[5] = "prop"
                        for (lat, lon) in coords:
                            coord_cls[(round(lat, vertex_prec),
                                       round(lon, vertex_prec))].add(new_kv)
                        changed = True
                if not changed:
                    break

        # Pass B: map vertices to class-aware nodes and build edges.
        tap_segs = []   # (node_a, node_b, latlon_a, latlon_b, kv) for tap snapping
        for coords, kv, circ, circ_src, osm_name, kv_src, is_cab, wires in feat_cache:
            node_ids = []
            last = len(coords) - 1
            for vi, (lat, lon) in enumerate(coords):
                # polygon-first binding; terminals keep a wider fallback
                sid = _bind_vertex(lat, lon, vi in (0, last))
                rlat, rlon = round(lat, vertex_prec), round(lon, vertex_prec)
                if sid is not None:
                    if multi_voltage:
                        sub_classes[sid].add(kv)
                        node_ids.append(f"S|{sid}|{kv:g}")
                    else:
                        node_ids.append(sid)
                else:
                    if multi_voltage:
                        jcls = kv if kv > 0 else max(coord_cls.get((rlat, rlon), (0,)))
                        jk = f"J:{rlat}:{rlon}:{jcls:g}"
                    else:
                        jk = f"J:{rlat}:{rlon}"
                    jct_coord[jk] = (lat, lon)
                    node_ids.append(jk)

            # Add edges between consecutive distinct nodes, with segment length
            # and the real coordinate pair as the (sub-)path. A single way
            # contributes its OWN circuit count (the OSM circuits/cables tag
            # where present — direct evidence — else 1) and only once per
            # node pair even if its vertices revisit it (snapping zig-zag);
            # genuine parallels come from separate ways summing.
            seen_pairs = set()
            for j in range(1, len(coords)):
                a, b = node_ids[j - 1], node_ids[j]
                if a == b:
                    continue
                seg = _haversine_km(coords[j - 1][0], coords[j - 1][1],
                                    coords[j][0], coords[j][1])
                pair = (a, b) if a <= b else (b, a)
                contrib = 0 if pair in seen_pairs else circ
                seen_pairs.add(pair)
                add_edge(a, b, seg, kv, [coords[j - 1], coords[j]],
                         parallel=contrib, evidence=circ_src, name=osm_name,
                         kv_src=kv_src, cable_km=seg if is_cab else 0.0,
                         bundle=wires)
                tap_segs.append((a, b, coords[j - 1], coords[j], kv))

    def is_jct(n):
        return isinstance(n, str) and n.startswith("J:")

    # Mid-span tap snap (user observation 2026-06-11: OSM ways are bare
    # polylines — a tee whose terminal lands mid-span of the through
    # line shares no node and LOOKS disconnected while being physically
    # continuous; counted 201/196/89 such dead-ends in tokyo/chubu/
    # kansai). A degree-1 junction within tap_snap_km of another
    # same-class (or unknown-class) segment is joined to that segment's
    # nearer endpoint; the edge is marked tap=True (prov "tap=snap") so
    # the fabrication stays visible.
    if tap_snap_km and tap_segs:
        import math as _math

        _KM = 111.32
        cell = max(tap_snap_km * 2, 0.2)

        def _xy(lat, lon):
            return (lon * _KM * _math.cos(_math.radians(lat)), lat * _KM)

        seg_grid = defaultdict(list)
        for si, (a, b, p1, p2, kv) in enumerate(tap_segs):
            # register the segment in EVERY cell its bbox touches — long
            # spans between OSM vertices otherwise vanish from the search
            x1, y1 = _xy(*p1)
            x2, y2 = _xy(*p2)
            for gx in range(int(min(x1, x2) // cell), int(max(x1, x2) // cell) + 1):
                for gy in range(int(min(y1, y2) // cell),
                                int(max(y1, y2) // cell) + 1):
                    seg_grid[(gx, gy)].append(si)

        n_taps = 0
        for nid in [n for n in list(adj) if is_jct(n) and len(adj[n]) == 1]:
            if nid not in jct_coord:
                continue
            nb = next(iter(adj[nid]))
            own_kv = adj[nid][nb].get("kv", 0)
            la, lo = jct_coord[nid]
            px, py = _xy(la, lo)
            cx, cy = int(px // cell), int(py // cell)
            best = (None, tap_snap_km)
            for gx in (cx - 1, cx, cx + 1):
                for gy in (cy - 1, cy, cy + 1):
                    for si in seg_grid.get((gx, gy), ()):
                        a, b, p1, p2, kv = tap_segs[si]
                        if nid in (a, b) or a in adj.get(nid, {})                                 or b in adj.get(nid, {}):
                            continue
                        # BOTH classes must be known and equal: tapping
                        # via an unknown-class segment fused a 154/66
                        # crossing in the multivoltage regression — the
                        # exact hazard the class stacks exist to prevent
                        if not (own_kv > 0 and abs(own_kv - kv) <= 1):
                            continue
                        ax, ay = _xy(*p1)
                        bx, by = _xy(*p2)
                        dx, dy = bx - ax, by - ay
                        l2 = dx * dx + dy * dy
                        t = 0.0 if l2 == 0 else max(
                            0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
                        qx, qy = ax + t * dx, ay + t * dy
                        d = _math.hypot(px - qx, py - qy)
                        if d < best[1]:
                            tgt = a if t < 0.5 else b
                            best = ((tgt, p1 if t < 0.5 else p2), d)
            if best[0] is None:
                continue
            tgt, tgt_ll = best[0]
            add_edge(nid, tgt, max(best[1], 0.01), own_kv or 0,
                     [(la, lo), tuple(tgt_ll)], parallel=1, evidence=None,
                     name=None, kv_src="unk", cable_km=0.0, tap=True)
            n_taps += 1

    # Tip joint — node-to-node complement of the tap snap (owner directive
    # 2026-06-12 「物理的に明らかにそこには線が存在するのを繋げばいいだけ」).
    # A degree-1 tip metres from another node of the SAME class is the same
    # physical pole/yard corner (vertex_prec rounding splits measured at
    # 4-6 m); only dead-end tips qualify, so parallel corridors running on
    # shared towers are never fused, and the class guard blocks
    # cross-voltage joins exactly like the tap snap.
    n_joints = 0
    if tip_joint_km:
        ncoords = {}
        for n in adj:
            if is_jct(n):
                if n in jct_coord:
                    ncoords[n] = jct_coord[n]
            elif isinstance(n, str) and n.startswith("S|"):
                si = sub_info.get(n.split("|")[1])
                if si:
                    ncoords[n] = (si["lat"], si["lon"])
        cellj = 0.005
        ngrid = defaultdict(list)
        for n, (la, lo) in ncoords.items():
            ngrid[(round(la / cellj), round(lo / cellj))].append(n)

        def _cls_of(n):
            try:
                return float(n.rsplit(":" if is_jct(n) else "|", 1)[1])
            except (ValueError, IndexError):
                return 0.0

        for nid in [n for n in list(adj) if is_jct(n) and len(adj[n]) == 1]:
            if nid not in ncoords:
                continue
            own = _cls_of(nid) or max(
                (adj[nid][m]["kv"] for m in adj[nid]), default=0.0)
            if own <= 0:
                continue   # no class evidence — a join could fuse classes
            la, lo = ncoords[nid]
            ci, cj = round(la / cellj), round(lo / cellj)
            best_n, bd = None, tip_joint_km
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    for m in ngrid.get((ci + di, cj + dj), ()):
                        if m == nid or m in adj.get(nid, {}) or m not in adj:
                            continue
                        mcls = _cls_of(m)
                        if not (mcls > 0 and abs(mcls - own) <= 1):
                            continue
                        d = _haversine_km(la, lo, *ncoords[m])
                        if d < bd:
                            best_n, bd = m, d
            if best_n is None:
                continue
            add_edge(nid, best_n, max(bd, 0.005), own,
                     [(la, lo), ncoords[best_n]], parallel=1, evidence=None,
                     name=None, kv_src="unk", cable_km=0.0, tap=True)
            n_joints += 1

    # Explicit lead-in (the honest replacement for the old blind radius):
    # OSM frequently ends a feeder at the last pole, 0.6-1.5 km short of
    # the substation it visibly serves. After polygon binding and the tip
    # joint, a REMAINING degree-1 tip with a known class binds to the
    # nearest substation by POLYGON distance within ``leadin_km`` as a
    # labelled "leadin" edge — same physical claim the 2.5 km centroid
    # radius used to make implicitly, now tip-only (passing corridors can
    # no longer fuse: their interior vertices stay free) and visible in
    # the line name for audit/exclusion.
    n_leadins = 0
    if leadin_km and poly_tree is not None:
        eps_l = leadin_km / _DEG_KM
        for nid in [n for n in list(adj) if is_jct(n) and len(adj[n]) == 1]:
            if nid not in jct_coord:
                continue
            own = max((adj[nid][m]["kv"] for m in adj[nid]), default=0.0)
            if own <= 0:
                continue   # class unknown — no evidence for a feed claim
            la, lo = jct_coord[nid]
            pt = _Pt(lo, la)
            best_sid, bd = None, leadin_km
            for pi in poly_tree.query(_box(lo - eps_l, la - eps_l,
                                           lo + eps_l, la + eps_l)):
                g = poly_geoms[int(pi)]
                d = 0.0 if g.covers(pt) else g.distance(pt) * _DEG_KM
                if d < bd:
                    best_sid, bd = poly_sids[int(pi)], d
            if best_sid is None:
                best_sid, bd = index.nearest(la, lo, leadin_km)
            if best_sid is None:
                continue
            si = sub_info[best_sid]
            if multi_voltage:
                sub_classes[best_sid].add(own)
                tgt = f"S|{best_sid}|{own:g}"
            else:
                tgt = best_sid
            if tgt in adj.get(nid, {}):
                continue
            add_edge(nid, tgt, max(bd, 0.02), own,
                     [(la, lo), (si["lat"], si["lon"])], parallel=1,
                     evidence=None, name="leadin", kv_src="unk",
                     cable_km=0.0, tap=False)
            n_leadins += 1

    # T-tap lead-in: a substation that bound NO vertex at all (the old
    # interior radius used to fuse a passing corridor's mid-vertex into
    # it — crude but it modelled the real T分岐 feeding distribution
    # substations). The honest replacement joins the substation to the
    # nearer endpoint of the nearest passing SEGMENT within ``leadin_km``
    # as a labelled "leadin" edge: the corridor keeps its through-path
    # (flow no longer detours into the yard) and the feed claim is
    # visible in the line name.
    if leadin_km and tap_segs and multi_voltage and poly_tree is not None:
        import math as _math2
        _KM2 = 111.32

        def _xy2(lat, lon):
            return (lon * _KM2 * _math2.cos(_math2.radians(lat)), lat * _KM2)

        cell2 = max(leadin_km, 0.5)
        seg_grid2 = defaultdict(list)
        for si2, (a, b, p1, p2, kv) in enumerate(tap_segs):
            x1, y1 = _xy2(*p1)
            x2, y2 = _xy2(*p2)
            for gx in range(int(min(x1, x2) // cell2),
                            int(max(x1, x2) // cell2) + 1):
                for gy in range(int(min(y1, y2) // cell2),
                                int(max(y1, y2) // cell2) + 1):
                    seg_grid2[(gx, gy)].append(si2)

        for sid, si in sub_info.items():
            if sub_classes.get(sid):
                continue   # already fed by bound vertices
            own_cls = si.get("own_cls") or 0.0
            px, py = _xy2(si["lat"], si["lon"])
            cx, cy = int(px // cell2), int(py // cell2)
            best = (None, leadin_km)
            for gx in (cx - 1, cx, cx + 1):
                for gy in (cy - 1, cy, cy + 1):
                    for si2 in seg_grid2.get((gx, gy), ()):
                        a, b, p1, p2, kv = tap_segs[si2]
                        if kv <= 0:
                            continue   # class-unknown corridor: no claim
                        # the substation's own tagged class, when known,
                        # must match the corridor (a 66 kV sub does not
                        # tap a 275 kV trunk)
                        if own_cls > 0 and abs(own_cls - kv) > 1:
                            continue
                        ax, ay = _xy2(*p1)
                        bx, by = _xy2(*p2)
                        dx, dy = bx - ax, by - ay
                        l2 = dx * dx + dy * dy
                        t = 0.0 if l2 == 0 else max(
                            0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
                        qx, qy = ax + t * dx, ay + t * dy
                        d = _math2.hypot(px - qx, py - qy)
                        if d < best[1]:
                            tgt = a if t < 0.5 else b
                            best = ((tgt, p1 if t < 0.5 else p2, kv), d)
            if best[0] is None:
                continue
            tgt, tgt_ll, kv = best[0]
            if multi_voltage:
                sub_classes[sid].add(kv)
                snode = f"S|{sid}|{kv:g}"
            else:
                snode = sid
            if tgt == snode or tgt in adj.get(snode, {}):
                continue
            add_edge(snode, tgt, max(best[1], 0.02), kv,
                     [(si["lat"], si["lon"]), tuple(tgt_ll)], parallel=1,
                     evidence=None, name="leadin", kv_src="unk",
                     cable_km=0.0, tap=False)
            n_leadins += 1

    # Collapse degree-2 junction chains into single branches.
    changed = True
    while changed:
        changed = False
        for n in list(adj.keys()):
            if not is_jct(n) or n not in adj:
                continue
            nbrs = list(adj[n].keys())
            if len(nbrs) == 2:
                a, b = nbrs
                if a == b:
                    del adj[n]
                    continue
                ea, eb = adj[n][a], adj[n][b]  # paths n->a, n->b
                la, lb = ea["len"], eb["len"]
                kv = max(ea["kv"], eb["kv"])
                # The circuits running a->n->b are the same circuits, so the
                # contracted edge carries the chain's multiplicity (max of the
                # two segments — equal for a clean corridor) rather than
                # resetting to 1. add_edge then sums this with any pre-existing
                # a-b route (a genuinely distinct parallel path).
                par = max(ea.get("parallel", 1), eb.get("parallel", 1))
                ev = ea.get("ev") if _EV_RANK.get(ea.get("ev"), 0) >= \
                    _EV_RANK.get(eb.get("ev"), 0) else eb.get("ev")
                ks = ea.get("kv_src", "unk")
                if _KV_RANK.get(eb.get("kv_src", "unk"), 0) > _KV_RANK.get(ks, 0):
                    ks = eb.get("kv_src", "unk")
                # name: prefer the longer segment's OSM name (the corridor)
                nm = (ea.get("name") if (ea.get("name") and la >= lb)
                      else eb.get("name") or ea.get("name"))
                # merged a->b path = (a->n) + (n->b), dropping the duplicate n
                path_ab = list(reversed(ea["path"]))[:-1] + eb["path"]
                # remove junction n, connect a-b with summed length
                del adj[a][n]
                del adj[b][n]
                del adj[n]
                add_edge(a, b, la + lb, kv, path_ab, parallel=par, evidence=ev,
                         name=nm, kv_src=ks,
                         cable_km=ea.get("cab", 0.0) + eb.get("cab", 0.0),
                         tap=bool(ea.get("tap")) or bool(eb.get("tap")),
                         bundle=max(int(ea.get("bnd", 0)), int(eb.get("bnd", 0))))
                changed = True

    # Optionally drop degree-1 junction stubs (dead-ends).
    if not keep_stubs:
        changed = True
        while changed:
            changed = False
            for n in list(adj.keys()):
                if is_jct(n) and n in adj and len(adj[n]) <= 1:
                    for m in list(adj[n].keys()):
                        adj[m].pop(n, None)
                    del adj[n]
                    changed = True

    # Add surviving junctions as synthetic buses (voltage = max incident kv).
    for n in adj:
        if is_jct(n):
            lat, lon = jct_coord[n]
            inc_kv = max((adj[n][m]["kv"] for m in adj[n]), default=0.0)
            node_coord[n] = (lat, lon)
            net.add_substation(Substation(
                id=n.replace("J:", f"{region}_jct_"),
                name=f"{region} junction {n[2:]}",
                region=region,
                latitude=lat,
                longitude=lon,
                voltage_kv=inc_kv,
            ))

    # Substation buses. multi_voltage: one bus per incident voltage class,
    # named {sid}@{kv} ({sid}@u for the unknown class, which keeps the
    # substation's own tagged voltage as its evidence). Single-class
    # substations keep the plain {sid} id so the common case is unchanged.
    sub_resolved = {}   # (sid, cls) -> final bus id
    xfmr_stubs = []     # (sid, hv_id, lv_id, hv_kv) intra-substation pairs

    def _add_sub_bus(sid, bus_id, name, vn_kv):
        info = sub_info[sid]
        net.add_substation(Substation(
            id=bus_id, name=name, region=region,
            latitude=info["lat"], longitude=info["lon"], voltage_kv=vn_kv))

    for sid, info in sub_info.items():
        classes = sub_classes.get(sid, set()) if multi_voltage else set()
        known = sorted((c for c in classes if c > 0), reverse=True)
        has_unknown = 0 in classes
        if not multi_voltage or len(classes) <= 1:
            # plain single bus; voltage = the line class if known, else the
            # substation's own tag (original behaviour for isolated subs)
            vn = known[0] if known else info["own_cls"]
            _add_sub_bus(sid, sid, info["name"], vn)
            node_coord[sid] = (info["lat"], info["lon"])
            for c in (classes or {None}):
                sub_resolved[(sid, c)] = sid
            continue
        ladder = []
        for c in known:
            bid = f"{sid}@{c:g}"
            _add_sub_bus(sid, bid, f"{info['name']} {c:g}kV", c)
            node_coord[bid] = (info["lat"], info["lon"])
            sub_resolved[(sid, c)] = bid
            ladder.append((c, bid))
        if has_unknown:
            bid = f"{sid}@u"
            _add_sub_bus(sid, bid, f"{info['name']} (untyped)", info["own_cls"])
            node_coord[bid] = (info["lat"], info["lon"])
            sub_resolved[(sid, 0)] = bid
            if ladder:
                # untyped busbar hangs off the highest class; once
                # fix_zero_voltages types it, insert_transformers either
                # converts the stub (different class) or leaves it as a
                # negligible-impedance coupler (same class)
                xfmr_stubs.append((sid, ladder[0][1], bid, ladder[0][0]))
        # the real intra-substation transformer ladder: adjacent class pairs
        for (hv_c, hv_id), (_lv_c, lv_id) in zip(ladder, ladder[1:]):
            xfmr_stubs.append((sid, hv_id, lv_id, hv_c))

    def node_to_id(n):
        if is_jct(n):
            return n.replace("J:", f"{region}_jct_")
        if n.startswith("S|"):
            _, sid, cls = n.split("|")
            return sub_resolved[(sid, float(cls))]
        return n

    # raw S|sid|cls node coordinates for the geometry lookup below
    for n in adj:
        if isinstance(n, str) and n.startswith("S|"):
            sid = n.split("|")[1]
            node_coord[n] = (sub_info[sid]["lat"], sub_info[sid]["lon"])

    def ckey(lat, lon):
        return (round(lat, 5), round(lon, 5))

    # geom lookup keyed by endpoint bus-coordinate pairs (both directions);
    # value is the real OSM route as [[lon,lat],...] for the live map.
    geom = {}

    # Emit branches (each undirected edge once).
    seen = set()
    k = 0
    for a in adj:
        for b in adj[a]:
            key = tuple(sorted((a, b)))
            if key in seen:
                continue
            seen.add(key)
            edge = adj[a][b]
            length, kv = edge["len"], edge["kv"]
            if length <= 0:
                length = 0.1
            path_latlon = edge.get("path") or []
            # connection provenance: endpoint kinds (S=substation, J=junction)
            # and the circuit-count evidence source — honest disclosure of
            # how each branch came to exist
            kind_a = "J" if is_jct(a) else "S"
            kind_b = "J" if is_jct(b) else "S"
            med_cable = edge.get("cab", 0.0) > 0.5 * length
            prov = (f"conn={kind_a}-{kind_b};circuits={edge.get('ev') or 'geom'};"
                    f"kv={edge.get('kv_src', 'unk')}"
                    + (";med=cable" if med_cable else "")
                    + (";tap=snap" if edge.get("tap") else ""))
            try:
                net.add_transmission_line(TransmissionLine(
                    id=f"{region}_line_{k}",
                    # real OSM line name where known — enables matching the
                    # model against per-line ground truth (TEPCO/OCCTO flow
                    # disclosures, TSO availability CSVs)
                    name=edge.get("name") or f"{region}_line_{k}",
                    from_substation_id=node_to_id(a),
                    to_substation_id=node_to_id(b),
                    voltage_kv=max(kv, 0),
                    length_km=length,
                    region=region,
                    coordinates=list(path_latlon),
                    num_parallel=edge.get("parallel", 1),
                    description=prov,
                    is_cable=med_cable,
                    n_bundle=int(edge.get("bnd", 0)),
                ))
                k += 1
            except ValueError:
                pass
            # register geometry keyed by the two endpoint bus coordinates
            if return_geom and path_latlon and a in node_coord and b in node_coord:
                ll = [[lon, lat] for (lat, lon) in path_latlon]  # GeoJSON order
                ac_, bc_ = node_coord[a], node_coord[b]
                geom[(ckey(*ac_), ckey(*bc_))] = ll
                geom[(ckey(*bc_), ckey(*ac_))] = list(reversed(ll))

    # Intra-substation transformer stubs: 50 m lines between the per-class
    # buses. insert_transformers converts each into a standard-ladder
    # transformer (500/275, 275/154, ...) — and since the swallowed line is
    # a stub by construction, no real line impedance is lost any more
    # (previously whole cross-voltage LINES were eaten into transformers).
    for sid, hv_id, lv_id, hv_kv in xfmr_stubs:
        info = sub_info[sid]
        try:
            net.add_transmission_line(TransmissionLine(
                id=f"{sid}_xfmr_{hv_id.split('@')[-1]}_{lv_id.split('@')[-1]}",
                name=f"{info['name']} intra-substation {hv_kv:g}kV stub",
                from_substation_id=hv_id,
                to_substation_id=lv_id,
                voltage_kv=hv_kv,
                length_km=0.05,
                region=region,
                coordinates=[(info["lat"], info["lon"]), (info["lat"], info["lon"])],
                num_parallel=1,
            ))
        except ValueError:
            pass

    # Generators -> nearest real substation (unchanged heuristic).
    plants_data = _layer("plants")
    if plants_data:
        for i, feat in enumerate(plants_data["features"]):
            lat, lon = _get_centroid(feat)
            if lat is None:
                continue
            props = feat["properties"]
            cap = props.get("capacity_mw")
            try:
                cap = float(cap) if cap is not None else None
            except (ValueError, TypeError):
                cap = None
            fuel = props.get("plant:source") or props.get("fuel_type") or "unknown"
            if isinstance(fuel, str) and fuel.startswith("http"):
                fuel = "unknown"
            if cap is None or cap <= 0:
                cap = _DEFAULT_CAPACITY_MW.get(fuel, _DEFAULT_CAPACITY_FALLBACK)
            sid, _ = index.nearest(lat, lon, 5.0)
            if sid is None and cap >= 100:
                sid, _ = index.nearest(lat, lon, 20.0)
            if sid is None:
                continue
            # Pick the connection bus among the substation's voltage classes:
            # big plants feed the grid at transmission level, small ones at
            # the lowest class present (matches JP interconnection practice).
            bus_id = sid
            if multi_voltage:
                known = sorted((c for c in sub_classes.get(sid, ()) if c > 0))
                if known:
                    cls = known[-1] if cap >= 200 else known[0]
                    bus_id = sub_resolved.get((sid, cls), sid)
                elif (sid, 0) in sub_resolved:
                    bus_id = sub_resolved[(sid, 0)]
            try:
                net.add_generator(Generator(
                    id=f"{region}_gen_{i}",
                    name=props.get("name") or f"{region}_plant_{i}",
                    capacity_mw=cap,
                    fuel_type=fuel,
                    connected_bus_id=bus_id,
                    region=region,
                    latitude=lat,
                    longitude=lon,
                ))
            except (ValueError, TypeError):
                pass

    if return_geom:
        return net, geom
    return net


def diagnose(region, snap_km=1.5):
    """Build and report connectivity stats (uses networkx)."""
    import networkx as nx

    net = build_network_snapped(region, snap_km=snap_km)
    if net is None:
        print(f"{region}: no data")
        return
    g = nx.Graph()
    real_subs = [s.id for s in net.substations if "_jct_" not in s.id]
    g.add_nodes_from(s.id for s in net.substations)
    for ln in net.transmission_lines:
        g.add_edge(ln.from_substation_id, ln.to_substation_id)
    n_comp = nx.number_connected_components(g)
    # components containing >=1 real substation
    comp_of = {}
    for ci, comp in enumerate(nx.connected_components(g)):
        for n in comp:
            comp_of[n] = ci
    real_comps = set(comp_of[s] for s in real_subs if s in comp_of)
    sizes = sorted((len(c) for c in nx.connected_components(g)), reverse=True)
    largest = sizes[0] if sizes else 0
    iso_real = sum(1 for s in real_subs if g.degree(s) == 0)
    n_jct = sum(1 for s in net.substations if "_jct_" in s.id)
    print(f"{region:9s} snap={snap_km}km | real_subs={len(real_subs)} junctions={n_jct} "
          f"branches={len(net.transmission_lines)} gens={len(net.generators)} | "
          f"total_components={n_comp} real_sub_components={len(real_comps)} "
          f"isolated_real_subs={iso_real} largest_comp={largest} "
          f"coverage={100.0*largest/max(len(net.substations),1):.0f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("regions", nargs="*", default=["okinawa", "shikoku", "hokuriku", "tokyo"])
    ap.add_argument("--snap-km", type=float, default=1.5)
    ap.add_argument("--diagnose", action="store_true")
    args = ap.parse_args()
    regions = args.regions or ["okinawa", "shikoku", "hokuriku", "tokyo"]
    for r in regions:
        diagnose(r, snap_km=args.snap_km)


if __name__ == "__main__":
    main()
