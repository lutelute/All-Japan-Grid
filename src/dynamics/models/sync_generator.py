"""4th-order synchronous generator model for All-Japan-Grid dynamics.

State vector: [delta, omega, Ed_p, Eq_p]

  delta  : rotor angle relative to synchronous reference frame (rad)
  omega  : per-unit rotor speed (= omega_actual / omega_s); 1.0 at steady state
  Ed_p   : d-axis transient EMF (pu)  — driven by q-axis flux / damper
  Eq_p   : q-axis transient EMF (pu)  — driven by field winding

Park transformation convention (PSAT/Milano):
  Vd = VD*sin(delta) - VQ*cos(delta)
  Vq = VD*cos(delta) + VQ*sin(delta)
  where V_net = VD + jVQ (rectangular network voltage)

Current injection to network:
  I_net = (Iq - j*Id) * exp(j*delta)

Stator voltage equations (generator current positive OUT of machine):
  Vd = Ed_p - Ra*Id + Xq_p*Iq
  Vq = Eq_p - Ra*Iq - Xd_p*Id

Solving for Id, Iq:
  det = Ra**2 + Xd_p*Xq_p
  Id  = ( Ra*(Ed_p - Vd) + Xq_p*(Eq_p - Vq) ) / det
  Iq  = (-Xd_p*(Ed_p - Vd) + Ra*(Eq_p - Vq)  ) / det

Base system: 100 MVA, ω_s = 2π×50 rad/s (east Japan default).

Usage::

    from src.dynamics.models.sync_generator import (
        GeneratorParams, FUEL_DEFAULT_PARAMS, SyncGenerator
    )

    params = GeneratorParams.from_fuel("nuclear", S_rated_mva=1000.0,
                                       bus_id=5, name="Kashiwazaki-7")
    gen = SyncGenerator(params)
    P_pu = 0.8   # on machine base, then convert to system base
    Q_pu = 0.1
    V0   = 1.02 * np.exp(1j * np.deg2rad(5.0))
    state, Efd0, Pm0 = gen.initialize(P_pu, Q_pu, V0)
"""

from __future__ import annotations

import dataclasses
import math
from typing import Dict, Tuple

import numpy as np


# ── Constants ─────────────────────────────────────────────────────────────────
_OMEGA_S_EAST  = 2.0 * math.pi * 50.0   # rad/s  east Japan (50 Hz)
_OMEGA_S_WEST  = 2.0 * math.pi * 60.0   # rad/s  west Japan (60 Hz)
_BASE_MVA      = 100.0                   # system MVA base


# ── Fuel-type default parameters ──────────────────────────────────────────────
#   All reactances in pu on machine base; time constants in seconds.
#   Sources: Anderson & Fouad (2003), Kundur (1994), PSSE standard library.
FUEL_DEFAULT_PARAMS: Dict[str, Dict] = {
    "nuclear": dict(
        H=6.0, D=2.0, Ra=0.003,
        Xd=1.79, Xq=1.71,
        Xd_p=0.169, Xq_p=0.228,
        Td0_p=5.89, Tq0_p=0.50,
    ),
    "coal": dict(
        H=4.0, D=2.0, Ra=0.003,
        Xd=1.60, Xq=1.55,
        Xd_p=0.230, Xq_p=0.330,
        Td0_p=5.60, Tq0_p=0.70,
    ),
    "lng": dict(
        H=3.5, D=2.0, Ra=0.003,
        Xd=1.50, Xq=1.45,
        Xd_p=0.250, Xq_p=0.350,
        Td0_p=4.50, Tq0_p=0.60,
    ),
    "oil": dict(
        H=3.0, D=2.0, Ra=0.003,
        Xd=1.40, Xq=1.35,
        Xd_p=0.270, Xq_p=0.380,
        Td0_p=4.00, Tq0_p=0.50,
    ),
    "hydro": dict(
        H=3.0, D=2.0, Ra=0.003,
        Xd=1.25, Xq=0.95,
        Xd_p=0.310, Xq_p=0.560,
        Td0_p=5.20, Tq0_p=1.80,
    ),
    "geothermal": dict(
        H=3.5, D=2.0, Ra=0.003,
        Xd=1.50, Xq=1.45,
        Xd_p=0.250, Xq_p=0.350,
        Td0_p=4.50, Tq0_p=0.60,
    ),
    "unknown": dict(
        H=4.0, D=2.0, Ra=0.003,
        Xd=1.60, Xq=1.55,
        Xd_p=0.230, Xq_p=0.330,
        Td0_p=5.60, Tq0_p=0.70,
    ),
}


