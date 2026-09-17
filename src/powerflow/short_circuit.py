"""テブナン短絡容量と SCR(短絡容量比)ベースの IBR 連系可能量 — トラックC②(2026-09-02).

背景(docs/reports/grid_strength_phase0_2026-08-17.md):
  Phase 0 は数値 Ybus 出荷物に典型値 xd''=0.2pu を一律に与えて S_sc 地図を描いた。
  オーナー課題④「SCR/ESCR への正規化 — 連系(予定)容量比に直す」がこのモジュール。

定式(全て**系統ベース pu・baseMVA=net.sn_mva**):
  1. 網の Ybus を pandapower の ppc(makeYbus)から作る。IEC 60909 の流儀に合わせ、
     線路充電容量 B とバスシャント・負荷は**既定で無視**(include_shunts=False)。
     pandapower.shortcircuit.calc_sc も同じ前提(検証で一致を確認)。
  2. 同期機の内部インピーダンス(次過渡リアクタンス)を接続バスの対角に足す:
        x_sys = xd''_mb · baseMVA / S_mva      (機械ベース→系統ベース換算)
        y_g   = 1 / (j·x_sys)                  (r は既定 0。x/r 指定で複素化可)
     機械の型式・xd''_mb・容量集約は src/dynamics/machine_agg.aggregate_machines に
     一本化(燃料種→典型値。IBR は同期機として扱わず**短絡電流源にしない**=保守側)。
  3. Z_th(対角) = diag(Y⁻¹) を疎 LU(scipy splu)の列ソルブでブロック計算。
     密逆行列は作らない(7k バスで数十秒)。
  4. S_sc[MVA] = baseMVA · V² / |Z_th|。V は既定 1.0pu(IEC 60909 の c 係数は掛けない。
     calc_sc の skss_mw と比べるときは c=1.1 を掛けること)。AC 解があれば
     v_pu=net.res_bus.vm_pu を渡せる。
  5. SCR = S_sc / P_ibr。SCR 制約の連系可能量
        P_max_scr = max(S_sc / SCR_min − P_ibr_existing, 0)
     SCR_min 既定 3.0(IEEE Std 1204-1997 の「弱い系統」目安 <3)。既設 IBR は
     machine_agg の ibr 勘定(OSM 容量ベース・#25 の太陽光既定 0.10MW を含む)。

限界(帳簿):
  - 線路インピーダンスは電圧階級別の合成値(観測 R/X ではない)。機械定数は典型値。
  - 変圧器は ppc の枝としてそのまま入る(タップ・零相は見ない。三相対称短絡のみ)。
  - 合成 slack(add_per_component_slacks の ext_grid)は**既定で電流源にしない**
    (include_ext_grid=False)。含めるなら s_sc_mva を明示すること。
  - SCR は「目安」。接続可否判断ではない(系統側の実データが要る)。
"""
from __future__ import annotations

import dataclasses
from typing import Dict, Optional

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import splu

DEFAULT_SCR_MIN = 3.0        # IEEE 1204-1997: SCR<3 を弱系統とみなす目安
_Z_NAN_ABS = 1e4             # 正則化痕(無電源成分)を NaN 化する |Z| 閾値


@dataclasses.dataclass
class SCResult:
    """バス別テブナン量。配列は ppc バス行順(bus_row_of_label で pandapower ラベルから引く)。"""
    base_mva: float
    z_th_pu: np.ndarray            # complex, 系統ベース pu
    s_sc_mva: np.ndarray           # baseMVA·V²/|Z_th|  (NaN=電源に繋がらない成分)
    v_pu: np.ndarray
    bus_row_of_label: Dict[int, int]
    label_of_row: np.ndarray       # 各行の代表 pandapower バスラベル
    n_source: int
    source_mva: float              # 電流源として入れた同期機容量の合計 [MVA]
    note: str

    def s_sc_by_label(self) -> Dict[int, float]:
        return {int(lbl): float(self.s_sc_mva[row])
                for lbl, row in self.bus_row_of_label.items()}


