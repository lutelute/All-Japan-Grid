"""
N-1 and N-2 transient stability analysis for multiple regions.

For each of Hokkaido, Tohoku, Kyushu:
  - Loads plant GeoJSON data and selects generators with meaningful capacity
  - Assigns H (inertia) by fuel type
  - Builds a geographically-motivated reduced Ybus:
      B_ij = k / haversine_distance_km(i, j)   for pairs within 200 km
  - Runs N-1 (each generator tripped one at a time) and N-2 (all pairs)
  - Reports: region, n_gen, n_cases, n_unstable, max_angle_deg, elapsed time
  - Saves results to papers/figs/nx_multiregion_results.json
  - Saves comparison figure to papers/figs/fig_nx_multiregion.png

Usage:
    cd /path/to/All-Japan-Grid
    python scripts/gen_nx_multiregion.py
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from itertools import combinations
from typing import Dict, List, Tuple, Optional

import numpy as np
from scipy.integrate import solve_ivp
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ── Add project root to path ─────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ── Constants ─────────────────────────────────────────────────────────
OMEGA_S   = 2 * np.pi * 50.0   # rad/s (50 Hz, all Japan)
OUT_DIR   = os.path.join(ROOT, "papers", "figs")
DATA_DIR  = os.path.join(ROOT, "data")

# Inertia constants H (seconds) by fuel type — standard power systems values
H_BY_FUEL: Dict[str, float] = {
    "nuclear":    6.5,
    "coal":       6.5,
    "hydro":      4.0,
    "gas":        5.0,
    "lng":        5.0,
    "oil":        5.0,
    "geothermal": 4.0,
    "wind":       3.5,
    "biomass":    4.0,
    "biofuel":    4.0,
    "waste":      4.0,
    "solar":      0.0,   # inverter-based: excluded (no inertia)
    "battery":    0.0,   # excluded
}
H_DEFAULT = 5.0   # fallback for unmapped fuels

# Typical installed capacity (MW) by fuel type — used when actual data is unavailable.
# Based on representative Japanese power plant statistics.
TYPICAL_CAP_BY_FUEL: Dict[str, float] = {
    "nuclear":    1100.0,
    "coal":        700.0,
    "gas":         500.0,
    "lng":         500.0,
    "oil":         400.0,
    "hydro":       200.0,
    "geothermal":   50.0,
    "biomass":     100.0,
    "biofuel":      50.0,
    "waste":        30.0,
    "wind":        100.0,
}

# Coupling scale: B_ij = COUPLING_K / distance_km
# Calibrated so inter-area coupling ~ 0.1–0.3 pu for 200 km separation
COUPLING_K    = 60.0    # pu·km  (gives B ≈ 0.3 at 200 km)
MAX_DIST_KM   = 250.0   # only couple generators within this distance
MIN_CAPACITY  = 10.0    # MW — minimum capacity to include as synchronous gen

# Stability threshold
ANGLE_LIMIT_RAD = np.pi   # |δ_i - δ_j| < π  (separation limit)

# Minimum generators to run a meaningful N-x analysis
MIN_GENS_FOR_ANALYSIS = 3

os.makedirs(OUT_DIR, exist_ok=True)


# ── Haversine distance ────────────────────────────────────────────────
def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in km between two (lon, lat) points.

    Delegates to the canonical src.utils.geo_utils implementation.
    """
    from src.utils.geo_utils import haversine_distance
    return haversine_distance(lat1, lon1, lat2, lon2)


