"""DAE system assembly for All-Japan-Grid power system dynamics.

Full DAE:
    dx/dt = f(x, V)   [differential: generator/controller states]
    0 = g(x, V)       [algebraic: network power balance]

where x = [delta1,omega1,Ed'1,Eq'1, ..., delta_ng,omega_ng,Ed'_ng,Eq'_ng,
           AVR_states..., Gov_states..., Inv_states...]
      V = [VD1+jVQ1, ..., VD_nb+jVQ_nb]  (complex bus voltages)

Park transformation convention (PSAT/Milano):
    Vd = V.real*sin(delta) - V.imag*cos(delta)
    Vq = V.real*cos(delta) + V.imag*sin(delta)

    I_net = (Iq - 1j*Id) * exp(1j*delta)

Stator algebraic (generator current positive OUT of machine):
    det = Ra**2 + Xd_p*Xq_p
    Id  = ( Ra*(Ed_p - Vd) + Xq_p*(Eq_p - Vq) ) / det
    Iq  = (-Xd_p*(Ed_p - Vd) + Ra*(Eq_p - Vq) ) / det
    Pe  = Vd*Id + Vq*Iq
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from src.dynamics.models.sync_generator import SyncGenerator, SGState


# ── Constants ─────────────────────────────────────────────────────────────────
_OMEGA_S: float = 2.0 * math.pi * 50.0  # rad/s — east Japan nominal


# ── SystemData ────────────────────────────────────────────────────────────────
@dataclass
class SystemData:
    """Container for all static data needed by the DAE system.

    Attributes
    ----------
    generators : list of SyncGenerator
        4th-order synchronous generator objects with their parameters.
    gen_bus_idx : list of int
        Network bus index for each generator (len == ng).
    Y_bus : scipy.sparse complex matrix, shape (nb, nb)
        Network admittance matrix in complex form.
    nb : int
        Number of network buses.
    ng : int
        Number of synchronous generators.
    load_buses : dict {bus_idx: (P_load_pu, Q_load_pu)}
        Constant-power load injections (positive = demand).
    slack_bus : int
        Index of the slack (reference) bus; default 0.
    sbase_mva : float
        System MVA base.
    V0_slack : complex
        Initial complex voltage at the slack bus (used to fix algebraic eq).
    Efd : list of float
        Steady-state field voltages (one per generator); set after init.
    Pm : list of float
        Steady-state mechanical powers (one per generator); set after init.
    """

    generators: List[SyncGenerator]
    gen_bus_idx: List[int]
    Y_bus: sp.spmatrix
    nb: int
    ng: int
    load_buses: Dict[int, Tuple[float, float]] = field(default_factory=dict)
    slack_bus: int = 0
    sbase_mva: float = 100.0
    V0_slack: complex = 1.0 + 0j
    Efd: List[float] = field(default_factory=list)
    Pm: List[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Normalize Efd / Pm to plain Python lists for safe indexing
        efd = self.Efd
        if efd is None or (hasattr(efd, '__len__') and len(efd) == 0):
            self.Efd = [0.0] * self.ng
        elif hasattr(efd, 'tolist'):
            self.Efd = efd.tolist()
        pm = self.Pm
        if pm is None or (hasattr(pm, '__len__') and len(pm) == 0):
            self.Pm = [0.0] * self.ng
        elif hasattr(pm, 'tolist'):
            self.Pm = pm.tolist()


# ── Helper functions ──────────────────────────────────────────────────────────
def pack_state(generators: List[SyncGenerator],
               states: Optional[List[np.ndarray]] = None) -> np.ndarray:
    """Pack per-generator state arrays into a single flat vector.

    Parameters
    ----------
    generators : list of SyncGenerator
        Generator objects (used only for count when states is None).
    states : list of np.ndarray or None
        Each element is shape (4,): [delta, omega, Ed_p, Eq_p].
        If None, returns zeros (uninitialized).

    Returns
    -------
    np.ndarray, shape (4 * ng,)
    """
    ng = len(generators)
    x = np.zeros(4 * ng)
    if states is not None:
        for i, s in enumerate(states):
            x[4 * i: 4 * i + 4] = s
    else:
        # Default: omega = 1 for all generators, angles = 0
        for i in range(ng):
            x[4 * i + 1] = 1.0
    return x


def unpack_state(x: np.ndarray, ng: int) -> List[Tuple[float, float, float, float]]:
    """Unpack the flat state vector into per-generator tuples.

    Parameters
    ----------
    x : np.ndarray, shape (4*ng,)
        Flat state vector.
    ng : int
        Number of generators.

    Returns
    -------
    list of (delta, omega, Ed_p, Eq_p) tuples, length ng
    """
    result = []
    for i in range(ng):
        seg = x[4 * i: 4 * i + 4]
        result.append((float(seg[0]), float(seg[1]), float(seg[2]), float(seg[3])))
    return result


def compute_load_current(load_buses: Dict[int, Tuple[float, float]],
                          V: np.ndarray) -> np.ndarray:
    """Compute complex load current for each network bus.

    Load current is withdrawn from the bus (positive = demand):
        I_load[k] = (P_load - j*Q_load) / conj(V[k])

    Parameters
    ----------
    load_buses : dict {bus_idx: (P_pu, Q_pu)}
        Constant-power loads in pu (positive = demand).
    V : np.ndarray, complex, shape (nb,)
        Current bus voltages.

    Returns
    -------
    np.ndarray, complex, shape (nb,)
        Load current injection (withdrawal); zero for non-load buses.
    """
    nb = len(V)
    I_load = np.zeros(nb, dtype=complex)
    for bus, (P, Q) in load_buses.items():
        Vk = V[bus]
        Vk_abs = abs(Vk)
        if Vk_abs < 1e-10:
            continue
        I_load[bus] = complex(P, -Q) / Vk.conjugate()
    return I_load


# ── DAE System ────────────────────────────────────────────────────────────────
class DAESystem:
    """Full DAE system for multi-machine power system dynamics.

    Encapsulates both differential equations f(x, V) for generator states
    and algebraic equations g(x, V) = 0 for network power balance.

    State layout: x[4*i : 4*i+4] = [delta_i, omega_i, Ed'_i, Eq'_i]
    Voltage layout: V (complex, nb)  ↔  real vector y = [Re(V); Im(V)]
    """

    def __init__(self, system_data: SystemData) -> None:
        self.data = system_data
        self._ng = system_data.ng
        self._nb = system_data.nb
        # Cache Y_bus as dense complex for small systems; sparse for large
        if self._nb <= 200:
            self._Y_dense: Optional[np.ndarray] = np.array(
                system_data.Y_bus.toarray(), dtype=complex
            )
        else:
            self._Y_dense = None

    # ── Sizes ──────────────────────────────────────────────────────────────
    @property
    def nx(self) -> int:
        """Total differential state size (4 per generator)."""
        return 4 * self._ng

    @property
    def nv(self) -> int:
        """Total algebraic size (2*nb: real + imag parts of bus voltages)."""
        return 2 * self._nb

    # ── Internal: stator solve for generator i ─────────────────────────────
    def _gen_currents(
        self, i: int, delta: float, omega: float, Ed_p: float, Eq_p: float,
        V_bus: complex
    ) -> Tuple[float, float, float, complex]:
        """Compute (Id, Iq, Pe, I_net) for generator i.

        Returns
        -------
        Id, Iq : float (machine base pu)
        Pe     : float electrical power (machine base pu)
        I_net  : complex current injection into network (system base pu)
        """
        gen = self.data.generators[i]
        p = gen.p

        # Park transform
        Vd, Vq = SGState.dq_from_net_voltage(V_bus, delta)

        # Stator algebraic solve
        Id, Iq = SGState.solve_stator(Ed_p, Eq_p, Vd, Vq, p.Ra, p.Xd_p, p.Xq_p)

        # Electrical power (machine base)
        Pe = SGState.electrical_power(Vd, Vq, Id, Iq)

        # Current injection into network (system base)
        I_machine = (Iq - 1j * Id) * np.exp(1j * delta)
        I_net = I_machine * p.mva_ratio

        return Id, Iq, Pe, I_net

    # ── Differential equations f(x, V) ────────────────────────────────────
    def f(self, x: np.ndarray, V: np.ndarray) -> np.ndarray:
        """Differential equations dx/dt = f(x, V).

        Parameters
        ----------
        x : np.ndarray, shape (nx,)
            Generator state vector.
        V : np.ndarray, complex, shape (nb,)
            Complex bus voltages.

        Returns
        -------
        np.ndarray, shape (nx,)
            Time derivatives [ddelta, domega, dEd_p, dEq_p] per generator.
        """
        dxdt = np.zeros(self.nx)
        ng = self._ng
        data = self.data

        for i in range(ng):
            base = 4 * i
            delta = float(x[base])
            omega = float(x[base + 1])
            Ed_p = float(x[base + 2])
            Eq_p = float(x[base + 3])

            gen = data.generators[i]
            p = gen.p
            bus = data.gen_bus_idx[i]
            V_bus = complex(V[bus])

            Id, Iq, Pe, _ = self._gen_currents(i, delta, omega, Ed_p, Eq_p, V_bus)

            # Swing equation in pu rotor speed convention
            Pm = data.Pm[i]
            Efd = data.Efd[i]

            ddelta = p.omega_s * (omega - 1.0)
            domega = (Pm - Pe - p.D * (omega - 1.0)) / (2.0 * p.H)
            dEd_p = (-Ed_p - (p.Xq - p.Xq_p) * Iq) / p.Tq0_p
            dEq_p = (Efd - Eq_p + (p.Xd - p.Xd_p) * Id) / p.Td0_p

            dxdt[base] = ddelta
            dxdt[base + 1] = domega
            dxdt[base + 2] = dEd_p
            dxdt[base + 3] = dEq_p

        return dxdt

    # ── Algebraic equations g(x, V) = 0 ────────────────────────────────────
    def g(self, x: np.ndarray, V: np.ndarray) -> np.ndarray:
        """Algebraic equations 0 = g(x, V).

        Network power balance in rectangular complex form:
            I_mismatch = Y_bus @ V - I_gen + I_load
        Slack bus rows are replaced by voltage fixing equations.

        Parameters
        ----------
        x : np.ndarray, shape (nx,)
        V : np.ndarray, complex, shape (nb,)

        Returns
        -------
        np.ndarray, real, shape (2*nb,)
            [Re(I_mismatch); Im(I_mismatch)] with slack bus rows modified.
        """
        nb = self._nb
        data = self.data

        # Y_bus @ V — network current leaving each bus via lines
        if self._Y_dense is not None:
            I_net_flow = self._Y_dense @ V
        else:
            I_net_flow = data.Y_bus @ V

        # Generator current injections (into the network)
        I_gen = np.zeros(nb, dtype=complex)
        for i in range(self._ng):
            base = 4 * i
            delta = float(x[base])
            omega = float(x[base + 1])
            Ed_p = float(x[base + 2])
            Eq_p = float(x[base + 3])
            bus = data.gen_bus_idx[i]
            _, _, _, I_inj = self._gen_currents(i, delta, omega, Ed_p, Eq_p, V[bus])
            I_gen[bus] += I_inj

        # Load current (withdrawal from bus)
        I_load = compute_load_current(data.load_buses, V)

        # Mismatch: Y*V - (I_gen - I_load) should be zero
        I_mismatch = I_net_flow - I_gen + I_load

        # Build real residual [Re; Im]
        residual = np.zeros(2 * nb)
        residual[:nb] = I_mismatch.real
        residual[nb:] = I_mismatch.imag

        # Slack bus: fix V[slack] = V0_slack
        slack = data.slack_bus
        V_slack_err = V[slack] - data.V0_slack
        residual[slack] = V_slack_err.real
        residual[nb + slack] = V_slack_err.imag

        return residual

    # ── Jacobian dg/dV (2nb × 2nb) ─────────────────────────────────────────
    def jacobian_g_v(self, x: np.ndarray, V: np.ndarray) -> np.ndarray:
        """Jacobian ∂g/∂V in real form, (2*nb × 2*nb).

        Decompose V into [VD; VQ] and compute analytic Y_bus part,
        then add generator Norton-equivalent contributions numerically.

        Parameters
        ----------
        x : np.ndarray, shape (nx,)
        V : np.ndarray, complex, shape (nb,)

        Returns
        -------
        np.ndarray, real, shape (2*nb, 2*nb)
        """
        nb = self._nb
        data = self.data

        # ── Analytic part from Y_bus ──────────────────────────────────────
        # g = Y*V - I_gen(x,V) + I_load(V)
        # ∂(Y*V)/∂[VD;VQ] in real form:
        #   If Y = G + jB, then (Y*V)_k = Σ_m (G_km + jB_km)(VD_m + jVQ_m)
        #   Re part: Σ_m G_km*VD_m - B_km*VQ_m
        #   Im part: Σ_m B_km*VD_m + G_km*VQ_m
        # In block form: J_Ybus = [G, -B; B, G]
        if self._Y_dense is not None:
            Y = self._Y_dense
        else:
            Y = np.array(data.Y_bus.toarray(), dtype=complex)
        G = Y.real
        B = Y.imag

        J = np.zeros((2 * nb, 2 * nb))
        J[:nb, :nb] = G
        J[:nb, nb:] = -B
        J[nb:, :nb] = B
        J[nb:, nb:] = G

        # ── Numeric correction for generator Norton current ───────────────
        # Each generator's current injection depends on V[bus_i]; add dI/dV
        eps = 1e-7
        for i in range(self._ng):
            base = 4 * i
            delta = float(x[base])
            omega = float(x[base + 1])
            Ed_p = float(x[base + 2])
            Eq_p = float(x[base + 3])
            bus = data.gen_bus_idx[i]

            # Compute base injection at nominal V
            _, _, _, I0 = self._gen_currents(i, delta, omega, Ed_p, Eq_p, V[bus])

            for part in range(2):  # 0=real, 1=imag perturbation
                dV = eps if part == 0 else 1j * eps
                _, _, _, I1 = self._gen_currents(
                    i, delta, omega, Ed_p, Eq_p, V[bus] + dV
                )
                dI = (I1 - I0) / (eps if part == 0 else eps)

                col = bus + part * nb
                # Subtract from J (because g = Y*V - I_gen + I_load)
                J[bus, col] -= dI.real
                J[nb + bus, col] -= dI.imag

        # ── Load current contribution ─────────────────────────────────────
        # For constant-power loads: I_load = (P - jQ)/conj(V)
        # ∂I_load/∂VD = (P - jQ) * ∂(1/conj(V))/∂VD
        # conj(V) = VD - jVQ → ∂/∂VD = 1 → ∂(1/conj(V))/∂VD = -1/conj(V)^2
        for bus, (P, Q) in data.load_buses.items():
            Vk = V[bus]
            Vc = Vk.conjugate()
            Vc2 = Vc * Vc
            if abs(Vc2) < 1e-20:
                continue
            S_load = complex(P, -Q)
            # ∂I_load/∂VD_bus = -S_load / Vc^2 * ∂Vc/∂VD = -S_load/Vc^2 (∂VD-jVQ/∂VD=1)
            dI_dVD = -S_load / Vc2
            # ∂I_load/∂VQ_bus = -S_load / Vc^2 * ∂Vc/∂VQ = -S_load/Vc^2 * (-j) = j*S_load/Vc^2
            dI_dVQ = 1j * S_load / Vc2
            # Add to rows for this bus (sign: g includes +I_load)
            J[bus, bus] += dI_dVD.real
            J[nb + bus, bus] += dI_dVD.imag
            J[bus, nb + bus] += dI_dVQ.real
            J[nb + bus, nb + bus] += dI_dVQ.imag

        # ── Slack bus rows ─────────────────────────────────────────────────
        slack = data.slack_bus
        J[slack, :] = 0.0
        J[nb + slack, :] = 0.0
        J[slack, slack] = 1.0
        J[nb + slack, nb + slack] = 1.0

        return J

    # ── Jacobian dg/dx (2nb × nx) ──────────────────────────────────────────
    def jacobian_gx(self, x: np.ndarray, V: np.ndarray) -> np.ndarray:
        """Jacobian ∂g/∂x via numerical finite differences, (2*nb × nx).

        Parameters
        ----------
        x : np.ndarray, shape (nx,)
        V : np.ndarray, complex, shape (nb,)

        Returns
        -------
        np.ndarray, real, shape (2*nb, nx)
        """
        nx = self.nx
        nv2 = 2 * self._nb
        J = np.zeros((nv2, nx))
        eps = 1e-7
        g0 = self.g(x, V)

        for j in range(nx):
            x_pert = x.copy()
            x_pert[j] += eps
            g1 = self.g(x_pert, V)
            J[:, j] = (g1 - g0) / eps

        return J

    # ── Jacobian df/dx (nx × nx) ───────────────────────────────────────────
    def jacobian_fx(self, x: np.ndarray, V: np.ndarray) -> np.ndarray:
        """Jacobian ∂f/∂x via numerical finite differences, (nx × nx).

        Parameters
        ----------
        x : np.ndarray, shape (nx,)
        V : np.ndarray, complex, shape (nb,)

        Returns
        -------
        np.ndarray, real, shape (nx, nx)
        """
        nx = self.nx
        J = np.zeros((nx, nx))
        eps = 1e-7
        f0 = self.f(x, V)

        for j in range(nx):
            x_pert = x.copy()
            x_pert[j] += eps
            f1 = self.f(x_pert, V)
            J[:, j] = (f1 - f0) / eps

        return J

    # ── Jacobian df/dV (nx × 2nb) ─────────────────────────────────────────
    def jacobian_fv(self, x: np.ndarray, V: np.ndarray) -> np.ndarray:
        """Jacobian ∂f/∂V via numerical finite differences, (nx × 2*nb).

        Parameters
        ----------
        x : np.ndarray, shape (nx,)
        V : np.ndarray, complex, shape (nb,)

        Returns
        -------
        np.ndarray, real, shape (nx, 2*nb)
        """
        nx = self.nx
        nb = self._nb
        J = np.zeros((nx, 2 * nb))
        eps = 1e-7
        f0 = self.f(x, V)

        # VD perturbations (real part)
        for j in range(nb):
            V_pert = V.copy()
            V_pert[j] += eps
            f1 = self.f(x, V_pert)
            J[:, j] = (f1 - f0) / eps

        # VQ perturbations (imag part)
        for j in range(nb):
            V_pert = V.copy()
            V_pert[j] += 1j * eps
            f1 = self.f(x, V_pert)
            J[:, nb + j] = (f1 - f0) / eps

        return J

    # ── Linearization ─────────────────────────────────────────────────────
    def linearize(
        self, x0: np.ndarray, V0: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Linearize the DAE around operating point (x0, V0).

        Full linearized form:
            Δẋ = A * Δx + B * ΔV_real
            0  = C * Δx + D * ΔV_real

        where ΔV_real = [ΔVD; ΔVQ] (length 2*nb).

        Also returns the reduced state matrix:
            A_red = A - B @ inv(D) @ C   (nx × nx)

        Parameters
        ----------
        x0 : np.ndarray, shape (nx,)
            Operating point state.
        V0 : np.ndarray, complex, shape (nb,)
            Operating point voltage.

        Returns
        -------
        A : np.ndarray, shape (nx, nx)   — ∂f/∂x
        B : np.ndarray, shape (nx, 2*nb) — ∂f/∂V_real
        C : np.ndarray, shape (2*nb, nx) — ∂g/∂x
        D : np.ndarray, shape (2*nb, 2*nb) — ∂g/∂V_real
        """
        A = self.jacobian_fx(x0, V0)
        B = self.jacobian_fv(x0, V0)
        C = self.jacobian_gx(x0, V0)
        D = self.jacobian_g_v(x0, V0)
        return A, B, C, D

    def reduced_state_matrix(
        self, x0: np.ndarray, V0: np.ndarray
    ) -> np.ndarray:
        """Compute reduced state matrix A_red = A - B @ inv(D) @ C.

        Uses sparse LU of D for numerical stability.

        Parameters
        ----------
        x0 : np.ndarray, shape (nx,)
        V0 : np.ndarray, complex, shape (nb,)

        Returns
        -------
        np.ndarray, shape (nx, nx)
        """
        A, B, C, D = self.linearize(x0, V0)
        # Solve D @ X = C  →  X = inv(D) @ C, shape (2nb, nx)
        # D is (2nb, 2nb), C is (2nb, nx), lu.solve(C) returns (2nb, nx)
        D_sp = sp.csc_matrix(D)
        try:
            lu = spla.splu(D_sp)
            D_inv_C = lu.solve(C.astype(float))  # (2nb, nx)
        except Exception:
            # Fallback: column-wise pseudo-inverse solve
            D_dense = D_sp.toarray()
            D_inv_C = np.linalg.lstsq(D_dense, C, rcond=None)[0]
        A_red = A - B @ D_inv_C  # (nx,2nb)@(2nb,nx) = (nx,nx)
        return A_red
