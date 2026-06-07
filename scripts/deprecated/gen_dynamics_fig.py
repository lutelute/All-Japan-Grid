"""DEPRECATED — superseded by ``gen_dynamics_fig_v2.py`` (Kundur 2-area model).

Both scripts write to ``papers/figs/fig_dynamics_improved.png``; use v2.
This file is retained only for reproducing earlier prototype results.

Improved dynamics figure for IEEJ paper.
D=0.05 (low damping) → clear oscillations visible.
Shows: (a) N-1 intra-area oscillations, (b) fault clear inter-area,
       (c) modal analysis eigenvalue plot.
"""

import os
import sys
import platform
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
from scipy.integrate import solve_ivp
from scipy import linalg

if platform.system() == "Darwin":
    plt.rcParams["font.family"] = ["Hiragino Sans", "Apple SD Gothic Neo", "sans-serif"]
else:
    try:
        import japanize_matplotlib  # noqa
    except ImportError:
        pass

OUT_DIR = "papers/figs"
os.makedirs(OUT_DIR, exist_ok=True)

# ── Classical machine model parameters ────────────────────────────
np.random.seed(42)
N_GEN = 12          # representative generators
OMEGA_S = 2 * np.pi * 50.0

# Inertia constants H (s) by generator type
H_VALS = np.array([6.5, 6.0, 5.5, 5.0, 4.5,  # large thermal/nuclear (bus 0-4)
                   4.0, 3.5, 3.0,               # medium thermal (bus 5-7)
                   2.5, 2.0, 1.5, 1.0])         # hydro/small (bus 8-11)
D_VALS = np.full(N_GEN, 0.05)                   # low damping → visible oscillations

# Synthetic Ybus (reduced, N_GEN x N_GEN)
# Create two electrical areas connected by a weak tie
def make_ybus(n_gen=12, n_area_a=6, tie_strength=0.05):
    Y = np.zeros((n_gen, n_gen), dtype=complex)
    # Area A: strong coupling among first n_area_a generators
    for i in range(n_area_a):
        for j in range(i+1, n_area_a):
            b_ij = np.random.uniform(1.0, 3.0)
            Y[i, j] = -1j * b_ij
            Y[j, i] = -1j * b_ij
            Y[i, i] += 1j * b_ij
            Y[j, j] += 1j * b_ij
    # Area B: strong coupling among remaining generators
    for i in range(n_area_a, n_gen):
        for j in range(i+1, n_gen):
            b_ij = np.random.uniform(0.8, 2.5)
            Y[i, j] = -1j * b_ij
            Y[j, i] = -1j * b_ij
            Y[i, i] += 1j * b_ij
            Y[j, j] += 1j * b_ij
    # Tie line: weak coupling A↔B
    for i in range(n_area_a):
        for j in range(n_area_a, n_gen):
            if np.random.rand() < 0.3:   # sparse tie
                b_ij = tie_strength
                Y[i, j] = -1j * b_ij
                Y[j, i] = -1j * b_ij
                Y[i, i] += 1j * b_ij
                Y[j, j] += 1j * b_ij
    return Y

Y = make_ybus(N_GEN, 6, 0.08)
E  = np.ones(N_GEN)  # internal voltage
Pm = np.random.uniform(0.3, 0.8, N_GEN)  # mechanical power

# Initial rotor angles from loadflow-like approximation
delta0 = np.zeros(N_GEN)
for i in range(N_GEN):
    delta0[i] = np.arcsin(Pm[i] / (E[i] * np.sum(np.abs(Y[i])) * 0.1 + 1e-6))
    delta0[i] = np.clip(delta0[i], -0.5, 0.5)
delta0[:6]  += np.random.uniform(0.0, 0.2, 6)   # Area A offset
delta0[6:]  += np.random.uniform(-0.2, 0.0, 6)   # Area B offset


def Pe_i(delta, i, Y, E):
    """Electrical power of generator i."""
    pe = 0.0
    for j in range(len(delta)):
        G_ij = Y[i, j].real
        B_ij = Y[i, j].imag
        pe += E[i] * E[j] * (G_ij * np.cos(delta[i]-delta[j]) +
                              B_ij * np.sin(delta[i]-delta[j]))
    return pe


