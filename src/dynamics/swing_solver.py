"""Transient stability and modal analysis for All-Japan-Grid.

Classical machine model:
    (2H_i / omega_s) d²δ_i/dt² = Pm_i - Pe_i(δ) - D_i dδ_i/dt

    Pe_i = Σ_j E_i E_j [ G_ij cos(δ_i-δ_j) + B_ij sin(δ_i-δ_j) ]

Modal analysis via linearisation around operating point:
    ẋ = A x,  x = [Δδ, Δω]ᵀ

    A = [  0        I    ]
        [ -M⁻¹K  -M⁻¹D  ]

    K_ij = ∂Pe_i/∂δ_j  (synchronising torque matrix)

Usage::

    from src.dynamics.swing_solver import SwingModel, run_transient, modal_analysis

    model = SwingModel.from_pandapower(net, baseMVA=100)

    # N-1 trip of largest generator at t=1s
    result = run_transient(model, t_end=10.0, fault='trip', fault_bus=0, t_fault=1.0)

    # Modal analysis
    modes = modal_analysis(model)
"""

from __future__ import annotations

import dataclasses
import warnings
from typing import List, Optional, Tuple

import numpy as np
from scipy import linalg, sparse
from scipy.integrate import solve_ivp


# ── Constants ────────────────────────────────────────────────────────────────
_OMEGA_50 = 2 * np.pi * 50   # rad/s  (east Japan)
_OMEGA_60 = 2 * np.pi * 60   # rad/s  (west Japan)


# ── Data classes ─────────────────────────────────────────────────────────────
@dataclasses.dataclass
class GenDyn:
    """Dynamic parameters of a single synchronous generator (classical model)."""
    bus: int          # Ybus row/col index
    H: float          # Inertia constant  (s)
    D: float          # Damping coefficient (pu)
    E: float          # Internal voltage magnitude (pu)
    delta0: float     # Initial rotor angle (rad)
    Pm: float         # Mechanical power input (pu on baseMVA)
    name: str = ""


@dataclasses.dataclass
class TransientResult:
    """Time-domain simulation result."""
    t: np.ndarray           # Time vector (s)
    delta: np.ndarray       # Rotor angles  [n_gen × n_t]  (rad)
    omega: np.ndarray       # Speed deviations [n_gen × n_t] (rad/s)
    stable: bool            # True if max |δ_i - δ_j| < π at all times
    coi_delta: np.ndarray   # Centre-of-inertia angle (rad)
    max_angle_sep: float    # Peak rotor angle separation (rad)
    fault_type: str


@dataclasses.dataclass
class ModeResult:
    """Single oscillation mode from modal analysis."""
    eigenvalue: complex     # λ = σ ± jω_d
    freq_hz: float          # Oscillation frequency (Hz)
    damping_ratio: float    # ζ = -σ / |λ|
    participants: List[int] # Top generator bus indices (by participation factor)
    mode_type: str          # 'local', 'inter-area', 'non-oscillatory'


