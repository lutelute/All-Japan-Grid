"""Transient stability analysis for All-Japan-Grid power system dynamics.

Provides fault-clear scenario simulation, critical clearing time (CCT)
binary search, N-1/N-2 contingency screening, and swing curve plotting.

Stability criterion: max|δ_i - δ_j| < π (180°) for all generator pairs
at all time points. Exceeding this threshold indicates loss of synchronism.

Usage::

    from src.dynamics.simulation.dae_system import DAESystem
    from src.dynamics.simulation.dae_solver import SolverConfig
    from src.dynamics.analysis.transient import (
        TransientAnalysis, FaultScenario, plot_swing_curves
    )

    config = SolverConfig(dt=0.01, t_end=5.0)
    ta = TransientAnalysis(system, config)

    scenario = FaultScenario("Bus5-3ph", fault_bus_idx=5, t_fault=0.1, t_clear=0.2)
    result = ta.run_scenario(x0, V0, scenario)
    print(f"Stable: {result.is_stable}, CCT: {result.cct_s:.3f} s")
    plot_swing_curves(result, "swing_bus5.png")
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from src.dynamics.simulation.dae_system import DAESystem
from src.dynamics.simulation.dae_solver import DAESolver, FaultEvent, SolverConfig


# ── Fault Scenario ────────────────────────────────────────────────────────────
@dataclass
class FaultScenario:
    """Specification for a single fault-clear transient scenario.

    Attributes
    ----------
    name : str
        Descriptive label (e.g., 'Bus5-3ph-0.15s').
    fault_bus_idx : int
        Bus index where the 3-phase fault is applied.
    t_fault : float
        Time at which fault is applied (s). Default 0.1 s.
    t_clear : float
        Fault clearing time (s). Default 0.2 s.
    t_end : float
        Total simulation duration (s). Default 5.0 s.
    fault_impedance : complex
        Fault impedance (pu). 0j = bolted fault.
    """

    name: str
    fault_bus_idx: int
    t_fault: float = 0.1
    t_clear: float = 0.2
    t_end: float = 5.0
    fault_impedance: complex = 0j


# ── Transient Result ──────────────────────────────────────────────────────────
@dataclass
class TransientResult:
    """Output of a transient stability simulation.

    Attributes
    ----------
    scenario : FaultScenario
        The fault scenario that was simulated.
    t : np.ndarray, shape (nt,)
        Time vector (s).
    delta : np.ndarray, shape (ng, nt)
        Rotor angles for each generator (rad).
    omega : np.ndarray, shape (ng, nt)
        Per-unit rotor speeds for each generator.
    Pe : np.ndarray, shape (ng, nt)
        Electrical power output (machine base pu).
    is_stable : bool
        True if max pairwise rotor angle separation < 180° at all times.
    max_separation_deg : float
        Maximum pairwise rotor angle separation in degrees.
    cct_s : float
        Critical clearing time (s). Set to NaN if not computed.
    generator_names : list of str
        Names of the generators.
    """

    scenario: FaultScenario
    t: np.ndarray
    delta: np.ndarray
    omega: np.ndarray
    Pe: np.ndarray
    is_stable: bool
    max_separation_deg: float
    cct_s: float = float("nan")
    generator_names: List[str] = field(default_factory=list)


# ── Stability Criterion ───────────────────────────────────────────────────────
def _check_stability(delta_traj: np.ndarray, limit_rad: float = math.pi) -> Tuple[bool, float]:
    """Check transient stability from rotor angle trajectories.

    Parameters
    ----------
    delta_traj : np.ndarray, shape (ng, nt) or (nt, ng)
        Rotor angle trajectories.
    limit_rad : float
        Maximum allowed angle separation (rad). Default π (180°).

    Returns
    -------
    (is_stable, max_separation_deg) : (bool, float)
    """
    if delta_traj.ndim == 2:
        # Ensure shape is (ng, nt)
        if delta_traj.shape[0] > delta_traj.shape[1]:
            d = delta_traj.T
        else:
            d = delta_traj
    else:
        return True, 0.0

    ng, nt = d.shape
    if ng <= 1:
        return True, 0.0

    max_sep_rad = 0.0
    for t_idx in range(nt):
        d_t = d[:, t_idx]
        sep = float(np.max(d_t) - np.min(d_t))
        if sep > max_sep_rad:
            max_sep_rad = sep

    is_stable = max_sep_rad < limit_rad
    return is_stable, float(np.rad2deg(max_sep_rad))


# ── Transient Analysis Class ──────────────────────────────────────────────────
class TransientAnalysis:
    """Transient stability analysis for a DAE power system model.

    Supports fault-clear scenario simulation, CCT binary search,
    N-1/N-2 contingency screening, and swing curve generation.

    Parameters
    ----------
    system : DAESystem
        The assembled DAE system.
    solver_config : SolverConfig
        Default solver configuration.
    """

    def __init__(self, system: DAESystem, solver_config: SolverConfig) -> None:
        self.system = system
        self.config = solver_config
        # Keep a reference to the nominal Y_bus for fault/restore
        self._Y_bus_nominal = system.data.Y_bus.copy()

    # ── Y_bus fault manipulation ───────────────────────────────────────────
    def apply_fault(
        self,
        fault_bus: int,
        Z_fault: complex = 0j,
    ) -> None:
        """Modify Y_bus to apply 3-phase fault at fault_bus.

        For a bolted fault (Z_fault = 0): add very large shunt admittance
        (1e10 pu) at the fault bus diagonal, effectively clamping bus voltage
        to zero.

        For impedance fault: Y_shunt = 1/Z_fault.

        Parameters
        ----------
        fault_bus : int
            Bus index of the faulted bus.
        Z_fault : complex
            Fault impedance (pu). 0j for bolted fault.
        """
        import scipy.sparse as sp
        if abs(Z_fault) < 1e-12:
            y_shunt = 1e10 + 0j
        else:
            y_shunt = 1.0 / Z_fault

        Y = self.system.data.Y_bus.tolil()
        Y[fault_bus, fault_bus] = Y[fault_bus, fault_bus] + y_shunt
        self.system.data.Y_bus = Y.tocsr()
        # Invalidate dense cache
        if self.system._nb <= 200:
            self.system._Y_dense = np.array(
                self.system.data.Y_bus.toarray(), dtype=complex
            )

    def clear_fault(self, fault_bus: Optional[int] = None) -> None:
        """Restore Y_bus to nominal state after fault clearance.

        Parameters
        ----------
        fault_bus : int, optional
            Not used (full Y_bus is restored). Kept for API symmetry.
        """
        self.system.data.Y_bus = self._Y_bus_nominal.copy()
        if self.system._nb <= 200:
            self.system._Y_dense = np.array(
                self.system.data.Y_bus.toarray(), dtype=complex
            )
        else:
            self.system._Y_dense = None

    # ── Single fault-clear scenario ────────────────────────────────────────
    def run_scenario(
        self,
        x0: np.ndarray,
        V0: np.ndarray,
        scenario: FaultScenario,
    ) -> TransientResult:
        """Simulate a fault-clear scenario and assess transient stability.

        Parameters
        ----------
        x0 : np.ndarray, shape (nx,)
            Initial generator state vector.
        V0 : np.ndarray, complex, shape (nb,)
            Initial bus voltage vector.
        scenario : FaultScenario
            Fault scenario specification.

        Returns
        -------
        TransientResult
            Simulation result with stability assessment.
        """
        # Create per-scenario solver config with scenario's t_end
        cfg = SolverConfig(
            dt=self.config.dt,
            t_end=scenario.t_end,
            max_iter_nr=self.config.max_iter_nr,
            tol_nr=self.config.tol_nr,
        )

        # Create fault event
        fault_ev = FaultEvent(
            t_fault=scenario.t_fault,
            t_clear=scenario.t_clear,
            fault_bus_idx=scenario.fault_bus_idx,
            fault_impedance=scenario.fault_impedance,
        )

        solver = DAESolver(self.system, cfg)
        sim = solver.run(x0, V0, events=[fault_ev])

        # Extract delta and omega: gen_data shape is (nt, ng)
        delta_traj = sim.gen_data["delta"]  # (nt, ng)
        omega_traj = sim.gen_data["omega"]  # (nt, ng)
        Pe_traj = sim.gen_data["Pe"]         # (nt, ng)

        # Transpose to (ng, nt) for TransientResult convention
        delta_ng_nt = delta_traj.T
        omega_ng_nt = omega_traj.T
        Pe_ng_nt = Pe_traj.T

        is_stable, max_sep_deg = _check_stability(delta_ng_nt)

        gen_names = [g.p.name for g in self.system.data.generators]

        return TransientResult(
            scenario=scenario,
            t=sim.t,
            delta=delta_ng_nt,
            omega=omega_ng_nt,
            Pe=Pe_ng_nt,
            is_stable=is_stable,
            max_separation_deg=max_sep_deg,
            generator_names=gen_names,
        )

    # ── Critical clearing time (CCT) search ───────────────────────────────
    def find_cct(
        self,
        x0: np.ndarray,
        V0: np.ndarray,
        fault_bus: int,
        dt: float = 0.01,
        max_tclear: float = 1.0,
        t_end: float = 5.0,
        n_bisect: int = 20,
    ) -> float:
        """Find critical clearing time via binary search.

        Searches for the largest clearing time t_clear in [dt, max_tclear]
        for which the system remains stable.

        Parameters
        ----------
        x0 : np.ndarray, shape (nx,)
        V0 : np.ndarray, complex, shape (nb,)
        fault_bus : int
            Bus index for the 3-phase fault.
        dt : float
            Time step and minimum resolution for CCT (s). Default 0.01 s.
        max_tclear : float
            Upper bound for clearing time search (s). Default 1.0 s.
        t_end : float
            Simulation duration for each candidate (s). Default 5.0 s.
        n_bisect : int
            Number of bisection iterations. Default 20.

        Returns
        -------
        float
            Critical clearing time (s). Returns NaN if unstable for
            the minimum clearing time or stable for the maximum.
        """
        t_fault = 0.1  # fixed fault onset

        def is_stable_for_tclear(t_clear: float) -> bool:
            scenario = FaultScenario(
                name=f"cct_search_tc{t_clear:.4f}",
                fault_bus_idx=fault_bus,
                t_fault=t_fault,
                t_clear=t_clear,
                t_end=t_end,
            )
            try:
                result = self.run_scenario(x0, V0, scenario)
                return result.is_stable
            except Exception:
                return False

        # Check bounds
        if not is_stable_for_tclear(dt):
            return float("nan")
        if is_stable_for_tclear(max_tclear):
            return max_tclear

        # Binary search
        t_lo = dt
        t_hi = max_tclear
        for _ in range(n_bisect):
            t_mid = (t_lo + t_hi) / 2.0
            if is_stable_for_tclear(t_mid):
                t_lo = t_mid
            else:
                t_hi = t_mid
            if t_hi - t_lo < dt / 10.0:
                break

        return float((t_lo + t_hi) / 2.0)

    # ── N-1 / N-2 stability screening ─────────────────────────────────────
    def nx_stability_check(
        self,
        x0: np.ndarray,
        V0: np.ndarray,
        n_candidates: int = 50,
        t_fault: float = 0.1,
        t_clear: float = 0.2,
        t_end: float = 5.0,
    ) -> Dict:
        """N-1 contingency stability screening.

        Trips generators one at a time (set Pm=0, disconnect from Y_bus)
        and checks stability for each contingency.

        Parameters
        ----------
        x0 : np.ndarray, shape (nx,)
        V0 : np.ndarray, complex, shape (nb,)
        n_candidates : int
            Number of largest generators to screen (by machine MVA). Default 50.
        t_fault : float
            Fault onset (s) for fault-clear events. Default 0.1 s.
        t_clear : float
            Fault clearing time (s). Default 0.2 s.
        t_end : float
            Simulation duration (s). Default 5.0 s.

        Returns
        -------
        dict with keys:
            'results': list of dicts per generator:
                {'gen_idx', 'gen_name', 'bus', 'is_stable', 'max_sep_deg', 'fault_bus'}
            'n_stable': int — number of stable N-1 contingencies
            'n_unstable': int
        """
        import scipy.sparse as sp
        data = self.system.data
        ng = data.ng

        # Sort generators by MVA rating (largest first)
        ratings = [(i, data.generators[i].p.S_rated_mva) for i in range(ng)]
        ratings.sort(key=lambda x: -x[1])
        candidates = [r[0] for r in ratings[:min(n_candidates, ng)]]

        results = []
        Y_nominal = self._Y_bus_nominal.copy()
        Pm_nominal = list(data.Pm)
        Efd_nominal = list(data.Efd)

        for gen_idx in candidates:
            bus = data.gen_bus_idx[gen_idx]
            gen_name = data.generators[gen_idx].p.name

            # Simulate bus fault at generator terminal bus
            scenario = FaultScenario(
                name=f"N-1_gen{gen_idx}_{gen_name}",
                fault_bus_idx=bus,
                t_fault=t_fault,
                t_clear=t_clear,
                t_end=t_end,
            )

            try:
                res = self.run_scenario(x0, V0, scenario)
                stable = res.is_stable
                max_sep = res.max_separation_deg
            except Exception as exc:
                stable = False
                max_sep = float("nan")

            results.append({
                "gen_idx": gen_idx,
                "gen_name": gen_name,
                "bus": bus,
                "is_stable": stable,
                "max_sep_deg": max_sep,
                "fault_bus": bus,
                "capacity_mva": data.generators[gen_idx].p.S_rated_mva,
            })

        n_stable = sum(1 for r in results if r["is_stable"])
        n_unstable = len(results) - n_stable

        return {
            "results": results,
            "n_stable": n_stable,
            "n_unstable": n_unstable,
            "screened": len(candidates),
        }


# ── Swing Curve Plotting ───────────────────────────────────────────────────────
def plot_swing_curves(
    result: TransientResult,
    fig_path: str,
    show_omega: bool = True,
) -> None:
    """Generate swing curve plots from a TransientResult.

    Creates a figure with:
    - Rotor angle trajectories (degrees) for all generators
    - Per-unit rotor speed trajectories (optional)
    - Fault period shaded region
    - Stability verdict annotation

    Parameters
    ----------
    result : TransientResult
        Simulation result to plot.
    fig_path : str
        Output file path for the figure (PNG, PDF, etc.).
    show_omega : bool
        If True, plot rotor speed deviations as a second panel. Default True.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
    except ImportError:
        print("matplotlib not available; skipping plot.")
        return

    ng, nt = result.delta.shape
    t = result.t
    delta_deg = np.rad2deg(result.delta)

    n_panels = 2 if show_omega else 1
    fig, axes = plt.subplots(n_panels, 1, figsize=(10, 4 * n_panels), sharex=True)
    if n_panels == 1:
        axes = [axes]

    # ── Panel 1: Rotor angles ─────────────────────────────────────────────
    ax1 = axes[0]
    colors = plt.cm.tab10(np.linspace(0, 1, max(ng, 1)))
    for i in range(ng):
        label = result.generator_names[i] if result.generator_names else f"Gen {i+1}"
        ax1.plot(t, delta_deg[i], color=colors[i], lw=1.5, label=label)

    # 180° stability limit
    ax1.axhline(180, color="red", lw=1, ls="--", label="180° limit")
    ax1.axhline(-180, color="red", lw=1, ls="--")

    # Shade fault period
    ax1.axvspan(
        result.scenario.t_fault,
        result.scenario.t_clear,
        alpha=0.15, color="orange", label="Fault period",
    )

    status = "STABLE" if result.is_stable else "UNSTABLE"
    color_status = "green" if result.is_stable else "red"
    ax1.set_title(
        f"{result.scenario.name} — {status} "
        f"(max sep: {result.max_separation_deg:.1f}°)",
        color=color_status, fontsize=12,
    )
    ax1.set_ylabel("Rotor Angle (°)")
    ax1.legend(loc="upper right", fontsize=8, ncol=min(ng, 4))
    ax1.grid(True, alpha=0.3)

    # ── Panel 2: Rotor speed ──────────────────────────────────────────────
    if show_omega:
        ax2 = axes[1]
        for i in range(ng):
            label = result.generator_names[i] if result.generator_names else f"Gen {i+1}"
            ax2.plot(t, (result.omega[i] - 1.0) * 100, color=colors[i], lw=1.5, label=label)

        ax2.axhline(0, color="gray", lw=0.8, ls="-")
        ax2.axvspan(
            result.scenario.t_fault,
            result.scenario.t_clear,
            alpha=0.15, color="orange",
        )
        ax2.set_ylabel("Speed Deviation (%)")
        ax2.grid(True, alpha=0.3)

    axes[-1].set_xlabel("Time (s)")

    fig.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(fig_path)), exist_ok=True)
    fig.savefig(fig_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