def swing_rhs(t, state, H, D, Pm, Y, E, omega_s, fault=None,
              fault_gen=None, t_fault=None, t_clear=None):
    n = len(H)
    delta = state[:n]
    omega = state[n:]
    ddelta = np.zeros(n)
    domega = np.zeros(n)

    # Apply fault: trip generator or 3-phase fault
    Y_eff = Y.copy()
    if fault == "trip" and fault_gen is not None:
        if t > (t_fault or 1.0):
            Pm_eff = Pm.copy()
            Pm_eff[fault_gen] = 0.0
            E_eff = E.copy()
            E_eff[fault_gen] = 0.0
        else:
            Pm_eff, E_eff = Pm.copy(), E.copy()
    elif fault == "fault_clear" and fault_gen is not None:
        Pm_eff = Pm.copy()
        E_eff = E.copy()
        if (t_fault or 1.0) <= t <= (t_clear or 1.1):
            E_eff[fault_gen] = 0.0   # 3-phase fault → E=0
    else:
        Pm_eff, E_eff = Pm.copy(), E.copy()

    for i in range(n):
        pe = Pe_i(delta, i, Y_eff, E_eff)
        M_i = 2 * H[i] / omega_s
        domega[i] = (Pm_eff[i] - pe - D[i] * omega[i]) / M_i
        ddelta[i] = omega[i]

    return np.concatenate([ddelta, domega])


# ── Simulation 1: N-1 generator trip (intra-area) ─────────────────
T_END, DT = 15.0, 0.01
t_eval = np.arange(0, T_END, DT)
state0 = np.concatenate([delta0, np.zeros(N_GEN)])

# Trip generator 0 (largest in Area A)
sol_trip = solve_ivp(
    swing_rhs, [0, T_END], state0, t_eval=t_eval, method="RK45",
    max_step=DT,
    args=(H_VALS, D_VALS, Pm, Y, E, OMEGA_S, "trip", 0, 1.0, None)
)
delta_trip = sol_trip.y[:N_GEN]  # [n_gen, n_t]

# ── Simulation 2: 3-phase fault (inter-area excitation) ───────────
sol_fault = solve_ivp(
    swing_rhs, [0, T_END], state0, t_eval=t_eval, method="RK45",
    max_step=DT,
    args=(H_VALS, D_VALS, Pm, Y, E, OMEGA_S, "fault_clear", 3, 1.0, 1.12)
)
delta_fault = sol_fault.y[:N_GEN]

# COI angle
def coi(delta, H):
    return np.dot(H, delta) / H.sum()

coi_trip  = np.array([coi(delta_trip[:, k], H_VALS) for k in range(delta_trip.shape[1])])
coi_fault = np.array([coi(delta_fault[:, k], H_VALS) for k in range(delta_fault.shape[1])])

# ── Modal analysis ──────────────────────────────────────────────────
def modal_analysis(Y, E, delta_eq, H, D, omega_s):
    n = len(H)
    M = np.diag(2 * H / omega_s)
    D_mat = np.diag(D)
    # Synchronizing torque matrix K_ij = dPe_i/ddelta_j
    K = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if i == j:
                s = 0.0
                for k in range(n):
                    if k != i:
                        G_ij = Y[i, k].real
                        B_ij = Y[i, k].imag
                        s += E[i]*E[k]*(
                            -G_ij*np.sin(delta_eq[i]-delta_eq[k]) +
                             B_ij*np.cos(delta_eq[i]-delta_eq[k]))
                K[i, i] = s
            else:
                G_ij = Y[i, j].real
                B_ij = Y[i, j].imag
                K[i, j] = -E[i]*E[j]*(
                    -G_ij*np.sin(delta_eq[i]-delta_eq[j]) +
                     B_ij*np.cos(delta_eq[i]-delta_eq[j]))
    # State matrix
    Minv = np.linalg.inv(M)
    A = np.block([[np.zeros((n,n)), np.eye(n)],
                  [-Minv @ K,      -Minv @ D_mat]])
    eigvals = linalg.eigvals(A)
    return eigvals

eigvals = modal_analysis(Y, E, delta0, H_VALS, D_VALS, OMEGA_S)
eig_c = eigvals[eigvals.imag > 0]   # keep positive imaginary part
freq_hz = eig_c.imag / (2 * np.pi)
zeta    = -eig_c.real / np.abs(eig_c)


# ── Plot ────────────────────────────────────────────────────────────
AREA_A_COLOR = "#1565c0"   # blue
AREA_B_COLOR = "#b71c1c"   # red

fig = plt.figure(figsize=(15, 5.5), facecolor="white")
gs = gridspec.GridSpec(1, 3, wspace=0.28, figure=fig)

# (a) N-1 trip — rotor angle deviation from COI
ax1 = fig.add_subplot(gs[0])
t = sol_trip.t
for i in range(N_GEN):
    col = AREA_A_COLOR if i < 6 else AREA_B_COLOR
    lw  = 1.5 if i < 2 or (6 <= i < 8) else 0.8
    ax1.plot(t, np.degrees(delta_trip[i] - coi_trip), color=col,
             lw=lw, alpha=0.75)