# ── Main model class ─────────────────────────────────────────────────────────
class SwingModel:
    """Classical-model multi-machine swing equation system.

    Parameters
    ----------
    generators : list of GenDyn
    Ybus_red : complex ndarray [n_gen × n_gen]
        Kron-reduced admittance matrix (generator internal buses only).
    omega_s : float
        Synchronous angular frequency (rad/s).
    baseMVA : float
    """

    def __init__(
        self,
        generators: List[GenDyn],
        Ybus_red: np.ndarray,
        omega_s: float = _OMEGA_50,
        baseMVA: float = 100.0,
    ):
        self.generators = generators
        self.Ybus_red = Ybus_red
        self.omega_s = omega_s
        self.baseMVA = baseMVA
        self.n = len(generators)

    # ── Factory ──────────────────────────────────────────────────────────────
    @classmethod
    def from_pandapower(
        cls,
        net,
        H_default: float = 5.0,
        D_default: float = 2.0,
        freq_hz: float = 50.0,
        baseMVA: float = 100.0,
    ) -> "SwingModel":
        """Build SwingModel from a pandapower network after runpp().

        Uses net.res_bus for initial voltages and net.gen / net.ext_grid
        for generator data. Electrical parameters (H, D) use defaults
        since OSM data does not contain dynamic parameters.
        """
        import pandapower as pp
        from src.ac_powerflow.network_prep import prepare_network

        omega_s = 2 * np.pi * freq_hz

        # Try to get Ybus — multiple fallback levels
        Ybus_full = None
        gen_buses_pp = []

        for init_mode in ("dc", "flat", None):
            try:
                kwargs = {"numba": False, "verbose": False, "max_iteration": 50}
                if init_mode:
                    kwargs["init"] = init_mode
                pp.runpp(net, **kwargs)
            except Exception:
                pass
            # Try to extract Ybus even if runpp failed
            try:
                from src.ac_powerflow.network_prep import prepare_network
                data = prepare_network(net)
                Ybus_full = np.array(data.Ybus.toarray(), dtype=complex)
                gen_buses_pp = sorted(set(list(data.ref) + list(data.pv)))
                break
            except Exception:
                pass

        # Last resort: build Ybus via DC power flow internal matrix
        if Ybus_full is None:
            try:
                pp.rundcpp(net, numba=False, verbose=False)
                ppc = net._ppc
                Y = ppc.get("internal", {}).get("Ybus")
                if Y is not None:
                    from scipy import sparse as _sp
                    if _sp.issparse(Y):
                        Y = Y.toarray()
                    Ybus_full = np.array(Y, dtype=complex)
            except Exception:
                pass

        if Ybus_full is None:
            raise RuntimeError(
                f"Cannot obtain Ybus for region — power flow did not converge "
                f"and DC fallback also failed."
            )

        nb = Ybus_full.shape[0]

        # Collect generator buses from pandapower tables if not from data
        if not gen_buses_pp:
            try:
                lookup = net._pd2ppc_lookups.get("bus", {})
                for bus_pd in net.gen["bus"].tolist() + net.ext_grid["bus"].tolist():
                    if bus_pd in lookup:
                        gen_buses_pp.append(lookup[bus_pd])
            except Exception:
                gen_buses_pp = [0]  # fallback to bus 0

        gen_buses = gen_buses_pp  # use the collected list

        # Try to get V0 from data if available
        V0 = None
        try:
            V0 = data.V0
        except Exception:
            pass

        gens: List[GenDyn] = []
        for bus_pp in gen_buses:
            V_mag = float(np.abs(V0[bus_pp])) if (V0 is not None and bus_pp < len(V0)) else 1.0
            V_ang = float(np.angle(V0[bus_pp])) if (V0 is not None and bus_pp < len(V0)) else 0.0

            # Find matching generator capacity for Pm estimate
            Pm = 1.0  # default 1 pu
            try:
                gen_mask = net.gen["bus"].isin(
                    net._pd2ppc_lookups["bus"][bus_pp:bus_pp+1]
                    if hasattr(net, "_pd2ppc_lookups") else []
                )
                if gen_mask.any():
                    cap = float(net.gen.loc[gen_mask, "p_mw"].sum())
                    Pm = cap / baseMVA
            except Exception:
                pass

            gens.append(GenDyn(
                bus=bus_pp,
                H=H_default,
                D=D_default,
                E=V_mag,
                delta0=V_ang,
                Pm=Pm,
                name=f"gen_bus{bus_pp}",
            ))

        # Kron reduction to generator buses only
        gen_idx = np.array([g.bus for g in gens], dtype=int)
        load_idx = np.array([i for i in range(nb) if i not in gen_idx], dtype=int)
        Ybus_red = _kron_reduce(Ybus_full, gen_idx, load_idx)

        return cls(gens, Ybus_red, omega_s=omega_s, baseMVA=baseMVA)

    # ── Internal helpers ──────────────────────────────────────────────────────
    # 2026-09-02(トラックC③): _Pe/_rhs/_linearise_A をベクトル化。式は従来の二重ループと
    # 同一(tests/test_swing_ac_operating_point.py が 4 機系で一致をゲート)。
    # west 実系統(数百機)の時間応答は Python ループでは実用にならないため。
    def _arrays(self):
        if getattr(self, "_arr_cache", None) is None:
            g = self.generators
            self._arr_cache = {
                "E": np.array([x.E for x in g], float),
                "H": np.array([x.H for x in g], float),
                "D": np.array([x.D for x in g], float),
                "Pm": np.array([x.Pm for x in g], float),
                "Y": np.asarray(self.Ybus_red, dtype=complex),
            }
        return self._arr_cache

    def _Pe(self, delta: np.ndarray, Y: Optional[np.ndarray] = None,
            active: Optional[np.ndarray] = None) -> np.ndarray:
        """Electrical power output for each generator.

        Pe_i = Σ_j E_iE_j [G_ij cos(δ_i−δ_j) + B_ij sin(δ_i−δ_j)]
             = Re( Ê_i · conj(Σ_j Y_ij Ê_j) ),  Ê = E·e^{jδ}
        Y: 使う縮約行列(既定=self.Ybus_red)。active: False の機械は網から外れている
        (解列後)として Ê=0・Pe=0。
        """
        a = self._arrays()
        Y = a["Y"] if Y is None else Y
        Eph = a["E"] * np.exp(1j * np.asarray(delta, float))
        if active is not None:
            Eph = np.where(active, Eph, 0.0)
        return np.real(Eph * np.conj(Y @ Eph))

    def _rhs(self, t: float, y: np.ndarray, trip_idx: Optional[int] = None,
             fault_on: bool = False,
             disconnect_idx: Optional[int] = None) -> np.ndarray:
        """Right-hand side of [dδ/dt, dω/dt].

        trip_idx: 従来どおり「Pm→0・機械は同期網に残る」(後方互換)。
        disconnect_idx: 機械を解列(内部ノードを Kron 消去した網で Pe を計算・
        当該機械の状態は凍結)。
        """
        a = self._arrays()
        n = self.n
        delta = y[:n]
        domega = y[n:]
        Pm = a["Pm"].copy()
        M = 2.0 * a["H"] / self.omega_s
        if disconnect_idx is not None:
            active = np.ones(n, bool)
            active[disconnect_idx] = False
            Pe = self._Pe(delta, Y=self._post_trip_Y(disconnect_idx), active=active)
            ddomega_dt = (Pm - Pe - a["D"] * domega) / M
            ddelta_dt = domega.copy()
            ddomega_dt[disconnect_idx] = 0.0
            ddelta_dt[disconnect_idx] = 0.0
            return np.concatenate([ddelta_dt, ddomega_dt])
        Pe = self._Pe(delta)
        if trip_idx is not None:
            Pm[trip_idx] = 0.0
        ddomega_dt = (Pm - Pe - a["D"] * domega) / M
        return np.concatenate([domega, ddomega_dt])

    def _post_trip_Y(self, idx: int) -> np.ndarray:
        """機械 idx 解列後の縮約行列: 内部ノード idx を Kron 消去した Y_red。

        解列＝内部起電力の除去。内部ノード idx は注入ゼロの浮きノードになるので、
        その Kron 消去が厳密に解列後の等価回路(xd″ 枝は無電流=開放)。
        行列の次元は保つ(消去ノードの行列は 0)ため状態ベクトルの並びは不変。
        """
        cache = getattr(self, "_post_trip_cache", None)
        if cache is None:
            cache = self._post_trip_cache = {}
        if idx not in cache:
            Y = self._arrays()["Y"]
            keep = np.array([i for i in range(self.n) if i != idx], dtype=int)
            Yr = _kron_reduce(Y, keep, np.array([idx], dtype=int))
            Yp = np.zeros_like(Y)
            Yp[np.ix_(keep, keep)] = Yr
            cache[idx] = Yp
        return cache[idx]

    def _linearise_A(self) -> np.ndarray:
        """Build state matrix A for modal analysis (around initial angles)."""
        n = self.n
        a = self._arrays()
        delta0 = np.array([g.delta0 for g in self.generators])
        Y = a["Y"]
        G, B = Y.real, Y.imag
        dij = delta0[:, None] - delta0[None, :]
        EE = a["E"][:, None] * a["E"][None, :]
        # K_ij (i≠j) = E_iE_j (G_ij sin δ_ij − B_ij cos δ_ij);  K_ii = Σ_{k≠i} E_iE_k(−G_ik sin δ_ik + B_ik cos δ_ik)
        K = EE * (G * np.sin(dij) - B * np.cos(dij))
        np.fill_diagonal(K, 0.0)
        np.fill_diagonal(K, -K.sum(axis=1))

        M_inv = np.diag(self.omega_s / (2 * a["H"]))
        D_mat = np.diag(a["D"])

        # A = [0, I; -M⁻¹K, -M⁻¹D]
        A = np.block([
            [np.zeros((n, n)), np.eye(n)],
            [-M_inv @ K,        -M_inv @ D_mat],
        ])
        return A

    # ── Factory from the operating-point classical model ─────────────────────
    @classmethod
    def from_classical(cls, cm: dict, D_override: Optional[np.ndarray] = None) -> "SwingModel":
        """machine_agg.build_classical_model_ac の返り値から組む(2026-09-02)。

        H は系統ベース換算 H_sys = H_mb·S/base(M = 2H_sys/ωs と整合)、
        D も系統ベース(cm["D"])。E∠δ・Pm は運転点の値。
        """
        base = float(cm["base_mva"])
        omega_s = float(cm["omega_s"])
        Dv = cm["D"] if D_override is None else np.asarray(D_override, float)
        gens = []
        for k, s in enumerate(cm["sync"]):
            gens.append(GenDyn(
                bus=k,
                H=float(s["H_mb"] * s["S_mva"] / base),
                D=float(Dv[k]),
                E=float(abs(cm["E"][k])),
                delta0=float(np.angle(cm["E"][k])),
                Pm=float(cm["Pm"][k]),
                name=str(s.get("name") or f"m{k}"),
            ))
        return cls(gens, np.asarray(cm["Y_red"], complex), omega_s=omega_s, baseMVA=base)


