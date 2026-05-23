"""Voltage stability analysis for All-Japan-Grid using continuation power flow.

Implements the predictor-corrector continuation power flow (CPF) method
for tracing P-V (nose) curves, Q-V curves, and identifying voltage collapse
(nose point) loading margins.

The CPF algorithm:
1. Parameterize load increase by scalar λ: P(λ) = P0 + λ*dP, Q(λ) = Q0 + λ*dQ
2. Predictor: tangent vector from augmented Jacobian [J, ∂g/∂λ; e_k^T, 0]
3. Corrector: Newton-Raphson to return to the equilibrium manifold
4. Nose point detection: monitoring eigenvalue sign change of J, or λ turning

Usage::

    from src.dynamics.simulation.dae_system import DAESystem
    from src.dynamics.analysis.voltage_stability import VoltageStabilityAnalysis

    vsa = VoltageStabilityAnalysis(system)
    result = vsa.run_cpf(x0, V0, dlambda=0.05, max_lambda=3.0)
    print(f"Nose point λ = {result.nose_point_lambda:.3f}")
    vsa.plot_pv_curves(result, "pv_curves.png")
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from src.dynamics.simulation.dae_system import DAESystem


# ── PV Curve Result ───────────────────────────────────────────────────────────
@dataclass
class PVCurveResult:
    """Output of continuation power flow.

    Attributes
    ----------
    lambda_values : np.ndarray, shape (n_pts,)
        Loading factor λ at each continuation step.
    V_mag : np.ndarray, shape (n_pts, nb)
        Bus voltage magnitudes (pu) at each step.
    V_ang : np.ndarray, shape (n_pts, nb)
        Bus voltage angles (rad) at each step.
    nose_point_lambda : float
        Loading factor at the voltage collapse (nose) point.
    critical_bus : int
        Bus index with the most severe voltage drop at the nose point.
    converged_steps : int
        Number of successful CPF steps.
    load_direction : dict
        The ΔP, ΔQ direction used for the loading increase.
    """

    lambda_values: np.ndarray
    V_mag: np.ndarray
    V_ang: np.ndarray
    nose_point_lambda: float
    critical_bus: int
    converged_steps: int
    load_direction: Dict[int, Tuple[float, float]] = field(default_factory=dict)


# ── Voltage Stability Analysis ────────────────────────────────────────────────
class VoltageStabilityAnalysis:
    """Voltage stability analysis via continuation power flow.

    Uses the CPF predictor-corrector method to trace the nose curve,
    compute Q-V characteristics, and identify voltage collapse points.

    Parameters
    ----------
    system : DAESystem
        The assembled DAE system.
    """

    def __init__(self, system: DAESystem) -> None:
        self.system = system
        self._nb = system.data.nb

    # ── Internal: power flow mismatch at given λ ────────────────────────────
    def _power_flow_g(
        self,
        V: np.ndarray,
        x0: np.ndarray,
        lam: float,
        P0: np.ndarray,
        Q0: np.ndarray,
        dP: np.ndarray,
        dQ: np.ndarray,
    ) -> np.ndarray:
        """Compute power flow mismatch at loading factor λ.

        g(V, λ) = Y*V - I_gen(x0, V) + I_load(λ)
        where I_load changes with λ: P_load = P0 + λ*dP

        Parameters
        ----------
        V : np.ndarray, complex, shape (nb,)
        x0 : np.ndarray, shape (nx,)
        lam : float
            Loading factor.
        P0, Q0 : np.ndarray, shape (nb,)
            Base load injections (pu). Positive = demand.
        dP, dQ : np.ndarray, shape (nb,)
            Load increase direction vectors.

        Returns
        -------
        np.ndarray, real, shape (2*nb,)
        """
        nb = self._nb
        data = self.system.data

        # Scale loads with lambda
        load_buses_lam = {}
        for bus, (p0, q0) in data.load_buses.items():
            dp = float(dP[bus]) if bus < len(dP) else 0.0
            dq = float(dQ[bus]) if bus < len(dQ) else 0.0
            load_buses_lam[bus] = (p0 + lam * dp, q0 + lam * dq)

        # Temporarily override load_buses
        orig_load = data.load_buses
        data.load_buses = load_buses_lam
        g_val = self.system.g(x0, V)
        data.load_buses = orig_load

        return g_val

    def _power_flow_jacobian(
        self,
        V: np.ndarray,
        x0: np.ndarray,
        lam: float,
        dP: np.ndarray,
        dQ: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Compute Jacobian ∂g/∂V and ∂g/∂λ.

        Returns
        -------
        J_V : np.ndarray, shape (2*nb, 2*nb) — ∂g/∂V_real
        J_lam : np.ndarray, shape (2*nb,) — ∂g/∂λ
        """
        nb = self._nb
        data = self.system.data

        # ∂g/∂V from DAE system
        load_buses_lam = {}
        for bus, (p0, q0) in data.load_buses.items():
            dp = float(dP[bus]) if bus < len(dP) else 0.0
            dq = float(dQ[bus]) if bus < len(dQ) else 0.0
            load_buses_lam[bus] = (p0 + lam * dp, q0 + lam * dq)

        orig_load = data.load_buses
        data.load_buses = load_buses_lam
        J_V = self.system.jacobian_g_v(x0, V)
        data.load_buses = orig_load

        # ∂g/∂λ: differentiate load current w.r.t. λ
        # I_load = (P_load - j*Q_load) / conj(V)
        # ∂I_load/∂λ = (dP - j*dQ) / conj(V)
        dI_dlam = np.zeros(nb, dtype=complex)
        for bus in data.load_buses:
            Vk = V[bus]
            Vc = Vk.conjugate()
            if abs(Vc) > 1e-10:
                dp = float(dP[bus]) if bus < len(dP) else 0.0
                dq = float(dQ[bus]) if bus < len(dQ) else 0.0
                dI_dlam[bus] = complex(dp, -dq) / Vc  # sign: +I_load in mismatch

        J_lam = np.zeros(2 * nb)
        J_lam[:nb] = dI_dlam.real
        J_lam[nb:] = dI_dlam.imag

        # Slack bus: no dependence on λ
        slack = data.slack_bus
        J_lam[slack] = 0.0
        J_lam[nb + slack] = 0.0

        return J_V, J_lam

    # ── CPF Predictor: tangent vector ──────────────────────────────────────
    def _cpf_predictor(
        self,
        V: np.ndarray,
        x0: np.ndarray,
        lam: float,
        dP: np.ndarray,
        dQ: np.ndarray,
        dlambda: float,
        param_bus: int,
        param_sign: int = 1,
    ) -> Tuple[np.ndarray, float]:
        """Compute CPF predictor step using tangent vector.

        The augmented system [J, J_lam; e_p^T, 0] * [dV; dlam] = [0; 1]
        where e_p selects the continuation parameter (bus voltage magnitude).

        Parameters
        ----------
        V : np.ndarray, complex, shape (nb,)
        x0 : np.ndarray, shape (nx,)
        lam : float
        dP, dQ : np.ndarray
        dlambda : float
            Predictor step size.
        param_bus : int
            Bus used as continuation parameter.
        param_sign : int
            +1 for increasing λ, -1 for decreasing (post-nose).

        Returns
        -------
        (V_pred, lam_pred)
        """
        nb = self._nb
        J_V, J_lam = self._power_flow_jacobian(V, x0, lam, dP, dQ)

        n = 2 * nb
        # Augmented system: [J_V, J_lam; e_p, 0] * [dV_real; dlam] = [0; 1]
        A_aug = np.zeros((n + 1, n + 1))
        A_aug[:n, :n] = J_V
        A_aug[:n, n] = J_lam
        # Continuation parameter: bus voltage magnitude at param_bus
        # Vm^2 = VD^2 + VQ^2, d(Vm)/d(VD) = VD/Vm, d(Vm)/d(VQ) = VQ/Vm
        Vm = abs(V[param_bus])
        if Vm > 1e-10:
            A_aug[n, param_bus] = V[param_bus].real / Vm   # ∂Vm/∂VD
            A_aug[n, nb + param_bus] = V[param_bus].imag / Vm  # ∂Vm/∂VQ
        else:
            A_aug[n, param_bus] = 1.0

        rhs = np.zeros(n + 1)
        rhs[n] = 1.0  # dVm_param / dlam = param_sign

        try:
            tangent = np.linalg.solve(A_aug, rhs * param_sign)
        except np.linalg.LinAlgError:
            tangent = np.zeros(n + 1)
            tangent[n] = param_sign

        # Normalize tangent: step in V-lam space = dlambda
        tan_norm = np.linalg.norm(tangent)
        if tan_norm > 1e-12:
            tangent = tangent * dlambda / tan_norm

        dV_real = tangent[:n]
        dlam = tangent[n]

        V_flat = np.concatenate([V.real, V.imag])
        V_flat_new = V_flat + dV_real
        V_pred = V_flat_new[:nb] + 1j * V_flat_new[nb:]
        lam_pred = lam + dlam

        return V_pred, float(lam_pred)

    # ── CPF Corrector: NR on augmented system ─────────────────────────────
    def _cpf_corrector(
        self,
        V_pred: np.ndarray,
        lam_pred: float,
        x0: np.ndarray,
        dP: np.ndarray,
        dQ: np.ndarray,
        param_bus: int,
        Vm_param_target: float,
        max_iter: int = 10,
        tol: float = 1e-8,
    ) -> Tuple[np.ndarray, float, bool]:
        """CPF corrector: Newton-Raphson on g(V, λ) = 0 with parametric constraint.

        Constraint: |V[param_bus]| = Vm_param_target (fixed from predictor).

        Parameters
        ----------
        V_pred, lam_pred : predicted starting point
        x0 : generator states (fixed)
        dP, dQ : load direction
        param_bus : continuation bus
        Vm_param_target : target voltage magnitude at param_bus
        max_iter, tol : NR parameters

        Returns
        -------
        (V, lam, converged)
        """
        nb = self._nb
        V = V_pred.copy()
        lam = lam_pred
        n = 2 * nb
        slack = self.system.data.slack_bus

        for _ in range(max_iter):
            # Use actual lambda-modified loads via direct system.g call
            data = self.system.data
            load_lam = {}
            for bus, (p0, q0) in data.load_buses.items():
                dp = float(dP[bus]) if bus < len(dP) else 0.0
                dq = float(dQ[bus]) if bus < len(dQ) else 0.0
                load_lam[bus] = (p0 + lam * dp, q0 + lam * dq)
            orig_load = data.load_buses
            data.load_buses = load_lam
            g_val = self.system.g(x0, V)
            J_V = self.system.jacobian_g_v(x0, V)
            data.load_buses = orig_load

            _, J_lam = self._power_flow_jacobian(V, x0, lam, dP, dQ)

            # Voltage magnitude at param_bus
            Vm_p = abs(V[param_bus])
            g_aug = np.zeros(n + 1)
            g_aug[:n] = g_val
            g_aug[n] = Vm_p - Vm_param_target

            # Augmented Jacobian
            A = np.zeros((n + 1, n + 1))
            A[:n, :n] = J_V
            A[:n, n] = J_lam
            if Vm_p > 1e-10:
                A[n, param_bus] = V[param_bus].real / Vm_p
                A[n, nb + param_bus] = V[param_bus].imag / Vm_p
            else:
                A[n, param_bus] = 1.0
            A[n, n] = 0.0

            if np.max(np.abs(g_aug)) < tol:
                return V, lam, True

            try:
                sol = np.linalg.solve(A, -g_aug)
            except np.linalg.LinAlgError:
                return V, lam, False

            dV_real = sol[:n]
            dlam = sol[n]
            V = (V.real + dV_real[:nb]) + 1j * (V.imag + dV_real[nb:])
            lam = lam + dlam

        return V, lam, False

    # ── Main CPF run ────────────────────────────────────────────────────────
    def run_cpf(
        self,
        x0: np.ndarray,
        V0: np.ndarray,
        load_direction: Optional[Dict[int, Tuple[float, float]]] = None,
        dlambda: float = 0.05,
        max_lambda: float = 3.0,
    ) -> PVCurveResult:
        """Run continuation power flow to trace the P-V (nose) curve.

        Parameters
        ----------
        x0 : np.ndarray, shape (nx,)
            Generator states (held fixed; only network voltages are traced).
        V0 : np.ndarray, complex, shape (nb,)
            Initial bus voltages at λ = 0.
        load_direction : dict {bus_idx: (dP, dQ)}, optional
            Direction of load increase per bus (pu). If None, all PQ buses
            increase load uniformly by 1 pu/lambda.
        dlambda : float
            Step size for continuation parameter. Default 0.05.
        max_lambda : float
            Maximum loading factor to trace. Default 3.0.

        Returns
        -------
        PVCurveResult
        """
        nb = self._nb
        data = self.system.data

        # Build load direction vectors
        dP = np.zeros(nb)
        dQ = np.zeros(nb)
        if load_direction is not None:
            for bus, (dp, dq) in load_direction.items():
                if bus < nb:
                    dP[bus] = dp
                    dQ[bus] = dq
        else:
            # Uniform increase on all load buses
            for bus, (p0, q0) in data.load_buses.items():
                dP[bus] = max(p0, 0.01)
                dQ[bus] = max(q0 * 0.3, 0.003)

        # Base loads
        P0 = np.zeros(nb)
        Q0 = np.zeros(nb)
        for bus, (p0, q0) in data.load_buses.items():
            P0[bus] = p0
            Q0[bus] = q0

        # Initialize CPF
        V = V0.copy()
        lam = 0.0

        lam_traj = [lam]
        V_mag_traj = [np.abs(V)]
        V_ang_traj = [np.angle(V)]
        converged_steps = 0

        # Initial continuation parameter bus: lowest voltage bus
        param_bus = int(np.argmin(np.abs(V)))
        param_sign = 1  # increasing lambda initially

        nose_lambda = max_lambda
        nose_detected = False
        prev_lam = 0.0

        step = 0
        max_steps = int(max_lambda / dlambda) * 3  # allow for back-tracing

        while step < max_steps and abs(lam) <= max_lambda:
            step += 1

            # Predictor
            V_pred, lam_pred = self._cpf_predictor(
                V, x0, lam, dP, dQ, dlambda, param_bus, param_sign
            )

            # Choose continuation parameter: bus with largest voltage change
            Vm_pred = np.abs(V_pred)
            Vm_curr = np.abs(V)
            delta_Vm = np.abs(Vm_pred - Vm_curr)
            param_bus = int(np.argmax(delta_Vm))
            if delta_Vm[param_bus] < 1e-10:
                param_bus = int(np.argmin(Vm_curr))
            Vm_target = abs(V_pred[param_bus])

            # Corrector
            V_new, lam_new, ok = self._cpf_corrector(
                V_pred, lam_pred, x0, dP, dQ,
                param_bus=param_bus,
                Vm_param_target=Vm_target,
            )

            if not ok:
                # Reduce step and retry
                dlambda = dlambda * 0.5
                if dlambda < 1e-4:
                    break
                continue

            converged_steps += 1

            # Check if lambda is decreasing (passed nose point)
            if lam_new < lam and not nose_detected:
                nose_detected = True
                nose_lambda = float(lam)
                param_sign = -1  # start back-tracing

            prev_lam = lam
            V = V_new
            lam = lam_new

            lam_traj.append(float(lam))
            V_mag_traj.append(np.abs(V))
            V_ang_traj.append(np.angle(V))

            # Stop if voltages collapse below 0.3 pu or lambda decreases back to 0
            if float(np.min(np.abs(V))) < 0.3:
                break
            if nose_detected and lam < 0.05:
                break

        # If nose not detected, use max lambda reached
        if not nose_detected:
            nose_lambda = float(max(lam_traj))

        # Critical bus: largest voltage drop at nose
        if len(V_mag_traj) > 1:
            V_at_nose = V_mag_traj[len(V_mag_traj) // 2]
            V_drop = V_mag_traj[0] - V_at_nose
            critical_bus = int(np.argmax(V_drop))
        else:
            critical_bus = int(np.argmin(V_mag_traj[-1]))

        load_dir_dict = {}
        for bus in range(nb):
            if dP[bus] != 0 or dQ[bus] != 0:
                load_dir_dict[bus] = (float(dP[bus]), float(dQ[bus]))

        return PVCurveResult(
            lambda_values=np.array(lam_traj),
            V_mag=np.array(V_mag_traj),
            V_ang=np.array(V_ang_traj),
            nose_point_lambda=nose_lambda,
            critical_bus=critical_bus,
            converged_steps=converged_steps,
            load_direction=load_dir_dict,
        )

    # ── P-V curve for a single bus ─────────────────────────────────────────
    def pv_curve_bus(
        self,
        V0_init: np.ndarray,
        load_factor_range: np.ndarray,
        target_bus: int,
        x0: Optional[np.ndarray] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Compute P-V curve at target_bus by sweeping load factors.

        For each λ in load_factor_range, runs Newton-Raphson power flow
        and records bus voltage magnitude.

        Parameters
        ----------
        V0_init : np.ndarray, complex, shape (nb,)
        load_factor_range : np.ndarray
            Array of loading factors λ to evaluate.
        target_bus : int
        x0 : np.ndarray, optional
            Generator states. Uses zeros if None.

        Returns
        -------
        (lambda_arr, V_mag_arr) : ndarrays of same length as load_factor_range
        """
        if x0 is None:
            x0 = np.zeros(self.system.nx)

        nb = self._nb
        data = self.system.data

        # Build base load arrays
        dP = np.zeros(nb)
        dQ = np.zeros(nb)
        for bus, (p0, q0) in data.load_buses.items():
            dP[bus] = p0
            dQ[bus] = q0 * 0.3

        V_results = []
        lam_results = []

        V = V0_init.copy()
        for lam in load_factor_range:
            # Temporarily set scaled loads
            load_lam = {}
            for bus, (p0, q0) in data.load_buses.items():
                load_lam[bus] = (p0 + lam * dP[bus], q0 + lam * dQ[bus])

            orig_load = data.load_buses
            data.load_buses = load_lam

            # Simple NR solve for V given x0
            from src.dynamics.simulation.dae_solver import DAESolver, SolverConfig
            cfg = SolverConfig(max_iter_nr=20, tol_nr=1e-8)
            solver = DAESolver(self.system, cfg)
            V_new, ok = solver.solve_algebraic(x0, V)

            data.load_buses = orig_load

            if ok:
                V = V_new
            lam_results.append(float(lam))
            V_results.append(float(abs(V[target_bus])))

        return np.array(lam_results), np.array(V_results)

    # ── Q-V curve at a bus ─────────────────────────────────────────────────
    def qv_curve(
        self,
        V0_init: np.ndarray,
        target_bus: int,
        Q_range: np.ndarray,
        x0: Optional[np.ndarray] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Compute Q-V curve at target_bus by varying reactive injection.

        Sweeps reactive power injection at target_bus and records the
        resulting voltage magnitude. The Q-V curve minimum gives the
        reactive power reserve margin.

        Parameters
        ----------
        V0_init : np.ndarray, complex, shape (nb,)
        target_bus : int
        Q_range : np.ndarray
            Array of reactive power injections (pu) to sweep.
        x0 : np.ndarray, optional

        Returns
        -------
        (Q_arr, V_mag_arr) : ndarrays of same length as Q_range
        """
        if x0 is None:
            x0 = np.zeros(self.system.nx)

        nb = self._nb
        data = self.system.data

        V_results = []
        Q_results = []
        V = V0_init.copy()

        for Q_inj in Q_range:
            # Add reactive injection at target bus
            orig_load = data.load_buses
            load_modified = dict(orig_load)
            if target_bus in load_modified:
                p0, q0 = load_modified[target_bus]
                load_modified[target_bus] = (p0, q0 - Q_inj)  # inject = reduce load
            else:
                load_modified[target_bus] = (0.0, -Q_inj)
            data.load_buses = load_modified

            from src.dynamics.simulation.dae_solver import DAESolver, SolverConfig
            cfg = SolverConfig(max_iter_nr=20, tol_nr=1e-8)
            solver = DAESolver(self.system, cfg)
            V_new, ok = solver.solve_algebraic(x0, V)
            data.load_buses = orig_load

            if ok:
                V = V_new
            Q_results.append(float(Q_inj))
            V_results.append(float(abs(V[target_bus])))

        return np.array(Q_results), np.array(V_results)

    # ── P-V curve plot ─────────────────────────────────────────────────────
    def plot_pv_curves(
        self,
        result: PVCurveResult,
        fig_path: str,
        buses_to_show: Optional[List[int]] = None,
        n_buses: int = 8,
    ) -> None:
        """Plot P-V curves for selected buses.

        Parameters
        ----------
        result : PVCurveResult
        fig_path : str
        buses_to_show : list of int, optional
            Specific bus indices to plot. If None, selects buses with
            largest voltage drop.
        n_buses : int
            Number of buses to show if buses_to_show is None. Default 8.
        """
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            print("matplotlib not available; skipping PV curve plot.")
            return

        nb = result.V_mag.shape[1] if result.V_mag.ndim == 2 else self._nb
        lam = result.lambda_values
        Vm = result.V_mag  # (n_pts, nb)

        # Select buses to show
        if buses_to_show is None:
            if Vm.shape[0] > 1:
                V_drop = Vm[0, :] - np.min(Vm, axis=0)
                sorted_buses = np.argsort(V_drop)[::-1]
            else:
                sorted_buses = np.arange(nb)
            buses_to_show = sorted_buses[:min(n_buses, nb)].tolist()

        fig, ax = plt.subplots(figsize=(10, 6))
        colors = plt.cm.tab10(np.linspace(0, 1, max(len(buses_to_show), 1)))

        for idx, bus in enumerate(buses_to_show):
            if bus < nb and Vm.ndim == 2:
                ax.plot(lam, Vm[:, bus], color=colors[idx], lw=1.8,
                        label=f"Bus {bus}")

        # Mark nose point
        ax.axvline(result.nose_point_lambda, color="red", ls="--", lw=1.5,
                   label=f"Nose: λ = {result.nose_point_lambda:.3f}")

        # Critical bus
        if result.critical_bus in buses_to_show and Vm.ndim == 2:
            ax.scatter(
                [result.nose_point_lambda],
                [float(np.min(Vm[:, result.critical_bus]))],
                c="red", s=80, zorder=10, label=f"Collapse bus {result.critical_bus}"
            )

        ax.axhline(0.9, color="orange", ls=":", lw=1, alpha=0.7, label="0.9 pu limit")
        ax.set_xlabel("Loading Factor λ")
        ax.set_ylabel("Bus Voltage Magnitude (pu)")
        ax.set_title(
            f"P-V Nose Curves — Voltage Collapse at λ = {result.nose_point_lambda:.3f} pu",
            fontsize=11,
        )
        ax.legend(loc="lower left", fontsize=8, ncol=2)
        ax.grid(True, alpha=0.3)
        ax.set_xlim([0, max(float(np.max(lam)) * 1.05, result.nose_point_lambda * 1.1)])
        ax.set_ylim([0, 1.1])

        fig.tight_layout()
        os.makedirs(os.path.dirname(os.path.abspath(fig_path)), exist_ok=True)
        fig.savefig(fig_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
