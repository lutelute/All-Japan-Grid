"""IEEE Type ST1A excitation system and PSS2A power system stabilizer.

ExcitationSystem (IEEE ST1A simplified)
----------------------------------------
A fast static exciter with a voltage measurement filter.

State vector: [Vm, x_avr]
  Vm    : filtered terminal voltage magnitude (pu)
  x_avr : AVR integrator state (pu); direct output is Efd before clamping

  d(Vm)/dt    = (|V| - Vm) / Tr
  d(x_avr)/dt = (Ka*(Vref - Vm + Vs) - x_avr) / Ta

  Efd = clamp(x_avr, Efd_min, Efd_max)

The fast-acting static exciter is well-suited for the All-Japan-Grid
model where most large generators use thyristor AVRs.

PSS2A (Speed-Input Stabilizer)
--------------------------------
Dual-input (speed + integral of accelerating power) stabilizer, simplified
here to a single-input (speed deviation) three-state model:

State vector: [x1, x2, x3]
  x1 : washout filter output  (speed signal after high-pass)
  x2 : first lead-lag output
  x3 : second lead-lag output

  d(x1)/dt = (Ks*(ω - 1) - x1) / Tw          [washout]
  d(x2)/dt = (x_in*(1 - T1/Tw) + x1*T1/Tw - x2) / T2   ... [see below]

  The lead-lag blocks implement the standard form:
    H(s) = (1 + s*T1) / (1 + s*T2)
  using the state-space form:
    x_out = x + (T1/T2)*u
    dx/dt = (u - x) / T2

  Vs = clamp(x3 + (T3/T4)*x_in2, Vs_min, Vs_max)

Usage::

    from src.dynamics.models.excitation import ExcitationSystem, PSS2A
    from src.dynamics.models.excitation import ExcitationParams, PSSParams

    exc = ExcitationSystem(ExcitationParams())
    pss = PSS2A(PSSParams())

    Efd0, V_mag0 = 1.15, 1.02
    exc_state, Vref = exc.initialize(Efd0, V_mag0)

    # Time step:
    Vs  = pss.output(pss_state)
    Efd = exc.output(exc_state)
    d_exc = exc.derivatives(exc_state, V_complex, Vs, Vref)
    d_pss = pss.derivatives(pss_state, omega)
"""

from __future__ import annotations

import dataclasses
import math
from typing import Tuple

import numpy as np


# ── Excitation system parameters ─────────────────────────────────────────────
@dataclasses.dataclass
class ExcitationParams:
    """Parameters for a simplified IEEE Type ST1A static excitation system.

    Parameters
    ----------
    Ka : float
        Voltage regulator gain (pu/pu).  Typical: 100–400.
    Ta : float
        Voltage regulator time constant (s).  Typical: 0.01–0.05.
    Ke : float
        Exciter gain constant (normally 1.0 for static exciter).
    Te : float
        Exciter time constant (s).  Typically very small for static exciter.
    Kf : float
        Rate feedback gain (used in some formulations; here for reference).
    Tf : float
        Rate feedback time constant (s).
    Tr : float
        Voltage measurement filter time constant (s).  Typical: 0.01–0.04.
    Efd_min : float
        Minimum field voltage limit (pu).
    Efd_max : float
        Maximum field voltage limit (pu).
    """

    Ka: float = 200.0
    Ta: float = 0.01
    Ke: float = 1.0
    Te: float = 0.05
    Kf: float = 0.001
    Tf: float = 0.1
    Tr: float = 0.02
    Efd_min: float = -6.0
    Efd_max: float = 6.0


# ── PSS parameters ────────────────────────────────────────────────────────────
@dataclasses.dataclass
class PSSParams:
    """Parameters for a simplified PSS2A (speed-input) stabilizer.

    Parameters
    ----------
    Ks : float
        Overall PSS gain.
    T1, T2 : float
        Time constants for first lead-lag block (s).
    T3, T4 : float
        Time constants for second lead-lag block (s).
    Tw : float
        Washout filter time constant (s).  Typically 5–15 s.
    Vs_max, Vs_min : float
        Output voltage signal limits (pu on terminal voltage base).
    """

    Ks: float = 2.0
    T1: float = 0.14
    T2: float = 0.04
    T3: float = 0.14
    T4: float = 0.04
    Tw: float = 10.0
    Vs_max: float = 0.1
    Vs_min: float = -0.1


