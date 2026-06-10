"""National zonal grid builder: merge per-region snapped networks into the
correct synchronous AC islands and add the inter-regional AC tie-lines, so
cross-regional power transfer is modelled instead of solving each region as
an isolated island.

Japan is NOT one synchronous grid:
  * 50 Hz east and 60 Hz west are asynchronous, bridged only by FC/HVDC.
  * Hokkaido couples to Tohoku only via the Hokkaido-Honshu HVDC link.
So synchronous AC islands are:
  - hokkaido         (50 Hz, alone; HVDC to Tohoku only)
  - east  = tohoku+tokyo                      (50 Hz, AC tie ic_002)
  - west  = chubu+hokuriku+kansai+chugoku+shikoku+kyushu (60 Hz, AC ties ic_004..009)
  - okinawa          (60 Hz, isolated)
Asynchronous links (HVDC ic_001, FC ic_003) are returned separately and are
modelled downstream as scheduled P injections, not AC branches.

Promoted from ``examples/build_national_snapped`` (phase-6 structural
unification); the example path remains as a back-compat re-export shim.

Usage::
    from src.powerflow.national import build_island_networks
    islands, async_links = build_island_networks()
    # islands["west"] -> {"net": GridNetwork, "geom": {...}, "regions": [...]}
"""
from __future__ import annotations

import math
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.powerflow.snapped_topology import _haversine_km, build_network_snapped
from src.model.grid_network import GridNetwork
from src.model.transmission_line import TransmissionLine

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INTERCONN_YAML = os.path.join(ROOT, "data", "reference", "interconnections.yaml")

# Synchronous AC islands (members are AC-connected; freq uniform within island)
ISLANDS = {
    "hokkaido": (["hokkaido"], 50),
    "east":     (["tohoku", "tokyo"], 50),
    "west":     (["chubu", "hokuriku", "kansai", "chugoku", "shikoku", "kyushu"], 60),
    "okinawa":  (["okinawa"], 60),
}
ALL_REGIONS = [r for regs, _ in ISLANDS.values() for r in regs]


def load_interconnections():
    """Return (ac_ties, async_links) lists of dicts from the OCCTO YAML."""
    with open(INTERCONN_YAML, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    ac, asyn = [], []
    for ic in data.get("interconnections", []):
        rec = {
            "id": ic["id"], "name": ic.get("name_ja", ic["id"]),
            "from_region": ic["from_region"], "to_region": ic["to_region"],
            "capacity_mw": ic.get("capacity_mw", 0),
            "voltage_kv": ic.get("voltage_kv", 500),
            "type": ic.get("type", "AC"),
            "from_sub": ic.get("route", {}).get("from_substation_ja", ""),
            "to_sub": ic.get("route", {}).get("to_substation_ja", ""),
        }
        (ac if rec["type"] == "AC" else asyn).append(rec)
    return ac, asyn


def _region_centroid(net, region):
    pts = [(s.latitude, s.longitude) for s in net.substations
           if s.region == region and s.latitude is not None]
    if not pts:
        return None
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _find_tie_bus(net, region, sub_name, target_centroid, voltage_kv):
    """Pick the substation in *region* to terminate a tie-line.

    Prefer a name match to the OCCTO substation; otherwise the high-voltage
    bus geographically closest to the partner region (a boundary crossing).
    """
    subs = [s for s in net.substations if s.region == region]
    if not subs:
        return None
    # 1) loose name match (first 3 chars of the OCCTO name, minus the suffix)
    key = (sub_name or "").replace("変電所", "").replace("変換所", "").strip()
    if len(key) >= 2:
        for s in subs:
            if s.name and key[:3] in s.name:
                return s.id
    # 2) nearest high-voltage bus to the partner region centroid
    hv = [s for s in subs if (s.voltage_kv or 0) >= max(voltage_kv * 0.8, 150)]
    cands = hv or subs
    if target_centroid is None:
        return cands[0].id
    best = min(cands, key=lambda s: _haversine_km(
        s.latitude, s.longitude, target_centroid[0], target_centroid[1]))
    return best.id


def build_island_networks(snap_km=1.5):
    """Build per-region snapped nets, merge into synchronous islands, add AC ties.

    Returns (islands, async_links) where islands[name] = {
        net, geom, regions, frequency, tie_lines (list of added tie ids)
    }.
    """
    ac_ties, async_links = load_interconnections()

    # per-region snapped networks + geometry
    reg_net, reg_geom = {}, {}
    for r in ALL_REGIONS:
        res = build_network_snapped(r, snap_km=snap_km, return_geom=True)
        if res:
            reg_net[r], reg_geom[r] = res

    islands = {}
    for island_id, (regions, freq) in ISLANDS.items():
        members = [r for r in regions if r in reg_net]
        if not members:
            continue
        net = GridNetwork(region=island_id, frequency_hz=freq)
        geom = {}
        for r in members:
            net.merge(reg_net[r])
            geom.update(reg_geom.get(r, {}))
        # region centroids within this island
        cents = {r: _region_centroid(net, r) for r in members}

        added = []
        k = 0
        for tie in ac_ties:
            if tie["from_region"] in members and tie["to_region"] in members:
                fb = _find_tie_bus(net, tie["from_region"], tie["from_sub"],
                                   cents.get(tie["to_region"]), tie["voltage_kv"])
                tb = _find_tie_bus(net, tie["to_region"], tie["to_sub"],
                                   cents.get(tie["from_region"]), tie["voltage_kv"])
                if not fb or not tb or fb == tb:
                    continue
                sf = net.get_substation(fb); st = net.get_substation(tb)
                length = _haversine_km(sf.latitude, sf.longitude,
                                       st.latitude, st.longitude)
                tie_id = f"tie_{tie['id']}"
                try:
                    net.add_transmission_line(TransmissionLine(
                        id=tie_id, name=tie["name"],
                        from_substation_id=fb, to_substation_id=tb,
                        voltage_kv=float(tie["voltage_kv"]),
                        length_km=max(length, 1.0),
                        region="interconnect",
                    ))
                    # geometry: straight boundary crossing
                    geom[((round(sf.latitude, 5), round(sf.longitude, 5)),
                          (round(st.latitude, 5), round(st.longitude, 5)))] = \
                        [[sf.longitude, sf.latitude], [st.longitude, st.latitude]]
                    added.append(tie_id)
                    k += 1
                except ValueError:
                    pass

        islands[island_id] = {
            "net": net, "geom": geom, "regions": members,
            "frequency": freq, "tie_lines": added,
        }
    return islands, async_links


def diagnose(snap_km=1.5):
    import networkx as nx
    islands, asyn = build_island_networks(snap_km=snap_km)
    print(f"Async links (P-injection): {[a['id']+':'+a['type'] for a in asyn]}")
    for name, isl in islands.items():
        net = isl["net"]
        g = nx.Graph()
        g.add_nodes_from(s.id for s in net.substations)
        for l in net.transmission_lines:
            g.add_edge(l.from_substation_id, l.to_substation_id)
        nc = nx.number_connected_components(g)
        sizes = sorted((len(c) for c in nx.connected_components(g)), reverse=True)
        cov = 100 * sizes[0] // max(len(net.substations), 1) if sizes else 0
        print(f"  island {name:9s} ({'+'.join(isl['regions'])}) {isl['frequency']}Hz: "
              f"subs={net.substation_count} lines={net.line_count} "
              f"ties={len(isl['tie_lines'])} components={nc} largest_cov={cov}%")


if __name__ == "__main__":
    diagnose()
