"""N-1 全枝スクリーニング — LODF（線路開放分布係数）で全枝開放を一括評価する純関数群。

直流潮流の枠内では、枝 k を開放したときの枝 j の潮流は

    f_j' = f_j + LODF[j,k] · f_k ,   LODF[j,k] = H[j,k] / (1 − H[k,k])

で閉じている（H = PTDF·Cft = 「k の from→to へ 1MW 送ったときの j の潮流」）。
全枝を開放して解き直すと枝数ぶんの潮流計算になるが、LODF なら行列 1 枚の列ごとの
積和で済む（`scripts/sensitivity/benchmark_sensitivity.py` Q4 で解き直しとの一致
max 0.0MW・west で ×17〜×2000 の速さを実測済み）。

**単回線開放（並列回線のうち 1 回線だけを落とす）** も同じ枠で閉じる。枝 k の
サセプタンスを b_k → b_k·(p−1)/p に変えるのは B 行列の rank-1 更新なので、
Sherman–Morrison から

    f_j' = f_j + H[j,k] · f_k / (p − H[k,k])            (j ≠ k)
    f_k' = f_k · (p − 1) / (p − H[k,k])                  (残回線の合計潮流)
    残回線の容量 = cap_k · (p − 1) / p

p = 1 で通常の LODF に戻る。分母が 0（H[k,k] = 1 かつ p = 1）は **橋**＝開放で系統が
分離する枝で、LODF は定義できない。この場合は「分離される側の負荷・発電」を別勘定で
記録する（`islanded_side`）。

前提と限界（正直に）:
  - 直流近似（無効電力・電圧・安定度は見ない）。合成インピーダンス（電圧階級の
    標準定数）の上の線形化なので、値は「相対的な危険度の順位付け」として使う。
  - 容量は `scripts/sensitivity/hosting_capacity.branch_capacity_mw` と同じ定義
    （線路 √3·V·I·parallel、変圧器 sn_mva·parallel）に `cap_factor` を掛けたもの。
    理論値であって公表運用容量ではない（関西比較で約 0.5、`line_capacity_calibration_*`）。
  - 対象は最大連結成分。連系線・FC・非通電の合成タイ（介入#31）は ppc 上で
    BR_STATUS=0 なので開放候補から外れる。
"""
from __future__ import annotations

import dataclasses
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components

from pandapower.pypower.idx_brch import BR_STATUS, F_BUS, PF, T_BUS
from pandapower.pypower.idx_bus import BASE_KV, PD
from pandapower.pypower.idx_gen import GEN_BUS, GEN_STATUS, PG

BRIDGE_TOL = 1e-9        # |1 − H[k,k]| < tol → 橋（benchmark_sensitivity と同じ判定）
OVER_PCT = 100.0         # 過負荷しきい値 [%]


# ── ppc からの基礎量 ──────────────────────────────────────────────────────
def branch_capacity_mw(sub, n_branch: int, cap_factor: float = 1.0) -> np.ndarray:
    """ppc 枝順の熱容量 [MW]。線路は √3·V·I·parallel、変圧器は sn_mva·parallel。

    `scripts/sensitivity/hosting_capacity.branch_capacity_mw` と同じ定義（あちらは
    スクリプト内関数で import すると matplotlib と chdir を伴うため、ここに写した。
    定義を変えるときは両方を変えること）。
    """
    cap = np.full(n_branch, np.inf)
    lk = sub._pd2ppc_lookups["branch"]
    if "line" in lk and len(sub.line):
        s, _ = lk["line"]
        kv = sub.bus.loc[sub.line["from_bus"].to_numpy(), "vn_kv"].to_numpy()
        mva = (np.sqrt(3.0) * kv * sub.line["max_i_ka"].to_numpy()
               * sub.line["parallel"].to_numpy())
        cap[s: s + len(sub.line)] = mva
    if "trafo" in lk and len(sub.trafo):
        s, _ = lk["trafo"]
        cap[s: s + len(sub.trafo)] = (sub.trafo["sn_mva"].to_numpy()
                                      * sub.trafo["parallel"].to_numpy())
    return cap * float(cap_factor)


def branch_parallel(sub, n_branch: int) -> np.ndarray:
    """ppc 枝順の回線数（parallel 列）。"""
    par = np.ones(n_branch, dtype=int)
    lk = sub._pd2ppc_lookups["branch"]
    if "line" in lk and len(sub.line):
        s, _ = lk["line"]
        par[s: s + len(sub.line)] = sub.line["parallel"].to_numpy().astype(int)
    if "trafo" in lk and len(sub.trafo):
        s, _ = lk["trafo"]
        par[s: s + len(sub.trafo)] = sub.trafo["parallel"].to_numpy().astype(int)
    return np.maximum(par, 1)


