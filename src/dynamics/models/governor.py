"""Governor and turbine models for All-Japan-Grid dynamics simulation.

Two models are provided:

GovernorModel (IEEEG1-like steam turbine governor)
---------------------------------------------------
A three-state model covering the speed relay, servomotor (valve), and
steam chest / turbine.  Suitable for coal, nuclear, LNG, and oil generators.

    State: [x1, x2, x3]
      x1 : speed relay (PI) output
      x2 : servo / valve position
      x3 : turbine steam power

    dx1/dt = ((ω_ref - ω)/R  - x1) / T1    [speed relay]
    dx2/dt = (x1 - x2) / T2                 [valve servomotor]
    dx3/dt = (x2 - x3) / T3                 [steam chest]

    Pm = Pm0 + x3   (clamped to [Pm_min, Pm_max])

HydroGovernor (simplified Pelton/Francis)
------------------------------------------
A two-state model of a hydraulic turbine governor with temporary droop
feedback.  Suitable for hydro generators.

    State: [x_servo, x_gate]
      x_servo : governor/servo output (target gate position)
      x_gate  : actual gate position (with water-starting inertia lag)

    dx_servo/dt = (-(ω - ω_ref)/Rp - x_servo) / Tg
    dx_gate/dt  = (x_servo - x_gate) / Tr

    Pm = Pm0 * x_gate   (simplified linear turbine model)

Both classes share the same interface convention:
    derivatives(state, omega, omega_ref=1.0) → ndarray
    output(state, Pm0)                       → Pm (pu, clamped)
    initialize(Pm0)                          → zero state (steady state)

All quantities in pu on machine base (S_rated_mva), 100 MVA system base.

Usage::

    from src.dynamics.models.governor import GovernorParams, GovernorModel
    from src.dynamics.models.governor import HydroGovernorParams, HydroGovernor

    gov = GovernorModel(GovernorParams())
    state0 = gov.initialize(Pm0=0.85)        # all zeros at steady state
    dxdt   = gov.derivatives(state0, omega=1.002)
    Pm     = gov.output(state0, Pm0=0.85)

    # For hydro:
    hgov = HydroGovernor(HydroGovernorParams())
    hstate0 = hgov.initialize(Pm0=0.70)
    dxdt_h  = hgov.derivatives(hstate0, omega=0.999)
    Pm_h    = hgov.output(hstate0, Pm0=0.70)
"""

from __future__ import annotations

import dataclasses
import math
from typing import Tuple

import numpy as np


# ── Steam governor parameters ─────────────────────────────────────────────────
@dataclasses.dataclass
class GovernorParams:
    """Parameters for an IEEEG1-like steam turbine governor.

    Parameters
    ----------
    R : float
        Permanent droop (pu speed / pu power).  1/R is the regulation factor.
        Typical: 0.04–0.06.
    T1 : float
        Speed relay time constant (s).  Typical: 0.05–0.20.
    T2 : float
        Valve servomotor time constant (s).  Typical: 0.15–0.35.
    T3 : float
        Steam chest time constant (s).  Typical: 0.30–0.60.
    Dt : float
        Turbine damping factor (pu/pu).  Typically 0 for simplicity.
    Pm_max : float
        Maximum mechanical power (pu on machine base).
    Pm_min : float
        Minimum mechanical power (pu on machine base).
    """

    R: float     = 0.05
    T1: float    = 0.10
    T2: float    = 0.25
    T3: float    = 0.45
    Dt: float    = 0.0
    Pm_max: float = 1.05
    Pm_min: float = 0.0


