"""Derived readings of the station model — All-Japan-Grid's strengths on exact data.

All-Japan-Grid's SubSLD (``docs/SUBSLD_METHOD.md`` there) graded every line end by its
evidence, gave each bay a role (bus coupler / feeder / transformer bay) and drew a real
single-line diagram; but it joined conductors by rounded coordinates, guessed switches
from bays and transformers from the voltage ladder. Here the same readings are computed
from the node-breaker rows of :func:`src.stations.core.model`, where every switch and
winding is an observed OSM object. Nothing below changes those rows:

* ``binding`` of a line terminal — ``wired`` (its connectivity node also holds a station
  conductor, switch, busbar or winding), ``fence_cut`` (the same way cut where it crosses
  the fence), ``line_joint`` (only other line ends), or ``footprint_only`` (the line just
  ends inside the fence); and per way and station, ``line_relation``: ``ends`` there,
  ``wired_through`` (does not end but touches the yard) or ``crosses`` (neither). All-Japan-Grid's
  vertex-shared / polygon ladder, without the coordinate rounding.
* ``bay`` — switches chained through non-busbar connectivity nodes, with the busbar
  sections, line ends and windings they reach, and a ``function`` from that:
  line_bay / transformer_bay / coupler / line_transformer / line_switching /
  transformer_switching / open_end.
* ``tn`` — topological nodes under the **hypothesis that every mapped switch is
  closed** (every arm of a switch then meets every other, resolved or not), labelled as such. OSM has no switch state; a level whose connected parts
  stay apart even then is a mapping gap (or two yards), which the bus-branch model
  merges into one bus without saying so.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from .core import Union

FUNCTIONS = ("line_bay", "transformer_bay", "coupler", "line_transformer", "line_switching",
             "transformer_switching", "open_end")


def _attachments(data):
    """connectivity node -> Counter of what is attached (busbar, switch, transformer, line, conductor)."""
    kind = {e["equipment_id"]: e["kind"] for e in data["equipment"]}
    att = defaultdict(Counter)
    for t in data["terminals"]:
        if t["node_id"]:
            att[t["node_id"]][kind[t["equipment_id"]]] += 1
    for e in data["equipment"]:
        if e["kind"] in ("bay", "internal"):
            for n in e.get("connectivity_nodes", ()):
                att[n]["conductor"] += 1
    return att


def analyse(data: dict) -> dict:
    eq = {e["equipment_id"]: e for e in data["equipment"]}
    att = _attachments(data)
    by_eq = defaultdict(list)
    for t in data["terminals"]:
        by_eq[t["equipment_id"]].append(t)
    busbar_cn = {n for n, a in att.items() if a["busbar"]}
    switches = [(e, sorted(by_eq[e["equipment_id"]], key=lambda t: t["sequence"]))
                for e in data["equipment"] if e["kind"] == "switch"]
    switches = [(e, ts) for e, ts in switches if len(ts) == 2 and all(t["node_id"] for t in ts)]

    # -- topological nodes, every switch closed (a hypothesis, not a state) --------
    # every arm of a closed switch meets every other, so a switch whose sides are not
    # resolved still joins its arms here (its terminals stay unresolved in the rows) — but
    # only where all its arms are at one known level: a switch never joins two voltages, and
    # an earthing switch joins nothing
    node_level0 = {n["node_id"]: n["level_id"] for n in data["nodes"]}
    uf = Union()
    for n in att:
        uf.find(n)
    for e in data["equipment"]:
        if e["kind"] != "switch" or e.get("subtype") == "earthing":
            continue
        arms = e.get("arm_nodes") or [t["node_id"] for t in by_eq[e["equipment_id"]] if t["node_id"]]
        if len(arms) < 2 or len({node_level0.get(n) for n in arms}) != 1 or node_level0.get(arms[0]) is None:
            continue
        for n in arms:
            att[n]["switch_arm"] += 1
            uf.find(n)
        for n in arms[1:]:
            uf.join(arms[0], n)
    groups = defaultdict(list)
    for n in att:
        groups[uf.find(n)].append(n)
    tn_of = {}
    for members in groups.values():
        tid = "tn:" + min(members)[3:]
        for n in members:
            tn_of[n] = tid
    tn_has_busbar = {tn_of[n] for n in busbar_cn}

    # -- line terminals graded by what their node also holds ------------------------
    binding = {}
    term_on_line = defaultdict(list)
    for t in data["terminals"]:
        if t["node_id"] and eq[t["equipment_id"]]["kind"] == "line":
            term_on_line[t["node_id"]].append(t)
    for e in data["equipment"]:
        if e["kind"] != "line":
            continue
        for t in by_eq[e["equipment_id"]]:
            if t["node_id"] is None:
                binding[t["terminal_id"]] = {"binding": "unmapped", "reaches_busbar": None}
                continue
            a = att[t["node_id"]]
            if a["busbar"] or a["switch"] or a["switch_arm"] or a["transformer"] or a["conductor"]:
                b = "wired"
            elif a["line"] > 1:
                # only line ends: one way cut where it enters / leaves the site, or ways meeting
                ways = {eq[x["equipment_id"]]["osm_id"] for x in term_on_line[t["node_id"]]}
                b = "fence_cut" if len(ways) == 1 else "line_joint"
            else:
                b = "footprint_only"
            binding[t["terminal_id"]] = {"binding": b, "reaches_busbar": tn_of[t["node_id"]] in tn_has_busbar}

    # -- each way at each station: does it end there, touch the yard, or only cross it? --
    # (a fence_cut is where the way crosses the fence; RTE's line codes showed most are lines
    # that do end inside, so the cut alone says nothing about crossing)
    rel = {}
    for e in data["equipment"]:
        if e["kind"] != "line":
            continue
        n = len(e["tags"].get("node_ids") or ())
        a, b_ = e.get("segment") or [0, n - 1]
        for t in by_eq[e["equipment_id"]]:
            site = (t["level_id"] or "").split("@")[0] or None
            if site is None or t["terminal_id"] not in binding:
                continue
            idx = a if t["sequence"] == 1 else b_
            k = (e["osm_id"], site)
            r = rel.setdefault(k, {"ends": False, "wired": False, "kv": set()})
            r["ends"] |= idx in (0, n - 1)
            r["wired"] |= binding[t["terminal_id"]]["binding"] == "wired"
            if e.get("lvl") and e["lvl"][0]:
                r["kv"].add(e["lvl"][0])
    line_relation = [{"way": w, "site": s, "relation": "ends" if r["ends"] else "wired_through" if r["wired"] else "crosses",
                      "kv": sorted(r["kv"], reverse=True)} for (w, s), r in sorted(rel.items())]

    # -- bays: switch chains between busbars and what they serve ------------------------
    bu = Union()
    sw_root = {}
    for e, ts in switches:
        a, b = ts[0]["node_id"], ts[1]["node_id"]
        free = [n for n in (a, b) if n not in busbar_cn]
        if not free:
            sw_root[e["equipment_id"]] = ("sw", e["equipment_id"])
            bu.find(sw_root[e["equipment_id"]])
            continue
        roots = [("cn", n) for n in free]
        for r in roots:
            bu.find(r)
        if len(roots) == 2:
            bu.join(*roots)
        sw_root[e["equipment_id"]] = roots[0]
    members = defaultdict(lambda: {"switches": [], "nodes": set(), "busbars": set(), "landing": set()})
    for e, ts in switches:
        g = members[bu.find(sw_root[e["equipment_id"]])]
        g["switches"].append(e["equipment_id"])
        a, b = ts[0]["node_id"], ts[1]["node_id"]
        for t in ts:
            (g["busbars"] if t["node_id"] in busbar_cn else g["nodes"]).add(t["node_id"])
        if (a in busbar_cn) != (b in busbar_cn):
            g["landing"].add(b if a in busbar_cn else a)      # where a busbar's switch lands in the bay
    term_on = defaultdict(list)
    for t in data["terminals"]:
        if t["node_id"]:
            term_on[t["node_id"]].append(t)
    bays, bay_of = [], {}
    for g in members.values():
        lines = sorted({t["terminal_id"] for n in g["nodes"] for t in term_on[n]
                        if eq[t["equipment_id"]]["kind"] == "line"})
        windings = sorted({t["terminal_id"] for n in g["nodes"] for t in term_on[n]
                           if eq[t["equipment_id"]]["kind"] == "transformer"})
        nb = len(g["busbars"])
        if lines and windings:
            fn = "line_transformer"
        elif windings:
            fn = "transformer_bay" if nb else "transformer_switching"
        elif lines:
            fn = "line_bay" if nb else "line_switching"
        else:
            # a coupler joins busbars through the bay (switch, node, switch ...); busbar switches
            # that all land on one node are a feeder's selector whose outgoing side is unmapped
            fn = "coupler" if nb >= 2 and (not g["nodes"] or len(g["landing"]) >= 2) else "open_end"
        sws = sorted(g["switches"])
        first = eq[sws[0]]
        bid = "bay:" + sws[0]
        kinds = Counter((eq[s]["subtype"] or "unspecified") for s in sws)
        bays.append({"bay_id": bid, "site": first["site"], "level_id": by_eq[sws[0]][0]["level_id"],
                     "function": fn, "switches": sws, "switch_kinds": dict(sorted(kinds.items())),
                     "busbar_nodes": sorted(g["busbars"]), "line_terminals": lines, "winding_terminals": windings})
        for s in sws:
            bay_of[s] = bid

    # -- per level: parts that stay apart with every switch closed ------------------------
    level_tns, level_ext = defaultdict(set), defaultdict(set)
    tn_ext, tn_mapped = set(), set()
    node_level = {n["node_id"]: n["level_id"] for n in data["nodes"]}
    for n, a in att.items():
        lid = node_level.get(n)
        if lid is None:
            continue
        level_tns[lid].add(tn_of[n])
        if a["line"] or a["transformer"]:
            level_ext[lid].add(tn_of[n])
            tn_ext.add(tn_of[n])
        if a["busbar"] or a["conductor"] or a["switch"] or a["switch_arm"]:
            tn_mapped.add(tn_of[n])
    # tn_mapped: parts that hold mapped station conductors *and* reach a line or winding;
    # two or more = mapped yards of one level that never meet, even with every switch closed
    level_busbars = Counter(node_level.get(n) for n in busbar_cn)
    levels = {lid: {"tn": len(level_tns[lid]), "tn_external": len(level_ext.get(lid, ())),
                    "tn_mapped": len(level_ext.get(lid, set()) & tn_mapped), "busbars": level_busbars[lid]}
              for lid in level_tns}

    # -- transformer voltage pairs as mapped --------------------------------------------
    pairs = []
    ends_of = defaultdict(set)
    for w in data["ends"]:
        if w["kv"]:
            ends_of[w["equipment_id"]].add(w["kv"])
    for e in data["equipment"]:
        if e["kind"] != "transformer" or e["site"] is None:
            continue
        kvs = sorted(ends_of.get(e["equipment_id"], ()), reverse=True)
        for i, hv in enumerate(kvs):
            for lv in kvs[i + 1:]:
                pairs.append({"site": e["site"], "equipment_id": e["equipment_id"], "hv_kv": hv, "lv_kv": lv})
    return {"tn_of": tn_of, "binding": binding, "bays": bays, "bay_of": bay_of, "levels": levels,
            "pairs": pairs, "attachments": att, "line_relation": line_relation}


def gaps(data: dict, views: dict, keep: int = 5) -> dict:
    """For each level whose mapped parts never meet (``tn_mapped > 1``): how far apart they
    are. Per part, the nearest other part — distance from its vertices to the other part's
    conductors, in metres, with the OSM node it is measured from. A gap of centimetres is a
    join the mapper meant (two nodes on one spot, a bay ending on a busbar without a shared
    node); All-Japan-Grid's 0.1 m vertex rounding would make it a connection. Listed for
    review, never joined here."""
    from math import cos, radians

    import numpy as np
    import shapely

    member_node = {}
    for n in data["nodes"]:
        for m in n["members"]:
            member_node.setdefault(int(m.split(">")[0]), n["node_id"])
    split = {lid for lid, v in views["levels"].items() if v["tn_mapped"] > 1}
    if not split:
        return {}
    tn_of, att = views["tn_of"], views["attachments"]
    part_ok = defaultdict(set)                    # level -> TNs that are mapped and carry lines / windings
    node_level = {n["node_id"]: n["level_id"] for n in data["nodes"]}
    ext, mapped = set(), set()
    for n, a in att.items():
        if a["line"] or a["transformer"]:
            ext.add(tn_of.get(n))
        if a["busbar"] or a["conductor"] or a["switch"] or a["switch_arm"]:
            mapped.add(tn_of.get(n))
    for n in att:
        lid = node_level.get(n)
        if lid in split and tn_of.get(n) in ext and tn_of.get(n) in mapped:
            part_ok[lid].add(tn_of[n])
    pieces = defaultdict(lambda: defaultdict(list))     # level -> TN -> [(node ids, coords)]
    way_cns = defaultdict(set)
    for x in data["equipment"]:
        if x["kind"] in ("busbar", "bay", "internal"):
            way_cns[x.get("section_of") or x["equipment_id"]].update(x.get("connectivity_nodes", ()))
    seen_way = set()
    for e in data["equipment"]:
        if e["kind"] not in ("busbar", "bay", "internal"):
            continue
        src = e.get("section_of") or e["equipment_id"]     # a busbar's sections share its way
        if src in seen_way:
            continue
        seen_way.add(src)
        ids, cs = e["tags"].get("node_ids") or [], e.get("coords") or []
        if len(ids) != len(cs) or len(ids) < 2:
            continue
        a, b = (e.get("segment") or [0, len(ids) - 1])
        ids, cs = ids[a:b + 1], cs[a:b + 1]
        for lid in {node_level.get(n) for n in way_cns[src]} & split:
            # each vertex goes with the part its node is in (switch arms may split a way)
            run_ids, run_cs, run_tn = [], [], None
            for nid, c in zip(ids, cs):
                tn = tn_of.get(member_node.get(nid))
                if tn != run_tn and run_ids:
                    pieces[lid][run_tn].append((run_ids, run_cs, e["kind"]))
                    run_ids, run_cs = run_ids[-1:], run_cs[-1:]
                run_ids.append(nid)
                run_cs.append(c)
                run_tn = tn
            if run_ids:
                pieces[lid][run_tn].append((run_ids, run_cs, e["kind"]))
    out = {}
    for lid in split:
        parts = {tn: ps for tn, ps in pieces[lid].items() if tn in part_ok[lid]}
        if len(parts) < 2:
            continue
        lat0 = next(iter(parts.values()))[0][1][0][1]
        k = np.array([111320 * cos(radians(lat0)), 110540])
        geo, verts = {}, {}
        runs_of = {}
        for tn, ps in parts.items():
            lines = [np.asarray(cs, dtype=float) * k for _, cs, _ in ps]
            runs = [shapely.linestrings(ln) for ln in lines if len(ln) > 1]
            runs_of[tn] = [(shapely.linestrings(ln) if len(ln) > 1 else shapely.points(ln[0]), kd)
                           for ln, (_, _, kd) in zip(lines, ps)]
            geo[tn] = shapely.multilinestrings(runs) if runs else shapely.multipoints(np.vstack(lines))
            verts[tn] = (np.vstack(lines), [n for ids, _, _ in ps for n in ids], [c for _, cs, _ in ps for c in cs],
                         [kd for ids, _, kd in ps for _ in ids])
        edges = []
        for tn, (xy, ids, ll, kinds) in verts.items():
            best = None
            for other, g in geo.items():
                if other == tn:
                    continue
                d = shapely.distance(shapely.points(xy), g)
                i = int(np.argmin(d))
                if best is None or d[i] < best[0]:
                    oxy, oids, _, _ = verts[other]
                    dv = np.hypot(*(oxy - xy[i]).T)
                    j = int(np.argmin(dv))
                    p = shapely.points(xy[i])
                    to_kind = min(runs_of[other], key=lambda r: shapely.distance(p, r[0]))[1]
                    best = (float(d[i]), ids[i], oids[j] if dv[j] - d[i] < 0.05 else None, other, ll[i],
                            kinds[i], to_kind)
            edges.append({"part": tn, "to": best[3], "gap_m": round(best[0], 2), "node": best[1],
                          "to_node": best[2], "at": [round(best[4][0], 7), round(best[4][1], 7)],
                          "between": "-".join(sorted((best[5], best[6])))})
        edges.sort(key=lambda r: r["gap_m"])
        out[lid] = {"parts": len(parts), "gap_m": edges[0]["gap_m"], "between": edges[0]["between"],
                    "nearest": edges[:keep]}
    return out


def coverage(data: dict, views: dict) -> dict:
    """Per site: what is mapped, and a status (mutually exclusive, All-AU-Grid's states
    plus ``lines_only``). A status grades the record, never the real station."""
    by_site = defaultdict(lambda: Counter())
    eq_site = {}
    for e in data["equipment"]:
        s = e["site"]
        eq_site[e["equipment_id"]] = s
        if s:
            by_site[s][e["kind"]] += 1
    for e in data["equipment"]:
        if e["kind"] == "line":
            for s in e.get("end_sites") or ():
                if s:
                    by_site[s]["line_end"] += 1
    unmapped, device_wired = Counter(), Counter()
    kind = {e["equipment_id"]: e["kind"] for e in data["equipment"]}
    for t in data["terminals"]:
        s = eq_site.get(t["equipment_id"])
        if s and not t["node_id"]:
            unmapped[s] += 1
        if s and t["node_id"] and kind[t["equipment_id"]] in ("switch", "transformer"):
            device_wired[s] += 1
    dev_issue = Counter(i["site_id"] for i in data["issues"]
                        if i["site_id"] and i["code"] in ("switch_ports_unresolved", "transformer_interfaces_unknown",
                                                          "transformer_interface_voltage_conflict",
                                                          "switch_bypass_or_mapping_loop"))
    out = {}
    for s, c in by_site.items():
        devices = c["transformer"] + c["switch"]
        conductors = c["busbar"] + c["bay"] + c["internal"]
        if not devices and not conductors:
            status = "lines_only"
        elif devices and not conductors:
            status = "partial" if device_wired[s] else "layout_only"
        elif not devices:
            status = "conductors_only"
        elif unmapped[s] or dev_issue[s]:
            status = "partial"
        else:
            status = "mapped"
        out[s] = {"status": status, "counts": dict(c), "unmapped_terminals": unmapped[s], "device_issues": dev_issue[s]}
    return out
