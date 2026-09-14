"""モンテカルロ駆動: 地震動サンプル → 損傷 → 直後の供給支障 → 復旧時系列。"""
from __future__ import annotations
import json, os, time
from dataclasses import dataclass
import numpy as np
import pandas as pd

from .grid import GridCase
from .hazard_field import default_field, TsunamiField, jma_class
from .fragility import FragilityModel
from .cascade import CascadeModel
from .restoration import RestorationModel


@dataclass
class DamageSample:
    site_ds: np.ndarray; site_cause: np.ndarray
    line_fail: np.ndarray; line_cause: np.ndarray
    gen_ds: np.ndarray; gen_out_days: np.ndarray; gen_cause: np.ndarray
    done_site: np.ndarray; done_line: np.ndarray; done_gen: np.ndarray   # 復旧完了日(健全は 0)
    intensity: np.ndarray; pga_g: np.ndarray
    blackout_until: np.ndarray | None = None   # 母線ごとの系統崩壊からの復電日(0=崩壊なし)
    jobs: list | None = None                   # 復旧ジョブ(id, zone, kv, load_mw, duration_d) — 資源勘定用
    site_shake: np.ndarray | None = None       # 揺れでも止まったか(原因が津波に上書きされていても)。動的カスケードの停止時刻に使う
    line_shake: np.ndarray | None = None
    gen_shake: np.ndarray | None = None


