"""ローカル系統(154 kV 以下)の常時開路と切替送電 — 解析上の運用状態の仮定。

All-Japan-Grid の正典は開閉器をすべて閉じた網として持っている。実運用では 154 kV 以下のローカル系統は放射状で運用され、
上位系統(主幹系統)と複数の変電所でつながるループは常時開路にしている:
  - 北陸電力送配電「設備形成ルール(特高編)」: 「77kV 以下の送電系統は原則として放射状運用とする」「77kV 以下の変圧器は、原則として並列運転しない」
    「154kV 送電系統は原則として放射状運用とする」
  - 九州電力「系統運用ルール」7.2: 主幹系統(500kV、220kV 系統)は「ループ系統を基本」、ローカル系統(上記以外の 220kV 及び 110kV 以下系統)は「放射状系統を基本」
網のまま DC 潮流を解くと、ローカル系統が主幹系統の迂回路になって非物理的な潮流が出る(東で 66 kV の線に 5,000 MW)。

やること(正典データは変えない):
  1. ローカル枝 = 線路は電圧 ≤ local_max_kv、変圧器は高圧側 ≤ local_max_kv
     給電点 = 高圧側が local_max_kv を超え、低圧側が local_max_kv 以下の変圧器(同じサイトの並列変圧器は 1 つの給電点)
  2. ローカル枝だけでつながる塊(ローカル成分)ごとに、給電点が 2 つ以上あれば、各母線を電気的に最も近い給電点の区間に割り当てる
     (多始点 Dijkstra・重み = リアクタンス)。区間をまたぐローカル枝を常時開路(タイ)にする
  3. 切替送電: 区間が電源を失い(母線は健全)、タイの向こう側が受電していれば、タイを閉じる(restore_ties)
"""
from __future__ import annotations
import numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components, dijkstra


class RadialOperation:
    def __init__(self, case, local_max_kv: float = 154.0):
        b, br = case.bus, case.branch
        n = len(b); self.n = n
        f = br.f.to_numpy(int); t = br.t.to_numpy(int); self.f, self.t = f, t
        kvb = b.kv.to_numpy(float)
        # 電圧不明(0)の母線は接続する枝の最大電圧で補う
        kv_inc = np.zeros(n); np.maximum.at(kv_inc, f, br.kv.to_numpy(float)); np.maximum.at(kv_inc, t, br.kv.to_numpy(float))
        kvb = np.where(kvb > 0, kvb, kv_inc)
        kvbr = br.kv.to_numpy(float); kind = br.kind.to_numpy()
        lo_end = np.minimum(kvb[f], kvb[t])
        self.local = np.where(kind == "trafo", kvbr <= local_max_kv, kvbr <= local_max_kv) & (np.maximum(kvb[f], kvb[t]) <= local_max_kv)
        feed = (kind == "trafo") & (np.maximum(kvb[f], kvb[t]) > local_max_kv) & (lo_end <= local_max_kv)
        lv_bus = np.where(kvb[f] <= kvb[t], f, t)
        site = b.site_id.to_numpy()
        m = self.local
        A = sp.coo_matrix((np.ones(m.sum()), (f[m], t[m])), shape=(n, n))
        _, comp = connected_components(A, directed=False)
        self.comp = comp
        feed_bus = lv_bus[feed]; feed_site = site[feed_bus]
        # ローカル成分ごとの給電サイト
        import pandas as pd
        fb = pd.DataFrame({"comp": comp[feed_bus], "site": feed_site, "bus": feed_bus})
        nsite = fb.groupby("comp").site.nunique()
        multi = nsite[nsite >= 2].index.to_numpy()
        open_mask = np.zeros(len(br), bool)
        section = np.full(n, -1)
        if len(multi):
            src = fb[fb.comp.isin(multi)].drop_duplicates("bus")
            x = np.clip(br.x_pu.to_numpy(float), 1e-5, None)
            W = sp.coo_matrix((x[m], (f[m], t[m])), shape=(n, n)).tocsr()
            dist, pred, srcs = dijkstra(W, directed=False, indices=src.bus.to_numpy(), min_only=True, return_predecessors=True)
            site_of_src = dict(zip(src.bus.to_numpy(), src.site.to_numpy()))
            in_multi = np.isin(comp, multi) & np.isfinite(dist)
            section[in_multi] = [hash(site_of_src[s]) & 0x7FFFFFFF for s in srcs[in_multi]]
            tie = m & in_multi[f] & in_multi[t] & (section[f] != section[t])
            open_mask |= tie
        self.open_mask = open_mask
        self.section = section
        self.n_multi_comp = int(len(multi))
        self.feed_mask = feed

    def restore_ties(self, bus_alive: np.ndarray, br_alive: np.ndarray, energized: np.ndarray, max_rounds: int = 20):
        """電源を失った健全母線に、閉じればつながるタイがあれば閉じる。戻り値: 閉じたタイの枝番号。"""
        closed = []
        br = br_alive.copy(); en = energized.copy()
        ties = np.where(self.open_mask)[0]
        for _ in range(max_rounds):
            ok = br[ties] == False  # noqa: E712 — 開いているタイだけ
            cand = ties[ok]
            if len(cand) == 0:
                break
            a, b_ = self.f[cand], self.t[cand]
            fire = bus_alive[a] & bus_alive[b_] & (en[a] ^ en[b_])
            if not fire.any():
                break
            k = cand[fire]
            br[k] = True; closed.extend(k.tolist())
            # 閉じた先の区間を受電扱いにして次の段へ(区間内はローカル枝でつながっている)
            m = self.local & br & bus_alive[self.f] & bus_alive[self.t]
            A = sp.coo_matrix((np.ones(m.sum()), (self.f[m], self.t[m])), shape=(self.n, self.n))
            _, lab = connected_components(A, directed=False)
            live_lab = np.zeros(lab.max() + 1, bool); live_lab[lab[en & bus_alive]] = True
            en = en | (live_lab[lab] & bus_alive)
        return np.array(closed, int), br