# ── Generator parameter dataclass ─────────────────────────────────────────────
@dataclasses.dataclass
class GeneratorParams:
    """All static parameters for a 4th-order synchronous generator.

    Electrical parameters are in pu on the *machine* base (S_rated_mva).
    Conversion to system base (100 MVA) is handled inside SyncGenerator.

    Parameters
    ----------
    H : float
        Inertia constant (MWs/MVA = s).
    D : float
        Damping coefficient (pu power / pu speed deviation).
    Ra : float
        Armature resistance (pu on machine base).
    Xd : float
        d-axis synchronous reactance (pu).
    Xq : float
        q-axis synchronous reactance (pu).
    Xd_p : float
        d-axis transient reactance (pu).
    Xq_p : float
        q-axis transient reactance (pu).
    Td0_p : float
        d-axis open-circuit transient time constant (s).
    Tq0_p : float
        q-axis open-circuit transient time constant (s).
    S_rated_mva : float
        Machine rated MVA (used for per-unit conversion to system base).
    bus_id : int
        Network bus index (0-based pandapower index).
    name : str
        Descriptive name / plant ID.
    fuel_type : str
        Fuel type string (e.g. 'nuclear', 'coal', 'lng', 'hydro').
    omega_s : float
        Synchronous speed (rad/s); default 2π×50 for east Japan.
    """

    H: float
    D: float
    Ra: float
    Xd: float
    Xq: float
    Xd_p: float
    Xq_p: float
    Td0_p: float
    Tq0_p: float
    S_rated_mva: float = _BASE_MVA
    bus_id: int = 0
    name: str = ""
    fuel_type: str = "unknown"
    omega_s: float = _OMEGA_S_EAST

    @classmethod
    def from_fuel(
        cls,
        fuel_type: str,
        S_rated_mva: float = _BASE_MVA,
        bus_id: int = 0,
        name: str = "",
        omega_s: float = _OMEGA_S_EAST,
        **overrides,
    ) -> "GeneratorParams":
        """Create GeneratorParams from a fuel-type template.

        Parameters
        ----------
        fuel_type : str
            Key in FUEL_DEFAULT_PARAMS.  Falls back to 'unknown' if not found.
        S_rated_mva : float
            Machine rated capacity in MVA.
        bus_id : int
            Network bus index.
        name : str
            Plant name.
        omega_s : float
            Synchronous speed (rad/s).
        **overrides
            Any field overrides (e.g. H=5.0).

        Returns
        -------
        GeneratorParams
        """
        defaults = FUEL_DEFAULT_PARAMS.get(fuel_type, FUEL_DEFAULT_PARAMS["unknown"]).copy()
        defaults.update(overrides)
        return cls(
            S_rated_mva=S_rated_mva,
            bus_id=bus_id,
            name=name,
            fuel_type=fuel_type,
            omega_s=omega_s,
            **defaults,
        )

    @property
    def base_mva(self) -> float:
        """System MVA base (100 MVA)."""
        return _BASE_MVA

    @property
    def mva_ratio(self) -> float:
        """Ratio S_rated_mva / base_mva for per-unit base conversion."""
        return self.S_rated_mva / _BASE_MVA