# ── Load and filter generators from GeoJSON ──────────────────────────
def load_generators(region: str) -> List[Dict]:
    """Return list of generator dicts with keys: name, lon, lat, cap_mw, fuel, H, Pm."""
    path = os.path.join(DATA_DIR, f"{region}_plants.geojson")
    with open(path) as f:
        gj = json.load(f)

    gens = []
    for feat in gj["features"]:
        props = feat["properties"]
        coords = feat["geometry"]["coordinates"]
        lon, lat = float(coords[0]), float(coords[1])

        fuel = (props.get("fuel_type") or "unknown").lower().strip()

        # Skip inverter-based, non-synchronous, and unclassifiable plants
        if fuel in ("solar", "battery", "unknown") or H_BY_FUEL.get(fuel, H_DEFAULT) == 0.0:
            continue
        # Skip URL-like strings that ended up as fuel types (data quality issue)
        if fuel.startswith("http"):
            continue

        cap = props.get("capacity_mw")
        # Treat None, missing, or negative as "unknown" — assign typical value by fuel.
        # This is especially important for regions like Kyushu where OSM capacity_mw = -1.
        if cap is None or cap < 0:
            cap = TYPICAL_CAP_BY_FUEL.get(fuel, 100.0)
        elif cap < MIN_CAPACITY:
            continue   # too small to matter dynamically

        H = H_BY_FUEL.get(fuel, H_DEFAULT)

        gens.append({
            "name": props.get("_display_name") or props.get("name") or f"{region}_{len(gens)}",
            "lon": lon,
            "lat": lat,
            "cap_mw": cap,
            "fuel": fuel,
            "H": H,
        })

    # Assign Pm proportional to capacity (pu on system base inferred from total)
    # For generators without known capacity, assign median of known ones
    caps_known = [g["cap_mw"] for g in gens if g["cap_mw"] is not None]
    cap_median = float(np.median(caps_known)) if caps_known else 100.0
    total_cap = sum(g["cap_mw"] if g["cap_mw"] is not None else cap_median for g in gens)
    if total_cap <= 0:
        total_cap = 1.0

    for g in gens:
        c = g["cap_mw"] if g["cap_mw"] is not None else cap_median
        g["Pm"] = c / total_cap   # pu — sum to ~1.0 across all gens

    return gens


# ── Build geographic Ybus ──────────────────────────────────────────────
def build_geographic_ybus(gens: List[Dict]) -> np.ndarray:
    """Kron-reduced Ybus from geographic distances.

    Y_ij = +j * B_ij   (off-diagonal, admittance between i and j)
    Y_ii = -j * sum_j(B_ij)   (diagonal, sum of all branch admittances)

    B_ij = COUPLING_K / dist_km   if dist_km <= MAX_DIST_KM, else 0
    """
    n = len(gens)
    Y = np.zeros((n, n), dtype=complex)

    for i in range(n):
        for j in range(i + 1, n):
            d_km = haversine_km(gens[i]["lon"], gens[i]["lat"],
                                gens[j]["lon"], gens[j]["lat"])
            if d_km <= MAX_DIST_KM and d_km > 0.1:
                B = COUPLING_K / d_km
                Y[i, j] += 1j * B
                Y[j, i] += 1j * B
                Y[i, i] -= 1j * B
                Y[j, j] -= 1j * B

    # Ensure every generator has at least one connection (connect to nearest)
    for i in range(n):
        if abs(Y[i, i]) < 1e-12:
            # find nearest neighbor
            dists = []
            for j in range(n):
                if j != i:
                    d = haversine_km(gens[i]["lon"], gens[i]["lat"],
                                     gens[j]["lon"], gens[j]["lat"])
                    dists.append((d, j))
            if dists:
                dists.sort()
                _, j_near = dists[0]
                d_km = dists[0][0]
                B = COUPLING_K / max(d_km, 1.0)
                Y[i, j_near] += 1j * B
                Y[j_near, i] += 1j * B
                Y[i, i] -= 1j * B
                Y[j_near, j_near] -= 1j * B

    return Y


# ── Electrical power vector ────────────────────────────────────────────
def Pe_vector(delta: np.ndarray, E: np.ndarray, Y: np.ndarray) -> np.ndarray:
    """Classical-model electrical power Pe_i = Σ_j E_i E_j [G cos + B sin].

    Fully vectorised: O(n²) numpy ops, no Python loops.
    """
    # delta_ij[i,j] = delta[i] - delta[j]
    diff = delta[:, None] - delta[None, :]   # (n, n)
    EiEj = E[:, None] * E[None, :]           # (n, n)
    G = Y.real
    B = Y.imag
    Pe = np.sum(EiEj * (G * np.cos(diff) + B * np.sin(diff)), axis=1)
    return Pe


