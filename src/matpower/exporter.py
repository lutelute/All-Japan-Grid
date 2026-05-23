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

    case = build_matpower_case(voltage_levels=[500, 275])
    BUS, BRANCH, GEN = case['BUS'], case['BRANCH'], case['GEN']
    baseMVA = case['baseMVA']
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np

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


def build_matpower_case(
    voltage_levels: List[int] = None,
    data_dir: str = "data",
    baseMVA: float = 100.0,
    load_factor: float = 0.60,
    qg_ratio: float = 0.30,
) -> Dict:
    """Build a MATPOWER-format case from the All-Japan-Grid GeoJSON data.

    Parameters
    ----------
    voltage_levels : list of int, optional
        Voltage levels [kV] to include. Default: [500, 275].
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
        voltage_levels = [500, 275]

    # ── 1. Build network ─────────────────────────────────────────────────
    net = GridNetwork.from_geojson(data_dir, voltage_levels=voltage_levels)
    lcc = net.largest_connected_component()
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

    # Slack bus: generator bus with largest capacity
    slack_bus_idx = max(bus_gen.keys(), key=lambda b: bus_gen[b][1])

    # Total generation → total load (power balance at load_factor)
    total_gen_mw = sum(bus_gen[b][1] * load_factor for b in gen_bus_list)
    pq_bus_count = n_bus - n_gen   # non-generator buses carry loads
    if pq_bus_count < 1:
        pq_bus_count = 1
    load_per_pq_bus_mw = total_gen_mw / pq_bus_count   # MW per PQ bus

    # ── 3. BUS array (n_bus × 13) ────────────────────────────────────────
    BUS = np.zeros((n_bus, 13))
    for i, b in enumerate(lcc.buses):
        bus_1idx = i + 1
        is_gen_bus = i in bus_gen
        if i == slack_bus_idx:
            btype = REF_BUS
        elif is_gen_bus:
            btype = PV_BUS
        else:
            btype = PQ_BUS

        # Distribute load evenly across PQ buses for power balance
        pd_mw = 0.0 if is_gen_bus else load_per_pq_bus_mw
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

    # ── 5. GEN array (n_gen × 10) ────────────────────────────────────────
    GEN = np.zeros((n_gen, 10))
    gen_fuel: List[str] = []
    for g, bus_idx in enumerate(gen_bus_list):
        fuel, cap_mw, _ = bus_gen[bus_idx]
        pg = cap_mw * load_factor   # MW
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
    }