# ── Kron reduction ────────────────────────────────────────────────────────────
def _kron_reduce(Y: np.ndarray, retain: np.ndarray, eliminate: np.ndarray) -> np.ndarray:
    """Kron-reduce Ybus to retained buses."""
    Y = np.atleast_2d(Y)
    if Y.ndim != 2:
        raise ValueError(f"Ybus must be 2-D, got shape {Y.shape}")

    retain = np.asarray(retain, dtype=int)
    eliminate = np.asarray(eliminate, dtype=int)

    # Clip indices to valid range
    nb = Y.shape[0]
    retain = retain[retain < nb]
    eliminate = eliminate[eliminate < nb]

    if len(retain) == 0:
        return np.zeros((0, 0), dtype=complex)
    if len(eliminate) == 0:
        return Y[np.ix_(retain, retain)]

    Yrr = Y[np.ix_(retain, retain)]
    Yrl = Y[np.ix_(retain, eliminate)]
    Yll = Y[np.ix_(eliminate, eliminate)]
    Ylr = Y[np.ix_(eliminate, retain)]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        Yll_inv = np.linalg.pinv(Yll)
    return Yrr - Yrl @ Yll_inv @ Ylr


# ── Public API ────────────────────────────────────────────────────────────────
def run_transient(
    model: SwingModel,
    t_end: float = 10.0,
    fault: str = "trip",          # 'trip' | 'fault_clear'
    fault_bus: int = 0,           # generator index to trip / short-circuit bus
    t_fault: float = 1.0,         # fault onset (s)
    t_clear: float = 1.15,        # fault clearing time (s)  [fault_clear only]
    dt: float = 0.01,
) -> TransientResult:
    """Run time-domain transient stability simulation.

    Parameters
    ----------
    fault : 'trip'
        N-1 generator trip at t_fault (legacy: Pm→0, machine stays synchronised).
    fault : 'disconnect'
        N-1 generator disconnection at t_fault (machine removed from the
        network by Kron elimination of its internal node; its states are frozen
        and excluded from the stability check). 2026-09-02.
    fault : 'fault_clear'
        Three-phase fault at fault_bus at t_fault, cleared at t_clear.
    """
    n = model.n
    if n < 2 or (fault == "disconnect" and n < 3):
        raise ValueError(f"run_transient: 機械が少なすぎる (n={n}, fault={fault})")
    y0 = np.concatenate([
        [g.delta0 for g in model.generators],
        np.zeros(n),   # initial Δω = 0
    ])

    t_eval = np.arange(0, t_end + dt, dt)

    if fault == "trip":
        def rhs(t, y):
            trip = fault_bus if t >= t_fault else None
            return model._rhs(t, y, trip_idx=trip)

    elif fault == "disconnect":
        # 解列(2026-09-02): t_fault 以降は機械 fault_bus を網から外す(Kron 消去)。
        # 従来の 'trip'(Pm→0・同期網に残る)は後方互換で残す。
        def rhs(t, y):
            dis = fault_bus if t >= t_fault else None
            return model._rhs(t, y, disconnect_idx=dis)

    elif fault == "fault_clear":
        def rhs(t, y):
            on = t_fault <= t < t_clear
            return model._rhs(t, y, fault_on=on)
    else:
        def rhs(t, y):
            return model._rhs(t, y)

    sol = solve_ivp(
        rhs, [0, t_end], y0,
        method="RK45",
        t_eval=t_eval,
        rtol=1e-6, atol=1e-8,
        dense_output=False,
    )
    if sol.status != 0 or sol.y.shape[1] == 0:
        # 失歩後の急峻な軌道で RK45 が刻み幅下限に当たることがある(2026-09-02 west 実測)。
        # 剛性対応の LSODA へ退避し、それでも駄目なら黙って空を返さず明示的に失敗する
        sol = solve_ivp(rhs, [0, t_end], y0, method="LSODA", t_eval=t_eval,
                        rtol=1e-6, atol=1e-8)
        if sol.status != 0 or sol.y.shape[1] == 0:
            raise RuntimeError(f"run_transient: 積分失敗 ({fault} idx={fault_bus}): {sol.message}")

    delta = sol.y[:n, :]
    omega = sol.y[n:, :]

    # Centre-of-inertia
    total_H = sum(g.H for g in model.generators)
    weights = np.array([g.H for g in model.generators]) / total_H
    coi_delta = weights @ delta

    # Stability check: |δ_i - δ_j| < π  (解列機は除外・COI も残存機で取る)
    keep = np.ones(n, bool)
    if fault == "disconnect":
        keep[fault_bus] = False
        weights = np.array([g.H for g in model.generators], float) * keep
        coi_delta = (weights / weights.sum()) @ delta
    angle_sep = np.max(delta[keep], axis=0) - np.min(delta[keep], axis=0)
    max_sep = float(np.max(angle_sep))
    stable = max_sep < np.pi

    return TransientResult(
        t=sol.t,
        delta=delta,
        omega=omega,
        stable=stable,
        coi_delta=coi_delta,
        max_angle_sep=max_sep,
        fault_type=fault,
    )