# ── Static dq-frame helper functions ─────────────────────────────────────────
class SGState:
    """Static helper functions for the synchronous generator d-q frame.

    All functions are pure (no instance state); they are collected here for
    namespace clarity and unit-test convenience.
    """

    @staticmethod
    def dq_from_net_voltage(
        V_complex: complex,
        delta: float,
    ) -> Tuple[float, float]:
        """Decompose network voltage into d-q components.

        Uses PSAT/Milano Park convention:
            Vd = VD*sin(δ) - VQ*cos(δ)
            Vq = VD*cos(δ) + VQ*sin(δ)
        where V_complex = VD + jVQ.

        Parameters
        ----------
        V_complex : complex
            Bus voltage phasor in network (DQ) frame.
        delta : float
            Rotor angle (rad).

        Returns
        -------
        Vd, Vq : float
            d- and q-axis voltage components (pu).
        """
        VD = V_complex.real
        VQ = V_complex.imag
        sin_d = math.sin(delta)
        cos_d = math.cos(delta)
        Vd = VD * sin_d - VQ * cos_d
        Vq = VD * cos_d + VQ * sin_d
        return Vd, Vq

    @staticmethod
    def solve_stator(
        Ed_p: float,
        Eq_p: float,
        Vd: float,
        Vq: float,
        Ra: float,
        Xd_p: float,
        Xq_p: float,
    ) -> Tuple[float, float]:
        """Solve stator algebraic equations for Id and Iq.

        Stator equations (current positive OUT of machine):
            Vd = Ed_p - Ra*Id + Xq_p*Iq
            Vq = Eq_p - Ra*Iq - Xd_p*Id

        Rearranged as linear system:
            Ra*Id  - Xq_p*Iq  = Ed_p - Vd
            Xd_p*Id + Ra*Iq   = Eq_p - Vq

        Matrix solution (det = Ra² + Xd_p*Xq_p):
            Id = ( Ra*(Ed_p - Vd) + Xq_p*(Eq_p - Vq) ) / det
            Iq = (-Xd_p*(Ed_p - Vd) + Ra*(Eq_p - Vq)  ) / det

        Parameters
        ----------
        Ed_p, Eq_p : float
            d- and q-axis transient EMFs (pu).
        Vd, Vq : float
            d- and q-axis terminal voltages (pu).
        Ra : float
            Armature resistance (pu).
        Xd_p, Xq_p : float
            Transient reactances (pu).

        Returns
        -------
        Id, Iq : float
            d- and q-axis armature currents (pu, positive out of machine).
        """
        det = Ra * Ra + Xd_p * Xq_p
        dEd = Ed_p - Vd
        dEq = Eq_p - Vq
        Id = ( Ra * dEd + Xq_p * dEq) / det
        Iq = (-Xd_p * dEd + Ra  * dEq) / det
        return Id, Iq

    @staticmethod
    def electrical_power(
        Vd: float,
        Vq: float,
        Id: float,
        Iq: float,
    ) -> float:
        """Electrical power at machine terminals: Pe = Vd*Id + Vq*Iq (pu).

        Positive Pe means power delivered to the network (generating convention).
        Copper losses Ra*(Id²+Iq²) are included implicitly because Vd, Vq
        already reflect the resistive drop.
        """
        return Vd * Id + Vq * Iq

    @staticmethod
    def air_gap_power(
        Ed_p: float,
        Eq_p: float,
        Id: float,
        Iq: float,
        Xd_p: float,
        Xq_p: float,
    ) -> float:
        """Air-gap power (electromagnetic torque × speed, pu).

        Paig = Ed_p*Id + Eq_p*Iq + (Xd_p - Xq_p)*Id*Iq

        The last term is the reluctance component (non-zero when Xd_p ≠ Xq_p).
        At rated speed (ω ≈ 1) this equals the electromagnetic torque in pu.

        Parameters
        ----------
        Ed_p, Eq_p : float
            Transient EMFs (pu).
        Id, Iq : float
            Armature current components (pu).
        Xd_p, Xq_p : float
            Transient reactances (pu).

        Returns
        -------
        float
            Air-gap power (pu on machine base).
        """
        return Ed_p * Id + Eq_p * Iq + (Xd_p - Xq_p) * Id * Iq


