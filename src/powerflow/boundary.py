"""Inter-regional boundary injections for REGIONAL power-flow models.

A regional slice is not an electrical island: Tokyo imports several GW
from Tohoku across ic_002, Kansai imports from Chubu/Chugoku/Shikoku,
and so on. Solving a region without those exchanges leaves the boundary
corridors empty — measured against TEPCO actuals this was the dominant
residual error after dispatch fixes (新いわき線 measured p95 1,970 MW vs
model 70 MW; 新栃木線 4,090 vs 2,072).

This module injects each OCCTO interconnection's typical flow at the
region's boundary substation(s):

- **imports** become static generators (``sgen``, type=boundary_import);
- **exports** become loads (named ``boundary_*``);
- ``balance_power`` accounts for both (local dispatch covers
  load − imports), see :mod:`src.powerflow.transforms`.

Typical flows are planning-level approximations (signed utilisation of
the OCCTO 運用容量, direction chosen from well-known structural
surplus/deficit patterns — e.g. Tohoku→Tokyo, Kyushu→Chugoku,
Shikoku→Kansai). They are deliberately overridable and are expected to
be replaced by measured OCCTO 連系線潮流実績 (validation roadmap item 5);
until then they carry an explicit provenance note in build_info.

Boundary bus selection is two-tier:

1. **name match** against the interconnection's official substation
   (works for the western regions: 加賀/越前/東近江/讃岐/阿南/紀北 …);
2. **positional fallback** when the official yard lies OUTSIDE the
   region slice (Tokyo: 新いわき/相馬 are in the tohoku slice): the
   injection is split equally across the trunk-class buses nearest the
   partner region's centroid (within ``spread_km`` of the closest one),
   which lands it on the cut corridor ends at the slice edge.
"""
from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from collections import defaultdict

import pandapower as pp
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INTERCONN_YAML = os.path.join(ROOT, "data", "reference", "interconnections.yaml")

# Signed utilisation of each interconnection's capacity, positive along
# the yaml's from_region -> to_region direction. Planning approximations
# of the structural pattern (replace with OCCTO actuals, roadmap 5):
#   ic_001 Hokkaido->Tohoku  : Hokkaido exports surplus          +0.5
#   ic_002 Tohoku->Tokyo     : the big eastbound import           +0.6
#   ic_003 Tokyo->Chubu (FC) : actually flows Chubu->Tokyo        -0.3
#   ic_004 Chubu->Kansai     : Kansai is structurally deficit     +0.5
#   ic_005 Chubu->Hokuriku   : Hokuriku exports to Chubu          -0.4
#   ic_006 Kansai->Chugoku   : flows Chugoku->Kansai              -0.4
#   ic_007 Kansai->Shikoku   : Shikoku (Ikata etc.) exports       -0.5
#   ic_008 Chugoku->Shikoku  : mild Shikoku->Chugoku              -0.2
#   ic_009 Chugoku->Kyushu   : Kyushu (solar/nuclear) exports     -0.5
TYPICAL_UTILISATION = {
    "ic_001": 0.5, "ic_002": 0.6, "ic_003": -0.3, "ic_004": 0.5,
    "ic_005": -0.4, "ic_006": -0.4, "ic_007": -0.5, "ic_008": -0.2,
    "ic_009": -0.5,
}

# MEASURED utilisations — FY2025+Q1FY2026 medians of OCCTO's published
# 30-min planned interconnector flows (web-kohyo jhSybt=04; derived
# aggregates in docs/reports/occto_calibration_2026-06-11.json), divided
# by the yaml capacities and signed along the yaml from->to convention.
# Cross-checks where the planning guesses were independent: FC -0.325
# vs -0.3, 関門 -0.49 vs -0.5, 相馬双葉 +0.74 vs +0.6 — same structure,
# better magnitudes. ic_006 clamps at -1.0: the measured westbound
# Kansai import (関西-中国 東+西, median ~5.0 GW) exceeds the single
# yaml capacity figure (4,090 MW), disclosed here rather than hidden.
MEASURED_UTILISATION = {
    "ic_001": +0.15,   # 北海道・本州間 median +133 MW / 900
    "ic_002": +0.74,   # 相馬双葉幹線 median +4,098 MW / 5,550
    "ic_003": -0.33,   # 周波数変換設備 median 683 MW Chubu->Tokyo / 2,100
    "ic_004": +0.79,   # 三重東近江線 median 2,000 MW Chubu->Kansai / 2,530
    "ic_005": -0.15,   # 北陸フェンス median 284 MW Hokuriku->out / 1,900
    "ic_006": -1.0,    # 関西-中国(東+西) median ~5.0 GW Chugoku->Kansai (clamped)
    "ic_007": -0.05,   # 阿南紀北直流幹線 median 70 MW Shikoku->Kansai / 1,400
    "ic_008": -0.94,   # 本四連系線 median 1,130 MW Shikoku->Chugoku / 1,200
    "ic_009": -0.49,   # 関門連系線 median 1,373 MW Kyushu->Chugoku / 2,780
}


