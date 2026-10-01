"""損傷後の系統評価: 連結成分 → 需給バランス(負荷遮断) → DC潮流 → 過負荷連鎖。

入力は「生きている母線・枝・発電機」のブール配列と発電上限。出力は母線ごとの供給率。
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import splu


@dataclass
class CascadeResult:
    served_frac: np.ndarray            # 母線ごとの供給率 0..1
    served_mw: np.ndarray
    n_components: int
    tripped_branches: list = field(default_factory=list)
    comp_of_bus: np.ndarray | None = None
    deficit_mw: float = 0.0
    overload_iters: int = 0
    connected: np.ndarray | None = None      # 母線が生きていて供給源(発電/仮想電源)のある成分にいる
    supply_ratio: np.ndarray | None = None   # 成分の需給比(1=不足なし)


class CascadeModel:
    """GridCase を保持し、任意の稼働状態で評価する。"""

    def __init__(self, case, overload_trip: float = 1.25, max_iter: int = 8, min_component_for_pf: int = 20,
                 fragment_size: int = 60):
        self.case = case
        b, br, g = case.bus, case.branch, case.gen
        self.n = len(b)
        self.f = br.f.to_numpy(int); self.t = br.t.to_numpy(int)
        self.x = np.clip(br.x_pu.to_numpy(float), 1e-4, 50.0)
        self.cap = np.where(np.isfinite(br.cap_mw.to_numpy(float)) & (br.cap_mw.to_numpy(float) > 0),
                            br.cap_mw.to_numpy(float), np.inf)
        self.load = b.pd_mw.to_numpy(float)
        self.gb = g.b.to_numpy(int)
        self.gp = g.p_mw.to_numpy(float)
        self.gpmax = np.where(np.isfinite(g.pmax_mw.to_numpy(float)), g.pmax_mw.to_numpy(float), 0.0)
        self.gslack = (g.kind == "slack").to_numpy()
        self.gcls = g.cls.to_numpy()
        self.overload_trip = overload_trip
        self.max_iter = max_iter
        self.min_pf = min_component_for_pf
        self.fragment_size = fragment_size
        # 事前: 基底状態の成分(フラグメント判定用)
        base = self._components(np.ones(self.n, bool), np.ones(len(self.f), bool))
        sizes = np.bincount(base)
        self.base_comp = base
        self.base_is_fragment = sizes[base] < fragment_size
        self.base_comp_size = sizes

    def _components(self, bus_alive, br_alive):
        m = br_alive & bus_alive[self.f] & bus_alive[self.t]
        A = sp.coo_matrix((np.ones(m.sum()), (self.f[m], self.t[m])), shape=(self.n, self.n))
        _, lab = connected_components(A, directed=False)
        return lab

    def evaluate(self, bus_alive: np.ndarray, br_alive: np.ndarray, gen_cap: np.ndarray,
                 slack_alive: np.ndarray | None = None, run_pf: bool = True) -> CascadeResult:
        """gen_cap: 各発電機の利用可能出力上限[MW](停止機は0)。slack: フラグメントの仮想供給。"""
        bus_alive = bus_alive.copy(); br_alive = br_alive.copy()
        gen_cap = np.where(bus_alive[self.gb], gen_cap, 0.0)
        tripped = []
        it = 0
        while True:
            lab = self._components(bus_alive, br_alive)
            ncomp = lab.max() + 1
            load_alive = np.where(bus_alive, self.load, 0.0)
            # 成分ごとの需給
            L = np.bincount(lab, weights=load_alive, minlength=ncomp)
            G = np.bincount(lab[self.gb], weights=gen_cap, minlength=ncomp)
            # フラグメント成分の slack(仮想供給): 基底でフラグメントだった成分にある生きた slack のみ無限扱い
            if slack_alive is None:
                slack_alive = np.ones(len(self.gb), bool)
            sl = self.gslack & slack_alive & bus_alive[self.gb] & self.base_is_fragment[self.gb]
            Ginf = np.bincount(lab[self.gb], weights=sl.astype(float), minlength=ncomp) > 0
            ratio = np.where(Ginf, 1.0, np.where(L > 1e-6, np.minimum(1.0, G / np.maximum(L, 1e-9)), 1.0))
            served = load_alive * ratio[lab]
            if not run_pf:
                break
            # DC 潮流: 大きい成分のみ。注入 = 発電(比例縮小して需給一致) − 供給負荷
            gen_scale = np.where(L > 1e-6, np.minimum(1.0, (L * ratio) / np.maximum(G, 1e-9)), 0.0)
            pinj_gen = gen_cap * gen_scale[lab[self.gb]]
            pinj = np.bincount(self.gb, weights=pinj_gen, minlength=self.n) - served
            flows = self._dc_flows(lab, bus_alive, br_alive, pinj, Ginf)
            over = np.abs(flows) > self.cap * self.overload_trip
            over &= br_alive
            if not over.any() or it >= self.max_iter:
                break
            # 最も過負荷率の高い枝から順に、上位 3 本を停止(連鎖1段)
            ratio_ol = np.where(over, np.abs(flows) / self.cap, 0.0)
            k = np.argsort(-ratio_ol)[: min(3, over.sum())]
            for kk in k:
                br_alive[kk] = False
                tripped.append(int(kk))
            it += 1
        frac = np.where(self.load > 1e-9, served / np.maximum(self.load, 1e-9), np.where(bus_alive, 1.0, 0.0))
        has_supply = (G > 1e-6) | Ginf
        connected = bus_alive & has_supply[lab]
        return CascadeResult(np.clip(frac, 0, 1), served, int(ncomp), tripped, lab,
                             float(self.load.sum() - served.sum()), it, connected, ratio[lab])

    def _dc_flows(self, lab, bus_alive, br_alive, pinj, Ginf):
        flows = np.zeros(len(self.f))
        m_all = br_alive & bus_alive[self.f] & bus_alive[self.t]
        sizes = np.bincount(lab)
        for c in np.where(sizes >= self.min_pf)[0]:
            buses = np.where((lab == c) & bus_alive)[0]
            if len(buses) < 2:
                continue
            loc = -np.ones(self.n, int); loc[buses] = np.arange(len(buses))
            m = m_all & (lab[self.f] == c)
            k = np.where(m)[0]
            if len(k) == 0:
                continue
            b = 1.0 / self.x[k]
            fi, ti = loc[self.f[k]], loc[self.t[k]]
            nb = len(buses)
            A = sp.coo_matrix((np.r_[b, -b, -b, b], (np.r_[fi, fi, ti, ti], np.r_[fi, ti, fi, ti])), shape=(nb, nb)).tocsc()
            p = pinj[buses].copy()
            if Ginf[c]:
                # 仮想 slack がある成分: 不足分は slack 母線(最大注入点)が吸収
                p -= 0.0
            p -= p.mean()   # 成分内で収支ゼロ化(仮想 slack 成分の残差も含む)
            ref = int(np.argmax(np.abs(p)))
            keep = np.ones(nb, bool); keep[ref] = False
            Ar = A[keep][:, keep]
            try:
                th = np.zeros(nb)
                th[keep] = splu(Ar.tocsc() + sp.eye(nb - 1) * 1e-9).solve(p[keep])
            except Exception:
                continue
            # 注入 p は MW で与えているので θ は「MW スケール」の角度になり、枝潮流 [MW] = b·Δθ。
            # (2026-09-13 修正: ×100 を重ねて掛けていたため潮流が 100 倍になり、過負荷を誤検出していた)
            flows[k] = b * (th[fi] - th[ti])
        return flows
