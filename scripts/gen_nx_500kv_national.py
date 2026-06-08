"""
全国500kV送電網の実GeoJSONトポロジからYbusを構築し、N-1/N-2過渡安定解析を実施する。

Step 1: 500kV変電所をバスとして読み込み
Step 2: 500kV送電線エンドポイントマッチングでYbus構築
Step 3: 接続成分の抽出（最大連結成分）
Step 4: 発電機の500kVバスへのマッピング
Step 5: 動揺方程式と平衡点
Step 6: N-1解析（全バス）
Step 7: N-2解析（最悪N-1上位30ケース）
Step 8: 出力図

Usage:
    cd /path/to/All-Japan-Grid
    python scripts/gen_nx_500kv_national.py
"""

from __future__ import annotations

import json
import math
import os
import platform
import sys
import time
from itertools import combinations
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.integrate import solve_ivp
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.cm as cm
import matplotlib.colors as mcolors

# ── Project root setup ───────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

DATA_DIR = os.path.join(ROOT, "data")
OUT_DIR  = os.path.join(ROOT, "papers", "figs")
os.makedirs(OUT_DIR, exist_ok=True)

# ── Japanese font (macOS) ────────────────────────────────────────────
if platform.system() == "Darwin":
    matplotlib.rcParams["font.family"] = "Hiragino Sans"

# ── Constants ────────────────────────────────────────────────────────
REGIONS = [
    "hokkaido","tohoku","tokyo","chubu",
    "hokuriku","kansai","chugoku","shikoku","kyushu","okinawa"
]

OMEGA_S = 2 * math.pi * 50.0  # rad/s (50 Hz)

# 500kV 線路インピーダンス基準値 (1000 MVA base)
Z_BASE         = 500.0 ** 2 / 1000.0   # 250 Ω
R_PU_PER_KM    = 0.012 / Z_BASE        # 4.8e-5 pu/km
X_PU_PER_KM    = 0.290 / Z_BASE        # 1.16e-3 pu/km

BUS_MATCH_KM   = 8.0    # 送電線端点→バスのマッチング閾値 [km]
PLANT_MATCH_KM = 30.0   # 発電機→バスのマッチング閾値 [km]

# 慣性定数 [s]
H_BY_FUEL: Dict[str, float] = {
    "nuclear":    6.5,
    "coal":       6.5,
    "hydro":      4.0,
    "lng":        5.0,
    "gas":        5.0,
    "oil":        5.0,
    "geothermal": 4.0,
}
H_DEFAULT = 5.0

# 発電容量デフォルト値 [MW]
CAP_DEFAULT: Dict[str, float] = {
    "nuclear": 1100.0,
    "coal":     700.0,
    "lng":      500.0,
    "gas":      500.0,
    "oil":      400.0,
    "hydro":    200.0,
    "geothermal": 50.0,
}

# 安定限界
ANGLE_LIMIT_RAD = math.pi   # 180°
D_DAMP          = 0.05      # 制動係数
T_FAULT         = 0.1       # 故障継続時間 [s]
T_END           = 8.0       # 解析時間 [s]
MAX_STEP        = 0.02      # RK45 最大ステップ [s]


# ── 電圧スナップ ──────────────────────────────────────────────────────
def snap_v(v_str) -> int:
    try:
        kv = int(str(v_str).split(";")[0]) // 1000
        return min([500, 275, 154, 110, 66], key=lambda c: abs(c - kv))
    except:
        return 66


# ── Haversine距離 [km] ────────────────────────────────────────────────
def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    # Canonical impl in src.utils.geo_utils; (lon, lat) order preserved.
    from src.utils.geo_utils import haversine_distance
    return haversine_distance(lat1, lon1, lat2, lon2)


