"""脆弱性: IM(PGA[g] / 計測震度 / 浸水深ランク) → 損傷状態・停止期間のサンプリング。

パラメータは config/fragility_default.yaml(実行用スキーマ)。文献整理版 config/fragility.yaml は
値の出典台帳で、採用値は default 側に転記してある(docs/FRAGILITY_SOURCES.md)。
"""
from __future__ import annotations
import os
import numpy as np
import yaml
from scipy.stats import norm

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.abspath(os.path.join(HERE, "..", "..", "config"))


def _deep_update(a: dict, b: dict) -> dict:
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _deep_update(a[k], v)
        else:
            a[k] = v
    return a


def load_params(name: str = "fragility") -> dict:
    base = yaml.safe_load(open(os.path.join(CONFIG, f"{name}_default.yaml"), encoding="utf-8"))
    p = os.path.join(CONFIG, f"{name}_override.yaml")     # 実行用スキーマの上書き(任意)
    if os.path.exists(p):
        _deep_update(base, yaml.safe_load(open(p, encoding="utf-8")) or {})
    return base


def p_exceed(im, median: float, beta: float) -> np.ndarray:
    im = np.maximum(np.asarray(im, float), 1e-6)
    return norm.cdf(np.log(im / median) / beta)


def sample_ds(im: np.ndarray, medians, betas, rng: np.random.Generator, adj: float = 1.0) -> np.ndarray:
    """各点で DS∈{0..4} を1つサンプル(共通乱数 u で単調に)。"""
    u = rng.random(len(im))
    ds = np.zeros(len(im), int)
    for k, (m, b) in enumerate(zip(medians, betas), start=1):
        ds[u < p_exceed(im, m * adj, b)] = k
    return ds


def p_out_lognormal(im, cfg: dict, adj: float, ff: int, pod: dict) -> np.ndarray:
    """解析的な機能停止確率 = Σ_k P(DS=k)·p_out(k)。"""
    pe = [p_exceed(im, cfg["median"][k] * adj, cfg["beta"][k]) for k in range(4)] + [np.zeros(np.shape(im))]
    out = np.zeros(np.shape(im))
    for k in range(4):
        pk = pe[k] - pe[k + 1]
        out = out + pk * float(pod.get(k + 1, 1.0 if k + 1 >= ff else 0.0))
    return out


def _class_lower(label: str) -> float:
    from .hazard_field import JMA_CLASSES
    for th, lab in JMA_CLASSES:
        if lab == label:
            return th
    return -1.0


def trip_probability(icls: np.ndarray, tp: dict) -> np.ndarray:
    """震度階級ラベル配列 → 確率(p_by_class 表)。"""
    pb = tp.get("p_by_class") or {}
    return np.array([float(pb.get(str(c), 0.0)) for c in icls])


def substation_class(kv: float, classes: dict) -> str:
    for name in ("low", "medium", "high"):
        if kv <= classes[name]["kv_max"]:
            return name
    return "high"


def _rank_table(tbl: dict, ranks: np.ndarray, default=1.0) -> np.ndarray:
    return np.array([float(tbl.get(int(r), default)) for r in ranks])