# OCCTO kohyo_04 disclosure name(s) and the sign of OCCTO's forward
# direction relative to the yaml's from->to, per interconnection. Only
# ic_004 flips (OCCTO forward = Kansai->Chubu; yaml = Chubu->Kansai) —
# verified by reproducing every hardcoded MEASURED_UTILISATION value
# from the raw medians (ledger 54).
_OCCTO_IC = {
    "ic_001": (["北海道・本州間電力連系設備"], +1),
    "ic_002": (["相馬双葉幹線"], +1),
    "ic_003": (["周波数変換設備"], +1),
    "ic_004": (["三重東近江線"], -1),
    "ic_005": (["北陸フェンス"], +1),
    "ic_006": (["関西-中国（東）", "関西-中国（西）"], +1),
    "ic_007": (["阿南紀北直流幹線"], +1),
    "ic_008": (["本四連系線"], +1),
    "ic_009": (["関門連系線"], +1),
}


def measured_utilisation_from_db(db_path: str = "data/grid.db") -> dict | None:
    """MEASURED_UTILISATION recomputed from the calibrated DB.

    occto kohyo_04 signed medians (measured_area_stats, metric
    ic_flow_mw) divided by the yaml capacity, clamped to [-1, 1].
    Fail-soft None keeps the hardcoded medians as the fallback — the
    hardcode becomes the frozen 2025-snapshot default, the DB the
    machine-updatable source (refresh = fetch_occto_kohyo + calibrate).
    """
    try:
        from src.db.calibration import load_measured_area_stats
    except ImportError:
        return None
    stats = load_measured_area_stats(db_path, metric="ic_flow_mw")
    if not stats:
        return None
    out = {}
    for ic in load_interconnections():
        spec = _OCCTO_IC.get(ic.get("id"))
        cap = float(ic.get("capacity_mw", 0) or 0)
        if not spec or cap <= 0:
            continue
        names, sign = spec
        vals = [stats[n].get("signed_q50") for n in names if n in stats]
        if len(vals) != len(names) or any(v is None for v in vals):
            continue
        out[ic["id"]] = max(-1.0, min(1.0, sign * sum(vals) / cap))
    return out or None


_CLASS_SUFFIX = re.compile(r"\s*(\d+(\.\d+)?kV|\(untyped\))$")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = _CLASS_SUFFIX.sub("", s)
    s = s.replace("ヶ", "ケ")   # 関ヶ原 vs OSM 関ケ原町
    for suf in ("変電所", "変換所", "開閉所", "発電所"):
        s = s.replace(suf, "")
    return "".join(s.split())


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return r * 2 * math.asin(math.sqrt(a))


def _bus_coords(net) -> dict:
    """bus index -> (lat, lon) from the pandapower geo column."""
    out = {}
    if "geo" not in net.bus.columns:
        return out
    for idx, raw in net.bus["geo"].items():
        try:
            c = json.loads(raw)["coordinates"] if isinstance(raw, str) else None
        except (ValueError, KeyError, TypeError):
            c = None
        if c and len(c) == 2:
            out[idx] = (float(c[1]), float(c[0]))
    return out


def _partner_centroid(partner_region: str, data_dir: str | None = None):
    """Centroid of the partner region's substations (its own slice file)."""
    path = os.path.join(data_dir or os.path.join(ROOT, "data"),
                        f"{partner_region}_substations.geojson")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    lats, lons = [], []
    for ft in data.get("features", []):
        geom = ft.get("geometry") or {}
        if geom.get("type") == "Point":
            lon, lat = geom["coordinates"][:2]
        elif geom.get("type") == "Polygon" and geom.get("coordinates"):
            ring = geom["coordinates"][0]
            lon = sum(c[0] for c in ring) / len(ring)
            lat = sum(c[1] for c in ring) / len(ring)
        else:
            continue
        lats.append(lat)
        lons.append(lon)
    if not lats:
        return None
    return (sum(lats) / len(lats), sum(lons) / len(lons))