# ── Compute equilibrium angles ─────────────────────────────────────────
def compute_equilibrium(Pm_centered: np.ndarray, E: np.ndarray,
                        Y: np.ndarray) -> Tuple[np.ndarray, float]:
    """Find δ₀ such that Pe(δ₀) = Pm_centered using scipy fsolve.

    Pm_centered must already be zero-sum (mean-subtracted).
    Returns (delta_eq, max_residual_pu).
    """
    from scipy.optimize import fsolve
    n = len(Pm_centered)

    # Initial guess: angles proportional to Pm spread over [-0.5, 0.5] rad
    # Sort angle order to match Pm ordering (large injectors lead in angle)
    delta0 = np.linspace(-0.4, 0.4, n)

    def residual(delta):
        # Fix reference bus (gen 0) to 0 to remove rank deficiency
        Pe = Pe_vector(delta, E, Y)
        res = Pe - Pm_centered
        res[0] = delta[0]   # reference constraint
        return res

    # fsolve with multiple starts if needed
    best_delta = delta0.copy()
    best_err = np.inf
    for scale in [1.0, 0.5, 0.2]:
        d0 = np.linspace(-0.4 * scale, 0.4 * scale, n)
        try:
            sol = fsolve(residual, d0, full_output=True)
            d_sol = sol[0]
            Pe_chk = Pe_vector(d_sol, E, Y)
            err = float(np.max(np.abs(Pe_chk - Pm_centered)))
            if err < best_err:
                best_err = err
                best_delta = d_sol
            if best_err < 1e-4:
                break
        except Exception:
            pass

    return best_delta, best_err


# ── Run N-x contingency ────────────────────────────────────────────────
def run_contingency(
    gens: List[Dict],
    Y: np.ndarray,
    trip_indices: List[int],
    delta0: np.ndarray,
    E: np.ndarray,
    Pm: np.ndarray,
    t_fault: float = 1.0,
    t_end: float = 10.0,
    dt: float = 0.05,
) -> Tuple[bool, float]:
    """Simulate N-x event: trip generators in trip_indices at t_fault.

    Returns (stable, max_angle_separation_rad).
    """
    n = len(gens)
    H_arr = np.array([g["H"] for g in gens])
    D_arr = np.full(n, 0.05)   # low damping → visible oscillations
    tripped = set(trip_indices)

    y0 = np.concatenate([delta0.copy(), np.zeros(n)])
    M = 2.0 * H_arr / OMEGA_S

    # Pre-compute post-trip Pm: zero out tripped generators
    Pm_post = Pm.copy()
    for idx in tripped:
        Pm_post[idx] = 0.0

    def rhs(t, y):
        delta = y[:n]
        omega = y[n:]
        Pe = Pe_vector(delta, E, Y)
        Pm_eff = Pm_post if t >= t_fault else Pm
        ddw = (Pm_eff - Pe - D_arr * omega) / M
        return np.concatenate([omega, ddw])

    t_eval = np.arange(0, t_end + dt, dt)
    sol = solve_ivp(
        rhs, [0, t_end], y0, method="RK45",
        t_eval=t_eval, rtol=1e-4, atol=1e-6,
        max_step=dt * 4,
    )

    delta_t = sol.y[:n, :]
    sep = float(np.max(np.max(delta_t, axis=0) - np.min(delta_t, axis=0)))
    stable = sep < ANGLE_LIMIT_RAD

    return stable, sep


