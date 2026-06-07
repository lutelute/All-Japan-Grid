"""MATPOWER-format exporter for All-Japan-Grid.

Converts the All-Japan-Grid GeoJSON network (substations + transmission lines)
into MATPOWER-compatible numpy arrays that can be consumed by psdat-python or
any MATPOWER-compatible power flow solver.

Output arrays (MATPOWER column conventions):
    BUS     (n_bus × 13)   — bus data
    BRANCH  (n_branch × 9) — branch data
    GEN     (n_gen × 10)   — generator data
    GENCOST (n_gen × 7)    — generator cost data (MATPOWER polynomial model 2)
    MD      (14 × n_gen)   — dynamic machine parameters
    ED      (8 × n_gen)    — dynamic exciter parameters
    TD      (3 × n_gen)    — dynamic turbine/governor parameters

A valid ``gencost`` table is required for MATPOWER OPF (``runopf``). Without
it the case can only be used for plain power flow (``runpf``). It is produced
here from the fuel-type cost defaults in
``data/reference/generator_defaults.yaml``.

The case can be built two ways:

1. From the legacy GeoJSON-derived dynamics network (default, ~2189 buses):

       case = build_matpower_case()   # [500,275,154,110,77,66], lf=0.20
       BUS, BRANCH, GEN = case['BUS'], case['BRANCH'], case['GEN']
       baseMVA = case['baseMVA']

2. From a prebuilt :class:`src.model.grid_network.GridNetwork` (e.g. the
   improved "snapped" topology from ``examples/build_snapped_topology.py``):

       from examples.build_snapped_topology import build_network_snapped
       net = build_network_snapped("okinawa")
       case = build_matpower_case(network=net)

Saving to a MATPOWER ``.mat`` file (consumable by MATPOWER / pandapower)::

    from src.matpower.exporter import build_matpower_case, save_case_to_matfile
    case = build_matpower_case(network=net)
    save_case_to_matfile(case, "output/matpower/okinawa.mat")
"""
from __future__ import annotations

import math
import os
from typing import Dict, List, Optional, Tuple

import numpy as np
import scipy.sparse as sp

from src.dynamics.network.builder import GridNetwork, BusData, LineData, assign_generators

# ---------------------------------------------------------------------------
# MATPOWER column indices (0-based)
# ---------------------------------------------------------------------------
# BUS
BUS_I    = 0;  BUS_TYPE = 1
PD       = 2;  QD       = 3
GS       = 4;  BS       = 5
BUS_AREA = 6;  VM       = 7;  VA  = 8
BASE_KV  = 9;  ZONE     = 10
VMAX     = 11; VMIN     = 12

# BRANCH
F_BUS  = 0; T_BUS  = 1
BR_R   = 2; BR_X   = 3; BR_B  = 4
RATE_A = 5; RATE_B = 6; RATE_C = 7
TAP    = 8

# GEN
GEN_BUS  = 0; PG = 1; QG = 2
QMAX     = 3; QMIN = 4; VG = 5
MBASE    = 6; GEN_STATUS = 7
PMAX     = 8; PMIN = 9

# GENCOST (MATPOWER polynomial model)
#   col 0  MODEL   : 1 = piecewise linear, 2 = polynomial
#   col 1  STARTUP : startup cost ($)
#   col 2  SHUTDOWN: shutdown cost ($)
#   col 3  NCOST   : number of coefficients (poly) / data points (pwl)
#   col 4+ COST    : c_(n-1) ... c_0 for f(P) = c2*P^2 + c1*P + c0
GC_MODEL    = 0; GC_STARTUP = 1; GC_SHUTDOWN = 2; GC_NCOST = 3
GC_COST0    = 4
PW_LINEAR   = 1
POLYNOMIAL  = 2

# BUS types
PQ_BUS   = 1
PV_BUS   = 2
REF_BUS  = 3

# ---------------------------------------------------------------------------
# Marginal cost per MWh by fuel type [$/MWh], used to build the GENCOST table.
#
# Sourced from data/reference/generator_defaults.yaml (fuel_cost_per_mwh, in
# JPY/MWh) divided by a nominal FX rate so OPF objective values are in $/h.
# The relative merit order (nuclear < coal < LNG < oil; renewables ~0) is what
# matters for dispatch; absolute magnitudes are a planning approximation.
# Used only when generator_defaults.yaml cannot be read or a fuel is missing.
# ---------------------------------------------------------------------------
_JPY_PER_USD = 150.0

_FALLBACK_COST_USD_PER_MWH: Dict[str, float] = {
    "nuclear":      10.0,
    "hydro":         5.0,
    "pumped_hydro": 13.0,
    "pumped":       13.0,
    "geothermal":    5.0,
    "coal":         30.0,
    "biomass":      20.0,
    "lng":          47.0,
    "gas":          47.0,
    "mixed":        33.0,
    "oil":          60.0,
    "solar":         0.0,
    "wind":          0.0,
    "storage":      13.0,
    "thermal":      40.0,
    "unknown":      33.0,
}

# ---------------------------------------------------------------------------
# Default dynamic parameters by fuel type
# Machine data MD rows:
#   0  H [s]       1  Xd [pu]    2  Xd' [pu]   3  Xd'' [pu]
#   4  Xq [pu]     5  Xq' [pu]   6  Xq'' [pu]
#   7  Td0' [s]    8  Td0'' [s]  9  Tq0' [s]   10 Tq0'' [s]
#   11 Rs [pu]     12 Xls [pu]   13 Dm (raw, ×0.005 = actual Dm)
# ---------------------------------------------------------------------------
_MD_DEFAULTS: Dict[str, List[float]] = {
    #           H     Xd    Xd'   Xd''  Xq    Xq'   Xq''  Td0'  Td0'' Tq0'  Tq0'' Rs    Xls   Dm_raw
    "thermal": [6.0, 1.80, 0.30, 0.25, 1.70, 0.55, 0.25,  8.0,  0.05, 1.0,  0.05, 0.0, 0.15, 10.0],
    "nuclear": [8.0, 1.80, 0.30, 0.25, 1.70, 0.55, 0.25, 10.0,  0.05, 1.5,  0.05, 0.0, 0.15, 10.0],
    "hydro":   [4.0, 0.90, 0.25, 0.20, 0.60, 0.35, 0.20,  5.0,  0.05, 0.8,  0.04, 0.0, 0.10,  5.0],
    "pumped":  [4.5, 0.90, 0.25, 0.20, 0.60, 0.35, 0.20,  5.0,  0.05, 0.8,  0.04, 0.0, 0.10,  5.0],
    "gas":     [5.0, 1.40, 0.25, 0.20, 1.30, 0.40, 0.20,  6.0,  0.05, 1.0,  0.05, 0.0, 0.12,  8.0],
    "oil":     [5.0, 1.50, 0.25, 0.20, 1.40, 0.45, 0.20,  7.0,  0.05, 1.0,  0.05, 0.0, 0.12,  8.0],
    "coal":    [6.0, 1.80, 0.30, 0.25, 1.70, 0.55, 0.25,  8.0,  0.05, 1.0,  0.05, 0.0, 0.15, 10.0],
    "wind":    [4.0, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10,  5.0,  0.05, 0.5,  0.04, 0.0, 0.05,  4.0],
    "solar":   [4.0, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10,  5.0,  0.05, 0.5,  0.04, 0.0, 0.05,  4.0],
    "storage": [4.0, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10,  5.0,  0.05, 0.5,  0.04, 0.0, 0.05,  4.0],
}
_MD_THERMAL = _MD_DEFAULTS["thermal"]