class Simulator:
    def __init__(self, case: GridCase, field=None, tsunami: TsunamiField | None = None,
                 fragility: FragilityModel | None = None, restoration: RestorationModel | None = None,
                 use_tsunami: bool = True, network: str = "mesh"):
        self.case = case
        self.field = field or default_field()
        self.fm = fragility or FragilityModel()
        self.rm = restoration or RestorationModel()
        if network == "reduced":                 # ローカル系統を常時開路・主幹系統だけで潮流(radial.py)
            from .radial import ReducedCascadeModel
            self.cm = ReducedCascadeModel(case)
        else:
            self.cm = CascadeModel(case)
        self.network = network
        b = case.bus
        self.lat, self.lon = case.bus_xy()
        # サイト(変電所)索引
        first = b.groupby("site_id").head(1)
        self.site_rows = first.index.to_numpy()
        pos = {s: i for i, s in enumerate(first.site_id.values)}
        self.bus_site = np.array([pos[s] for s in b.site_id.values])
        self.site_kv = b.groupby("site_id").kv.max().loc[first.site_id.values].to_numpy(float)
        self.site_zone = first.zone.to_numpy()
        self.site_load = b.groupby("site_id").pd_mw.sum().loc[first.site_id.values].to_numpy(float)
        self.junction = b.is_junction.to_numpy()
        self.site_is_junction = self.junction[self.site_rows]
        br = case.branch
        self.bf, self.bt = br.f.to_numpy(int), br.t.to_numpy(int)
        self.br_len = br.length_km.to_numpy(float)
        self.br_par = br.parallel.to_numpy(int)
        self.br_kv = br.kv.to_numpy(float)
        self.br_zone = b.zone.to_numpy()[self.bf]
        g = case.gen
        self.gb = g.b.to_numpy(int); self.gcls = g.cls.to_numpy(); self.gp = g.p_mw.to_numpy(float)
        self.gpmax = np.where(np.isfinite(g.pmax_mw.to_numpy(float)), g.pmax_mw.to_numpy(float), 0.0)
        self.gslack = (g.kind == "slack").to_numpy()
        # 津波ランク(決定論)
        self.ts = tsunami if tsunami is not None else TsunamiField()
        if use_tsunami and self.ts.available:
            self.bus_ts = self._tsunami_rank_cached(case)
        else:
            self.bus_ts = np.zeros(case.n_bus, int)
        self.site_ts = np.zeros(len(self.site_rows), int)
        np.maximum.at(self.site_ts, self.bus_site, self.bus_ts)
        self.br_ts = np.maximum(self.bus_ts[self.bf], self.bus_ts[self.bt])
        self.gen_ts = self.bus_ts[self.gb]
        # 基底の仮想 slack 容量(フラグメント成分の残差)
        self.slack_cap = self._base_slack_capacity()
        rp = self.rm.p
        self.timeline = np.array(rp["timeline_days"], float)
        self.avail = rp["generation_availability"]
        self.reserve = float(rp.get("immediate_reserve_factor", 1.1))
        self.load0 = self.cm.load.copy()
        self.base_alive = self.cm.evaluate(np.ones(case.n_bus, bool), np.ones(len(br), bool), self._gen_cap(0.0, np.ones(len(g), bool)), run_pf=True)
        # 基底の過負荷連鎖を無効化: 基底潮流を許容(緊急定格 = max(cap*1.25, 基底|f|*1.3))
        self.cm.cap = np.maximum(self.cm.cap, self._base_flows() * 1.3 / self.cm.overload_trip)

    def _tsunami_rank_cached(self, case):
        """A40 gpkg(1GB超)の読込を避けるため、島ごとの母線→浸水深ランクを parquet にキャッシュする。"""
        from .grid import DERIVED
        cp = os.path.join(DERIVED, f"tsunami_rank_{case.island}.parquet")
        src_m = os.path.getmtime(self.ts.path) if os.path.exists(self.ts.path) else 0
        if os.path.exists(cp) and os.path.getmtime(cp) >= src_m:
            c = pd.read_parquet(cp)
            if len(c) == case.n_bus and (c.bus_id.values == case.bus.bus_id.values).all():
                return c["rank"].to_numpy(int)
        self.ts.load()
        r = self.ts.depth_rank(self.lat, self.lon)
        pd.DataFrame({"bus_id": case.bus.bus_id.values, "rank": r}).to_parquet(cp, index=False)
        return r

    def _base_flows(self):
        cm = self.cm
        gen_cap = self._gen_cap(0.0, np.ones(len(self.gb), bool))
        lab = cm._components(np.ones(cm.n, bool), np.ones(len(cm.f), bool))
        pinj = np.bincount(self.gb, weights=gen_cap, minlength=cm.n) - cm.load
        # 成分内で均す
        L = np.bincount(lab, weights=cm.load, minlength=lab.max() + 1)
        G = np.bincount(lab[self.gb], weights=gen_cap, minlength=lab.max() + 1)
        gs = np.where(G > 1e-6, L / np.maximum(G, 1e-9), 0.0)
        pinj = np.bincount(self.gb, weights=gen_cap * gs[lab[self.gb]], minlength=cm.n) - cm.load
        return np.abs(cm._dc_flows(lab, np.ones(cm.n, bool), np.ones(len(cm.f), bool), pinj, np.zeros(lab.max() + 1, bool)))

    def _base_slack_capacity(self):
        cm = self.cm
        lab = cm.base_comp
        L = np.bincount(lab, weights=cm.load, minlength=lab.max() + 1)
        G = np.bincount(lab[self.gb], weights=np.where(self.gslack, 0.0, self.gp), minlength=lab.max() + 1)
        resid = np.maximum(L - G, 0.0)
        cap = np.zeros(len(self.gb))
        for i in np.where(self.gslack)[0]:
            c = lab[self.gb[i]]
            cap[i] = resid[c]; resid[c] = 0.0   # 成分に複数 slack があれば最初の1基へ
        return cap

    def _gen_cap(self, t_days: float, gen_ok: np.ndarray) -> np.ndarray:
        if t_days < 1.0:
            cap = self.gp * self.reserve
        else:
            av = np.vectorize(lambda c: self.avail.get(c, 0.5))(self.gcls)
            cap = np.maximum(self.gpmax * av, self.gp * 0.0)
            cap = np.where(self.gcls == "solar", np.minimum(cap, self.gp * 1.0 + 1e-9) if False else cap, cap)
        cap = np.where(self.gslack, self.slack_cap, cap)
        return np.where(gen_ok, cap, 0.0)

    # ── 1サンプル ────────────────────────────────────────────────
    def damage(self, rng: np.random.Generator) -> DamageSample:
        hs = self.field.sample(self.lat, self.lon, rng=rng, randomize=True)
        pga_site = np.zeros(len(self.site_rows)); np.maximum.at(pga_site, self.bus_site, hs.pga_g)
        i_site = np.zeros(len(self.site_rows)); np.maximum.at(i_site, self.bus_site, hs.intensity)
        sds, scause = self.fm.substation_ds(self.site_kv, pga_site, self.site_ts, rng, intensity=i_site)
        sds = np.where(self.site_is_junction, 0, sds); scause = np.where(self.site_is_junction, 0, scause)
        pga_br = np.maximum(hs.pga_g[self.bf], hs.pga_g[self.bt])
        i_br = np.maximum(hs.intensity[self.bf], hs.intensity[self.bt])
        lf, lc = self.fm.line_fail(pga_br, self.br_len, self.br_par, self.br_ts, rng, intensity=i_br)
        gout, gds, gcause = self.fm.generator_state(self.gcls, hs.pga_g[self.gb], hs.intensity[self.gb], self.gen_ts, rng)
        gds = np.where(self.gslack, 0, gds); gout = np.where(self.gslack, 0.0, gout); gcause = np.where(self.gslack, 0, gcause)
        # 復旧スケジュール(変電所・線路は作業班制約、発電は所有者側で独立)
        jobs = []
        ff = int(self.fm.p["substation"]["functional_failure_ds"])
        for i in np.where(sds >= ff)[0]:
            jobs.append({"id": ("s", int(i)), "zone": self.site_zone[i], "kv": self.site_kv[i], "load_mw": self.site_load[i],
                         "duration_d": self.rm.repair_time_days("substation", int(sds[i]), int(scause[i]), rng)})
        so = self.fm.p["line"].get("short_outage", {"median_d": 2.0, "beta": 0.5})
        for k in np.where(lf)[0]:
            dur = (float(np.exp(np.log(so["median_d"]) + so["beta"] * rng.normal())) if lc[k] == 3
                   else self.rm.repair_time_days("line", 4, int(lc[k]), rng))
            jobs.append({"id": ("l", int(k)), "zone": self.br_zone[k], "kv": self.br_kv[k], "load_mw": 0.0, "duration_d": dur})
        done = self.rm.schedule(jobs, rng)
        self._last_jobs = jobs
        done_site = np.zeros(len(sds)); done_line = np.zeros(len(lf)); done_gen = np.zeros(len(gds))
        for (kind, i), t in done.items():
            (done_site if kind == "s" else done_line)[i] = t
        gff = int(self.fm.p["generator"]["functional_failure_ds"])
        done_gen = gout.copy()
        for i in np.where(gds >= gff)[0]:
            done_gen[i] = max(done_gen[i], self.rm.repair_time_days("generator", int(gds[i]), int(gcause[i]), rng))
        ssh = getattr(self.fm, "last_site_shake", None); lsh = getattr(self.fm, "last_line_shake", None); gsh = getattr(self.fm, "last_gen_shake", None)
        if ssh is not None:
            ssh = np.where(self.site_is_junction, False, ssh)
        if gsh is not None:
            gsh = np.where(self.gslack, False, gsh)
        return DamageSample(sds, scause, lf, lc, gds, gout, gcause, done_site, done_line, done_gen, hs.intensity, hs.pga_g, jobs=jobs,
                            site_shake=ssh, line_shake=lsh, gen_shake=gsh)

    def _load_factor(self, d: DamageSample, t_days: float) -> np.ndarray:
        """需要減係数(母線ごと)。demand_reduction が無効なら 1。"""
        dr = self.rm.p.get("demand_reduction") or {}
        if not dr.get("enabled"):
            return np.ones(self.case.n_bus)
        red = np.array([float(dr["by_class"].get(str(c), 0.0)) for c in jma_class(d.intensity)])
        hold, end = float(dr.get("hold_d", 14)), float(dr.get("end_d", 90))
        w = 1.0 if t_days <= hold else max(0.0, 1 - (t_days - hold) / max(end - hold, 1e-9))
        return 1.0 - red * w

    def _blackout(self, d: DamageSample, rng) -> np.ndarray:
        """直後(t=0)の供給不足率がしきい値超なら zone(または成分)全体を停電させ、復電時刻[日]を母線ごとに付ける。"""
        bo = self.rm.p.get("blackout")
        n = self.case.n_bus; until = np.zeros(n)
        if not bo:
            return until
        site_ok = ~(d.done_site > 0); bus_alive = site_ok[self.bus_site]; br_alive = ~(d.done_line > 0); gen_ok = ~(d.done_gen > 0)
        gen_cap = self._gen_cap(0.0, gen_ok)
        load = self.cm.load * self._load_factor(d, 0.0)
        if bo.get("level", "zone") == "zone":
            zones = self.case.bus.zone.to_numpy()
            gz = zones[self.gb].copy()
            ovr = bo.get("supply_zone_override_by_pref") or {}
            if ovr:
                from .aggregate import bus_prefecture
                pref = bus_prefecture(self.case)[self.gb]
                for p_, z_ in ovr.items():
                    gz[pref == p_] = z_
            hit_bus = np.zeros(n, bool)
            for z in np.unique(zones):
                mz = zones == z
                L = float(np.where(bus_alive & mz, load, 0.0).sum())
                G = float(np.where(bus_alive[self.gb] & (gz == z), gen_cap, 0.0).sum())
                imp = float(bo.get("import_cap_mw", {}).get(z, 0.0))
                deficit = 1 - min(1.0, (G + imp) / max(L, 1e-9)) if L > 0 else 0.0
                if deficit > float(bo["deficit_threshold"]) and L >= float(bo.get("min_component_load_mw", 0)):
                    hit_bus |= mz
            idx = np.where(hit_bus)[0]
        else:
            r = self.cm.evaluate(bus_alive, br_alive, gen_cap, run_pf=False)
            lab = r.comp_of_bus; nc = lab.max() + 1
            L = np.bincount(lab, weights=np.where(bus_alive, load, 0.0), minlength=nc)
            S = np.bincount(lab, weights=r.served_mw, minlength=nc)
            deficit = np.where(L > 0, 1 - S / np.maximum(L, 1e-9), 0.0)
            hit = (deficit > float(bo["deficit_threshold"])) & (L >= float(bo.get("min_component_load_mw", 0)))
            idx = np.where(hit[lab])[0]
        if len(idx):
            # サイトごとに独立な復電時刻(同一サイトの母線は同時)
            ts = np.exp(np.log(bo["restore_h_median"]) + bo["restore_h_beta"] * rng.normal(size=len(self.site_rows))) / 24.0
            until[idx] = ts[self.bus_site[idx]]
        return until

    def evaluate_timeline(self, d: DamageSample):
        """戻り: (served[T,n], phys[T,n], info)。phys=物理的に受電可能(設備健全・電源のある成分・系統崩壊なし)。
        served = phys × 需給比(供給力不足による遮断=計画停電相当を含む)。"""
        T = len(self.timeline); out = np.zeros((T, self.case.n_bus), np.float32); phys = np.zeros((T, self.case.n_bus), np.float32)
        info = []
        for ti, t in enumerate(self.timeline):
            site_ok = ~(d.done_site > t)
            bus_alive = site_ok[self.bus_site]
            br_alive = ~(d.done_line > t)
            gen_ok = ~(d.done_gen > t)
            lf = self._load_factor(d, t)
            self.cm.load = self.load0 * lf
            r = self.cm.evaluate(bus_alive, br_alive, self._gen_cap(t, gen_ok))
            self.cm.load = self.load0
            out[ti] = r.served_frac
            phys[ti] = r.connected.astype(np.float32)
            if d.blackout_until is not None:
                bo = d.blackout_until > t
                out[ti] = np.where(bo, 0.0, out[ti]); phys[ti] = np.where(bo, 0.0, phys[ti])
            info.append({"t_days": float(t), "served_mw": float((out[ti] * self.cm.load).sum()), "phys_mw": float((phys[ti] * self.cm.load).sum()),
                         "n_comp": r.n_components,
                         "load_reduced_mw": float((self.load0 * lf).sum()),
                         "blackout_mw": float(self.cm.load[(d.blackout_until > t)].sum()) if d.blackout_until is not None else 0.0,
                         "n_trip": len(r.tripped_branches), "sites_out": int((~site_ok & ~self.site_is_junction).sum()),
                         "lines_out": int((~br_alive).sum()), "gens_out": int((~gen_ok & ~self.gslack).sum()),
                         "gen_cap_mw": float(self._gen_cap(t, gen_ok)[~self.gslack].sum())})
        return out, phys, info

    def run(self, n_samples: int, seed: int = 0, progress: bool = True):
        rng = np.random.default_rng(seed)
        T = len(self.timeline); n = self.case.n_bus
        acc = np.zeros((T, n)); acc_out = np.zeros((T, n)); acc_sq = np.zeros((T, n)); acc_phys = np.zeros((T, n))
        rows = []; site_fail = np.zeros(len(self.site_rows)); line_fail = np.zeros(len(self.bf)); gen_fail = np.zeros(len(self.gb))
        int_acc = np.zeros(n)
        t0 = time.time()
        for s in range(n_samples):
            d = self.damage(rng)
            d.blackout_until = self._blackout(d, rng)
            out, phys, info = self.evaluate_timeline(d)
            acc += out; acc_sq += out ** 2; acc_out += (out < 0.5); acc_phys += phys
            site_fail += (d.done_site > 0); line_fail += d.line_fail; gen_fail += (d.done_gen > 0)
            int_acc += d.intensity
            for r in info:
                r["sample"] = s; rows.append(r)
            if progress and (s % 10 == 0 or s == n_samples - 1):
                print(f"  sample {s+1}/{n_samples}  served@0={info[0]['served_mw']:.0f}MW  @7d={[r for r in info if r['t_days']==7][0]['served_mw']:.0f}MW  {time.time()-t0:.0f}s", flush=True)
        N = n_samples
        return {"served_mean": acc / N, "served_std": np.sqrt(np.maximum(acc_sq / N - (acc / N) ** 2, 0)),
                "p_outage": acc_out / N, "phys_mean": acc_phys / N, "p_outage_phys": 1 - acc_phys / N, "site_pfail": site_fail / N, "line_pfail": line_fail / N, "gen_pfail": gen_fail / N,
                "intensity_mean": int_acc / N, "samples": pd.DataFrame(rows), "n": N}

    # ── 保存 ────────────────────────────────────────────────────
    def save(self, res: dict, out_dir: str, tag: str = ""):
        os.makedirs(out_dir, exist_ok=True)
        b = self.case.bus.copy()
        T = self.timeline
        bus = b[["bus_id", "name", "site", "kv", "zone", "lat", "lon", "pd_mw", "is_junction", "site_id"]].copy()
        bus["intensity_mean"] = res["intensity_mean"]
        bus["jma_class"] = jma_class(res["intensity_mean"])
        bus["tsunami_rank"] = self.bus_ts
        bus["site_pfail"] = res["site_pfail"][self.bus_site]
        for ti, t in enumerate(T):
            bus[f"served_t{t:g}"] = res["served_mean"][ti]
            bus[f"pout_t{t:g}"] = res["p_outage"][ti]
            bus[f"phys_t{t:g}"] = res["phys_mean"][ti]
            bus[f"pout_phys_t{t:g}"] = res["p_outage_phys"][ti]
        # 期待停電日数(台形則, 0..max)
        unserved = 1 - res["served_mean"]
        bus["expected_outage_days"] = np.trapezoid(unserved, T, axis=0)
        bus["expected_outage_days_phys"] = np.trapezoid(1 - res["phys_mean"], T, axis=0)
        bus.to_parquet(os.path.join(out_dir, f"bus_results{tag}.parquet"), index=False)
        br = self.case.branch[["branch_id", "kind", "f_bus", "t_bus", "kv", "name", "mid_lat", "mid_lon", "length_km"]].copy()
        br["pfail"] = res["line_pfail"]
        br.to_parquet(os.path.join(out_dir, f"branch_results{tag}.parquet"), index=False)
        g = self.case.gen[["gen_id", "bus_id", "name", "cls", "p_mw", "pmax_mw", "kind"]].copy()
        g["pfail"] = res["gen_pfail"]; g["lat"] = self.lat[self.gb]; g["lon"] = self.lon[self.gb]
        g.to_parquet(os.path.join(out_dir, f"gen_results{tag}.parquet"), index=False)
        res["samples"].to_csv(os.path.join(out_dir, f"sample_timeline{tag}.csv"), index=False)
        summ = res["samples"].groupby("t_days").agg(served_mw_mean=("served_mw", "mean"), phys_mw_mean=("phys_mw", "mean"), blackout_mw=("blackout_mw", "mean"),
                                                     load_reduced_mw=("load_reduced_mw", "mean"), served_mw_p10=("served_mw", lambda x: np.quantile(x, 0.1)),
                                                     served_mw_p90=("served_mw", lambda x: np.quantile(x, 0.9)), sites_out=("sites_out", "mean"),
                                                     lines_out=("lines_out", "mean"), gens_out=("gens_out", "mean"), gen_cap_mw=("gen_cap_mw", "mean")).reset_index()
        summ["load_mw"] = float(self.cm.load.sum())
        summ["served_frac"] = summ.served_mw_mean / summ.load_mw
        summ["phys_frac"] = summ.phys_mw_mean / summ.load_mw
        summ["shortage_frac"] = summ.phys_frac - summ.served_frac
        summ.to_csv(os.path.join(out_dir, f"timeline_summary{tag}.csv"), index=False)
        meta = {"island": self.case.island, "n_samples": res["n"], "timeline_days": T.tolist(), "field": getattr(self.field, "name", "gmpe"),
                "tsunami": bool(self.ts.available), "load_mw": float(self.cm.load.sum()), "generated": time.strftime("%Y-%m-%dT%H:%M:%S")}
        json.dump(meta, open(os.path.join(out_dir, f"meta{tag}.json"), "w"), ensure_ascii=False, indent=1)
        return bus, summ