# ── Analyse one region ────────────────────────────────────────────────
def analyse_region(region: str, max_gens: int = 30,
                   run_n2: bool = True) -> Dict:
    """Full N-1 / N-2 transient stability analysis for one region.

    To keep runtime manageable, limits to max_gens largest generators.
    """
    print(f"\n{'='*60}")
    print(f"  Region: {region.upper()}")
    print(f"{'='*60}")

    t0_total = time.time()

    # 1. Load generators
    all_gens = load_generators(region)
    print(f"  Loaded {len(all_gens)} synchronous generators (capacity >= {MIN_CAPACITY} MW or fuel-typed)")

    # Filter to generators with known or inferable capacity, prefer largest
    # Sort by capacity descending (None treated as median)
    caps_known = [g["cap_mw"] for g in all_gens if g["cap_mw"] is not None]
    cap_median = float(np.median(caps_known)) if caps_known else 100.0

    # Require at least MIN_CAPACITY MW — already filtered in load_generators
    # For regions without capacity data (Kyushu), keep all non-solar/battery
    # and use a fuel-tier priority instead
    fuel_priority = {"nuclear": 5, "coal": 4, "gas": 4, "lng": 4,
                     "oil": 3, "hydro": 3, "geothermal": 2,
                     "biomass": 1, "biofuel": 1, "waste": 1, "wind": 1}

    def sort_key(g):
        cap = g["cap_mw"] if g["cap_mw"] is not None else cap_median
        prio = fuel_priority.get(g["fuel"], 0)
        return -(cap * 10 + prio)

    all_gens.sort(key=sort_key)

    # Deduplicate by location (within 0.5 km)
    deduped = []
    for g in all_gens:
        is_dup = False
        for d in deduped:
            if haversine_km(g["lon"], g["lat"], d["lon"], d["lat"]) < 0.5:
                is_dup = True
                break
        if not is_dup:
            deduped.append(g)

    gens = deduped[:max_gens]

    print(f"  Selected {len(gens)} generators (after dedup + top-{max_gens} by capacity/priority)")
    for g in gens[:8]:
        print(f"    {g['name'][:40]:40s}  {g['fuel']:12s}  "
              f"cap={g['cap_mw'] or '?':>8}  H={g['H']:.1f}s")
    if len(gens) > 8:
        print(f"    ... ({len(gens)-8} more)")

    if len(gens) < MIN_GENS_FOR_ANALYSIS:
        print(f"  WARNING: fewer than {MIN_GENS_FOR_ANALYSIS} generators — skipping analysis")
        return {
            "region": region, "n_generators": len(gens),
            "n1_cases": 0, "n1_unstable": 0, "n1_max_angle_deg": 0.0, "n1_time_s": 0.0,
            "n2_cases": 0, "n2_unstable": 0, "n2_max_angle_deg": 0.0, "n2_time_s": 0.0,
            "error": "too few generators",
        }

    n = len(gens)

    # 2. Build Ybus
    Y = build_geographic_ybus(gens)
    E = np.ones(n)   # unit internal voltages (classical model)

    # Re-normalise Pm proportional to capacity.
    # For a lossless network, net power injections must sum to zero.
    # We use Pm_centered = Pm_raw - mean(Pm_raw), so generators above average
    # inject power and those below absorb (represent loads in classical model).
    caps_eff = np.array([g["cap_mw"] if g["cap_mw"] is not None else cap_median
                         for g in gens])
    Pm_raw = caps_eff / caps_eff.sum()     # proportional, sums to 1.0
    Pm = Pm_raw - Pm_raw.mean()           # zero-sum: required for lossless network

    # 3. Find equilibrium via Newton-Raphson / scipy fsolve
    delta0, eq_err = compute_equilibrium(Pm, E, Y)
    print(f"  Equilibrium: max |Pe - Pm| = {eq_err:.4f} pu  "
          f"(angle spread: {np.degrees(delta0.max()-delta0.min()):.1f}°)")

    # 4. N-1 contingency
    print(f"\n  Running N-1 ({n} cases)...")
    t0 = time.time()
    n1_results = []
    for i in range(n):
        stable, sep = run_contingency(gens, Y, [i], delta0, E, Pm)
        n1_results.append((i, stable, np.degrees(sep)))
        status = "STABLE  " if stable else "UNSTABLE"
        if not stable or sep > 0.3:   # print noteworthy cases
            print(f"    Trip gen[{i:2d}] {gens[i]['name'][:30]:30s} "
                  f"→ {status}  Δδ_max={np.degrees(sep):7.2f}°")

    t_n1 = time.time() - t0
    n1_unstable = sum(1 for _, s, _ in n1_results if not s)
    n1_max_angle = max(sep for _, _, sep in n1_results)

    print(f"  N-1 done in {t_n1:.1f}s: {n1_unstable}/{n} unstable, "
          f"max angle sep = {n1_max_angle:.1f}°")

    # 5. N-2 contingency
    n2_cases = math.comb(n, 2)
    n2_unstable = 0
    n2_max_angle = 0.0
    t_n2 = 0.0

    if run_n2 and n >= 3:
        print(f"\n  Running N-2 ({n2_cases} cases)...")
        t0 = time.time()
        for i, j in combinations(range(n), 2):
            stable, sep = run_contingency(gens, Y, [i, j], delta0, E, Pm)
            if not stable:
                n2_unstable += 1
            if np.degrees(sep) > n2_max_angle:
                n2_max_angle = np.degrees(sep)
        t_n2 = time.time() - t0
        print(f"  N-2 done in {t_n2:.1f}s: {n2_unstable}/{n2_cases} unstable, "
              f"max angle sep = {n2_max_angle:.1f}°")
    else:
        print(f"  N-2 skipped (run_n2={run_n2})")

    t_total = time.time() - t0_total
    result = {
        "region": region,
        "n_generators": n,
        "n1_cases": n,
        "n1_unstable": n1_unstable,
        "n1_max_angle_deg": round(n1_max_angle, 2),
        "n1_time_s": round(t_n1, 2),
        "n2_cases": n2_cases if run_n2 else 0,
        "n2_unstable": n2_unstable,
        "n2_max_angle_deg": round(n2_max_angle, 2),
        "n2_time_s": round(t_n2, 2),
        "total_time_s": round(t_total, 2),
        "equilibrium_error_pu": round(float(eq_err), 4),
    }
    return result


