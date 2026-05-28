"""
Load Models: ZIP Load and Simplified Induction Motor
=====================================================
Park convention:
  Vd = VD*sin(δ) - VQ*cos(δ)
  Vq = VD*cos(δ) + VQ*sin(δ)
  I_net_complex = (Iq - j*Id) * exp(j*δ)

All quantities in per-unit (100 MVA system base).
Current withdrawal convention: load withdraws positive current, so
    I_load = (P - j*Q) / conj(V)    [for positive P consumed]
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


# ---------------------------------------------------------------------------
# ZIP Load (algebraic — no differential states)
# ---------------------------------------------------------------------------

@dataclass
class ZIPParams:
    """
    Parameters for a polynomial (ZIP) load model.

    P and Q consumption are expressed as:
        P = P0 * [ Zp*(V/V0)^2 + Ip*(V/V0) + Pp ]
        Q = Q0 * [ Zq*(V/V0)^2 + Iq_*(V/V0) + Pq ]

    ZIP fractions must sum to 1 for each axis (enforced softly at runtime).
    """

    # Nominal load (pu on 100 MVA base)
    P0: float = 0.0    # Active power demand [pu]
    Q0: float = 0.0    # Reactive power demand [pu]

    # ZIP fractions for P  (Z: constant impedance, I: constant current, P: constant power)
    Zp: float = 0.0
    Ip: float = 0.0
    Pp: float = 1.0

    # ZIP fractions for Q
    Zq: float = 0.0
    Iq_frac: float = 0.0   # renamed to avoid clash with complex I symbol
    Pq: float = 1.0

    # Nominal (base) voltage for ZIP model
    V0: float = 1.0    # [pu]

    # Identification
    bus_id: int = 0
    name: str = ""


class ZIPLoad:
    """
    Algebraic ZIP load model — zero differential states.

    Positive P0, Q0 represent load (withdrawal from the bus).
    """

    state_size: int = 0

    def __init__(self, params: ZIPParams) -> None:
        self.p = params

    def power(self, V_complex: complex) -> tuple[float, float]:
        """
        Compute instantaneous load consumption (P, Q) [pu].

        Parameters
        ----------
        V_complex : complex
            Terminal voltage phasor [pu]

        Returns
        -------
        (P, Q) : tuple of float
            Active and reactive power consumed [pu].
        """
        V_mag = abs(V_complex)
        vr = V_mag / max(self.p.V0, 1e-6)    # voltage ratio

        P = self.p.P0 * (self.p.Zp * vr ** 2 + self.p.Ip * vr + self.p.Pp)
        Q = self.p.Q0 * (self.p.Zq * vr ** 2 + self.p.Iq_frac * vr + self.p.Pq)

        return P, Q

    def current_withdrawal(self, V_complex: complex) -> complex:
        """
        Current withdrawn from the bus by the load [pu].

        I_load = (P - j*Q) / conj(V_complex)

        A positive value represents current flowing INTO the load (out of the bus).

        Parameters
        ----------
        V_complex : complex
            Terminal voltage phasor [pu]

        Returns
        -------
        complex
            Load current phasor [pu]
        """
        P, Q = self.power(V_complex)
        V_conj = V_complex.conjugate()
        if abs(V_conj) < 1e-9:
            return 0j
        return complex(P, -Q) / V_conj


# ---------------------------------------------------------------------------
# Simplified Induction Motor (3 differential states)
# ---------------------------------------------------------------------------

@dataclass
class MotorParams:
    """
    Parameters for a third-order induction motor model.

    Circuit parameters are in per-unit on the motor's own base (S_rated_mva).
    """

    # Equivalent circuit [pu on motor base]
    Rs: float = 0.01     # Stator resistance
    Xs: float = 0.1      # Stator leakage reactance
    Xm: float = 3.0      # Magnetising reactance
    Rr: float = 0.02     # Rotor resistance
    Xr: float = 0.05     # Rotor leakage reactance

    # Inertia constant [s]
    H: float = 0.5

    # Rating / identification
    S_rated_mva: float = 10.0
    bus_id: int = 0
    name: str = ""


class InductionMotor:
    """
    Simplified third-order induction motor model.

    State vector (index):
        0: Ed_m   — d-axis transient EMF [pu]
        1: Eq_m   — q-axis transient EMF [pu]
        2: slip   — rotor slip s = (ωs - ωr) / ωs  [pu, positive for motoring]

    Derived circuit parameters (computed from MotorParams at construction):
        X  = Xs + Xm                          total open-circuit reactance
        X' = Xs + Xm*Xr / (Xm + Xr)          transient (short-circuit) reactance
        T0'= (Xr + Xm) / (ωs * Rr)           open-circuit transient time constant [s]

    Stator algebraic equations (steady-state stator, neglect Rs for simplicity):
        V_complex ≈ Ed_m + j*Eq_m + (Rs + j*X') * I_stator
        → solve for I_stator = (V - E') / (Rs + j*X')

    Rotor EMF dynamics (with stator frame convention):
        dEd_m/dt = -slip*ωs*Eq_m - (Ed_m - (X - X')*Iq_m) / T0'
        dEq_m/dt =  slip*ωs*Ed_m - (Eq_m + (X - X')*Id_m) / T0'

    Mechanical dynamics:
        Tm = Tm0 * (1 - slip)^2      [constant-torque load adjusted for speed]
        Te = Ed_m*Id_m + Eq_m*Iq_m
        d(slip)/dt = (Tm - Te) / (2*H)

    Note: ωs = 2π*50 = 314.159 rad/s.  All pu time uses ωs as base.
    """

    state_size: int = 3

    # System angular frequency [rad/s]
    OMEGA_S: float = 2.0 * math.pi * 50.0

    def __init__(self, params: MotorParams) -> None:
        self.p = params

        # Derived parameters
        p = params
        self.X_total = p.Xs + p.Xm               # open-circuit reactance
        denom_xp = p.Xm + p.Xr
        self.X_prime = p.Xs + (p.Xm * p.Xr) / max(denom_xp, 1e-9)   # transient reactance
        self.T0_prime = (p.Xr + p.Xm) / (self.OMEGA_S * max(p.Rr, 1e-9))  # open-circuit T' [s]
        self.dX = self.X_total - self.X_prime     # X - X' (used in EMF eqs)

        # Impedance behind which stator current flows
        self._Zs_prime = complex(p.Rs, self.X_prime)

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    def _stator_current(
        self, state: np.ndarray, V_complex: complex
    ) -> tuple[float, float, complex]:
        """
        Solve stator algebraic equation:
            I_motor = (V - E') / (Rs + j*X')
        where E' = Ed_m + j*Eq_m (transient EMF in stator DQ frame).

        Returns (Id_m, Iq_m, I_complex).
        """
        Ed_m, Eq_m, slip = state
        E_prime = complex(Ed_m, Eq_m)

        if abs(self._Zs_prime) < 1e-12:
            I_complex = 0j
        else:
            I_complex = (V_complex - E_prime) / self._Zs_prime

        # In the convention used here, V = VD + jVQ (DQ frame)
        # Motor current: Id_m ≈ -I_complex.imag,  Iq_m ≈ I_complex.real
        # (mapping from complex to dq for motor convention)
        Id_m = -I_complex.imag
        Iq_m = I_complex.real
        return Id_m, Iq_m, I_complex

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def derivatives(
        self,
        state: np.ndarray,
        V_complex: complex,
        Tm0: float,
    ) -> np.ndarray:
        """
        Compute time derivatives of the 3-element state vector.

        Parameters
        ----------
        state : np.ndarray, shape (3,)
            [Ed_m, Eq_m, slip]
        V_complex : complex
            Terminal bus voltage phasor [pu]
        Tm0 : float
            Mechanical torque at rated speed [pu on motor base].
            The actual torque is: Tm = Tm0 * (1 - slip)^2

        Returns
        -------
        np.ndarray, shape (3,)
            [dEd_m, dEq_m, d_slip]
        """
        Ed_m, Eq_m, slip = state

        Id_m, Iq_m, _ = self._stator_current(state, V_complex)

        T0p = max(self.T0_prime, 1e-6)
        ws  = self.OMEGA_S

        # Rotor EMF dynamics
        dEd_m = (-slip * ws * Eq_m - (Ed_m - self.dX * Iq_m)) / T0p
        dEq_m = ( slip * ws * Ed_m - (Eq_m + self.dX * Id_m)) / T0p

        # Electrical torque (Te = P in pu at unit speed)
        Te = Ed_m * Id_m + Eq_m * Iq_m

        # Mechanical torque (speed-squared load characteristic)
        speed = max(1.0 - slip, 0.0)      # rotor speed in pu
        Tm = Tm0 * speed ** 2

        # Swing equation: d(slip)/dt = (Tm - Te) / (2H)
        d_slip = (Tm - Te) / max(2.0 * self.p.H, 1e-6)

        return np.array([dEd_m, dEq_m, d_slip])

    def current_withdrawal(self, state: np.ndarray, V_complex: complex) -> complex:
        """
        Current withdrawn from the bus by the motor [pu].

        Positive current = current flowing from bus into motor (load convention).

        Parameters
        ----------
        state : np.ndarray, shape (3,)
        V_complex : complex

        Returns
        -------
        complex
            Motor terminal current [pu on system base]
        """
        _, _, I_motor_complex = self._stator_current(state, V_complex)

        # Scale from motor base to system base
        scale = self.p.S_rated_mva / 100.0
        return I_motor_complex * scale

    def initialize(
        self, P: float, Q: float, V_complex: complex
    ) -> np.ndarray:
        """
        Compute steady-state initial conditions for the motor.

        Parameters
        ----------
        P, Q : float
            Initial active / reactive power consumed [pu on system base]
        V_complex : complex
            Terminal voltage phasor [pu]

        Returns
        -------
        np.ndarray, shape (3,)
            [Ed_m_0, Eq_m_0, slip_0]
        """
        # Scale P, Q from system base to motor base
        scale = 100.0 / max(self.p.S_rated_mva, 1.0)
        P_m = P * scale
        Q_m = Q * scale

        # Stator current (load withdrawal: I = (P - jQ) / conj(V))
        V_conj = V_complex.conjugate()
        if abs(V_conj) < 1e-9:
            I_m = 0j
        else:
            I_m = complex(P_m, -Q_m) / V_conj

        # Back-calculate transient EMF: E' = V - Zs' * I
        E_prime = V_complex - self._Zs_prime * I_m
        Ed_m_0 = E_prime.real
        Eq_m_0 = E_prime.imag

        # Slip at steady state: use torque balance
        # Te_0 = P_m (electrical torque ≈ input power at slip→0)
        Te_0 = P_m
        # From Tm = Tm0*(1-s)^2 = Te at s≈0, Tm0 ≈ Te_0
        # Steady-state slip: small positive value for motoring
        # Using approximate formula for squirrel-cage: s ≈ Rr*Te / (Xm^2 * Im^2) (simplified)
        # Here we use a conservative initial guess
        slip_0 = self.p.Rr * Te_0 / max(self.p.Xm ** 2 * abs(I_m) ** 2, 1e-6)
        slip_0 = max(0.0, min(slip_0, 0.3))    # clamp to realistic range

        return np.array([Ed_m_0, Eq_m_0, slip_0])