# ── Steam governor class ──────────────────────────────────────────────────────
class GovernorModel:
    """IEEEG1-like three-state steam turbine governor.

    State vector: [x1, x2, x3]
    --------------------------
    x1 : speed relay state (deviation of valve demand from equilibrium)
    x2 : servo/valve state (valve position deviation from Pm0/Pm_max equilibrium)
    x3 : turbine power state (steam power deviation from Pm0)

    Differential equations:
        dx1/dt = ((ω_ref - ω)/R  - x1) / T1
        dx2/dt = (x1 - x2) / T2
        dx3/dt = (x2 - x3) / T3

    Mechanical power output:
        Pm = clamp(Pm0 + x3, Pm_min, Pm_max)

    At steady state (ω = ω_ref):
        x1 = x2 = x3 = 0  →  Pm = Pm0.

    Parameters
    ----------
    params : GovernorParams

    Examples
    --------
    >>> p = GovernorParams(R=0.05, T1=0.1, T2=0.25, T3=0.45)
    >>> gov = GovernorModel(p)
    >>> state0 = gov.initialize(Pm0=0.80)
    >>> all(state0 == 0.0)
    True
    >>> gov.output(state0, Pm0=0.80)
    0.80
    >>> dxdt = gov.derivatives(state0, omega=1.0)
    >>> np.allclose(dxdt, 0.0)
    True
    """

    def __init__(self, params: GovernorParams) -> None:
        self.p = params

    @property
    def state_size(self) -> int:
        """Number of state variables (always 3)."""
        return 3

    def derivatives(
        self,
        state: np.ndarray,
        omega: float,
        omega_ref: float = 1.0,
    ) -> np.ndarray:
        """Compute time derivatives [dx1/dt, dx2/dt, dx3/dt].

        Parameters
        ----------
        state : np.ndarray, shape (3,)
            [x1, x2, x3]
        omega : float
            Per-unit rotor speed (1.0 = synchronous).
        omega_ref : float
            Speed reference (pu); typically 1.0 (nominal frequency).

        Returns
        -------
        np.ndarray, shape (3,)
            [dx1/dt, dx2/dt, dx3/dt]
        """
        p = self.p
        x1, x2, x3 = float(state[0]), float(state[1]), float(state[2])

        # Speed error → valve demand
        speed_error = (omega_ref - omega) / p.R
        dx1 = (speed_error - x1) / p.T1

        # Servomotor / valve
        dx2 = (x1 - x2) / p.T2

        # Steam chest / turbine power
        dx3 = (x2 - x3) / p.T3

        return np.array([dx1, dx2, dx3])

    def output(self, state: np.ndarray, Pm0: float) -> float:
        """Return mechanical power Pm = clamp(Pm0 + x3, Pm_min, Pm_max).

        Parameters
        ----------
        state : np.ndarray, shape (3,)
            [x1, x2, x3]
        Pm0 : float
            Nominal mechanical power at the operating point (pu).

        Returns
        -------
        float
            Mechanical power (pu), clamped to [Pm_min, Pm_max].
        """
        p = self.p
        x3 = float(state[2])
        Pm = Pm0 + x3
        return float(np.clip(Pm, p.Pm_min, p.Pm_max))

    def initialize(self, Pm0: float) -> np.ndarray:
        """Return zero initial state (steady state at ω = ω_ref).

        At steady state, speed error is zero, so all states are zero and
        Pm = Pm0 + 0 = Pm0 as required.

        Parameters
        ----------
        Pm0 : float
            Initial mechanical power (pu).  Unused here but kept for API
            consistency with HydroGovernor.

        Returns
        -------
        np.ndarray, shape (3,)
            [0.0, 0.0, 0.0]
        """
        return np.zeros(3)


# ── Hydro governor parameters ─────────────────────────────────────────────────
@dataclasses.dataclass
class HydroGovernorParams:
    """Parameters for a simplified hydraulic turbine governor.

    Based on the IEEE Working Group model (HYGOV / simplified Francis).

    Parameters
    ----------
    Tw : float
        Water starting time (s).  Typical: 0.5–3.0.
        Longer Tw means more water inertia → slower response.
    Tg : float
        Governor time constant (s).  Typical: 0.2–1.0.
    Rp : float
        Permanent droop (pu/pu).  Typical: 0.04–0.06.
    Rt : float
        Temporary droop (pu/pu).  Typical: 0.2–0.5.
        Improves transient stability by providing temporary speed drop compensation.
    Tr : float
        Reset / dashpot time constant (s).  Typical: 2.0–10.0.
    Pm_max : float
        Maximum gate (power) limit (pu).  Typically 1.0.
    Pm_min : float
        Minimum gate (power) limit (pu).  Typically 0.0.
    """

    Tw: float     = 1.0
    Tg: float     = 0.5
    Rp: float     = 0.05
    Rt: float     = 0.38
    Tr: float     = 5.0
    Pm_max: float = 1.0
    Pm_min: float = 0.0