# ── Step 1: 500kVバス読み込み ─────────────────────────────────────────
def load_500kv_buses() -> List[Dict]:
    buses = []
    bus_id = 0
    for region in REGIONS:
        path = os.path.join(DATA_DIR, f"{region}_substations.geojson")
        with open(path) as f:
            gj = json.load(f)
        for feat in gj["features"]:
            props = feat["properties"]
            if snap_v(props.get("voltage")) != 500:
                continue
            geom = feat["geometry"]
            if geom is None:
                continue
            # 座標取得
            if geom["type"] == "Point":
                lon, lat = float(geom["coordinates"][0]), float(geom["coordinates"][1])
            elif geom["type"] == "Polygon":
                coords = geom["coordinates"][0]
                lon = float(np.mean([c[0] for c in coords]))
                lat = float(np.mean([c[1] for c in coords]))
            elif geom["type"] == "MultiPolygon":
                all_coords = [c for ring in geom["coordinates"] for c in ring[0]]
                lon = float(np.mean([c[0] for c in all_coords]))
                lat = float(np.mean([c[1] for c in all_coords]))
            else:
                continue
            buses.append({
                "id": bus_id,
                "region": region,
                "lon": lon,
                "lat": lat,
                "name": props.get("name") or props.get("_display_name") or f"{region}_{bus_id}",
            })
            bus_id += 1
    return buses


# ── Step 2: 500kV送電線マッチングでYbus構築 ───────────────────────────
def build_ybus_from_lines(buses: List[Dict]) -> Tuple[np.ndarray, List[Tuple[int, int]]]:
    n = len(buses)
    Y = np.zeros((n, n), dtype=complex)
    edges = []  # 描画用 (i, j)

    bus_lons = np.array([b["lon"] for b in buses])
    bus_lats = np.array([b["lat"] for b in buses])

    def find_nearest_bus(lon: float, lat: float) -> Optional[int]:
        dists = [haversine_km(lon, lat, bus_lons[j], bus_lats[j]) for j in range(n)]
        idx = int(np.argmin(dists))
        if dists[idx] <= BUS_MATCH_KM:
            return idx
        return None

    def process_linestring_coords(coords: List) -> None:
        if len(coords) < 2:
            return
        # 線路長計算
        length_km = 0.0
        for k in range(len(coords) - 1):
            length_km += haversine_km(
                float(coords[k][0]), float(coords[k][1]),
                float(coords[k+1][0]), float(coords[k+1][1])
            )
        if length_km < 0.1:
            return

        # 始点・終点マッチ
        bi = find_nearest_bus(float(coords[0][0]), float(coords[0][1]))
        bj = find_nearest_bus(float(coords[-1][0]), float(coords[-1][1]))
        if bi is None or bj is None or bi == bj:
            return

        z = complex(R_PU_PER_KM * length_km, X_PU_PER_KM * length_km)
        y = 1.0 / z

        Y[bi, bj] += y
        Y[bj, bi] += y
        Y[bi, bi] -= y
        Y[bj, bj] -= y

        edge = (min(bi, bj), max(bi, bj))
        if edge not in edges:
            edges.append(edge)

    for region in REGIONS:
        path = os.path.join(DATA_DIR, f"{region}_lines.geojson")
        with open(path) as f:
            gj = json.load(f)
        for feat in gj["features"]:
            props = feat["properties"]
            if snap_v(props.get("voltage")) != 500:
                continue
            geom = feat["geometry"]
            if geom is None:
                continue
            if geom["type"] == "LineString":
                process_linestring_coords(geom["coordinates"])
            elif geom["type"] == "MultiLineString":
                for part in geom["coordinates"]:
                    process_linestring_coords(part)

    return Y, edges


