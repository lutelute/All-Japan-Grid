"""Derived readings of the station model — All-Japan-Grid's strengths on exact data.

All-Japan-Grid's SubSLD (``docs/SUBSLD_METHOD.md`` there) graded every line end by its
evidence, gave each bay a role (bus coupler / feeder / transformer bay) and drew a real
single-line diagram; but it joined conductors by rounded coordinates, guessed switches
from bays and transformers from the voltage ladder. Here the same readings are computed
from the node-breaker rows of :func:`all_eu_grid.stations.model`, where every switch and
winding is an observed OSM object. Nothing below changes those rows:

* ``binding`` of a line terminal — ``wired`` (its connectivity node also holds a station
  conductor, switch, busbar or winding), ``line_joint`` (only other line ends), or
  ``footprint_only`` (the line just ends inside the fence). All-Japan-Grid's
  vertex-shared / polygon ladder, without the coordinate rounding.
* ``bay`` — switches chained through non-busbar connectivity nodes, with the busbar
  sections, line ends and windings they reach, and a ``function`` from that:
  line_bay / transformer_bay / coupler / line_transformer / line_switching /
  transformer_switching / open_end.
* ``tn`` — topological nodes under the **hypothesis that every mapped switch is
  closed**, labelled as such. OSM has no switch state; a level whose connected parts
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
    uf = Union()
    for n in att:
        uf.find(n)
    for _, ts in switches:
        uf.join(ts[0]["node_id"], ts[1]["node_id"])
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
            a = att[t["node_id"]]
            if a["busbar"] or a["switch"] or a["transformer"] or a["conductor"]:
                b = "wired"
            elif a["line"] > 1:
                # only line ends: one way cut where it enters / leaves the site, or ways meeting
                ways = {eq[x["equipment_id"]]["osm_id"] for x in term_on_line[t["node_id"]]}
                b = "pass_through" if len(ways) == 1 else "line_joint"
            else:
                b = "footprint_only"
            binding[t["terminal_id"]] = {"binding": b, "reaches_busbar": tn_of[t["node_id"]] in tn_has_busbar}

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
        if a["busbar"] or a["conductor"] or a["switch"]:
            tn_mapped.add(tn_of[n])
    # tn_mapped: parts that hold mapped station conductors *and* reach a line or winding;
    # two or more = mapped yards of one level that never meet, even with every switch closed
    levels = {lid: {"tn": len(level_tns[lid]), "tn_external": len(level_ext.get(lid, ())),
                    "tn_mapped": len(level_ext.get(lid, set()) & tn_mapped)} for lid in level_tns}

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
            "pairs": pairs, "attachments": att}


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
