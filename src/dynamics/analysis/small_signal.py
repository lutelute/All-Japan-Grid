"""Small-signal stability analysis for All-Japan-Grid power system dynamics.

Computes the reduced state matrix A_red = A - B @ inv(D) @ C from the
linearized DAE system, performs eigenvalue analysis, identifies
electromechanical oscillation modes, and computes participation factors.

Key definitions:
    A_red : reduced state matrix (nx × nx)
    λ = σ ± jω_d : complex eigenvalue pair
    frequency = ω_d / (2π) [Hz]
    damping ratio = -σ / |λ|
    participation factor: P[i,k] = |ψ_k[i]| * |φ_k[i]|
        where ψ_k = left eigenvector, φ_k = right eigenvector of mode k

Usage::

    from src.dynamics.simulation.dae_system import DAESystem
    from src.dynamics.analysis.small_signal import SmallSignalAnalysis

    ssa = SmallSignalAnalysis(system)
    result = ssa.analyze(x0, V0)

    for i, lam in enumerate(result.eigenvalues):
        print(f"Mode {i}: {result.frequencies_hz[i]:.3f} Hz, "
              f"ζ={result.damping_ratios[i]:.3f}")

    ssa.plot_eigenvalues(result, "eigenvalues.png")
    ssa.participation_heatmap(result, "participation.png")
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
import scipy.linalg as la
import scipy.sparse.linalg as spla

from src.dynamics.simulation.dae_system import DAESystem


# ── Modal Result ─────────────────────────────────────────────────────────────
@dataclass
class ModalResult:
    """Output of small-signal modal analysis.

    Attributes
    ----------
    eigenvalues : np.ndarray, complex, shape (n_modes,)
        Complex eigenvalues λ = σ ± jω_d of the reduced state matrix.
    frequencies_hz : np.ndarray, shape (n_modes,)
        Oscillation frequencies f = |ω_d| / (2π) [Hz].
    damping_ratios : np.ndarray, shape (n_modes,)
        Damping ratios ζ = -σ / |λ|. Positive = stable mode.
    participation_matrix : np.ndarray, shape (n_modes, nx)
        Normalized participation factors: P[k, i] for mode k, state i.
    state_labels : list of str
        Human-readable labels for each state variable.
    mode_shapes : np.ndarray, complex, shape (n_modes, nx)
        Right eigenvectors (columns of V from eig(A_red)).
    A_red : np.ndarray, shape (nx, nx)
        Reduced state matrix used for the analysis.
    n_unstable : int
        Number of modes with positive real part (σ > 0).
    electromechanical_modes : list of int
        Indices of modes in the 0.1–2.0 Hz range (inter-area / local).
    """

    eigenvalues: np.ndarray
    frequencies_hz: np.ndarray
    damping_ratios: np.ndarray
    participation_matrix: np.ndarray
    state_labels: List[str]
    mode_shapes: np.ndarray
    A_red: np.ndarray
    n_unstable: int = 0
    electromechanical_modes: List[int] = field(default_factory=list)


# ── Small-Signal Analysis Class ───────────────────────────────────────────────
class SmallSignalAnalysis:
    """Small-signal (modal) stability analysis for a DAE power system.

    Linearizes the DAE at an operating point, computes the reduced state
    matrix, performs full eigenanalysis, and identifies electromechanical
    oscillation modes.

    Parameters
    ----------
    system : DAESystem
        The assembled DAE system.
    eps : float
        Perturbation size for numerical Jacobians. Default 1e-7.
    """

    def __init__(self, system: DAESystem, eps: float = 1e-7) -> None:
        self.system = system
        self.eps = eps

    # ── State labels ───────────────────────────────────────────────────────
    def _build_state_labels(self) -> List[str]:
        """Build descriptive labels for each state variable.

        Format: ['δ_name', 'ω_name', "Ed'_name", "Eq'_name"] per generator.

        Returns
        -------
        list of str, length nx
        """
        labels = []
        for gen in self.system.data.generators:
            name = gen.p.name if gen.p.name else f"bus{gen.p.bus_id}"
            # Shorten long names
            short = name[:12] if len(name) > 12 else name
            labels.append(f"δ_{short}")
            labels.append(f"ω_{short}")
            labels.append(f"Ed'_{short}")
            labels.append(f"Eq'_{short}")
        return labels

    # ── Reduced state matrix ───────────────────────────────────────────────
    def compute_state_matrix(
        self,
        x0: np.ndarray,
        V0: np.ndarray,
    ) -> np.ndarray:
        """Compute reduced state matrix A_red = A - B @ inv(D) @ C.

        Linearizes the DAE at (x0, V0) using numerical finite differences
        with perturbation size self.eps.

        A = ∂f/∂x  (nx × nx)
        B = ∂f/∂y  (nx × 2nb)
        C = ∂g/∂x  (2nb × nx)
        D = ∂g/∂y  (2nb × 2nb)

        The reduced matrix eliminates algebraic variables:
            A_red = A - B @ D^{-1} @ C

        Parameters
        ----------
        x0 : np.ndarray, shape (nx,)
            Operating point state.
        V0 : np.ndarray, complex, shape (nb,)
            Operating point bus voltage.

        Returns
        -------
        np.ndarray, shape (nx, nx)
            Reduced state matrix.
        """
        A, B, C, D = self.system.linearize(x0, V0)
        return self.system.reduced_state_matrix(x0, V0)

    # ── Full modal analysis ────────────────────────────────────────────────
    def analyze(
        self,
        x0: np.ndarray,
        V0: np.ndarray,
        em_freq_range: Tuple[float, float] = (0.1, 2.0),
    ) -> ModalResult:
        """Full eigenvalue analysis and mode identification.

        Steps:
        1. Compute A_red via linearization.
        2. Eigenvalue decomposition: A_red = φ Λ ψ^H
           where φ = right eigenvectors, ψ = left eigenvectors.
        3. For each eigenvalue λ = σ + jω_d:
           - frequency = |ω_d| / (2π) [Hz]
           - damping = -σ / |λ| (positive = stable)
        4. Participation factors: P[k, i] = |ψ_k[i]| * |φ_k[i]|
           normalized so that max(P[k, :]) = 1.
        5. Identify electromechanical modes (em_freq_range Hz range).

        Parameters
        ----------
        x0 : np.ndarray, shape (nx,)
        V0 : np.ndarray, complex, shape (nb,)
        em_freq_range : (float, float)
            Frequency range (Hz) to classify as electromechanical modes.
            Default (0.1, 2.0) Hz.

        Returns
        -------
        ModalResult
        """
        A_red = self.compute_state_matrix(x0, V0)
        nx = A_red.shape[0]

        # Eigenvalue decomposition (unsymmetric matrix)
        # eig returns (eigenvalues, right_eigenvectors)
        eigenvalues, right_vecs = la.eig(A_red)

        # Left eigenvectors: from eig of A_red.T
        _, left_vecs = la.eig(A_red.T)

        n_modes = len(eigenvalues)

        # Sort by imaginary part magnitude (oscillation frequency)
        sort_idx = np.argsort(np.abs(eigenvalues.imag))[::-1]
        eigenvalues = eigenvalues[sort_idx]
        right_vecs = right_vecs[:, sort_idx]
        left_vecs = left_vecs[:, sort_idx]

        # Compute frequencies and damping ratios
        frequencies_hz = np.abs(eigenvalues.imag) / (2.0 * math.pi)
        abs_lam = np.abs(eigenvalues)
        abs_lam_safe = np.where(abs_lam < 1e-12, 1e-12, abs_lam)
        damping_ratios = -eigenvalues.real / abs_lam_safe

        # Participation factors: P[k, i] = |ψ_k[i]| * |φ_k[i]|
        # Normalize left eigenvectors: inner product φ_k^H ψ_k = 1
        participation = np.zeros((n_modes, nx), dtype=float)
        for k in range(n_modes):
            phi_k = right_vecs[:, k]   # right eigenvector (length nx)
            psi_k = left_vecs[:, k]    # left eigenvector (length nx)
            # Biorthonormalize: scale so that psi_k^T @ phi_k = 1
            inner = float(np.abs(psi_k.conj() @ phi_k))
            if inner > 1e-14:
                psi_k = psi_k / (psi_k.conj() @ phi_k)
            pf = np.abs(psi_k) * np.abs(phi_k)
            # Normalize to [0, 1]
            pf_max = float(np.max(pf))
            if pf_max > 1e-14:
                pf = pf / pf_max
            participation[k, :] = pf

        # Identify electromechanical modes
        f_lo, f_hi = em_freq_range
        em_modes = [
            k for k in range(n_modes)
            if f_lo <= frequencies_hz[k] <= f_hi
        ]

        # Count unstable modes (σ > 0)
        n_unstable = int(np.sum(eigenvalues.real > 1e-6))

        state_labels = self._build_state_labels()

        return ModalResult(
            eigenvalues=eigenvalues,
            frequencies_hz=frequencies_hz,
            damping_ratios=damping_ratios,
            participation_matrix=participation,
            state_labels=state_labels,
            mode_shapes=right_vecs.T,  # shape (n_modes, nx)
            A_red=A_red,
            n_unstable=n_unstable,
            electromechanical_modes=em_modes,
        )

    # ── Eigenvalue locus plot ──────────────────────────────────────────────
    def plot_eigenvalues(
        self,
        result: ModalResult,
        fig_path: str,
        highlight_em: bool = True,
    ) -> None:
        """Plot eigenvalue loci (σ vs jω) on the complex plane.

        Eigenvalues are displayed as points in the s-plane:
        - Stable region (σ < 0): left half-plane
        - Electromechanical modes are highlighted in orange
        - Unstable modes (σ > 0) are shown in red

        Parameters
        ----------
        result : ModalResult
        fig_path : str
            Output file path for the figure.
        highlight_em : bool
            If True, highlight electromechanical modes. Default True.
        """
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            print("matplotlib not available; skipping eigenvalue plot.")
            return

        fig, ax = plt.subplots(figsize=(9, 7))

        lam = result.eigenvalues

        # Color coding
        colors = []
        for k, lk in enumerate(lam):
            if lk.real > 1e-6:
                colors.append("red")
            elif k in result.electromechanical_modes and highlight_em:
                colors.append("darkorange")
            else:
                colors.append("steelblue")

        sc = ax.scatter(
            lam.real,
            lam.imag,
            c=colors,
            s=40,
            zorder=5,
            edgecolors="k",
            linewidths=0.3,
        )

        # Label electromechanical modes with frequency
        if highlight_em:
            for k in result.electromechanical_modes:
                if lam[k].imag >= 0:  # label only upper half
                    ax.annotate(
                        f"{result.frequencies_hz[k]:.2f}Hz\nζ={result.damping_ratios[k]:.2f}",
                        xy=(lam[k].real, lam[k].imag),
                        xytext=(8, 5),
                        textcoords="offset points",
                        fontsize=7,
                        color="darkorange",
                    )

        # Reference lines
        ax.axvline(0, color="black", lw=1.0, ls="-")
        ax.axhline(0, color="black", lw=0.5, ls="-")

        # 5% damping line
        theta_zeta = math.acos(0.05)
        lim_r = max(abs(lam.real.max()), 2.0)
        lim_i = max(abs(lam.imag.max()), 2.0)
        r_max = max(lim_r, lim_i) * 1.5
        for sign in [1, -1]:
            ax.plot(
                [-r_max * math.sin(math.acos(0.05)), 0],
                [sign * r_max * math.cos(math.acos(0.05)), 0],
                "k--",
                lw=0.8,
                alpha=0.5,
                label="5% damping" if sign == 1 else None,
            )

        ax.set_xlabel("Real part σ (s⁻¹)")
        ax.set_ylabel("Imaginary part jω (rad/s)")
        ax.set_title(
            f"Eigenvalue Loci — {result.n_unstable} unstable mode(s)\n"
            f"{len(result.electromechanical_modes)} electromechanical modes highlighted",
            fontsize=11,
        )

        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor="steelblue", label="Stable"),
            Patch(facecolor="darkorange", label="Electromechanical (0.1–2 Hz)"),
            Patch(facecolor="red", label="Unstable"),
        ]
        ax.legend(handles=legend_elements, loc="upper right", fontsize=9)
        ax.grid(True, alpha=0.3)

        fig.tight_layout()
        os.makedirs(os.path.dirname(os.path.abspath(fig_path)), exist_ok=True)
        fig.savefig(fig_path, dpi=150, bbox_inches="tight")
        plt.close(fig)

    # ── Participation factor heatmap ───────────────────────────────────────
    def participation_heatmap(
        self,
        result: ModalResult,
        fig_path: str,
        max_modes: int = 30,
        max_states: int = 40,
    ) -> None:
        """Plot participation factor heatmap (modes × states).

        Shows which state variables participate most in each oscillation mode.
        Row = mode, column = state variable.
        Color intensity = normalized participation factor (0–1).

        Parameters
        ----------
        result : ModalResult
        fig_path : str
            Output file path.
        max_modes : int
            Maximum number of modes to display. Default 30.
        max_states : int
            Maximum number of states to display. Default 40.
        """
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            print("matplotlib not available; skipping heatmap.")
            return

        # Restrict to electromechanical modes if available, else all modes
        em_idx = result.electromechanical_modes
        if em_idx:
            mode_idx = em_idx[:max_modes]
        else:
            mode_idx = list(range(min(max_modes, len(result.eigenvalues))))

        n_m = len(mode_idx)
        n_s = min(max_states, len(result.state_labels))

        P = result.participation_matrix[np.ix_(mode_idx, range(n_s))]

        # Build row labels (mode ID + frequency + damping)
        row_labels = []
        for k in mode_idx:
            lk = result.eigenvalues[k]
            row_labels.append(
                f"M{k}: {result.frequencies_hz[k]:.2f}Hz "
                f"ζ={result.damping_ratios[k]:.2f}"
            )
        col_labels = result.state_labels[:n_s]

        fig_h = max(4, 0.35 * n_m)
        fig_w = max(6, 0.3 * n_s)
        fig, ax = plt.subplots(figsize=(fig_w, fig_h))

        im = ax.imshow(P, aspect="auto", cmap="YlOrRd", vmin=0, vmax=1)
        plt.colorbar(im, ax=ax, label="Participation Factor (normalized)")

        ax.set_xticks(range(n_s))
        ax.set_xticklabels(col_labels, rotation=90, fontsize=7)
        ax.set_yticks(range(n_m))
        ax.set_yticklabels(row_labels, fontsize=7)

        ax.set_xlabel("State Variable")
        ax.set_ylabel("Mode")
        ax.set_title("Participation Factor Heatmap (Electromechanical Modes)", fontsize=11)

        fig.tight_layout()
        os.makedirs(os.path.dirname(os.path.abspath(fig_path)), exist_ok=True)
        fig.savefig(fig_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