# ── Step 3: 接続成分の抽出 ────────────────────────────────────────────
def extract_largest_component(buses: List[Dict], Y: np.ndarray, edges: List[Tuple]) -> Tuple[List[Dict], np.ndarray, List[Tuple]]:
    n = len(buses)
    # adjacency matrix (unweighted)
    adj = np.zeros((n, n), dtype=int)
    for (i, j) in edges:
        adj[i, j] = 1
        adj[j, i] = 1
    sparse_adj = csr_matrix(adj)
    n_comp, labels = connected_components(sparse_adj, directed=False)
    print(f"  Connected components: {n_comp}")

    # 最大連結成分
    comp_sizes = np.bincount(labels)
    main_comp = int(np.argmax(comp_sizes))
    mask = labels == main_comp

    new_buses = [b for b, m in zip(buses, mask) if m]
    old_to_new = {old: new for new, old in enumerate(np.where(mask)[0])}

    n2 = len(new_buses)
    Y2 = np.zeros((n2, n2), dtype=complex)
    old_idx = np.where(mask)[0]
    for ni, oi in enumerate(old_idx):
        for nj, oj in enumerate(old_idx):
            Y2[ni, nj] = Y[oi, oj]

    edges2 = [(old_to_new[i], old_to_new[j]) for (i, j) in edges
              if i in old_to_new and j in old_to_new]

    print(f"  Main component buses: {n2}")
    return new_buses, Y2, edges2


