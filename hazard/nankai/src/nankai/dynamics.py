"""周波数の動的シミュレーション(島ごとの慣性中心周波数 + ガバナ + 負荷の周波数特性 + 周波数リレー + 緊急融通)。

系統が分離するたびに島(同期して周波数が一緒に動く塊)ごとに 1 本の周波数を持つ。

    2 E_k / f0 · dΔf_k/dt = Σ_i∈k (p0_i + ΔPgov_i) + P_aid,k − L_k (1 + D Δf_k)
    E_k = Σ_i∈k H_i S_i(運転中の同期機)
    T_i dΔPgov_i/dt = −(pmax_i / R)(Δf_k / f0) − ΔPgov_i,   −down_i ≤ ΔPgov_i ≤ up_i

リレー:
    - 発電機の周波数低下 / 上昇保護: 比 r_i と遅延 τ_i。f < r f0 が τ 続くと解列
    - UFLS: 段 s ごとに複数のリレー(遅延が 0.1〜21 秒などに散らばる)。島の f が段のしきい値を下回り続けると、
      そのリレー分の負荷(母線ごとに比率)を遮断。f が戻るとタイマーは戻る(北海道 2018 の「1 回目は時間が短く不動作」を再現)
    - 崩壊: f が f_min_ratio f0 を割る / 上回る、または同期機がほぼ無いのに負荷がある島は全停
    - 緊急融通(直流): 島の f がトリガ比を割ると ramp で容量まで受電

呼び出し側(dyn_cascade.py / hindcast)が島の割り当て・発電機の停止・母線の喪失を事象として与える。
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np


@dataclass
class Link:
    name: str
    cap_mw: float
    kind: str                  # "external"(外から一方的に受電) / "pair"(2 島のうち周波数の低い側へ)
    bus_a: np.ndarray          # external: 受電側の母線集合 / pair: A 側
    bus_b: np.ndarray | None = None
    flow: float = 0.0          # 受電側(external) or A→B を正(pair)
    active: bool = False       # トリガ周波数を一度割ると AFC として働き続ける


class FreqCore:
    def __init__(self, cfg: dict, f0: float, gen_cls, gen_bus, gen_p0, gen_pmax, bus_load, bus_red=None, bus_ts=None, rng=None):
        self.cfg = cfg; self.f0 = float(f0)
        self.rng = rng or np.random.default_rng(0)
        self.gcls = np.asarray(gen_cls); self.gbus = np.asarray(gen_bus, int)
        self.p0 = np.asarray(gen_p0, float).copy(); self.pmax = np.maximum(np.asarray(gen_pmax, float), self.p0)
        ng = len(self.p0); nb = len(bus_load)
        inert = cfg["inertia"]; gov = cfg["governor"]; prot = cfg["generator_protection"]
        H = np.array([float(inert["H_s"].get(c, 4.0)) for c in self.gcls])
        S = self.pmax / float(inert.get("power_factor", 0.9))
        self.E = H * S
        self.online = self.p0 > 1e-6
        up = np.array([float(gov["up_share"].get(c, 0.0)) for c in self.gcls])
        self.gov_up = np.minimum(np.maximum(self.pmax - self.p0, 0.0), up * self.pmax)
        self.gov_dn = np.minimum(self.p0, float(gov["down_share"]) * self.pmax)
        self.Tg = np.array([float(gov["T_s"].get(c, 6.0)) for c in self.gcls])
        self.Kg = np.where(up > 0, self.pmax / float(gov["droop"]), 0.0)
        def prot_arr(side):
            tbl = prot[side]; dflt = tbl.get("default", {"ratio": 0.0 if side == "under" else 9.9, "delay_s": 1.0})
            r = np.array([float(tbl.get(c, dflt)["ratio"]) for c in self.gcls]); d = np.array([float(tbl.get(c, dflt)["delay_s"]) for c in self.gcls])
            return r, d
        self.uf_r, self.uf_d = prot_arr("under"); self.of_r, self.of_d = prot_arr("over")
        self.pgov = np.zeros(ng); self.uf_t = np.zeros(ng); self.of_t = np.zeros(ng)
        # 負荷
        self.L0 = np.asarray(bus_load, float).copy()
        self.D = float(cfg["load"]["damping_pct_per_hz"]["value"]) / 100.0
        self.red = np.zeros(nb) if bus_red is None else np.asarray(bus_red, float)
        self.ts = np.full(nb, np.inf) if bus_ts is None else np.asarray(bus_ts, float)
        self.ramp = float(cfg["load"]["quake_demand_drop_ramp_s"]["value"])
        self.bus_on = np.ones(nb, bool); self.collapsed = np.zeros(nb, bool); self.shed = np.zeros(nb)
        # UFLS リレー(段 × 本数)
        rel = []
        for s, st in enumerate(cfg["ufls"]["stages"]):
            n = int(st["n_relays"]); lo, hi = st["delay_s"]; spacing = st.get("spacing", "linear")
            for j in range(n):
                q = (j + 0.5) / n
                d = lo * (hi / lo) ** q if spacing == "log" else lo + (hi - lo) * q
                rel.append((s, float(st["ratio"]), d, float(st["shed_frac"]) / n))
        self.rel_ratio = np.array([r[1] for r in rel]); self.rel_delay = np.array([r[2] for r in rel]); self.rel_frac = np.array([r[3] for r in rel])
        self.rel_done = np.zeros((nb, len(rel)), bool)
        col = cfg["collapse"]
        self.fmin = float(col["f_min_ratio"]) * self.f0; self.fmax = float(col["f_max_ratio"]) * self.f0; self.Emin = float(col["min_inertia_mws"])
        self.Hsys_min = float(col.get("min_system_H_s", 0.5))
        es = cfg["emergency_support"]
        self.aid_trig = float(es["trigger_ratio"]["value"]) * self.f0; self.aid_ramp = float(es["ramp_mw_s"]["value"])
        self.aid_ki = float(es.get("afc_gain_mw_per_hz_s", {"value": 200.0})["value"])
        self.links: list[Link] = []
        self.t = 0.0
        self.settle_until = np.inf          # これより後は「静穏」とみなして次の事象まで飛ぶ(呼び出し側が事象ごとに延ばす)
        self.set_islands(np.zeros(nb, int))
        self.log: list[tuple] = []

    # ── 島 ──────────────────────────────────────────────
    def set_islands(self, bus_island: np.ndarray):
        """母線の島ラベルを更新。新しい島の Δf は、負荷で重み付けした旧島の Δf を継ぐ。"""
        bus_island = np.asarray(bus_island, int)
        nk = int(bus_island.max()) + 1 if len(bus_island) else 1
        rel_t = np.zeros((nk, len(self.rel_ratio)))
        if hasattr(self, "bus_island"):
            old_df = self.df[self.bus_island]
            w = self.L0 + 1e-3
            num = np.bincount(bus_island, weights=old_df * w, minlength=nk); den = np.bincount(bus_island, weights=w, minlength=nk)
            df = num / np.maximum(den, 1e-12)
            # UFLS タイマーは、負荷の最も多くを受け継いだ旧島から引き継ぐ(分割のたびに 0 に戻すと遅延の長いリレーが永久に動かない)
            key = bus_island.astype(np.int64) * (self.nk + 1) + self.bus_island
            uk, inv = np.unique(key, return_inverse=True)
            wk = np.bincount(inv, weights=w)
            order = np.lexsort((-wk, uk // (self.nk + 1)))
            new_k = (uk[order] // (self.nk + 1)).astype(int); old_k = (uk[order] % (self.nk + 1)).astype(int)
            first = np.r_[True, new_k[1:] != new_k[:-1]]
            rel_t[new_k[first]] = self.rel_t[old_k[first]]
        else:
            df = np.zeros(nk)
        self.bus_island = bus_island; self.nk = nk
        self.gen_island = bus_island[self.gbus]
        self.df = df
        self.rel_t = rel_t

    # ── 事象 ──────────────────────────────────────────────
    def trip_gens(self, idx, why="trip"):
        idx = np.asarray(idx, int)
        idx = idx[self.online[idx]]
        if len(idx):
            self.online[idx] = False; self.pgov[idx] = 0.0
            self.log.append((self.t, why, float(self.p0[idx].sum()), len(idx)))

    def drop_buses(self, idx, why="bus"):
        idx = np.asarray(idx, int)
        idx = idx[self.bus_on[idx]]
        if len(idx):
            self.bus_on[idx] = False
            self.trip_gens(np.where(np.isin(self.gbus, idx))[0], why + "_gen")
            self.log.append((self.t, why, float(self.L0[idx].sum()), len(idx)))

    # ── 状態量 ──────────────────────────────────────────────
    def load_now(self):
        lf = 1.0 - self.red * np.clip((self.t - self.ts) / max(self.ramp, 1e-9), 0.0, 1.0)
        return self.L0 * lf * (1.0 - self.shed) * self.bus_on

    def island_sums(self):
        L = np.bincount(self.bus_island, weights=self.load_now(), minlength=self.nk)
        on = self.online.astype(float)
        Pm = np.bincount(self.gen_island, weights=(self.p0 + self.pgov) * on, minlength=self.nk)
        E = np.bincount(self.gen_island, weights=self.E * on, minlength=self.nk)
        return L, Pm, E

    def aid_by_island(self):
        a = np.zeros(self.nk)
        for lk in self.links:
            ka = np.bincount(self.bus_island[lk.bus_a], weights=self.L0[lk.bus_a] + 1e-3, minlength=self.nk).argmax()
            if lk.kind == "external":
                a[ka] += lk.flow
            else:
                kb = np.bincount(self.bus_island[lk.bus_b], weights=self.L0[lk.bus_b] + 1e-3, minlength=self.nk).argmax()
                if ka != kb:
                    a[ka] -= lk.flow; a[kb] += lk.flow
        return a

    # ── 積分 ──────────────────────────────────────────────
    def step(self, dt: float):
        f0 = self.f0
        L, Pm, E = self.island_sums()
        aid = self.aid_by_island()
        net = Pm + aid - L * (1.0 + self.D * self.df)
        live = (E >= np.maximum(1.0, self.Hsys_min * L))
        dfdt = np.where(live, f0 * net / (2.0 * np.maximum(E, 1e-9)), 0.0)
        self.df = self.df + dfdt * dt
        f = f0 + self.df
        # 同期機がほぼ無いのに負荷がある島 / 周波数が範囲外の島 → 崩壊
        dead = ((~live) & (L > 1.0)) | (f < self.fmin) | (f > self.fmax)
        # ガバナ
        dfg = self.df[self.gen_island]
        tgt = -self.Kg * dfg / f0
        self.pgov = np.clip(self.pgov + (tgt - self.pgov) * dt / self.Tg, -self.gov_dn, self.gov_up) * self.online
        # 発電機の周波数保護
        fg = f[self.gen_island]
        c_uf = self.online & (fg < self.uf_r * f0); c_of = self.online & (fg > self.of_r * f0)
        self.uf_t = np.where(c_uf, self.uf_t + dt, 0.0); self.of_t = np.where(c_of, self.of_t + dt, 0.0)
        tr = np.where((self.uf_t >= self.uf_d) & c_uf)[0]
        if len(tr):
            self.trip_gens(tr, "UF")
        tr = np.where((self.of_t >= self.of_d) & c_of)[0]
        if len(tr):
            self.trip_gens(tr, "OF")
        # UFLS
        cond = f[:, None] < self.rel_ratio[None, :] * f0
        self.rel_t = np.where(cond, self.rel_t + dt, 0.0)
        fire = np.argwhere(self.rel_t >= self.rel_delay[None, :])
        if len(fire):
            for k, r in fire:
                mb = (self.bus_island == k) & self.bus_on & ~self.rel_done[:, r]
                if mb.any():
                    sh0 = float((self.L0 * self.shed * self.bus_on).sum())
                    self.shed[mb] = np.minimum(1.0, self.shed[mb] + self.rel_frac[r]); self.rel_done[mb, r] = True
                    self.log.append((self.t, "UFLS", float((self.L0 * self.shed * self.bus_on).sum()) - sh0, int(k)))
                self.rel_t[k, r] = -1e9          # 同じ島で二度は動かない(母線側でも済み印)
        # 緊急融通(AFC): トリガ周波数を割ったら以後は周波数偏差の積分で融通量を動かす(変化率は ramp で頭打ち)
        for lk in self.links:
            ka = np.bincount(self.bus_island[lk.bus_a], weights=self.L0[lk.bus_a] + 1e-3, minlength=self.nk).argmax()
            if lk.kind == "external":
                if f[ka] < self.aid_trig:
                    lk.active = True
                if dead[ka]:
                    lk.flow = 0.0; lk.active = False
                elif lk.active:
                    rate = np.clip(self.aid_ki * (f0 - f[ka]), -self.aid_ramp, self.aid_ramp)
                    lk.flow = float(np.clip(lk.flow + rate * dt, 0.0, lk.cap_mw))
            else:
                kb = np.bincount(self.bus_island[lk.bus_b], weights=self.L0[lk.bus_b] + 1e-3, minlength=self.nk).argmax()
                if ka == kb or dead[ka] or dead[kb]:
                    lk.flow = 0.0; lk.active = False
                    continue
                if min(f[ka], f[kb]) < self.aid_trig:
                    lk.active = True
                if lk.active:
                    rate = np.clip(self.aid_ki * (f[ka] - f[kb]), -self.aid_ramp, self.aid_ramp)      # 周波数の高い側から低い側へ
                    lk.flow = float(np.clip(lk.flow + rate * dt, -lk.cap_mw, lk.cap_mw))
        if dead.any():
            for k in np.where(dead)[0]:
                mb = (self.bus_island == k) & self.bus_on
                if mb.any() or (self.online & (self.gen_island == k)).any():
                    self.log.append((self.t, "COLLAPSE", float(L[k]), int(k)))
                    self.collapsed[mb] = True
                    self.drop_buses(np.where(mb)[0], "collapse")
                    self.trip_gens(np.where(self.online & (self.gen_island == k))[0], "collapse")
                self.df[k] = 0.0
        self.t += dt
        busy = bool((np.abs(dfdt[live]) > float(self.cfg["integration"]["calm_rocof_hz_s"])).any() if live.any() else False) \
            or bool((self.uf_t > 0).any() or (self.of_t > 0).any() or (self.rel_t > 0).any()) \
            or any(lk.active and 0.0 < abs(lk.flow) < lk.cap_mw and abs(self.df[np.bincount(self.bus_island[lk.bus_a], weights=self.L0[lk.bus_a] + 1e-3, minlength=self.nk).argmax()]) > 0.02 for lk in self.links)
        gov_moving = bool((np.abs(self.pgov - np.clip(-self.Kg * self.df[self.gen_island] / f0, -self.gov_dn, self.gov_up)) > 0.5).any())
        return busy or gov_moving

    def run_until(self, t_end: float, recorder=None):
        ig = self.cfg["integration"]
        dt_a = float(ig["dt_active_s"]); dt_c = float(ig["dt_calm_s"])
        calm_steps = 0
        while self.t < t_end - 1e-9:
            if self.t >= self.settle_until:
                self.t = t_end
                if recorder is not None:
                    recorder(self)
                break
            busy = self.step(min(dt_a if calm_steps < 50 else dt_c, t_end - self.t))
            if recorder is not None:
                recorder(self)
            calm_steps = 0 if busy else calm_steps + 1
            if calm_steps > 250:                 # 十分静か → 次の事象まで飛ぶ(ガバナは収束済み)
                self.t = t_end
                if recorder is not None:
                    recorder(self)
                break

    def live_islands(self):
        L, Pm, E = self.island_sums()
        return (E >= np.maximum(1.0, self.Hsys_min * L)) & (Pm + L > 0), L, Pm, E

    def energized(self):
        """母線ごとの受電状態(0..1): 母線が生きていて、島に運転中の同期機があり、崩壊していない。UFLS 分は差し引く。"""
        live, L, Pm, E = self.live_islands()
        ok = self.bus_on & live[self.bus_island]
        return np.where(ok, 1.0 - self.shed, 0.0)