def branch_elements(sub) -> List[Tuple[Optional[str], Optional[int]]]:
    """ppc 枝行 → (テーブル名, 要素ラベル)。"""
    lookups = sub._pd2ppc_lookups["branch"]
    n = len(sub._ppc["branch"])
    out: List[Tuple[Optional[str], Optional[int]]] = [(None, None)] * n
    for tbl, (s, e) in lookups.items():
        tab = getattr(sub, tbl, None)
        if tab is None:
            continue
        for k in range(s, min(e, n)):
            out[k] = (tbl, int(tab.index[k - s]))
    return out


def branch_kv(ppc) -> np.ndarray:
    """ppc 枝の代表電圧（両端の高い方）[kV]。"""
    kvb = ppc["bus"][:, BASE_KV].real.astype(float)
    fb = ppc["branch"][:, F_BUS].real.astype(int)
    tb = ppc["branch"][:, T_BUS].real.astype(int)
    return np.maximum(kvb[fb], kvb[tb])


def bus_load_gen_mw(ppc) -> Tuple[np.ndarray, np.ndarray]:
    """バス別の負荷 [MW] と（運転中の）発電 [MW]。"""
    load = ppc["bus"][:, PD].real.astype(float).copy()
    gen = np.zeros(len(load))
    for g in ppc["gen"]:
        if float(g[GEN_STATUS].real) > 0:
            gen[int(g[GEN_BUS].real)] += float(g[PG].real)
    return load, gen


# ── 感度 ───────────────────────────────────────────────────────────────
def self_sensitivity(ptdf: np.ndarray, branch: np.ndarray) -> np.ndarray:
    """H[k,k] = PTDF[k,f_k] − PTDF[k,t_k]（自分の from→to 送電に対する自分の感度）。"""
    fb = branch[:, F_BUS].real.astype(int)
    tb = branch[:, T_BUS].real.astype(int)
    idx = np.arange(len(fb))
    return ptdf[idx, fb] - ptdf[idx, tb]


def transfer_columns(ptdf: np.ndarray, branch: np.ndarray, cols: np.ndarray) -> np.ndarray:
    """H[:, cols] = PTDF[:, f] − PTDF[:, t]（列だけ取り出す。全 nl×nl は west で 620MB）。"""
    fb = branch[cols, F_BUS].real.astype(int)
    tb = branch[cols, T_BUS].real.astype(int)
    return ptdf[:, fb] - ptdf[:, tb]


def islanding_mask(h_self: np.ndarray, parallel: np.ndarray, single_circuit: bool,
                   status: Optional[np.ndarray] = None, tol: float = BRIDGE_TOL) -> np.ndarray:
    """開放で系統が分離する枝（LODF の分母 p − H[k,k] が 0）。

    single_circuit=True なら並列回線（p ≥ 2）は 1 回線開放なので分離しない。
    非通電（status=0）の枝は感度 0 だが開放候補でもないので False。
    """
    p = parallel if single_circuit else np.ones_like(parallel)
    den = p.astype(float) - h_self
    m = np.abs(den) < tol
    if status is not None:
        m &= status > 0
    return m


def outage_factors(h_col: np.ndarray, h_kk: float, k: int, p: int,
                   single_circuit: bool) -> Tuple[np.ndarray, float]:
    """枝 k の開放に対する分布係数 g（j≠k）と、k 自身の残回線潮流の倍率。

    single_circuit かつ p ≥ 2 なら 1 回線開放、それ以外は全回線開放（p=1 扱い）。
    Returns (g, surv): f_j' = f_j + g_j·f_k、 f_k' = surv·f_k。
    """
    pe = p if (single_circuit and p >= 2) else 1
    den = pe - h_kk
    if abs(den) < BRIDGE_TOL:
        raise ValueError(f"branch {k} is a bridge (islanding); LODF undefined")
    g = h_col / den
    g = g.copy()
    g[k] = 0.0
    surv = (pe - 1) / den
    return g, surv


def post_contingency_flows(ptdf: np.ndarray, branch: np.ndarray, f0: np.ndarray,
                           k: int, parallel: Optional[np.ndarray] = None,
                           single_circuit: bool = True) -> np.ndarray:
    """枝 k 開放後の全枝潮流 [MW]（k の行は残回線の合計潮流。全回線開放なら 0）。"""
    h_col = transfer_columns(ptdf, branch, np.array([k]))[:, 0]
    h_kk = float(h_col[k])
    p = int(parallel[k]) if parallel is not None else 1
    g, surv = outage_factors(h_col, h_kk, k, p, single_circuit)
    f = f0 + g * f0[k]
    f[k] = surv * f0[k]
    return f