# ── Hydro governor class ──────────────────────────────────────────────────────
class HydroGovernor:
    """Simplified hydraulic turbine governor with temporary droop.

    State vector: [x_servo, x_gate]
    --------------------------------
    x_servo : governor/servomotor output — target gate opening deviation (pu)
    x_gate  : actual gate position deviation from steady-state opening (pu)

    Differential equations:
        dx_servo/dt = (-(ω - ω_ref)/Rp - x_servo) / Tg
        dx_gate/dt  = (x_servo - x_gate) / Tr

    Mechanical power (linear turbine model):
        gate     = clamp(1.0 + x_gate, Pm_min, Pm_max)
        Pm       = Pm0 * gate

    The temporary droop acts through x_gate which feeds back via Tg.

    Physical interpretation:
        x_servo  — integrating action of the governor on the valve
        x_gate   — dashpot / reset element capturing transient overshoot

    At steady state (ω = ω_ref):
        x_servo = x_gate = 0  →  gate = 1.0  →  Pm = Pm0.

    Parameters
    ----------
    params : HydroGovernorParams

    Examples
    --------
    >>> p = HydroGovernorParams()
    >>> hgov = HydroGovernor(p)
    >>> s0 = hgov.initialize(Pm0=0.70)
    >>> hgov.output(s0, Pm0=0.70)
    0.70
    >>> np.allclose(hgov.derivatives(s0, omega=1.0), 0.0)
    True
    """

    def __init__(self, params: HydroGovernorParams) -> None:
        self.p = params

    @property
    def state_size(self) -> int:
        """Number of state variables (always 2)."""
        return 2

    def derivatives(
        self,
        state: np.ndarray,
        omega: float,
        omega_ref: float = 1.0,
    ) -> np.ndarray:
        """Compute time derivatives [dx_servo/dt, dx_gate/dt].

        Parameters
        ----------
        state : np.ndarray, shape (2,)
            [x_servo, x_gate]
        omega : float
            Per-unit rotor speed (1.0 = synchronous).
        omega_ref : float
            Speed reference (pu); typically 1.0.

        Returns
        -------
        np.ndarray, shape (2,)
            [dx_servo/dt, dx_gate/dt]
        """
        p = self.p
        x_servo = float(state[0])
        x_gate  = float(state[1])

        delta_omega = omega - omega_ref

        # Governor/servomotor: integrating speed error + temporary droop feedback
        # The temporary droop x_gate feeds back through Rp (linearized):
        dx_servo = (-(delta_omega) / p.Rp - x_servo) / p.Tg

        # Dashpot / gate position (with transient droop via slow reset Tr)
        dx_gate = (x_servo - x_gate) / p.Tr

        return np.array([dx_servo, dx_gate])

    def output(self, state: np.ndarray, Pm0: float) -> float:
        """Return mechanical power using a linear gate-power relationship.

        gate_pos = clamp(1.0 + x_gate, Pm_min, Pm_max)
        Pm       = Pm0 * gate_pos

        This approximates the linear region of the turbine power-gate curve.
        For more accuracy a nonlinear (quadratic) curve can be substituted.

        Parameters
        ----------
        state : np.ndarray, shape (2,)
            [x_servo, x_gate]
        Pm0 : float
            Nominal (steady-state) mechanical power (pu on machine base).

        Returns
        -------
        float
            Mechanical power (pu), clamped implicitly by gate limits.
        """
        p = self.p
        x_gate = float(state[1])
        gate = float(np.clip(1.0 + x_gate, p.Pm_min, p.Pm_max))
        return float(Pm0 * gate)

    def initialize(self, Pm0: float) -> np.ndarray:
        """Return zero initial state (steady state at ω = ω_ref).

        At steady state, speed error is zero and gate deviation is zero:
            x_servo = 0  →  Pm = Pm0 * (1 + 0) = Pm0.

        Parameters
        ----------
        Pm0 : float
            Initial mechanical power (pu).  Unused here; kept for API
            consistency with GovernorModel.

        Returns
        -------
        np.ndarray, shape (2,)
            [0.0, 0.0]
        """
        return np.zeros(2)