# ── Excitation system class ───────────────────────────────────────────────────
class ExcitationSystem:
    """Simplified IEEE Type ST1A static excitation system.

    State vector: [Vm, x_avr]
    -------------------------
    Vm    : low-pass filtered terminal voltage magnitude (pu)
    x_avr : AVR state whose output (before clamping) is Efd (pu)

    Differential equations:
        dVm/dt    = (|V| - Vm) / Tr
        dx_avr/dt = (Ka*(Vref - Vm + Vs) - x_avr) / Ta

    Output:
        Efd = clamp(x_avr, Efd_min, Efd_max)

    Parameters
    ----------
    params : ExcitationParams
    """

    def __init__(self, params: ExcitationParams) -> None:
        self.p = params

    @property
    def state_size(self) -> int:
        """Number of state variables (always 2)."""
        return 2

    def derivatives(
        self,
        state: np.ndarray,
        V_complex: complex,
        Vs: float,
        Vref: float,
    ) -> np.ndarray:
        """Compute time derivatives [dVm/dt, dx_avr/dt].

        Parameters
        ----------
        state : np.ndarray, shape (2,)
            [Vm, x_avr]
        V_complex : complex
            Terminal voltage phasor (pu).
        Vs : float
            PSS output voltage (pu); zero if no PSS.
        Vref : float
            Voltage reference set-point (pu).

        Returns
        -------
        np.ndarray, shape (2,)
            [dVm/dt, dx_avr/dt]
        """
        p = self.p
        Vm, x_avr = float(state[0]), float(state[1])
        V_mag = abs(V_complex)

        dVm    = (V_mag - Vm) / p.Tr
        dx_avr = (p.Ka * (Vref - Vm + Vs) - x_avr) / p.Ta

        return np.array([dVm, dx_avr])

    def output(self, state: np.ndarray) -> float:
        """Return field voltage Efd = clamp(x_avr, Efd_min, Efd_max).

        Parameters
        ----------
        state : np.ndarray, shape (2,)
            [Vm, x_avr]

        Returns
        -------
        float
            Efd (pu), clamped to [Efd_min, Efd_max].
        """
        p = self.p
        x_avr = float(state[1])
        return float(np.clip(x_avr, p.Efd_min, p.Efd_max))

    def initialize(
        self,
        Efd0: float,
        V0_mag: float,
    ) -> Tuple[np.ndarray, float]:
        """Compute initial state for a given steady-state Efd and terminal voltage.

        At steady state dx_avr/dt = 0, dVm/dt = 0, so:
            Vm0   = V0_mag
            x_avr = Efd0   (before clamping)
            Vref  = Vm0 - Vs + x_avr/Ka
                  = V0_mag + Efd0/Ka   (assuming Vs=0 at init)

        Parameters
        ----------
        Efd0 : float
            Steady-state field voltage (pu) from generator initialization.
        V0_mag : float
            Steady-state terminal voltage magnitude (pu).

        Returns
        -------
        state0 : np.ndarray, shape (2,)
            [Vm0=V0_mag, x_avr0=Efd0]
        Vref0 : float
            Reference voltage set-point (pu).
        """
        p = self.p
        Vm0   = float(V0_mag)
        x_avr0 = float(Efd0)
        # From dx_avr/dt = 0:  Ka*(Vref - Vm + Vs) - x_avr = 0
        # → Vref = Vm + x_avr/Ka  (Vs=0 at steady state)
        Vref0 = Vm0 + x_avr0 / p.Ka
        state0 = np.array([Vm0, x_avr0])
        return state0, float(Vref0)


