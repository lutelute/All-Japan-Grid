"""揺れの到達 → 設備の停止 → 系統分離 → 周波数 → リレー → 停電、を時刻つきで解く(1 サンプル)。

Simulator.damage() が決めた「何が壊れる / 止まるか」に、「いつ止まるか」を与えて順に系統へ加える。
  - 変電所・線路の損傷(揺れ): S 波の到達時刻 + 保護の遮断時間
  - 発電機: 振動検知などの停止(停止率曲線)・原子力の scram・水力の損傷は S 波到達 + 遅れ
  - 津波が原因の停止: 津波の到達時刻(√(gh) 走時 + 陸上の進入)
  - 需要減(震度別): S 波到達から ramp
事象のたびに連結成分(独立系統 = 島)を数え直し、島ごとの周波数を dynamics.FreqCore で解く。
決まった時刻に DC 潮流で過負荷を見て、過負荷リレー(緊急定格の 1.25 倍)で上位 3 本ずつ切る(分離の連鎖)。
"""
from __future__ import annotations
import os
import numpy as np
import pandas as pd

from .dynamics import FreqCore, Link
from .hazard_field import jma_class

WEST_ZONES = {"chubu", "hokuriku", "kansai", "chugoku", "shikoku", "kyushu"}


class DynCascade:
    def __init__(self, sim, cfg: dict, t_s_bus: np.ndarray, t_tsu_bus: np.ndarray):
        self.sim = sim; self.cfg = cfg; cm = sim.cm; case = sim.case
        self.case = case; self.cm = cm
        self.zone = case.bus.zone.to_numpy()
        self.f0 = 60.0 if set(np.unique(self.zone)) <= WEST_ZONES else 50.0
        self.t_s = np.asarray(t_s_bus, float); self.t_tsu = np.asarray(t_tsu_bus, float)
        # 平常時: 基底の成分ごとに発電を負荷に合わせる(フラグメントの仮想電源 slack を含む)
        g = case.gen
        self.gcls = np.where(sim.gslack, "slack", sim.gcls)
        p_nom = np.where(sim.gslack, sim.slack_cap, sim.gp)
        lab0 = cm.base_comp; nc = lab0.max() + 1
        L = np.bincount(lab0, weights=cm.load, minlength=nc)
        G = np.bincount(lab0[sim.gb], weights=p_nom, minlength=nc)
        scale = np.where(G > 1e-6, L / np.maximum(G, 1e-9), 0.0)
        self.p0 = p_nom * scale[lab0[sim.gb]]
        self.pmax = np.where(sim.gslack, self.p0 * 1.1, np.maximum(sim.gpmax, self.p0))
        # 平常時に電源のある成分にいる母線だけを対象にする。sim.base_alive は平常時でも過負荷で線路を切った後の状態なので使わない
        # (使うと発電の配分に含めた負荷が対象外になり、島に偽の余剰が出て潮流がずれる — 東で 1,209 MW・過負荷 40 本の偽分離を起こした)
        self.base_on = (G > 1e-6)[lab0]
        Lb = np.bincount(lab0, weights=cm.load, minlength=nc)
        self.trunk_bus = (Lb[lab0] >= 100.0) & self.base_on          # 平常時の幹線系統(100 MW 以上の成分)に属する母線
        ff_site = int(sim.fm.p["substation"]["functional_failure_ds"])
        self.ff_site = ff_site
        rel = cfg["relays"]
        self.clear = float(rel["protection_clear_s"]["value"]); self.gtrip = float(rel["gen_seismic_trip_s"]["value"])
        self.scram = float(rel["nuclear_scram_s"]["value"]); self.ol_rounds = int(rel["max_overload_rounds"])
        self.ol_enabled = bool(rel.get("overload_enabled", True))
        self.ol_mask = case.branch.kv.to_numpy(float) >= float(rel.get("overload_min_kv", 0.0))      # 過負荷リレーを見る枝(電圧の下限)
        self.rec_t = np.array(cfg["record_times_s"], float)

    # ── 事象の列 ──────────────────────────────────────────
    def events(self, d):
        sim = self.sim; ev = []
        site_bus = sim.site_rows                          # サイトの代表母線
        for i in np.where(d.site_ds >= self.ff_site)[0]:
            buses = np.where(sim.bus_site == i)[0]
            if d.site_cause[i] == 2:
                t = float(self.t_tsu[site_bus[i]])
            else:
                t = float(self.t_s[site_bus[i]]) + self.clear
            ev.append((t, "site", buses))
        for k in np.where(d.line_fail)[0]:
            f, t_ = sim.bf[k], sim.bt[k]
            if d.line_cause[k] == 2:
                t = float(min(self.t_tsu[f], self.t_tsu[t_]))
            else:
                t = float(max(self.t_s[f], self.t_s[t_])) + self.clear
            ev.append((t, "line", np.array([k])))
        out0 = np.where(d.done_gen > 0)[0]
        for i in out0:
            b = sim.gb[i]
            if sim.gslack[i]:
                continue
            if d.gen_cause[i] == 2:
                t = float(self.t_tsu[b])
            elif sim.gcls[i] == "nuclear":
                t = float(self.t_s[b]) + self.scram
            elif d.gen_cause[i] == 1:
                t = float(self.t_s[b]) + self.clear
            else:
                t = float(self.t_s[b]) + self.gtrip
            ev.append((t, "gen", np.array([i])))
        ev.sort(key=lambda e: e[0])
        return ev

    # ── 1 サンプル ─────────────────────────────────────────
    def run(self, d, rng, trace: bool = False):
        cm = self.cm; sim = self.sim; cfg = self.cfg
        n = self.case.n_bus
        red = 1.0 - sim._load_factor(d, 0.0)
        core = FreqCore(cfg, self.f0, self.gcls, sim.gb, self.p0, self.pmax, cm.load, bus_red=red, bus_ts=self.t_s, rng=rng)
        core.cfg = dict(cfg); core.cfg["integration"] = dict(cfg["integration"], dt_active_s=float(cfg["integration"].get("dt_active_bus_s", 0.05)))
        # 平常時に電源の無い母線は対象外(地震と無関係)
        core.bus_on &= self.base_on
        self._links(core)
        bus_alive = self.base_on.copy(); br_alive = np.ones(len(cm.f), bool)
        lab = cm._components(bus_alive, br_alive); core.set_islands(lab)
        core.settle_until = 0.0
        settle_s = float(cfg["integration"].get("settle_after_event_s", 120.0))
        dt_slow = float(cfg["integration"].get("dt_slow_s", 0.2)); settle_slow = float(cfg["integration"].get("settle_slow_s", 60.0))
        ev = self.events(d)
        # 事象をまとめる刻み: 揺れの間 0.5 秒、以後 30 秒
        bins = []
        for t, kind, idx in ev:
            key = round(t / 0.5) * 0.5 if t < 600 else round(t / 30.0) * 30.0
            if bins and abs(bins[-1][0] - key) < 1e-9:
                bins[-1][1].append((kind, idx))
            else:
                bins.append((key, [(kind, idx)]))
        ol_times = [10, 30, 60, 120, 240, 360, 600, 1800, 3600, 7200]
        schedule = sorted([(t, "events", items) for t, items in bins] + [(float(t), "overload", None) for t in ol_times], key=lambda x: (x[0], x[1] != "events"))
        rec = {"t": [], "energized_mw": [], "n_islands": [], "n_islands_100mw": [], "n_islands_1gw": [], "shed_mw": [], "collapsed_mw": [], "isolated_mw": [], "site_out_mw": [], "f_min": [], "f_max": []}
        bus_state = np.zeros((len(self.rec_t), n), np.float32)
        tr = {"t": [], "zone_f": [], "n_islands": [], "n_100mw": [], "energized": [], "island": [], "collapsed": [], "isolated": [], "site_out": [],
              "mw": []} if trace else None
        zones = np.unique(self.zone)
        site_out = np.zeros(n, bool); isolated = np.zeros(n, bool)
        ri = 0
        load0 = cm.load

        def record_until(t_stop):
            nonlocal ri
            while ri < len(self.rec_t) and self.rec_t[ri] <= t_stop + 1e-9:
                core.run_until(self.rec_t[ri], recorder)
                snap(self.rec_t[ri]); ri += 1
            core.run_until(t_stop, recorder)

        last_tr = [-1e9]

        def recorder(c):
            if trace and (c.t - last_tr[0] >= (0.5 if c.t < 400 else 60.0)):
                last_tr[0] = c.t
                tr["t"].append(c.t)
                zf = {}
                Lb = c.load_now()
                for z in zones:
                    m = self.zone == z
                    if (Lb[m] > 0).any():
                        k = np.bincount(c.bus_island[m], weights=Lb[m] + 1e-6, minlength=c.nk).argmax()
                        zf[z] = float(self.f0 + c.df[k])
                    else:
                        zf[z] = np.nan
                tr["zone_f"].append(zf)
                isl = self._island_stats(c)
                tr["n_islands"].append(isl[0]); tr["n_100mw"].append(isl[1])
                e = c.energized()
                tr["energized"].append(e.astype(np.float16)); tr["island"].append(c.bus_island.astype(np.int32).copy())
                tr["collapsed"].append(c.collapsed.copy()); tr["isolated"].append((isolated & ~c.collapsed & ~site_out).copy()); tr["site_out"].append(site_out.copy())
                tr["mw"].append({"energized": float((e * load0).sum()), "shed": float((load0 * c.shed * c.bus_on).sum()), "collapsed": float(load0[c.collapsed].sum()),
                                 "isolated": float(load0[isolated & ~c.collapsed & ~site_out].sum()), "site_out": float(load0[site_out].sum())})

        def snap(t):
            e = core.energized()
            bus_state[ri] = e
            isl = self._island_stats(core)
            Lnow = load0
            rec["t"].append(t); rec["energized_mw"].append(float((e * Lnow).sum()))
            rec["n_islands"].append(isl[0]); rec["n_islands_100mw"].append(isl[1]); rec["n_islands_1gw"].append(isl[2])
            rec["shed_mw"].append(float((load0 * core.shed * core.bus_on).sum()))
            rec["collapsed_mw"].append(float(load0[core.collapsed].sum()))
            rec["isolated_mw"].append(float(load0[isolated & ~core.collapsed & ~site_out].sum()))
            rec["site_out_mw"].append(float(load0[site_out].sum()))
            fk = self.f0 + core.df
            live, L, Pm, E = core.live_islands()
            live = live & (L >= 100.0)                      # 周波数の幅は 100 MW 以上の島で見る
            rec["f_min"].append(float(fk[live].min()) if live.any() else np.nan)
            rec["f_max"].append(float(fk[live].max()) if live.any() else np.nan)

        ol_round = 0
        for t, what, items in schedule:
            if t > float(cfg["integration"]["t_end_s"]):
                break
            if t >= 600.0 and core.cfg["integration"]["dt_active_s"] != dt_slow:
                core.cfg["integration"] = dict(core.cfg["integration"], dt_active_s=dt_slow)   # 津波の段階はゆっくりした事象なので刻みを粗く
            record_until(t)
            core.settle_until = max(core.settle_until, t + (settle_s if t < 600.0 else settle_slow))
            changed = False
            if what == "events":
                for kind, idx in items:
                    if kind == "site":
                        idx = idx[bus_alive[idx]]
                        if len(idx):
                            bus_alive[idx] = False; site_out[idx] = True; core.drop_buses(idx, "site"); changed = True
                    elif kind == "line":
                        if br_alive[idx[0]]:
                            br_alive[idx[0]] = False; changed = True
                    else:
                        core.trip_gens(idx, "gen_quake"); changed = changed or False
            else:
                # 過負荷リレー: 島ごとに DC 潮流(発電の不足・余剰は慣性比で配る準定常)→ 緊急定格超過の上位 3 本を切る。解消するまで繰り返す
                for _ in range(self.ol_rounds if self.ol_enabled else 0):
                    flows = self._flows(core, bus_alive, br_alive)
                    over = br_alive & self.ol_mask & (np.abs(flows) > cm.cap * cm.overload_trip)
                    if not over.any():
                        break
                    ratio = np.where(over, np.abs(flows) / cm.cap, 0.0)
                    for kk in np.argsort(-ratio)[: min(3, int(over.sum()))]:
                        br_alive[kk] = False
                    core.log.append((core.t, "overload_trip", float(over.sum()), 0))
                    lab_new = cm._components(bus_alive & core.bus_on, br_alive)
                    self._apply_islands(core, lab_new, isolated)
                    ol_round += 1
                continue
            if changed:
                lab_new = cm._components(bus_alive & core.bus_on, br_alive)
                self._apply_islands(core, lab_new, isolated)
        record_until(float(cfg["integration"]["t_end_s"]))
        while ri < len(self.rec_t):
            snap(self.rec_t[ri]); ri += 1
        out = {k: np.array(v) for k, v in rec.items()}
        out["bus_state"] = bus_state
        out["collapsed_bus"] = core.collapsed.copy()
        out["site_out_bus"] = site_out; out["isolated_bus"] = isolated & ~core.collapsed & ~site_out
        out["log"] = core.log
        if trace:
            out["trace"] = tr
        return out

    # ── 補助 ────────────────────────────────────────────
    def _links(self, core):
        es = self.cfg["emergency_support"]["links"]
        if self.f0 == 50.0:
            lk = es["hokuhon_to_tohoku"]; m = np.where(self.zone == lk["to_zone"])[0]
            if len(m):
                core.links.append(Link("北本(北海道→東北)", float(lk["cap_mw"]), "external", m))
        else:
            lk = es["fc_east_west"]; m = np.where(self.zone == "chubu")[0]
            if len(m):
                core.links.append(Link("周波数変換所(東→中部)", float(lk["cap_mw"]), "external", m))

    def _apply_islands(self, core, lab, isolated):
        core.set_islands(lab)
        live, L, Pm, E = core.live_islands()
        dead = (~live) & (L > 1.0)
        if dead.any():
            mb = dead[core.bus_island] & core.bus_on
            isolated |= mb
            core.drop_buses(np.where(mb)[0], "isolated")

    def _island_stats(self, core):
        """平常時の幹線系統(負荷 100 MW 以上の基底成分)から分かれて受電を続けている島の数:
        (負荷 10 MW 以上, 100 MW 以上, 1,000 MW 以上)。平常時からある小さな断片(仮想電源つき)は数えない。"""
        live, L, Pm, E = core.live_islands()
        trunk_bus = self.trunk_bus & core.bus_on
        has_trunk = np.bincount(core.bus_island[trunk_bus], minlength=core.nk) > 0
        ok = live & has_trunk
        return int((ok & (L >= 10.0)).sum()), int((ok & (L >= 100.0)).sum()), int((ok & (L >= 1000.0)).sum())

    def _flows(self, core, bus_alive, br_alive):
        cm = self.cm
        on = core.online
        pg = (core.p0 + core.pgov) * on
        L, Pm, E = core.island_sums()
        aid = core.aid_by_island()
        imb = L * (1 + core.D * core.df) - Pm - aid                 # 不足(+)
        share = np.where(E[core.gen_island] > 0, core.E * on / np.maximum(E[core.gen_island], 1e-9), 0.0)
        pg = pg + imb[core.gen_island] * share
        pinj = np.bincount(core.gbus, weights=pg, minlength=cm.n) - core.load_now()
        lab = core.bus_island
        return cm._dc_flows(lab, bus_alive & core.bus_on, br_alive, pinj, np.zeros(lab.max() + 1, bool))