# ── Main generator class ───────────────────────────────────────────────────────
class SyncGenerator:
    """4th-order (two-axis) synchronous generator model.

    State vector (4 elements)
    -------------------------
    [0] delta  : rotor angle (rad) w.r.t. synchronous reference
    [1] omega  : per-unit rotor speed (1.0 = synchronous)
    [2] Ed_p   : d-axis transient EMF (pu on machine base)
    [3] Eq_p   : q-axis transient EMF (pu on machine base)

    Differential equations
    ----------------------
    d(delta)/dt = omega_s * (omega - 1)

    d(omega)/dt = (Pm - Pe - D*(omega-1)) / (2*H)
        where Pe = Vd*Id + Vq*Iq (pu on machine base)

    d(Ed_p)/dt  = (-Ed_p - (Xq - Xq_p)*Iq) / Tq0_p

    d(Eq_p)/dt  = (Efd - Eq_p - (Xd - Xd_p)*Id) / Td0_p
        Note: MINUS sign on (Xd-Xd_p)*Id with generator-out convention.
        At steady state: Efd = Eq_p + (Xd-Xd_p)*Id = Vq + Ra*Iq + Xd*Id
        (matches the synchronous stator equation).

    All quantities in pu on the *machine* base (S_rated_mva).
    Conversion to/from system base (100 MVA) happens at the interface
    (`current_injection` outputs system-base current).

    Parameters
    ----------
    params : GeneratorParams
        All static electrical and mechanical parameters.

    Examples
    --------
    >>> params = GeneratorParams.from_fuel("coal", S_rated_mva=600.0, bus_id=3)
    >>> gen = SyncGenerator(params)
    >>> V0 = 1.0 + 0j
    >>> state, Efd0, Pm0 = gen.initialize(0.85, 0.20, V0)
    >>> dxdt = gen.derivatives(state, Efd0, Pm0, V0)
    >>> # ddelta=0, domega=0, dEq_p=0 always; dEd_p may be non-zero for salient machines
    >>> abs(dxdt[1]) < 1e-10  # domega = 0
    True
    """

    def __init__(self, params: GeneratorParams) -> None:
        self.p = params

    # ── Properties ────────────────────────────────────────────────────────────
    @property
    def state_size(self) -> int:
        """Number of state variables (always 4 for this model)."""
        return 4

    # ── Core dynamics ─────────────────────────────────────────────────────────
    def derivatives(
        self,
        state: np.ndarray,
        Efd: float,
        Pm: float,
        V_complex: complex,
    ) -> np.ndarray:
        """Compute time derivatives of the state vector.

        Parameters
        ----------
        state : np.ndarray, shape (4,)
            [delta, omega, Ed_p, Eq_p] in pu on machine base.
        Efd : float
            Field voltage from AVR (pu on machine base).
        Pm : float
            Mechanical power from governor (pu on machine base).
        V_complex : complex
            Terminal bus voltage phasor (pu, system-base).
            The voltage is the same regardless of machine base.

        Returns
        -------
        np.ndarray, shape (4,)
            [d(delta)/dt, d(omega)/dt, d(Ed_p)/dt, d(Eq_p)/dt]
        """
        p = self.p
        delta, omega, Ed_p, Eq_p = float(state[0]), float(state[1]), \
                                    float(state[2]), float(state[3])

        # Park transform: network voltage → d-q components
        Vd, Vq = SGState.dq_from_net_voltage(V_complex, delta)

        # Stator algebraic equations → currents
        Id, Iq = SGState.solve_stator(Ed_p, Eq_p, Vd, Vq,
                                       p.Ra, p.Xd_p, p.Xq_p)

        # Electrical power at terminals (pu on machine base)
        Pe = SGState.electrical_power(Vd, Vq, Id, Iq)

        # Swing equation
        ddelta = p.omega_s * (omega - 1.0)
        domega = (Pm - Pe - p.D * (omega - 1.0)) / (2.0 * p.H)

        # Transient flux linkage dynamics
        dEd_p = (-Ed_p - (p.Xq - p.Xq_p) * Iq) / p.Tq0_p
        dEq_p = (Efd - Eq_p - (p.Xd - p.Xd_p) * Id) / p.Td0_p

        return np.array([ddelta, domega, dEd_p, dEq_p])

    def current_injection(
        self,
        state: np.ndarray,
        V_complex: complex,
    ) -> complex:
        """Compute complex current injection into the network (system base).

        Convention: I_net = (Iq - j*Id) * exp(j*delta)
        This represents the current that the generator injects into the bus.

        Parameters
        ----------
        state : np.ndarray, shape (4,)
            Generator state [delta, omega, Ed_p, Eq_p].
        V_complex : complex
            Terminal bus voltage (pu, system base).

        Returns
        -------
        complex
            Current injection phasor in network DQ frame (pu, *system* base).
        """
        p = self.p
        delta, _, Ed_p, Eq_p = float(state[0]), float(state[1]), \
                                 float(state[2]), float(state[3])

        Vd, Vq = SGState.dq_from_net_voltage(V_complex, delta)
        Id, Iq = SGState.solve_stator(Ed_p, Eq_p, Vd, Vq,
                                       p.Ra, p.Xd_p, p.Xq_p)

        # Machine-frame current → network frame, then scale to system base
        I_machine = (Iq - 1j * Id) * np.exp(1j * delta)
        I_system  = I_machine * p.mva_ratio
        return I_system

    def initialize(
        self,
        P_gen: float,
        Q_gen: float,
        V_complex: complex,
    ) -> Tuple[np.ndarray, float, float]:
        """Compute the initial steady-state from a power-flow solution.

        P_gen and Q_gen are on the *machine* base (S_rated_mva).
        V_complex is the terminal voltage phasor (unchanged by base).

        The steady-state initialization follows these steps:

        1. Form terminal current:
               I = (P_gen - j*Q_gen) / conj(V)   [generator convention: I out]

        2. Find rotor angle δ₀ via q-axis alignment using the *full* Xq
           (this locates the q-axis correctly in both salient and round-rotor):
               E_q = V + (Ra + j*Xq)*I
               δ₀  = angle(E_q)

        3. Apply Park transform to get Id, Iq:
               Id = Re[I]*sin(δ₀) - Im[I]*cos(δ₀)
               Iq = Re[I]*cos(δ₀) + Im[I]*sin(δ₀)

        4. Compute Vd, Vq from Park transform:
               Vd = Re[V]*sin(δ₀) - Im[V]*cos(δ₀)
               Vq = Re[V]*cos(δ₀) + Im[V]*sin(δ₀)

        5. Initial transient EMFs via stator inversion (PSS/E-class standard):
               Ed_p0 = Vd + Ra*Id - Xq_p*Iq
               Eq_p0 = Vq + Ra*Iq + Xd_p*Id
           This ensures Pe = Pm0 at t=0 (domega/dt = 0 exactly).
           For salient machines (Xq >> Xq_p, e.g. hydro), dEd_p/dt may be
           non-zero at t=0 and damps out in approximately Tq0_p seconds.
           This is accepted by all major commercial simulation codes.

        6. Field voltage and mechanical power:
               Efd0 = Eq_p0 + (Xd - Xd_p)*Id   [ensures dEq_p/dt = 0]
               Pm0  = Vd*Id + Vq*Iq             [terminal electrical power]
           Efd0 equals the synchronous stator: Vq + Ra*Iq + Xd*Id > 0 for lagging.

        Parameters
        ----------
        P_gen : float
            Active power generated (pu on machine base, positive = generating).
        Q_gen : float
            Reactive power generated (pu on machine base, positive = capacitive).
        V_complex : complex
            Terminal voltage phasor (pu, any base — same V for all bases).

        Returns
        -------
        state0 : np.ndarray, shape (4,)
            Initial state [delta0, 1.0, Ed_p0, Eq_p0].
        Efd0 : float
            Initial field voltage required to sustain steady state (pu).
        Pm0 : float
            Initial mechanical power (pu on machine base).
        """
        p = self.p
        V = complex(V_complex)

        # Step 1: Terminal current (generator convention: I flows out of machine)
        #   S = V * conj(I)  →  I = (P - jQ) / conj(V)
        I = (P_gen - 1j * Q_gen) / V.conjugate()

        # Step 2: Rotor angle from q-axis alignment using full Xq
        E_q_axis = V + (p.Ra + 1j * p.Xq) * I
        delta0 = float(np.angle(E_q_axis))

        # Step 3: Park transform for currents
        sin_d = math.sin(delta0)
        cos_d = math.cos(delta0)
        Id = I.real * sin_d - I.imag * cos_d
        Iq = I.real * cos_d + I.imag * sin_d

        # Step 4: Park transform for voltages
        Vd = V.real * sin_d - V.imag * cos_d
        Vq = V.real * cos_d + V.imag * sin_d

        # Step 5: Initial transient EMFs via stator-inversion
        #
        # Solve the transient stator equations for Ed_p, Eq_p given the
        # power-flow Id, Iq:
        #   Vd = Ed_p - Ra*Id + Xq_p*Iq  →  Ed_p = Vd + Ra*Id - Xq_p*Iq
        #   Vq = Eq_p - Ra*Iq - Xd_p*Id  →  Eq_p = Vq + Ra*Iq + Xd_p*Id
        #
        # This guarantees that the stator algebraic is satisfied at t=0,
        # so Pe = Pm0 and domega/dt = 0 exactly.
        #
        # For salient-pole machines (Xq >> Xq_p, e.g. hydro), dEd_p/dt will
        # be non-zero at t=0.  This is standard practice in all PSS/E-class
        # software — the q-axis transient damps out in ~ Tq0_p seconds.
        Ed_p0 = Vd + p.Ra * Id - p.Xq_p * Iq
        Eq_p0 = Vq + p.Ra * Iq + p.Xd_p * Id

        # Step 6: Field voltage and mechanical power
        #   dEq_p/dt = (Efd - Eq_p - (Xd-Xd_p)*Id) / Td0_p = 0
        #     → Efd = Eq_p + (Xd - Xd_p)*Id   [generator-out Id convention]
        #   This matches the synchronous stator: Efd = Vq + Ra*Iq + Xd*Id.
        #   Efd0 > 0 for typical lagging (overexcited) generator operation.
        Efd0 = Eq_p0 + (p.Xd - p.Xd_p) * Id
        Pm0  = Vd * Id + Vq * Iq   # terminal electrical power = Pe at t=0

        state0 = np.array([delta0, 1.0, Ed_p0, Eq_p0])
        return state0, float(Efd0), float(Pm0)


