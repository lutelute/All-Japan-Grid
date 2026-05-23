"""
全国500kV+275kV送電網の実GeoJSONトポロジからYbusを構築し、
Kron縮約・DC潮流平衡・N-1/N-2過渡安定解析を実施する。

Usage:
    cd /path/to/All-Japan-Grid
    python scripts/gen_nx_proper.py
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
from scipy.optimize import fsolve
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

S_BASE  = 1000.0           # MVA
OMEGA_S = 2 * math.pi * 50.0  # rad/s (50 Hz)
D_COEFF = 0.05
T_FAULT = 0.10             # s
T_END   = 8.0              # s

# 電圧クラス別インピーダンス (1000MVAベース)
# V=500kV: Z_base=500^2/1000=250 Ω
# V=275kV: Z_base=275^2/1000=75.625 Ω
VOLT_PARAMS = {
    500: {"R_km": 0.012 / 250.0,      "X_km": 0.290 / 250.0},    # pu/km
    275: {"R_km": 0.028 / 75.625,     "X_km": 0.325 / 75.625},   # pu/km
}

MATCH_THRESHOLD_KM_500 = 8.0
MATCH_THRESHOLD_KM_275 = 5.0
GEN_MATCH_KM           = 30.0

# 慣性定数 [s]
H_BY_FUEL: Dict[str, float] = {
    "nuclear":    6.5,
    "coal":       6.5,
    "hydro":      4.0,
    "gas":        5.0,
    "lng":        5.0,
    "oil":        5.0,
    "geothermal": 4.0,
    "biomass":    4.0,
    "waste":      4.0,
}
H_DEFAULT = 5.0

# 発電容量デフォルト値 [MW]
CAP_DEFAULT: Dict[str, float] = {
    "nuclear":    1100.0,
    "coal":        700.0,
    "lng":         500.0,
    "gas":         500.0,
    "oil":         400.0,
    "hydro":       200.0,
    "geothermal":   50.0,
    "biomass":     100.0,
    "waste":        30.0,
}

EXCLUDE_FUELS = {"solar", "battery", "wind", "unknown"}

# 安定限界
ANGLE_LIMIT_RAD = math.pi   # 180°


# ── 電圧スナップ ──────────────────────────────────────────────────────
def snap_v(v_str) -> int:
    try:
        kv = int(str(v_str).split(";")[0]) // 1000
        return min([500, 275, 154, 110, 66], key=lambda c: abs(c - kv))
    except:
        return 66


# ── Haversine距離 [km] ────────────────────────────────────────────────
def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(max(0.0, min(1.0, a))))


# ── ポリゴン重心 ─────────────────────────────────────────────────────
def geom_centroid(geom) -> Optional[Tuple[float, float]]:
    gtype = geom.get("type")
    if gtype == "Point":
        c = geom["coordinates"]
        return float(c[0]), float(c[1])
    elif gtype == "Polygon":
        coords = geom["coordinates"][0]
        lon = float(np.mean([c[0] for c in coords]))
        lat = float(np.mean([c[1] for c in coords]))
        return lon, lat
    elif gtype == "MultiPolygon":
        all_coords = []
        for poly in geom["coordinates"]:
            all_coords.extend(poly[0])
        lon = float(np.mean([c[0] for c in all_coords]))
        lat = float(np.mean([c[1] for c in all_coords]))
        return lon, lat
    return None


# ── Step 1: バス読み込み（500kV + 275kV変電所）──────────────────────
def load_buses() -> List[Dict]:
    buses = []
    bus_id = 0
    for region in REGIONS:
        path = os.path.join(DATA_DIR, f"{region}_substations.geojson")
        with open(path) as f:
            gj = json.load(f)
        for feat in gj["features"]:
            props = feat["properties"]
            v_kv = snap_v(props.get("voltage"))
            if v_kv not in (500, 275):
                continue
            geom = feat.get("geometry")
            if geom is None:
                continue
            pos = geom_centroid(geom)
            if pos is None:
                continue
            lon, lat = pos
            buses.append({
                "id":      bus_id,
                "region":  region,
                "lon":     lon,
                "lat":     lat,
                "name":    props.get("name") or props.get("_display_name") or f"{region}_{bus_id}",
                "volt_kv": v_kv,
            })
            bus_id += 1
    return buses


# ── Step 2: 送電線マッチングとYbus構築 ──────────────────────────────
def line_length_km(coords: List[List[float]]) -> float:
    total = 0.0
    for k in range(len(coords) - 1):
        total += haversine_km(coords[k][0], coords[k][1], coords[k+1][0], coords[k+1][1])
    return total


def nearest_bus(lon: float, lat: float, buses: List[Dict],
                preferred_volt: int, threshold_km: float) -> Optional[int]:
    """最近傍バスを探す。同電圧を優先し、閾値以内なら異電圧も許容。"""
    best_same_id, best_same_d = None, float("inf")
    best_any_id,  best_any_d  = None, float("inf")
    for b in buses:
        d = haversine_km(lon, lat, b["lon"], b["lat"])
        if d < best_any_d:
            best_any_d  = d
            best_any_id = b["id"]
        if b["volt_kv"] == preferred_volt and d < best_same_d:
            best_same_d  = d
            best_same_id = b["id"]
    # 同電圧が閾値以内にあればそちらを使用
    if best_same_id is not None and best_same_d <= threshold_km:
        return best_same_id
    # 異電圧でも閾値以内なら許容
    if best_any_id is not None and best_any_d <= threshold_km:
        return best_any_id
    return None


def build_ybus(buses: List[Dict]) -> Tuple[np.ndarray, List[Tuple[int, int, int, float]]]:
    """
    Returns:
        Y      : (n_buses, n_buses) complex Ybus matrix
        edges  : list of (i, j, volt_kv, length_km)
    """
    n = len(buses)
    Y = np.zeros((n, n), dtype=complex)
    edges: List[Tuple[int, int, int, float]] = []

    for region in REGIONS:
        path = os.path.join(DATA_DIR, f"{region}_lines.geojson")
        with open(path) as f:
            gj = json.load(f)
        for feat in gj["features"]:
            props = feat["properties"]
            v_kv = snap_v(props.get("voltage"))
            if v_kv not in (500, 275):
                continue
            geom = feat.get("geometry")
            if geom is None:
                continue

            # LineString / MultiLineString を統一処理
            if geom["type"] == "LineString":
                segments = [geom["coordinates"]]
            elif geom["type"] == "MultiLineString":
                segments = geom["coordinates"]
            else:
                continue

            params    = VOLT_PARAMS[v_kv]
            threshold = MATCH_THRESHOLD_KM_500 if v_kv == 500 else MATCH_THRESHOLD_KM_275

            for seg in segments:
                if len(seg) < 2:
                    continue
                length_km = line_length_km(seg)
                if length_km < 0.5:   # 0.5km未満は無視
                    continue

                start_lon, start_lat = seg[0][0],  seg[0][1]
                end_lon,   end_lat   = seg[-1][0], seg[-1][1]

                bi = nearest_bus(start_lon, start_lat, buses, v_kv, threshold)
                bj = nearest_bus(end_lon,   end_lat,   buses, v_kv, threshold)

                if bi is None or bj is None or bi == bj:
                    continue

                R_pu = params["R_km"] * length_km
                X_pu = params["X_km"] * length_km
                z_ij = complex(R_pu, X_pu)
                if abs(z_ij) < 1e-12:
                    continue
                y_ij = 1.0 / z_ij

                # 標準Ybus符号規約
                Y[bi, bj] -= y_ij
                Y[bj, bi] -= y_ij
                Y[bi, bi] += y_ij
                Y[bj, bj] += y_ij

                edges.append((bi, bj, v_kv, length_km))

    return Y, edges


# ── Step 3: 連結成分抽出 ────────────────────────────────────────────
def largest_component(buses: List[Dict], Y: np.ndarray, edges: List) -> Tuple[List[Dict], np.ndarray, List]:
    n = len(buses)
    # 隣接行列（対称）
    adj = (np.abs(Y) > 1e-12).astype(int)
    np.fill_diagonal(adj, 0)
    adj_sparse = csr_matrix(adj)
    n_comp, labels = connected_components(adj_sparse, directed=False)
    print(f"  連結成分数: {n_comp}")
    # 最大成分
    comp_sizes = np.bincount(labels)
    main_label = np.argmax(comp_sizes)
    mask = (labels == main_label)
    idx  = np.where(mask)[0]
    old2new = {old: new for new, old in enumerate(idx)}

    buses_sub = [buses[i] for i in idx]
    # バスIDを更新
    for new_i, b in enumerate(buses_sub):
        b["id"] = new_i

    Y_sub  = Y[np.ix_(idx, idx)]
    edges_sub = []
    for (bi, bj, v_kv, lkm) in edges:
        if bi in old2new and bj in old2new:
            edges_sub.append((old2new[bi], old2new[bj], v_kv, lkm))

    print(f"  最大成分バス数: {len(buses_sub)} / {n}")
    return buses_sub, Y_sub, edges_sub


# ── Step 4: 発電機マッピング ─────────────────────────────────────────
def load_generators(buses: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
    """
    Returns:
        bus_gen_cap : (n_buses,) 各バスの合計容量 [MW]
        bus_gen_H   : (n_buses,) 加重平均慣性定数 [s]
    """
    n = len(buses)
    bus_gen_cap = np.zeros(n)
    bus_gen_H   = np.zeros(n)

    for region in REGIONS:
        path = os.path.join(DATA_DIR, f"{region}_plants.geojson")
        with open(path) as f:
            gj = json.load(f)
        for feat in gj["features"]:
            props = feat["properties"]
            fuel = str(props.get("fuel_type") or "unknown").lower().strip()
            if fuel in EXCLUDE_FUELS:
                continue
            # 容量
            cap = props.get("capacity_mw")
            try:
                cap = float(cap)
                if cap < 0 or cap != cap:  # NaN or negative
                    cap = CAP_DEFAULT.get(fuel, 100.0)
            except (TypeError, ValueError):
                cap = CAP_DEFAULT.get(fuel, 100.0)
            if cap < 10.0:
                continue

            # 座標
            geom = feat.get("geometry")
            if geom is None:
                continue
            pos = geom_centroid(geom)
            if pos is None:
                continue
            g_lon, g_lat = pos

            # 最近傍バス（全電圧バス対象）
            best_id, best_d = None, float("inf")
            for b in buses:
                d = haversine_km(g_lon, g_lat, b["lon"], b["lat"])
                if d < best_d:
                    best_d  = d
                    best_id = b["id"]
            if best_id is None or best_d > GEN_MATCH_KM:
                continue

            h = H_BY_FUEL.get(fuel, H_DEFAULT)
            bus_gen_cap[best_id] += cap
            bus_gen_H[best_id]   += cap * h  # 加重和（後で除算）

    # 加重平均
    mask = bus_gen_cap > 0
    bus_gen_H[mask] /= bus_gen_cap[mask]

    return bus_gen_cap, bus_gen_H


# ── Step 5: Kron縮約 ─────────────────────────────────────────────────
def kron_reduction(Y: np.ndarray, gen_idx: List[int], lod_idx: List[int]) -> np.ndarray:
    Y_GG = Y[np.ix_(gen_idx, gen_idx)]
    Y_GL = Y[np.ix_(gen_idx, lod_idx)]
    Y_LG = Y[np.ix_(lod_idx, gen_idx)]
    Y_LL = Y[np.ix_(lod_idx, lod_idx)]

    try:
        Y_red = Y_GG - Y_GL @ np.linalg.solve(Y_LL, Y_LG)
    except np.linalg.LinAlgError:
        print("  警告: Y_LL が特異行列 → pinv で代替")
        Y_red = Y_GG - Y_GL @ np.linalg.pinv(Y_LL) @ Y_LG

    return Y_red


# ── Step 6: 平衡点計算 ──────────────────────────────────────────────
def Pe_vec(delta: np.ndarray, E: np.ndarray, Y: np.ndarray) -> np.ndarray:
    diff = delta[:, None] - delta[None, :]
    EiEj = E[:, None] * E[None, :]
    G = Y.real
    B = Y.imag
    return np.sum(EiEj * (G * np.cos(diff) + B * np.sin(diff)), axis=1)


def equilibrium(Pm_raw: np.ndarray, Y: np.ndarray, n_tries: int = 6) -> np.ndarray:
    """DC近似で平衡角 delta* を求める（Pm_rawはpu、ゼロ和でなくて良い）。"""
    Pm_c = Pm_raw - Pm_raw.mean()
    ng   = len(Pm_c)
    E    = np.ones(ng)

    def res(d):
        r = Pe_vec(d, E, Y) - Pm_c
        r[0] = d[0]   # スラック: delta_0 = 0
        return r

    best_d, best_err = np.zeros(ng), np.inf
    scales = np.linspace(0.3, 0.03, n_tries)
    for scale in scales:
        d0 = np.linspace(-scale, scale, ng)
        try:
            d_sol, _, ier, _ = fsolve(res, d0, full_output=True)[:4]
            err = float(np.max(np.abs(res(d_sol))))
            if err < best_err:
                best_err = err
                best_d   = d_sol
        except Exception:
            pass
    return best_d


# ── Step 7: N-1解析 ──────────────────────────────────────────────────
def simulate_swing(Pm_c: np.ndarray, H_gen: np.ndarray,
                   Y_post: np.ndarray, delta0: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """古典機モデル動揺シミュレーション (RK45, 発散検出付き)"""
    ns = len(Pm_c)
    M  = 2.0 * H_gen / OMEGA_S
    D  = D_COEFF * np.ones(ns)
    E  = np.ones(ns)

    def rhs(t, y):
        d, w = y[:ns], y[ns:]
        Pe = Pe_vec(d, E, Y_post) if t >= T_FAULT else np.zeros(ns)
        return np.concatenate([w, (Pm_c - Pe - D * w) / M])

    # 角度分離が4π(720°)を超えたら発散と判定して早期終了
    def diverge_event(t, y):
        d = y[:ns]
        return 4 * np.pi - (np.max(d) - np.min(d))
    diverge_event.terminal  = True
    diverge_event.direction = -1

    y0  = np.concatenate([delta0, np.zeros(ns)])
    sol = solve_ivp(rhs, [0.0, T_END], y0,
                    method="RK45", max_step=0.02, rtol=1e-6, atol=1e-8,
                    events=diverge_event, dense_output=False)
    return sol.t, sol.y[:ns, :]


def max_angle_deviation(delta_arr: np.ndarray) -> float:
    """最大角度偏差 max |delta_i - delta_j| [rad]"""
    if delta_arr.shape[0] <= 1:
        return 0.0
    diffs = []
    for i in range(delta_arr.shape[0]):
        for j in range(i + 1, delta_arr.shape[0]):
            diffs.append(np.max(np.abs(delta_arr[i] - delta_arr[j])))
    return float(max(diffs)) if diffs else 0.0


def run_n1(gen_idx: List[int], lod_idx: List[int], Y_full: np.ndarray,
           bus_gen_cap: np.ndarray, bus_gen_H: np.ndarray,
           delta0_all: np.ndarray, Pm_all: np.ndarray) -> List[Dict]:
    """
    N-1解析: 各発電機バスをtrip
    発電機k脱落時、そのバスを負荷バスに移してフルYbusから再Kron縮約する（正確な実装）。
    """
    ng = len(gen_idx)
    results = []

    for k in range(ng):
        bus_k   = gen_idx[k]
        surv    = [i for i in range(ng) if i != k]
        if len(surv) < 2:
            continue

        # ★ フルYbusから再縮約（近似なし）
        gen_post = [gen_idx[i] for i in surv]
        lod_post = sorted(lod_idx + [bus_k])
        try:
            Y_post = kron_reduction(Y_full, gen_post, lod_post)
        except Exception as e:
            results.append({"trip_k": k, "trip_bus_idx": bus_k,
                            "max_dev_rad": float("inf"),
                            "max_dev_deg": float("inf"), "stable": False})
            continue

        delta0_surv = delta0_all[surv]
        Pm_surv     = Pm_all[surv]
        Pm_surv_c   = Pm_surv - Pm_surv.mean()
        H_surv = np.array([bus_gen_H[gen_idx[i]] for i in surv])
        H_surv = np.where(H_surv > 0, H_surv, H_DEFAULT)

        try:
            t_arr, delta_arr = simulate_swing(Pm_surv_c, H_surv, Y_post, delta0_surv)
            max_dev_rad = max_angle_deviation(delta_arr)
            stable      = max_dev_rad < ANGLE_LIMIT_RAD
        except Exception:
            max_dev_rad = float("inf")
            stable      = False

        results.append({
            "trip_k":       k,
            "trip_bus_idx": bus_k,
            "max_dev_rad":  max_dev_rad,
            "max_dev_deg":  math.degrees(max_dev_rad) if np.isfinite(max_dev_rad) else 9999.0,
            "stable":       stable,
        })
        if (k + 1) % 10 == 0:
            print(f"    N-1進捗: {k+1}/{ng}")

    return results


# ── Step 8: N-2解析 ──────────────────────────────────────────────────
def run_n2(top_k_indices: List[int], gen_idx: List[int], lod_idx: List[int],
           Y_full: np.ndarray,
           bus_gen_cap: np.ndarray, bus_gen_H: np.ndarray,
           delta0_all: np.ndarray, Pm_all: np.ndarray) -> List[Dict]:
    """上位N-1ケースのペアについてN-2解析（フルYbusから再縮約）。"""
    results = []
    ng = len(gen_idx)

    for ka, kb in combinations(top_k_indices, 2):
        surv = [i for i in range(ng) if i not in (ka, kb)]
        if len(surv) < 2:
            continue

        # ★ フルYbusから再縮約
        gen_post = [gen_idx[i] for i in surv]
        lod_post = sorted(lod_idx + [gen_idx[ka], gen_idx[kb]])
        try:
            Y_post = kron_reduction(Y_full, gen_post, lod_post)
        except Exception:
            results.append({"trip_ka": ka, "trip_kb": kb,
                            "max_dev_deg": 9999.0, "stable": False})
            continue

        delta0_surv = delta0_all[surv]
        Pm_surv     = Pm_all[surv]
        Pm_surv_c   = Pm_surv - Pm_surv.mean()
        H_surv = np.array([bus_gen_H[gen_idx[i]] for i in surv])
        H_surv = np.where(H_surv > 0, H_surv, H_DEFAULT)

        try:
            t_arr, delta_arr = simulate_swing(Pm_surv_c, H_surv, Y_post, delta0_surv)
            max_dev_rad = max_angle_deviation(delta_arr)
            stable      = (max_dev_rad < ANGLE_LIMIT_RAD)
        except Exception:
            max_dev_rad = float("inf")
            stable      = False

        results.append({
            "trip_ka":      ka,
            "trip_kb":      kb,
            "max_dev_rad":  max_dev_rad,
            "max_dev_deg":  math.degrees(max_dev_rad),
            "stable":       stable,
        })

    return results


# ── Step 9: 出力図 ───────────────────────────────────────────────────
def make_figure(buses: List[Dict], edges: List, gen_idx: List[int],
                n1_results: List[Dict], worst_n1: Dict,
                t_worst: np.ndarray, delta_worst: np.ndarray,
                delta0_surv_worst: np.ndarray) -> None:

    fig, axes = plt.subplots(1, 3, figsize=(16, 5.5),
                              gridspec_kw={"width_ratios":[1.1, 1.0, 1.0]})

    # ── (a) 地図パネル ───────────────────────────────────────────────
    ax = axes[0]
    ax.set_aspect("equal")
    ax.set_facecolor("#f0f4f8")

    # coastline
    coast_path = os.path.join(OUT_DIR, "ne_countries.geojson")
    if os.path.exists(coast_path):
        with open(coast_path) as f:
            coast_gj = json.load(f)
        for feat in coast_gj.get("features", []):
            geom = feat.get("geometry", {})
            gtype = geom.get("type", "")
            if gtype == "Polygon":
                polys = [geom["coordinates"]]
            elif gtype == "MultiPolygon":
                polys = geom["coordinates"]
            else:
                continue
            for poly in polys:
                ext = poly[0]
                xs  = [c[0] for c in ext]
                ys  = [c[1] for c in ext]
                ax.fill(xs, ys, color="#e8edd4", alpha=0.6, zorder=0)
                ax.plot(xs, ys, color="#aaaaaa", lw=0.3, zorder=1)

    # ブランチ描画
    bus_pos = {b["id"]: (b["lon"], b["lat"]) for b in buses}
    drawn_edges = set()
    for (bi, bj, v_kv, _) in edges:
        key = (min(bi, bj), max(bi, bj))
        if key in drawn_edges:
            continue
        drawn_edges.add(key)
        if bi not in bus_pos or bj not in bus_pos:
            continue
        x0, y0 = bus_pos[bi]
        x1, y1 = bus_pos[bj]
        color = "#cc2222" if v_kv == 500 else "#dd8800"
        lw    = 0.6       if v_kv == 500 else 0.4
        ax.plot([x0, x1], [y0, y1], color=color, lw=lw, alpha=0.6, zorder=2)

    # N-1最大角度偏差マップ
    gen_set = set(gen_idx)
    max_dev_by_bus: Dict[int, float] = {}
    for r in n1_results:
        bus_id = r["trip_bus_idx"]
        max_dev_by_bus[bus_id] = max(max_dev_by_bus.get(bus_id, 0.0), r["max_dev_deg"])

    all_devs = [v for v in max_dev_by_bus.values() if v < 1e5]
    v_min = 0.0
    v_max = max(all_devs) if all_devs else 180.0

    cmap   = cm.RdYlGn_r
    norm   = mcolors.Normalize(vmin=v_min, vmax=min(v_max, 360.0))

    # 発電機なしバス（グレー）
    for b in buses:
        if b["id"] not in gen_set:
            ms = 4 if b["volt_kv"] == 500 else 2.5
            ax.plot(b["lon"], b["lat"], "o", color="#888888",
                    ms=ms, alpha=0.5, zorder=3)

    # 発電機ありバス（カラー）
    for b in buses:
        if b["id"] in gen_set:
            dev = max_dev_by_bus.get(b["id"], 0.0)
            color = cmap(norm(min(dev, 360.0)))
            ms    = 8 if b["volt_kv"] == 500 else 6
            ax.plot(b["lon"], b["lat"], "o", color=color,
                    ms=ms, zorder=4, markeredgecolor="k", markeredgewidth=0.3)

    # カラーバー
    sm = cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax, shrink=0.7, pad=0.02)
    cbar.set_label("N-1 最大角度偏差 [°]", fontsize=9)

    # 凡例
    leg_elements = [
        mpatches.Patch(color="#cc2222", label="500kV線路"),
        mpatches.Patch(color="#dd8800", label="275kV線路"),
        mpatches.Patch(color="#888888", label="負荷バス"),
    ]
    ax.legend(handles=leg_elements, loc="lower left", fontsize=7, framealpha=0.8)
    ax.set_xlim(128, 146)
    ax.set_ylim(30, 46)
    ax.set_xlabel("経度 [°]", fontsize=9)
    ax.set_ylabel("緯度 [°]", fontsize=9)
    ax.set_title("(a) 500+275kV系統 N-1角度偏差", fontsize=10)
    ax.tick_params(labelsize=8)

    # ── (b) ロータ角時空間ヒートマップ（最悪N-1） ───────────────────
    ax = axes[1]
    # 全発電機の角度偏差（事故後平衡点からの差）をラスタ化
    delta_rel_deg = np.degrees(delta_worst - delta0_surv_worst[:, None])  # (ng_surv, nt)
    ng_surv = delta_rel_deg.shape[0]

    # 地域順にソート（バスのregion属性を利用）
    REGION_ORDER = ["hokkaido","tohoku","tokyo","chubu","hokuriku",
                    "kansai","chugoku","shikoku","kyushu","okinawa"]
    k_worst = worst_n1["trip_k"]
    surv_bus_ids = [gen_idx[i] for i in range(len(gen_idx)) if i != k_worst]
    bus_map_local = {b["id"]: b for b in buses}
    def region_sort_key(idx):
        bid = surv_bus_ids[idx]
        reg = bus_map_local.get(bid, {}).get("region","z")
        return (REGION_ORDER.index(reg) if reg in REGION_ORDER else 99, idx)
    sorted_gen_order = sorted(range(ng_surv), key=region_sort_key)
    delta_sorted = delta_rel_deg[sorted_gen_order, :]  # 地域順に並び替え

    # リサンプル（時間軸を粗くしてメモリ節約）
    nt = delta_sorted.shape[1]
    step = max(1, nt // 200)
    t_ds = t_worst[::step]
    d_ds = delta_sorted[:, ::step]

    vmax = max(abs(d_ds.min()), abs(d_ds.max()), 0.5)
    im = ax.imshow(d_ds, aspect="auto", origin="lower",
                   extent=[t_ds[0], t_ds[-1], 0, ng_surv],
                   cmap="RdBu_r", vmin=-vmax, vmax=vmax, interpolation="nearest")
    ax.axvline(T_FAULT, color="k", lw=1.0, ls="--", alpha=0.7, label=f"故障除去 {T_FAULT}s")
    plt.colorbar(im, ax=ax, shrink=0.85, pad=0.02, label="Δδ [°]")
    ax.set_xlabel("時刻 [s]", fontsize=9)
    ax.set_ylabel("発電機バス（地域順）", fontsize=9)
    ax.set_title(f"(b) 時空間ヒートマップ（最悪N-1, gen #{k_worst} 脱落）", fontsize=10)
    ax.legend(fontsize=7, loc="upper right")
    ax.tick_params(labelsize=8)

    # ── (c) 最悪N-1 動揺波形 ────────────────────────────────────────
    ax = axes[2]
    ng_surv = delta_worst.shape[0]
    delta_rel = np.degrees(delta_worst - delta0_surv_worst[:, None])   # 平衡点からの偏差 [°]
    n_plot = min(5, ng_surv)
    # 最も偏差が大きいバスを選択
    max_per_gen = np.max(np.abs(delta_rel), axis=1)
    top_idx     = np.argsort(max_per_gen)[::-1][:n_plot]

    for i, gi in enumerate(top_idx):
        ax.plot(t_worst, delta_rel[gi], lw=1.2,
                label=f"Gen {gi}", alpha=0.85)
    ax.axhline(0, color="k", lw=0.5, ls=":")
    ax.axvline(T_FAULT, color="gray", lw=0.8, ls="--", label=f"故障除去 {T_FAULT}s")
    ax.set_xlabel("時刻 [s]", fontsize=9)
    ax.set_ylabel("δ - δ* [°]", fontsize=9)
    k_worst = worst_n1["trip_k"]
    ax.set_title(f"(c) 最悪N-1 (gen #{k_worst} trip)", fontsize=10)
    ax.legend(fontsize=7, ncol=2)
    ax.tick_params(labelsize=8)

    plt.tight_layout(pad=1.5)
    out_path = os.path.join(OUT_DIR, "fig_nx_proper.png")
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  図を保存: {out_path}")


# ── メイン ───────────────────────────────────────────────────────────
def main():
    t0 = time.time()
    print("=" * 60)
    print("Step 1: バス読み込み（500kV + 275kV変電所）")
    print("=" * 60)
    buses = load_buses()
    n500 = sum(1 for b in buses if b["volt_kv"] == 500)
    n275 = sum(1 for b in buses if b["volt_kv"] == 275)
    print(f"  総バス数: {len(buses)} (500kV: {n500}, 275kV: {n275})")

    print("\n" + "=" * 60)
    print("Step 2: 送電線マッチングとYbus構築")
    print("=" * 60)
    Y_full, edges_full = build_ybus(buses)
    print(f"  エッジ数: {len(edges_full)}")
    e500 = sum(1 for e in edges_full if e[2] == 500)
    e275 = sum(1 for e in edges_full if e[2] == 275)
    print(f"  500kVエッジ: {e500}, 275kVエッジ: {e275}")

    print("\n" + "=" * 60)
    print("Step 3: 連結成分抽出")
    print("=" * 60)
    buses, Y_full, edges_full = largest_component(buses, Y_full, edges_full)
    n = len(buses)

    print("\n" + "=" * 60)
    print("Step 4: 発電機マッピング")
    print("=" * 60)
    bus_gen_cap, bus_gen_H = load_generators(buses)
    n_gen_buses = int((bus_gen_cap > 0).sum())
    total_cap   = float(bus_gen_cap.sum())
    print(f"  発電機ありバス数: {n_gen_buses}")
    print(f"  総設備容量: {total_cap:.0f} MW")

    gen_idx = [i for i in range(n) if bus_gen_cap[i] > 0]
    lod_idx = [i for i in range(n) if bus_gen_cap[i] == 0]
    print(f"  Generator buses: {len(gen_idx)}, Load buses: {len(lod_idx)}")

    if len(gen_idx) < 2:
        print("エラー: 発電機バスが2未満。解析を中断します。")
        return

    print("\n" + "=" * 60)
    print("Step 5: Kron縮約")
    print("=" * 60)
    Y_red = kron_reduction(Y_full, gen_idx, lod_idx)
    print(f"  Y_red shape: {Y_red.shape}")
    print(f"  Y_red 最大|B|: {np.max(np.abs(Y_red.imag)):.4f} pu")

    print("\n" + "=" * 60)
    print("Step 6: 事前平衡点計算")
    print("=" * 60)
    Pm_raw = np.array([bus_gen_cap[i] for i in gen_idx]) / max(total_cap, 1.0)
    delta0 = equilibrium(Pm_raw, Y_red)
    Pm_c   = Pm_raw - Pm_raw.mean()
    Pe_eq  = Pe_vec(delta0, np.ones(len(gen_idx)), Y_red)
    residual = float(np.max(np.abs(Pe_eq - Pm_c)))
    print(f"  平衡点残差 (max): {residual:.4f} pu")
    print(f"  delta0 range: [{math.degrees(delta0.min()):.1f}°, {math.degrees(delta0.max()):.1f}°]")

    print("\n" + "=" * 60)
    print("Step 7: N-1解析")
    print("=" * 60)
    ng = len(gen_idx)
    print(f"  N-1ケース数: {ng}")
    n1_results = run_n1(gen_idx, lod_idx, Y_full, bus_gen_cap, bus_gen_H, delta0, Pm_raw)

    n_stable   = sum(1 for r in n1_results if r["stable"])
    n_unstable = sum(1 for r in n1_results if not r["stable"])
    devs_finite = [r["max_dev_deg"] for r in n1_results if r["max_dev_deg"] < 1e4]
    worst_dev = max(devs_finite) if devs_finite else float("inf")
    print(f"  安定: {n_stable}, 不安定: {n_unstable}")
    print(f"  最悪角度偏差: {worst_dev:.1f}°")

    # 最悪ケースの特定
    finite_results = [r for r in n1_results if r["max_dev_deg"] < 1e5]
    worst_n1 = max(finite_results, key=lambda r: r["max_dev_deg"]) if finite_results else n1_results[0]
    print(f"  最悪N-1: gen #{worst_n1['trip_k']} trip, max_dev={worst_n1['max_dev_deg']:.1f}°, stable={worst_n1['stable']}")

    # 最悪ケースの波形を再生成
    k_worst = worst_n1["trip_k"]
    surv_w  = [i for i in range(ng) if i != k_worst]
    # 最悪ケースの波形: フルYbusから再縮約
    gen_post_w = [gen_idx[i] for i in surv_w]
    lod_post_w = sorted(lod_idx + [gen_idx[k_worst]])
    Y_post_w   = kron_reduction(Y_full, gen_post_w, lod_post_w)
    delta0_surv_w = delta0[surv_w]
    Pm_surv_w     = Pm_raw[surv_w]
    Pm_surv_c_w   = Pm_surv_w - Pm_surv_w.mean()
    H_surv_w      = np.array([bus_gen_H[gen_idx[i]] for i in surv_w])
    H_surv_w      = np.where(H_surv_w > 0, H_surv_w, H_DEFAULT)
    t_worst, delta_worst = simulate_swing(Pm_surv_c_w, H_surv_w, Y_post_w, delta0_surv_w)

    print("\n" + "=" * 60)
    print("Step 8: N-2解析（上位20ケースのペア）")
    print("=" * 60)
    n_top = min(20, len(finite_results))
    top20_k = [r["trip_k"] for r in sorted(finite_results, key=lambda r: r["max_dev_deg"], reverse=True)[:n_top]]
    n2_cases = len(list(combinations(top20_k, 2)))
    print(f"  N-2ケース数: {n2_cases}")
    n2_results = run_n2(top20_k, gen_idx, lod_idx, Y_full, bus_gen_cap, bus_gen_H, delta0, Pm_raw)
    n2_stable   = sum(1 for r in n2_results if r["stable"])
    n2_unstable = sum(1 for r in n2_results if not r["stable"])
    print(f"  N-2 安定: {n2_stable}, 不安定: {n2_unstable}")

    print("\n" + "=" * 60)
    print("Step 9: 図生成")
    print("=" * 60)
    make_figure(buses, edges_full, gen_idx, n1_results, worst_n1,
                t_worst, delta_worst, delta0_surv_w)

    elapsed = time.time() - t0
    print(f"\n完了 ({elapsed:.1f}s)")
    print("=" * 60)
    print(f"  バス数:        {n} (500kV: {n500}, 275kV: {n275})")
    print(f"  エッジ数:      {len(edges_full)}")
    print(f"  発電機バス数:  {n_gen_buses}")
    print(f"  総設備容量:    {total_cap:.0f} MW")
    print(f"  N-1: 安定={n_stable}, 不安定={n_unstable}")
    print(f"  N-2: 安定={n2_stable}, 不安定={n2_unstable}")
    print(f"  最悪N-1偏差:   {worst_dev:.1f}°")


if __name__ == "__main__":
    main()