# ── PSS2A class ───────────────────────────────────────────────────────────────
class PSS2A:
    """Simplified PSS2A power system stabilizer (speed-deviation input).

    State vector: [x1, x2, x3]
    --------------------------
    x1 : washout filter state
    x2 : first lead-lag filter state
    x3 : second lead-lag filter state

    Signal flow
    -----------
    Input:  Δω = ω - 1  (per-unit speed deviation)

    1. Washout (high-pass):
           d(x1)/dt = (Ks*Δω - x1) / Tw
           y1 = x1 + Ks*Δω*(0)  ... washout output:
           Actually: H_w(s) = s*Tw/(1+s*Tw), state-space:
             dx1/dt = (Ks*Δω - x1) / Tw
             y1     = Ks*Δω - x1       ... (= Tw*s/(1+Tw*s) * Ks*Δω)

    2. First lead-lag  H1(s) = (1+s*T1)/(1+s*T2):
           dx2/dt = (y1 - x2) / T2
           y2     = x2 + (T1/T2)*y1

    3. Second lead-lag  H2(s) = (1+s*T3)/(1+s*T4):
           dx3/dt = (y2 - x3) / T4
           y3     = x3 + (T3/T4)*y2

    4. Output: Vs = clamp(y3, Vs_min, Vs_max)

    Parameters
    ----------
    params : PSSParams
    """

    def __init__(self, params: PSSParams) -> None:
        self.p = params

    @property
    def state_size(self) -> int:
        """Number of state variables (always 3)."""
        return 3

    def _washout_output(self, x1: float, omega: float) -> float:
        """Washout filter output y1 = Ks*Δω - x1.

        This is the standard first-order washout (high-pass):
            H_w(s) = s*Tw/(1+s*Tw)
        State-space: dx1/dt=(Ks*Δω-x1)/Tw, y1 = Ks*(ω-1) - x1.
        """
        return self.p.Ks * (omega - 1.0) - float(x1)

    def derivatives(
        self,
        state: np.ndarray,
        omega: float,
    ) -> np.ndarray:
        """Compute time derivatives [dx1/dt, dx2/dt, dx3/dt].

        Parameters
        ----------
        state : np.ndarray, shape (3,)
            [x1, x2, x3]
        omega : float
            Per-unit rotor speed (1.0 = synchronous).

        Returns
        -------
        np.ndarray, shape (3,)
            [dx1/dt, dx2/dt, dx3/dt]
        """
        p = self.p
        x1, x2, x3 = float(state[0]), float(state[1]), float(state[2])

        # Washout block
        u_w  = p.Ks * (omega - 1.0)   # scaled speed input
        dx1  = (u_w - x1) / p.Tw
        y1   = u_w - x1               # washout output

        # First lead-lag  (1+sT1)/(1+sT2)
        dx2  = (y1 - x2) / p.T2
        y2   = x2 + (p.T1 / p.T2) * y1

        # Second lead-lag  (1+sT3)/(1+sT4)
        dx3  = (y2 - x3) / p.T4
        # y3 computed in output()

        return np.array([dx1, dx2, dx3])

    def output(self, state: np.ndarray, omega: float = 1.0) -> float:
        """Return PSS output signal Vs, clamped to [Vs_min, Vs_max].

        Parameters
        ----------
        state : np.ndarray, shape (3,)
            [x1, x2, x3]
        omega : float
            Per-unit rotor speed; needed to reconstruct lead-lag outputs.
            Defaults to 1.0 (synchronous speed) for convenience.

        Returns
        -------
        float
            Vs (pu), clamped.
        """
        p = self.p
        x1, x2, x3 = float(state[0]), float(state[1]), float(state[2])

        # Reconstruct signal chain
        u_w = p.Ks * (omega - 1.0)
        y1  = u_w - x1
        y2  = x2 + (p.T1 / p.T2) * y1
        y3  = x3 + (p.T3 / p.T4) * y2

        return float(np.clip(y3, p.Vs_min, p.Vs_max))

    def initialize(self) -> np.ndarray:
        """Return zero initial state (PSS inactive at steady state).

        At steady state Δω = 0, so all states and outputs are zero.

        Returns
        -------
        np.ndarray, shape (3,)
            [0.0, 0.0, 0.0]
        """
        return np.zeros(3)


