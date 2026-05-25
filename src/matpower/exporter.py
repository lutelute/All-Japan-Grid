"""MATPOWER-format exporter for All-Japan-Grid.

Converts the All-Japan-Grid GeoJSON network (substations + transmission lines)
into MATPOWER-compatible numpy arrays that can be consumed by psdat-python or
any MATPOWER-compatible power flow solver.

Output arrays (MATPOWER column conventions):
    BUS    (n_bus × 13)   — bus data
    BRANCH (n_branch × 9) — branch data
    GEN    (n_gen × 10)   — generator data
    MD     (14 × n_gen)   — dynamic machine parameters
    ED     (8 × n_gen)    — dynamic exciter parameters
    TD     (3 × n_gen)    — dynamic turbine/governor parameters

Usage::

    from src.matpower.exporter import build_matpower_case

    case = build_matpower_case(voltage_levels=[500, 275, 154, 77, 66])
    BUS, BRANCH, GEN = case['BUS'], case['BRANCH'], case['GEN']
    baseMVA = case['baseMVA']
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

# BUS types
PQ_BUS   = 1
PV_BUS   = 2
REF_BUS  = 3

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
    load_factor: float = 0.60,
    qg_ratio: float = 0.30,
    shunt_compensation: Optional[str] = None,
    compensation_alpha: float = 0.9,
    compensation_v_threshold: float = 0.05,
) -> Dict:
    """Build a MATPOWER-format case from the All-Japan-Grid GeoJSON data.

    Parameters
    ----------
    voltage_levels : list of int, optional
        Voltage levels [kV] to include. Default: [500, 275, 154, 77, 66].
    data_dir : str
        Path to the data directory containing GeoJSON files.
    baseMVA : float
        System MVA base.
    load_factor : float
        Generator output as fraction of capacity (used for PG initial guess).
    qg_ratio : float
        QG / PG ratio for initial reactive power dispatch.

    Returns
    -------
    dict with keys:
        'BUS'    — ndarray (n_bus, 13)
        'BRANCH' — ndarray (n_branch, 9)
        'GEN'    — ndarray (n_gen, 10)
        'MD'     — ndarray (14, n_gen)  machine dynamic data
        'ED'     — ndarray (8, n_gen)   exciter dynamic data
        'TD'     — ndarray (3, n_gen)   turbine dynamic data
        'baseMVA' — float
        'gen_fuel' — list of str, fuel type per generator
        'bus_names' — list of str
    """
    if voltage_levels is None:
        voltage_levels = [500, 275, 154, 77, 66]

    # ── 1. Build network (with disk cache for slow multi-kV builds) ───────
    cache_dir = os.path.join(data_dir, "..", "data", "cache") if os.path.isdir(data_dir) else None
    net = GridNetwork.from_geojson(
        data_dir, voltage_levels=voltage_levels, cache_dir=cache_dir
    )
    lcc = net.largest_connected_component()
    # Filter out radial chains far from the HV backbone.
    # 77 kV buses > 2 hops from 154 kV, or 66 kV buses > 2 hops from 110 kV,
    # create ill-conditioned Jacobians due to very high X/R ratios.
    if any(v <= 66 for v in (voltage_levels or [500, 275])):
        lcc = lcc.filter_by_hv_distance(hv_threshold_kv=110.0, max_hops=2)
        lcc = lcc.largest_connected_component()
    elif any(v <= 77 for v in (voltage_levels or [500, 275])):
        lcc = lcc.filter_by_hv_distance(hv_threshold_kv=154.0, max_hops=2)
        # Re-extract LCC: hop filter may disconnect sub-clusters that were
        # bridged through removed 77 kV buses, leaving isolated islands.
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

    # Load distribution: V_kv² weighting across all non-generator PQ buses.
    # Including 500 kV PQ buses in the weighting distributes load more evenly and
    # avoids overloading weak radial 154 kV buses at the network periphery.
    # The large V_kv² weight on 500 kV buses acts as a virtual load at strongly
    # coupled (X=0.006 pu) transformer nodes — physically they represent the
    # equivalent downstream load seen from the 500 kV backbone.
    LOAD_MIN_KV = 66 if any(v <= 66 for v in voltage_levels) else 77
    all_weights: Dict[int, float] = {}
    for i in range(n_bus):
        if i in bus_gen:
            continue   # gen buses have PD=0; PG handles their injection
        kv = lcc.buses[i].base_kv
        if kv < LOAD_MIN_KV:
            continue
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
        BRANCH[k, RATE_A] = ln.rating_mva
        BRANCH[k, RATE_B] = ln.rating_mva
        BRANCH[k, RATE_C] = ln.rating_mva
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

    return {
        "BUS":       BUS,
        "BRANCH":    BRANCH,
        "GEN":       GEN,
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
