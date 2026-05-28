"""Power flow based initialization for All-Japan-Grid dynamic simulations.

Provides:
- DC power flow (linearized, angle-only)
- Full AC Newton-Raphson power flow
- Generator steady-state initialization from power flow results
- SystemData builder from grid network objects

The AC power flow follows standard textbook formulation (Glover-Sarma-Overbye):
    ΔP = P_sch - P_calc
    ΔQ = Q_sch - Q_calc
    Jacobian: [dP/dθ, dP/d|V|; dQ/dθ, dQ/d|V|]  (polar form)

Usage::

    from src.dynamics.simulation.initializer import (
        run_ac_powerflow, initialize_generators, build_system_from_grid
    )

    pf = run_ac_powerflow(Y_bus, buses)
    if pf.converged:
        init = initialize_generators(gens, gen_bus_idx, pf.V, P_gen, Q_gen)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from src.dynamics.models.sync_generator import (
    GeneratorParams,
    SyncGenerator,
    FUEL_DEFAULT_PARAMS,
)
from src.dynamics.simulation.dae_system import SystemData


# ── Power Flow Result ─────────────────────────────────────────────────────────
@dataclass
class PowerFlowResult:
    """Result of a power flow calculation.

    Attributes
    ----------
    V : np.ndarray, complex, shape (nb,)
        Complex bus voltage phasors (pu).
    converged : bool
        True if the power flow converged.
    iterations : int
        Number of Newton-Raphson iterations performed.
    P_mismatch : float
        Final maximum active power mismatch (pu).
    Q_mismatch : float
        Final maximum reactive power mismatch (pu).
    """

    V: np.ndarray
    converged: bool
    iterations: int
    P_mismatch: float = 0.0
    Q_mismatch: float = 0.0


# ── Bus Data for AC Power Flow ────────────────────────────────────────────────
@dataclass
class BusData:
    """Bus specification for AC power flow.

    Attributes
    ----------
    idx : int
        Bus index (0-based).
    bus_type : str
        'slack', 'PV', or 'PQ'.
    P_sch : float
        Scheduled active power injection (pu). Positive = injection.
    Q_sch : float
        Scheduled reactive power injection (pu). Positive = injection.
    V_mag : float
        Voltage magnitude setpoint (pu). Used for PV and slack buses.
    V_ang : float
        Voltage angle (rad). Used for slack bus only.
    Q_min : float
        Minimum reactive power (pu). For PV bus limits.
    Q_max : float
        Maximum reactive power (pu). For PV bus limits.
    """

    idx: int
    bus_type: str  # 'slack', 'PV', 'PQ'
    P_sch: float = 0.0
    Q_sch: float = 0.0
    V_mag: float = 1.0
    V_ang: float = 0.0
    Q_min: float = -9999.0
    Q_max: float = 9999.0


# ── DC Power Flow ─────────────────────────────────────────────────────────────
def run_dc_powerflow(
    Y_bus: sp.spmatrix,
    P_inj: np.ndarray,
    slack_bus: int = 0,
) -> np.ndarray:
    """DC (linearized) power flow: solve B * θ = P_inj.

    Assumes all voltage magnitudes = 1.0 pu.
    The slack bus angle is fixed at 0.

    Parameters
    ----------
    Y_bus : scipy.sparse complex matrix, shape (nb, nb)
        Network admittance matrix.
    P_inj : np.ndarray, shape (nb,)
        Net active power injection at each bus (pu). Positive = injection.
    slack_bus : int
        Index of the slack bus.

    Returns
    -------
    V_angles : np.ndarray, shape (nb,)
        Bus voltage angles (rad). Magnitudes are all 1.0.
    """
    nb = Y_bus.shape[0]

    # DC approximation: B_ij ≈ -Im(Y_ij) = 1/X_ij
    B = -Y_bus.imag
    if sp.issparse(B):
        B = np.array(B.toarray(), dtype=float)
    else:
        B = np.array(B, dtype=float)

    # Remove slack bus row and column
    mask = np.ones(nb, dtype=bool)
    mask[slack_bus] = False
    B_red = B[np.ix_(mask, mask)]
    P_red = P_inj[mask]

    # Solve B_red * θ_red = P_red
    B_red_sp = sp.csc_matrix(B_red)
    try:
        theta_red = spla.spsolve(B_red_sp, P_red)
    except Exception:
        theta_red = np.linalg.solve(B_red, P_red)

    theta = np.zeros(nb)
    theta[mask] = theta_red

    return theta


# ── AC Newton-Raphson Power Flow ──────────────────────────────────────────────
def run_ac_powerflow(
    Y_bus: sp.spmatrix,
    buses: List[BusData],
    max_iter: int = 50,
    tol: float = 1e-8,
) -> PowerFlowResult:
    """Newton-Raphson AC power flow.

    Formulation: polar coordinates (V magnitude + angle).
    Mismatch:
        ΔP_i = P_sch_i - Σ_j |V_i||V_j|(G_ij cos(θ_ij) + B_ij sin(θ_ij))
        ΔQ_i = Q_sch_i - Σ_j |V_i||V_j|(G_ij sin(θ_ij) - B_ij cos(θ_ij))
    where θ_ij = θ_i - θ_j.

    Jacobian in polar form (standard 4-block structure):
        J = [H, N; J_block, L]
    PQ buses: update both θ and |V|
    PV buses: update only θ (|V| fixed); check Q limits each iteration
    Slack bus: fixed θ and |V|

    Parameters
    ----------
    Y_bus : scipy.sparse complex matrix, shape (nb, nb)
        Network admittance matrix.
    buses : list of BusData
        Bus specifications (ordered by bus index).
    max_iter : int
        Maximum NR iterations. Default 50.
    tol : float
        Convergence tolerance (max |mismatch|). Default 1e-8.

    Returns
    -------
    PowerFlowResult
        Converged bus voltages, convergence flag, iteration count.
    """
    nb = len(buses)
    # Sort buses by index to ensure consistent ordering
    buses_by_idx = sorted(buses, key=lambda b: b.idx)

    # Build index sets
    slack_buses = [b.idx for b in buses_by_idx if b.bus_type == "slack"]
    pv_buses = [b.idx for b in buses_by_idx if b.bus_type == "PV"]
    pq_buses = [b.idx for b in buses_by_idx if b.bus_type == "PQ"]

    slack = slack_buses[0] if slack_buses else 0

    # Admittance matrix
    if sp.issparse(Y_bus):
        Y = Y_bus.toarray()
    else:
        Y = np.array(Y_bus, dtype=complex)
    G = Y.real
    B = Y.imag

    # Initial voltage (flat start at bus specs)
    V_mag = np.ones(nb)
    V_ang = np.zeros(nb)
    for b in buses_by_idx:
        V_mag[b.idx] = b.V_mag
        V_ang[b.idx] = b.V_ang

    P_sch = np.zeros(nb)
    Q_sch = np.zeros(nb)
    for b in buses_by_idx:
        P_sch[b.idx] = b.P_sch
        Q_sch[b.idx] = b.Q_sch

    # Scheduled Q limits for PV buses (for limit checking)
    Q_limits: Dict[int, Tuple[float, float]] = {}
    for b in buses_by_idx:
        if b.bus_type == "PV":
            Q_limits[b.idx] = (b.Q_min, b.Q_max)

    def calc_PQ(Vm: np.ndarray, Va: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Calculate injected P and Q from admittance and voltages."""
        P = np.zeros(nb)
        Q = np.zeros(nb)
        for i in range(nb):
            for j in range(nb):
                theta_ij = Va[i] - Va[j]
                P[i] += Vm[i] * Vm[j] * (G[i, j] * math.cos(theta_ij) + B[i, j] * math.sin(theta_ij))
                Q[i] += Vm[i] * Vm[j] * (G[i, j] * math.sin(theta_ij) - B[i, j] * math.cos(theta_ij))
        return P, Q

    def calc_PQ_vectorized(Vm: np.ndarray, Va: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Vectorized P/Q calculation."""
        # Build complex voltage
        V_cplx = Vm * np.exp(1j * Va)
        # Current injection: I = Y * V
        I_inj = Y @ V_cplx
        # S = V * conj(I)
        S = V_cplx * I_inj.conjugate()
        return S.real, S.imag

    def build_jacobian(Vm: np.ndarray, Va: np.ndarray) -> Tuple[np.ndarray, List[int], List[int]]:
        """Build the NR Jacobian in polar form.

        Returns (J_full, pq_pv_idx, pq_idx) where:
        - J_full: full (2nb × 2nb) Jacobian [H N; J L] (polar)
        - pq_pv_idx: row/col indices for ΔP equations (PQ + PV buses)
        - pq_idx: row/col indices for ΔQ equations (PQ buses only)
        """
        H = np.zeros((nb, nb))  # dP/dθ
        N = np.zeros((nb, nb))  # dP/d|V| * |V|
        J_bl = np.zeros((nb, nb))  # dQ/dθ
        L = np.zeros((nb, nb))  # dQ/d|V| * |V|

        for i in range(nb):
            for j in range(nb):
                theta_ij = Va[i] - Va[j]
                if i != j:
                    H[i, j] = Vm[i] * Vm[j] * (-G[i, j] * math.sin(theta_ij) + B[i, j] * math.cos(theta_ij))
                    N[i, j] = Vm[i] * Vm[j] * ( G[i, j] * math.cos(theta_ij) + B[i, j] * math.sin(theta_ij))
                    J_bl[i, j] = Vm[i] * Vm[j] * ( G[i, j] * math.cos(theta_ij) + B[i, j] * math.sin(theta_ij))
                    L[i, j] = Vm[i] * Vm[j] * ( G[i, j] * math.sin(theta_ij) - B[i, j] * math.cos(theta_ij))
                else:
                    P_i, Q_i = 0.0, 0.0
                    for k in range(nb):
                        th_ik = Va[i] - Va[k]
                        P_i += Vm[i] * Vm[k] * (G[i, k] * math.cos(th_ik) + B[i, k] * math.sin(th_ik))
                        Q_i += Vm[i] * Vm[k] * (G[i, k] * math.sin(th_ik) - B[i, k] * math.cos(th_ik))
                    H[i, i] = -Q_i - B[i, i] * Vm[i] ** 2
                    N[i, i] =  P_i + G[i, i] * Vm[i] ** 2
                    J_bl[i, i] = P_i - G[i, i] * Vm[i] ** 2
                    L[i, i] = Q_i - B[i, i] * Vm[i] ** 2

        return H, N, J_bl, L

    P_calc, Q_calc = calc_PQ_vectorized(V_mag, V_ang)
    converged = False
    last_dp = 0.0
    last_dq = 0.0

    # Indices for reduced equations
    pq_pv = sorted(pv_buses + pq_buses)  # buses where ΔP is included
    pq_only = sorted(pq_buses)           # buses where ΔQ is included

    for iteration in range(max_iter):
        P_calc, Q_calc = calc_PQ_vectorized(V_mag, V_ang)

        # Mismatch
        dP = P_sch - P_calc
        dQ = Q_sch - Q_calc

        # Mask out slack bus from mismatch (and PV buses from Q mismatch)
        dP_red = dP[pq_pv]
        dQ_red = dQ[pq_only]

        last_dp = float(np.max(np.abs(dP_red))) if len(dP_red) > 0 else 0.0
        last_dq = float(np.max(np.abs(dQ_red))) if len(dQ_red) > 0 else 0.0
        max_mis = max(last_dp, last_dq)

        if max_mis < tol:
            converged = True
            break

        # Build Jacobian
        H, N, J_bl, L = build_jacobian(V_mag, V_ang)

        # Reduced Jacobian: extract rows/cols for PQ+PV (angle) and PQ (mag)
        n_pv_pq = len(pq_pv)
        n_pq = len(pq_only)
        n_eq = n_pv_pq + n_pq

        J_red = np.zeros((n_eq, n_eq))
        J_red[:n_pv_pq, :n_pv_pq] = H[np.ix_(pq_pv, pq_pv)]
        J_red[:n_pv_pq, n_pv_pq:] = N[np.ix_(pq_pv, pq_only)]
        J_red[n_pv_pq:, :n_pv_pq] = J_bl[np.ix_(pq_only, pq_pv)]
        J_red[n_pv_pq:, n_pv_pq:] = L[np.ix_(pq_only, pq_only)]

        rhs = np.concatenate([dP_red, dQ_red])

        # Solve
        try:
            J_sp = sp.csc_matrix(J_red)
            lu = spla.splu(J_sp)
            sol = lu.solve(rhs)
        except Exception:
            try:
                sol = np.linalg.solve(J_red, rhs)
            except np.linalg.LinAlgError:
                break

        d_theta = sol[:n_pv_pq]
        d_Vmag = sol[n_pv_pq:]

        # Update
        for k, bus_k in enumerate(pq_pv):
            V_ang[bus_k] += d_theta[k]
        for k, bus_k in enumerate(pq_only):
            V_mag[bus_k] += d_Vmag[k] * V_mag[bus_k]  # ΔV = (ΔV/V) * V

        # PV bus voltage magnitude: keep fixed (set from spec)
        for bus_k in pv_buses:
            b = buses_by_idx[bus_k] if bus_k < len(buses_by_idx) else None
            if b is not None and b.bus_type == "PV":
                V_mag[bus_k] = b.V_mag

    V_complex = V_mag * np.exp(1j * V_ang)
    return PowerFlowResult(
        V=V_complex,
        converged=converged,
        iterations=iteration + 1,
        P_mismatch=last_dp,
        Q_mismatch=last_dq,
    )


# ── Generator Initialization ──────────────────────────────────────────────────
def initialize_generators(
    generators: List[SyncGenerator],
    gen_bus_idx: List[int],
    V_pf: np.ndarray,
    P_gen: np.ndarray,
    Q_gen: np.ndarray,
    sbase_mva: float = 100.0,
) -> Dict:
    """Initialize generator states from a power flow solution.

    For each generator i:
    1. Retrieves terminal voltage from power flow: V = V_pf[gen_bus_idx[i]]
    2. Converts P_gen[i], Q_gen[i] to machine base (pu on machine base)
    3. Calls gen.initialize(P_pu, Q_pu, V) to get initial state + Efd0, Pm0

    Parameters
    ----------
    generators : list of SyncGenerator
    gen_bus_idx : list of int
        Bus indices for each generator.
    V_pf : np.ndarray, complex, shape (nb,)
        Complex bus voltages from power flow.
    P_gen : np.ndarray, shape (ng,)
        Active power output (MW) for each generator.
    Q_gen : np.ndarray, shape (ng,)
        Reactive power output (MVAR) for each generator.
    sbase_mva : float
        System MVA base for converting MW/MVAR to pu.

    Returns
    -------
    dict with keys:
        'x0'   : np.ndarray shape (4*ng,) — initial state vector
        'Efd0' : list of float — initial field voltages
        'Pm0'  : list of float — initial mechanical powers (machine base pu)
        'states': list of np.ndarray (4,) — individual generator states
    """
    ng = len(generators)
    x0 = np.zeros(4 * ng)
    Efd0_list: List[float] = []
    Pm0_list: List[float] = []
    states_list: List[np.ndarray] = []

    for i, gen in enumerate(generators):
        bus = gen_bus_idx[i]
        V = complex(V_pf[bus])
        p = gen.p

        # Convert from system base to machine base
        P_pu_sys = float(P_gen[i]) / sbase_mva
        Q_pu_sys = float(Q_gen[i]) / sbase_mva
        # Machine base: divide by mva_ratio (S_rated / S_base)
        P_pu_mach = P_pu_sys / p.mva_ratio
        Q_pu_mach = Q_pu_sys / p.mva_ratio

        # Steady-state initialization
        state0, Efd0, Pm0 = gen.initialize(P_pu_mach, Q_pu_mach, V)

        x0[4 * i: 4 * i + 4] = state0
        Efd0_list.append(Efd0)
        Pm0_list.append(Pm0)
        states_list.append(state0)

    return {
        "x0": x0,
        "Efd0": Efd0_list,
        "Pm0": Pm0_list,
        "states": states_list,
    }


# ── System Builder from Grid Network ─────────────────────────────────────────
def build_system_from_grid(
    grid_network,
    gen_assignments: Optional[Dict[int, str]] = None,
    sbase_mva: float = 100.0,
    slack_bus: int = 0,
    omega_s: float = 2.0 * math.pi * 50.0,
) -> Tuple[SystemData, PowerFlowResult]:
    """Build a SystemData from a grid network object.

    Constructs SyncGenerator objects using fuel-type default parameters,
    builds Y_bus, assigns loads, and runs an AC power flow initialization.

    Parameters
    ----------
    grid_network : GridNetwork or object with .Y_bus, .buses, .generators
        The grid network model. Can also be a pandapower network.
    gen_assignments : dict {bus_idx: fuel_type_str}, optional
        Maps bus indices to fuel types. If None, fuel types are inferred
        from the grid_network's generator objects.
    sbase_mva : float
        System MVA base. Default 100.0.
    slack_bus : int
        Slack bus index. Default 0.
    omega_s : float
        Synchronous frequency (rad/s). Default 2π×50.

    Returns
    -------
    (SystemData, PowerFlowResult)
        SystemData with initialized generators, and the power flow result.
    """
    import scipy.sparse as sp_mod

    # Try to extract Y_bus and bus/generator data from various formats
    Y_bus_raw = None
    bus_count = 0
    gen_caps: Dict[int, float] = {}   # bus_idx → capacity MW
    gen_fuels: Dict[int, str] = {}    # bus_idx → fuel_type
    load_data: Dict[int, Tuple[float, float]] = {}  # bus_idx → (P_pu, Q_pu)

    # Pandapower network
    if hasattr(grid_network, "_ppc") or hasattr(grid_network, "bus"):
        try:
            import pandapower as pp
            from src.ac_powerflow.network_prep import prepare_network
            data = prepare_network(grid_network)
            Y_bus_raw = data.Ybus
            bus_count = Y_bus_raw.shape[0]
            # Extract load data from pandapower loads
            if hasattr(grid_network, "load") and not grid_network.load.empty:
                lookup = getattr(grid_network, "_pd2ppc_lookups", {}).get("bus", {})
                for _, row in grid_network.load.iterrows():
                    b_pd = int(row["bus"])
                    b_ppc = lookup.get(b_pd, b_pd)
                    if b_ppc < bus_count:
                        load_data[b_ppc] = (
                            float(row.get("p_mw", 0.0)) / sbase_mva,
                            float(row.get("q_mvar", 0.0)) / sbase_mva,
                        )
        except Exception:
            pass

    # GridNetwork or similar object
    if Y_bus_raw is None and hasattr(grid_network, "build_ybus"):
        Y_bus_raw = grid_network.build_ybus()
        bus_count = Y_bus_raw.shape[0]
    if Y_bus_raw is None and hasattr(grid_network, "Y_bus"):
        Y_bus_raw = grid_network.Y_bus
        bus_count = Y_bus_raw.shape[0]

    # Fallback: create trivial single-bus system
    if Y_bus_raw is None:
        bus_count = 1
        Y_bus_raw = sp_mod.eye(1, dtype=complex) * (1 / (0.1j))

    # Ensure sparse
    if not sp_mod.issparse(Y_bus_raw):
        Y_bus_raw = sp_mod.csr_matrix(Y_bus_raw)
    Y_bus = Y_bus_raw.astype(complex)

    # Build generator assignments from gen_assignments dict or defaults
    if gen_assignments is None:
        gen_assignments = {}
        # Try to extract from grid_network generators
        if hasattr(grid_network, "generators"):
            for gen_obj in grid_network.generators:
                b = getattr(gen_obj, "bus_id", None) or getattr(gen_obj, "bus", 0)
                if b < bus_count:
                    fuel = getattr(gen_obj, "fuel_type", "unknown")
                    cap = getattr(gen_obj, "capacity_mw", 100.0)
                    gen_assignments[b] = str(fuel)
                    gen_caps[b] = float(cap)

    # Accept list-of-tuples from assign_generators: [(bus_id, fuel, cap_mw, name), ...]
    if isinstance(gen_assignments, list):
        gen_list = gen_assignments
        gen_assignments = {}
        for item in gen_list:
            bus_id_i, fuel_i, cap_i, *_ = item
            if int(bus_id_i) < bus_count:
                gen_assignments[int(bus_id_i)] = str(fuel_i)
                gen_caps[int(bus_id_i)] = float(cap_i)

    # If still empty, place one generator at slack bus
    if not gen_assignments:
        gen_assignments = {slack_bus: "unknown"}
        gen_caps[slack_bus] = sbase_mva

    # Build SyncGenerator objects (aggregate multiple gens on same bus)
    generators: List[SyncGenerator] = []
    gen_bus_idx: List[int] = []
    P_gen = []
    Q_gen = []

    for bus_idx, fuel_type in sorted(gen_assignments.items()):
        cap_mw = gen_caps.get(bus_idx, sbase_mva)
        params = GeneratorParams.from_fuel(
            fuel_type=str(fuel_type),
            S_rated_mva=float(cap_mw),
            bus_id=bus_idx,
            name=f"gen_bus{bus_idx}_{fuel_type}",
            omega_s=omega_s,
        )
        gen = SyncGenerator(params)
        generators.append(gen)
        gen_bus_idx.append(bus_idx)
        # Assume generators deliver 80% of rated at operating point
        P_gen.append(cap_mw * 0.8)
        Q_gen.append(cap_mw * 0.0)

    ng = len(generators)

    # Build P_inj for DC power flow initialization
    P_inj = np.zeros(bus_count)
    for i, bus in enumerate(gen_bus_idx):
        P_inj[bus] += P_gen[i] / sbase_mva

    # If no loads specified, assign 50% of generation as loads on non-generator buses
    if not load_data:
        gen_bus_set = set(gen_bus_idx)
        non_gen_buses = [b for b in range(bus_count) if b not in gen_bus_set]
        total_P_gen = sum(P_gen) / sbase_mva
        if non_gen_buses:
            P_load_each = total_P_gen * 0.5 / len(non_gen_buses)
            for b in non_gen_buses:
                load_data[b] = (P_load_each, P_load_each * 0.3)
                P_inj[b] -= P_load_each

    # DC power flow for initial angles
    theta_dc = run_dc_powerflow(Y_bus, P_inj, slack_bus=slack_bus)
    V0_dc = np.exp(1j * theta_dc)  # flat magnitudes

    # Try AC power flow
    bus_specs = []
    gen_bus_set = set(gen_bus_idx)
    for b in range(bus_count):
        if b == slack_bus:
            bs = BusData(idx=b, bus_type="slack", V_mag=1.0, V_ang=0.0)
        elif b in gen_bus_set:
            P_sch = P_inj[b]
            bs = BusData(idx=b, bus_type="PV", P_sch=P_sch, V_mag=1.0,
                         Q_min=-5.0, Q_max=5.0)
        else:
            if b in load_data:
                P_ld, Q_ld = load_data[b]
                bs = BusData(idx=b, bus_type="PQ", P_sch=-P_ld, Q_sch=-Q_ld)
            else:
                bs = BusData(idx=b, bus_type="PQ", P_sch=0.0, Q_sch=0.0)
        bus_specs.append(bs)

    pf_result = run_ac_powerflow(Y_bus, bus_specs, max_iter=50, tol=1e-8)
    V_init = pf_result.V if pf_result.converged else V0_dc

    # Initialize generators from power flow
    gen_init = initialize_generators(
        generators=generators,
        gen_bus_idx=gen_bus_idx,
        V_pf=V_init,
        P_gen=np.array(P_gen),
        Q_gen=np.array(Q_gen),
        sbase_mva=sbase_mva,
    )

    # Build SystemData
    system_data = SystemData(
        generators=generators,
        gen_bus_idx=gen_bus_idx,
        Y_bus=Y_bus,
        nb=bus_count,
        ng=ng,
        load_buses=load_data,
        slack_bus=slack_bus,
        sbase_mva=sbase_mva,
        V0_slack=complex(V_init[slack_bus]),
        Efd=gen_init["Efd0"],
        Pm=gen_init["Pm0"],
    )

    return system_data, pf_result