class FragilityModel:
    def __init__(self, params: dict | None = None):
        self.p = params or load_params("fragility")

    # ── 変電所(サイト単位) ─────────────────────────────────────
    def substation_pout(self, kv: np.ndarray, pga_g: np.ndarray, intensity: np.ndarray | None = None) -> np.ndarray:
        """揺れによる機能停止確率(解析的)。"""
        sp = self.p["substation"]
        if sp.get("model", "hazus") == "jma_table":
            from .hazard_field import jma_class
            tbl = sp["jma_table"]
            return np.array([float(tbl.get(str(c), 0.0)) for c in jma_class(intensity)])
        cl = sp["classes"]; adj = float(sp.get("japan_adjustment", 1.0)); ff = int(sp["functional_failure_ds"]); pod = sp.get("p_out_by_ds", {})
        out = np.zeros(len(kv))
        for name in ("low", "medium", "high"):
            m = np.array([substation_class(k, cl) == name for k in kv])
            if m.any():
                out[m] = p_out_lognormal(pga_g[m], cl[name], adj, ff, pod)
        return out

    def substation_ds(self, kv, pga_g, ts_rank, rng, intensity=None):
        """戻り: (ds, cause) cause: 0=none 1=shaking 2=tsunami。ds は復旧時間の索引(ff=3 / 津波 ds_if_fail)。"""
        sp = self.p["substation"]; ff = int(sp["functional_failure_ds"]); n = len(kv)
        pout = self.substation_pout(np.asarray(kv, float), np.asarray(pga_g, float), intensity)
        out = rng.random(n) < pout
        # 揺れ停止のうち complete 相当(長期)の割合: hazus モデルなら P(DS4|out) で分ける
        ds = np.where(out, ff, 0)
        if sp.get("model", "hazus") != "jma_table":
            cl = sp["classes"]; adj = float(sp.get("japan_adjustment", 1.0))
            p4 = np.zeros(n)
            for name in ("low", "medium", "high"):
                m = np.array([substation_class(k, cl) == name for k in kv])
                if m.any():
                    p4[m] = p_exceed(np.asarray(pga_g, float)[m], cl[name]["median"][3] * adj, cl[name]["beta"][3])
            ds = np.where(out & (rng.random(n) < p4 / np.maximum(pout, 1e-9)), 4, ds)
        cause = np.where(out, 1, 0)
        self.last_site_shake = out.copy()          # 揺れでも止まったか(津波が原因に上書きされても、止まる時刻は揺れの方が早い)
        pf = _rank_table(sp["tsunami"]["pfail_by_rank"], ts_rank)
        ts_fail = rng.random(n) < pf
        ds = np.where(ts_fail, np.maximum(ds, sp["tsunami"]["ds_if_fail"]), ds)
        cause = np.where(ts_fail, 2, cause)
        return ds, cause

    # ── 線路(枝単位) ────────────────────────────────────────────
    def line_pfail(self, pga_g, length_km, parallel, ts_rank, intensity=None):
        """(p_collapse_or_tsunami, p_short) 解析的。"""
        lp = self.p["line"]; tw = lp["tower"]
        pt = p_exceed(pga_g, tw["median"], tw["beta"])
        nt = np.maximum(np.asarray(length_km, float) / tw["spacing_km"], 1.0)
        p_line = 1 - (1 - pt) ** nt
        p_line = np.where(np.asarray(parallel) >= 2, p_line * lp.get("parallel_reduction", 0.5), p_line)
        pts = _rank_table(lp["tsunami"]["pfail_by_rank"], ts_rank, 0.5)
        p_long = 1 - (1 - p_line) * (1 - pts)
        p_short = np.zeros(len(p_long))
        so = lp.get("short_outage")
        if so and intensity is not None:
            from .hazard_field import jma_class
            p_short = trip_probability(jma_class(intensity), so)
        return p_long, p_short

    def line_fail(self, pga_g, length_km, parallel, ts_rank, rng, intensity=None):
        """戻り: (fail, cause) cause 0=none 1=倒壊 2=津波 3=短期停止(がいし等)"""
        lp = self.p["line"]; tw = lp["tower"]; n = len(pga_g)
        pt = p_exceed(pga_g, tw["median"], tw["beta"])
        nt = np.maximum(np.asarray(length_km, float) / tw["spacing_km"], 1.0)
        p_line = 1 - (1 - pt) ** nt
        p_line = np.where(np.asarray(parallel) >= 2, p_line * lp.get("parallel_reduction", 0.5), p_line)
        fail = rng.random(n) < p_line
        ts_fail = rng.random(n) < _rank_table(lp["tsunami"]["pfail_by_rank"], ts_rank, 0.5)
        cause = np.where(ts_fail, 2, np.where(fail, 1, 0))
        shake = fail.copy()
        so = lp.get("short_outage")
        if so and intensity is not None:
            from .hazard_field import jma_class
            sh = (rng.random(n) < trip_probability(jma_class(intensity), so)) & (cause == 0)
            cause = np.where(sh, 3, cause); shake |= sh
        self.last_line_shake = shake
        return cause > 0, cause

    # ── 発電機 ──────────────────────────────────────────────────
    def _stop_fraction(self, icls: np.ndarray, t_days: float) -> np.ndarray:
        sc = self.p["generator"]["stop_curve"]; ax = np.array(sc["time_axis_days"], float)
        out = np.zeros(len(icls))
        for c, arr in sc["stop_fraction"].items():
            m = icls == c
            if m.any():
                out[m] = np.interp(t_days, ax, np.array(arr, float))
        return out

    def generator_pout(self, cls, pga_g, intensity, ts_rank, t_days: float) -> np.ndarray:
        """時刻 t における停止確率(解析的; 停止率曲線+scram+津波+損傷)。"""
        from .hazard_field import jma_class
        gp = self.p["generator"]; n = len(cls); icls = jma_class(intensity)
        p = np.zeros(n)
        sc_cls = set(gp["stop_curve"]["applies_to"])
        m = np.isin(cls, list(sc_cls))
        p[m] = self._stop_fraction(icls[m], t_days)
        nm = cls == "nuclear"
        nuc = gp["nuclear"]
        p[nm] = np.where((np.asarray(pga_g)[nm] >= nuc["scram_pga_g"]) & (t_days < nuc["out_days"]), 1.0, 0.0)
        for name, cfg in gp.get("classes", {}).items():
            mm = cls == name
            if mm.any():
                p[mm] = np.maximum(p[mm], p_out_lognormal(np.asarray(pga_g)[mm], cfg, float(gp.get("japan_adjustment", 1.0)),
                                                          int(gp["functional_failure_ds"]), gp.get("p_out_by_ds", {})))
        # 津波: 停止期間表(停止率曲線クラス) / 確率表(その他)
        tsd = _rank_table(gp["stop_curve"]["tsunami_stop_days_by_rank"], ts_rank, 0.0)
        p = np.where(m & (tsd > t_days), 1.0, p)
        pts = _rank_table(gp["tsunami"]["pfail_by_rank"], ts_rank)
        p = np.where(~m, 1 - (1 - p) * (1 - pts), p)
        return p

    def generator_state(self, cls, pga_g, intensity, ts_rank, rng):
        """戻り: (out_days, ds, cause) — out_days: 停止期間[日](0=停止なし; 停止率曲線/scram/津波),
        ds: 損傷モデル対象クラス(hydro 等)の損傷状態(復旧時間は restoration 側), cause: 0/1損傷/2津波/3停止曲線・scram"""
        from .hazard_field import jma_class
        gp = self.p["generator"]; n = len(cls); icls = jma_class(intensity)
        out_days = np.zeros(n); ds = np.zeros(n, int); cause = np.zeros(n, int)
        sc = gp["stop_curve"]; ax = np.array(sc["time_axis_days"], float)
        m = np.isin(cls, list(sc["applies_to"]))
        u = rng.random(n)
        for c, arr in sc["stop_fraction"].items():
            mm = m & (icls == c)
            if not mm.any():
                continue
            f = np.array(arr, float)
            # u < f(t) の間停止 → f は非増加なので f(t)=u となる t を逆補間(f が u より常に大なら最終時刻)
            fr = f[::-1]; tr = ax[::-1]
            td = np.interp(u[mm], fr, tr)           # fr 昇順・tr 降順
            td = np.where(u[mm] >= f[0], 0.0, td)
            td = np.where(u[mm] < f[-1], ax[-1], td)
            out_days[mm] = td
        cause = np.where(out_days > 0, 3, 0)
        shake = out_days > 0
        tsd = _rank_table(sc["tsunami_stop_days_by_rank"], ts_rank, 0.0)
        tsm = m & (tsd > 0)
        out_days = np.where(tsm, np.maximum(out_days, tsd), out_days); cause = np.where(tsm, 2, cause)
        nm = cls == "nuclear"; nuc = gp["nuclear"]
        scram = nm & (np.asarray(pga_g) >= nuc["scram_pga_g"])
        out_days = np.where(scram, np.maximum(out_days, nuc["out_days"]), out_days); cause = np.where(scram, 3, cause); shake |= scram
        for name, cfg in gp.get("classes", {}).items():
            mm = cls == name
            if mm.any():
                d = sample_ds(np.asarray(pga_g)[mm], cfg["median"], cfg["beta"], rng, float(gp.get("japan_adjustment", 1.0)))
                ff = int(gp["functional_failure_ds"]); pod = gp.get("p_out_by_ds", {})
                pout = np.array([float(pod.get(int(x), 1.0 if x >= ff else 0.0)) for x in d])
                o = rng.random(mm.sum()) < pout
                d = np.where(o, np.maximum(d, ff), np.minimum(d, ff - 1))
                ds[mm] = d; cause[mm] = np.where(o, 1, cause[mm]); shake[mm] |= o
        others = ~m & ~nm
        pts = _rank_table(gp["tsunami"]["pfail_by_rank"], ts_rank)
        tf = others & (rng.random(n) < pts)
        ds = np.where(tf, np.maximum(ds, gp["tsunami"]["ds_if_fail"]), ds); cause = np.where(tf, 2, cause)
        self.last_gen_shake = shake
        return out_days, ds, cause
