"""
3地域 最悪N-1 動揺波形比較 (fig_swing_waveforms.png)
北海道・東北・九州の最大容量機脱落後の
ロータ角スイング曲線 δ_i(t) を時間領域で可視化する．

修正点:
- Pm の中心化（ゼロ和条件）を平衡計算・シミュレーション双方で一貫させる
- 事前平衡 δ₀（Y_pre）から事故後平衡 δ*（Y_post）への初期変位が振動の源泉
- 過渡期モデル: t=0~t_cl で故障(Pe→0), t>t_cl で発電機脱落後ネットワーク
"""
import json, os, sys, math, platform
import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import fsolve
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

if platform.system() == "Darwin":
    plt.rcParams["font.family"] = ["Hiragino Sans", "Apple SD Gothic Neo", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
OUT_DIR  = "papers/figs"
DATA_DIR = "data"
os.makedirs(OUT_DIR, exist_ok=True)

OMEGA_S  = 2 * np.pi * 50.0   # rad/s (50 Hz)
D_COEFF  = 0.05                # 制動係数 (pu) — 実系統の制動比 5〜10%相当
T_FAULT  = 0.10                # 故障継続時間 (s) ≈ 5サイクル@50Hz
T_END    = 8.0                 # シミュレーション時間 (s)
MAX_GENS = 10                  # 地域あたり上位機数

H_BY_FUEL = {
    "nuclear":6.5,"coal":6.5,"hydro":4.0,
    "gas":5.0,"lng":5.0,"oil":5.0,
    "geothermal":4.0,"biomass":4.0,"waste":4.0,
}
TYPICAL_CAP = {
    "nuclear":1100,"coal":700,"lng":500,"gas":500,
    "oil":400,"hydro":200,"geothermal":50,"biomass":100,"waste":30,
}
FUEL_COL = {
    "nuclear":"#7B2D8E","coal":"#444444","lng":"#E8832A","gas":"#E8832A",
    "oil":"#C44E52","hydro":"#2196F3","geothermal":"#FF5722",
    "biomass":"#8BC34A","waste":"#9E9E9E",
}
FUEL_JP = {
    "nuclear":"原子力","coal":"石炭","lng":"LNG","gas":"LNG",
    "oil":"石油","hydro":"水力","geothermal":"地熱","biomass":"バイオ","waste":"廃棄",
}
REGION_JP = {"hokkaido":"北海道","tohoku":"東北","kyushu":"九州"}


# ── ユーティリティ ────────────────────────────────────────────────────

def haversine_km(lo1, la1, lo2, la2):
    # Canonical impl in src.utils.geo_utils; (lon, lat) order preserved.
    from src.utils.geo_utils import haversine_distance
    return haversine_distance(la1, lo1, la2, lo2)


def load_gens(region, max_gens=MAX_GENS):
    with open(f"{DATA_DIR}/{region}_plants.geojson") as f:
        gj = json.load(f)
    gens = []
    for feat in gj["features"]:
        p = feat["properties"]
        coords = feat["geometry"]["coordinates"]
        lon, lat = float(coords[0]), float(coords[1])
        fuel = (p.get("fuel_type") or "unknown").lower().strip()
        if fuel in ("solar","battery","wind","unknown") or fuel.startswith("http"):
            continue
        H = H_BY_FUEL.get(fuel, 0.0)
        if H == 0.0:
            continue
        cap = p.get("capacity_mw")
        if cap is None or cap < 0:
            cap = float(TYPICAL_CAP.get(fuel, 100))
        elif float(cap) < 10:
            continue
        else:
            cap = float(cap)
        gens.append({"name":(p.get("name") or f"{fuel}_{len(gens)}")[:20],
                     "lon":lon,"lat":lat,"cap_mw":cap,"fuel":fuel,"H":H})
    gens.sort(key=lambda g: -g["cap_mw"])
    return gens[:max_gens]


def build_ybus(gens):
    n = len(gens)
    Y = np.zeros((n,n), dtype=complex)
    K, DMAX = 25.0, 300.0  # 弱め結合でinter-area周波数を0.3-0.6 Hzに
    for i in range(n):
        for j in range(i+1,n):
            d = haversine_km(gens[i]["lon"],gens[i]["lat"],
                             gens[j]["lon"],gens[j]["lat"])
            if 0.1 < d <= DMAX:
                B = K/d
                Y[i,j]+=1j*B; Y[j,i]+=1j*B
                Y[i,i]-=1j*B; Y[j,j]-=1j*B
    for i in range(n):
        if abs(Y[i,i]) < 1e-12:
            dists = sorted((haversine_km(gens[i]["lon"],gens[i]["lat"],
                           gens[j]["lon"],gens[j]["lat"]),j)
                          for j in range(n) if j!=i)
            d,j = dists[0]
            B = K/max(d,1.0)
            Y[i,j]+=1j*B; Y[j,i]+=1j*B; Y[i,i]-=1j*B; Y[j,j]-=1j*B
    return Y


def Pe_vec(delta, E, Y):
    diff = delta[:,None] - delta[None,:]
    EiEj = E[:,None]*E[None,:]
    return np.sum(EiEj*(Y.real*np.cos(diff)+Y.imag*np.sin(diff)), axis=1)


def equilibrium(Pm_raw, E, Y):
    """Pm_raw を内部でゼロ和中心化して平衡点を求める."""
    n = len(Pm_raw)
    Pm_c = Pm_raw - Pm_raw.mean()        # ← ゼロ和条件

    def res(d):
        r = Pe_vec(d, E, Y) - Pm_c
        r[0] = d[0]                       # 参照バス固定
        return r

    best_d, best_err = np.linspace(-0.4,0.4,n), np.inf
    for scale in [1.0, 0.5, 0.2]:
        d0 = np.linspace(-0.4*scale, 0.4*scale, n)
        try:
            d_sol = fsolve(res, d0, full_output=False)
            err = np.max(np.abs(res(d_sol)))
            if err < best_err:
                best_err = err
                best_d = d_sol
        except Exception:
            pass
    return best_d


# ── 動揺シミュレーション ──────────────────────────────────────────────

def simulate(gens, trip_idx):
    """最悪N-1: trip_idx 機を t=0 で脱落（t<T_FAULT は故障中）"""
    n = len(gens)
    caps   = np.array([g["cap_mw"] for g in gens])
    E_pre  = np.ones(n)
    Pm_pre = caps / caps.sum()            # pu (sum=1)
    M_pre  = np.array([2*g["H"]/OMEGA_S for g in gens])

    Y_pre = build_ybus(gens)

    # ── 事前平衡点 δ₀ ──
    delta0 = equilibrium(Pm_pre, E_pre, Y_pre)

    # ── 事故後ネットワーク (trip_idx 除外) ──
    surv   = [g for i,g in enumerate(gens) if i != trip_idx]
    ns     = len(surv)
    idx_map= [i for i in range(n) if i != trip_idx]

    caps_s  = np.array([g["cap_mw"] for g in surv])
    E_s     = np.ones(ns)
    Pm_s    = caps_s / caps_s.sum()       # pu (sum=1)
    Pm_s_c  = Pm_s - Pm_s.mean()         # ← 事故後中心化 Pm（シミュレーションに使用）
    M_s     = np.array([2*g["H"]/OMEGA_S for g in surv])
    D_s     = D_COEFF * np.ones(ns)

    Y_post = build_ybus(surv)

    # ── 事故後平衡点 δ* ──
    delta_star = equilibrium(Pm_s, E_s, Y_post)   # equilibrium 内部で中心化

    # ── 初期条件: 事前平衡角（= 大きなオフセットの源泉） ──
    d_init = delta0[idx_map]
    w_init = np.zeros(ns)
    y0     = np.concatenate([d_init, w_init])

    def rhs(t, y):
        d, w = y[:ns], y[ns:]
        if t < T_FAULT:
            # 故障中: 脱落機バスへの電力输送ゼロ（完全短絡近似）
            Pe = np.zeros(ns)
        else:
            Pe = Pe_vec(d, E_s, Y_post)
        dd = w
        dw = (Pm_s_c - Pe - D_s*w) / M_s   # ← Pm_s_c を使う
        return np.concatenate([dd, dw])

    sol = solve_ivp(rhs, [0, T_END], y0, method="RK45",
                    max_step=0.01, rtol=1e-7, atol=1e-9)

    # ロータ角: δ_i(t) を度で返す（絶対値, 参照バス基準）
    t        = sol.t
    delta_t  = sol.y[:ns, :] * 180/np.pi      # degree
    delta_st = delta_star * 180/np.pi

    # 周波数偏差: ω_i(t) / (2π) [Hz]
    freq_t   = sol.y[ns:, :] / (2*np.pi)

    return t, delta_t, delta_st, freq_t, surv


# ── 描画 ─────────────────────────────────────────────────────────────

REGIONS = ["hokkaido", "tohoku", "kyushu"]

fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), facecolor="white",
                          gridspec_kw={"wspace":0.28})

