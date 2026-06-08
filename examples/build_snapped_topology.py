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

    python examples/build_snapped_topology.py shikoku --snap-km 1.5 --diagnose
    # or, programmatically:
    from examples.build_snapped_topology import build_network_snapped
    net = build_network_snapped("shikoku", snap_km=1.5)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.model.generator import Generator
from src.model.grid_network import GridNetwork
from src.model.substation import Substation
from src.model.transmission_line import TransmissionLine
from src.regions import REGION_FREQUENCY_HZ as REGION_FREQ

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

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
    if not voltage_raw:
        return 0.0
    parts = str(voltage_raw).strip().replace(",", ";").split(";")
    best = 0.0
    for p in parts:
        p = p.strip()
        if not p:
            continue
        try:
            v = float(p)
        except (ValueError, TypeError):
            continue
        kv = v / 1000 if v > 1000 else v
        best = max(best, kv)
    return best


VALID_VOLTAGES = [66, 77, 110, 132, 154, 187, 220, 275, 500]


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
        best, bd = None, float("inf")
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for slat, slon, sid in self.buckets.get((ci + di, cj + dj), ()):  # noqa: E501
                    d = _haversine_km(lat, lon, slat, slon)
                    if d < bd:
                        bd, best = d, sid
        return (best, bd) if best is not None and bd <= max_km else (None, bd)


# ── core builder ─────────────────────────────────────────────────────────────

