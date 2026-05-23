"""Implicit trapezoidal DAE solver for All-Japan-Grid power system dynamics.

Implements the predictor-corrector trapezoidal method for solving the
differential-algebraic system:
    dx/dt = f(x, V)
    0     = g(x, V)

The trapezoidal rule discretises the ODE part as:
    x_{n+1} = x_n + (h/2) * [f(x_n, V_n) + f(x_{n+1}, V_{n+1})]

The algebraic part is solved via Newton-Raphson at each stage.

Usage::

    from src.dynamics.simulation.dae_system import DAESystem, SystemData
    from src.dynamics.simulation.dae_solver import DAESolver, SolverConfig, FaultEvent

    config = SolverConfig(dt=0.01, t_end=10.0)
    solver = DAESolver(system, config)

    fault = FaultEvent(t_fault=0.1, t_clear=0.2, fault_bus_idx=5)
    result = solver.run(x0, V0, events=[fault])
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from src.dynamics.simulation.dae_system import DAESystem


# ── Configuration ─────────────────────────────────────────────────────────────
@dataclass
class SolverConfig:
    """Configuration parameters for the DAE solver.

    Attributes
    ----------
    dt : float
        Fixed time step (s). Default 0.01 s (half-cycle at 50 Hz).
    t_end : float
        Simulation end time (s). Default 10.0 s.
    max_iter_nr : int
        Maximum Newton-Raphson iterations per algebraic solve. Default 20.
    tol_nr : float
        Newton-Raphson convergence tolerance (L-inf norm). Default 1e-8.
    event_dt : float
        Minimum time resolution for event detection (s). Default 0.01 s.
    max_iter_trap : int
        Maximum corrector iterations for the trapezoidal step. Default 5.
    tol_trap : float
        Trapezoidal corrector convergence tolerance. Default 1e-8.
    store_every : int
        Store solution every N time steps (1 = every step). Default 1.
    verbose : bool
        Print progress every 1 s of simulation time. Default False.
    """

    dt: float = 0.01
    t_end: float = 10.0
    max_iter_nr: int = 20
    tol_nr: float = 1e-8
    event_dt: float = 0.01
    max_iter_trap: int = 5
    tol_trap: float = 1e-8
    store_every: int = 1
    verbose: bool = False


# ── Fault Event ───────────────────────────────────────────────────────────────
@dataclass
class FaultEvent:
    """Three-phase bus fault event descriptor.

    Attributes
    ----------
    t_fault : float
        Time at which the fault is applied (s).
    t_clear : float
        Time at which the fault is cleared (s).
    fault_bus_idx : int
        Bus index of the faulted bus.
    fault_impedance : complex
        Fault impedance (pu). 0+0j = bolted 3-phase fault.
        Use small R or jX for impedance faults.
    """

    t_fault: float
    t_clear: float
    fault_bus_idx: int
    fault_impedance: complex = 0j

    @property
    def is_bolted(self) -> bool:
        """True when the fault impedance is effectively zero."""
        return abs(self.fault_impedance) < 1e-10


# ── Simulation Result ─────────────────────────────────────────────────────────
@dataclass
class SimulationResult:
    """Time-domain simulation output.

    Attributes
    ----------
    t : np.ndarray, shape (nt,)
        Stored time points (s).
    x : np.ndarray, shape (nt, nx)
        Generator state trajectories.
    V : np.ndarray, complex, shape (nt, nb)
        Bus voltage trajectories.
    gen_data : dict
        Per-generator time series. Keys include:
        'delta' (nt, ng), 'omega' (nt, ng), 'Ed_p' (nt, ng), 'Eq_p' (nt, ng),
        'Pe' (nt, ng).
    converged : bool
        True if all Newton-Raphson solves converged.
    nr_fail_count : int
        Number of NR non-convergence events during simulation.
    """

    t: np.ndarray
    x: np.ndarray
    V: np.ndarray
    gen_data: Dict[str, np.ndarray] = field(default_factory=dict)
    converged: bool = True
    nr_fail_count: int = 0

    def delta_deg(self) -> np.ndarray:
        """Rotor angles in degrees, shape (nt, ng)."""
        return np.rad2deg(self.gen_data.get("delta", np.array([])))

    def max_angle_separation_deg(self) -> np.ndarray:
        """Maximum pairwise rotor angle separation at each time, shape (nt,)."""
        delta = self.gen_data.get("delta", None)
        if delta is None or delta.ndim < 2:
            return np.array([])
        return np.rad2deg(np.max(delta, axis=1) - np.min(delta, axis=1))


# ── DAE Solver ────────────────────────────────────────────────────────────────
class DAESolver:
    """Implicit trapezoidal predictor-corrector DAE solver.

    The algorithm:
    1. Predictor: explicit Euler step for x, then NR solve for V.
    2. Corrector: iterate trapezoidal residual R(x_new) = 0 via simple
       fixed-point (or NR-lite) iteration until convergence.
    3. Event handling: fault application/clearance by modifying Y_bus.

    Parameters
    ----------
    system : DAESystem
        The assembled DAE system.
    config : SolverConfig
        Solver parameters.
    """

    def __init__(self, system: DAESystem, config: SolverConfig) -> None:
        self.system = system
        self.config = config
        # Working copy of Y_bus that can be modified for faults
        self._Y_bus_nominal = system.data.Y_bus.copy()
        self._Y_bus_current = system.data.Y_bus.copy()

    # ── Y_bus modification ─────────────────────────────────────────────────
    def _apply_fault_ybus(self, fault: FaultEvent) -> None:
        """Apply a fault by adding a large shunt admittance at the fault bus."""
        bus = fault.fault_bus_idx
        if fault.is_bolted:
            y_shunt = 1e10 + 0j
        else:
            y_shunt = 1.0 / fault.fault_impedance
        # Modify the working Y_bus
        Y = self._Y_bus_current.tolil()
        Y[bus, bus] = Y[bus, bus] + y_shunt
        self._Y_bus_current = Y.tocsr()
        self.system.data.Y_bus = self._Y_bus_current
        # Invalidate dense cache
        self.system._Y_dense = None

    def _clear_fault_ybus(self) -> None:
        """Restore nominal Y_bus after fault clearance."""
        self._Y_bus_current = self._Y_bus_nominal.copy()
        self.system.data.Y_bus = self._Y_bus_current
        nb = self.system.data.nb
        if nb <= 200:
            self.system._Y_dense = np.array(
                self.system.data.Y_bus.toarray(), dtype=complex
            )
        else:
            self.system._Y_dense = None

    # ── NR algebraic solve: g(x, V) = 0 for V ────────────────────────────
    def solve_algebraic(
        self,
        x: np.ndarray,
        V_init: np.ndarray,
    ) -> Tuple[np.ndarray, bool]:
        """Newton-Raphson solve for bus voltages V given generator states x.

        Solves 0 = g(x, V) for V using NR with sparse LU factorization.

        Parameters
        ----------
        x : np.ndarray, shape (nx,)
            Current generator states (held fixed).
        V_init : np.ndarray, complex, shape (nb,)
            Initial guess for bus voltages.

        Returns
        -------
        V : np.ndarray, complex, shape (nb,)
            Converged bus voltages.
        converged : bool
            True if NR converged within max_iter_nr iterations.
        """
        cfg = self.config
        nb = self.system.data.nb
        V = V_init.copy()

        for iteration in range(cfg.max_iter_nr):
            # Evaluate mismatch g(x, V) — real vector length 2*nb
            g_val = self.system.g(x, V)

            norm_g = np.max(np.abs(g_val))
            if norm_g < cfg.tol_nr:
                return V, True

            # Jacobian ∂g/∂V_real — (2*nb × 2*nb)
            J = self.system.jacobian_g_v(x, V)

            # Solve J * ΔV_real = -g_val
            J_sp = sp.csc_matrix(J)
            try:
                lu = spla.splu(J_sp)
                dV_real = lu.solve(-g_val)
            except Exception:
                # Fallback to dense solve if LU fails
                try:
                    dV_real = np.linalg.solve(J, -g_val)
                except np.linalg.LinAlgError:
                    return V, False

            # Reconstruct complex update: ΔVD + j*ΔVQ
            dV = dV_real[:nb] + 1j * dV_real[nb:]

            # Line search: simple damping if step is large
            step = dV
            step_norm = np.max(np.abs(step))
            if step_norm > 1.0:
                step = step / step_norm

            V = V + step

        # Final check
        g_val_final = self.system.g(x, V)
        return V, (np.max(np.abs(g_val_final)) < cfg.tol_nr * 100)

    # ── Single trapezoidal step ────────────────────────────────────────────
    def step_trapezoidal(
        self,
        x_n: np.ndarray,
        V_n: np.ndarray,
        h: float,
    ) -> Tuple[np.ndarray, np.ndarray, bool]:
        """Single implicit trapezoidal integration step.

        Algorithm:
        1. Predictor: x_pred = x_n + h * f(x_n, V_n)
                      V_pred = solve_algebraic(x_pred)
        2. Corrector: iterate
                      R(x_new) = x_new - x_n - (h/2)*[f(x_n,V_n) + f(x_new,V_new)]
                      x_new ← x_new - R(x_new)
                      V_new = solve_algebraic(x_new)

        Parameters
        ----------
        x_n : np.ndarray, shape (nx,)
        V_n : np.ndarray, complex, shape (nb,)
        h : float
            Time step (s).

        Returns
        -------
        x_new : np.ndarray, shape (nx,)
        V_new : np.ndarray, complex, shape (nb,)
        ok : bool
            True if corrector converged.
        """
        cfg = self.config

        # Step 1: Predictor (explicit Euler)
        f_n = self.system.f(x_n, V_n)
        x_pred = x_n + h * f_n
        V_pred, _ = self.solve_algebraic(x_pred, V_n)

        # Step 2: Corrector (fixed-point iteration on trapezoidal residual)
        x_new = x_pred.copy()
        V_new = V_pred.copy()
        ok = False

        for _ in range(cfg.max_iter_trap):
            V_new, conv = self.solve_algebraic(x_new, V_new)
            f_new = self.system.f(x_new, V_new)

            # Trapezoidal residual
            R = x_new - x_n - (h / 2.0) * (f_n + f_new)
            r_norm = np.max(np.abs(R))

            if r_norm < cfg.tol_trap:
                ok = True
                break

            # Fixed-point correction
            x_new = x_new - R

        if not ok:
            # Accept predictor if corrector did not converge
            V_new, _ = self.solve_algebraic(x_pred, V_n)
            x_new = x_pred

        return x_new, V_new, ok

    # ── Extract per-generator data ─────────────────────────────────────────
    def _extract_gen_data(
        self, x_traj: np.ndarray, V_traj: np.ndarray
    ) -> Dict[str, np.ndarray]:
        """Extract per-generator time series from state trajectories.

        Parameters
        ----------
        x_traj : np.ndarray, shape (nt, nx)
        V_traj : np.ndarray, complex, shape (nt, nb)

        Returns
        -------
        dict with keys 'delta', 'omega', 'Ed_p', 'Eq_p', 'Pe'
        Each value is shape (nt, ng).
        """
        ng = self.system.data.ng
        nt = x_traj.shape[0]
        data = self.system.data

        delta = np.zeros((nt, ng))
        omega = np.zeros((nt, ng))
        Ed_p = np.zeros((nt, ng))
        Eq_p = np.zeros((nt, ng))
        Pe = np.zeros((nt, ng))

        for t_idx in range(nt):
            x = x_traj[t_idx]
            V = V_traj[t_idx]
            for i in range(ng):
                base = 4 * i
                di = float(x[base])
                oi = float(x[base + 1])
                ep_d = float(x[base + 2])
                ep_q = float(x[base + 3])
                bus = data.gen_bus_idx[i]
                V_bus = complex(V[bus])

                delta[t_idx, i] = di
                omega[t_idx, i] = oi
                Ed_p[t_idx, i] = ep_d
                Eq_p[t_idx, i] = ep_q

                # Compute Pe
                from src.dynamics.models.sync_generator import SGState
                gen = data.generators[i]
                p = gen.p
                Vd, Vq = SGState.dq_from_net_voltage(V_bus, di)
                Id, Iq = SGState.solve_stator(ep_d, ep_q, Vd, Vq, p.Ra, p.Xd_p, p.Xq_p)
                Pe[t_idx, i] = SGState.electrical_power(Vd, Vq, Id, Iq)

        return {
            "delta": delta,
            "omega": omega,
            "Ed_p": Ed_p,
            "Eq_p": Eq_p,
            "Pe": Pe,
        }

    # ── Main simulation run ────────────────────────────────────────────────
    def run(
        self,
        x0: np.ndarray,
        V0: np.ndarray,
        events: Optional[List[Any]] = None,
    ) -> SimulationResult:
        """Run time-domain simulation with optional fault events.

        Parameters
        ----------
        x0 : np.ndarray, shape (nx,)
            Initial generator state vector.
        V0 : np.ndarray, complex, shape (nb,)
            Initial bus voltage vector.
        events : list, optional
            List of FaultEvent objects or (t_event, callback) tuples.
            For FaultEvent: fault applied at t_fault, cleared at t_clear.
            For (t, fn): fn(system) is called at time t.

        Returns
        -------
        SimulationResult
        """
        cfg = self.config
        h = cfg.dt
        nb = self.system.data.nb

        # Restore nominal Y_bus at start
        self._clear_fault_ybus()

        # Parse events
        fault_events: List[FaultEvent] = []
        generic_events: List[Tuple[float, Callable]] = []
        if events:
            for ev in events:
                if isinstance(ev, FaultEvent):
                    fault_events.append(ev)
                elif isinstance(ev, tuple) and len(ev) == 2:
                    generic_events.append(ev)

        # Identify critical time points (event boundaries)
        critical_times: List[float] = []
        for fe in fault_events:
            critical_times.append(fe.t_fault)
            critical_times.append(fe.t_clear)
        for t_ev, _ in generic_events:
            critical_times.append(t_ev)

        # Storage lists
        t_list: List[float] = [0.0]
        x_list: List[np.ndarray] = [x0.copy()]
        V_list: List[np.ndarray] = [V0.copy()]

        x_cur = x0.copy()
        V_cur = V0.copy()

        nr_fail_count = 0
        t_cur = 0.0
        step_num = 0
        active_faults: List[FaultEvent] = []
        cleared_faults: set = set()

        t_end = cfg.t_end
        last_print_t = 0.0

        while t_cur < t_end - 1e-12:
            # Determine next step size (snap to critical times)
            t_next = min(t_cur + h, t_end)
            for tc in critical_times:
                if t_cur < tc <= t_next:
                    t_next = tc
                    break
            h_step = t_next - t_cur

            # ── Apply/clear faults before this step ─────────────────────
            for fe in fault_events:
                fid = id(fe)
                # Apply fault
                if (abs(t_cur - fe.t_fault) < 1e-10 and fid not in cleared_faults
                        and fe not in active_faults):
                    self._apply_fault_ybus(fe)
                    active_faults.append(fe)

                # Clear fault
                if (abs(t_cur - fe.t_clear) < 1e-10 and fe in active_faults):
                    active_faults.remove(fe)
                    cleared_faults.add(fid)
                    if not active_faults:
                        self._clear_fault_ybus()

            # ── Apply generic events ─────────────────────────────────────
            for t_ev, fn in generic_events:
                if abs(t_cur - t_ev) < 1e-10:
                    fn(self.system)

            # ── Integration step ─────────────────────────────────────────
            x_new, V_new, ok = self.step_trapezoidal(x_cur, V_cur, h_step)
            if not ok:
                nr_fail_count += 1

            t_cur = t_next
            x_cur = x_new
            V_cur = V_new
            step_num += 1

            # ── Store output ─────────────────────────────────────────────
            if step_num % cfg.store_every == 0:
                t_list.append(t_cur)
                x_list.append(x_cur.copy())
                V_list.append(V_cur.copy())

            if cfg.verbose and t_cur - last_print_t >= 1.0:
                print(f"  t = {t_cur:.2f} s  (NR fails so far: {nr_fail_count})")
                last_print_t = t_cur

        # ── Assemble result arrays ────────────────────────────────────────
        t_arr = np.array(t_list)
        x_arr = np.array(x_list)
        V_arr = np.array(V_list)

        gen_data = self._extract_gen_data(x_arr, V_arr)

        return SimulationResult(
            t=t_arr,
            x=x_arr,
            V=V_arr,
            gen_data=gen_data,
            converged=(nr_fail_count == 0),
            nr_fail_count=nr_fail_count,
        )
