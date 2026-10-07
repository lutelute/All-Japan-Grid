"""Substation internals as node-breaker data: levels, conductors, switches, windings.

The method is All-AU-Grid's (``docs/SUBSTATION_METHOD.md`` there): a footprint only
says *where* equipment stands; only a shared OSM **node id** joins two conductors;
a switch has one port per incident arm and a transformer one per voltage side, so
neither is ever shorted by the way that runs through it. Unknown stays unknown.

What is added here, each with its own evidence label so the strict reading stays
available (``docs/STATIONS.md``):

* **membership** of a point is ``covered`` (inside one footprint), ``innermost_nested``
  (several strictly nested footprints, the innermost is unique) or ``buffer``
  (outside every footprint but within ``buffer_m`` of exactly one polygon). Portals
  and gantries often stand a few metres outside the mapped fence; the topology step
  uses the same 25 m. Point substations never take a buffer.
* a transformer tagged only ``voltage=380000;110000`` gets one interface per value
  (``device_voltage_list``), roles unknown.
* each conductor voltage carries its system (``ac`` for Japan's 50 and 60 Hz alike — see
  :mod:`src.stations.tags` — / ``rail`` for 16.7 Hz traction, ``ac_other``); a rail level is a separate level even at the same kV, DC is left out.

``model(sites, lines, elements)`` is pure: GeoJSON-like inputs in, plain rows out.
Identifiers are readable and independent of input order: ``w123`` for an OSM object,
``w123@110`` for a site's level, ``cn:w123@110:<node>`` for a connectivity node.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from math import cos, radians

import numpy as np
import shapely
from shapely.geometry import Point, shape

from .tags import circuit_sets, parse_voltage_kv, split_list

VERSION = "agj-station-2"  # eu-station-2 (All-EU-Grid 5d85ba9) + 日本の周波数
INTERNAL = {"busbar", "bay", "internal", "transformer"}   # line=* values of station conductors
CONDUCTOR_POWER = {"line", "cable", "minor_line", "minor_cable", "minor_underground_cable",
                   "busbar", "bay"}
ROLES = ("primary", "secondary", "tertiary")
PREFIX = {"node": "n", "way": "w", "relation": "r"}


def key_of(osm_type: str, osm_id) -> str:
    return f"{PREFIX[osm_type]}{osm_id}"


def fkv(kv) -> str:
    """kV in an id: exact to 0.1 V (``%g`` would print 230.0001 kV as 230)."""
    return "?" if kv is None else f"{kv:.4f}".rstrip("0").rstrip(".")


def level_id(site: str, lvl) -> str | None:
    if site is None or lvl is None or lvl[0] is None:
        return None
    kv, system = lvl
    return f"{site}@{fkv(kv)}" + ("" if system == "ac" else f"~{system}")


def mva(raw) -> float | None:
    """No unitless ratings, no MW-to-MVA conversion (All-AU-Grid's rule)."""
    m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*(VA|kVA|MVA|GVA)\s*", str(raw or ""))
    if not m:
        return None
    v = float(m[1].replace(",", ".")) * {"VA": 1e-6, "kVA": 1e-3, "MVA": 1.0, "GVA": 1e3}[m[2]]
    return v if v > 0 else None


def levels_of(tags: dict) -> list:
    """Conductor voltage systems ``[(kv, system)]``; ``[(None, None)]`` when any voltage
    token is unreadable (a partly readable list would misplace the aligned values).
    DC sets are left out: they belong to the DC inventory, not to an AC station."""
    raw = split_list(tags.get("voltage"))
    if not raw:
        return [(None, None)]
    if any(parse_voltage_kv(t) is None for t in raw):
        return [(None, None)]
    out = []
    for s in circuit_sets(tags):
        if s.system == "dc" or s.kv is None:
            continue
        lvl = (s.kv, s.system)
        if lvl not in out:
            out.append(lvl)
    return sorted(out, key=lambda t: (-t[0], t[1]))


def circuit_allocation(tags: dict) -> list:
    """Per-voltage circuit counts from the way's own tags; an ambiguous total is never
    multiplied out and ``cables`` is not divided by three (All-AU-Grid's rule; the
    topology step keeps its own documented cables rule for the computation model)."""
    raw_v = split_list(tags.get("voltage"))
    kvs = [parse_voltage_kv(v) for v in raw_v]
    if not kvs or any(v is None for v in kvs):
        return [(None, None, "unknown_voltage")]
    raw_n = split_list(tags.get("circuits"))
    ns = [int(n) if re.fullmatch(r"[1-9]\d*", n) else None for n in raw_n]
    if len(kvs) == len(ns) and all(ns):
        totals = defaultdict(int)
        for kv, n in zip(kvs, ns):
            totals[kv] += n
        return [(kv, n, "ordered_circuits_tag") for kv, n in sorted(totals.items(), reverse=True)]
    if len(set(kvs)) == 1 and len(ns) == 1 and ns[0]:
        return [(kvs[0], ns[0], "circuits_tag")]
    return [(kv, None, "unallocated_total" if any(ns) else "unknown_count")
            for kv in sorted(set(kvs), reverse=True)]


class Union:
    """Union-find whose root is the smallest member under ``key`` (order-independent ids)."""

    def __init__(self, key=lambda x: x):
        self.parent = {}
        self.key = key

    def find(self, x):
        p = self.parent
        p.setdefault(x, x)
        root = x
        while p[root] != root:
            root = p[root]
        while p[x] != root:
            p[x], x = root, p[x]
        return root

    def join(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            lo, hi = (a, b) if self.key(a) <= self.key(b) else (b, a)
            self.parent[hi] = lo


def _order(port):
    """Total order on ports (site, lvl, node, arm) with None anywhere."""
    site, lvl, node, arm = port
    return (site or "", -(lvl[0] or 0) if lvl else 0, (lvl[1] or "") if lvl else "",
            node or 0, -1 if arm is None else arm)


def _port_repr(port) -> str:
    _, _, node, arm = port
    return f"{node}" if arm is None else f"{node}>{arm}"


# ------------------------------------------------------------------ membership
class SiteLocator:
    """Which footprint a point or geometry belongs to, with the evidence for it."""

    def __init__(self, sites: list, buffer_m: float = 25.0):
        self.keys = [key_of(f["properties"]["osm_type"], f["properties"]["osm_id"]) for f in sites]
        self.geoms = [f["geometry"] if hasattr(f["geometry"], "geom_type") else shape(f["geometry"])
                      for f in sites]
        self.polygon = np.array([g.geom_type in ("Polygon", "MultiPolygon") for g in self.geoms])
        self.area = np.array([g.area for g in self.geoms])
        self.tree = shapely.STRtree(self.geoms)
        self.buffer_m = buffer_m
        poly_idx = np.flatnonzero(self.polygon)
        self.buf_idx = poly_idx
        self.buf_tree = shapely.STRtree([_buffer_deg(self.geoms[i], buffer_m) for i in poly_idx]) \
            if buffer_m and len(poly_idx) else None
        self._nest = {}

    def _resolve(self, hits):
        """-> (site index or None, method, candidates). All-AU-Grid's nesting rule."""
        if len(hits) == 1:
            return hits[0], "covered", None
        hs = tuple(sorted(hits))
        if hs not in self._nest:
            gs = self.geoms
            leaves = [i for i in hs if not any(
                gs[i].covers(gs[j]) and not gs[i].equals(gs[j]) for j in hs if j != i)]
            if len(leaves) == 1 and all(self.area[i] > 0 for i in hs):
                self._nest[hs] = (leaves[0], "innermost_nested", list(hs))
            else:
                self._nest[hs] = (None, "ambiguous", list(hs))
        return self._nest[hs]

    def locate(self, geoms) -> list:
        """Membership of each geometry: (site index | None, method | None, candidates)."""
        geoms = np.asarray(geoms, dtype=object)
        strict = defaultdict(list)
        a, b = self.tree.query(geoms, predicate="covered_by")
        for i, j in zip(a.tolist(), b.tolist()):
            strict[i].append(j)
        out = [(None, None, None)] * len(geoms)
        rest = []
        for i in range(len(geoms)):
            if i in strict:
                out[i] = self._resolve(strict[i])
            else:
                rest.append(i)
        if self.buf_tree is not None and rest:
            near = defaultdict(list)
            a, b = self.buf_tree.query(geoms[rest], predicate="covered_by")
            for i, j in zip(a.tolist(), b.tolist()):
                near[rest[i]].append(int(self.buf_idx[j]))
            for i, js in near.items():
                out[i] = (js[0], "buffer", None) if len(js) == 1 else (None, "ambiguous_buffer", sorted(js))
        return out


def _buffer_deg(g, metres: float):
    """Buffer a lon/lat geometry by metres (local equirectangular scaling)."""
    lat = g.representative_point().y
    k = max(cos(radians(lat)), 0.05)
    scaled = shapely.transform(g, lambda xy: xy * np.array([k, 1.0]))
    return shapely.transform(scaled.buffer(metres / 111320.0), lambda xy: xy / np.array([k, 1.0]))


def _metres_from(g, xy) -> float:
    """Distance in metres from a lon/lat point to a lon/lat geometry (local equirectangular)."""
    k = np.array([max(cos(radians(g.representative_point().y)), 0.05), 1.0])
    return shapely.transform(g, lambda a: a * k).distance(Point(*(np.asarray(xy, dtype=float) * k))) * 111320.0


# ------------------------------------------------------------------ helpers
def device_feature(e: dict):
    """Geometry of an OSM element given as {type, id, tags, lon/lat | nodes+geometry}."""
    if e["type"] == "node":
        return Point(e["lon"], e["lat"])
    if e["type"] == "way" and e.get("geometry"):
        cs = [(p["lon"], p["lat"]) for p in e["geometry"]]
        if len(cs) > 3 and cs[0] == cs[-1]:
            return shapely.Polygon(cs)
        return shapely.LineString(cs) if len(cs) > 1 else Point(cs[0])
    return None


def _interfaces(tags: dict, connected: list) -> list:
    """Transformer voltage sides: (role, lvl or None, method)."""
    out = []
    for role in ROLES:
        raw = tags.get("voltage:" + role)
        if raw:
            vs = [parse_voltage_kv(t) for t in split_list(raw)]
            kv = vs[0] if len(vs) == 1 and vs[0] is not None else None
            out.append((role, kv, "interface_voltage_tag"))
    if not out:
        vs = [parse_voltage_kv(t) for t in split_list(tags.get("voltage"))]
        if len(vs) >= 2 and all(v is not None for v in vs) and len(set(vs)) == len(vs):
            out = [(f"listed_{i}", kv, "device_voltage_list") for i, kv in enumerate(sorted(vs, reverse=True), 1)]
    if not out:
        kvs = sorted({kv for kv, _ in connected if kv is not None}, reverse=True)
        if len(kvs) >= 2:
            out = [(f"unassigned_{i}", kv, "shared_node_conductor_voltage") for i, kv in enumerate(kvs, 1)]
    return out


# ------------------------------------------------------------------ builder
def model(sites: list, lines: list, elements: list, buffer_m: float = 25.0,
          extension_m: float = 0.0) -> dict:
    """Station structure from footprints, conductors (with ordered OSM ``node_ids``) and
    the transformer / switch / circuit elements. Rows only; nothing is written.

    ``extension_m`` (All-Japan-Grid): a ``line=bay|busbar`` way whose in-site nodes all lie in
    one site and whose other nodes lie in none, within ``extension_m`` of that site's polygon,
    brings those outside nodes into the site as ``internal_extension``. 0 is the strict
    reading of All-AU-Grid / All-EU-Grid."""

    out = {k: [] for k in ("levels", "equipment", "nodes", "terminals", "ends",
                           "circuits", "members", "issues")}
    if not (buffer_m >= 0) or buffer_m == float("inf"):
        raise ValueError("buffer_m must be finite and non-negative")
    loc = SiteLocator(sites, buffer_m)
    skey = loc.keys

    def self_polygon(si):
        return bool(loc.polygon[si])
    level_evidence = defaultdict(Counter)

    def issue(entity, code, site=None, **detail):
        out["issues"].append({"site_id": site, "entity_id": entity, "code": code, "detail": detail})

    def level(site_i, lvl, evidence):
        if site_i is None or lvl is None or lvl[0] is None:
            return None
        level_evidence[site_i, lvl][evidence] += 1
        return level_id(skey[site_i], lvl)

    # -- devices --------------------------------------------------------------
    specials, devices = {}, []
    dev_elems = [e for e in elements
                 if e.get("_equipment_kind", e.get("tags", {}).get("power")) in ("transformer", "switch")]
    dev_geoms = [device_feature(e) for e in dev_elems]
    ok = [i for i, g in enumerate(dev_geoms) if g is not None]
    dev_site = dict(zip(ok, loc.locate([dev_geoms[i] for i in ok])))
    for i, e in enumerate(dev_elems):
        key = key_of(e["type"], e["id"])
        kind = e.get("_equipment_kind", e["tags"].get("power"))
        g = dev_geoms[i]
        if g is None:
            issue(key, "unsupported_equipment_geometry")
            continue
        si, method, cands = dev_site[i]
        if method in ("ambiguous", "ambiguous_buffer"):
            issue(key, "ambiguous_site_containment", sites=[skey[j] for j in cands], method=method)
        elif si is None:
            issue(key, "equipment_without_site")
        eq = {"equipment_id": key, "osm_id": key, "site_i": si, "kind": kind,
              "subtype": e["tags"].get(kind),
              "membership": method if si is not None else None, "tags": e["tags"], "geometry": g,
              "classification": e.get("_classification_method", "power_tag")}
        out["equipment"].append(eq)
        devices.append((eq, e))
        if e["type"] == "node":
            specials[e["id"]] = eq

    # -- conductor voltages; inference crosses a conductor junction, never a device --
    prepared = []
    for f in lines:
        p = f["properties"]
        ns = p.get("node_ids") or []
        cs = f["geometry"]["coordinates"] if isinstance(f["geometry"], dict) else list(f["geometry"].coords)
        key = key_of(p.get("osm_type", "way"), p["osm_id"])
        if len(ns) != len(cs) or len(ns) < 2:
            issue(key, "missing_way_node_ids", nodes=len(ns), coords=len(cs))
            continue
        prepared.append((key, p, ns, cs))
    lvls, vmethod = {}, {}
    by_node = defaultdict(list)
    for key, p, ns, _ in prepared:
        lvls[key] = levels_of(p)
        vmethod[key] = "voltage_tag"
        for n in ns:
            if n not in specials:
                by_node[n].append(key)
    node_lists = {key: ns for key, _, ns, _ in prepared}
    internal_keys = [key for key, p, *_ in prepared if p.get("line") in INTERNAL and not p.get("voltage")]
    for _ in range(10):
        updates = {}
        for key in internal_keys:
            if lvls[key] != [(None, None)]:
                continue
            adj = {lv for n in node_lists[key] for k in by_node[n] for lv in lvls[k] if lv[0] is not None}
            if len(adj) == 1:
                updates[key] = sorted(adj)
        if not updates:
            break
        lvls.update(updates)
        vmethod.update({k: "unique_adjacent_voltage" for k in updates})

    # -- where each conductor vertex stands --------------------------------------
    node_xy = {}
    for _, _, ns, cs in prepared:
        for n, c in zip(ns, cs):
            node_xy.setdefault(n, c)
    order = list(node_xy)
    located = loc.locate(shapely.points(np.array([node_xy[n] for n in order], dtype=float))) if order else []
    node_site = {n: r for n, r in zip(order, located) if r[0] is not None}
    for n, r in zip(order, located):
        if r[1] in ("ambiguous", "ambiguous_buffer"):
            node_site[n] = (None, r[1], r[2])

    # A station conductor drawn past the fence (All-Japan-Grid): Japanese mappers often run a
    # line=bay on to the first portal or tower 30-100 m outside the mapped fence (median 47 m in
    # the 2026-10-06 extract), where the line starts. Its outside nodes join the one site its
    # inside nodes stand in, so that line meets the station there; a way touching two sites, an
    # ambiguous node or a node farther than ``extension_m`` keeps the strict reading.
    if extension_m:
        for key, p, ns, cs in prepared:
            if p.get("line") not in INTERNAL:
                continue
            states = [node_site.get(n, (None, None, None)) for n in ns]
            if any(st[1] in ("ambiguous", "ambiguous_buffer") for st in states):
                continue
            inside = {st[0] for st in states if st[0] is not None}
            outside = [(n, c) for n, c, st in zip(ns, cs, states) if st[0] is None]
            if len(inside) != 1 or not outside:
                continue
            si = next(iter(inside))
            if not self_polygon(si) or max(_metres_from(loc.geoms[si], c) for _, c in outside) > extension_m:
                continue
            for n, _ in outside:
                node_site.setdefault(n, (si, "internal_extension", None))

    def site_of(n):
        return node_site.get(n, (None, None, None))[0]


    # -- ports and conductor paths -----------------------------------------------
    uf = Union(_order)
    switch_ports = defaultdict(set)
    incident = defaultdict(set)
    arm_way = defaultdict(set)       # switch port -> {(way, is busbar)}; two ways on one arm = unresolved

    def series(special):
        # An earthing switch closes a conductor to ground; it is not in series with it.
        return special and special["kind"] == "switch" and special["subtype"] != "earthing"

    def port(si, lvl, node, neighbor, way=None, busbar=False):
        special = specials.get(node)
        # A switch has one side per incident arm; never shorted by a through-way.
        arm = neighbor if series(special) else None
        k = (skey[si], lvl, node, arm)
        uf.find(k)
        if special:
            incident[node].add(lvl)
            if special["kind"] == "switch":
                switch_ports[node].add(k)
                arm_way[k].add((way, busbar))
        return k

    earthing = {n for n, sp in specials.items() if sp["kind"] == "switch" and sp["subtype"] == "earthing"}

    junctions = {n for n, ks in by_node.items() if len(set(ks)) > 1} | set(specials)
    pending, internal_segments = [], {}
    circuit_seen = set()
    for key, p, ns, cs in prepared:
        internal = p.get("line") in INTERNAL
        if internal:
            sites_here = {site_of(n) for n in ns}
            methods = {node_site.get(n, (None, None))[1] for n in ns}
            if len(sites_here) != 1 or None in sites_here:
                if any(s is not None for s in sites_here):
                    issue(key, "internal_way_without_unique_site",
                          sites=sorted(skey[s] for s in sites_here if s is not None),
                          outside_nodes=sum(site_of(n) is None for n in ns))
                continue
            si = next(iter(sites_here))
            membership = "internal_extension" if "internal_extension" in methods else (
                "buffer" if "buffer" in methods else (
                    "innermost_nested" if "innermost_nested" in methods else "covered"))
            segments = [(0, len(ns) - 1)]
        else:
            # Cut where the way enters/leaves a site or meets another way/device inside one;
            # whole ways passing through keep their in-site nodes. No node is invented.
            # A line vertex just outside the fence belongs to the site only where it meets a
            # station conductor or device (the portal a bay starts from); a line merely passing
            # within the buffer is not cut there.
            ss = [site_of(n) if node_site.get(n, (None, None))[1] not in ("buffer", "internal_extension")
                  or n in junctions else None for n in ns]
            if not any(s is not None for s in ss):
                continue
            cuts = [0]
            for i in range(1, len(ns) - 1):
                s = ss[i]
                if s is not None and (ns[i] in junctions or s != ss[i - 1] or s != ss[i + 1]):
                    cuts.append(i)
            cuts.append(len(ns) - 1)
            segments = list(zip(cuts, cuts[1:]))
        # A conductor that never leaves one footprint is a station conductor whatever its
        # line tag (a short power=line from a gantry to a transformer, say): it joins what it
        # touches instead of counting as a line leaving the station. A way that enters or
        # crosses the site keeps its line terminals at the cuts.
        inner = {}
        if not internal and len(set(ss)) == 1 and ss[0] is not None:
            ms = {node_site[n][1] for n in ns}
            m = "internal_extension" if "internal_extension" in ms else "buffer" if "buffer" in ms \
                else "innermost_nested" if "innermost_nested" in ms else "covered"
            inner = {seg: (ss[0], m) for seg in segments}
        line_piece = False
        for lvl in lvls[key]:
            for a, b in segments:
                seg_ns, seg_cs = ns[a:b + 1], cs[a:b + 1]
                cut = len(segments) > 1
                eqid = f"{key}@{fkv(lvl[0])}" + (f"~{lvl[1]}" if lvl[1] not in (None, "ac") else "") + \
                       (f"#{a}-{b}" if cut else "")
                if internal or (a, b) in inner:
                    if internal:
                        kind = p["line"] if p["line"] in ("busbar", "bay") else "internal"
                        rule = "line_tag"
                    else:
                        si, membership = inner[a, b]
                        kind, rule = "internal", "inside_one_footprint"
                    level(si, lvl, "conductor:" + vmethod[key])
                    ports, segs = [], []
                    for idx, (u, v) in enumerate(zip(seg_ns, seg_ns[1:])):
                        pu, pv = port(si, lvl, u, v, key, kind == "busbar"), port(si, lvl, v, u, key, kind == "busbar")
                        uf.join(pu, pv)
                        ports += [pu, pv]
                        segs.append((pu, [seg_cs[idx], seg_cs[idx + 1]]))
                    internal_segments[eqid] = segs
                    eq = {"equipment_id": eqid, "osm_id": key, "site_i": si, "kind": kind, "lvl": lvl,
                          "membership": membership, "voltage_method": vmethod[key], "tags": p,
                          "coords": seg_cs, "subtype": p.get("power"), "conductor_rule": rule,
                          "segment": [a, b] if cut else None}
                    out["equipment"].append(eq)
                    pending.append((eq, ports))
                else:
                    line_piece = True
                    end_sites = [ss[a], ss[b]]
                    if not any(s is not None for s in end_sites):
                        continue
                    terms = []
                    for seq, (si, node, nb) in enumerate(zip(end_sites, (ns[a], ns[b]), (ns[a + 1], ns[b - 1])), 1):
                        if si is not None:
                            level(si, lvl, "line_end:" + vmethod[key])
                            terms.append((seq, port(si, lvl, node, nb, key), node_site[node][1]))
                    eq = {"equipment_id": eqid, "osm_id": key, "site_i": None, "kind": "line", "lvl": lvl,
                          "membership": "line_end", "voltage_method": vmethod[key], "tags": p,
                          "coords": seg_cs, "segment": [a, b] if cut else None, "subtype": p.get("power"),
                          "end_sites": [skey[s] if s is not None else None for s in end_sites]}
                    out["equipment"].append(eq)
                    pending.append((eq, terms))
        if line_piece and key not in circuit_seen:
            circuit_seen.add(key)
            for kv, count, method in circuit_allocation(p):
                cid = f"{key}@{fkv(kv)}"
                out["circuits"].append({"circuit_id": cid, "kind": "way_bundle", "kv": kv,
                                        "circuit_count": count, "method": method,
                                        "detail": {"ref": p.get("ref"), "name": p.get("name"),
                                                   "circuits": p.get("circuits"), "cables": p.get("cables"),
                                                   "scope": "one OSM way; not a whole-route count"}})
                out["members"].append({"circuit_id": cid, "member": key, "sequence": 1, "role": "segment"})

    # A switch drawn where a busbar meets exactly one other conductor (a bay or line ending
    # there or crossing it) separates the two: the busbar runs on through the node and the
    # switch sits between it and the branch (the usual mapping of a busbar disconnector).
    # One voltage, one way per arm; anything else stays unresolved. (A "tee" rule — the way
    # that runs through vs. the one that ends — was tried and dropped: where a way is split
    # says nothing physical; on All-AU-Grid's data it turned 5 of 9 line disconnectors and
    # 2 bus-section breakers the wrong way round.)
    junction = {}
    for node, ks in switch_ports.items():
        if node in earthing or len(ks) == 2:
            continue
        if any(len(arm_way.get(k, ())) != 1 for k in ks):
            continue                     # overlapping ways on one arm: which is which is unknown
        ways = defaultdict(list)
        for k in ks:
            ways[next(iter(arm_way[k]))].append(k)
        if len(ways) != 2 or len({k[1] for k in ks}) != 1:
            continue
        (wa, a), (wb, b) = ways.items()
        if wa[1] == wb[1]:
            continue
        rule = "busbar_junction"
        if wb[1]:
            a, b = b, a
        for g in (a, b):
            g.sort(key=_order)
            for k in g[1:]:
                uf.join(g[0], k)
        junction[node] = (a[0], b[0], rule)

    # -- connectivity nodes: conductor paths collapsed, ports kept as members ----
    roots = defaultdict(list)
    for k in list(uf.parent):
        roots[uf.find(k)].append(k)
    cn_of = {}
    for root, members in roots.items():
        members.sort(key=_order)
        site, lvl, _, _ = members[0]
        lid = level_id(site, lvl)
        cid = f"cn:{site}@{fkv(lvl[0] if lvl else None)}" + \
              (f"~{lvl[1]}" if lvl and lvl[1] not in (None, "ac") else "") + f":{_port_repr(members[0])}"
        for m in members:
            cn_of[m] = cid
        out["nodes"].append({"node_id": cid, "site": site, "level_id": lid,
                             "members": [_port_repr(m) for m in members]})
    site_i = {k: i for i, k in enumerate(skey)}

    def terminal(eq, seq, node, lvl, site, method="shared_osm_node", **detail):
        tid = f"{eq['equipment_id']}#{seq}"
        out["terminals"].append({"terminal_id": tid, "equipment_id": eq["equipment_id"], "sequence": seq,
                                 "level_id": level_id(site, lvl), "node_id": node, "method": method,
                                 "detail": detail})
        return tid

    extra = []
    for eq, ports in pending:
        if eq["kind"] == "line":
            for seq, pk, membership in ports:
                terminal(eq, seq, cn_of[pk], pk[1], pk[0], membership=membership)
            continue
        nodes = sorted({cn_of[p] for p in ports})
        eq["connectivity_nodes"] = nodes
        if eq["kind"] == "busbar":
            # A switch bisecting one OSM busbar gives two sections; never one node.
            for nid in nodes:
                sec = {**eq, "equipment_id": f"{eq['equipment_id']}/{nid.rsplit(':', 1)[1]}",
                       "section_of": eq["equipment_id"], "connectivity_nodes": [nid],
                       "pieces": [c for p, c in internal_segments[eq["equipment_id"]] if cn_of[p] == nid]}
                extra.append(sec)
                terminal(sec, 1, nid, eq["lvl"], skey[eq["site_i"]])
            eq["_drop"] = True
    out["equipment"] = [e for e in out["equipment"] if not e.get("_drop")] + extra

    # -- switches and transformer windings -----------------------------------------
    for eq, e in devices:
        si = eq["site_i"]
        node = e["id"] if e["type"] == "node" else None
        if eq["kind"] == "switch" and node in earthing:
            # one terminal on the conductor it grounds (CIM GroundDisconnector); the
            # ground side is not a connectivity node of the station
            sides = sorted({a for a in switch_ports.get(node, ())}, key=_order)
            if len({cn_of[a] for a in sides}) != 1:
                issue(eq["equipment_id"], "switch_ports_unresolved", site=skey[si] if si is not None else None,
                      arms=len(sides), note="earthing switch off any conductor")
                continue
            terminal(eq, 1, cn_of[sides[0]], sides[0][1], sides[0][0])
            eq["lvl"] = sides[0][1]
            continue
        if eq["kind"] == "switch":
            # every arm's node: with every switch closed they are one (station_views)
            eq["arm_nodes"] = sorted({cn_of[k] for k in switch_ports.get(node, ())})
        if eq["kind"] == "switch" and node in junction:
            for seq, side in enumerate(junction[node][:2], 1):
                terminal(eq, seq, cn_of[side], side[1], side[0], junction[node][2])
            if cn_of[junction[node][0]] == cn_of[junction[node][1]]:
                # All-AU-Grid's addition: an alternate path joins both sides here too
                issue(eq["equipment_id"], "switch_bypass_or_mapping_loop", site=junction[node][0][0],
                      node_id=cn_of[junction[node][0]], method=junction[node][2])
            eq["lvl"] = junction[node][0][1]
            continue
        if eq["kind"] == "switch":
            arms = sorted(switch_ports.get(node, ()), key=_order)
            if len(arms) != 2 or len({a[1] for a in arms}) != 1:
                issue(eq["equipment_id"], "switch_ports_unresolved", site=skey[si] if si is not None else None,
                      arms=len(arms))
                continue
            for seq, arm in enumerate(arms, 1):
                terminal(eq, seq, cn_of[arm], arm[1], arm[0])
            eq["lvl"] = arms[0][1]
            if cn_of[arms[0]] == cn_of[arms[1]]:
                issue(eq["equipment_id"], "switch_bypass_or_mapping_loop", site=arms[0][0],
                      node_id=cn_of[arms[0]],
                      note="Another mapped conductor joins both arms; the switch itself was not collapsed.")
            continue
        connected = sorted(incident.get(node, ()), key=lambda t: (-(t[0] or 0), t[1] or ""))
        ifaces = _interfaces(eq["tags"], connected)
        site = skey[si] if si is not None else None
        if not ifaces:
            issue(eq["equipment_id"], "transformer_interfaces_unknown", site=site,
                  connected_kv=[lv[0] for lv in connected])
        elif ifaces[0][2] == "device_voltage_list":
            # All-AU-Grid's addition: candidate sides from a legacy list; roles and count unverified
            issue(eq["equipment_id"], "transformer_voltage_list_unverified", site=site,
                  raw_voltage=eq["tags"].get("voltage"))
        known = {kv for _, kv, _ in ifaces if kv is not None}
        wire_kv = {lv[0] for lv in connected if lv[0] is not None}
        conflict = bool(ifaces) and bool(wire_kv - known)
        if conflict:
            issue(eq["equipment_id"], "transformer_interface_voltage_conflict", site=site,
                  tag_kv=sorted(known), wire_kv=sorted(wire_kv))
        repeated = Counter(kv for _, kv, _ in ifaces)
        # endNumber orders highest voltage first; the OSM role name is kept separately
        # (a generator transformer's primary is its low-voltage side).
        for seq, (role, kv, method) in enumerate(sorted(ifaces, key=lambda t: (-(t[1] or 0), t[0])), 1):
            match = [lv for lv in connected if lv[0] == kv] if kv is not None else []
            lvl = match[0] if len(match) == 1 else ((kv, "ac") if kv is not None else None)
            pk = (site, lvl, node, None)
            cn = cn_of.get(pk) if node is not None and kv is not None and repeated[kv] == 1 else None
            if site is not None and lvl is not None:
                level(si, lvl, "transformer:" + method)
            tid = terminal(eq, seq, cn, lvl, site, "shared_osm_node" if cn else "interface_tag_only",
                           role=role, wire_voltage_conflict=conflict)
            out["ends"].append({"end_id": f"{eq['equipment_id']}#{role}", "equipment_id": eq["equipment_id"],
                                "terminal_id": tid, "role": role, "end_number": seq, "kv": kv,
                                "rated_mva": mva(eq["tags"].get("rating:" + role)), "voltage_method": method,
                                "detail": {"rating_raw": eq["tags"].get("rating:" + role),
                                           "bank_rating_raw": eq["tags"].get("rating"),
                                           "windings": eq["tags"].get("windings")}})

    # -- circuit relations ----------------------------------------------------------
    available = {key for key, *_ in prepared}
    for e in elements:
        t = e.get("tags", {})
        if e["type"] != "relation" or not (t.get("power") == "circuit" or t.get("route") == "power"):
            continue
        key = key_of("relation", e["id"])
        members = [(seq, m, key_of(m["type"], m["ref"])) for seq, m in enumerate(e.get("members", []), 1)]
        if not any(mk in available for _, _, mk in members):
            continue    # a route that never reaches a station is not station data
        vs = [parse_voltage_kv(v) for v in split_list(t.get("voltage"))]
        out["circuits"].append({"circuit_id": key, "kind": "power_circuit" if t.get("power") == "circuit"
                                else "route_power", "kv": vs[0] if len(vs) == 1 else None,
                                "circuit_count": 1, "method": "circuit_relation",
                                "detail": {k: t[k] for k in ("name", "ref", "operator", "voltage", "circuits")
                                           if k in t}})
        missing = 0
        for seq, m, mk in members:
            if mk in available:
                out["members"].append({"circuit_id": key, "member": mk, "sequence": seq, "role": m.get("role", "")})
            else:
                missing += 1
        if missing:
            # Members away from stations are not extracted; the relation is incomplete here.
            out["circuits"][-1]["detail"]["members_outside_extract"] = missing

    # -- levels ------------------------------------------------------------------
    used_sites = {eq["site_i"] for eq in out["equipment"] if eq["site_i"] is not None}
    used_sites |= {site_i[n["site"]] for n in out["nodes"]}
    for si in used_sites:
        p = sites[si]["properties"]
        for lvl in levels_of({k: p.get(k) for k in ("voltage", "frequency", "operator") if p.get(k)}):
            level(si, lvl, "site_voltage_tag")
    out["levels"] = sorted(({"level_id": level_id(skey[si], lvl), "site": skey[si], "kv": lvl[0],
                             "system": lvl[1], "evidence": dict(sorted(ev.items()))}
                            for (si, lvl), ev in level_evidence.items()), key=lambda r: r["level_id"])
    seen = Counter(r["level_id"] for r in out["levels"])
    dup = [r for r in out["levels"] if seen[r["level_id"]] > 1]
    if dup:
        raise ValueError(f"level ids collide: {dup[:6]}")
    for eq in out["equipment"]:
        si = eq.pop("site_i")
        eq["site"] = skey[si] if si is not None else None
    out["sites"] = skey
    return out