# ── 1. 網 Ybus ──────────────────────────────────────────────────────────
def build_sc_ybus(net, include_shunts: bool = False):
    """(Ybus[csc, 系統pu], bus_row_of_label, label_of_row, baseMVA) を返す。

    net._ppc が無ければ rundcpp で作る(DC でも ppc 枝は R/X/B を保持する)。
    include_shunts=False で線路充電 B とバスシャント(GS/BS)を落とす(IEC 60909 流儀)。
    """
    import pandapower as pp
    from pandapower.pypower.idx_brch import BR_B
    from pandapower.pypower.idx_bus import BS, GS
    from pandapower.pypower.makeYbus import makeYbus

    if getattr(net, "_ppc", None) is None or "branch" not in net._ppc:
        pp.rundcpp(net)
    ppc = net._ppc
    bus = ppc["bus"].copy()
    branch = ppc["branch"].copy()
    if not include_shunts:
        branch[:, BR_B] = 0.0
        bus[:, GS] = 0.0
        bus[:, BS] = 0.0
    base = float(ppc["baseMVA"])
    Y, _yf, _yt = makeYbus(base, bus, branch)
    lookup = net._pd2ppc_lookups["bus"]
    row_of = {int(lbl): int(lookup[int(lbl)]) for lbl in net.bus.index
              if 0 <= int(lookup[int(lbl)]) < Y.shape[0]}
    label_of_row = np.full(Y.shape[0], -1, dtype=int)
    for lbl, row in row_of.items():
        if label_of_row[row] < 0:
            label_of_row[row] = lbl
    return Y.tocsc(), row_of, label_of_row, base


# ── 2. 電流源(同期機・検証用 ext_grid) ─────────────────────────────────
def machine_sources(net, base_mva: float, agg: Optional[dict] = None,
                    x_over_r: Optional[float] = None) -> Dict[int, complex]:
    """同期機集約(machine_agg)から {バスラベル: y_pu(系統ベース)} を返す。

    y = 1/(r + j·x), x = xd''_mb·base/S_mva。x_over_r=None なら r=0(純リアクタンス)。
    IBR は含めない(短絡電流源にしない=保守側。既設 IBR 容量は existing_ibr_mw で別勘定)。
    """
    from src.dynamics.machine_agg import aggregate_machines
    if agg is None:
        agg = aggregate_machines(net)
    out: Dict[int, complex] = {}
    for m in agg["sync"]:
        x = float(m["xd2"]) * base_mva / float(m["S_mva"])
        r = x / x_over_r if x_over_r else 0.0
        out[int(m["bus"])] = out.get(int(m["bus"]), 0j) + 1.0 / complex(r, x)
    return out


def existing_ibr_mw(net, agg: Optional[dict] = None) -> Dict[int, float]:
    """{バスラベル: 既設 IBR 容量[MW]}(machine_agg の ibr 勘定そのもの)。"""
    from src.dynamics.machine_agg import aggregate_machines
    if agg is None:
        agg = aggregate_machines(net)
    return {int(b): float(v) for b, v in agg["ibr"].items()}


def ext_grid_sources(net, base_mva: float, c: float = 1.1) -> Dict[int, complex]:
    """検証用: ext_grid(s_sc_max_mva, rx_max) を IEC 60909 と同じ Z=c·V²/S で電流源化。

    calc_sc(case='max') と厳密に同じ内部インピーダンスになる(c=1.1, vn>1kV)。
    """
    out: Dict[int, complex] = {}
    for _, e in net.ext_grid.iterrows():
        if not bool(e.get("in_service", True)):
            continue
        s = float(e["s_sc_max_mva"])
        rx = float(e.get("rx_max", 0.0) or 0.0)
        zabs = c * base_mva / s                       # pu
        x = zabs / np.sqrt(1.0 + rx * rx)
        r = x * rx
        out[int(e["bus"])] = out.get(int(e["bus"]), 0j) + 1.0 / complex(r, x)
    return out


# ── 3. Z_th 対角(疎 LU 列ソルブ) ────────────────────────────────────────
def thevenin_diag(Y: sp.spmatrix, sources_by_row: Dict[int, complex],
                  block: int = 512) -> np.ndarray:
    """diag((Y + diag(y_src))⁻¹) を返す。電源に繋がらない成分は NaN。"""
    from scipy.sparse.csgraph import connected_components
    n = Y.shape[0]
    add = np.zeros(n, dtype=complex)
    for row, y in sources_by_row.items():
        add[int(row)] += y
    # 電源(電流源)を持たない連結成分は Y が特異(浮いた網)。成分ラベルで先に見つけ、
    # その行だけ微小シャントで正則化してから解き、結果は NaN にする(巨大値を返さない)。
    _ncomp, comp = connected_components(abs(Y) > 0, directed=False)
    powered = np.zeros(_ncomp, dtype=bool)
    for row, y in sources_by_row.items():
        if abs(y) > 0:
            powered[comp[int(row)]] = True
    fix = ~powered[comp]
    fix |= np.abs((Y + sp.diags(add)).diagonal()) < 1e-9   # 完全孤立行
    Yp = (Y + sp.diags(add) + sp.diags(np.where(fix, 1e-6j, 0.0))).tocsc()
    lu = splu(Yp)
    diag = np.empty(n, dtype=complex)
    for s0 in range(0, n, block):
        e0 = min(s0 + block, n)
        rhs = np.zeros((n, e0 - s0), dtype=complex)
        rhs[np.arange(s0, e0), np.arange(e0 - s0)] = 1.0
        X = lu.solve(rhs)
        diag[s0:e0] = X[np.arange(s0, e0), np.arange(e0 - s0)]
    diag = diag.astype(complex)
    diag[np.abs(diag) > _Z_NAN_ABS] = np.nan          # 無電源成分(正則化痕)
    diag[fix] = np.nan
    return diag