# ── Step 4: 発電機マッピング ──────────────────────────────────────────
def map_generators_to_buses(buses: List[Dict]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(buses)
    total_cap = np.zeros(n)
    sum_H_cap = np.zeros(n)

    SYNC_FUELS = {"nuclear", "coal", "lng", "gas", "oil", "hydro", "geothermal"}

    for region in REGIONS:
        path = os.path.join(DATA_DIR, f"{region}_plants.geojson")
        with open(path) as f:
            gj = json.load(f)
        for feat in gj["features"]:
            props = feat["properties"]
            fuel = (props.get("fuel_type") or "unknown").lower().strip()
            if fuel not in SYNC_FUELS:
                continue
            if fuel.startswith("http"):
                continue

            cap = props.get("capacity_mw")
            if cap is None or cap <= 0:
                cap = CAP_DEFAULT.get(fuel, 100.0)

            geom = feat["geometry"]
            if geom is None:
                continue
            if geom["type"] == "Point":
                lon, lat = float(geom["coordinates"][0]), float(geom["coordinates"][1])
            else:
                continue

            # 最近傍バスにマッピング
            dists = [haversine_km(lon, lat, buses[j]["lon"], buses[j]["lat"]) for j in range(n)]
            idx = int(np.argmin(dists))
            if dists[idx] > PLANT_MATCH_KM:
                continue

            H = H_BY_FUEL.get(fuel, H_DEFAULT)
            total_cap[idx] += cap
            sum_H_cap[idx] += H * cap

    # Pm_bus: 各バスの容量割合 [pu]
    grand_total = total_cap.sum()
    if grand_total <= 0:
        grand_total = 1.0
    Pm_bus = total_cap / grand_total

    # H_bus: 加重平均慣性定数
    H_bus = np.where(total_cap > 0, sum_H_cap / np.maximum(total_cap, 1e-9), H_DEFAULT)

    print(f"  Buses with generators: {(Pm_bus > 0).sum()}")
    print(f"  Total mapped capacity: {grand_total:.0f} MW")

    return Pm_bus, H_bus, total_cap


# ── 電力方程式 ────────────────────────────────────────────────────────
def Pe_vec(delta: np.ndarray, Y: np.ndarray) -> np.ndarray:
    """電気的出力 Pe_i = Σ_j |V_i||V_j|(G_ij cosδ_ij + B_ij sinδ_ij)
    簡略: |V|=1, G=0 の時  Pe_i = Σ_j B_ij sin(δ_i - δ_j) = Im(Y)[i,j]*sin(δi-δj)
    実際には Y の虚部 = B の場合:
    Pe_i = -Im(Y_ii)*0 + Σ_{j≠i} B_ij sin(δi - δj)   (Y_ij = jB_ij)
    """
    n = len(delta)
    B = Y.imag   # susceptance行列 (オフ対角: 正値, 対角: 負値)
    Pe = np.zeros(n)
    for i in range(n):
        for j in range(n):
            if i != j:
                Pe[i] += B[i, j] * math.sin(delta[i] - delta[j])
    return -Pe  # Y_ij = jB_ij (off-diag positive) → Pe = +ΣB_ij sin(δi-δj)


def Pe_vec_fast(delta: np.ndarray, Y: np.ndarray) -> np.ndarray:
    """numpy版の Pe 計算

    仕様書の符号規約: Y[i,j] += y_line, Y[i,i] -= y_line
    → Y_off_diag = +y_line, Y_diag = -y_line  (通常のYbusと逆)
    → B_off = Im(y_line) < 0 (誘導性)
    → Pe_i = -Σ_j B[i,j] * sin(δi-δj) が物理的に正しい符号
    """
    B = Y.imag
    d_diff = delta[:, np.newaxis] - delta[np.newaxis, :]
    sin_d = np.sin(d_diff)
    # 負号: 仕様書符号規約 (off-diag: +y_line) に合わせる
    Pe = -np.sum(B * sin_d, axis=1)
    return Pe


# ── 平衡点計算 ────────────────────────────────────────────────────────
def equilibrium(Pm_raw: np.ndarray, Y: np.ndarray) -> Optional[np.ndarray]:
    """fsolve でδ平衡点を求める。delta[0]=0固定。"""
    from scipy.optimize import fsolve
    n = len(Pm_raw)
    Pm_c = Pm_raw - Pm_raw.mean()  # ゼロ和中心化

    def equations(delta_free):
        delta = np.concatenate([[0.0], delta_free])
        Pe = Pe_vec_fast(delta, Y)
        return (Pm_c - Pe)[1:]

    x0 = np.zeros(n - 1)
    try:
        sol, _, ier, _ = fsolve(equations, x0, full_output=True)
        if ier != 1:
            return None
        delta = np.concatenate([[0.0], sol])
        return delta
    except Exception:
        return None


# ── 動揺方程式 RHS ───────────────────────────────────────────────────
def swing_rhs(t: float, y: np.ndarray, M: np.ndarray, Pm_c: np.ndarray,
              Y: np.ndarray, D: float) -> np.ndarray:
    n = len(M)
    delta = y[:n]
    omega = y[n:]
    Pe = Pe_vec_fast(delta, Y)
    ddelta = omega
    domega = (Pm_c - Pe - D * omega) / M
    return np.concatenate([ddelta, domega])


# ── 1ケースの安定性解析 ───────────────────────────────────────────────
def analyze_stability(
    delta0: np.ndarray,
    M: np.ndarray,
    Pm_c: np.ndarray,
    Y_post: np.ndarray,
    D: float = D_DAMP,
    t_fault: float = T_FAULT,
    t_end: float = T_END,
) -> Tuple[bool, float, Optional[np.ndarray]]:
    """
    Returns: (is_stable, max_angle_spread_deg, delta_history or None)
    """
    n = len(delta0)
    y0 = np.concatenate([delta0, np.zeros(n)])

    # 故障中: Pe=0 (短絡)
    def rhs_fault(t, y):
        delta = y[:n]
        omega = y[n:]
        Pe = np.zeros(n)
        ddelta = omega
        domega = (Pm_c - Pe - D * omega) / M
        return np.concatenate([ddelta, domega])

    # 故障除去後: 正常ネットワーク
    def rhs_post(t, y):
        return swing_rhs(t, y, M, Pm_c, Y_post, D)

    max_spread = 0.0
    delta_hist = None

    # 故障区間 [0, t_fault]
    try:
        sol1 = solve_ivp(
            rhs_fault, [0.0, t_fault], y0,
            method="RK45", max_step=MAX_STEP,
            dense_output=False
        )
        if not sol1.success:
            return False, 180.0, None

        y_mid = sol1.y[:, -1]

        # 故障除去後 [t_fault, t_end]
        t_eval = np.linspace(t_fault, t_end, 400)
        sol2 = solve_ivp(
            rhs_post, [t_fault, t_end], y_mid,
            method="RK45", max_step=MAX_STEP,
            t_eval=t_eval, dense_output=False
        )
        if not sol2.success:
            return False, 360.0, None

        delta_hist = sol2.y[:n, :]

        # 最大角度偏差
        for k in range(delta_hist.shape[1]):
            d = delta_hist[:, k]
            spread = np.max(d) - np.min(d)
            if spread > max_spread:
                max_spread = spread

        is_stable = max_spread < ANGLE_LIMIT_RAD
        return is_stable, math.degrees(max_spread), delta_hist

    except Exception:
        return False, 360.0, None


# ── N-1解析 ──────────────────────────────────────────────────────────
def run_n1_analysis(
    gen_bus_idx: np.ndarray,  # 発電機バスのインデックス (in buses)
    Pm_gen: np.ndarray,       # 各発電機バスのPm [pu]
    H_gen: np.ndarray,        # 各発電機バスのH [s]
    Y: np.ndarray,
) -> List[Dict]:
    n_gen = len(gen_bus_idx)
    M_gen = 2.0 * H_gen / OMEGA_S

    results = []
    for k in range(n_gen):
        # k番目の発電機バスをトリップ
        survivors = [i for i in range(n_gen) if i != k]
        if len(survivors) < 2:
            results.append({"bus_k": k, "stable": True, "max_deg": 0.0})
            continue

        Pm_sub = Pm_gen[survivors]
        H_sub  = H_gen[survivors]
        M_sub  = M_gen[survivors]
        Y_sub  = Y[np.ix_(gen_bus_idx[survivors], gen_bus_idx[survivors])]

        # 平衡点
        delta0 = equilibrium(Pm_sub, Y_sub)
        if delta0 is None:
            # 収束失敗 → ゼロで代用
            delta0 = np.zeros(len(survivors))

        Pm_c = Pm_sub - Pm_sub.mean()
        stable, max_deg, _ = analyze_stability(delta0, M_sub, Pm_c, Y_sub)
        results.append({
            "bus_k": k,
            "stable": stable,
            "max_deg": max_deg,
        })

    return results


# ── N-2解析 ──────────────────────────────────────────────────────────
def run_n2_analysis(
    gen_bus_idx: np.ndarray,
    Pm_gen: np.ndarray,
    H_gen: np.ndarray,
    Y: np.ndarray,
    top_k: int = 30,
    n1_results: Optional[List[Dict]] = None,
) -> List[Dict]:
    n_gen = len(gen_bus_idx)
    M_gen = 2.0 * H_gen / OMEGA_S

    # N-1最悪上位30バス
    if n1_results is not None:
        sorted_n1 = sorted(n1_results, key=lambda r: r["max_deg"], reverse=True)
        worst_k = min(top_k, len(sorted_n1))
        worst_indices = [r["bus_k"] for r in sorted_n1[:worst_k]]
    else:
        worst_indices = list(range(min(top_k, n_gen)))

    n2_results = []
    pairs = list(combinations(worst_indices, 2))

    for (k1, k2) in pairs:
        survivors = [i for i in range(n_gen) if i != k1 and i != k2]
        if len(survivors) < 2:
            n2_results.append({"bus_k1": k1, "bus_k2": k2, "stable": True, "max_deg": 0.0})
            continue

        Pm_sub = Pm_gen[survivors]
        H_sub  = H_gen[survivors]
        M_sub  = M_gen[survivors]
        Y_sub  = Y[np.ix_(gen_bus_idx[survivors], gen_bus_idx[survivors])]

        delta0 = equilibrium(Pm_sub, Y_sub)
        if delta0 is None:
            delta0 = np.zeros(len(survivors))

        Pm_c = Pm_sub - Pm_sub.mean()
        stable, max_deg, _ = analyze_stability(delta0, M_sub, Pm_c, Y_sub)
        n2_results.append({
            "bus_k1": k1,
            "bus_k2": k2,
            "stable": stable,
            "max_deg": max_deg,
        })

    return n2_results


# ── 最悪N-1の動揺波形 ────────────────────────────────────────────────
def get_worst_n1_waveform(
    gen_bus_idx: np.ndarray,
    Pm_gen: np.ndarray,
    H_gen: np.ndarray,
    Y: np.ndarray,
    n1_results: List[Dict],
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], int]:
    """最悪ケースの時刻・角度波形を返す"""
    sorted_n1 = sorted(n1_results, key=lambda r: r["max_deg"], reverse=True)
    M_gen = 2.0 * H_gen / OMEGA_S

    for worst in sorted_n1[:5]:
        k = worst["bus_k"]
        survivors = [i for i in range(len(gen_bus_idx)) if i != k]
        if len(survivors) < 2:
            continue

        Pm_sub = Pm_gen[survivors]
        H_sub  = H_gen[survivors]
        M_sub  = 2.0 * H_sub / OMEGA_S
        Y_sub  = Y[np.ix_(gen_bus_idx[survivors], gen_bus_idx[survivors])]

        delta0 = equilibrium(Pm_sub, Y_sub)
        if delta0 is None:
            delta0 = np.zeros(len(survivors))

        Pm_c = Pm_sub - Pm_sub.mean()
        n = len(survivors)
        y0 = np.concatenate([delta0, np.zeros(n)])

        def rhs_fault(t, y):
            delta = y[:n]; omega = y[n:]
            Pe = np.zeros(n)
            domega = (Pm_c - Pe - D_DAMP * omega) / M_sub
            return np.concatenate([omega, domega])

        def rhs_post(t, y):
            return swing_rhs(t, y, M_sub, Pm_c, Y_sub, D_DAMP)

        try:
            sol1 = solve_ivp(rhs_fault, [0.0, T_FAULT], y0, method="RK45", max_step=MAX_STEP)
            if not sol1.success:
                continue
            y_mid = sol1.y[:, -1]

            t_eval = np.linspace(T_FAULT, T_END, 600)
            sol2 = solve_ivp(rhs_post, [T_FAULT, T_END], y_mid,
                             method="RK45", max_step=MAX_STEP, t_eval=t_eval)
            if not sol2.success:
                continue

            # 全区間結合
            t_all = np.concatenate([sol1.t, sol2.t])
            delta_all = np.concatenate([sol1.y[:n, :], sol2.y[:n, :]], axis=1)
            return t_all, delta_all, k

        except Exception:
            continue

    return None, None, -1


