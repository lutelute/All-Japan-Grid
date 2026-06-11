"""Synthetic load estimation and generation scaling for power flow analysis.

Distributes regional peak demand across buses proportional to their voltage
class weights, and scales generator output to match total demand plus
reserve margin.  The external grid (slack bus) absorbs residual mismatch.

Usage::

    from src.powerflow.load_estimator import estimate_loads, scale_generation

    estimate_loads(net, region="shikoku", demand_config=cfg)
    scale_generation(net, target_mw=total_demand * 1.05)
"""

import math
import os
from typing import Any, Dict, Optional, Set

import pandapower as pp
import yaml

from src.utils.logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_DEMAND_CONFIG_PATH = "config/regional_demand.yaml"


def load_demand_config(
    config_path: str = DEFAULT_DEMAND_CONFIG_PATH,
) -> Dict[str, Any]:
    """Load regional demand configuration from YAML.

    Args:
        config_path: Path to ``regional_demand.yaml``.

    Returns:
        Parsed configuration dictionary.
    """
    with open(config_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def estimate_loads(
    net: Any,
    region: str,
    demand_config: Optional[Dict[str, Any]] = None,
    config_path: str = DEFAULT_DEMAND_CONFIG_PATH,
    skip_existing: bool = False,
    spatial: str = "none",
    measured_bus_loads: Optional[Dict[str, Any]] = None,
    measured_stat: str = "p95",
) -> float:
    """Distribute synthetic loads across all buses in the network.

    Each bus receives a load proportional to its voltage-class weight.
    The total load equals the regional peak demand multiplied by the
    configured load factor.

    For national (multi-region) models, the ``zone`` column on each bus
    is used to determine its region and allocate demand accordingly.

    When *skip_existing* is ``True``, buses that already have at least
    one load element attached are excluded from load allocation.  The
    target demand is reduced by the existing load total so that the
    sum of existing + new loads approximates the regional target.
    This supports reconstruction workflows where some buses carry
    real load data while others need synthetic loads.

    Args:
        net: pandapower network (modified in place).
        region: Region identifier (e.g. ``"shikoku"``).
        demand_config: Pre-loaded config dict.  If ``None``, loaded from
            *config_path*.
        config_path: Fallback path for loading config.
        skip_existing: If ``True``, do not create loads on buses that
            already have at least one load element.  Existing loads are
            preserved and the allocation target is reduced accordingly.
        spatial: "none" (pure voltage-class weights, default) or
            "degree" (tilt by branch degree — see :func:`degree_factors`).
            Kept opt-in until validated against external per-substation
            flow data (TEPCO disclosure; docs/VALIDATION_SOURCES.md).
        measured_bus_loads: measured per-substation demands
            ``{normalised sub name: {"q50":.., "p95":..} | MW}`` (e.g.
            from ``src.db.calibration.load_measured_bus_loads``). Name-
            matched substation buses are pinned to the measured value
            (absolute MW); only the residual goes through the synthetic
            voltage-class rule, on the remaining buses.
        measured_stat: which measured statistic to pin ("p95" default —
            closest to the solved peak-ish snapshot; "q50" for medians).

    Returns:
        Total active power (MW) allocated across all buses.
    """
    if demand_config is None:
        demand_config = load_demand_config(config_path)

    peak_demands = demand_config["regional_peak_demand_mw"]
    load_factor = demand_config.get("load_factor", 0.85)
    power_factor = demand_config.get("power_factor", 0.95)
    voltage_weights = demand_config.get("voltage_weights", {})

    # Q/P ratio from power factor
    tan_phi = math.tan(math.acos(power_factor))

    if region == "national":
        return _estimate_loads_national(
            net, peak_demands, load_factor, tan_phi, voltage_weights,
            skip_existing=skip_existing,
        )

    # Regional model: single region
    peak_mw = peak_demands.get(region)
    if peak_mw is None:
        logger.warning(
            "No peak demand data for region '%s'; skipping load allocation",
            region,
        )
        return 0.0

    target_mw = peak_mw * load_factor

    # Measured demand placement (M3): pin name-matched substations to
    # their disclosed busbar/terminal statistic, then let the synthetic
    # rule fill only the residual on the remaining buses.
    if measured_bus_loads:
        placed = _place_measured_loads(net, measured_bus_loads, tan_phi,
                                       target_mw, stat=measured_stat)
        if placed > 0.0:
            skip_existing = True

    # Reduce target by existing loads when skipping
    existing_mw = 0.0
    if skip_existing and not net.load.empty:
        existing_mw = float(net.load["p_mw"].sum())
        target_mw = max(target_mw - existing_mw, 0.0)

    total_allocated = _allocate_bus_loads(
        net, target_mw, tan_phi, voltage_weights,
        skip_existing=skip_existing,
        spatial_factors=(degree_factors(net) if spatial == "degree"
                         else population_factors(net) or None
                         if spatial == "population" else None),
    )

    logger.info(
        "Allocated %.1f MW (%.1f MVAr) across %d buses for region '%s'"
        + (" (skipped buses with existing loads)" if skip_existing else ""),
        total_allocated,
        total_allocated * tan_phi,
        len(net.bus),
        region,
    )
    return total_allocated + existing_mw


def _place_measured_loads(net: Any, measured: Dict[str, Any],
                          tan_phi: float, target_mw: float,
                          stat: str = "p95") -> float:
    """Pin measured per-substation demands to name-matched buses.

    A multi-voltage yard places its offtake at its LOWEST >=50 kV bus
    (the distribution draw hangs off the lowest transmission class, so
    the 66 kV network carries it — that is what the disclosure
    measured). Loads are named ``measured_<sub>`` for traceability.
    The aggregate is capped at *target_mw* (proportional scale-down,
    logged) so the regional total stays honest.

    Returns the MW placed.
    """
    from src.validation.external_tepco import _norm

    candidates: Dict[str, tuple] = {}
    for b in _delivery_buses(net):
        name = net.bus.at[b, "name"]
        if not name:
            continue
        vn = float(net.bus.at[b, "vn_kv"])
        if vn < 50.0:
            continue
        key = _norm(str(name))
        cur = candidates.get(key)
        if cur is None or vn < cur[1]:
            candidates[key] = (b, vn)

    # Eponym-corridor tier (user challenge, ledger 47): Japanese line
    # names carry their destination yard (塚田線 feeds 塚田変電所), so a
    # measured sub absent from the model BY NAME can still be placed at
    # the model endpoint of its eponymous in-band corridor — the yard
    # exists, just named differently/unnamed in OSM. Only endpoints that
    # don't belong to another measured yard qualify (no stealing).
    from src.validation.external_tepco import _model_name_keys

    eponym_lines: Dict[str, list] = {}
    vn_col = net.bus["vn_kv"]
    for idx in net.line.index:
        raw = str(net.line.at[idx, "name"] or "")
        if not raw or raw.startswith("recon_line"):
            continue
        fb = int(net.line.at[idx, "from_bus"])
        if not (50.0 <= float(vn_col.get(fb, 0)) < 140.0):
            continue
        for k in _model_name_keys(raw):
            eponym_lines.setdefault(k, []).append(idx)

    measured_keys = set(measured)

    def _eponym_bus(key: str):
        cands = []
        for idx in eponym_lines.get(key + "線", ()):
            for b in (int(net.line.at[idx, "from_bus"]),
                      int(net.line.at[idx, "to_bus"])):
                vn = float(vn_col.get(b, 0))
                if not (50.0 <= vn < 140.0):
                    continue
                bname = _norm(str(net.bus.at[b, "name"] or ""))
                if bname and bname in measured_keys and bname != key:
                    continue          # endpoint is another measured yard
                cands.append((vn, b))
        return min(cands)[1] if cands else None

    rows = []
    for key, v in measured.items():
        if isinstance(v, dict):
            mw = float(v.get(stat) or v.get("q50") or 0.0)
        else:
            mw = float(v)
        if mw <= 0.0:
            continue
        hit = candidates.get(key)
        if hit is not None:
            rows.append((hit[0], key, mw))
            continue
        b = _eponym_bus(key)
        if b is not None:
            rows.append((b, key, mw))
    if not rows:
        return 0.0

    total = sum(mw for _b, _k, mw in rows)
    scale = min(1.0, target_mw / total) if total > 0 else 1.0
    if scale < 1.0:
        logger.warning(
            "Measured loads (%.0f MW) exceed the regional target "
            "(%.0f MW); scaling by %.2f", total, target_mw, scale)
    for b, key, mw in rows:
        p = mw * scale
        pp.create_load(net, bus=b, p_mw=p, q_mvar=p * tan_phi,
                       name=f"measured_{key}")
    logger.info("Pinned %d measured substation loads (%.0f MW, stat=%s)",
                len(rows), total * scale, stat)
    return total * scale


def _estimate_loads_national(
    net: Any,
    peak_demands: Dict[str, float],
    load_factor: float,
    tan_phi: float,
    voltage_weights: Dict,
    skip_existing: bool = False,
) -> float:
    """Allocate loads for a national (multi-region) network.

    Uses the ``zone`` column on each bus to determine regional
    membership and applies per-region demand targets.

    When *skip_existing* is ``True``, buses with existing loads are
    excluded and the per-zone target is reduced accordingly.
    """
    total_allocated = 0.0

    if "zone" not in net.bus.columns:
        logger.warning(
            "National network has no 'zone' column; "
            "distributing load uniformly"
        )
        total_peak = sum(peak_demands.values())
        target_mw = total_peak * load_factor

        # Reduce target by existing loads when skipping
        existing_mw = 0.0
        if skip_existing and not net.load.empty:
            existing_mw = float(net.load["p_mw"].sum())
            target_mw = max(target_mw - existing_mw, 0.0)

        total_allocated = _allocate_bus_loads(
            net, target_mw, tan_phi, voltage_weights,
            skip_existing=skip_existing,
        )
        return total_allocated + existing_mw

    # Identify buses with existing loads (for skip_existing)
    buses_with_loads = _get_buses_with_loads(net) if skip_existing else set()

    # Group buses by zone
    delivery = set(_delivery_buses(net))
    for zone, group in net.bus.groupby("zone"):
        peak_mw = peak_demands.get(zone, 0)
        if peak_mw <= 0:
            continue

        target_mw = peak_mw * load_factor
        bus_indices = [b for b in group.index if b in delivery]

        # Filter out buses with existing loads and adjust target
        if skip_existing and buses_with_loads:
            existing_zone_mw = 0.0
            if not net.load.empty:
                zone_loads = net.load[net.load["bus"].isin(bus_indices)]
                existing_zone_mw = float(zone_loads["p_mw"].sum())
            target_mw = max(target_mw - existing_zone_mw, 0.0)
            bus_indices = [b for b in bus_indices if b not in buses_with_loads]
            total_allocated += existing_zone_mw

        if not bus_indices:
            continue

        allocated = _allocate_bus_loads_subset(
            net, bus_indices, target_mw, tan_phi, voltage_weights,
        )
        total_allocated += allocated

        logger.info(
            "National model: allocated %.1f MW to zone '%s' (%d buses)",
            allocated, zone, len(bus_indices),
        )

    return total_allocated


def _delivery_buses(net: Any) -> list:
    """Bus indices eligible for synthetic load: real substations only.

    Junction buses (vertex-snap tap points) are typed 'n' by the builder
    — they are points ON a line, not delivery substations, so allocating
    regional demand to them put load in mid-span and dragged corridor
    voltages down artificially. Nets without the type convention (all
    'b' / legacy builders) are unaffected.
    """
    if "type" in net.bus.columns:
        mask = net.bus["type"] != "n"
        if mask.any():                  # never empty the candidate set
            return net.bus.index[mask].tolist()
    return net.bus.index.tolist()


def _allocate_bus_loads(
    net: Any,
    target_mw: float,
    tan_phi: float,
    voltage_weights: Dict,
    skip_existing: bool = False,
    spatial_factors: Dict[int, float] | None = None,
) -> float:
    """Allocate *target_mw* across the delivery (substation) buses.

    When *skip_existing* is ``True``, buses that already have loads
    attached are excluded from the allocation.
    """
    bus_indices = _delivery_buses(net)

    if skip_existing:
        buses_with_loads = _get_buses_with_loads(net)
        bus_indices = [b for b in bus_indices if b not in buses_with_loads]

    return _allocate_bus_loads_subset(
        net, bus_indices, target_mw, tan_phi, voltage_weights,
        spatial_factors=spatial_factors,
    )


MESH_POP_DIR = "data/external/estat"


def _load_mesh_population(mesh_dir: str = MESH_POP_DIR):
    """[(lat, lon, population)] from e-Stat 1 km census mesh files.

    Files are ``tblT001140S<code>.txt`` (scripts/fetch_estat_mesh.py).
    KEY_CODE is the 8-digit 1 km mesh code; T001140001 the population.
    Returns None when the directory has no parsable files (fail-soft).
    """
    import csv
    import glob

    rows = []
    for path in sorted(glob.glob(os.path.join(mesh_dir, "tblT001140S*.txt"))):
        try:
            with open(path, encoding="cp932", newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
                k = header.index("KEY_CODE")
                p = header.index("T001140001")
                for row in reader:
                    code = row[k].strip()
                    if len(code) != 8 or not code.isdigit():
                        continue   # label row / sub-mesh aggregates
                    try:
                        pop = float(row[p])
                    except ValueError:
                        continue
                    if pop <= 0:
                        continue
                    # 1 km mesh decode -> cell centre
                    lat = (int(code[0:2]) / 1.5 + int(code[4]) * 5 / 60
                           + int(code[6]) * 30 / 3600 + 15 / 3600)
                    lon = (100 + int(code[2:4]) + int(code[5]) * 7.5 / 60
                           + int(code[7]) * 45 / 3600 + 22.5 / 3600)
                    rows.append((lat, lon, pop))
        except (OSError, ValueError, IndexError):
            continue
    return rows or None


def population_factors(net, mesh_dir: str = MESH_POP_DIR) -> Dict[int, float]:
    """Per-bus census-population weight (PLAN_66KV M5-2).

    Every 1 km mesh cell's population is assigned to its NEAREST
    delivery bus (a Voronoi partition — no double counting), so a bus's
    factor is "how many people live closest to this substation". The
    caller multiplies this with the voltage-class weight, which keeps
    demand at distribution-class buses. Returns {} when mesh data is
    absent (the allocator then falls back to the class-only rule).

    Known v1 limits (recorded in the ledger): residential population is
    a proxy — industrial/commercial demand (bay-area plants, downtown
    offices) deviates from it.
    """
    cells = _load_mesh_population(mesh_dir)
    if not cells:
        logger.warning("population spatial mode: no mesh data under %s "
                       "— falling back to class-only weights", mesh_dir)
        return {}
    import json as _json

    import numpy as np

    buses, coords = [], []
    geo = net.bus.get("geo")
    for b in _delivery_buses(net):
        try:
            g = _json.loads(geo.at[b]) if geo is not None else None
        except (TypeError, ValueError):
            g = None
        if not g or "coordinates" not in g:
            continue
        lon, lat = g["coordinates"][0], g["coordinates"][1]
        buses.append(b)
        coords.append((lat, lon))
    if not buses:
        return {}
    try:
        from scipy.spatial import cKDTree
    except ImportError:
        logger.warning("population spatial mode needs scipy — skipped")
        return {}
    tree = cKDTree(np.asarray(coords))
    pop = np.zeros(len(buses))
    cell_arr = np.asarray([(la, lo) for la, lo, _p in cells])
    _d, idx = tree.query(cell_arr)
    for i, (_la, _lo, p) in zip(idx, cells):
        pop[i] += p
    total = float(pop.sum())
    if total <= 0:
        return {}
    # Bounded tilt, same convention as degree_factors (0.5 + 0.5*x/mean):
    # the raw Voronoi share REPLACED the class structure and measurably
    # overconcentrated demand (trunk rho 0.617->0.567, magnitude ratio
    # 1.09->1.31 on tokyo, ledger 43) — damping keeps the population
    # signal as a tilt on the voltage-class allocation instead.
    mean = total / len(buses)
    return {b: 0.5 + 0.5 * float(v) / mean for b, v in zip(buses, pop)}


def degree_factors(net) -> Dict[int, float]:
    """Per-bus connectivity factor for spatial load weighting.

    Utilities site substations where the load is, and busy substations
    terminate more feeders — so branch degree is the best in-repo spatial
    proxy for demand density until external ground truth (per-substation
    flow data) validates something better. Bounded to 0.5 + 0.5*deg/mean
    so it tilts the voltage-class allocation rather than replacing it.
    """
    from collections import Counter

    deg = Counter()
    if len(net.line) > 0:
        deg.update(net.line["from_bus"].tolist())
        deg.update(net.line["to_bus"].tolist())
    if len(net.trafo) > 0:
        deg.update(net.trafo["hv_bus"].tolist())
        deg.update(net.trafo["lv_bus"].tolist())
    if not deg:
        return {}
    mean_deg = sum(deg.values()) / len(deg)
    return {b: 0.5 + 0.5 * d / mean_deg for b, d in deg.items()}


def _allocate_bus_loads_subset(
    net: Any,
    bus_indices: list,
    target_mw: float,
    tan_phi: float,
    voltage_weights: Dict,
    spatial_factors: Dict[int, float] | None = None,
) -> float:
    """Allocate *target_mw* across a subset of buses.

    The allocation is proportional to each bus's voltage-class weight,
    optionally tilted by *spatial_factors* (see :func:`degree_factors`).
    """
    if not bus_indices:
        return 0.0

    # Compute per-bus weights
    weights = []
    for idx in bus_indices:
        vn_kv = net.bus.at[idx, "vn_kv"]
        # Find the closest matching voltage weight
        w = _voltage_weight(vn_kv, voltage_weights)
        if spatial_factors:
            w *= spatial_factors.get(idx, 0.5)
        weights.append(w)

    total_weight = sum(weights)
    if total_weight <= 0:
        # Uniform distribution fallback
        total_weight = len(bus_indices)
        weights = [1.0] * len(bus_indices)

    total_allocated = 0.0
    for idx, w in zip(bus_indices, weights):
        p_mw = target_mw * (w / total_weight)
        q_mvar = p_mw * tan_phi

        pp.create_load(
            net,
            bus=idx,
            p_mw=p_mw,
            q_mvar=q_mvar,
            name=f"load_bus_{idx}",
        )
        total_allocated += p_mw

    return total_allocated


def _get_buses_with_loads(net: Any) -> Set[int]:
    """Return the set of bus indices that already have loads attached.

    Args:
        net: pandapower network.

    Returns:
        Set of bus indices with at least one load element.
    """
    if net.load.empty:
        return set()
    return set(net.load["bus"].unique())


def _voltage_weight(vn_kv: float, voltage_weights: Dict) -> float:
    """Look up the voltage weight for a given nominal voltage.

    Falls back to the closest available key if no exact match exists.
    """
    # Try exact integer match first
    key = int(round(vn_kv))
    if key in voltage_weights:
        return voltage_weights[key]

    # Find the closest key
    available = [k for k in voltage_weights if isinstance(k, (int, float)) and k > 0]
    if not available:
        return 0.5  # default

    closest = min(available, key=lambda k: abs(k - vn_kv))
    return voltage_weights[closest]


def scale_generation(net: Any, target_mw: float) -> float:
    """Scale all generator outputs proportionally to meet *target_mw*.

    The external grid (``ext_grid``) absorbs the residual mismatch
    between generation and demand after scaling.

    Args:
        net: pandapower network (modified in place).
        target_mw: Total generation target in MW.

    Returns:
        Actual total generation set (MW) after scaling.
    """
    if len(net.gen) == 0:
        logger.info("No generators to scale; ext_grid will supply all load")
        return 0.0

    total_capacity = net.gen["max_p_mw"].sum()
    if total_capacity <= 0:
        logger.warning("Total generator capacity is zero; skipping scaling")
        return 0.0

    # Scale factor: target / total_capacity, capped at 1.0
    scale = min(target_mw / total_capacity, 1.0)

    net.gen["p_mw"] = net.gen["max_p_mw"] * scale
    # Ensure in_service
    net.gen["in_service"] = True

    actual_total = net.gen["p_mw"].sum()
    logger.info(
        "Scaled %d generators: total=%.1f MW (scale=%.3f, capacity=%.1f MW)",
        len(net.gen),
        actual_total,
        scale,
        total_capacity,
    )
    return actual_total


_OCCTO_AREA_TO_REGION = {
    "北海道": "hokkaido", "東北": "tohoku", "東京": "tokyo", "中部": "chubu",
    "北陸": "hokuriku", "関西": "kansai", "中国": "chugoku",
    "四国": "shikoku", "九州": "kyushu", "沖縄": "okinawa",
}


def demand_config_from_occto(stats_path: str, quantile: str = "median",
                             base_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Demand config whose regional targets are MEASURED area demand.

    ``stats_path`` is the committed aggregate of OCCTO's published 30-min
    area demand (docs/reports/occto_calibration_*.json); ``quantile`` is
    one of its stats keys (``median`` / ``p95`` / ``max``). The values are
    actual MW, so ``load_factor`` is forced to 1.0 — this replaces the
    static "2023 peak x 0.85" guess with a measured operating point
    (median = typical, p95 = the high-load point the TEPCO flow
    comparison effectively probes).
    """
    import json as _json

    base = dict(base_config or load_demand_config())
    with open(stats_path, encoding="utf-8") as f:
        stats = _json.load(f)["area_demand_mw"]
    peaks = {}
    for area, region in _OCCTO_AREA_TO_REGION.items():
        if area in stats and quantile in stats[area]:
            peaks[region] = float(stats[area][quantile])
    missing = [r for r in _OCCTO_AREA_TO_REGION.values() if r not in peaks]
    if missing:
        raise ValueError(f"OCCTO stats missing regions: {missing}")
    base["regional_peak_demand_mw"] = peaks
    base["load_factor"] = 1.0
    base["_demand_source"] = f"occto:{quantile} ({stats_path})"
    return base