def run_nx_contingency(
    model: SwingModel,
    n_out: int = 1,
    t_end: float = 10.0,
    t_fault: float = 1.0,
) -> List[Tuple[List[int], TransientResult]]:
    """Run all N-x contingencies (generator trip combinations).

    Returns list of (tripped_indices, result) sorted by max angle separation.
    """
    from itertools import combinations

    results = []
    indices = list(range(model.n))

    for combo in combinations(indices, n_out):
        # Sequential trip: trip generators one by one at t_fault, t_fault+0.1, ...
        trip_list = list(combo)

        y0 = np.concatenate([
            [g.delta0 for g in model.generators],
            np.zeros(model.n),
        ])

        tripped: set = set()

        def rhs_nx(t, y, _trip_list=trip_list, _tripped=tripped):
            for k, ti in enumerate(_trip_list):
                if t >= t_fault + k * 0.1:
                    _tripped.add(ti)
            for idx in _tripped:
                pass  # modeled via Pm=0

            delta = y[:model.n]; domega = y[model.n:]
            Pe = model._Pe(delta)
            ddelta = domega
            ddw = np.zeros(model.n)
            for i, g in enumerate(model.generators):
                Pm_i = 0.0 if i in _tripped else g.Pm
                Mi = 2.0 * g.H / model.omega_s
                ddw[i] = (Pm_i - Pe[i] - g.D * domega[i]) / Mi
            return np.concatenate([ddelta, ddw])

        t_eval = np.arange(0, t_end + 0.01, 0.01)
        sol = solve_ivp(rhs_nx, [0, t_end], y0, method="RK45",
                        t_eval=t_eval, rtol=1e-5, atol=1e-7)

        delta = sol.y[:model.n]
        omega = sol.y[model.n:]
        sep = float(np.max(np.max(delta, 0) - np.min(delta, 0)))
        stable = sep < np.pi
        total_H = sum(g.H for g in model.generators)
        w = np.array([g.H for g in model.generators]) / total_H

        res = TransientResult(
            t=sol.t, delta=delta, omega=omega,
            stable=stable, coi_delta=w @ delta,
            max_angle_sep=sep,
            fault_type=f"N-{n_out} trip {combo}",
        )
        results.append((trip_list, res))

    results.sort(key=lambda x: -x[1].max_angle_sep)
    return results