# ── 縮約した潮流モデル(主幹系統だけで DC 潮流、ローカル系統は給電点に集約) ─────────────────────
from .cascade import CascadeModel


class ReducedCascadeModel(CascadeModel):
    """CascadeModel の置き換え。
    - つながり: ローカル系統は常時開路(RadialOperation.open_mask)。電源を失った区間はタイを閉じて切替送電(restore_ties)
    - 潮流: 主幹系統(両端 > main_min_kv 相当)の枝だけで DC 潮流。ローカル側の母線の注入は、ローカル枝でつながる塊ごとに合計し、
      その塊に接する生きた給電枝(給電用変圧器・電圧の食い違う線)の上位側母線へ等分する
    - 過負荷: 主幹系統の枝だけ(ローカル枝と給電枝の流れは 0 として返す)
    """

    def __init__(self, case, local_max_kv: float = 154.0, **kw):
        self.open_now = np.zeros(len(case.branch), bool)          # 親の __init__ が _components を呼ぶので先に用意
        super().__init__(case, **kw)
        b, br = case.bus, case.branch
        n = len(b); f, t = self.f, self.t
        kvb = b.kv.to_numpy(float); kvbr = br.kv.to_numpy(float)
        inc = np.zeros(n); np.maximum.at(inc, f, kvbr); np.maximum.at(inc, t, kvbr); kvb = np.where(kvb > 0, kvb, inc)
        hi, lo = np.maximum(kvb[f], kvb[t]), np.minimum(kvb[f], kvb[t])
        self.is_hv_bus = kvb > local_max_kv
        self.hv = (hi > local_max_kv) & (lo > local_max_kv)
        self.lv = hi <= local_max_kv
        self.feed = ~self.hv & ~self.lv                          # 給電用変圧器 + 電圧の食い違う線
        self.op = RadialOperation(case, local_max_kv)
        self.open_now = self.op.open_mask.copy()
        # 平常時: 電源を失う区間があればタイを閉じておく
        self.refresh_ties(np.ones(n, bool), np.ones(len(f), bool), None)
        self.base_comp = self._components(np.ones(n, bool), np.ones(len(f), bool))
        sizes = np.bincount(self.base_comp)
        self.base_is_fragment = sizes[self.base_comp] < self.fragment_size
        self.base_comp_size = sizes
        self.feed_flow = np.zeros(len(f))

    def _components(self, bus_alive, br_alive):
        return super()._components(bus_alive, br_alive & ~self.open_now)

    def refresh_ties(self, bus_alive, br_alive, gen_cap):
        """電源のある成分を求め、電源を失った健全区間へのタイを閉じる。閉じたタイの本数を返す。"""
        gcap = np.ones(len(self.gb)) if gen_cap is None else gen_cap
        lab = self._components(bus_alive, br_alive)
        nc = lab.max() + 1
        G = np.bincount(lab[self.gb], weights=np.where(bus_alive[self.gb], gcap, 0.0), minlength=nc)
        en = bus_alive & (G[lab] > 1e-6)
        closed, br_new = self.op.restore_ties(bus_alive, br_alive & ~self.open_now, en)
        if len(closed):
            self.open_now[closed] = False
        return len(closed)

    def evaluate(self, bus_alive, br_alive, gen_cap, slack_alive=None, run_pf=True):
        saved = self.open_now.copy()
        self.refresh_ties(bus_alive, br_alive, gen_cap)
        try:
            return super().evaluate(bus_alive, br_alive, gen_cap, slack_alive, run_pf)
        finally:
            self.open_now = saved                               # 評価ごとに平常の開閉状態へ戻す(時刻ごとに独立)

    def _dc_flows(self, lab, bus_alive, br_alive, pinj, Ginf):
        n = self.n; f, t = self.f, self.t
        alive = br_alive & ~self.open_now & bus_alive[f] & bus_alive[t]
        # ローカルの塊(ローカル枝だけでつながる)
        m = self.lv & alive
        A = sp.coo_matrix((np.ones(m.sum()), (f[m], t[m])), shape=(n, n))
        _, lvlab = connected_components(A, directed=False)
        P = np.bincount(lvlab, weights=np.where(bus_alive & ~self.is_hv_bus, pinj, 0.0), minlength=lvlab.max() + 1)
        # 塊に接する生きた給電枝
        fe = np.where(self.feed & alive)[0]
        lv_end = np.where(self.is_hv_bus[f[fe]], t[fe], f[fe]); hv_end = np.where(self.is_hv_bus[f[fe]], f[fe], t[fe])
        cnt = np.bincount(lvlab[lv_end], minlength=lvlab.max() + 1)
        share = P[lvlab[lv_end]] / np.maximum(cnt[lvlab[lv_end]], 1)
        pin_hv = np.where(self.is_hv_bus & bus_alive, pinj, 0.0) + np.bincount(hv_end, weights=share, minlength=n)
        self.feed_flow = np.zeros(len(f)); self.feed_flow[fe] = share
        # 主幹系統だけの DC 潮流(成分ごと)
        flows = np.zeros(len(f))
        mh = self.hv & alive
        Ah = sp.coo_matrix((np.ones(mh.sum()), (f[mh], t[mh])), shape=(n, n))
        _, hlab = connected_components(Ah, directed=False)
        hv_buses = np.where(self.is_hv_bus & bus_alive)[0]
        for cset in np.unique(hlab[hv_buses]):
            buses = hv_buses[hlab[hv_buses] == cset]
            if len(buses) < 2:
                continue
            loc = -np.ones(n, int); loc[buses] = np.arange(len(buses))
            k = np.where(mh & (hlab[f] == cset))[0]
            if len(k) == 0:
                continue
            bb = 1.0 / self.x[k]; fi, ti = loc[f[k]], loc[t[k]]; nb = len(buses)
            M = sp.coo_matrix((np.r_[bb, -bb, -bb, bb], (np.r_[fi, fi, ti, ti], np.r_[fi, ti, fi, ti])), shape=(nb, nb)).tocsc()
            p = pin_hv[buses].copy(); p -= p.mean()
            ref = int(np.argmax(np.abs(p))); keep = np.ones(nb, bool); keep[ref] = False
            try:
                th = np.zeros(nb)
                from scipy.sparse.linalg import splu
                th[keep] = splu(M[keep][:, keep].tocsc() + sp.eye(nb - 1) * 1e-9).solve(p[keep])
            except Exception:
                continue
            flows[k] = bb * (th[fi] - th[ti])
        return flows