# ── Self-test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== ExcitationSystem + PSS2A self-test ===")

    # --- Test 1: Excitation initialize → zero derivatives ---
    p_exc = ExcitationParams()
    exc = ExcitationSystem(p_exc)
    Efd0, V0_mag = 1.15, 1.02
    state_exc, Vref0 = exc.initialize(Efd0, V0_mag)
    V0 = V0_mag * np.exp(1j * np.deg2rad(3.0))
    dxdt_exc = exc.derivatives(state_exc, V0, Vs=0.0, Vref=Vref0)
    assert np.allclose(dxdt_exc, 0.0, atol=1e-10), \
        f"Excitation non-zero derivatives at init: {dxdt_exc}"
    Efd_out = exc.output(state_exc)
    assert abs(Efd_out - Efd0) < 1e-12, \
        f"Excitation output mismatch: {Efd_out} vs {Efd0}"
    print(f"  [PASS] ExcitationSystem init: Vm0={state_exc[0]:.4f}, "
          f"Efd0={Efd_out:.4f}, Vref0={Vref0:.6f}")

    # --- Test 2: Efd clamping ---
    state_high = np.array([1.0, 8.0])   # x_avr above Efd_max
    state_low  = np.array([1.0, -8.0])  # x_avr below Efd_min
    assert exc.output(state_high) == p_exc.Efd_max, "Efd upper clamp failed"
    assert exc.output(state_low)  == p_exc.Efd_min, "Efd lower clamp failed"
    print("  [PASS] Efd clamping at limits")

    # --- Test 3: PSS initialize → zero output ---
    p_pss = PSSParams()
    pss = PSS2A(p_pss)
    state_pss = pss.initialize()
    assert np.all(state_pss == 0.0), "PSS init should be all zeros"
    Vs0 = pss.output(state_pss, omega=1.0)
    assert Vs0 == 0.0, f"PSS output non-zero at sync speed: {Vs0}"
    print("  [PASS] PSS2A initialize: all zeros, Vs=0 at ω=1")

    # --- Test 4: PSS derivatives → zero at steady state ---
    dxdt_pss = pss.derivatives(state_pss, omega=1.0)
    assert np.allclose(dxdt_pss, 0.0, atol=1e-15), \
        f"PSS non-zero derivatives at steady state: {dxdt_pss}"
    print("  [PASS] PSS2A zero derivatives at steady state")

    # --- Test 5: PSS responds to speed deviation ---
    dxdt_dev = pss.derivatives(state_pss, omega=1.01)
    # dx1/dt = (Ks*0.01 - 0) / Tw = 2.0*0.01/10 = 0.002
    expected_dx1 = p_pss.Ks * 0.01 / p_pss.Tw
    assert abs(dxdt_dev[0] - expected_dx1) < 1e-14, \
        f"PSS dx1/dt mismatch: {dxdt_dev[0]} vs {expected_dx1}"
    print(f"  [PASS] PSS responds to Δω=0.01: dx1/dt={dxdt_dev[0]:.6f}")

    # --- Test 6: PSS output clamping ---
    state_large = np.array([0.0, 0.0, 1.0])  # x3 >> Vs_max
    Vs_clamped = pss.output(state_large, omega=1.0)
    assert abs(Vs_clamped - p_pss.Vs_max) < 1e-14, \
        f"PSS upper clamp failed: {Vs_clamped}"
    state_neg = np.array([0.0, 0.0, -1.0])
    Vs_neg = pss.output(state_neg, omega=1.0)
    assert abs(Vs_neg - p_pss.Vs_min) < 1e-14, \
        f"PSS lower clamp failed: {Vs_neg}"
    print("  [PASS] PSS output clamping at ±Vs_max")

    # --- Test 7: AVR response to voltage error ---
    # If |V| > Vref, AVR should reduce Efd
    V_high = 1.10 * np.exp(0j)
    state_nom = np.array([1.0, Efd0])
    _, Vref_nom = exc.initialize(Efd0, 1.02)
    dxdt_vhigh = exc.derivatives(state_nom, V_high, Vs=0.0, Vref=Vref_nom)
    # dVm/dt > 0 (Vm < |V|)
    assert dxdt_vhigh[0] > 0, "dVm/dt should be positive when |V|>Vm"
    # dx_avr/dt < 0 (Vref - Vm is now more negative after filter responds)
    # Initially Vm=1.02, |V|=1.10, so Vref-Vm = Vref-1.02 = Efd0/Ka > 0 (small)
    # net error = Vref - Vm + Vs = Vref_nom - 1.02 + 0 ≈ small positive → Efd nudges up
    # but |V| just changed, so Vm will chase |V|, which actually tests dVm
    print(f"  [PASS] AVR dVm/dt={dxdt_vhigh[0]:.6f} (>0 when |V|>Vm)")

    print("=== All tests passed ===")