# ── Self-test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Governor self-test ===")

    # --- Test 1: Steam governor steady state ---
    p_gov = GovernorParams()
    gov = GovernorModel(p_gov)
    Pm0 = 0.85
    state0 = gov.initialize(Pm0)
    assert np.all(state0 == 0.0), "Steam governor init must be zero"
    dxdt0 = gov.derivatives(state0, omega=1.0)
    assert np.allclose(dxdt0, 0.0, atol=1e-15), \
        f"Non-zero derivatives at steady state: {dxdt0}"
    Pm_out = gov.output(state0, Pm0)
    assert abs(Pm_out - Pm0) < 1e-14, \
        f"Steam governor output mismatch: {Pm_out} vs {Pm0}"
    print(f"  [PASS] Steam governor steady state: Pm={Pm_out:.4f}")

    # --- Test 2: Steam governor response to underspeed ---
    # omega < 1 → speed_error > 0 → x1 increases → more steam
    dxdt_slow = gov.derivatives(state0, omega=0.99)
    speed_error = (1.0 - 0.99) / p_gov.R
    expected_dx1 = (speed_error - 0.0) / p_gov.T1
    assert abs(dxdt_slow[0] - expected_dx1) < 1e-14, \
        f"Steam dx1/dt mismatch: {dxdt_slow[0]} vs {expected_dx1}"
    assert dxdt_slow[0] > 0, "dx1/dt should be positive at underspeed"
    print(f"  [PASS] Steam governor underspeed response: dx1/dt={dxdt_slow[0]:.6f}")

    # --- Test 3: Steam governor Pm clamping ---
    state_high = np.array([0.0, 0.0, 0.25])  # x3 = 0.25 → Pm0+0.25 = 1.10 > Pm_max
    Pm_high = gov.output(state_high, Pm0=0.85)
    assert abs(Pm_high - p_gov.Pm_max) < 1e-14, \
        f"Pm upper clamp failed: {Pm_high}"
    state_neg = np.array([0.0, 0.0, -0.9])  # Pm0-0.9 < 0 = Pm_min
    Pm_neg = gov.output(state_neg, Pm0=0.85)
    assert abs(Pm_neg - p_gov.Pm_min) < 1e-14, \
        f"Pm lower clamp failed: {Pm_neg}"
    print("  [PASS] Steam governor Pm clamping at limits")

    # --- Test 4: Hydro governor steady state ---
    p_hydro = HydroGovernorParams()
    hgov = HydroGovernor(p_hydro)
    Pm0_h = 0.70
    hstate0 = hgov.initialize(Pm0_h)
    assert np.all(hstate0 == 0.0), "Hydro governor init must be zero"
    dxdt_h0 = hgov.derivatives(hstate0, omega=1.0)
    assert np.allclose(dxdt_h0, 0.0, atol=1e-15), \
        f"Hydro non-zero derivatives at steady state: {dxdt_h0}"
    Pm_h_out = hgov.output(hstate0, Pm0_h)
    assert abs(Pm_h_out - Pm0_h) < 1e-14, \
        f"Hydro governor output mismatch: {Pm_h_out} vs {Pm0_h}"
    print(f"  [PASS] Hydro governor steady state: Pm={Pm_h_out:.4f}")

    # --- Test 5: Hydro governor response to overspeed ---
    # omega > 1 → delta_omega > 0 → dx_servo < 0 → gate closes → less power
    dxdt_fast = hgov.derivatives(hstate0, omega=1.01)
    expected_dxs = (-(0.01) / p_hydro.Rp - 0.0) / p_hydro.Tg
    assert abs(dxdt_fast[0] - expected_dxs) < 1e-14, \
        f"Hydro dx_servo/dt mismatch: {dxdt_fast[0]} vs {expected_dxs}"
    assert dxdt_fast[0] < 0, "dx_servo/dt should be negative at overspeed"
    print(f"  [PASS] Hydro governor overspeed response: dx_servo/dt={dxdt_fast[0]:.6f}")

    # --- Test 6: Hydro gate clamping ---
    hstate_open = np.array([0.0, 0.5])   # x_gate=0.5 → gate=1.5 > Pm_max=1.0
    Pm_open = hgov.output(hstate_open, Pm0=0.70)
    assert abs(Pm_open - 0.70 * p_hydro.Pm_max) < 1e-14, \
        f"Hydro upper clamp failed: {Pm_open}"
    hstate_shut = np.array([0.0, -2.0])  # gate=-1.0 → clamp to Pm_min=0
    Pm_shut = hgov.output(hstate_shut, Pm0=0.70)
    assert abs(Pm_shut - 0.70 * p_hydro.Pm_min) < 1e-14, \
        f"Hydro lower clamp failed: {Pm_shut}"
    print("  [PASS] Hydro gate clamping at limits")

    # --- Test 7: Custom parameters ---
    p_custom = GovernorParams(R=0.04, T1=0.15, T2=0.30, T3=0.50, Pm_max=1.10)
    gov_custom = GovernorModel(p_custom)
    state_c = gov_custom.initialize(0.9)
    Pm_c = gov_custom.output(state_c, 0.9)
    assert abs(Pm_c - 0.9) < 1e-14, f"Custom governor output: {Pm_c}"
    print(f"  [PASS] Custom GovernorParams (R={p_custom.R}, Pm_max={p_custom.Pm_max})")

    print("=== All tests passed ===")
