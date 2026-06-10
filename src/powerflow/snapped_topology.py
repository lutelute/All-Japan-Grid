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


def build_network_snapped(region, snap_km=1.5, vertex_prec=4, keep_stubs=True,
                          min_voltage_kv=22.0, return_geom=False, data_dir=None,
                          multi_voltage=True, endpoint_snap_km=2.5,
                          propagate_voltage=True):
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

    Returns:
        GridNetwork with real substations + synthetic junction buses + branches
        tracing real OSM line geometry. Returns None if data missing.
    """
    data_dir = data_dir or DATA_DIR
    freq = REGION_FREQ.get(region, 50)
    net = GridNetwork(region=region, frequency_hz=freq)

    sub_path = os.path.join(data_dir, f"{region}_substations.geojson")
    if not os.path.exists(sub_path):
        return None
    with open(sub_path, encoding="utf-8") as f:
        subs_data = json.load(f)

    sub_coords = []   # (lat, lon, sub_id)
    sub_info = {}     # sub_id -> dict(name, lat, lon, own_cls)
    for i, feat in enumerate(subs_data["features"]):
        lat, lon = _get_centroid(feat)
        if lat is None:
            continue
        props = feat["properties"]
        op_hz = _operator_freq(props.get("operator"))
        if op_hz is not None and op_hz != freq:
            continue   # opposite-frequency TSO: not in this synchronous net
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

    index = _SubIndex(sub_coords)
    node_coord = {}   # final bus id -> (lat, lon)

    # Build the vertex graph. Each edge carries length, voltage, and the real
    # OSM coordinate path (oriented a->b) so the true route survives chain
    # collapse and can be rendered instead of a straight bus-to-bus segment.
    adj = defaultdict(dict)            # node -> neighbor -> {len, kv, path:[(lat,lon)...]}
    jct_coord = {}                     # junction key -> (lat, lon)

    _EV_RANK = {None: 0, "cables": 1, "tag": 2}
    _KV_RANK = {"unk": 0, "prop": 1, "tag": 2}

    def add_edge(a, b, seg, kv, path, parallel=1, evidence=None, name=None,
                 kv_src="unk"):
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
                         "ev": evidence, "name": name, "kv_src": kv_src}
            adj[b][a] = {"len": seg, "kv": kv, "path": list(reversed(path)),
                         "parallel": p, "ev": evidence, "name": name,
                         "kv_src": kv_src}
            return
        kv2 = max(cur["kv"], kv)
        par = cur["parallel"] + max(int(parallel), 0)
        ev = evidence if _EV_RANK.get(evidence, 0) >= _EV_RANK.get(cur.get("ev"), 0) \
            else cur.get("ev")
        ks = kv_src if _KV_RANK.get(kv_src, 0) >= _KV_RANK.get(cur.get("kv_src"), 0) \
            else cur.get("kv_src", "unk")
        nm = cur.get("name") or name  # first real OSM name wins
        if seg < cur["len"] or cur["len"] <= 0:
            # keep the shorter parallel connection's geometry, highest voltage
            adj[a][b] = {"len": seg, "kv": kv2, "path": list(path), "parallel": par,
                         "ev": ev, "name": nm, "kv_src": ks}
            adj[b][a] = {"len": seg, "kv": kv2, "path": list(reversed(path)),
                         "parallel": par, "ev": ev, "name": nm, "kv_src": ks}
        else:
            for side in (cur, adj[b][a]):
                side["kv"] = kv2
                side["parallel"] = par
                side["ev"] = ev
                side["name"] = nm
                side["kv_src"] = ks

    lines_path = os.path.join(data_dir, f"{region}_lines.geojson")
    sub_classes = defaultdict(set)   # sub_id -> incident line voltage classes
    feat_cache = []                  # (coords, cls) parsed once
    coord_cls = defaultdict(set)     # rounded coord -> known classes present
    if os.path.exists(lines_path):
        with open(lines_path, encoding="utf-8") as f:
            lines_data = json.load(f)

        # Pass A: parse + collect the known classes at each vertex, so an
        # unknown-voltage segment can join the class it most likely
        # continues (deterministic, order-independent).
        for feat in lines_data["features"]:
            coords = _get_line_coords(feat)
            if len(coords) < 2:
                continue
            props = feat["properties"]
            op_hz = _operator_freq(props.get("operator"))
            if op_hz is not None and op_hz != freq:
                continue   # opposite-frequency TSO equipment
            kv = max(_parse_voltage_kv(props.get("voltage")), 0)
            # Skip non-transmission mistags (known voltage below threshold);
            # keep unknown (0) so unlabelled transmission survives.
            if 0 < kv < min_voltage_kv:
                continue
            kv = _clean_voltage(kv)  # snap known line voltage to a standard class
            circ, circ_src = _parse_circuits(props)
            osm_name = props.get("name") or None
            feat_cache.append([coords, kv, circ, circ_src, osm_name,
                               "tag" if kv > 0 else "unk"])
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
        for coords, kv, circ, circ_src, osm_name, kv_src in feat_cache:
            node_ids = []
            last = len(coords) - 1
            for vi, (lat, lon) in enumerate(coords):
                # terminal vertices get the wider radius (yard-fence gaps)
                radius = endpoint_snap_km if vi in (0, last) else snap_km
                sid, _ = index.nearest(lat, lon, max(radius, snap_km))
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
                         kv_src=kv_src)

    def is_jct(n):
        return isinstance(n, str) and n.startswith("J:")

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
                         name=nm, kv_src=ks)
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
            prov = (f"conn={kind_a}-{kind_b};circuits={edge.get('ev') or 'geom'};"
                    f"kv={edge.get('kv_src', 'unk')}")
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
    plants_path = os.path.join(data_dir, f"{region}_plants.geojson")
    if os.path.exists(plants_path):
        with open(plants_path, encoding="utf-8") as f:
            plants_data = json.load(f)
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