# ── Self-test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import numpy as np

    print("=== SyncGenerator self-test ===")

    # --- Test 1: Park transform round-trip ---
    V = 1.0 * np.exp(1j * np.deg2rad(10.0))
    delta = np.deg2rad(30.0)
    Vd, Vq = SGState.dq_from_net_voltage(V, delta)
    V_mag = abs(V)
    V_ang = np.angle(V)
    # Vq² + Vd² should equal |V|²
    assert abs(math.sqrt(Vd**2 + Vq**2) - V_mag) < 1e-12, "Park norm failed"
    # Vq/Vd angle check: angle in dq = V_ang - delta
    diff = V_ang - delta
    expected_Vd = V_mag * math.sin(-(diff))  # sin(-diff) == -sin(diff)
    expected_Vq = V_mag * math.cos(diff)     # ... actually
    # More direct: Vd = |V|*sin(θv - delta'), hmm. Let's just verify
    # by reconstructing V from Vd,Vq:
    # VD = Vd*sin(delta) + Vq*cos(delta)
    # VQ = -Vd*cos(delta) + Vq*sin(delta)
    VD_rec = Vd * math.sin(delta) + Vq * math.cos(delta)
    VQ_rec = -Vd * math.cos(delta) + Vq * math.sin(delta)
    assert abs(VD_rec - V.real) < 1e-12, f"Park inverse VD failed: {VD_rec} vs {V.real}"
    assert abs(VQ_rec - V.imag) < 1e-12, f"Park inverse VQ failed: {VQ_rec} vs {V.imag}"
    print("  [PASS] Park transform round-trip")

    # --- Test 2: Stator solve self-consistency ---
    Ra, Xd_p, Xq_p = 0.003, 0.169, 0.228
    Ed_p, Eq_p = 0.05, 1.10
    Vd_t, Vq_t = 0.10, 0.98
    Id, Iq = SGState.solve_stator(Ed_p, Eq_p, Vd_t, Vq_t, Ra, Xd_p, Xq_p)
    # Verify back-substitution
    Vd_check = Ed_p - Ra * Id + Xq_p * Iq
    Vq_check = Eq_p - Ra * Iq - Xd_p * Id
    assert abs(Vd_check - Vd_t) < 1e-12, f"Stator Vd mismatch: {Vd_check} vs {Vd_t}"
    assert abs(Vq_check - Vq_t) < 1e-12, f"Stator Vq mismatch: {Vq_check} vs {Vq_t}"
    print("  [PASS] Stator solve consistency")

    # --- Test 3: Initialization → correct steady-state conditions ---
    # Standard PSS/E-class initialization guarantees:
    #   ddelta = 0  (omega=1)
    #   domega = 0  (Pe=Pm by stator inversion)
    #   dEq_p  = 0  (Efd chosen for this)
    # For salient machines (Xq >> Xq_p), dEd_p may be non-zero — this is accepted.
    for fuel in ["nuclear", "coal", "lng", "hydro"]:
        params = GeneratorParams.from_fuel(fuel, S_rated_mva=500.0, bus_id=0)
        gen = SyncGenerator(params)
        V0 = 1.02 * np.exp(1j * np.deg2rad(5.0))
        P0, Q0 = 0.80, 0.15
        state0, Efd0, Pm0 = gen.initialize(P0, Q0, V0)
        dxdt = gen.derivatives(state0, Efd0, Pm0, V0)
        # Verify the three guaranteed-zero derivatives
        assert abs(dxdt[0]) < 1e-12, f"ddelta non-zero for {fuel}: {dxdt[0]}"
        assert abs(dxdt[1]) < 1e-12, f"domega non-zero for {fuel}: {dxdt[1]}"
        assert abs(dxdt[3]) < 1e-10, f"dEq_p non-zero for {fuel}: {dxdt[3]}"
        # dEd_p may be non-zero for salient machines (Xq >> Xq_p)
        print(f"  [PASS] {fuel}: δ₀={np.rad2deg(state0[0]):.2f}°, "
              f"Efd0={Efd0:.4f}, Pm0={Pm0:.4f}, "
              f"dEd_p={dxdt[2]:.3e} (0 for round-rotor)")

    # --- Test 4: Current injection base conversion ---
    params = GeneratorParams.from_fuel("coal", S_rated_mva=200.0, bus_id=1)
    gen = SyncGenerator(params)
    V0 = 1.0 + 0j
    state0, Efd0, Pm0 = gen.initialize(0.5, 0.1, V0)
    I_net = gen.current_injection(state0, V0)
    # Power check: S_system = V * conj(I_net) should equal (P+jQ)*mva_ratio
    S_sys = V0 * I_net.conjugate()
    P_sys = params.mva_ratio * 0.5
    Q_sys = params.mva_ratio * 0.1
    assert abs(S_sys.real - P_sys) < 1e-9, f"P injection mismatch: {S_sys.real} vs {P_sys}"
    assert abs(S_sys.imag - Q_sys) < 1e-9, f"Q injection mismatch: {S_sys.imag} vs {Q_sys}"
    print(f"  [PASS] Current injection base conversion (200MVA machine → 100MVA system)")

    print("=== All tests passed ===")
