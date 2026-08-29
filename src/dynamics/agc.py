"""Multi-area Load-Frequency Control (AGC) for All-Japan-Grid.

Closes the operations chain  UC → power flow → AGC:

* the **UC** solution decides which units are online (→ inertia), their
  base points (→ regulation headroom) and the largest online unit
  (→ the credible N-1 disturbance);
* the **extracted network** supplies the inter-area tie stiffness
  T_ab = Σ 1/x over the actual OSM-derived corridors crossing each
  area boundary — this coupling is *measured from the model*, not assumed;
* the **AGC layer** (this module) simulates primary (governor-free /
  droop + inertia + load damping) and secondary (LFC: TBC / FFC)
  frequency response per synchronous island.

Generator / control modelling follows the **IEEJ standard model AGC30**
(電気学会技術報告 GH1386「電力需給・周波数シミュレーションの標準解析
モデル」) in a deliberately *simplified* form — the owner's licensed
AGC30 implementation (Simulink, 30-unit) is the reference; this module
keeps its structure and constants but reduces each plant to a 2nd-order
governor–turbine aggregate per area×class:

    dx1_g/dt = (−Δf_a/R_g + s_g − x1_g) / Tg_g       (governor)
    dx2_g/dt = (x1_g − x2_g) / Tt_g                   (turbine)
    ΔPm_g    = clip(x2_g, ±GF幅·S_g, UC headroom)     (AGC30 PLM + UC room)

secondary control (AGC30 LFC, continuous-time approximation of the
5-s cycle):

    ACE_a  = ΔP_tie,a + B_a Δf_a          (TBC; single-area → FFC)
    z_a    : ACE smoothed (AGC30 α=0.3 @5 s → T_s ≈ 15 s), AR deadband 10 MW
    u_a    = −(KP z_a + KI ∫z_a)          (AGC30 KP=1.0, KI=0.003 s⁻¹)
    ds_g/dt = clip((α_g u_a − s_g)/T_lfc, ±rate_g)    (機種別出力変化率)

island model (deviation domain, pu on the 100 MVA system base):

    dΔδ_a/dt   = 2π f0 Δf_a
    ΔP_tie,a   = Σ_b T_ab (Δδ_a − Δδ_b)
    M_a dΔf_a/dt = Σ_g ΔPm_g − ΔPL_a − D_a Δf_a − ΔP_tie,a

Parameter provenance (捏造ゼロ contract — every constant is labelled):

* per-class droop / GF width / ramp rate / governor–turbine time
  constants: **AGC30 定数.xlsx** (GH1386) — see ``AGC30_CLASSES``; the
  2nd-order reduction per class is ours and is stated inline;
* LFC constants KP/KI/AR-deadband/cycle & smoothing: AGC30 initset_lfc.m;
* load frequency characteristic K_L = 2 %MW/%Hz: AGC30 initset_inertia.m;
* frequency bias: Japanese 系統定数 convention 10 %MW/Hz of area demand
  (AGC30 K_A = 0.1);
* inertia H per fuel: ``FUEL_DEFAULT_PARAMS`` (Anderson & Fouad / Kundur /
  PSSE library) — AGC30 supplies island inertia as an exogenous input, so
  the per-fuel H ledger of the transient suite is reused here.

Results are structural demonstrations on the open model, not operational
predictions; no utility-internal control parameters are used.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.integrate import solve_ivp

S_BASE_MVA = 100.0

# ── AGC30 plant classes (GH1386 定数.xlsx; simplified 2nd-order form) ────
#   R      : 速度調定率 DELTA (pu on class capacity; AGC30 4–5 % → 0.04)
#   gf     : ガバナフリー幅 PLM (pu of class capacity; ST ±5 %, GTCC t2 ±10 %)
#   rate   : LFC出力変化率 R_MWD (pu/min of class capacity)
#   Tg     : governor lag [s] — ST: スピードリレー0.2+サーボ0.2;
#            GTCC: 負荷設定時定数1.0 (type2); hydro: コンバータ0.367+サーボ0.198
#   Tt     : turbine lag [s] — ST: K_G·T4+(1−K_G)·T5 = 0.3·0.25+0.7·9 ≈ 6.4
#            (高圧/低圧再熱の分担加重・簡約は本モジュール);
#            GTCC: GT燃料系≈1.0 — GT分担比0.65のみ速応、HRSG(300 s)は捨象
#            → resp_share=0.65; hydro: 水路特性 Tw≈2.0 (PID補償前提で簡約)
#   agc    : LFC(二次調整)対象か
#   resp_share: 周波数応答に使える容量比率 (GTCCのGT分担0.65以外は1.0)
AGC30_CLASSES: Dict[str, Dict] = {
    "oil":   dict(R=0.04, gf=0.05, rate=0.012, Tg=0.4, Tt=6.4, agc=True,
                  resp_share=1.0),
    "coal":  dict(R=0.04, gf=0.05, rate=0.03, Tg=0.3, Tt=6.4, agc=True,
                  resp_share=1.0),
    "lng":   dict(R=0.03, gf=0.10, rate=0.047, Tg=1.0, Tt=1.0, agc=True,
                  resp_share=0.65),          # GTCC type2 相当に写像
    "hydro": dict(R=0.04, gf=0.10, rate=0.30, Tg=0.6, Tt=2.0, agc=True,
                  resp_share=1.0),           # 揚水系: RATE 0.0167pu/s≈1pu/min→保守的に0.3
    "geothermal": dict(R=0.05, gf=0.05, rate=0.01, Tg=0.4, Tt=6.4, agc=False,
                       resp_share=1.0),
    "biomass":    dict(R=0.05, gf=0.05, rate=0.01, Tg=0.4, Tt=6.4, agc=False,
                       resp_share=1.0),
    "nuclear":    None,     # governor-free運用: 慣性のみ(日本の慣行)
    "unknown":    dict(R=0.05, gf=0.05, rate=0.01, Tg=0.4, Tt=6.4, agc=False,
                       resp_share=1.0),
}

K_LOAD = 2.0          # 負荷周波数特性 K_L [%MW/%Hz] (AGC30 initset_inertia.m)
K_SYS = 0.10          # 系統定数(バイアス) [pu MW/Hz on area demand] = 10 %MW/Hz
LFC_KP = 1.0          # AGC30 initset_lfc.m KP_A
LFC_KI = 0.003        # AGC30 initset_lfc.m KI_A [1/s]
LFC_TS = 15.0         # ACE平滑: α=0.3 @5s周期 の連続近似 (5/0.3 ≈ 16.7 → 15 s)
LFC_DB_MW = 10.0      # AR不感帯 XAR [MW] (AGC30)
# 簡易UFLS(周波数低下時の負荷遮断) — プラント粒度のN-1上界シナリオ用。
# 段数・整定は典型値(実整定は事業者ごとで非公開): Δf −1.5/−2.0/−2.5 Hz で
# 各エリア負荷の10%を段階遮断。シグモイド近似(幅0.05Hz)・非ラッチ
# (復帰時の手動再閉路は捨象) — 簡易実装であることを台帳に明記
UFLS_STEPS_HZ = (-1.5, -2.0, -2.5)
UFLS_SHED_FRAC = 0.10
LFC_TLAG = 5.0        # LFC制御周期→群への指令一次遅れ [s]
LFC_CAP_FRAC = 0.05   # LFC確保容量 = エリア需要の5% (AGC30のPMAX/PMIN方式に
                      # 倣った上限。日本のLFC確保容量の典型値≈需要数%)。
                      # 持続分はEDCが引き継ぐ — 二重積分の張り合いを防ぐ
T_EDC = 300.0         # EDC周期5分(AGC30 initset_edc.m)の連続近似 [s] — 持続
                      # 不平衡の経済再配分。バイアスはβ_a(自然応答)で外乱エリア
                      # へ帰属させる(EDCは需給計画の再配分であり系統定数を介さない)


@dataclasses.dataclass
class ResponseGroup:
    """Area×class aggregate of committed, frequency-responsive units."""
    area: str
    fuel: str
    s_mva: float          # committed (online) capacity in the group [MVA]
    room_up_mw: float     # Σ (Pmax − P_uc) — UC headroom (upward)
    room_dn_mw: float     # Σ (P_uc − Pmin) — downward room
    R: float
    gf: float             # ガバナフリー幅 [pu of s_resp]
    rate: float           # LFC変化率 [pu/min of s_resp]
    Tg: float
    Tt: float
    agc: bool
    resp_share: float = 1.0
    alpha: float = 0.0    # AGC participation factor within the area (Σ=1)

    @property
    def s_resp(self) -> float:
        """Frequency-responsive capacity [MVA]."""
        return self.s_mva * self.resp_share

    @property
    def inv_R_sys(self) -> float:
        """1/R referred to the system base [pu ΔP / pu Δf]."""
        return (self.s_resp / S_BASE_MVA) / self.R

    @property
    def gf_pu(self) -> float:
        """ガバナフリー幅 [pu on S_BASE]."""
        return self.gf * self.s_resp / S_BASE_MVA

    @property
    def rate_pu_s(self) -> float:
        """LFC変化率 [pu on S_BASE / s]."""
        return self.rate * self.s_resp / S_BASE_MVA / 60.0


@dataclasses.dataclass
class AreaSpec:
    """One control area (TSO zone) of a synchronous island."""
    name: str
    M: float              # Σ 2 H_i S_i / S_base over online units [pu·s]
    load_mw: float        # area demand at the studied hour
    groups: List[ResponseGroup] = dataclasses.field(default_factory=list)

    @property
    def D_sys(self) -> float:
        """負荷周波数特性 K_L=2%MW/%Hz → pu ΔP/pu Δf on S_BASE."""
        return K_LOAD * self.load_mw / S_BASE_MVA

    @property
    def beta(self) -> float:
        """自然応答 β_a = D + Σ 1/R [pu/pu] (GF幅拘束を考慮しない線形値)."""
        return self.D_sys + sum(g.inv_R_sys for g in self.groups)


@dataclasses.dataclass
class Disturbance:
    """Step disturbance: unit trip = +ΔP load step in its area (the tripped
    unit's inertia/response must be removed from the AreaSpec beforehand)."""
    area: str
    dp_mw: float
    t_step: float = 1.0
    label: str = ""


@dataclasses.dataclass
class LFCResult:
    t: np.ndarray
    df_hz: Dict[str, np.ndarray]
    ptie_mw: Dict[str, np.ndarray]
    ace_mw: Dict[str, np.ndarray]
    pm_mw: Dict[str, np.ndarray]
    agc_mw: Dict[str, np.ndarray]
    f0: float
    nadir_hz: float = 0.0
    rocof_hz_s: float = 0.0             # COI initial RoCoF (analytic ΔP/M)
    qss_hz: float = 0.0                 # β線形の参考値 (GF幅拘束は考慮せず)
    restore_s: Optional[float] = None   # |Δf|<0.02 Hz for good (LFC有効時)
    ledger: Dict = dataclasses.field(default_factory=dict)


class MultiAreaLFC:
    """A synchronous island as a set of control areas coupled by tie lines.

    mode: 'tbc' (多エリア島; 単エリアでは tie項=0 で実質FFC) / 'off'
    (一次調整のみ; LFC無効 — 比較用)。
    """

    def __init__(self, f0: float, areas: List[AreaSpec],
                 tie_pu: Dict[Tuple[str, str], float],
                 mode: str = "tbc", ufls: bool = False):
        self.f0 = f0
        self.areas = areas
        self.mode = mode
        self.ufls = ufls
        self.names = [a.name for a in areas]
        n = len(areas)
        self.T = np.zeros((n, n))
        for (a, b), t_ab in tie_pu.items():
            if a in self.names and b in self.names:
                i, j = self.names.index(a), self.names.index(b)
                self.T[i, j] = self.T[j, i] = t_ab
        # LFC participation: headroom share among agc-capable groups
        for ar in areas:
            cap = [g for g in ar.groups if g.agc and g.room_up_mw > 0]
            tot = sum(g.room_up_mw for g in cap)
            for g in ar.groups:
                g.alpha = (g.room_up_mw / tot) if (g in cap and tot > 0) else 0.0

    def _groups(self) -> List[Tuple[int, ResponseGroup]]:
        return [(i, g) for i, ar in enumerate(self.areas) for g in ar.groups]

    # 剛結合簡約(COI): 実網から測った T_ab は 10^3〜10^6 pu/rad — 対応する
    # エリア間動揺モードは数Hz〜数十Hz で LFC帯域(0.01〜0.1Hz)の遥か上。
    # よって島内エリアは1つの周波数(COI)を共有するとし、連系偏差は
    # 各エリアの収支から代数的に復元する:
    #   ΔP_tie,a = surplus_a − (M_a/M_tot)·Σ surplus,
    #   surplus_a = ΣΔPm − ΔPL − D_a·Δf
    # (測定した T_ab はこの簡約の妥当性根拠として ledger に残す。
    #  動揺そのものは transient suite(swing_solver)の守備範囲)
    # state: [Δf(1), x1(ng), x2(ng), s(ng), z(n), w(n), e(n)]
    def simulate(self, dist: Disturbance, t_end: float = 300.0) -> LFCResult:
        n = len(self.areas)
        gs = self._groups()
        ng = len(gs)
        di = self.names.index(dist.area)
        dp_pu = dist.dp_mw / S_BASE_MVA
        M = np.array([a.M for a in self.areas])
        m_tot = float(max(M.sum(), 1e-6))
        D = np.array([a.D_sys for a in self.areas])
        B = np.array([K_SYS * a.load_mw * self.f0 / S_BASE_MVA
                      for a in self.areas])
        db_pu = LFC_DB_MW / S_BASE_MVA
        beta_a = np.array([a.beta for a in self.areas])
        lfc_on = self.mode != "off"
        ia = np.array([i for i, _g in gs], dtype=int)
        invR = np.array([g.inv_R_sys for _i, g in gs])
        Tg = np.array([g.Tg for _i, g in gs])
        Tt = np.array([g.Tt for _i, g in gs])
        alpha = np.array([g.alpha if g.agc else 0.0 for _i, g in gs])
        rate = np.array([g.rate_pu_s for _i, g in gs])
        gf = np.array([g.gf_pu for _i, g in gs])
        r_up = np.array([g.room_up_mw / S_BASE_MVA for _i, g in gs])
        r_dn = np.array([g.room_dn_mw / S_BASE_MVA for _i, g in gs])
        load_pu = np.array([a.load_mw / S_BASE_MVA for a in self.areas])
        lfc_cap = LFC_CAP_FRAC * load_pu

        def parts(t, y):
            """状態→(各微分, 診断量)。剛結合なので Δf はスカラー1状態。"""
            df = y[0]
            x1 = y[1:1 + ng]
            x2 = y[1 + ng:1 + 2 * ng]
            sg = y[1 + 2 * ng:1 + 3 * ng]
            z = y[1 + 3 * ng:1 + 3 * ng + n]
            w = y[1 + 3 * ng + n:1 + 3 * ng + 2 * n]
            e = y[1 + 3 * ng + 2 * n:]
            u_raw = -(LFC_KP * z + LFC_KI * w) if lfc_on else np.zeros(n)
            u = np.clip(u_raw, -lfc_cap, lfc_cap)
            dx1 = (-df * invR + sg - x1) / Tg
            dx2 = (x1 - x2) / Tt
            ds = np.clip((alpha * (u + e)[ia] - sg) / LFC_TLAG, -rate, rate)
            lim_up = np.minimum(gf + np.maximum(sg, 0.0), r_up)
            lim_dn = np.minimum(gf + np.maximum(-sg, 0.0), r_dn)
            pm = np.bincount(ia, np.clip(x2, -lim_dn, lim_up), minlength=n)
            pl = np.zeros(n)
            if t >= dist.t_step:
                pl[di] = dp_pu
            if self.ufls:
                df_hz_now = df * self.f0
                shed = sum(UFLS_SHED_FRAC * 0.5 *
                           (1.0 - np.tanh((df_hz_now - thr) / 0.1))
                           for thr in UFLS_STEPS_HZ)
                pl -= shed * load_pu
            surplus = pm - pl - D * df
            dfdot = surplus.sum() / m_tot
            ptie = surplus - (M / m_tot) * surplus.sum()
            ace = ptie + B * df
            ace_db = np.sign(ace) * np.maximum(np.abs(ace) - db_pu, 0.0)
            dz = (ace_db - z) / LFC_TS
            # アンチワインドアップ(逆算式・連続): LFC出力の飽和超過分を
            # 積分器から引き戻す — 持続分はEDCが基点シフトとして引き継ぐ。
            # ハードな条件付き積分は不連続でLSODAが刻むため逆算式を使う
            dw = z - (u_raw - u) / (LFC_KI * 30.0)
            de = (-(ptie + beta_a * df) / T_EDC) if lfc_on else np.zeros(n)
            return (np.concatenate([[dfdot], dx1, dx2, ds, dz, dw, de]),
                    ptie, ace, pm, u + e)

        def rhs(t, y):
            return parts(t, y)[0]

        y0 = np.zeros(1 + 3 * ng + 3 * n)
        sol = solve_ivp(rhs, (0.0, t_end), y0, method="LSODA",
                        max_step=1.0, rtol=1e-7, atol=1e-10,
                        t_eval=np.arange(0.0, t_end, 0.1))
        t = sol.t
        df = sol.y[0]
        nt = len(t)
        ptie = np.zeros((n, nt)); ace = np.zeros((n, nt))
        pm = np.zeros((n, nt)); cmd = np.zeros((n, nt))
        for k in range(nt):
            _d, p_, a_, m_, c_ = parts(t[k], sol.y[:, k])
            ptie[:, k], ace[:, k], pm[:, k], cmd[:, k] = p_, a_, m_, c_

        beta = sum(a.beta for a in self.areas)
        res = LFCResult(
            t=t,
            df_hz={a: df * self.f0 for a in self.names},
            ptie_mw={a: ptie[i] * S_BASE_MVA for i, a in enumerate(self.names)},
            ace_mw={a: ace[i] * S_BASE_MVA for i, a in enumerate(self.names)},
            pm_mw={a: pm[i] * S_BASE_MVA for i, a in enumerate(self.names)},
            agc_mw={a: cmd[i] * S_BASE_MVA for i, a in enumerate(self.names)},
            f0=self.f0,
            nadir_hz=float(df.min() * self.f0),
            rocof_hz_s=float(-dp_pu / m_tot * self.f0),
            qss_hz=float(-dp_pu / max(beta, 1e-9) * self.f0),
        )
        if lfc_on:
            thr = 0.02
            ok = np.abs(df * self.f0) < thr
            idx = next((k for k in range(nt) if ok[k:].all()), None)
            res.restore_s = (float(t[idx] - dist.t_step)
                             if idx is not None else None)
        res.ledger = {
            "model": "IEEJ AGC30 (GH1386) simplified — 2nd-order per-class "
                     "aggregates; reductions stated in src/dynamics/agc.py",
            "reduction": "coherent-island (COI) — 測定した連系剛性 T_ab が"
                         "LFC帯域外の動揺周波数を与えるため、島内は単一周波数・"
                         "連系偏差は収支から代数復元",
            "mode": self.mode,
            "lfc": {"KP": LFC_KP, "KI": LFC_KI, "Ts_s": LFC_TS,
                    "deadband_mw": LFC_DB_MW, "cycle_lag_s": LFC_TLAG},
            "edc": f"T_EDC={T_EDC:.0f}s (AGC30 EDC周期5分の連続近似・"
                   "β_aバイアスで外乱エリアへ帰属)",
            "bias": f"K={K_SYS:.2f} pu(=10%MW/Hz) × area demand (系統定数方式)",
            "ufls": (f"典型3段 Δf{UFLS_STEPS_HZ}Hz×{UFLS_SHED_FRAC:.0%}/段・"
                     "tanh近似・非ラッチ(簡易)" if self.ufls else "off"),
            "load_damping": f"K_L={K_LOAD}%MW/%Hz (AGC30 initset_inertia.m)",
            "M_pu_s": {a.name: round(a.M, 1) for a in self.areas},
            "beta_pu": {a.name: round(a.beta, 1) for a in self.areas},
            "tie_pu_per_rad": {f"{a}-{b}": round(float(self.T[i, j]), 1)
                               for i, a in enumerate(self.names)
                               for j, b in enumerate(self.names)
                               if j > i and self.T[i, j] > 0},
            "disturbance": dataclasses.asdict(dist),
            "provenance": "class constants from AGC30 定数.xlsx (GH1386); "
                          "H per fuel = FUEL_DEFAULT_PARAMS (Anderson&Fouad/"
                          "Kundur/PSSE lib). Structural demonstration on the "
                          "open model — not operational data.",
        }
        return res


# ── builders ─────────────────────────────────────────────────────────────

# UC正規化燃料 → AGC30クラス（GTCC/汽力の区別はUC燃料語彙に無いため
# lng はGTCC type2 相当へ写像する簡易化 — 台帳に開示）
FUEL_TO_CLASS = {"oil": "oil", "coal": "coal", "lng": "lng",
                 "hydro": "hydro", "geothermal": "geothermal",
                 "biomass": "biomass", "nuclear": "nuclear"}


def build_area_from_uc(area: str, uc_result, generators, hour: int,
                       load_mw: float) -> AreaSpec:
    """Aggregate the UC solution of one zone at one hour into an AreaSpec."""
    from src.dynamics.models.sync_generator import FUEL_DEFAULT_PARAMS
    from src.uc.pf_injection import normalize_fuel

    gen_map = {g.id: g for g in generators}
    m = 0.0
    agg: Dict[str, Dict[str, float]] = {}
    for sched in uc_result.schedules:
        g = gen_map.get(sched.generator_id)
        if g is None or g.region != area:
            continue
        if hour >= len(sched.commitment) or not sched.commitment[hour]:
            continue
        fuel = normalize_fuel(str(getattr(g, "fuel_type", "") or ""))
        if fuel in ("solar", "wind", "battery"):
            continue                    # 慣性・応答なし (v1、グリッドフォーミング仮定なし)
        cls = FUEL_TO_CLASS.get(fuel, "unknown")
        s_mva = float(g.capacity_mw)
        h = (FUEL_DEFAULT_PARAMS.get(fuel)
             or FUEL_DEFAULT_PARAMS["unknown"])["H"]
        m += 2.0 * h * s_mva / S_BASE_MVA
        p = float(sched.power_output_mw[hour])
        d = agg.setdefault(cls, {"s": 0.0, "up": 0.0, "dn": 0.0})
        d["s"] += s_mva
        d["up"] += max(0.0, float(g.capacity_mw) - p)
        d["dn"] += max(0.0, p - float(getattr(g, "p_min_mw", 0.0) or 0.0))
    groups = []
    for cls, d in sorted(agg.items()):
        dyn = AGC30_CLASSES.get(cls, AGC30_CLASSES["unknown"])
        if dyn is None:                 # nuclear: inertia only
            continue
        groups.append(ResponseGroup(
            area=area, fuel=cls, s_mva=d["s"], room_up_mw=d["up"],
            room_dn_mw=d["dn"], R=dyn["R"], gf=dyn["gf"], rate=dyn["rate"],
            Tg=dyn["Tg"], Tt=dyn["Tt"], agc=dyn["agc"],
            resp_share=dyn["resp_share"]))
    return AreaSpec(name=area, M=m, load_mw=load_mw, groups=groups)


def tie_stiffness_from_net(net, zones: Sequence[str]) -> Dict[Tuple[str, str], float]:
    """T_ab = S_base·Σ 1/x_pu over in-service AC lines whose endpoints lie in
    different zones of the built pandapower net (bus.zone from territory
    attribution).  Units: pu MW / rad on S_BASE.  DC/BTB links are absent
    from the AC line table by construction (interventions #31/#32), so the
    sum runs over genuinely synchronous corridors only."""
    out: Dict[Tuple[str, str], float] = {}
    zb = net.bus["zone"]
    vn = net.bus["vn_kv"]
    ln = net.line[net.line.in_service]
    for _, row in ln.iterrows():
        za, zc = zb.at[int(row.from_bus)], zb.at[int(row.to_bus)]
        if za == zc or za not in zones or zc not in zones:
            continue
        x_ohm = float(row.x_ohm_per_km) * float(row.length_km) \
            / max(int(row.parallel), 1)
        if x_ohm <= 0:
            continue
        v_kv = float(vn.at[int(row.from_bus)])
        x_pu = x_ohm / (v_kv * v_kv / S_BASE_MVA)
        key = tuple(sorted((za, zc)))
        out[key] = out.get(key, 0.0) + 1.0 / x_pu
    return out


def largest_online_unit(uc_result, generators, hour: int,
                        regions: Sequence[str]):
    """The credible N-1 disturbance: largest committed unit in the island."""
    gen_map = {g.id: g for g in generators}
    best = None
    for sched in uc_result.schedules:
        g = gen_map.get(sched.generator_id)
        if g is None or g.region not in regions:
            continue
        if hour >= len(sched.commitment) or not sched.commitment[hour]:
            continue
        p = float(sched.power_output_mw[hour])
        if p <= 0:
            continue
        if best is None or p > best[1]:
            best = (g, p)
    return best


def remove_unit_from_area(area: AreaSpec, gen, p_mw: float) -> AreaSpec:
    """Return a copy of `area` with the tripped unit's inertia and response
    removed (trip = the unit no longer contributes M, droop or headroom)."""
    from src.dynamics.models.sync_generator import FUEL_DEFAULT_PARAMS
    from src.uc.pf_injection import normalize_fuel
    fuel = normalize_fuel(str(getattr(gen, "fuel_type", "") or ""))
    cls = FUEL_TO_CLASS.get(fuel, "unknown")
    s_mva = float(gen.capacity_mw)
    h = (FUEL_DEFAULT_PARAMS.get(fuel) or FUEL_DEFAULT_PARAMS["unknown"])["H"]
    groups = []
    for g in area.groups:
        g2 = dataclasses.replace(g)
        if g2.fuel == cls:
            g2.s_mva = max(0.0, g2.s_mva - s_mva)
            g2.room_up_mw = max(0.0, g2.room_up_mw - (s_mva - p_mw))
            g2.room_dn_mw = max(0.0, g2.room_dn_mw - p_mw)
        groups.append(g2)
    return AreaSpec(name=area.name,
                    M=max(0.0, area.M - 2.0 * h * s_mva / S_BASE_MVA),
                    load_mw=area.load_mw, groups=groups)