def _find_boundary_buses(net, official_name: str, partner_region: str,
                         min_kv: float, spread_km: float,
                         data_dir: str | None = None,
                         corridor_stats: dict | None = None):
    """Return ([(bus_idx, weight)], method) for one interconnection end."""
    active = net.bus[net.bus["in_service"]]

    # tier 1: name match, highest voltage class of the matched yard
    key = _norm(official_name)
    if key:
        matches = [i for i in active.index
                   if key and key in _norm(active.at[i, "name"])]
        if matches:
            best = max(matches, key=lambda i: float(active.at[i, "vn_kv"]))
            return [(best, 1.0)], "name"

    # tier 2: positional — trunk buses nearest the partner centroid.
    # Multi-voltage yards and adjacent corridor vertices produce many
    # near-coincident candidates, so candidates are clustered (10 km) and
    # the injection is split equally across CLUSTERS (= distinct cut
    # corridors at the slice edge), one representative bus per cluster.
    cent = _partner_centroid(partner_region, data_dir=data_dir)
    coords = _bus_coords(net)
    if cent is None or not coords:
        return [], "none"
    cands = [(i, _haversine_km(*coords[i], *cent))
             for i in active.index
             if i in coords and float(active.at[i, "vn_kv"]) >= min_kv]
    if not cands:
        return [], "none"
    cands.sort(key=lambda t: t[1])
    dmin = cands[0][1]
    picked = [i for i, d in cands if d <= dmin + spread_km]
    clusters: list[list[int]] = []
    for i in picked:                      # greedy 10 km clustering
        for cl in clusters:
            if _haversine_km(*coords[i], *coords[cl[0]]) <= 10.0:
                cl.append(i)
                break
        else:
            clusters.append([i])
    reps = [min(cl, key=lambda i: _haversine_km(*coords[i], *cent))
            for cl in clusters]
    # Per-corridor measured weighting: an equal split over-feeds the
    # corridors that really carry little and starves the heavy ones —
    # the validation signature was 阿武隈線 (Iwaki side) over-routed
    # ~3x while 新栃木線 ran at half its measured flow. When the
    # caller provides measured per-line statistics, each cluster is
    # weighted by the flow its own incident named corridor actually
    # carries (fallback: equal split, disclosed via the method string).
    weights = None
    if corridor_stats and net is not None:
        ws = []
        for rep in reps:
            stat = 0.0
            inc = net.line[((net.line["from_bus"] == rep)
                            | (net.line["to_bus"] == rep))
                           & net.line["in_service"]]
            for raw in inc["name"].astype(str):
                for part in raw.replace(" / ", ";").split(";"):
                    stat = max(stat, corridor_stats.get(_norm(part), 0.0))
            ws.append(stat)
        if sum(ws) > 0:
            weights = [w / sum(ws) for w in ws]
    if weights is None:
        weights = [1.0 / len(reps)] * len(reps)
        method = f"position({len(reps)} corridors, equal)"
    else:
        method = f"position({len(reps)} corridors, measured-weighted)"
    return list(zip(reps, weights)), method


def _fc_buses(net, converters: list[dict], min_kv: float,
              max_km: float = 30.0):
    """Frequency-converter tie: nearest trunk bus to each converter site,
    weighted by converter capacity (sites beyond max_km are outside this
    region's slice and skipped)."""
    coords = _bus_coords(net)
    active = net.bus[net.bus["in_service"]]
    trunk = [i for i in active.index
             if i in coords and float(active.at[i, "vn_kv"]) >= min_kv]
    placed = []
    for fc in converters:
        loc = fc.get("location") or {}
        lat, lon = loc.get("latitude"), loc.get("longitude")
        cap = float(fc.get("capacity_mw", 0) or 0)
        if lat is None or lon is None or cap <= 0 or not trunk:
            continue
        best = min(trunk, key=lambda i: _haversine_km(*coords[i], lat, lon))
        if _haversine_km(*coords[best], lat, lon) <= max_km:
            placed.append((best, cap))
    total = sum(c for _, c in placed)
    if not placed or total <= 0:
        return [], "none"
    return ([(i, c / total) for i, c in placed],
            f"fc-site({len(placed)} converters)")