# ── Generate comparison figure ─────────────────────────────────────────
def generate_figure(results: List[Dict]) -> str:
    """Create comparison bar/table figure for N-1 and N-2 results."""
    valid = [r for r in results if r.get("n1_cases", 0) > 0]
    if not valid:
        print("No valid results to plot.")
        return ""

    regions = [r["region"].capitalize() for r in valid]
    x = np.arange(len(regions))

    # Data
    n_gens    = [r["n_generators"] for r in valid]
    n1_cases  = [r["n1_cases"] for r in valid]
    n1_uns    = [r["n1_unstable"] for r in valid]
    n1_stab   = [c - u for c, u in zip(n1_cases, n1_uns)]
    n1_ang    = [r["n1_max_angle_deg"] for r in valid]
    n2_cases  = [r["n2_cases"] for r in valid]
    n2_uns    = [r["n2_unstable"] for r in valid]
    n2_ang    = [r["n2_max_angle_deg"] for r in valid]

    fig, axes = plt.subplots(1, 3, figsize=(14, 5.0))
    fig.patch.set_facecolor("white")

    BAR_W  = 0.35
    C_STAB = "#1565c0"   # stable cases: blue
    C_UNST = "#c62828"   # unstable cases: red
    C_ANG  = "#e65100"   # angle: orange

    # ── (a) N-1 stability bar chart ───────────────────────────────────
    ax = axes[0]
    ax.bar(x - BAR_W/2, n1_stab, BAR_W, label="Stable",   color=C_STAB, alpha=0.85)
    ax.bar(x + BAR_W/2, n1_uns,  BAR_W, label="Unstable", color=C_UNST, alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(regions, fontsize=10)
    ax.set_ylabel("Number of N-1 contingencies", fontsize=10)
    ax.set_title("(a)  N-1 Stability Results\n(per region)", fontsize=10)
    ax.legend(fontsize=8, framealpha=0.8)
    ax.grid(axis="y", color="#eeeeee", lw=0.7, zorder=0)
    ax.set_axisbelow(True)
    # Annotate total cases
    for xi, (ns, nu) in enumerate(zip(n1_stab, n1_uns)):
        total = ns + nu
        ax.text(xi, total + 0.3, f"n={total}", ha="center", fontsize=8, color="#333")
    ax.set_facecolor("white")
    for sp in ax.spines.values():
        sp.set_color("#cccccc")

    # ── (b) N-2 stability bar chart ───────────────────────────────────
    ax = axes[1]
    n2_stab = [c - u for c, u in zip(n2_cases, n2_uns)]
    bars_s = ax.bar(x - BAR_W/2, n2_stab, BAR_W, label="Stable",   color=C_STAB, alpha=0.85)
    bars_u = ax.bar(x + BAR_W/2, n2_uns,  BAR_W, label="Unstable", color=C_UNST, alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(regions, fontsize=10)
    ax.set_ylabel("Number of N-2 contingencies", fontsize=10)
    ax.set_title("(b)  N-2 Stability Results\n(per region)", fontsize=10)
    ax.legend(fontsize=8, framealpha=0.8)
    ax.grid(axis="y", color="#eeeeee", lw=0.7, zorder=0)
    ax.set_axisbelow(True)
    for xi, (ns, nu) in enumerate(zip(n2_stab, n2_uns)):
        total = ns + nu
        ax.text(xi, total + max(n2_cases)*0.01, f"n={total}", ha="center",
                fontsize=8, color="#333")
    ax.set_facecolor("white")
    for sp in ax.spines.values():
        sp.set_color("#cccccc")

    # ── (c) Maximum angle separation ──────────────────────────────────
    ax = axes[2]
    width = 0.35
    rects_n1 = ax.bar(x - width/2, n1_ang, width, label="N-1 max", color=C_STAB, alpha=0.85)
    rects_n2 = ax.bar(x + width/2, n2_ang, width, label="N-2 max", color=C_ANG,  alpha=0.85)
    ax.axhline(180.0, color=C_UNST, lw=1.2, ls="--", label="π limit (instability)")
    ax.set_xticks(x)
    ax.set_xticklabels(regions, fontsize=10)
    ax.set_ylabel(r"Max rotor angle separation $\Delta\delta_{\max}$ (°)", fontsize=10)
    ax.set_title("(c)  Peak Angle Separation\n(worst contingency)", fontsize=10)
    ax.legend(fontsize=8, framealpha=0.8)
    ax.grid(axis="y", color="#eeeeee", lw=0.7, zorder=0)
    ax.set_axisbelow(True)
    ax.set_facecolor("white")
    for sp in ax.spines.values():
        sp.set_color("#cccccc")

    # Annotate angle values
    for xi, (a1, a2) in enumerate(zip(n1_ang, n2_ang)):
        ax.text(xi - width/2, a1 + 3, f"{a1:.0f}°", ha="center", fontsize=8, color=C_STAB)
        ax.text(xi + width/2, a2 + 3, f"{a2:.0f}°", ha="center", fontsize=8, color=C_ANG)

    fig.suptitle(
        "N-1 and N-2 Transient Stability Analysis — All-Japan-Grid\n"
        "Classical swing model, geographic Kron-reduced Ybus, 50 Hz system",
        fontsize=11, y=1.02, color="#111",
    )
    plt.tight_layout()

    out_path = os.path.join(OUT_DIR, "fig_nx_multiregion.png")
    plt.savefig(out_path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"\nSaved figure: {out_path}")
    return out_path


# ── Summary table printer ──────────────────────────────────────────────
def print_summary_table(results: List[Dict]) -> None:
    header = (
        f"{'Region':12s} {'n_gen':>6} "
        f"{'N-1 cases':>10} {'N-1 unstable':>13} {'N-1 max°':>9} "
        f"{'N-2 cases':>10} {'N-2 unstable':>13} {'N-2 max°':>9} "
        f"{'time(s)':>8}"
    )
    sep = "─" * len(header)
    print(f"\n{sep}")
    print(header)
    print(sep)
    for r in results:
        print(
            f"{r['region']:12s} {r['n_generators']:>6} "
            f"{r['n1_cases']:>10} {r['n1_unstable']:>13} {r['n1_max_angle_deg']:>9.1f} "
            f"{r['n2_cases']:>10} {r['n2_unstable']:>13} {r['n2_max_angle_deg']:>9.1f} "
            f"{r['total_time_s']:>8.1f}"
        )
    print(sep)


# ── Main ──────────────────────────────────────────────────────────────
def main():
    REGIONS = ["hokkaido", "tohoku", "kyushu"]

    # Limit number of generators per region to keep runtime reasonable.
    # N-2 scales as C(n,2) = n*(n-1)/2 simulations.
    # With n=15 and vectorised Pe: C(15,2)=105 cases × ~0.05s ≈ 5s per region.
    MAX_GENS   = 15
    RUN_N2     = True
    T_END      = 10.0

    print("=" * 60)
    print("  N-1 / N-2 Transient Stability — Multi-Region Analysis")
    print(f"  Regions: {', '.join(REGIONS)}")
    print(f"  Max generators per region: {MAX_GENS}")
    print(f"  Simulation time: {T_END}s  |  Run N-2: {RUN_N2}")
    print("=" * 60)

    t_start = time.time()
    results = []
    for region in REGIONS:
        try:
            r = analyse_region(region, max_gens=MAX_GENS, run_n2=RUN_N2)
            results.append(r)
        except Exception as exc:
            print(f"  ERROR in {region}: {exc}")
            import traceback; traceback.print_exc()
            results.append({"region": region, "n_generators": 0,
                            "n1_cases": 0, "n1_unstable": 0,
                            "n1_max_angle_deg": 0.0, "n1_time_s": 0.0,
                            "n2_cases": 0, "n2_unstable": 0,
                            "n2_max_angle_deg": 0.0, "n2_time_s": 0.0,
                            "total_time_s": 0.0, "error": str(exc)})

    # Print summary
    print_summary_table(results)
    print(f"\nTotal elapsed: {time.time() - t_start:.1f}s")

    # Save JSON
    json_path = os.path.join(OUT_DIR, "nx_multiregion_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Saved JSON: {json_path}")

    # Generate figure
    generate_figure(results)

    return results


if __name__ == "__main__":
    main()