# Exciter data ED rows: KA, TA, KE, TE, KF, TF, Ax, Bx
_ED_DEFAULT = [40.0, 0.020, 1.0, 0.785, 0.063, 0.350, 0.070, 0.910]

# Turbine/Governor data TD rows: TCH, TSV, RD
_TD_DEFAULT = [0.10, 0.05, 0.05]


def _fuel_key(fuel: str) -> str:
    """Map raw fuel string to MD defaults key."""
    f = fuel.lower()
    for key in _MD_DEFAULTS:
        if key in f:
            return key
    return "thermal"


# ---------------------------------------------------------------------------
# Fuel-cost / startup-cost table (cached after first load)
# ---------------------------------------------------------------------------
_FUEL_COST_CACHE: Optional[Dict[str, Dict[str, float]]] = None


def _load_fuel_cost_table(data_dir: str = "data") -> Dict[str, Dict[str, float]]:
    """Load per-fuel marginal/startup/shutdown costs.

    Reads ``data/reference/generator_defaults.yaml`` (JPY units) and converts
    to USD so OPF objective values are in $/h. Falls back to
    ``_FALLBACK_COST_USD_PER_MWH`` if the file is missing or unreadable.

    Returns a dict ``fuel -> {marginal, startup, shutdown}`` in USD where
    ``startup``/``shutdown`` are *per-MW-of-capacity* costs (matching the YAML
    ``startup_cost_per_mw`` convention); callers multiply by capacity.
    """
    global _FUEL_COST_CACHE
    if _FUEL_COST_CACHE is not None:
        return _FUEL_COST_CACHE

    table: Dict[str, Dict[str, float]] = {}
    yaml_path = os.path.join(data_dir, "reference", "generator_defaults.yaml")
    try:
        import yaml  # local import: optional dependency for this path
        with open(yaml_path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        for fuel, params in (raw.get("fuel_types") or {}).items():
            if not isinstance(params, dict):
                continue
            table[fuel.lower()] = {
                "marginal": float(params.get("fuel_cost_per_mwh", 0.0)) / _JPY_PER_USD,
                "startup":  float(params.get("startup_cost_per_mw", 0.0)) / _JPY_PER_USD,
                "shutdown": float(params.get("shutdown_cost_per_mw", 0.0)) / _JPY_PER_USD,
            }
    except (FileNotFoundError, ImportError, ValueError, TypeError):
        table = {}

    # Ensure every fallback fuel has an entry (startup/shutdown 0 if unknown).
    for fuel, cost in _FALLBACK_COST_USD_PER_MWH.items():
        table.setdefault(fuel, {"marginal": cost, "startup": 0.0, "shutdown": 0.0})

    _FUEL_COST_CACHE = table
    return table


def _gencost_fuel_key(fuel: str) -> str:
    """Map a raw fuel string to a cost-table key (more granular than _fuel_key).

    Distinguishes coal / lng / oil / nuclear / hydro / solar / wind / biomass
    so the OPF merit order is meaningful, rather than collapsing everything to
    'thermal' as the dynamics-parameter mapping does.
    """
    f = (fuel or "").lower()
    # Direct / substring matches against known cost keys (most specific first).
    ordered = [
        "nuclear", "pumped_hydro", "pumped", "geothermal", "biomass",
        "hydro", "coal", "lng", "oil", "solar", "wind", "storage", "mixed",
    ]
    for key in ordered:
        if key in f:
            return key
    if "gas" in f or "gtcc" in f:
        return "lng"
    if "thermal" in f:
        return "coal"
    return "unknown"


def build_gencost(
    GEN: np.ndarray,
    gen_fuel: List[str],
    gen_caps_mw: Optional[List[float]] = None,
    data_dir: str = "data",
) -> np.ndarray:
    """Build a MATPOWER GENCOST table (one row per generator).

    Uses the polynomial cost model (MODEL=2, NCOST=3 → quadratic
    ``c2*P^2 + c1*P + c0``). The dominant term is the linear marginal fuel
    cost ``c1`` [$/MWh] derived per fuel type; a small convex quadratic term
    ``c2`` is added so the OPF objective is strictly convex (avoids degenerate
    multiple optima), and ``c0`` is left at 0.

    Parameters
    ----------
    GEN : ndarray (n_gen × ≥10)
        The MATPOWER generator table (used only for the row count / ordering).
    gen_fuel : list of str
        Fuel type per generator, same order as ``GEN`` rows.
    gen_caps_mw : list of float, optional
        Rated capacity [MW] per generator, same order. Used to scale the
        per-MW startup/shutdown costs. If omitted, uses GEN[:, PMAX].
    data_dir : str
        Directory containing ``reference/generator_defaults.yaml``.

    Returns
    -------
    ndarray (n_gen × 7)
        Columns: [MODEL, STARTUP, SHUTDOWN, NCOST, c2, c1, c0].
    """
    n_gen = GEN.shape[0]
    costs = _load_fuel_cost_table(data_dir)
    if gen_caps_mw is None:
        gen_caps_mw = [float(GEN[g, PMAX]) for g in range(n_gen)]

    # Small quadratic curvature so OPF is strictly convex. Chosen so the
    # quadratic adds <~10% to marginal cost at full output of a typical unit.
    C2 = 0.001  # $/MWh^2

    GENCOST = np.zeros((n_gen, 7))
    for g in range(n_gen):
        key = _gencost_fuel_key(gen_fuel[g] if g < len(gen_fuel) else "unknown")
        entry = costs.get(key, costs.get("unknown", {"marginal": 33.0, "startup": 0.0, "shutdown": 0.0}))
        cap = max(float(gen_caps_mw[g]) if g < len(gen_caps_mw) else 0.0, 0.0)
        GENCOST[g, GC_MODEL]    = POLYNOMIAL
        GENCOST[g, GC_STARTUP]  = entry["startup"] * cap
        GENCOST[g, GC_SHUTDOWN] = entry["shutdown"] * cap
        GENCOST[g, GC_NCOST]    = 3
        GENCOST[g, GC_COST0 + 0] = C2                 # c2
        GENCOST[g, GC_COST0 + 1] = entry["marginal"]  # c1 [$/MWh]
        GENCOST[g, GC_COST0 + 2] = 0.0                # c0
    return GENCOST


def diagnose_powerflow_risks(
    BUS: np.ndarray,
    BRANCH: np.ndarray,
    baseMVA: float = 100.0,
    x_high_threshold: float = 0.40,
    q_high_threshold: float = 0.10,
) -> dict:
    """Detect and quantify the three main NR convergence risk factors.

    Returns a dict with keys:
        'radial'        : radial bus count per voltage class
        'q_imbalance'   : reactive surplus Q_flat per voltage class [pu]
        'high_x'        : branch count with X_pu > x_high_threshold
        'isolated'      : buses with degree 0 (disconnected)
        'summary'       : human-readable warning lines
    """
    from collections import defaultdict
    n = BUS.shape[0]
    bus_kv = {int(BUS[i, BUS_I]): BUS[i, BASE_KV] for i in range(n)}
    bus_map = {int(BUS[i, BUS_I]): i for i in range(n)}

    # ── Degree (connectivity) ───────────────────────────────────────────────
    degree = defaultdict(int)
    for k in range(BRANCH.shape[0]):
        fb = int(BRANCH[k, F_BUS]); tb = int(BRANCH[k, T_BUS])
        degree[fb] += 1; degree[tb] += 1

    radial = defaultdict(int)   # kv → count of degree-1 buses
    isolated = []
    for bus_num, kv in bus_kv.items():
        d = degree[bus_num]
        if d == 0:
            isolated.append(bus_num)
        elif d == 1:
            radial[int(kv)] += 1

    # ── Q imbalance at flat start ───────────────────────────────────────────
    Ybus = _build_ybus_for_compensation(BUS, BRANCH, baseMVA)
    rowsum = np.asarray(Ybus.sum(axis=1)).ravel()
    Q_flat = rowsum.imag   # pu; >0 = capacitive surplus

    q_stats: dict = {}
    for kv in sorted(set(int(v) for v in bus_kv.values()), reverse=True):
        mask = np.array([BUS[i, BASE_KV] == kv for i in range(n)])
        qf = Q_flat[mask]
        if len(qf):
            q_stats[kv] = {
                "n": int(len(qf)),
                "max": float(np.max(np.abs(qf))),
                "mean": float(np.mean(qf)),
                "sum": float(np.sum(qf)),
            }

    # ── High-impedance branches ──────────────────────────────────────────────
    high_x = int(np.sum(BRANCH[:, BR_X] > x_high_threshold))
    max_x  = float(BRANCH[:, BR_X].max()) if len(BRANCH) else 0.0

    # ── Build summary warnings ───────────────────────────────────────────────
    warnings = []
    for kv, cnt in sorted(radial.items(), reverse=True):
        if cnt:
            warnings.append(
                f"[RADIAL] {kv} kV: {cnt} leaf buses (deg=1) "
                "→ possible Jacobian near-singularity"
            )
    if isolated:
        warnings.append(f"[ISOLATED] {len(isolated)} buses with degree=0 "
                        "→ power balance impossible, will diverge")
    for kv, s in q_stats.items():
        if s["max"] > q_high_threshold:
            warnings.append(
                f"[Q-IMBALANCE] {kv} kV: max Q_flat={s['max']:.3f} pu "
                f"({s['max']*baseMVA:.0f} MVAr) "
                "→ add shunt reactor to compensate line charging"
            )
    if high_x:
        warnings.append(f"[HIGH-X] {high_x} branches with X_pu > {x_high_threshold} "
                        f"(max {max_x:.3f}) → long/weak connections, skip or aggregate")
    if not warnings:
        warnings.append("[OK] No major convergence risks detected.")

    return {
        "radial": dict(radial),
        "q_imbalance": q_stats,
        "high_x": high_x,
        "max_x": max_x,
        "isolated": isolated,
        "summary": warnings,
    }


def _build_ybus_for_compensation(
    BUS: np.ndarray,
    BRANCH: np.ndarray,
    baseMVA: float,
) -> sp.csc_matrix:
    """Sparse Y-bus from MATPOWER BUS/BRANCH arrays (for reactive compensation).

    Includes existing bus shunts and branch line charging (B/2 per end).
    """
    n = BUS.shape[0]
    bus_nums = BUS[:, BUS_I].astype(int)
    bus_map = {int(b): i for i, b in enumerate(bus_nums)}

    rows, cols, vals = [], [], []

    # Bus shunts (GS + jBS)
    for i in range(n):
        gs = BUS[i, GS] / baseMVA
        bs = BUS[i, BS] / baseMVA
        rows.append(i); cols.append(i); vals.append(complex(gs, bs))

    # Branch π-model contributions
    for k in range(BRANCH.shape[0]):
        fi = bus_map[int(BRANCH[k, F_BUS])]
        ti = bus_map[int(BRANCH[k, T_BUS])]
        R  = BRANCH[k, BR_R]
        X  = BRANCH[k, BR_X]
        B  = BRANCH[k, BR_B]
        tap = BRANCH[k, TAP] if BRANCH[k, TAP] != 0.0 else 1.0

        z = complex(R, X)
        if abs(z) < 1e-15:
            continue
        y_s = 1.0 / z
        y_c = 0.5j * B

        rows += [fi, ti, fi, ti]
        cols += [fi, ti, ti, fi]
        vals += [(y_s + y_c) / (tap * tap), y_s + y_c,
                 -y_s / tap, -y_s / tap]

    Y = sp.coo_matrix((vals, (rows, cols)), shape=(n, n), dtype=complex)
    return Y.tocsc()


def _add_shunt_compensation(
    BUS: np.ndarray,
    BRANCH: np.ndarray,
    baseMVA: float,
    method: str = "local",
    alpha: float = 0.9,
    v_threshold: float = 0.05,
) -> "tuple[np.ndarray, dict]":
    """Add shunt reactive compensation to PQ buses.

    Fixes Newton-Raphson divergence caused by reactive surplus/deficit at
    flat start (V = 1 pu, θ = 0).  The flat-start reactive injection is:

        Q_flat[i] = imag(sum_j Ybus[i,j])   [pu]

    Positive Q_flat → capacitive surplus (long EHV lines) → add REACTOR (BS < 0).
    Negative Q_flat → inductive deficit (transformer-heavy buses) → add CAPACITOR (BS > 0).

    Parameters
    ----------
    method : 'local' | 'sensitivity'
        'local'       — compensate every PQ bus for its own Q_flat.
        'sensitivity' — compensate only high-voltage-sensitivity buses
                        (buses where estimated |ΔV| = |Q_flat/L_diag| > v_threshold).
    alpha : float [0, 1]
        Fraction of surplus to compensate.  0.9 leaves a 10% residual to
        avoid exact Jacobian singularity at flat start.
    v_threshold : float
        Minimum estimated voltage deviation [pu] to trigger compensation
        in the 'sensitivity' method.

    Returns
    -------
    BUS_out : ndarray — modified copy of BUS with updated BS column
    info : dict
        Q_flat_pu     : net reactive at flat start per bus [pu]
        BS_added_MVAr : added shunt susceptance per bus [MVAr]
        n_compensated : number of buses compensated
        total_MVAr    : algebraic sum of added MVAr (negative = net reactor)
        method        : string label
    """
    BUS = BUS.copy()
    n   = BUS.shape[0]

    # ── Build Y-bus and flat-start Q injection ───────────────────────────
    Ybus     = _build_ybus_for_compensation(BUS, BRANCH, baseMVA)
    rowsum   = np.asarray(Ybus.sum(axis=1)).ravel()  # complex, shape (n,)
    Q_flat   = rowsum.imag                            # [pu]; >0 = capacitive surplus

    bus_type = BUS[:, BUS_TYPE].astype(int)
    pq_mask  = bus_type == PQ_BUS

    BS_added = np.zeros(n)  # [MVAr]

    if method == "local":
        # ── Method 1: local line-charging compensation ───────────────────
        # Each PQ bus gets a shunt to cancel its own Q_flat exactly.
        # BS_comp = -alpha * Q_flat * baseMVA  (negative = reactor for Q_flat>0)
        for i in np.where(pq_mask)[0]:
            bs = -alpha * Q_flat[i] * baseMVA
            BUS[i, BS] += bs
            BS_added[i] = bs

    elif method == "sensitivity":
        # ── Method 2: voltage-sensitivity ranked placement ───────────────
        # Estimate flat-start Jacobian L-block diagonal:
        #   L[i,i] = Q_flat[i] - imag(Ybus[i,i])   (at V=1, angle=0)
        # Voltage deviation estimate: |ΔV[i]| ≈ |Q_flat[i]| / |L[i,i]|
        # → compensate buses with |ΔV| > v_threshold (most urgent first)
        B_diag  = np.asarray(Ybus.diagonal()).imag   # [pu]
        L_diag  = Q_flat - B_diag                    # [pu]
        L_safe  = np.where(np.abs(L_diag) > 1e-8, L_diag, 1e-8)
        dV_est  = np.abs(Q_flat / L_safe)            # urgency [pu]

        for i in np.where(pq_mask & (dV_est > v_threshold))[0]:
            bs = -alpha * Q_flat[i] * baseMVA
            BUS[i, BS] += bs
            BS_added[i] = bs
    else:
        raise ValueError(f"Unknown shunt_compensation method '{method}'")

    n_comp = int(np.count_nonzero(BS_added))
    info = {
        "Q_flat_pu":     Q_flat,
        "BS_added_MVAr": BS_added,
        "n_compensated": n_comp,
        "total_MVAr":    float(BS_added.sum()),
        "method":        method,
    }
    return BUS, info


def build_matpower_case(
    voltage_levels: List[int] = None,
    data_dir: str = "data",
    baseMVA: float = 100.0,
    load_factor: float = 0.20,
    qg_ratio: float = 0.30,
    shunt_compensation: Optional[str] = None,
    compensation_alpha: float = 0.9,
    compensation_v_threshold: float = 0.05,
    hv_hops: int = 4,
    isolate_regions: Optional[List[str]] = ("hokkaido",),
    target_regions: Optional[List[str]] = None,
    drop_cross_region_links: Optional[List[Tuple[str, str]]] = None,
    network: Optional["object"] = None,
    # Note on the default: empirically, dropping kansai↔shikoku breaks NR
    # convergence (OSM conflates the 1400 MW Kii Channel HVDC with real AC
    # connections through Shikoku that supply Awaji/Tokushima). Dropping
    # tokyo↔chubu has the same issue — OSM mixes the 50/60 Hz FCs with real
    # 60 Hz AC connections. Until the specific HVDC line IDs are identified,
    # only the hokkaido isolation (which is geographically unambiguous) is
    # applied by default. ``target_regions`` lets callers build a single-
    # subsystem case (e.g. Hokkaido only) which is the proper way to model
    # the AC side of an HVDC inter-tie.
) -> Dict:
    """Build a MATPOWER-format case from the All-Japan-Grid GeoJSON data.

    Parameters
    ----------
    voltage_levels : list of int, optional
        Voltage levels [kV] to include. Default: [500, 275, 154, 110, 77, 66].
    data_dir : str
        Path to the data directory containing GeoJSON files.
    baseMVA : float
        System MVA base.
    load_factor : float
        Generator output as fraction of capacity (used for PG initial guess).
    qg_ratio : float
        QG / PG ratio for initial reactive power dispatch.
    network : src.model.grid_network.GridNetwork, optional
        A prebuilt model GridNetwork (substations / transmission_lines /
        generators), e.g. the output of
        ``examples.build_snapped_topology.build_network_snapped(region)``.
        When provided, the case is built directly from this topology and the
        GeoJSON-loading / region-isolation parameters above are ignored.

    Returns
    -------
    dict with keys:
        'BUS'     — ndarray (n_bus, 13)
        'BRANCH'  — ndarray (n_branch, 9)
        'GEN'     — ndarray (n_gen, 10)
        'GENCOST' — ndarray (n_gen, 7)   MATPOWER cost table (OPF-ready)
        'gencost' — alias of 'GENCOST' (lowercase MATPOWER field name)
        'MD'      — ndarray (14, n_gen)  machine dynamic data
        'ED'      — ndarray (8, n_gen)   exciter dynamic data
        'TD'      — ndarray (3, n_gen)   turbine dynamic data
        'baseMVA' — float
        'gen_fuel' — list of str, fuel type per generator
        'bus_names' — list of str
    """
    if network is not None:
        return _build_case_from_model_network(
            network,
            baseMVA=baseMVA,
            load_factor=load_factor,
            qg_ratio=qg_ratio,
            shunt_compensation=shunt_compensation,
            compensation_alpha=compensation_alpha,
            compensation_v_threshold=compensation_v_threshold,
            data_dir=data_dir,
        )

    if voltage_levels is None:
        voltage_levels = [500, 275, 154, 110, 77, 66]

    # ── 1. Build network (with disk cache for slow multi-kV builds) ───────
    cache_dir = os.path.join(data_dir, "..", "data", "cache") if os.path.isdir(data_dir) else None
    net = GridNetwork.from_geojson(
        data_dir, voltage_levels=voltage_levels, cache_dir=cache_dir
    )

    # ── 1b. HVDC-connected region isolation ──────────────────────────────
    # Japanese grid has DC inter-ties (北本連系: hokkaido↔tohoku, 紀伊水道直流連系:
    # kansai↔shikoku) and back-to-back FCs (50/60 Hz boundary: tokyo↔chubu).
    # OSM models these as AC lines, which causes huge angle accumulation in NR.
    # Drop those regions' buses from the main case so the AC NR converges on
    # the synchronous backbone. Equivalent HVDC P-injections are handled
    # separately (out of scope for this build).
    if target_regions:
        # When the caller asks for a specific subsystem, isolate everything
        # else. This is the proper way to model an HVDC-connected island
        # (e.g. Hokkaido) as a standalone AC NR case.
        drop = set(b.region for b in net.buses) - set(target_regions)
        isolate_regions = list(drop) if drop else None
    if isolate_regions:
        drop = set(isolate_regions)
        old_buses = list(net.buses)
        keep_old_ids = [b.id for b in old_buses if b.region not in drop]
        if len(keep_old_ids) < len(old_buses):
            from src.dynamics.network.builder import BusData, LineData, GridNetwork as _GN
            kept = [b for b in old_buses if b.region not in drop]
            old2new = {b.id: i for i, b in enumerate(kept)}
            new_buses = [BusData(
                id=i, name=b.name, base_kv=b.base_kv,
                region=b.region, lat=b.lat, lon=b.lon,
                bus_type=b.bus_type, V_mag=b.V_mag, V_ang=b.V_ang,
                P_gen=b.P_gen, Q_gen=b.Q_gen,
                P_load=b.P_load, Q_load=b.Q_load,
            ) for i, b in enumerate(kept)]
            new_lines = []
            for ln in net.lines:
                fi = old2new.get(ln.from_bus); ti = old2new.get(ln.to_bus)
                if fi is not None and ti is not None:
                    new_lines.append(LineData(
                        from_bus=fi, to_bus=ti, R_pu=ln.R_pu, X_pu=ln.X_pu,
                        B_pu=ln.B_pu, base_kv=ln.base_kv,
                        length_km=ln.length_km, rating_mva=ln.rating_mva,
                    ))
            print(f"  [HVDC-ISOLATE] dropped {len(isolate_regions)} regions "
                  f"({', '.join(sorted(drop))}): {len(old_buses)} → "
                  f"{len(new_buses)} buses, {len(net.lines)} → "
                  f"{len(new_lines)} lines")
            net = _GN(new_buses, new_lines, net.sbase_mva)

    # ── 1c. Drop AC-modeled DC inter-ties between specified region pairs ──
    if drop_cross_region_links:
        from src.dynamics.network.builder import LineData, GridNetwork as _GN
        drop_pairs = {frozenset(p) for p in drop_cross_region_links}
        new_lines = []
        n_dropped = 0
        bus_region = {b.id: b.region for b in net.buses}
        for ln in net.lines:
            pair = frozenset({bus_region.get(ln.from_bus, ""),
                              bus_region.get(ln.to_bus, "")})
            if pair in drop_pairs and len(pair) == 2:
                n_dropped += 1
                continue
            new_lines.append(ln)
        if n_dropped:
            print(f"  [HVDC-CROSS] dropped {n_dropped} cross-region AC lines "
                  f"({', '.join('↔'.join(sorted(p)) for p in drop_pairs)})")
            net = _GN(list(net.buses), new_lines, net.sbase_mva)

    lcc = net.largest_connected_component()
    # Filter out radial chains far from the HV backbone.
    # 77 kV buses > 2 hops from 154 kV, or 66 kV buses > 2 hops from 110 kV,
    # create ill-conditioned Jacobians due to very high X/R ratios.
    if any(v <= 66 for v in (voltage_levels or [500, 275])):
        lcc = lcc.filter_by_hv_distance(hv_threshold_kv=110.0, max_hops=hv_hops)
        lcc = lcc.largest_connected_component()
    elif any(v <= 77 for v in (voltage_levels or [500, 275])):
        lcc = lcc.filter_by_hv_distance(hv_threshold_kv=154.0, max_hops=hv_hops)
        # Re-extract LCC: hop filter may disconnect sub-clusters that were
        # bridged through removed lower-kV buses, leaving isolated islands.
        lcc = lcc.largest_connected_component()
    n_bus = lcc.nb

    # ── 2. Generator assignment ──────────────────────────────────────────
    gens_raw = assign_generators(lcc, data_dir)
    # Aggregate: one generator per bus (largest capacity wins)
    bus_gen: Dict[int, Tuple[str, float, str]] = {}
    for bus_idx, fuel, cap_mw, name in gens_raw:
        if bus_idx not in bus_gen or cap_mw > bus_gen[bus_idx][1]:
            bus_gen[bus_idx] = (fuel, cap_mw, name)

    gen_bus_list = sorted(bus_gen.keys())
    n_gen = len(gen_bus_list)

    # Slack bus: well-connected generator bus with large capacity.
    # Radial buses (degree=1) make poor slack buses because they can't
    # distribute system mismatches. Prefer buses with degree ≥ 3.
    from collections import Counter as _Counter
    _bus_degree: Dict[int, int] = _Counter()
    for _ln in lcc.lines:
        _bus_degree[_ln.from_bus] += 1
        _bus_degree[_ln.to_bus]   += 1

    def _slack_score(b: int) -> tuple:
        deg = _bus_degree.get(b, 0)
        cap = bus_gen[b][1]
        # (connectivity tier, capacity): prefer well-connected (≥3) over radial
        tier = 2 if deg >= 3 else (1 if deg == 2 else 0)
        return (tier, cap)

    slack_bus_idx = max(bus_gen.keys(), key=_slack_score)

    # Total generation → total load.
    # Cap total to Japan's realistic peak demand so adding more matched generators
    # does not artificially inflate the network power flow.
    # Japan 2022 summer peak ≈ 170 GW; installed capacity ≫ this value.
    JAPAN_PEAK_MW = 170_000.0
    total_cap_mw = sum(bus_gen[b][1] for b in gen_bus_list)
    total_gen_mw = min(total_cap_mw, JAPAN_PEAK_MW) * load_factor
    pg_scale     = total_gen_mw / max(total_cap_mw * load_factor, 1.0)

    # Load distribution: weight ∝ kV² (placing demand at HV ↔ MV buses so the
    # NR Jacobian stays well-conditioned). The earlier kV-class-unit weighting
    # (66 kV dominated) caused 66 kV radial buses to make the matrix singular.
    # The Issue-#12-style improvement (66 kV-heavy distribution) belongs in a
    # separate pass after AC NR convergence is verified on this weighting.
    all_weights: Dict[int, float] = {}
    for i in range(n_bus):
        if i in bus_gen:
            continue
        kv = lcc.buses[i].base_kv
        all_weights[i] = kv ** 2
    if not all_weights:
        all_weights = {i: 1.0 for i in range(n_bus)}
    total_weight = sum(all_weights.values()) or 1.0
    load_scale = total_gen_mw / total_weight

    # ── 3. BUS array (n_bus × 13) ────────────────────────────────────────
    BUS = np.zeros((n_bus, 13))
    for i, b in enumerate(lcc.buses):
        bus_1idx = i + 1
        is_gen_bus = i in bus_gen
        bus_kv = b.base_kv
        if i == slack_bus_idx:
            btype = REF_BUS
        elif is_gen_bus and bus_kv >= 77.0:
            # Only make buses PV if at sub-transmission level or above.
            # 66 kV generator buses remain PQ to avoid ill-conditioning;
            # their generation is included in the load balance.
            btype = PV_BUS
        else:
            btype = PQ_BUS

        # Distribute load from all_weights (gen buses also get reduced load)
        pd_mw = all_weights.get(i, 0.0) * load_scale
        qd_mvar = pd_mw * qg_ratio

        BUS[i, BUS_I]    = bus_1idx
        BUS[i, BUS_TYPE] = btype
        BUS[i, PD]       = pd_mw
        BUS[i, QD]       = qd_mvar
        BUS[i, GS]       = 0.0
        BUS[i, BS]       = 0.0
        BUS[i, BUS_AREA] = 1
        BUS[i, VM]       = b.V_mag
        BUS[i, VA]       = math.degrees(b.V_ang)
        BUS[i, BASE_KV]  = b.base_kv
        BUS[i, ZONE]     = 1
        BUS[i, VMAX]     = 1.05
        BUS[i, VMIN]     = 0.95

    # ── 4. BRANCH array (n_branch × 9) ──────────────────────────────────
    n_br = len(lcc.lines)
    BRANCH = np.zeros((n_br, 9))
    for k, ln in enumerate(lcc.lines):
        BRANCH[k, F_BUS]  = ln.from_bus + 1   # 1-indexed
        BRANCH[k, T_BUS]  = ln.to_bus + 1
        BRANCH[k, BR_R]   = max(ln.R_pu, 1e-6)
        BRANCH[k, BR_X]   = max(ln.X_pu, 1e-6)
        BRANCH[k, BR_B]   = ln.B_pu
        # デフォルト熱容量: 電圧クラス別の標準的な 1 回線定格 [MVA]
        # (RATE_A=0 は loading_pct が計算不能になるため、電圧別の典型値を使用)
        _DEFAULT_RATE: Dict[int, float] = {
            500: 1500.0, 275: 800.0, 154: 400.0,
            110: 250.0,   77: 200.0,  66: 150.0,
        }
        kv_round = int(round(ln.base_kv))
        rate = ln.rating_mva if ln.rating_mva > 0 else _DEFAULT_RATE.get(kv_round, 100.0)
        BRANCH[k, RATE_A] = rate
        BRANCH[k, RATE_B] = rate
        BRANCH[k, RATE_C] = rate
        BRANCH[k, TAP]    = 0.0   # 0 = line (no transformer tap)

    # ── 4b. Convergence diagnostics (always run, log risk factors) ──────────
    diag = diagnose_powerflow_risks(BUS, BRANCH, baseMVA)
    for warn in diag["summary"]:
        print(f"  {warn}")

    # ── 4c. Optional shunt reactive compensation ──────────────────────────
    comp_info = None
    if shunt_compensation is not None:
        BUS, comp_info = _add_shunt_compensation(
            BUS, BRANCH, baseMVA,
            method=shunt_compensation,
            alpha=compensation_alpha,
            v_threshold=compensation_v_threshold,
        )

    # ── 5. GEN array (n_gen × 10) ────────────────────────────────────────
    GEN = np.zeros((n_gen, 10))
    gen_fuel: List[str] = []
    for g, bus_idx in enumerate(gen_bus_list):
        fuel, cap_mw, _ = bus_gen[bus_idx]
        pg = cap_mw * load_factor * pg_scale   # MW (pg_scale=1 normally)
        qg = pg * qg_ratio           # MVAr initial dispatch
        GEN[g, GEN_BUS]    = bus_idx + 1   # 1-indexed
        GEN[g, PG]         = pg
        GEN[g, QG]         = qg
        GEN[g, QMAX]       = cap_mw * 0.50
        GEN[g, QMIN]       = -cap_mw * 0.25
        GEN[g, VG]         = lcc.buses[bus_idx].V_mag
        GEN[g, MBASE]      = baseMVA
        GEN[g, GEN_STATUS] = 1
        GEN[g, PMAX]       = cap_mw
        GEN[g, PMIN]       = 0.0
        gen_fuel.append(fuel)

    # ── 6. Dynamic machine data MD (14 × n_gen) ──────────────────────────
    MD = np.zeros((14, n_gen))
    for g, fuel in enumerate(gen_fuel):
        cap_mw = bus_gen[gen_bus_list[g]][1]
        params = list(_MD_DEFAULTS.get(_fuel_key(fuel), _MD_THERMAL))
        # Scale H to system base: H_sys = H_machine * (MBASE_machine / baseMVA)
        # We assume MBASE_machine = cap_mw (single machine per bus)
        params[0] = params[0] * max(cap_mw, baseMVA) / baseMVA
        MD[:, g] = params

    # ── 7. Exciter data ED (8 × n_gen) ───────────────────────────────────
    ED = np.tile(np.array(_ED_DEFAULT, dtype=float), (n_gen, 1)).T

    # ── 8. Turbine data TD (3 × n_gen) ───────────────────────────────────
    TD = np.tile(np.array(_TD_DEFAULT, dtype=float), (n_gen, 1)).T

    bus_names = [b.name for b in lcc.buses]

    # ── 9. GENCOST (n_gen × 7) — required for OPF ─────────────────────────
    gen_caps = [bus_gen[gen_bus_list[g]][1] for g in range(n_gen)]
    GENCOST = build_gencost(GEN, gen_fuel, gen_caps_mw=gen_caps, data_dir=data_dir)

    return {
        "BUS":       BUS,
        "BRANCH":    BRANCH,
        "GEN":       GEN,
        "GENCOST":   GENCOST,
        "gencost":   GENCOST,
        "MD":        MD,
        "ED":        ED,
        "TD":        TD,
        "baseMVA":   baseMVA,
        "gen_fuel":  gen_fuel,
        "bus_names": bus_names,
        "n_gen":     n_gen,
        "n_bus":     n_bus,
        "slack_bus": slack_bus_idx + 1,  # 1-indexed
        "gen_buses_1idx": [b + 1 for b in gen_bus_list],
        "compensation": comp_info,
        "diagnostics": diag,
    }


# ---------------------------------------------------------------------------
# Model-GridNetwork → MATPOWER case (snapped topology path)
# ---------------------------------------------------------------------------
# Series-impedance reference (Ω/km, μS/km) per voltage class, used to convert
# a model GridNetwork (which carries geometry/length but not pu params) into
# MATPOWER pu values. Mirrors src/dynamics/network/builder.LINE_PARAMS_OHM_KM
# so the two paths agree electrically.
_LINE_OHM_KM: Dict[int, Dict[str, float]] = {
    500: {"r": 0.02, "x": 0.30, "b_us": 2.7},
    275: {"r": 0.06, "x": 0.35, "b_us": 2.3},
    220: {"r": 0.07, "x": 0.37, "b_us": 2.1},
    187: {"r": 0.08, "x": 0.38, "b_us": 2.0},
    154: {"r": 0.10, "x": 0.40, "b_us": 1.8},
    132: {"r": 0.11, "x": 0.41, "b_us": 1.6},
    110: {"r": 0.12, "x": 0.42, "b_us": 1.5},
    77:  {"r": 0.18, "x": 0.45, "b_us": 1.2},
    66:  {"r": 0.20, "x": 0.45, "b_us": 1.0},
}

_DEFAULT_RATE_MVA: Dict[int, float] = {
    500: 1500.0, 275: 800.0, 220: 600.0, 187: 500.0, 154: 400.0,
    132: 300.0, 110: 250.0, 77: 200.0, 66: 150.0,
}


def _nearest_kv_class(kv: float) -> int:
    """Snap an arbitrary kV to the nearest known voltage class key."""
    if kv <= 0:
        return 154  # neutral mid-range default for unknown-voltage lines
    return min(_LINE_OHM_KM.keys(), key=lambda k: abs(k - kv))


def _model_line_pu(volt_kv: float, length_km: float, baseMVA: float,
                   num_parallel: int = 1):
    """Compute (R_pu, X_pu, B_pu, rating_mva) for a model line.

    Uses the same z_base = V^2 / S_base convention as the dynamics builder.
    ``num_parallel`` bakes the parallel-circuit bundle into the single
    branch (series Z / n, shunt B * n, rating * n) — the same convention
    PandapowerBuilder applies via the ``parallel`` column, so the .mat
    case and the pandapower validation network stay electrically
    identical (REVIEW_FINDINGS P0 #7).
    """
    cls = _nearest_kv_class(volt_kv)
    p = _LINE_OHM_KM[cls]
    v_used = volt_kv if volt_kv > 0 else float(cls)
    length_km = max(length_km, 0.1)
    par = max(int(num_parallel or 1), 1)
    z_base = (v_used ** 2) / baseMVA
    R_pu = p["r"] * length_km / z_base / par
    X_pu = p["x"] * length_km / z_base / par
    # B_pu = b[S/km] * L / Y_base = b_us*1e-6 * L * z_base
    B_pu = p["b_us"] * 1e-6 * length_km * z_base * par
    rating = _DEFAULT_RATE_MVA[cls] * par
    return R_pu, X_pu, B_pu, rating


def _build_case_from_model_network(
    network: "object",
    baseMVA: float = 100.0,
    load_factor: float = 0.20,
    qg_ratio: float = 0.30,
    shunt_compensation: Optional[str] = None,
    compensation_alpha: float = 0.9,
    compensation_v_threshold: float = 0.05,
    data_dir: str = "data",
) -> Dict:
    """Build a MATPOWER case from a model GridNetwork (snapped topology).

    The model GridNetwork (``src.model.grid_network.GridNetwork``) provides
    substations (buses), transmission_lines (branches with geometry/length but
    no pu params), and generators. This restricts to the largest connected
    component, derives pu line parameters from voltage class + length, places
    load weighted by kV^2, assigns one PV/REF generator per bus, and produces
    a full BUS/BRANCH/GEN/GENCOST case (OPF-ready).
    """
    from collections import Counter as _Counter

    subs = list(network.substations)
    lines = list(network.transmission_lines)

    # ── Restrict to the largest connected component (well-posed AC NR) ────
    sid_to_idx = {s.id: i for i, s in enumerate(subs)}
    adj: Dict[int, set] = {i: set() for i in range(len(subs))}
    edge_idx: List[Tuple[int, int, "object"]] = []
    for ln in lines:
        fi = sid_to_idx.get(ln.from_substation_id)
        ti = sid_to_idx.get(ln.to_substation_id)
        if fi is None or ti is None or fi == ti:
            continue
        adj[fi].add(ti)
        adj[ti].add(fi)
        edge_idx.append((fi, ti, ln))

    # BFS components
    seen = [False] * len(subs)
    best_comp: List[int] = []
    for start in range(len(subs)):
        if seen[start]:
            continue
        stack = [start]
        seen[start] = True
        comp = []
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in adj[u]:
                if not seen[v]:
                    seen[v] = True
                    stack.append(v)
        if len(comp) > len(best_comp):
            best_comp = comp

    keep = set(best_comp)
    old2new = {old: new for new, old in enumerate(sorted(keep))}
    kept_subs = [subs[old] for old in sorted(keep)]
    n_bus = len(kept_subs)
    if n_bus == 0:
        raise ValueError(
            f"Model network '{getattr(network, 'region', '?')}' has no "
            "connected buses to export"
        )

    # ── Branches within the kept component ────────────────────────────────
    kept_edges = [
        (old2new[fi], old2new[ti], ln)
        for (fi, ti, ln) in edge_idx
        if fi in keep and ti in keep
    ]

    # ── Generators → bus (aggregate largest capacity per bus) ─────────────
    bus_gen: Dict[int, Tuple[str, float, str]] = {}
    for gen in network.generators:
        bi = sid_to_idx.get(gen.connected_bus_id)
        if bi is None or bi not in keep:
            continue
        ni = old2new[bi]
        cap = float(gen.capacity_mw)
        fuel = str(gen.fuel_type)
        if ni not in bus_gen or cap > bus_gen[ni][1]:
            bus_gen[ni] = (fuel, cap, gen.name)

    gen_bus_list = sorted(bus_gen.keys())
    n_gen = len(gen_bus_list)

    # Bus degree (for slack selection + diagnostics)
    deg: Dict[int, int] = _Counter()
    for fi, ti, _ in kept_edges:
        deg[fi] += 1
        deg[ti] += 1

    # ── Slack: best-connected, highest-capacity generator bus ─────────────
    if n_gen > 0:
        def _slack_score(b: int) -> tuple:
            d = deg.get(b, 0)
            tier = 2 if d >= 3 else (1 if d == 2 else 0)
            return (tier, bus_gen[b][1])
        slack_bus_idx = max(bus_gen.keys(), key=_slack_score)
    else:
        # No generators: pick the most-connected bus as a synthetic slack.
        slack_bus_idx = max(range(n_bus), key=lambda b: deg.get(b, 0))

    # ── Total generation target → matched load ────────────────────────────
    JAPAN_PEAK_MW = 170_000.0
    total_cap_mw = sum(bus_gen[b][1] for b in gen_bus_list) if n_gen else 0.0
    if total_cap_mw > 0:
        total_gen_mw = min(total_cap_mw, JAPAN_PEAK_MW) * load_factor
    else:
        # No generators: size a nominal load off bus count so the NR is posed.
        total_gen_mw = max(n_bus * 5.0, 50.0)

    # ── Load distribution weighted by kV^2 (HV-heavy keeps Jacobian sane) ──
    all_weights: Dict[int, float] = {}
    for i in range(n_bus):
        if i in bus_gen:
            continue
        kv = max(kept_subs[i].voltage_kv, 1.0)
        all_weights[i] = kv ** 2
    if not all_weights:
        all_weights = {i: 1.0 for i in range(n_bus)}
    total_weight = sum(all_weights.values()) or 1.0
    load_scale = total_gen_mw / total_weight

    # ── BUS array ─────────────────────────────────────────────────────────
    BUS = np.zeros((n_bus, 13))
    for i, sub in enumerate(kept_subs):
        bus_kv = sub.voltage_kv if sub.voltage_kv > 0 else 154.0
        if i == slack_bus_idx:
            btype = REF_BUS
        elif i in bus_gen and bus_kv >= 77.0:
            btype = PV_BUS
        else:
            btype = PQ_BUS
        pd_mw = all_weights.get(i, 0.0) * load_scale
        BUS[i, BUS_I]    = i + 1
        BUS[i, BUS_TYPE] = btype
        BUS[i, PD]       = pd_mw
        BUS[i, QD]       = pd_mw * qg_ratio
        BUS[i, GS]       = 0.0
        BUS[i, BS]       = 0.0
        BUS[i, BUS_AREA] = 1
        BUS[i, VM]       = 1.0
        BUS[i, VA]       = 0.0
        BUS[i, BASE_KV]  = bus_kv
        BUS[i, ZONE]     = 1
        BUS[i, VMAX]     = 1.05
        BUS[i, VMIN]     = 0.95

    # ── BRANCH array ──────────────────────────────────────────────────────
    n_br = len(kept_edges)
    BRANCH = np.zeros((n_br, 9))
    for k, (fi, ti, ln) in enumerate(kept_edges):
        kv = ln.voltage_kv if ln.voltage_kv > 0 else max(
            kept_subs[fi].voltage_kv, kept_subs[ti].voltage_kv, 0.0)
        R_pu, X_pu, B_pu, rating = _model_line_pu(
            kv, ln.length_km, baseMVA, getattr(ln, "num_parallel", 1))
        BRANCH[k, F_BUS]  = fi + 1
        BRANCH[k, T_BUS]  = ti + 1
        BRANCH[k, BR_R]   = max(R_pu, 1e-6)
        BRANCH[k, BR_X]   = max(X_pu, 1e-6)
        BRANCH[k, BR_B]   = B_pu
        BRANCH[k, RATE_A] = rating
        BRANCH[k, RATE_B] = rating
        BRANCH[k, RATE_C] = rating
        BRANCH[k, TAP]    = 0.0

    # ── Diagnostics + optional shunt compensation ─────────────────────────
    diag = diagnose_powerflow_risks(BUS, BRANCH, baseMVA)
    for warn in diag["summary"]:
        print(f"  {warn}")

    comp_info = None
    if shunt_compensation is not None:
        BUS, comp_info = _add_shunt_compensation(
            BUS, BRANCH, baseMVA,
            method=shunt_compensation,
            alpha=compensation_alpha,
            v_threshold=compensation_v_threshold,
        )

    # ── GEN array ─────────────────────────────────────────────────────────
    GEN = np.zeros((n_gen, 10))
    gen_fuel: List[str] = []
    gen_caps: List[float] = []
    for g, bi in enumerate(gen_bus_list):
        fuel, cap_mw, _ = bus_gen[bi]
        pg = cap_mw * load_factor
        GEN[g, GEN_BUS]    = bi + 1
        GEN[g, PG]         = pg
        GEN[g, QG]         = pg * qg_ratio
        GEN[g, QMAX]       = cap_mw * 0.50
        GEN[g, QMIN]       = -cap_mw * 0.25
        GEN[g, VG]         = 1.0
        GEN[g, MBASE]      = baseMVA
        GEN[g, GEN_STATUS] = 1
        GEN[g, PMAX]       = cap_mw
        GEN[g, PMIN]       = 0.0
        gen_fuel.append(fuel)
        gen_caps.append(cap_mw)

    # ── Dynamic data (kept for downstream compatibility) ──────────────────
    MD = np.zeros((14, n_gen))
    for g, fuel in enumerate(gen_fuel):
        params = list(_MD_DEFAULTS.get(_fuel_key(fuel), _MD_THERMAL))
        params[0] = params[0] * max(gen_caps[g], baseMVA) / baseMVA
        MD[:, g] = params
    ED = np.tile(np.array(_ED_DEFAULT, dtype=float), (n_gen, 1)).T
    TD = np.tile(np.array(_TD_DEFAULT, dtype=float), (n_gen, 1)).T

    # ── GENCOST (OPF-ready) ───────────────────────────────────────────────
    GENCOST = build_gencost(GEN, gen_fuel, gen_caps_mw=gen_caps, data_dir=data_dir)

    bus_names = [s.name for s in kept_subs]

    return {
        "BUS":       BUS,
        "BRANCH":    BRANCH,
        "GEN":       GEN,
        "GENCOST":   GENCOST,
        "gencost":   GENCOST,
        "MD":        MD,
        "ED":        ED,
        "TD":        TD,
        "baseMVA":   baseMVA,
        "gen_fuel":  gen_fuel,
        "bus_names": bus_names,
        "n_gen":     n_gen,
        "n_bus":     n_bus,
        "slack_bus": slack_bus_idx + 1,  # 1-indexed
        "gen_buses_1idx": [b + 1 for b in gen_bus_list],
        "compensation": comp_info,
        "diagnostics": diag,
        "region":    getattr(network, "region", ""),
    }


# ---------------------------------------------------------------------------
# MATPOWER .mat writer
# ---------------------------------------------------------------------------

def _pad_branch_matpower(BRANCH: np.ndarray) -> np.ndarray:
    """Pad a compact 9-column branch array to the full 13-column MATPOWER format.

    Full columns: [F_BUS, T_BUS, R, X, B, RATE_A, RATE_B, RATE_C, TAP, SHIFT,
    BR_STATUS, ANGMIN, ANGMAX]. The compact build arrays stop at TAP (col 9);
    MATPOWER / pandapower read SHIFT (9), BR_STATUS (10), ANGMIN/ANGMAX (11/12).
    """
    n, ncol = BRANCH.shape
    if ncol >= 13:
        return BRANCH
    out = np.zeros((n, 13))
    out[:, :ncol] = BRANCH
    # SHIFT=0 (already), BR_STATUS=1 (in service), ANGMIN/ANGMAX = ±360 deg.
    out[:, 10] = 1.0
    out[:, 11] = -360.0
    out[:, 12] = 360.0
    return out


def _pad_gen_matpower(GEN: np.ndarray) -> np.ndarray:
    """Pad a compact 10-column gen array to the full 21-column MATPOWER format.

    Full columns: [GEN_BUS, PG, QG, QMAX, QMIN, VG, MBASE, GEN_STATUS, PMAX,
    PMIN, PC1, PC2, QC1MIN, QC1MAX, QC2MIN, QC2MAX, RAMP_AGC, RAMP_10,
    RAMP_30, RAMP_Q, APF]. Columns past PMIN (10..20) are capability-curve /
    ramp fields left at 0, which MATPOWER treats as unconstrained.
    """
    n, ncol = GEN.shape
    if ncol >= 21:
        return GEN
    out = np.zeros((n, 21))
    out[:, :ncol] = GEN
    return out


def save_case_to_matfile(case: Dict, path: str, version: str = "2") -> str:
    """Save a case dict (from :func:`build_matpower_case`) as a MATPOWER .mat.

    Wraps the arrays into an ``mpc`` struct with the standard MATPOWER fields
    (``version``, ``baseMVA``, ``bus``, ``branch``, ``gen``, ``gencost``) so
    the file can be loaded by MATPOWER (``loadcase``) or by pandapower's
    ``from_mpc()``. Indices are already 1-based in the case arrays.

    Parameters
    ----------
    case : dict
        The case dict with keys 'BUS', 'BRANCH', 'GEN', 'GENCOST', 'baseMVA'.
    path : str
        Output .mat path (parent directories are created if needed).
    version : str
        MATPOWER case-format version string (default '2').

    Returns
    -------
    str
        The path written.
    """
    from scipy.io import savemat

    BUS = np.asarray(case["BUS"], dtype=float)
    BRANCH = np.asarray(case["BRANCH"], dtype=float)
    GEN = np.asarray(case["GEN"], dtype=float)
    GENCOST = case.get("GENCOST", case.get("gencost"))
    if GENCOST is None:
        GENCOST = build_gencost(GEN, case.get("gen_fuel", []))
    GENCOST = np.asarray(GENCOST, dtype=float)

    # Pad to the full MATPOWER column widths so the .mat is standards-
    # compliant and loadable by MATPOWER (loadcase) / pandapower (from_mpc),
    # both of which index columns the compact build arrays omit.
    BRANCH = _pad_branch_matpower(BRANCH)
    GEN = _pad_gen_matpower(GEN)

    mpc = {
        "version": version,
        "baseMVA": float(case.get("baseMVA", 100.0)),
        "bus": BUS,
        "branch": BRANCH,
        "gen": GEN,
        "gencost": GENCOST,
    }

    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    # Wrap in an 'mpc' struct (MATPOWER convention). do_compression keeps
    # large national cases small.
    savemat(path, {"mpc": mpc}, do_compression=True)
    return path
