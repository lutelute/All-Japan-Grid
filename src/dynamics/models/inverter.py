"""
Grid-Following (GFL) and Grid-Forming (GFM) Inverter Models
============================================================
Park convention used throughout:
  Vd = VD*sin(δ) - VQ*cos(δ)
  Vq = VD*cos(δ) + VQ*sin(δ)
  I_net_complex = (Iq - j*Id) * exp(j*δ)

All quantities in per-unit (100 MVA base unless overridden by S_rated_mva).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


# ---------------------------------------------------------------------------
# Grid-Following Inverter (GFL) — PLL + current-mode control
# ---------------------------------------------------------------------------

@dataclass
class GFLParams:
    """Parameters for a grid-following inverter with PLL."""

    # Filter (LC output filter, series RL approximation)
    Lf: float = 0.05      # Filter inductance [pu]
    Rf: float = 0.005     # Filter resistance  [pu]

    # PLL PI gains
    Kp_pll: float = 40.0
    Ki_pll: float = 800.0

    # Current controller PI gains (d-axis, q-axis)
    Kp_d: float = 1.0
    Ki_d: float = 20.0
    Kp_q: float = 1.0
    Ki_q: float = 20.0

    # Power references [pu on S_rated_mva base]
    P_ref: float = 0.0
    Q_ref: float = 0.0

    # Current limit [pu]
    I_max: float = 1.2

    # Ratings / identification
    S_rated_mva: float = 100.0
    bus_id: int = 0
    name: str = ""


class GFLInverter:
    """
    Grid-Following Inverter — 6 state variables.

    State vector (index):
        0: theta_pll   — PLL phase angle [rad]
        1: omega_pll   — PLL angular frequency error integrator output [pu] (integrator state)
        2: xi_d        — d-axis current PI integrator [pu]
        3: xi_q        — q-axis current PI integrator [pu]
        4: Id          — d-axis output current [pu]
        5: Iq          — q-axis output current [pu]

    PLL structure:
        pll_err   = Im[V_complex * exp(-j*theta_pll)]   (imaginary part of rotated voltage)
        omega_pll = omega_s_nom + Kp_pll*pll_err + Ki_pll*integral(pll_err)
                  = 1.0 (pu) + Kp_pll*pll_err + omega_pll_integrator
        d(theta_pll)/dt      = omega_pll
        d(omega_pll_int)/dt  = Ki_pll * pll_err

    Current references (P/Q outer loop, simplified):
        Id_ref = P_ref / max(|V|, 0.01)
        Iq_ref = -Q_ref / max(|V|, 0.01)

    Current controller:
        d(xi_d)/dt = Id_ref - Id
        d(xi_q)/dt = Iq_ref - Iq
        Vd_cmd = Kp_d*(Id_ref - Id) + Ki_d*xi_d + Vd - omega_pll*Lf*Iq
        Vq_cmd = Kp_q*(Iq_ref - Iq) + Ki_q*xi_q + Vq + omega_pll*Lf*Id

    Filter dynamics (RL equivalent):
        d(Id)/dt = (Vd_cmd - Rf*Id + omega_pll*Lf*Iq - Vd) / Lf
        d(Iq)/dt = (Vq_cmd - Rf*Iq - omega_pll*Lf*Id - Vq) / Lf
    """

    state_size: int = 6

    def __init__(self, params: GFLParams) -> None:
        self.p = params

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pll_decompose(
        self, theta_pll: float, omega_pll_int: float, V_complex: complex
    ) -> tuple[float, float, float, float, float]:
        """
        Returns (pll_err, omega_pll, Vd_pll, Vq_pll, V_mag).
        """
        # Rotate terminal voltage by -theta_pll
        V_rot = V_complex * cmath_exp(-1j * theta_pll)
        pll_err = V_rot.imag          # Im[V*exp(-j*theta)] → zero at lock

        # PLL frequency (pu); nominal is 1.0
        omega_pll = 1.0 + self.p.Kp_pll * pll_err + omega_pll_int

        # dq voltages in PLL frame (Park with theta_pll)
        VD = V_complex.real
        VQ = V_complex.imag
        Vd = VD * math.sin(theta_pll) - VQ * math.cos(theta_pll)
        Vq = VD * math.cos(theta_pll) + VQ * math.sin(theta_pll)

        V_mag = abs(V_complex)
        return pll_err, omega_pll, Vd, Vq, V_mag

    def _current_references(self, V_mag: float) -> tuple[float, float]:
        """Id_ref, Iq_ref from P/Q references."""
        denom = max(V_mag, 0.01)
        Id_ref = self.p.P_ref / denom
        Iq_ref = -self.p.Q_ref / denom

        # Current limiter (circular)
        I_ref_mag = math.hypot(Id_ref, Iq_ref)
        if I_ref_mag > self.p.I_max:
            scale = self.p.I_max / I_ref_mag
            Id_ref *= scale
            Iq_ref *= scale

        return Id_ref, Iq_ref

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def derivatives(self, state: np.ndarray, V_complex: complex) -> np.ndarray:
        """
        Compute time derivatives of the 6-element state vector.

        Parameters
        ----------
        state : np.ndarray, shape (6,)
            [theta_pll, omega_pll_int, xi_d, xi_q, Id, Iq]
        V_complex : complex
            Terminal bus voltage phasor [pu], DQ frame (V = VD + j*VQ)

        Returns
        -------
        np.ndarray, shape (6,)
        """
        theta_pll, omega_pll_int, xi_d, xi_q, Id, Iq = state

        pll_err, omega_pll, Vd, Vq, V_mag = self._pll_decompose(
            theta_pll, omega_pll_int, V_complex
        )
        Id_ref, Iq_ref = self._current_references(V_mag)

        # Current controller voltage commands
        Vd_cmd = (
            self.p.Kp_d * (Id_ref - Id)
            + self.p.Ki_d * xi_d
            + Vd
            - omega_pll * self.p.Lf * Iq
        )
        Vq_cmd = (
            self.p.Kp_q * (Iq_ref - Iq)
            + self.p.Ki_q * xi_q
            + Vq
            + omega_pll * self.p.Lf * Id
        )

        # Derivatives
        d_theta = omega_pll                                          # [rad/s] in pu time
        d_omega_int = self.p.Ki_pll * pll_err
        d_xi_d = Id_ref - Id
        d_xi_q = Iq_ref - Iq
        d_Id = (Vd_cmd - self.p.Rf * Id + omega_pll * self.p.Lf * Iq - Vd) / self.p.Lf
        d_Iq = (Vq_cmd - self.p.Rf * Iq - omega_pll * self.p.Lf * Id - Vq) / self.p.Lf

        return np.array([d_theta, d_omega_int, d_xi_d, d_xi_q, d_Id, d_Iq])

    def current_injection(self, state: np.ndarray, V_complex: complex) -> complex:
        """
        Current injected INTO the network at the terminal bus [pu].

        Convention: I_net = (Iq - j*Id) * exp(j*theta_pll)
        """
        theta_pll = state[0]
        Id = state[4]
        Iq = state[5]
        return (Iq - 1j * Id) * cmath_exp(1j * theta_pll)

    def initialize(self, P_gen: float, Q_gen: float, V_complex: complex) -> np.ndarray:
        """
        Compute steady-state initial conditions.

        Parameters
        ----------
        P_gen, Q_gen : float
            Generated active / reactive power [pu on system base]
        V_complex : complex
            Terminal voltage phasor at t=0

        Returns
        -------
        np.ndarray, shape (6,)
            [theta_pll, omega_pll_int, xi_d, xi_q, Id, Iq]
        """
        # PLL locks to terminal voltage angle
        theta_pll = math.atan2(V_complex.imag, V_complex.real)

        V_mag = abs(V_complex)
        denom = max(V_mag, 0.01)

        # Scale from system base to device base if needed
        scale = 100.0 / max(self.p.S_rated_mva, 1.0)
        Id_ss = P_gen * scale / denom
        Iq_ss = -Q_gen * scale / denom

        # Integrators: at steady state, PI outputs hold the correct command
        # omega_pll_int = 0 (PLL locked, no residual error)
        # xi_d, xi_q: from filter steady-state (Lf terms zero at omega=1, Rf small)
        # We leave them at zero; the simulation will settle quickly.
        omega_pll_int = 0.0
        xi_d = 0.0
        xi_q = 0.0

        return np.array([theta_pll, omega_pll_int, xi_d, xi_q, Id_ss, Iq_ss])


# ---------------------------------------------------------------------------
# Grid-Forming Inverter (GFM) — droop control (virtual synchronous)
# ---------------------------------------------------------------------------

@dataclass
class GFMParams:
    """Parameters for a grid-forming inverter with P-ω / Q-V droop."""

    # Output filter
    Lf: float = 0.05      # [pu]
    Rf: float = 0.005     # [pu]

    # Droop coefficients
    mp: float = 0.05      # P-ω droop [pu/pu]  (Δω = -mp * ΔP)
    nq: float = 0.05      # Q-V droop [pu/pu]  (ΔV = -nq * ΔQ)

    # Nominal setpoints
    omega_ref: float = 1.0   # [pu]
    V_ref: float = 1.0       # [pu]

    # Power references (may be updated externally)
    P_ref: float = 0.0
    Q_ref: float = 0.0

    # Measurement filter time constant
    tau_f: float = 0.01   # [s] (in pu time, same if omega_s=1)

    # Ratings / identification
    S_rated_mva: float = 100.0
    bus_id: int = 0
    name: str = ""


class GFMInverter:
    """
    Grid-Forming Inverter — 4 state variables.

    State vector (index):
        0: theta     — Internal voltage angle [rad]
        1: omega     — Angular frequency [pu]
        2: P_filt    — Filtered active power [pu]
        3: Q_filt    — Filtered reactive power [pu]

    Dynamics:
        Instantaneous power at terminal:
            S_inst = V_complex * conj(I_inj)   (where I_inj is from this inverter)

        Measurement filters:
            d(P_filt)/dt = (P_inst - P_filt) / tau_f
            d(Q_filt)/dt = (Q_inst - Q_filt) / tau_f

        Droop laws:
            omega   = omega_ref - mp * (P_filt - P_ref)
            V_out   = V_ref   - nq * (Q_filt - Q_ref)

        Phase integrator (θ̇ = ω_ref * (ω - 1) maps pu frequency to rad/s):
            d(theta)/dt = omega_ref * (omega - 1)

        Internal voltage source (behind filter impedance):
            E_internal = V_out * exp(j*theta)

        Current injection (voltage source behind Zf = Rf + j*omega*Lf):
            I_net = (E_internal - V_terminal) / (Rf + j*omega*Lf)
    """

    state_size: int = 4

    def __init__(self, params: GFMParams) -> None:
        self.p = params

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    def _instantaneous_power(
        self, state: np.ndarray, V_complex: complex
    ) -> tuple[float, float]:
        """Return (P_inst, Q_inst) at the terminal bus."""
        I_inj = self.current_injection(state, V_complex)
        S = V_complex * I_inj.conjugate()
        return S.real, S.imag

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def derivatives(
        self,
        state: np.ndarray,
        V_complex: complex,
        P_ref: float | None = None,
        Q_ref: float | None = None,
    ) -> np.ndarray:
        """
        Compute time derivatives of the 4-element state vector.

        Parameters
        ----------
        state : np.ndarray, shape (4,)
            [theta, omega, P_filt, Q_filt]
        V_complex : complex
            Terminal voltage phasor [pu]
        P_ref, Q_ref : float, optional
            Override the droop setpoints stored in params.

        Returns
        -------
        np.ndarray, shape (4,)
        """
        theta, omega, P_filt, Q_filt = state

        p_ref = P_ref if P_ref is not None else self.p.P_ref
        q_ref = Q_ref if Q_ref is not None else self.p.Q_ref

        P_inst, Q_inst = self._instantaneous_power(state, V_complex)

        # Measurement filters
        d_P_filt = (P_inst - P_filt) / self.p.tau_f
        d_Q_filt = (Q_inst - Q_filt) / self.p.tau_f

        # Droop: omega and V_out are algebraic (no state for omega here;
        # the omega state IS updated via theta integrator)
        omega_droop = self.p.omega_ref - self.p.mp * (P_filt - p_ref)

        # Phase integrator: maps pu frequency deviation to angle rate [rad/s]
        # Using omega_ref as the nominal angular frequency multiplier
        d_theta = self.p.omega_ref * (omega_droop - 1.0)

        # omega state follows droop algebraically; we store it for diagnostics
        # but d(omega)/dt just tracks the droop output through a simple update.
        # Here we treat omega as a filtered state with fast (tau→0) dynamics:
        d_omega = (omega_droop - omega) / self.p.tau_f

        return np.array([d_theta, d_omega, d_P_filt, d_Q_filt])

    def current_injection(self, state: np.ndarray, V_complex: complex) -> complex:
        """
        Current injected INTO the network [pu].

        Models the GFM as an ideal voltage source E behind filter impedance Zf.
            E = V_out * exp(j*theta)
            I_net = (E - V_terminal) / Zf
        """
        theta, omega, P_filt, Q_filt = state

        V_out = self.p.V_ref - self.p.nq * (Q_filt - self.p.Q_ref)
        V_out = max(V_out, 0.0)     # voltage floor

        E_internal = V_out * cmath_exp(1j * theta)
        Zf = complex(self.p.Rf, omega * self.p.Lf)

        if abs(Zf) < 1e-12:
            return 0j

        return (E_internal - V_complex) / Zf

    def initialize(
        self, P_gen: float, Q_gen: float, V_complex: complex
    ) -> np.ndarray:
        """
        Steady-state initialisation.

        Parameters
        ----------
        P_gen, Q_gen : float
            Initial active / reactive generation [pu on system base]
        V_complex : complex
            Terminal voltage phasor

        Returns
        -------
        np.ndarray, shape (4,)
            [theta, omega, P_filt, Q_filt]
        """
        # At steady state: P_filt = P_gen, Q_filt = Q_gen (scaled to device base)
        scale = 100.0 / max(self.p.S_rated_mva, 1.0)
        P_ss = P_gen * scale
        Q_ss = Q_gen * scale

        # Droop: omega_ss ≈ omega_ref (nominal load), V_out_ss ≈ V_ref
        omega_ss = self.p.omega_ref - self.p.mp * (P_ss - self.p.P_ref)

        # Internal angle: set so that E_internal aligns with terminal voltage
        # at nominal output.  Simple approximation: theta = angle(V_complex)
        theta_ss = math.atan2(V_complex.imag, V_complex.real)

        return np.array([theta_ss, omega_ss, P_ss, Q_ss])


# ---------------------------------------------------------------------------
# Module-level helper (replaces cmath.exp for brevity)
# ---------------------------------------------------------------------------

def cmath_exp(x: complex) -> complex:
    """Return e^x for a complex x via Euler's formula."""
    return math.exp(x.real) * complex(math.cos(x.imag), math.sin(x.imag))