def modal_analysis(model: SwingModel) -> List[ModeResult]:
    """Compute oscillation modes via eigenvalue analysis of state matrix A.

    Returns list of ModeResult sorted by oscillation frequency.
    """
    A = model._linearise_A()
    eigenvalues, eigenvectors = linalg.eig(A)

    modes: List[ModeResult] = []
    visited = set()

    for k, lam in enumerate(eigenvalues):
        if k in visited:
            continue
        sigma = lam.real
        omega_d = abs(lam.imag)

        # Find conjugate pair
        conj_idx = None
        for m, lam2 in enumerate(eigenvalues):
            if m != k and abs(lam2 - lam.conjugate()) < 1e-6:
                conj_idx = m
                break

        if conj_idx is not None:
            visited.add(conj_idx)

        freq_hz = omega_d / (2 * np.pi)
        abs_lam = abs(lam)
        zeta = -sigma / abs_lam if abs_lam > 1e-10 else 0.0

        # Mode type classification
        if omega_d < 0.01:
            mtype = "non-oscillatory"
        elif freq_hz < 0.1:
            mtype = "inter-area"
        elif freq_hz < 2.0:
            mtype = "local"
        else:
            mtype = "control"

        # Participation factors (right eigenvector squared)
        pf = np.abs(eigenvectors[:model.n, k])**2
        top = list(np.argsort(pf)[::-1][:3])

        modes.append(ModeResult(
            eigenvalue=lam,
            freq_hz=freq_hz,
            damping_ratio=zeta,
            participants=[model.generators[i].bus for i in top],
            mode_type=mtype,
        ))
        visited.add(k)

    modes.sort(key=lambda m: m.freq_hz)
    return modes