# ── 一括スクリーニング ───────────────────────────────────────────────────
@dataclasses.dataclass
class ScreenResult:
    """全枝開放の一括評価結果（配列は ppc 枝順・長さ nl）。"""
    n_branch: int
    single_circuit: bool
    f0: np.ndarray                 # 基準潮流 [MW]
    cap: np.ndarray                # 容量 [MW]（inf=不明）
    parallel: np.ndarray
    h_self: np.ndarray
    status: np.ndarray             # BR_STATUS
    outage_ok: np.ndarray          # 評価した枝（通電・非橋）
    islanding: np.ndarray          # 橋（分離）
    base_loading: np.ndarray       # 基準の負荷率 [%]
    base_over: np.ndarray          # 基準で既に >100% の監視枝
    post_max_loading: np.ndarray   # k 開放後の監視枝の最大負荷率 [%]（nan=未評価）
    post_worst: np.ndarray         # その枝（-1=無し）
    post_n_over: np.ndarray        # k 開放後に >100% の監視枝数
    post_n_new_over: np.ndarray    # 基準では ≤100% だったのに超えた監視枝数
    post_max_new: np.ndarray       # 基準で過負荷でない監視枝の中の開放後最大負荷率 [%]
    post_worst_new: np.ndarray     # その枝（-1=無し）
    post_max_delta: np.ndarray     # 監視枝の負荷率増分の最大 [pt]
    monitor: np.ndarray            # 監視対象の枝
    sec: float = 0.0

    def ranking(self, top: int = 20, new_only: bool = False) -> np.ndarray:
        """開放の危険度順（新規過負荷数 → 新規側の最大負荷率）に並べた枝インデックス。

        基準ケースに既に過負荷枝があると post_max_loading はそれに支配されて開放の
        優劣を映さない（east/west の実態）ので、順位は「基準で過負荷でない枝」の側で取る。
        """
        ok = self.outage_ok & np.isfinite(self.post_max_loading)
        idx = np.where(ok)[0]
        if new_only:
            idx = idx[self.post_n_new_over[idx] > 0]
        key = np.lexsort((-self.post_max_new[idx], -self.post_n_new_over[idx]))
        return idx[key][:top]


def screen(ptdf: np.ndarray, branch: np.ndarray, f0: np.ndarray, cap: np.ndarray,
           parallel: Optional[np.ndarray] = None, monitor: Optional[np.ndarray] = None,
           single_circuit: bool = True, chunk: int = 256,
           over_pct: float = OVER_PCT) -> ScreenResult:
    """全枝を順に開放したときの監視枝の負荷率を一括で出す（列チャンク・反復なし）。

    monitor: 負荷率を見る枝のマスク（None=全枝）。過負荷の「錯視」（合成定格の
    枝）を主結果から外すときは、実在線だけを monitor にして呼ぶ。
    """
    import time
    t0 = time.perf_counter()
    nl = len(f0)
    par = np.maximum(parallel.astype(int), 1) if parallel is not None else np.ones(nl, dtype=int)
    mon = np.ones(nl, dtype=bool) if monitor is None else monitor.astype(bool)
    status = branch[:, BR_STATUS].real.astype(float)
    h_self = self_sensitivity(ptdf, branch)
    isl = islanding_mask(h_self, par, single_circuit, status)
    outage_ok = (status > 0) & ~isl
    capf = np.where(np.isfinite(cap) & (cap > 0), cap, np.inf)
    base_loading = np.abs(f0) / capf * 100.0
    base_over = mon & (base_loading > over_pct)

    post_max = np.full(nl, np.nan)
    post_worst = np.full(nl, -1, dtype=int)
    post_n_over = np.zeros(nl, dtype=int)
    post_new = np.zeros(nl, dtype=int)
    post_max_new = np.full(nl, np.nan)
    post_worst_new = np.full(nl, -1, dtype=int)
    post_max_delta = np.full(nl, np.nan)
    mon_f = mon.astype(float)
    notbase_f = (mon & ~base_over).astype(float)
    base_mon = np.where(mon, base_loading, 0.0)
    pe_all = par if single_circuit else np.ones(nl, dtype=int)

    cand = np.where(outage_ok)[0]
    for c0 in range(0, len(cand), chunk):
        K = cand[c0: c0 + chunk]
        Hk = transfer_columns(ptdf, branch, K)          # nl × |K|
        pe = np.where(pe_all[K] >= 2, pe_all[K], 1).astype(float)
        den = pe - h_self[K]
        G = Hk / den[None, :]
        F = f0[:, None] + G * f0[K][None, :]
        # 開放した枝自身: 残回線の合計潮流 vs 残回線容量（全回線開放なら 0）
        surv = (pe - 1.0) / den
        F[K, np.arange(len(K))] = surv * f0[K]
        L = np.abs(F) / capf[:, None] * 100.0
        capk = capf[K] * (pe - 1.0) / pe                 # 残回線容量（p=1 → 0）
        with np.errstate(divide="ignore", invalid="ignore"):
            lk = np.where(pe > 1, np.abs(F[K, np.arange(len(K))]) / capk * 100.0, 0.0)
        L[K, np.arange(len(K))] = lk
        L = L * mon_f[:, None]                            # 監視外は 0
        post_max[K] = L.max(axis=0)
        post_worst[K] = L.argmax(axis=0)
        over = L > over_pct
        post_n_over[K] = over.sum(axis=0)
        post_new[K] = (over & ~base_over[:, None]).sum(axis=0)
        Ln = L * notbase_f[:, None]                       # 基準で過負荷でない枝だけ
        post_max_new[K] = Ln.max(axis=0)
        post_worst_new[K] = Ln.argmax(axis=0)
        post_max_delta[K] = (L - base_mon[:, None]).max(axis=0)
    post_worst[~np.isfinite(post_max) | (post_max <= 0)] = -1
    post_worst_new[~np.isfinite(post_max_new) | (post_max_new <= 0)] = -1

    return ScreenResult(
        n_branch=nl, single_circuit=single_circuit, f0=f0, cap=cap, parallel=par,
        h_self=h_self, status=status, outage_ok=outage_ok, islanding=isl,
        base_loading=base_loading, base_over=base_over,
        post_max_loading=post_max, post_worst=post_worst,
        post_n_over=post_n_over, post_n_new_over=post_new,
        post_max_new=post_max_new, post_worst_new=post_worst_new,
        post_max_delta=post_max_delta, monitor=mon,
        sec=time.perf_counter() - t0)