# ── 4. まとめ ─────────────────────────────────────────────────────────
def short_circuit_mva(net, sources: Optional[Dict[int, complex]] = None,
                      v_pu=None, include_shunts: bool = False,
                      include_ext_grid: bool = False, c: float = 1.1,
                      agg: Optional[dict] = None) -> SCResult:
    """全バスの S_sc[MVA] を返す。

    sources: {バスラベル: y_pu}。None なら machine_sources(net)。
    include_ext_grid: True なら ext_grid(s_sc_max_mva 必須)も電流源に足す(検証用)。
    v_pu: None=1.0pu 一律 / 'ac'=net.res_bus.vm_pu(AC 解済みのとき) / 配列(ラベル順)。
    """
    Y, row_of, label_of_row, base = build_sc_ybus(net, include_shunts=include_shunts)
    src_mva = 0.0
    if sources is None:
        if agg is None:
            from src.dynamics.machine_agg import aggregate_machines
            agg = aggregate_machines(net)
        sources = machine_sources(net, base, agg=agg)
        src_mva = float(sum(m["S_mva"] for m in agg["sync"] if int(m["bus"]) in row_of))
    src = dict(sources)
    if include_ext_grid:
        for b, y in ext_grid_sources(net, base, c=c).items():
            src[b] = src.get(b, 0j) + y
    by_row: Dict[int, complex] = {}
    n_src = 0
    for lbl, y in src.items():
        if int(lbl) in row_of:
            by_row[row_of[int(lbl)]] = by_row.get(row_of[int(lbl)], 0j) + y
            n_src += 1
    z = thevenin_diag(Y, by_row)
    n = Y.shape[0]
    if v_pu is None:
        v = np.ones(n)
    elif isinstance(v_pu, str) and v_pu == "ac":
        v = np.ones(n)
        for lbl, row in row_of.items():
            vm = net.res_bus.at[lbl, "vm_pu"] if lbl in net.res_bus.index else np.nan
            if np.isfinite(vm):
                v[row] = float(vm)
    else:
        v = np.ones(n)
        for lbl, row in row_of.items():
            v[row] = float(v_pu[lbl])
    zabs = np.abs(z)
    with np.errstate(divide="ignore", invalid="ignore"):
        s_sc = base * v * v / zabs
    s_sc[~np.isfinite(zabs) | (zabs <= 0)] = np.nan
    return SCResult(base_mva=base, z_th_pu=z, s_sc_mva=s_sc, v_pu=v,
                    bus_row_of_label=row_of, label_of_row=label_of_row,
                    n_source=n_src, source_mva=src_mva,
                    note=("V=1.0pu 一律・線路充電/負荷無視・同期機 xd'' 典型値(機械ベース→系統ベース換算)・"
                          "IBR と合成slackは電流源にしない" if v_pu is None else
                          "V=AC解・線路充電/負荷無視・同期機 xd'' 典型値"))


def scr_hosting(s_sc_mva: np.ndarray, existing_ibr_mw: np.ndarray,
                scr_min: float = DEFAULT_SCR_MIN):
    """(P_max_scr[MW], SCR_existing) を返す。

    P_max_scr = max(S_sc/SCR_min − 既設IBR, 0)。SCR_existing = S_sc/既設IBR(既設0は inf)。
    """
    s = np.asarray(s_sc_mva, dtype=float)
    p0 = np.asarray(existing_ibr_mw, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        pmax = np.maximum(s / float(scr_min) - p0, 0.0)
        scr_now = np.where(p0 > 0, s / np.where(p0 > 0, p0, 1.0), np.inf)
    pmax[~np.isfinite(s)] = np.nan
    scr_now = np.where(np.isfinite(s), scr_now, np.nan)
    return pmax, scr_now