def build_network_snapped(region, snap_km=1.5, vertex_prec=4, keep_stubs=True,
                          min_voltage_kv=22.0, return_geom=False):
    """Build a GridNetwork via vertex-graph + tolerance snapping.

    Args:
        region: region key.
        snap_km: bind a line vertex to a substation within this radius (km).
        vertex_prec: decimal places to merge near-coincident vertices
            (4 ~= 11 m). Lines sharing a coordinate within this precision
            are treated as electrically connected.
        keep_stubs: keep degree-1 dangling junction buses if True.
        min_voltage_kv: skip line features with a KNOWN voltage below this
            (non-transmission distribution/industrial mistags, e.g. a 2 kV
            OSM line). Lines with unknown voltage (0) are kept so legitimate
            unlabelled transmission is not lost.

    Returns:
        GridNetwork with real substations + synthetic junction buses + branches
        tracing real OSM line geometry. Returns None if data missing.
    """
    freq = REGION_FREQ.get(region, 50)
    net = GridNetwork(region=region, frequency_hz=freq)

    sub_path = os.path.join(DATA_DIR, f"{region}_substations.geojson")
    if not os.path.exists(sub_path):
        return None
    with open(sub_path, encoding="utf-8") as f:
        subs_data = json.load(f)

    sub_coords = []  # (lat, lon, sub_id)
    for i, feat in enumerate(subs_data["features"]):
        lat, lon = _get_centroid(feat)
        if lat is None:
            continue
        props = feat["properties"]
        sid = f"{region}_sub_{i}"
        vkv = _parse_voltage_kv(props.get("voltage"))
        # A spurious sub-transmission tag (e.g. 2 kV) on a substation that
        # actually sits on a 66+ kV line creates a huge per-unit mismatch.
        # Treat known-low voltages as unknown (0) so fix_zero_voltages infers
        # the real level from the connected transmission lines.
        if 0 < vkv < min_voltage_kv:
            vkv = 0.0
        net.add_substation(Substation(
            id=sid,
            name=props.get("name") or f"{region}_sub_{i}",
            region=region,
            latitude=lat,
            longitude=lon,
            voltage_kv=_clean_voltage(vkv),
        ))
        sub_coords.append((lat, lon, sid))

    index = _SubIndex(sub_coords)
    node_coord = {sid: (lat, lon) for (lat, lon, sid) in sub_coords}  # id -> (lat,lon)

    # Build the vertex graph. Each edge carries length, voltage, and the real
    # OSM coordinate path (oriented a->b) so the true route survives chain
    # collapse and can be rendered instead of a straight bus-to-bus segment.
    adj = defaultdict(dict)            # node -> neighbor -> {len, kv, path:[(lat,lon)...]}
    jct_coord = {}                     # junction key -> (lat, lon)

    def add_edge(a, b, seg, kv, path):
        """Insert/merge an undirected edge; count merged parallels.

        Real grids run 2-4 parallel circuits between the same two nodes. The
        vertex-snap collapses them into a single edge, so we count how many
        were merged and carry it as ``parallel`` — restoring the transmission
        capacity that the simplification would otherwise lose.
        """
        cur = adj[a].get(b)
        if cur is None:
            adj[a][b] = {"len": seg, "kv": kv, "path": list(path), "parallel": 1}
            adj[b][a] = {"len": seg, "kv": kv, "path": list(reversed(path)), "parallel": 1}
        elif seg < cur["len"] or cur["len"] <= 0:
            # keep the shorter parallel connection's geometry, highest voltage
            kv2 = max(cur["kv"], kv)
            par = cur.get("parallel", 1) + 1
            adj[a][b] = {"len": seg, "kv": kv2, "path": list(path), "parallel": par}
            adj[b][a] = {"len": seg, "kv": kv2, "path": list(reversed(path)), "parallel": par}
        else:
            cur["kv"] = max(cur["kv"], kv)
            cur["parallel"] = cur.get("parallel", 1) + 1
            adj[b][a]["kv"] = cur["kv"]
            adj[b][a]["parallel"] = cur["parallel"]

    lines_path = os.path.join(DATA_DIR, f"{region}_lines.geojson")
    if os.path.exists(lines_path):
        with open(lines_path, encoding="utf-8") as f:
            lines_data = json.load(f)

        for feat in lines_data["features"]:
            coords = _get_line_coords(feat)
            if len(coords) < 2:
                continue
            kv = max(_parse_voltage_kv(feat["properties"].get("voltage")), 0)
            # Skip non-transmission mistags (known voltage below threshold);
            # keep unknown (0) so unlabelled transmission survives.
            if 0 < kv < min_voltage_kv:
                continue
            kv = _clean_voltage(kv)  # snap known line voltage to a standard class

            # Map each vertex to a node id (sub if snappable, else junction).
            node_ids = []
            for (lat, lon) in coords:
                sid, _ = index.nearest(lat, lon, snap_km)
                if sid is not None:
                    node_ids.append(sid)
                else:
                    jk = f"J:{round(lat, vertex_prec)}:{round(lon, vertex_prec)}"
                    jct_coord[jk] = (lat, lon)
                    node_ids.append(jk)

            # Add edges between consecutive distinct nodes, with segment length
            # and the real coordinate pair as the (sub-)path.
            for j in range(1, len(coords)):
                a, b = node_ids[j - 1], node_ids[j]
                if a == b:
                    continue
                seg = _haversine_km(coords[j - 1][0], coords[j - 1][1],
                                    coords[j][0], coords[j][1])
                add_edge(a, b, seg, kv, [coords[j - 1], coords[j]])

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
                # merged a->b path = (a->n) + (n->b), dropping the duplicate n
                path_ab = list(reversed(ea["path"]))[:-1] + eb["path"]
                # remove junction n, connect a-b with summed length
                del adj[a][n]
                del adj[b][n]
                del adj[n]
                add_edge(a, b, la + lb, kv, path_ab)
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

    def node_to_id(n):
        return n.replace("J:", f"{region}_jct_") if is_jct(n) else n

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
            try:
                net.add_transmission_line(TransmissionLine(
                    id=f"{region}_line_{k}",
                    name=f"{region}_line_{k}",
                    from_substation_id=node_to_id(a),
                    to_substation_id=node_to_id(b),
                    voltage_kv=max(kv, 0),
                    length_km=length,
                    region=region,
                    coordinates=list(path_latlon),
                    num_parallel=edge.get("parallel", 1),
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

    # Generators -> nearest real substation (unchanged heuristic).
    plants_path = os.path.join(DATA_DIR, f"{region}_plants.geojson")
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
            try:
                net.add_generator(Generator(
                    id=f"{region}_gen_{i}",
                    name=props.get("name") or f"{region}_plant_{i}",
                    capacity_mw=cap,
                    fuel_type=fuel,
                    connected_bus_id=sid,
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


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("regions", nargs="*", default=["okinawa", "shikoku", "hokuriku", "tokyo"])
    ap.add_argument("--snap-km", type=float, default=1.5)
    ap.add_argument("--diagnose", action="store_true")
    args = ap.parse_args()
    regions = args.regions or ["okinawa", "shikoku", "hokuriku", "tokyo"]
    for r in regions:
        diagnose(r, snap_km=args.snap_km)
