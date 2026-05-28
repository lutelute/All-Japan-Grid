"""Short-circuit analysis for All-Japan-Grid power system.

Implements:
- Three-phase (balanced) fault analysis using Z_bus method
- Single-line-to-ground (SLG) fault via symmetrical components
- Line-to-line (LL) and line-to-line-to-ground (LLG) faults
- Comprehensive bus SCC (short-circuit capacity) computation
- Geographic SCC map visualization

The Z_bus method:
    Z_bus = inv(Y_bus)
    I_fault_k = V_prefault[k] / Z_bus[k,k]   (3-phase, pu)
    V_during_fault[j] = V_prefault[j] - Z_bus[j,k] * I_fault_k  (pu)

Short-circuit capacity (SCC):
    SCC_k [MVA] = |V0[k]|^2 / |Z_bus[k,k]| * S_base_MVA

Usage::

    from src.dynamics.analysis.short_circuit import (
        ShortCircuitAnalysis, FaultType
    )

    sca = ShortCircuitAnalysis(Y_bus, V0, sbase_mva=100.0)
    result = sca.compute_all_bus_scc()
    I_fault, V_fault = sca.three_phase_fault(fault_bus=5)
    sca.plot_scc_map(result, buses, "scc_map.png")
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla


# ── Fault Type Enum ───────────────────────────────────────────────────────────
class FaultType(Enum):
    """Enumeration of fault types for power system short-circuit analysis."""

    THREE_PHASE = auto()            # Balanced three-phase fault (worst case)
    SINGLE_LINE_GROUND = auto()     # SLG: most common fault type (~70% of faults)
    LINE_LINE = auto()              # LL: line-to-line fault (~15%)
    LINE_LINE_GROUND = auto()       # LLG: double-line-to-ground fault (~10%)


# ── Short-Circuit Result ───────────────────────────────────────────────────────
@dataclass
class SCCResult:
    """Output of bus short-circuit capacity calculation.

    Attributes
    ----------
    bus_names : list of str
        Bus labels (index-based if not provided).
    scc_mva : np.ndarray, shape (nb,)
        Three-phase short-circuit capacity (MVA) at each bus.
    Z_bus_diag : np.ndarray, complex, shape (nb,)
        Diagonal of the Z_bus matrix (Thevenin impedance at each bus).
    fault_currents : np.ndarray, shape (nb,)
        Three-phase fault current (pu) at each bus at nominal voltage.
    fault_currents_ka : np.ndarray, shape (nb,)
        Fault currents in kA (requires base voltage per bus for conversion).
    nb : int
        Number of buses.
    sbase_mva : float
        System MVA base used in the calculation.
    """

    bus_names: List[str]
    scc_mva: np.ndarray
    Z_bus_diag: np.ndarray
    fault_currents: np.ndarray
    fault_currents_ka: np.ndarray
    nb: int
    sbase_mva: float


# ── Short-Circuit Analysis Class ──────────────────────────────────────────────
class ShortCircuitAnalysis:
    """Short-circuit (fault level) analysis for a network bus system.

    Uses the Z_bus (impedance matrix) method for balanced three-phase
    fault calculations, and symmetrical components for unbalanced faults.

    Parameters
    ----------
    Y_bus : scipy.sparse or np.ndarray, shape (nb, nb)
        Positive-sequence network admittance matrix (complex pu).
    V0 : np.ndarray, complex, shape (nb,)
        Pre-fault bus voltage vector (pu). Typically from power flow.
    sbase_mva : float
        System MVA base. Default 100.0 MVA.
    vbase_kv : np.ndarray or float, optional
        Base voltage at each bus (kV). If scalar, applied to all buses.
        Used for converting fault current from pu to kA.
    """

    def __init__(
        self,
        Y_bus: sp.spmatrix,
        V0: np.ndarray,
        sbase_mva: float = 100.0,
        vbase_kv: Optional[np.ndarray] = None,
        gen_admittances: Optional[Dict[int, complex]] = None,
    ) -> None:
        if not sp.issparse(Y_bus):
            Y_bus = sp.csr_matrix(Y_bus, dtype=complex)
        Y_bus = Y_bus.astype(complex)
        # Add generator Thevenin shunt admittances to make Y_bus non-singular.
        # Without shunts a pure series Y_bus is singular (sum of rows = 0).
        # gen_admittances: {bus_idx: y_gen_pu}  e.g. 1/(Ra+jXd')
        if gen_admittances:
            Y_gen = sp.lil_matrix(Y_bus.shape, dtype=complex)
            for bus_k, y_k in gen_admittances.items():
                Y_gen[bus_k, bus_k] = y_k
            Y_bus = Y_bus + Y_gen.tocsr()
        self.Y_bus = Y_bus.tocsr()
        self.V0 = np.asarray(V0, dtype=complex)
        self.nb = Y_bus.shape[0]
        self.sbase_mva = float(sbase_mva)

        if vbase_kv is None:
            self._vbase_kv = np.ones(self.nb) * 500.0  # default 500 kV
        elif np.isscalar(vbase_kv):
            self._vbase_kv = np.ones(self.nb) * float(vbase_kv)
        else:
            self._vbase_kv = np.asarray(vbase_kv, dtype=float)

        # Base current at each bus [kA] = S_base / (sqrt(3) * V_base)
        self._ibase_ka = self.sbase_mva / (np.sqrt(3.0) * self._vbase_kv * 1e3) * 1e6  # -> kA

        # Z_bus cache (computed lazily)
        self._Z_bus_diag: Optional[np.ndarray] = None
        self._Z_bus_full: Optional[np.ndarray] = None

    # ── Z_bus diagonal computation ─────────────────────────────────────────
    def build_zbus(self) -> np.ndarray:
        """Compute full Z_bus = inv(Y_bus).

        For small systems (nb <= 300): direct dense inversion.
        For larger systems: sparse LU solve for each column.

        Each bus diagonal Z_bus[k,k] gives the Thevenin impedance
        seen from bus k.

        Returns
        -------
        np.ndarray, complex, shape (nb, nb)
            Full impedance matrix.
        """
        if self._Z_bus_full is not None:
            return self._Z_bus_full

        nb = self.nb

        if nb <= 300:
            # Dense inversion
            Y_dense = np.array(self.Y_bus.toarray(), dtype=complex)
            try:
                Z = np.linalg.inv(Y_dense)
            except np.linalg.LinAlgError:
                # Singular or near-singular: use pinv
                Z = np.linalg.pinv(Y_dense)
            self._Z_bus_full = Z
            self._Z_bus_diag = np.diag(Z)
        else:
            # Compute only diagonal via sparse LU: solve Y*e_k = I
            Y_csc = self.Y_bus.tocsc()
            lu = spla.splu(Y_csc)

            Z_diag = np.zeros(nb, dtype=complex)
            for k in range(nb):
                e_k = np.zeros(nb, dtype=complex)
                e_k[k] = 1.0
                col_k = lu.solve(e_k)
                Z_diag[k] = col_k[k]

            self._Z_bus_diag = Z_diag
            # Build sparse representation of diagonal only
            # Full Z_bus not cached for large systems
            self._Z_bus_full = None  # not stored

        return self._Z_bus_full if self._Z_bus_full is not None else np.diag(self._Z_bus_diag)

    def _get_zbus_row_col(self, bus: int) -> Tuple[np.ndarray, np.ndarray]:
        """Get row and column k of Z_bus efficiently.

        For small systems: extract from cached full Z_bus.
        For large systems: solve Y * e_k for the column.

        Parameters
        ----------
        bus : int

        Returns
        -------
        (Z_row_k, Z_col_k) : np.ndarray, complex, shape (nb,)
            Row and column bus of Z_bus.
        """
        if self._Z_bus_full is not None:
            return self._Z_bus_full[bus, :], self._Z_bus_full[:, bus]

        # Compute column via sparse LU
        Y_csc = self.Y_bus.tocsc()
        lu = spla.splu(Y_csc)
        e_k = np.zeros(self.nb, dtype=complex)
        e_k[bus] = 1.0
        Z_col = lu.solve(e_k)
        Z_row = Z_col  # Z_bus is symmetric if Y_bus is symmetric
        return Z_row, Z_col

    def _get_zbus_diag(self) -> np.ndarray:
        """Return diagonal elements of Z_bus (Thevenin impedances)."""
        if self._Z_bus_diag is not None:
            return self._Z_bus_diag

        nb = self.nb
        if self.nb <= 300:
            self.build_zbus()
            return self._Z_bus_diag
        else:
            Y_csc = self.Y_bus.tocsc()
            try:
                lu = spla.splu(Y_csc)
            except Exception:
                Y_csc_reg = Y_csc + sp.eye(nb, dtype=complex) * 1e-8
                lu = spla.splu(Y_csc_reg.tocsc())

            Z_diag = np.zeros(nb, dtype=complex)
            for k in range(nb):
                e_k = np.zeros(nb, dtype=complex)
                e_k[k] = 1.0
                try:
                    col_k = lu.solve(e_k)
                    Z_diag[k] = col_k[k]
                except Exception:
                    Z_diag[k] = 1e-3 + 1j * 0.1  # fallback
            self._Z_bus_diag = Z_diag
            return Z_diag

    # ── Three-phase fault ──────────────────────────────────────────────────
    def three_phase_fault(
        self, fault_bus: int
    ) -> Tuple[complex, np.ndarray]:
        """Compute three-phase fault current and bus voltages during fault.

        Using Z_bus method:
            I_fault = V0[fault_bus] / Z_bus[fault_bus, fault_bus]
            V_during[k] = V0[k] - Z_bus[k, fault_bus] * I_fault

        Parameters
        ----------
        fault_bus : int
            Bus index where the 3-phase fault is applied.

        Returns
        -------
        I_fault : complex
            Fault current phasor (pu on system base).
        V_during : np.ndarray, complex, shape (nb,)
            Bus voltages during the fault (pu).
        """
        Z_diag = self._get_zbus_diag()
        Z_kk = Z_diag[fault_bus]

        V0_k = self.V0[fault_bus]
        if abs(Z_kk) < 1e-14:
            I_fault = complex(1e10, 0.0)
        else:
            I_fault = V0_k / Z_kk

        # Voltage sag at all buses
        _, Z_col = self._get_zbus_row_col(fault_bus)
        V_during = self.V0 - Z_col * I_fault

        return I_fault, V_during

    # ── All-bus SCC computation ────────────────────────────────────────────
    def compute_all_bus_scc(
        self,
        bus_names: Optional[List[str]] = None,
    ) -> SCCResult:
        """Compute three-phase short-circuit capacity (SCC) for all buses.

        SCC formula:
            SCC_k [MVA] = |V0[k]|^2 / |Z_bus[k,k]| * S_base_MVA

        where Z_bus[k,k] is the Thevenin impedance at bus k.
        Equivalently: SCC_k = |V0[k]| * |I_fault_k| * S_base_MVA
        (in pu per-unit arithmetic).

        Parameters
        ----------
        bus_names : list of str, optional
            Bus labels. If None, uses 'Bus_k' format.

        Returns
        -------
        SCCResult
        """
        nb = self.nb

        if bus_names is None:
            bus_names = [f"Bus_{k}" for k in range(nb)]
        elif len(bus_names) < nb:
            bus_names = list(bus_names) + [f"Bus_{k}" for k in range(len(bus_names), nb)]

        Z_diag = self._get_zbus_diag()

        V_mag = np.abs(self.V0)
        Z_mag = np.abs(Z_diag)

        # Avoid division by zero
        Z_mag_safe = np.where(Z_mag < 1e-14, 1e-14, Z_mag)

        # SCC in MVA
        scc_mva = (V_mag ** 2) / Z_mag_safe * self.sbase_mva

        # Fault current in pu
        fault_currents_pu = V_mag / Z_mag_safe

        # Fault current in kA
        fault_currents_ka = fault_currents_pu * self._ibase_ka

        return SCCResult(
            bus_names=bus_names[:nb],
            scc_mva=scc_mva,
            Z_bus_diag=Z_diag,
            fault_currents=fault_currents_pu,
            fault_currents_ka=fault_currents_ka,
            nb=nb,
            sbase_mva=self.sbase_mva,
        )

    # ── Single-line-to-ground fault ────────────────────────────────────────
    def single_line_ground(
        self,
        fault_bus: int,
        Z1: Optional[complex] = None,
        Z2: Optional[complex] = None,
        Z0: Optional[complex] = None,
    ) -> float:
        """Compute SLG fault current using symmetrical components.

        For a single-line-to-ground fault on phase A:
            I_a1 = V_prefault / (Z1 + Z2 + Z0)
            I_fault = 3 * I_a1   (total fault current magnitude)

        If Z1, Z2, Z0 are not provided, uses Z_bus[k,k] for all three
        sequences (simplified: Z1 = Z2 = Z0 = Z_thevenin).

        Parameters
        ----------
        fault_bus : int
        Z1, Z2, Z0 : complex, optional
            Sequence impedances (pu). If None, uses Z_bus diagonal.

        Returns
        -------
        float
            Total SLG fault current magnitude (pu).
        """
        Z_diag = self._get_zbus_diag()
        Z_thevenin = Z_diag[fault_bus]

        if Z1 is None:
            Z1 = Z_thevenin
        if Z2 is None:
            Z2 = Z_thevenin
        if Z0 is None:
            Z0 = Z_thevenin

        Z_total = Z1 + Z2 + Z0
        if abs(Z_total) < 1e-14:
            return float("inf")

        V_pf = self.V0[fault_bus]
        I_a1 = V_pf / Z_total
        I_fault = 3.0 * abs(I_a1)

        return float(I_fault)

    # ── Line-to-line fault ─────────────────────────────────────────────────
    def line_line(
        self,
        fault_bus: int,
        Z1: Optional[complex] = None,
        Z2: Optional[complex] = None,
    ) -> float:
        """Compute phase-to-phase (LL) fault current.

        Symmetrical components for LL fault:
            I_a1 = V_prefault / (Z1 + Z2)
            I_fault = sqrt(3) * |I_a1|

        Parameters
        ----------
        fault_bus : int
        Z1, Z2 : complex, optional
            Positive and negative sequence impedances. If None, uses Z_bus diagonal.

        Returns
        -------
        float
            LL fault current magnitude (pu).
        """
        Z_diag = self._get_zbus_diag()
        Z_th = Z_diag[fault_bus]

        Z1 = Z_th if Z1 is None else Z1
        Z2 = Z_th if Z2 is None else Z2

        Z_total = Z1 + Z2
        if abs(Z_total) < 1e-14:
            return float("inf")

        V_pf = self.V0[fault_bus]
        I_a1 = V_pf / Z_total
        I_fault = np.sqrt(3.0) * abs(I_a1)

        return float(I_fault)

    # ── Line-to-line-to-ground fault ──────────────────────────────────────
    def line_line_ground(
        self,
        fault_bus: int,
        Z1: Optional[complex] = None,
        Z2: Optional[complex] = None,
        Z0: Optional[complex] = None,
    ) -> float:
        """Compute double-line-to-ground (LLG) fault current.

        Symmetrical components for LLG fault:
            Z_parallel = Z2 * Z0 / (Z2 + Z0)
            I_a1 = V_prefault / (Z1 + Z_parallel)
            I_a2 = -I_a1 * Z0 / (Z2 + Z0)
            I_a0 = -I_a1 * Z2 / (Z2 + Z0)
            I_fault = |I_a1 + I_a2 + I_a0| (not meaningful); use:
            I_b = |a^2*I_a1 + a*I_a2 + I_a0| (phase B fault current)

        Returns the magnitude of the maximum fault phase current.

        Parameters
        ----------
        fault_bus : int
        Z1, Z2, Z0 : complex, optional

        Returns
        -------
        float
            Maximum faulted-phase current magnitude (pu).
        """
        Z_diag = self._get_zbus_diag()
        Z_th = Z_diag[fault_bus]

        Z1 = Z_th if Z1 is None else Z1
        Z2 = Z_th if Z2 is None else Z2
        Z0 = Z_th if Z0 is None else Z0

        Z_denom = Z2 + Z0
        if abs(Z_denom) < 1e-14:
            return float("inf")

        Z_parallel = Z2 * Z0 / Z_denom
        Z_total = Z1 + Z_parallel
        if abs(Z_total) < 1e-14:
            return float("inf")

        V_pf = self.V0[fault_bus]
        a = complex(-0.5, np.sqrt(3) / 2.0)  # 120° rotation

        I_a1 = V_pf / Z_total
        I_a2 = -I_a1 * Z0 / Z_denom
        I_a0 = -I_a1 * Z2 / Z_denom

        I_b = a * a * I_a1 + a * I_a2 + I_a0
        I_c = a * I_a1 + a * a * I_a2 + I_a0

        return float(max(abs(I_b), abs(I_c)))

    # ── Full fault analysis for a bus ─────────────────────────────────────
    def fault_analysis(
        self, fault_bus: int
    ) -> Dict[str, float]:
        """Compute all fault types at a given bus.

        Parameters
        ----------
        fault_bus : int

        Returns
        -------
        dict with keys: '3ph_pu', 'slg_pu', 'll_pu', 'llg_pu',
                        '3ph_mva', 'slg_mva', 'll_mva', 'llg_mva'
        """
        I_3ph, _ = self.three_phase_fault(fault_bus)
        I_slg = self.single_line_ground(fault_bus)
        I_ll = self.line_line(fault_bus)
        I_llg = self.line_line_ground(fault_bus)

        V_mag = float(abs(self.V0[fault_bus]))

        def to_mva(I_pu: float) -> float:
            return I_pu * V_mag * self.sbase_mva

        return {
            "3ph_pu": float(abs(I_3ph)),
            "slg_pu": float(I_slg),
            "ll_pu": float(I_ll),
            "llg_pu": float(I_llg),
            "3ph_mva": to_mva(float(abs(I_3ph))),
            "slg_mva": to_mva(float(I_slg)),
            "ll_mva": to_mva(float(I_ll)),
            "llg_mva": to_mva(float(I_llg)),
        }

    # ── Geographic SCC map ─────────────────────────────────────────────────
    def plot_scc_map(
        self,
        result: SCCResult,
        buses: List,
        fig_path: str,
        max_scc_gva: Optional[float] = None,
    ) -> None:
        """Geographic bubble map of short-circuit capacity.

        Bubble size is proportional to SCC in MVA. Color indicates
        relative fault severity (red = high SCC, blue = low SCC).

        Parameters
        ----------
        result : SCCResult
        buses : list of substation/bus objects with .latitude, .longitude attributes.
            Objects must have numeric lat/lon attributes. Can also be dicts
            with 'lat'/'lon' or 'latitude'/'longitude' keys.
        fig_path : str
            Output file path.
        max_scc_gva : float, optional
            Maximum SCC for color scale normalization (GVA).
            If None, uses the 95th percentile.
        """
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import matplotlib.cm as cm
            import matplotlib.colors as mcolors
        except ImportError:
            print("matplotlib not available; skipping SCC map.")
            return

        nb = result.nb
        lats = []
        lons = []

        for bus_obj in buses[:nb]:
            lat, lon = _extract_lat_lon(bus_obj)
            lats.append(lat)
            lons.append(lon)

        # Filter out buses with no geographic data
        valid = [(i, lats[i], lons[i]) for i in range(len(lats))
                 if abs(lats[i]) > 0.1 or abs(lons[i]) > 0.1]

        if not valid:
            print("No geographic data available for SCC map.")
            return

        scc = result.scc_mva / 1000.0  # convert to GVA for display

        if max_scc_gva is None:
            max_scc_gva = float(np.percentile(scc, 95))
        max_scc_gva = max(max_scc_gva, 1.0)

        fig, ax = plt.subplots(figsize=(12, 10))

        norm = mcolors.Normalize(vmin=0, vmax=max_scc_gva)
        cmap = cm.RdYlGn_r  # red = high SCC (severe), green = low

        for bus_i, lat, lon in valid:
            if bus_i >= len(scc):
                continue
            scc_val = float(scc[bus_i])
            size = max(10, min(800, scc_val * 80 / max(max_scc_gva, 1.0)))
            color = cmap(norm(scc_val))
            ax.scatter(lon, lat, s=size, c=[color], alpha=0.7,
                       edgecolors="k", linewidths=0.4, zorder=5)

            if scc_val > max_scc_gva * 0.5:
                ax.annotate(
                    f"{scc_val:.1f}GVA",
                    xy=(lon, lat),
                    xytext=(3, 3),
                    textcoords="offset points",
                    fontsize=6,
                    alpha=0.85,
                )

        sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        plt.colorbar(sm, ax=ax, label="3-Phase SCC (GVA)")

        ax.set_xlabel("Longitude (°E)")
        ax.set_ylabel("Latitude (°N)")
        ax.set_title(
            f"Short-Circuit Capacity Map — {nb} buses\n"
            f"Max SCC: {float(np.max(scc)):.1f} GVA | "
            f"Total: {float(np.sum(scc)):.0f} GVA",
            fontsize=11,
        )
        ax.grid(True, alpha=0.3)

        fig.tight_layout()
        os.makedirs(os.path.dirname(os.path.abspath(fig_path)), exist_ok=True)
        fig.savefig(fig_path, dpi=150, bbox_inches="tight")
        plt.close(fig)


# ── Helper: extract lat/lon from various bus object types ─────────────────────
def _extract_lat_lon(bus_obj) -> Tuple[float, float]:
    """Extract latitude and longitude from various bus object types.

    Supports: objects with .latitude/.longitude, .lat/.lon attributes,
    dicts with 'latitude'/'longitude' or 'lat'/'lon' keys.
    """
    if isinstance(bus_obj, dict):
        lat = float(bus_obj.get("latitude", bus_obj.get("lat", 0.0)))
        lon = float(bus_obj.get("longitude", bus_obj.get("lon", 0.0)))
        return lat, lon

    for lat_attr in ("latitude", "lat", "y"):
        if hasattr(bus_obj, lat_attr):
            lat = float(getattr(bus_obj, lat_attr) or 0.0)
            break
    else:
        lat = 0.0

    for lon_attr in ("longitude", "lon", "x"):
        if hasattr(bus_obj, lon_attr):
            lon = float(getattr(bus_obj, lon_attr) or 0.0)
            break
    else:
        lon = 0.0

    return lat, lon


# ── Convenience function ──────────────────────────────────────────────────────
def compute_system_scc(
    Y_bus: sp.spmatrix,
    V0: np.ndarray,
    sbase_mva: float = 100.0,
    bus_names: Optional[List[str]] = None,
    vbase_kv: Optional[np.ndarray] = None,
) -> SCCResult:
    """One-shot SCC computation for the entire network.

    Parameters
    ----------
    Y_bus : scipy.sparse, shape (nb, nb)
    V0 : np.ndarray, complex, shape (nb,)
        Pre-fault bus voltages.
    sbase_mva : float
    bus_names : list of str, optional
    vbase_kv : np.ndarray or float, optional

    Returns
    -------
    SCCResult
    """
    sca = ShortCircuitAnalysis(Y_bus, V0, sbase_mva=sbase_mva, vbase_kv=vbase_kv)
    return sca.compute_all_bus_scc(bus_names=bus_names)