for col_idx, region in enumerate(REGIONS):
    gens = load_gens(region)
    trip_idx  = 0
    trip_name = gens[trip_idx]["name"]
    trip_cap  = gens[trip_idx]["cap_mw"]
    trip_fuel = gens[trip_idx]["fuel"]
    print(f"{region}: {len(gens)}機  trip={trip_name} ({trip_cap:.0f}MW, {trip_fuel})")

    t, delta_t, delta_st, freq_t, surv = simulate(gens, trip_idx)

    ax = axes[col_idx]

    fuels_seen = set()
    for i, g in enumerate(surv):
        col = FUEL_COL.get(g["fuel"], "#888")
        lbl = FUEL_JP.get(g["fuel"], g["fuel"]) if g["fuel"] not in fuels_seen else None
        fuels_seen.add(g["fuel"])
        ax.plot(t, delta_t[i], color=col, lw=1.3, alpha=0.85, label=lbl)

    # 事故後平衡点（点線）
    for i in range(len(surv)):
        ax.axhline(delta_st[i], color=FUEL_COL.get(surv[i]["fuel"],"#888"),
                   lw=0.5, ls=":", alpha=0.35)

    ax.axvline(T_FAULT, color="#cc0000", lw=1.0, ls="--", alpha=0.8,
               label=f"故障除去 {T_FAULT*1000:.0f}ms")

    max_exc = np.max(np.abs(delta_t - delta_st[:, None]))
    nadir   = float(np.min(freq_t)*1000)

    ax.set_xlabel("時刻 (s)", fontsize=8)
    ax.set_ylabel("ロータ角 δ (°)", fontsize=8) if col_idx == 0 else None
    ax.set_xlim(0, T_END)
    ax.set_title(
        f"({chr(97+col_idx)}) {REGION_JP[region]}\n"
        f"{FUEL_JP.get(trip_fuel,trip_fuel)} {trip_cap:.0f} MW 脱落\n"
        f"最大偏差 {max_exc:.1f}°  Δf$_{{min}}$ {nadir:.0f} mHz",
        fontsize=8.5, fontweight="bold"
    )
    ax.legend(fontsize=6.5, loc="upper right", framealpha=0.85, ncol=1)
    ax.grid(color="#eee", lw=0.5)
    ax.tick_params(labelsize=7)

fig.suptitle(
    f"最悪N-1（最大容量機脱落）後のロータ角スイング曲線"
    f"（故障時間 {T_FAULT*1000:.0f} ms, 古典機モデル, $D={D_COEFF}$ pu）",
    fontsize=10, y=1.02
)

out = f"{OUT_DIR}/fig_swing_waveforms.png"
plt.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
plt.close()
print(f"Saved: {out}")