# ── 描画 ─────────────────────────────────────────────────────────────
def make_figure(
    buses: List[Dict],
    edges: List[Tuple],
    n1_results: List[Dict],
    n2_results: List[Dict],
    gen_bus_idx: np.ndarray,
    t_wave: Optional[np.ndarray],
    delta_wave: Optional[np.ndarray],
    worst_k: int,
    out_path: str,
) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), facecolor="white")
    fig.suptitle("全国500kV系統 N-1/N-2 過渡安定解析", fontsize=14, fontweight="bold")

    # ── (a) 全国500kV系統マップ + N-1結果 ──────────────────────────
    ax = axes[0]
    ax.set_facecolor("#f5f5f5")

    # N-1最大角度偏差をバスに付与
    n_gen = len(gen_bus_idx)
    gen_max_deg = np.full(n_gen, np.nan)
    for r in n1_results:
        gen_max_deg[r["bus_k"]] = r["max_deg"]

    all_bus_max_deg = np.full(len(buses), np.nan)
    for gi, bi in enumerate(gen_bus_idx):
        if not np.isnan(gen_max_deg[gi]):
            all_bus_max_deg[bi] = gen_max_deg[gi]

    # 送電線
    for (i, j) in edges:
        ax.plot(
            [buses[i]["lon"], buses[j]["lon"]],
            [buses[i]["lat"], buses[j]["lat"]],
            color="#aaaaaa", linewidth=0.5, zorder=1
        )

    # 非発電機バス（グレー）
    non_gen_mask = np.isnan(all_bus_max_deg)
    if non_gen_mask.any():
        lons_ng = [buses[i]["lon"] for i, m in enumerate(non_gen_mask) if m]
        lats_ng = [buses[i]["lat"] for i, m in enumerate(non_gen_mask) if m]
        ax.scatter(lons_ng, lats_ng, c="#cccccc", s=15, zorder=2, label="負荷バス")

    # 発電機バス（カラー）
    gen_mask = ~non_gen_mask
    if gen_mask.any():
        lons_g = [buses[i]["lon"] for i, m in enumerate(gen_mask) if m]
        lats_g = [buses[i]["lat"] for i, m in enumerate(gen_mask) if m]
        vals_g = [all_bus_max_deg[i] for i, m in enumerate(gen_mask) if m]
        vmin, vmax = 0, 180
        sc = ax.scatter(lons_g, lats_g, c=vals_g, s=30, cmap="RdYlGn_r",
                        vmin=vmin, vmax=vmax, zorder=3, edgecolors="k",
                        linewidths=0.3, label="発電機バス")
        cbar = plt.colorbar(sc, ax=ax, shrink=0.6, pad=0.02)
        cbar.set_label("N-1 最大角度偏差 (°)", fontsize=8)

    # 最悪バス
    if worst_k >= 0 and worst_k < n_gen:
        bi_worst = gen_bus_idx[worst_k]
        ax.scatter([buses[bi_worst]["lon"]], [buses[bi_worst]["lat"]],
                   marker="x", c="red", s=100, zorder=5, linewidths=2, label="最悪バス")

    ax.set_xlabel("経度 (°E)")
    ax.set_ylabel("緯度 (°N)")
    ax.set_title("(a) 500kV系統マップ + N-1結果", fontsize=10)
    ax.set_xlim(128, 146)
    ax.set_ylim(30, 46)
    ax.legend(fontsize=7, loc="lower right")
    ax.grid(True, linewidth=0.3, alpha=0.5)

    # ── (b) N-1/N-2 安定性ヒストグラム ───────────────────────────
    ax = axes[1]
    n1_degs = [r["max_deg"] for r in n1_results]
    n2_degs = [r["max_deg"] for r in n2_results]

    bins = np.linspace(0, 360, 37)
    ax.hist(n1_degs, bins=bins, alpha=0.7, label=f"N-1 ({len(n1_degs)}件)", color="#2196F3")
    ax.hist(n2_degs, bins=bins, alpha=0.7, label=f"N-2 ({len(n2_degs)}件)", color="#FF9800")
    ax.axvline(180, color="red", linestyle="--", linewidth=1.5, label="安定限界 180°")
    ax.set_xlabel("最大角度偏差 (°)")
    ax.set_ylabel("件数")
    ax.set_title("(b) N-1/N-2 安定性分布", fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(True, linewidth=0.3, alpha=0.5)

    n1_unstable = sum(1 for r in n1_results if not r["stable"])
    n2_unstable = sum(1 for r in n2_results if not r["stable"])
    ax.text(0.97, 0.97, f"N-1不安定: {n1_unstable}/{len(n1_results)}\n"
            f"N-2不安定: {n2_unstable}/{len(n2_results)}",
            transform=ax.transAxes, ha="right", va="top", fontsize=8,
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))

    # ── (c) 最悪N-1 動揺波形 ─────────────────────────────────────
    ax = axes[2]
    if t_wave is not None and delta_wave is not None:
        n_show = min(5, delta_wave.shape[0])
        colors_wave = plt.cm.tab10(np.linspace(0, 1, n_show))
        for i in range(n_show):
            ax.plot(t_wave, np.degrees(delta_wave[i, :]),
                    color=colors_wave[i], linewidth=1.0, label=f"Bus {i+1}")
        ax.axvline(T_FAULT, color="red", linestyle="--", linewidth=1.5, label=f"故障除去 {T_FAULT}s")
        ax.axhline(180, color="red", linestyle=":", linewidth=1.0, alpha=0.6)
        ax.axhline(-180, color="red", linestyle=":", linewidth=1.0, alpha=0.6)
        ax.set_xlabel("時刻 (s)")
        ax.set_ylabel("ロータ角 δ (°)")
        ax.set_title(f"(c) 最悪N-1 動揺波形 (Bus {worst_k+1}トリップ)", fontsize=10)
        ax.legend(fontsize=7, loc="upper right")
        ax.grid(True, linewidth=0.3, alpha=0.5)
    else:
        ax.text(0.5, 0.5, "波形データなし", ha="center", va="center",
                transform=ax.transAxes, fontsize=12)
        ax.set_title("(c) 最悪N-1 動揺波形", fontsize=10)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"  図を保存: {out_path}")