# ── 分離（橋）の勘定 ────────────────────────────────────────────────────
def islanded_side(branch: np.ndarray, n_bus: int, ref_bus: int, bridge: np.ndarray,
                  bus_load_mw: np.ndarray, bus_gen_mw: np.ndarray) -> Dict[int, dict]:
    """橋 k を開放したとき参照バスから切り離される側の {n_bus, load_mw, gen_mw}。

    橋を全部外した 2-辺連結成分を節にした「橋の木」を ref 側から根付け、部分木の
    合計を 1 回の走査で出す（O(n+m)）。PTDF 判定の橋が実際にはグラフを分離しない
    （数値的な擬似橋）場合は結果に含めない（呼び出し側は「不明」として扱う）。
    """
    status = branch[:, BR_STATUS].real.astype(float) > 0
    fb = branch[:, F_BUS].real.astype(int)
    tb = branch[:, T_BUS].real.astype(int)
    keep = status & ~bridge
    A = csr_matrix((np.ones(keep.sum()), (fb[keep], tb[keep])), shape=(n_bus, n_bus))
    _, comp = connected_components(A, directed=False)
    nc = int(comp.max()) + 1
    # 成分ごとの集計
    c_n = np.bincount(comp, minlength=nc).astype(float)
    c_load = np.bincount(comp, weights=bus_load_mw, minlength=nc)
    c_gen = np.bincount(comp, weights=bus_gen_mw, minlength=nc)
    # 橋の木（成分間の辺）
    adj: Dict[int, List[Tuple[int, int]]] = {}
    bidx = np.where(bridge & status)[0]
    for k in bidx:
        cf, ct = int(comp[fb[k]]), int(comp[tb[k]])
        if cf == ct:
            continue                      # 擬似橋（分離しない）
        adj.setdefault(cf, []).append((ct, int(k)))
        adj.setdefault(ct, []).append((cf, int(k)))
    root = int(comp[ref_bus])
    parent = {root: None}
    order = [root]
    via = {}                              # 子成分 → それを繋ぐ橋
    i = 0
    while i < len(order):
        u = order[i]
        i += 1
        for v, k in adj.get(u, ()):
            if v not in parent:
                parent[v] = u
                via[v] = k
                order.append(v)
    sub_n = c_n.copy(); sub_load = c_load.copy(); sub_gen = c_gen.copy()
    for v in reversed(order):
        p = parent.get(v)
        if p is not None:
            sub_n[p] += sub_n[v]; sub_load[p] += sub_load[v]; sub_gen[p] += sub_gen[v]
    out: Dict[int, dict] = {}
    for v, k in via.items():
        out[k] = {"n_bus": int(sub_n[v]), "load_mw": float(sub_load[v]),
                  "gen_mw": float(sub_gen[v])}
    return out


def ppc_flows_mw(ppc) -> np.ndarray:
    """ppc の from 側有効電力 [MW]（rundcpp 後）。"""
    return ppc["branch"][:, PF].real.astype(float)