def load_interconnections(yaml_path: str | None = None) -> list[dict]:
    with open(yaml_path or INTERCONN_YAML, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("interconnections", [])


def apply_boundary_imports(net, region: str, yaml_path: str | None = None,
                           utilisation: dict | None = None,
                           spread_km: float = 75.0,
                           data_dir: str | None = None,
                           corridor_stats: dict | None = None,
                           net_rescale: bool = True) -> dict:
    """Inject every interconnection touching *region* at its boundary.

    Returns a summary dict {ic_id: {mw, bus_names, method}} plus totals;
    ``mw`` > 0 is an import into the region.
    """
    util = dict(MEASURED_UTILISATION)   # frozen 2025-snapshot default
    db_util = measured_utilisation_from_db()
    if db_util:                          # DB-first (calibrate --occto)
        util.update(db_util)
    if utilisation:
        util.update(utilisation)

    summary = {"ics": {}, "import_mw": 0.0, "export_mw": 0.0,
               "provenance": "typical planning utilisation of OCCTO 運用容量 "
                             "(pending measured 連系線潮流実績)"}
    placements = []   # (icid, inj, buses, method) — created after net rescale
    for ic in load_interconnections(yaml_path):
        icid = ic.get("id")
        frm, to = ic.get("from_region"), ic.get("to_region")
        if region not in (frm, to):
            continue
        cap = float(ic.get("capacity_mw", 0) or 0)
        u = util.get(icid, 0.0)
        flow = u * cap                       # + along from->to
        inj = flow if region == to else -flow  # + = import into region
        if cap <= 0 or abs(inj) < 1.0:
            continue
        partner = frm if region == to else to
        route = ic.get("route", {})
        official = (route.get("to_substation_ja") if region == to
                    else route.get("from_substation_ja")) or ""
        # trunk-class floor for positional candidates: just below the
        # interconnection voltage (275 kV ties may land on 275 buses)
        min_kv = max(0.8 * float(ic.get("voltage_kv", 500) or 500), 154.0)
        fcs = ic.get("frequency_converters")
        if fcs:
            # FC stations have exact coordinates: weight by converter
            # capacity at the nearest in-region trunk bus to each site
            buses, method = _fc_buses(net, fcs, min_kv=min_kv)
        else:
            buses, method = _find_boundary_buses(
                net, official, partner, min_kv=min_kv, spread_km=spread_km,
                data_dir=data_dir, corridor_stats=corridor_stats)
        if not buses:
            summary["ics"][icid] = {"mw": 0.0, "bus_names": [],
                                    "method": "UNPLACED"}
            continue
        placements.append((icid, inj, buses, method))

    # Net rescale against the AREA's measured net interconnect (X2-2,
    # ledger 87): corridor-median utilisations double-count loop flow —
    # kansai measured a NET median of +865 MW while the corridor-derived
    # injections summed to +6,160 MW (7x). Where the calibrated DB holds
    # the TSO supply-demand actual (gen_by_fuel:interconnect, signed
    # median), scale every boundary injection by one factor so the net
    # matches the measured operating point while the corridor RATIOS
    # (placement evidence) survive. Fail-soft: no stat, no rescale.
    scale = 1.0
    if placements and net_rescale:
        model_net = sum(p[1] for p in placements)
        try:
            from src.db.calibration import (
                AREA_OF_REGION,
                load_measured_area_stats,
            )
            stats = load_measured_area_stats() or {}
            s = stats.get((AREA_OF_REGION.get(region, region),
                           "gen_by_fuel:interconnect"))
        except Exception:   # noqa: BLE001 — calibration layer is optional
            s = None
        # demand-conditional target: the pipeline solves a peak x LF
        # snapshot that sits at the area's ~p95 demand, and interconnect
        # draw rises with demand — so the consistent operating point is
        # the p95 magnitude with the measured net DIRECTION, not the
        # annual median (kansai A/B: a median target pushed the freed
        # 5.3 GW into thermal at 14.2 GW, overshooting its band).
        target = None
        if s:
            sq = s.get("signed_q50")
            p95 = s.get("p95")
            if sq is not None:
                target = (p95 if (p95 and sq > 0)
                          else (-p95 if (p95 and sq < 0) else sq))
        if target is not None and abs(model_net) > 1.0:
            f = target / model_net
            # same-direction shrink/boost only, with a sanity ceiling —
            # a sign flip would fabricate a regime the corridors don't
            # support; record instead of forcing.
            if f >= 0:
                scale = min(f, 2.0)
                summary["net_rescale"] = {
                    "model_net_mw": round(model_net, 1),
                    "measured_net_mw": round(float(target), 1),
                    "factor": round(scale, 3),
                    "source": "measured_area_stats gen_by_fuel:interconnect",
                }
            else:
                summary["net_rescale"] = {
                    "model_net_mw": round(model_net, 1),
                    "measured_net_mw": round(float(target), 1),
                    "factor": 1.0,
                    "note": "sign mismatch — corridors imply the opposite "
                            "net direction; left unscaled for honesty",
                }

    for icid, inj, buses, method in placements:
        inj *= scale
        names = []
        for bus, w in buses:
            mw = inj * w
            if mw >= 0:
                pp.create_sgen(net, bus=int(bus), p_mw=mw, q_mvar=0.0,
                               name=f"boundary_{icid}",
                               type="boundary_import")
            else:
                pp.create_load(net, bus=int(bus), p_mw=-mw, q_mvar=0.0,
                               name=f"boundary_{icid}")
            names.append(str(net.bus.at[bus, "name"]))
        summary["ics"][icid] = {"mw": round(inj, 1), "bus_names": names,
                                "method": method}
        if inj >= 0:
            summary["import_mw"] += inj
        else:
            summary["export_mw"] += -inj
    summary["import_mw"] = round(summary["import_mw"], 1)
    summary["export_mw"] = round(summary["export_mw"], 1)
    return summary