# ── メイン ────────────────────────────────────────────────────────────
def main():
    t_start = time.time()
    print("=" * 60)
    print("全国500kV系統 N-1/N-2 過渡安定解析")
    print("=" * 60)

    # Step 1: バス読み込み
    print("\n[Step 1] 500kVバス読み込み...")
    buses = load_500kv_buses()
    print(f"  総バス数: {len(buses)}")

    # Step 2: Ybus構築
    print("\n[Step 2] 500kV送電線からYbus構築...")
    Y, edges = build_ybus_from_lines(buses)
    print(f"  線路エッジ数: {len(edges)}")
    print(f"  Ybus shape: {Y.shape}")

    # Step 3: 最大連結成分
    print("\n[Step 3] 接続成分抽出...")
    buses, Y, edges = extract_largest_component(buses, Y, edges)
    n_bus = len(buses)

    # Step 4: 発電機マッピング
    print("\n[Step 4] 発電機→バスマッピング...")
    Pm_bus, H_bus, cap_bus = map_generators_to_buses(buses)

    # 発電機バス（Pm>0）を選択
    gen_mask = Pm_bus > 0
    gen_bus_idx = np.where(gen_mask)[0]
    Pm_gen = Pm_bus[gen_bus_idx]
    H_gen  = H_bus[gen_bus_idx]
    n_gen  = len(gen_bus_idx)
    print(f"  発電機バス数: {n_gen}")

    if n_gen < 3:
        print("  ERROR: 発電機バスが3つ未満 → 解析不能")
        return

    # Step 5: 動揺解析用行列
    print("\n[Step 5] 動揺解析準備...")
    M_gen = 2.0 * H_gen / OMEGA_S
    print(f"  M_gen 範囲: {M_gen.min():.4f} ~ {M_gen.max():.4f} s²/rad")

    # Step 6: N-1解析
    print(f"\n[Step 6] N-1解析 ({n_gen}件)...")
    t_n1 = time.time()
    n1_results = run_n1_analysis(gen_bus_idx, Pm_gen, H_gen, Y)
    elapsed_n1 = time.time() - t_n1
    n1_unstable = sum(1 for r in n1_results if not r["stable"])
    max_n1 = max(r["max_deg"] for r in n1_results) if n1_results else 0.0
    print(f"  完了 ({elapsed_n1:.1f}s): {n_gen}件, 不安定={n1_unstable}, 最大偏差={max_n1:.1f}°")

    # Step 7: N-2解析
    print(f"\n[Step 7] N-2解析 (上位30バスペア)...")
    t_n2 = time.time()
    n2_results = run_n2_analysis(gen_bus_idx, Pm_gen, H_gen, Y,
                                  top_k=30, n1_results=n1_results)
    elapsed_n2 = time.time() - t_n2
    n2_unstable = sum(1 for r in n2_results if not r["stable"])
    max_n2 = max(r["max_deg"] for r in n2_results) if n2_results else 0.0
    print(f"  完了 ({elapsed_n2:.1f}s): {len(n2_results)}件, 不安定={n2_unstable}, 最大偏差={max_n2:.1f}°")

    # 最悪N-1の動揺波形
    print("\n最悪N-1ケースの動揺波形計算...")
    t_wave, delta_wave, worst_k = get_worst_n1_waveform(
        gen_bus_idx, Pm_gen, H_gen, Y, n1_results
    )

    # Step 8: 出力図
    print("\n[Step 8] 図の生成...")
    out_path = os.path.join(OUT_DIR, "fig_nx_500kv.png")
    make_figure(
        buses, edges,
        n1_results, n2_results,
        gen_bus_idx,
        t_wave, delta_wave, worst_k,
        out_path
    )

    elapsed_total = time.time() - t_start
    print(f"\n{'='*60}")
    print(f"完了: {elapsed_total:.1f}s")
    print(f"バス数 (最大連結成分): {n_bus}")
    print(f"N-1件数: {n_gen}")
    print(f"N-2件数: {len(n2_results)}")
    print(f"出力: {out_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