ax1.axvline(1.0, color="#888", lw=0.8, ls="--", label="t=1 s 脱落")
ax1.set_xlabel("時間 (s)", fontsize=10)
ax1.set_ylabel(r"$\delta_i - \delta_{\rm COI}$ (deg)", fontsize=10)
ax1.set_title("(a) N-1 発電機脱落\n(エリア内振動)", fontsize=10, pad=5, color="#222")
ax1.set_xlim(0, T_END)
ax1.set_ylim(-20, 20)
ax1.grid(color="#eee", lw=0.5)
from matplotlib.lines import Line2D
ax1.legend(handles=[
    Line2D([0],[0], color=AREA_A_COLOR, lw=2, label="エリアA"),
    Line2D([0],[0], color=AREA_B_COLOR, lw=2, label="エリアB"),
], fontsize=8, loc="upper right")

# (b) 3-phase fault — inter-area oscillation
ax2 = fig.add_subplot(gs[1])
t2 = sol_fault.t
for i in range(N_GEN):
    col = AREA_A_COLOR if i < 6 else AREA_B_COLOR
    lw  = 1.5 if i < 2 or (6 <= i < 8) else 0.8
    ax2.plot(t2, np.degrees(delta_fault[i] - coi_fault), color=col,
             lw=lw, alpha=0.75)
ax2.axvspan(1.0, 1.12, alpha=0.12, color="#ff0000", label="事故中")
ax2.axvline(1.0,  color="#ff4444", lw=0.8, ls="--")
ax2.axvline(1.12, color="#ff4444", lw=0.8, ls="--")
ax2.set_xlabel("時間 (s)", fontsize=10)
ax2.set_ylabel(r"$\delta_i - \delta_{\rm COI}$ (deg)", fontsize=10)
ax2.set_title("(b) 3相短絡・遮断 (120ms)\n(エリア間振動の励起)", fontsize=10, pad=5, color="#222")
ax2.set_xlim(0, T_END)
ax2.grid(color="#eee", lw=0.5)
ax2.legend(handles=[
    Line2D([0],[0], color=AREA_A_COLOR, lw=2, label="エリアA (G1-G6)"),
    Line2D([0],[0], color=AREA_B_COLOR, lw=2, label="エリアB (G7-G12)"),
    mpatches.Patch(color="#ff0000", alpha=0.25, label="事故期間"),
], fontsize=7.5, loc="upper right")

# (c) Modal analysis — freq vs damping ratio
ax3 = fig.add_subplot(gs[2])
# Color by frequency zone
INTER_COLOR = "#e65100"
LOCAL_COLOR = "#1565c0"
for f, z in zip(freq_hz, zeta):
    if 0 < f < 100:  # valid modes
        col  = INTER_COLOR if f < 0.8 else LOCAL_COLOR
        sz   = 60 if z < 0.1 else 30
        mrk  = "^" if f < 0.8 else "o"
        ax3.scatter(z * 100, f, c=col, s=sz, marker=mrk, alpha=0.85,
                    zorder=3, edgecolors="white", linewidths=0.4)

# Reference lines
ax3.axhline(0.8, color="#999", lw=0.8, ls="--", label="0.8 Hz 境界")
ax3.axvline(5,   color="#aaa", lw=0.8, ls=":",  label="5% 減衰比")
ax3.axvline(10,  color="#bbb", lw=0.8, ls=":")
ax3.fill_betweenx([0, 0.8], 0, 100, alpha=0.07, color="#ff6600", zorder=0)
ax3.fill_betweenx([0.8, 8], 0, 100, alpha=0.05, color="#1565c0", zorder=0)
ax3.text(60, 0.35, "系間モード\n(要監視)", fontsize=7.5, color="#e65100", ha="center")
ax3.text(60, 3.5,  "局所モード", fontsize=7.5, color="#1565c0", ha="center")
ax3.set_xlabel("減衰比 $\\zeta$ (%)", fontsize=10)
ax3.set_ylabel("振動周波数 $f_k$ (Hz)", fontsize=10)
ax3.set_title("(c) モード解析\n(固有値分布)", fontsize=10, pad=5, color="#222")
ax3.set_xlim(0, 80)
ax3.set_ylim(0, 8)
ax3.grid(color="#eee", lw=0.5)
ax3.legend(fontsize=7.5, loc="upper right")

import matplotlib.patches as mpatches
for ax in [ax1, ax2, ax3]:
    ax.set_facecolor("white")
    for sp in ax.spines.values():
        sp.set_color("#ccc")

fig.suptitle(
    "古典機モデルによる過渡安定解析・モード解析 (H=2-6.5 s, D=0.05 pu)",
    fontsize=11, y=1.01, color="#111"
)

out = f"{OUT_DIR}/fig_dynamics_improved.png"
plt.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
plt.close()
print(f"Saved: {out}")
