#!/usr/bin/env python3
"""復旧の人員を実規模で見る: 配電の電柱被害 → 営業所の人員(被災で欠ける)→ 社内の融通 → 他社応援の到着 → 電柱の修理 → 停電軒数。

    PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/make_restoration_workforce.py --run hazard/nankai/output/run_v6 \
        --out docs/reports/nankai_hazard_2026-09-13/workforce/restoration_workforce

前の試作(make_restoration_ops.py)は送変電の修理班だけで、営業所の人(配電)・協力会社・被災会社の社内融通が入っておらず、
東京向けの応援が 5.4 班(約 43 人)と桁が小さかった(オーナー指摘)。本スクリプトは配電の層を足し、人数を実績から当てる。
パラメータと出典: config/restoration_workforce.yaml(人員被災と本店座標は restoration_ops_scenario.yaml を再利用)。
送電側の停電(設備損傷・系統分離)は動的カスケードの母線ごとの平均(--run)を使い、配電の停電と独立に重ねる:
  停電の割合 = 1 − (1 − 送電側の停電確率)(1 − 配電の停電の割合)
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import numpy as np, pandas as pd, yaml
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from nankai.hazard_field import jma_class
from nankai.aggregate import customers_per_mw

NANKAI = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.abspath(os.path.join(NANKAI, "..", ".."))
plt.rcParams["font.family"] = ["Hiragino Sans"]
JA = {"hokkaido": "北海道", "tohoku": "東北", "tokyo": "東京", "chubu": "中部", "hokuriku": "北陸", "kansai": "関西", "chugoku": "中国", "shikoku": "四国", "kyushu": "九州", "okinawa": "沖縄"}
ZCOL = {"tokyo": "#ffb347", "chubu": "#ff6b6b", "kansai": "#c79bff", "chugoku": "#9be37a", "shikoku": "#6fd3ff", "kyushu": "#ffd86b", "hokuriku": "#7ff0d2", "tohoku": "#b0b8ff", "hokkaido": "#ff9ecb"}
BG = "#081018"; PANEL = "#0f1a26"; GRID = "#1f2d3d"; TXT = "#e8e4d8"; MUTED = "#8e98ab"


def v(x):
    return x["value"] if isinstance(x, dict) and "value" in x else x


def gc_km(la1, lo1, la2, lo2):
    p1, p2 = np.radians(la1), np.radians(la2); dl = np.radians(np.asarray(lo2) - np.asarray(lo1))
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def kmeans_w(X, w, k, rng, it=30):
    k = max(1, min(k, len(X)))
    idx = rng.choice(len(X), size=k, replace=False, p=w / w.sum())
    C = X[idx].copy()
    for _ in range(it):
        d = ((X[:, None, :] - C[None, :, :]) ** 2).sum(-1); lab = d.argmin(1)
        for j in range(k):
            m = lab == j
            if m.any():
                C[j] = (X[m] * w[m, None]).sum(0) / w[m].sum()
    return lab, C


def load_buses(run):
    parts = []
    for isl in ("west", "east"):
        b = pd.read_parquet(os.path.join(run, isl, "bus_results.parquet"))
        cpm = customers_per_mw(b.groupby("zone").pd_mw.sum().to_dict())
        b["cust"] = b.pd_mw * b.zone.map(cpm).fillna(0.0)
        b["island"] = isl
        parts.append(b)
    b = pd.concat(parts, ignore_index=True)
    return b[(b.cust > 0) & ~b.is_junction].reset_index(drop=True)


SUPPORT_DB = os.environ.get("HAZARD_SUPPORT_DB") or os.path.join(NANKAI, "data", "external", "hazard_support", "hazard_support.sqlite")
DERIVED = os.path.join(NANKAI, "data", "derived")


def support_tables():
    """pws-160core で取得・DB 化した補助データ(hazard_support.sqlite)。無ければ空の dict(仮定のまま動く)。"""
    if not os.path.exists(SUPPORT_DB):
        return {}
    import sqlite3
    con = sqlite3.connect(SUPPORT_DB); out = {}
    for (name,) in con.execute("select name from sqlite_master where type='table'"):
        try:
            out[name] = pd.read_sql_query(f"select * from {name}", con)
        except Exception:
            pass
    con.close()
    return out


UTIL_ZONE = {"北海道電力ネットワーク": "hokkaido", "東北電力ネットワーク": "tohoku", "東京電力パワーグリッド": "tokyo", "中部電力パワーグリッド": "chubu", "北陸電力送配電": "hokuriku",
             "関西電力送配電": "kansai", "中国電力ネットワーク": "chugoku", "四国電力送配電": "shikoku", "九州電力送配電": "kyushu", "沖縄電力": "okinawa"}


def poles_per_customer_by_company(sup):
    """会社ごとの 配電設備 支持物数 / 契約口数 合計(補助 DB の utility_scale)。"""
    us = sup.get("utility_scale")
    if us is None or us.empty:
        return {}
    w = us.pivot_table(index="utility", columns="field", values="value", aggfunc="first")
    if not {"distribution_supports", "retail_contracts_total"} <= set(w.columns):
        return {}
    r = (w.distribution_supports / w.retail_contracts_total).dropna()
    return {UTIL_ZONE[u]: float(x) for u, x in r.items() if u in UTIL_ZONE}


def bus_municipality(b):
    """母線 → 市区町村コード。境界(N03・被害想定の 26 都府県)の中は点を含むポリゴン、範囲外の県は県コード(xx000)。キャッシュつき。"""
    cp = os.path.join(DERIVED, "bus_muni_workforce.parquet")
    key = b[["island", "bus_id"]].astype(str).agg(":".join, axis=1)
    if os.path.exists(cp):
        c = pd.read_parquet(cp)
        if len(c) == len(b) and (c.key.values == key.values).all():
            return c.muni_code.to_numpy(), c.pref.to_numpy()
    import geopandas as gpd
    from shapely import points as shp_points
    pref = pd.concat([pd.read_parquet(os.path.join(DERIVED, f"bus_pref_{isl}.parquet")).assign(island=isl) for isl in ("west", "east")])
    pref = b[["island", "bus_id"]].merge(pref, on=["island", "bus_id"], how="left").pref.fillna("不明").to_numpy()
    mu = gpd.read_file(os.path.join(DERIVED, "municipalities.gpkg"))[["muni_code", "pref_name", "geometry"]]
    pts = gpd.GeoDataFrame({"i": np.arange(len(b)), "pref": pref}, geometry=shp_points(np.c_[b.lon.values, b.lat.values]), crs="EPSG:4326")
    inside = pts[np.isin(pref, mu.pref_name.unique())]
    j = gpd.sjoin(inside, mu, how="left", predicate="within"); j = j[~j.index.duplicated()]
    miss = j.muni_code.isna() | (j.pref_name != j.pref)
    if miss.any():   # 海沿い・県境の取りこぼしは同じ県の最近傍ポリゴン
        for p, g in j[miss].groupby("pref"):
            near = gpd.sjoin_nearest(inside.loc[g.index], mu[mu.pref_name == p], how="left"); near = near[~near.index.duplicated()]
            j.loc[g.index, "muni_code"] = near.muni_code.values
    code = np.full(len(b), "", dtype=object); code[j.i.values] = j.muni_code.values
    pd.DataFrame({"key": key.values, "muni_code": code, "pref": pref}).to_parquet(cp, index=False)
    return code, pref


def wooden_era_shares(sup, cfg):
    """市区町村コード → 木造住宅の建築年次の構成 [旧(〜S37), 中(S38〜S55), 新(S56〜)] と木造の比率。
    令和5年住宅・土地統計調査 第6-3表。表に無い小さな町村は「県 − 表にある市町村」の残り、県外は県全体。"""
    h = sup["municipal_housing"]
    h = h[h.category.isin(["1_木造", "0_総数"])].pivot_table(index=["muni_code", "muni_name", "area_type_code"], columns=["category", "construction_period"], values="dwellings", aggfunc="sum").fillna(0.0)
    per = ["01_1970年以前", "02_1971～1980年", "04_1981～1990年", "05_1991～2000年", "06_2001～2010年", "07_2011～2020年", "08_2021～2023年9月"]
    W = h["1_木造"].reindex(columns=per + ["00_総数"], fill_value=0.0); A = h["0_総数"].reindex(columns=["00_総数"], fill_value=0.0)
    W = W.reset_index(); A = A.reset_index()
    W["pref_code"] = W.muni_code.str[:2]; A["pref_code"] = A.muni_code.str[:2]
    rows = {}
    for pc, g in W.groupby("pref_code"):
        pr = g[g.area_type_code == "a"]; munis = g[g.area_type_code.isin(["1", "2", "3"])]
        if len(pr):
            rest = (pr[per + ["00_総数"]].sum() - munis[per + ["00_総数"]].sum()).clip(lower=0)
            ga = A[A.pref_code == pc]
            rest_all = float((ga[ga.area_type_code == "a"]["00_総数"].sum() - ga[ga.area_type_code.isin(["1", "2", "3"])]["00_総数"].sum()))
            rows[pc + "rest"] = (rest[per].to_numpy(float), float(rest["00_総数"]), max(rest_all, 1.0))
            rows[pc + "000"] = (pr[per].sum().to_numpy(float), float(pr["00_総数"].sum()), float(ga[ga.area_type_code == "a"]["00_総数"].sum()))
    for _, r in W[W.area_type_code != "a"].iterrows():
        rows[r.muni_code] = (r[per].to_numpy(float), float(r["00_総数"]), float(A.loc[A.muni_code == r.muni_code, "00_総数"].sum()))
    split = float(v(cfg["housing_eras"]["old_share_of_1970_or_earlier"]))
    out = {}
    for k, (x, wood_total, all_total) in rows.items():
        s = x.sum()
        if s <= 0:
            continue
        old = x[0] * split; mid = x[0] * (1 - split) + x[1]; new = x[2:].sum()
        out[k] = (np.array([old, mid, new]) / s, wood_total / max(all_total, 1.0))
    return out


def wooden_collapse_rate(intensity, shares, cfg):
    """木造全壊率 = Σ_e 構成_e × Φ((I − μ_e)/σ)。μ_e は 2005 年首都直下手法の推計震度 6.4 の値(71/50/11%)から σ に応じて決める。"""
    from scipy.stats import norm
    cv = cfg["wooden_collapse_curve"]; sig = float(v(cv["sigma"])); I0 = float(cv["anchor_intensity"])
    mu = np.array([I0 - sig * norm.ppf(cv["anchor_rates"][e]) for e in ("old", "mid", "new")])
    P = norm.cdf((np.asarray(intensity)[:, None] - mu[None, :]) / sig)
    return (P * shares).sum(1)


def build(cfg, ops, buses, rng, sup=None):
    dd = cfg["distribution_damage"]; rp = cfg["repair"]; wf = cfg["workforce"]
    sup = sup or {}
    b = buses
    cls = jma_class(b.intensity_mean.values)
    rate = np.array([dd["shaking_break_rate"]["by_class"].get(str(c), 0.0) for c in cls])
    ts = b.tsunami_rank.values > 0
    ppc = poles_per_customer_by_company(sup)                       # 有価証券報告書の配電支持物数 / 契約口数(補助 DB)。無ければ一律の仮定
    b.attrs["poles_per_customer"] = {JA.get(k, k): round(x, 3) for k, x in ppc.items()}
    poles = b.cust.values * b.zone.map(ppc).fillna(v(dd["poles_per_customer"])).to_numpy(float)
    # 建物全壊による電柱折損 = 係数 × 木造建物全壊率(補助 DB の住宅統計があるときだけ。無ければ入れない)
    bc = dd["building_collapse_poles"]; collapse = np.zeros(len(b)); wshare = np.full(len(b), np.nan)
    if "municipal_housing" in sup and bc.get("enabled", True):
        code, pref = bus_municipality(b)
        eras = wooden_era_shares(sup, dd)
        hp = sup["municipal_housing"]; hp = hp[hp.area_type_code == "a"]
        p2c = dict(zip(hp.muni_name, hp.muni_code.str[:2]))
        S = np.zeros((len(b), 3)); ws = np.zeros(len(b)); src = np.empty(len(b), dtype=object)
        for i, c in enumerate(code):
            pc = p2c.get(pref[i], "??")
            for k, lab in ((c, "市区町村"), (pc + "rest" if c else "", "県の残り"), (pc + "000", "県全体")):
                if k in eras:
                    S[i], ws[i] = eras[k]; src[i] = lab; break
            else:
                S[i] = (0.2, 0.3, 0.5); ws[i] = 0.55; src[i] = "既定"
        collapse = wooden_collapse_rate(b.intensity_mean.values, S, dd)
        if v(bc["rate_basis"]) == "all_dwellings":
            collapse = collapse * ws
        wshare = ws
        b.attrs["era_source_counts"] = pd.Series(src).value_counts().to_dict()
    rate_bc = float(bc["coefficient"]) * collapse
    brk_s = np.minimum(poles * (rate + rate_bc), poles) * (~ts); brk_t = poles * v(dd["tsunami_break_rate"]) * ts
    b = b.assign(wooden_collapse=collapse, wooden_share=wshare, brk_shake_only=poles * rate * (~ts))
    lost = b.tsunami_rank.values >= v(dd["not_restorable_tsunami_rank_min"])
    cpp = v(dd["customers_per_broken_pole"])
    out_s = np.minimum(b.cust.values, brk_s * cpp) * (~lost)
    out_t = np.minimum(b.cust.values, brk_t * cpp) * (~lost)
    b = b.assign(cls=cls, poles=poles, brk_s=brk_s * (~lost), brk_t=brk_t * (~lost), out_s=out_s, out_t=out_t, lost_cust=np.where(lost, b.cust.values, 0.0))
    b.attrs["support_used"] = sorted(sup.keys())
    # 営業所: エリアごとに需要家数で重み付けした k-means
    offices = []; b["office"] = -1
    for z, g in b.groupby("zone"):
        k = int(round(g.cust.sum() / v(wf["office_customers"])))
        X = np.c_[g.lon.values * np.cos(np.radians(35)), g.lat.values]
        lab, C = kmeans_w(X, g.cust.values, max(k, 1), rng)
        base = len(offices)
        for j in range(len(C)):
            m = lab == j
            if not m.any():
                continue
            gg = g[m]; wj = gg.cust.values
            offices.append(dict(zone=z, lat=float((gg.lat * wj).sum() / wj.sum()), lon=float((gg.lon * wj).sum() / wj.sum()), cust=float(wj.sum())))
            b.loc[gg.index, "office"] = len(offices) - 1
    O = pd.DataFrame(offices)
    O["work_s"] = b.groupby("office").brk_s.sum().reindex(O.index, fill_value=0) / v(rp["poles_per_person_day"])
    O["work_t"] = b.groupby("office").brk_t.sum().reindex(O.index, fill_value=0) / v(rp["poles_per_person_day"])
    O["out_s"] = b.groupby("office").out_s.sum().reindex(O.index, fill_value=0)
    O["out_t"] = b.groupby("office").out_t.sum().reindex(O.index, fill_value=0)
    # 人員: 会社の動員可能数を需要家数比で配る
    spm = v(wf["staff_per_million_customers"])
    O["staff"] = O.cust / 1e6 * spm
    # 人員の被災(営業所の需要家で重み付けした震度別の不在率・浸水)
    per = ops["personnel"]; unav = per["unavailable_by_class"]["values"]
    u_cls = np.array([unav.get(str(c), 0.0) for c in cls])
    b["u_shake"] = u_cls; b["u_ts"] = np.where(ts, per["tsunami_unavailable"]["value"], 0.0)
    for c in ("u_shake", "u_ts"):
        O[c] = (b[c] * b.cust).groupby(b.office).sum().reindex(O.index, fill_value=0) / O.cust
    return b, O


def simulate(cfg, ops, O, scenario, T):
    """scenario: dict(send_share, internal: bool)。T: 日の配列(等間隔 dt)。戻り: 時系列の dict。"""
    rp = cfg["repair"]; wf = cfg["workforce"]; ma = cfg["mutual_aid"]; per = ops["personnel"]
    dt = T[1] - T[0]; nO = len(O)
    zones = O.zone.values
    staff = O.staff.values
    tau_s, tau_t, perm = per["tau_shake_d"]["value"], per["tau_tsunami_d"]["value"], per["permanent_share"]["value"]
    def avail(t):
        u0 = np.clip(O.u_shake.values + O.u_ts.values, 0, 0.95)
        rec_s = O.u_shake.values * ((1 - perm) * np.exp(-t / tau_s) + perm); rec_t = O.u_ts.values * ((1 - perm) * np.exp(-t / tau_t) + perm)
        return np.clip(1 - rec_s - rec_t, 0.05, 1.0)
    ramp = lambda t: np.clip((t - v(rp["patrol_d"])) / v(wf["call_up_d"]), 0, 1)
    # 会社の被害度と応援
    comp = sorted(set(zones) | set(ops["mutual_aid"]["headquarters"]["coords"].keys()))
    spm = v(wf["staff_per_million_customers"])
    cust_c = yaml.safe_load(open(os.path.join(NANKAI, "config", "customers.yaml"), encoding="utf-8"))["contracts_thousand"]
    mob = {c: cust_c.get(c, 0) / 1000.0 * spm for c in comp}
    work_c = {c: float((O.work_s + O.work_t)[O.zone == c].sum()) for c in comp}
    r = {c: (work_c[c] / max(mob[c] * 7.0, 1e-9)) for c in comp}
    receivers = [c for c in comp if r[c] >= float(v(ma["receiver_threshold_r"]))]
    # 災害時連携計画: 応援事業者は「供給区域に設備被害がない(被害予想がない)」か「復旧の目途が立っている」会社。受け手は送り手にしない
    senders = [c for c in comp if r[c] < float(v(ma.get("sender_max_r", 0.25))) and c not in receivers and c != "okinawa" and mob[c] > 0]
    hq = ops["mutual_aid"]["headquarters"]["coords"]
    convoys = []
    wsum = sum(work_c[c] for c in receivers) or 1.0
    for s in senders:
        people = scenario["send_share"] * mob[s] * (1 - r[s] / float(v(ma.get("sender_max_r", 0.25))))
        for rc in receivers:
            share = work_c[rc] / wsum
            if share <= 0:
                continue
            km = float(gc_km(hq[s][0], hq[s][1], hq[rc][0], hq[rc][1])) * float(ma["detour_factor"])
            travel = km / float(ma["convoy_speed_kmh"]) / float(ma["drive_h_per_day"])
            if s == "hokkaido":
                travel += 1.0                                   # 苫小牧→敦賀の海路(restoration_ops_scenario.yaml と同じ)
            for off, sh in zip(ma["waves"]["offsets_d"], ma["waves"]["shares"]):
                t_arr = float(ma["decision_d"]) + float(ma["mobilization_d"]) + off + travel
                convoys.append(dict(sender=s, receiver=rc, people=people * share * sh, arrive=t_arr, depart=t_arr - travel, km=km))
    CV = pd.DataFrame(convoys)
    # 受け手の会社の中で、応援を残作業比で営業所へ配る
    w_off = (O.work_s + O.work_t).values
    rem_s = O.work_s.values.copy(); rem_t = O.work_t.values.copy()
    tot_s = np.maximum(O.work_s.values, 1e-9); tot_t = np.maximum(O.work_t.values, 1e-9)
    res = {k: [] for k in ("t", "own", "internal", "aid", "rem_poles_by_zone", "dist_out_s", "dist_out_t", "aid_by_sender")}
    access = v(rp["tsunami_access_d"])
    iw = wf["internal_reallocation"]
    for t in T:
        base = staff * avail(t) * ramp(t)
        people = base.copy(); internal = np.zeros(nO)
        if scenario.get("internal", True) and t >= iw["start_d"]:
            for c in set(zones):
                m = zones == c
                cap7 = np.maximum(base[m] * 7.0, 1e-9)
                ratio = (rem_s[m] + rem_t[m]) / cap7
                light = ratio < iw["light_backlog_ratio"]; heavy = ~light & ((rem_s[m] + rem_t[m]) > 0)
                if light.any() and heavy.any():
                    give = base[m][light] * iw["share_from_light_offices"]
                    need = (rem_s[m] + rem_t[m])[heavy]
                    idx = np.where(m)[0]
                    people[idx[light]] -= give
                    internal[idx[heavy]] += give.sum() * need / need.sum()
        aid = np.zeros(nO); aid_s = {}
        if len(CV):
            arrived = CV[CV.arrive <= t]
            for rc, g in arrived.groupby("receiver"):
                m = zones == rc
                need = (rem_s + rem_t)[m]
                if need.sum() > 0:
                    aid[np.where(m)[0]] += g.people.sum() * need / need.sum()
            for s, g in arrived.groupby("sender"):
                aid_s[s] = float(g.people.sum())
        cap = (people + internal + aid) * dt                   # 人・日
        # 先に揺れの被害、浸水域は着手できるようになってから
        use_s = np.minimum(cap, rem_s); rem_s -= use_s; cap -= use_s
        if t >= access:
            use_t = np.minimum(cap, rem_t); rem_t -= use_t
        res["t"].append(t); res["own"].append(float(people.sum())); res["internal"].append(float(internal.sum())); res["aid"].append(float(aid.sum()))
        res["rem_poles_by_zone"].append({c: float((rem_s + rem_t)[zones == c].sum() * v(rp["poles_per_person_day"])) for c in set(zones)})
        res["dist_out_s"].append(rem_s / tot_s); res["dist_out_t"].append(rem_t / tot_t)
        res["aid_by_sender"].append(aid_s)
    return res, CV, r, senders, receivers, mob


def main():
    ap_ = argparse.ArgumentParser(); ap_.add_argument("--run", required=True); ap_.add_argument("--out", required=True); ap_.add_argument("--seed", type=int, default=0)
    ap_.add_argument("--no-video", action="store_true")
    ap_.add_argument("--sigma", type=float); ap_.add_argument("--basis", choices=["wooden_stock", "all_dwellings"]); ap_.add_argument("--old-split", type=float)
    ap_.add_argument("--no-collapse", action="store_true", help="建物全壊による電柱折損を入れない(前の版と同じ)"); a = ap_.parse_args()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    cfg = yaml.safe_load(open(os.path.join(NANKAI, "config", "restoration_workforce.yaml"), encoding="utf-8"))
    ops = yaml.safe_load(open(os.path.join(NANKAI, "config", "restoration_ops_scenario.yaml"), encoding="utf-8"))
    dd = cfg["distribution_damage"]
    if a.sigma is not None: dd["wooden_collapse_curve"]["sigma"]["value"] = a.sigma
    if a.basis: dd["building_collapse_poles"]["rate_basis"]["value"] = a.basis
    if a.old_split is not None: dd["housing_eras"]["old_share_of_1970_or_earlier"]["value"] = a.old_split
    if a.no_collapse: dd["building_collapse_poles"]["enabled"] = False
    rng = np.random.default_rng(a.seed)
    sup = support_tables()
    b, O = build(cfg, ops, load_buses(a.run), rng, sup)
    dt = 1.0 / 24.0; T = np.arange(0, 90 + dt / 2, dt)
    scen = {"base": dict(send_share=v(cfg["mutual_aid"]["send_share"]), internal=True), "aid30": dict(send_share=0.30, internal=True),
            "no_aid": dict(send_share=0.0, internal=True), "no_internal": dict(send_share=v(cfg["mutual_aid"]["send_share"]), internal=False)}
    R = {}
    for k, sc in scen.items():
        R[k] = simulate(cfg, ops, O, sc, T)
    res, CV, r, senders, receivers, mob = R["base"]
    # 送電側の停電(動的カスケードの母線ごとの平均)
    tl = np.array(sorted({float(c[6:]) for c in b.columns if c.startswith("phys_t")}))
    phys = np.stack([b[f"phys_t{t:g}"].values for t in tl])                  # [len(tl), nbus]
    def bulk_out(t):
        """時系列の点のあいだは線形補間(以前は階段になっていた)。"""
        k = int(np.clip(np.searchsorted(tl, t, side="right") - 1, 0, len(tl) - 1))
        if k >= len(tl) - 1:
            return 1 - phys[-1]
        f = (t - tl[k]) / (tl[k + 1] - tl[k])
        return 1 - (phys[k] * (1 - f) + phys[k + 1] * f)
    cust = b.cust.values; off = b.office.values
    def customers_out(rr, ti):
        fs = rr["dist_out_s"][ti][off]; ft = rr["dist_out_t"][ti][off]
        f_dist = np.clip((b.out_s.values * fs + b.out_t.values * ft) / np.maximum(cust, 1e-9), 0, 1)
        pb = bulk_out(T[ti])
        tot = cust * (1 - (1 - pb) * (1 - f_dist)) + b.lost_cust.values * (1 - (1 - pb))
        return float(tot.sum() + b.lost_cust.values.sum() * 0), float((cust * pb).sum()), float((cust * f_dist).sum())
    sel = [int(round(x / dt)) for x in (0.5, 1, 2, 3, 4, 7, 14, 30, 60, 90)]
    curves = {}
    for k, rr in R.items():
        curves[k] = [customers_out(rr[0], i) for i in sel]
    summary = {
        "offices": int(len(O)), "staff_total": float(O.staff.sum()),
        "staff_by_company": {JA[c]: round(float(O.staff[O.zone == c].sum())) for c in sorted(set(O.zone))},
        "broken_poles_by_company": {JA[c]: round(float((b.brk_s + b.brk_t)[b.zone == c].sum())) for c in sorted(set(b.zone))},
        "broken_poles_tsunami_share": float(b.brk_t.sum() / max((b.brk_s + b.brk_t).sum(), 1e-9)),
        "poles_per_customer": b.attrs.get("poles_per_customer", {}),
        "broken_poles_by_cause": {"揺れ": round(float(b.brk_shake_only.sum())), "建物全壊": round(float((b.brk_s - np.minimum(b.brk_shake_only, b.brk_s)).sum())), "津波": round(float(b.brk_t.sum()))},
        "collapse_settings": {"sigma": v(cfg["distribution_damage"]["wooden_collapse_curve"]["sigma"]), "basis": v(cfg["distribution_damage"]["building_collapse_poles"]["rate_basis"]),
                              "old_split": v(cfg["distribution_damage"]["housing_eras"]["old_share_of_1970_or_earlier"]), "enabled": cfg["distribution_damage"]["building_collapse_poles"].get("enabled", True),
                              "support_db": os.path.basename(SUPPORT_DB) if sup else None, "era_source_counts": b.attrs.get("era_source_counts", {})},
        "wooden_collapse_by_company": {JA[c]: round(float((b.wooden_collapse * b.cust)[b.zone == c].sum() / max(b.cust[b.zone == c].sum(), 1)), 4) for c in sorted(set(b.zone))},
        "dist_outage_customers": float((b.out_s + b.out_t).sum()), "not_restorable_customers": float(b.lost_cust.sum()),
        "own_damage_r": {JA[c]: round(float(r[c]), 2) for c in r}, "senders": [JA[s] for s in senders], "receivers": [JA[c] for c in receivers],
        "aid_people_total": float(CV.people.sum()) if len(CV) else 0.0,
        "aid_people_by_receiver": {JA[c]: round(float(g.people.sum())) for c, g in CV.groupby("receiver")} if len(CV) else {},
        "aid_people_to_tokyo_by_sender": {JA[s]: round(float(g.people.sum())) for s, g in CV[CV.receiver == "tokyo"].groupby("sender")} if len(CV) else {},
        "first_arrival_d": {JA[c]: round(float(g.arrive.min()), 2) for c, g in CV.groupby("receiver")} if len(CV) else {},
        "people_on_duty": {f"{T[i]:g}d": {"own": round(res["own"][i]), "internal": round(res["internal"][i]), "aid": round(res["aid"][i])} for i in sel},
        "customers_out_10k": {k: {f"{T[i]:g}d": [round(x / 1e4) for x in vals] for i, vals in zip(sel, cv)} for k, cv in curves.items()},
        "customers_out_note": "各時点 [合計, 送電側のみ, 配電のみ](万軒)。合計には津波で全壊相当の需要家(復旧対象外)を含む",
        "remaining_poles_by_company": {f"{T[i]:g}d": {JA[c]: round(x) for c, x in res["rem_poles_by_zone"][i].items() if x > 0} for i in sel},
    }
    json.dump(summary, open(a.out + "_summary.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1)[:4000])
    if a.no_video:
        return
    render(a, b, O, R, CV, T, dt, customers_out, summary)


def render(a, b, O, R, CV, T, dt, customers_out, summary):
    res = R["base"][0]
    times = list(np.arange(0, 1, 1 / 12)) + list(np.arange(1, 14, 0.25)) + list(np.arange(14, 90.01, 2.0))
    idx_all = [int(round(t / dt)) for t in times]
    cur = {k: np.array([customers_out(R[k][0], i)[0] for i in idx_all]) for k in R}
    parts = np.array([customers_out(R["base"][0], i) for i in idx_all])
    gj = json.load(open(os.path.join(ROOT, "data", "reference", "japan_prefectures_simplified.geojson"), encoding="utf-8"))
    kx = np.cos(np.radians(35))
    hq = yaml.safe_load(open(os.path.join(NANKAI, "config", "restoration_ops_scenario.yaml"), encoding="utf-8"))["mutual_aid"]["headquarters"]["coords"]
    tmp = tempfile.mkdtemp()
    xt = lambda t: np.log10(1 + np.asarray(t))
    ticks = [0, 1, 3, 7, 14, 30, 90]; tl = ["直後", "1日", "3日", "1週", "2週", "1月", "3月"]
    zones = sorted(set(O.zone))
    for fi, (t, i) in enumerate(zip(times, idx_all)):
        fig = plt.figure(figsize=(19.2, 10.8), dpi=100, facecolor=BG)
        ax = fig.add_axes([0.0, 0.04, 0.52, 0.86]); ax.set_facecolor(BG); ax.axis("off")
        for f in gj["features"]:
            geo = f["geometry"]; rings = geo["coordinates"][:1] if geo["type"] == "Polygon" else [p[0] for p in geo["coordinates"]]
            for rr in rings:
                rr = np.array(rr)
                if rr[:, 1].max() > 30.5 and rr[:, 0].min() < 146 and rr[:, 1].min() < 42:
                    ax.fill(rr[:, 0] * kx, rr[:, 1], color="#13202e", ec="#223246", lw=0.4, zorder=0)
        # 営業所: 大きさ = いま働く人数、色 = 残作業の割合
        rem = (res["dist_out_s"][i] * O.work_s.values + res["dist_out_t"][i] * O.work_t.values) / np.maximum(O.work_s.values + O.work_t.values, 1e-9)
        has = (O.work_s + O.work_t).values > 1
        staff_now = O.staff.values  # 目安の大きさ(自所の人員)
        ax.scatter(O.lon.values * kx, O.lat.values, s=np.sqrt(staff_now) * 6, c=np.where(has, rem, 0.0), cmap="inferno", vmin=0, vmax=1, ec="#9fb3c8", lw=0.4, zorder=3)
        # 応援の車列
        if len(CV):
            for (s, rc), g in CV.groupby(["sender", "receiver"]):
                dep = g.depart.min(); arr = g.arrive.max()
                if t < dep:
                    continue
                x0, y0 = hq[s][1] * kx, hq[s][0]; tz = O[O.zone == rc]; x1 = float((tz.lon * tz.cust).sum() / tz.cust.sum()) * kx; y1 = float((tz.lat * tz.cust).sum() / tz.cust.sum())
                prog = np.clip((t - dep) / max(arr - dep, 1e-6), 0, 1)
                ax.plot([x0, x0 + (x1 - x0) * prog], [y0, y0 + (y1 - y0) * prog], color=ZCOL.get(s, "#ccc"), lw=0.6 + 2.2 * np.sqrt(g.people.sum() / 2000), alpha=0.75, zorder=2)
        ax.set_xlim(129.0 * kx, 146.0 * kx); ax.set_ylim(30.5, 43.8); ax.set_aspect("equal")
        fig.text(0.02, 0.93, f"発災から {t:.0f} 日" if t >= 1 else f"発災から {t*24:.0f} 時間", fontsize=40, color=TXT, fontweight="bold")
        fig.text(0.02, 0.895, "営業所(円の大きさ = 人員、色 = 残っている電柱修理の割合)と他社応援の車列(線の太さ = 人数)", fontsize=14, color=MUTED, bbox=dict(fc=BG, ec="none", alpha=0.85, pad=2))
        on = res["own"][i] + res["internal"][i] + res["aid"][i]
        fig.text(0.02, 0.85, f"働いている人  {on:,.0f} 人(地元 {res['own'][i]:,.0f}・社内融通 {res['internal'][i]:,.0f}・他社応援 {res['aid'][i]:,.0f})", fontsize=17, color="#ffd696", bbox=dict(fc=BG, ec="none", alpha=0.85, pad=2))
        fig.text(0.02, 0.815, f"停電中の需要家  {cur['base'][fi]/1e4:,.0f} 万軒(送電側 {parts[fi,1]/1e4:,.0f}・配電 {parts[fi,2]/1e4:,.0f})", fontsize=17, color="#ff9b7a", bbox=dict(fc=BG, ec="none", alpha=0.85, pad=2))
        # グラフ 1: 人員の内訳
        m = np.array(idx_all) <= i
        ax1 = fig.add_axes([0.56, 0.66, 0.42, 0.26], facecolor=PANEL)
        own = np.array([res["own"][j] for j in idx_all]); inr = np.array([res["internal"][j] for j in idx_all]); aid = np.array([res["aid"][j] for j in idx_all])
        tt = xt(np.array(times))
        ax1.stackplot(tt[m], own[m], inr[m], aid[m], colors=["#4fb3a9", "#9be37a", "#ffb347"], labels=["地元の営業所", "社内の融通", "他社応援"], alpha=0.9)
        ax1.set_xlim(0, xt(90)); ax1.set_ylim(0, max(1, (own + inr + aid).max() * 1.1)); ax1.set_xticks(xt(ticks)); ax1.set_xticklabels(tl, color=MUTED)
        ax1.tick_params(colors=MUTED); [sp.set_color(GRID) for sp in ax1.spines.values()]; ax1.grid(color=GRID, lw=0.6)
        ax1.set_title("解析した 8 エリアで働いている人(配電・協力会社を含む)", color=TXT, fontsize=13, loc="left"); ax1.legend(loc="upper left", fontsize=10, frameon=False, labelcolor=TXT)
        # グラフ 2: 残っている折れた電柱(会社別)
        ax2 = fig.add_axes([0.56, 0.36, 0.42, 0.22], facecolor=PANEL)
        for z in zones:
            y = np.array([res["rem_poles_by_zone"][j].get(z, 0.0) for j in idx_all])
            if y.max() > 50:
                ax2.plot(tt[m], y[m], color=ZCOL.get(z, "#ccc"), lw=2, label=JA[z])
        ax2.set_xlim(0, xt(90)); ax2.set_xticks(xt(ticks)); ax2.set_xticklabels(tl, color=MUTED); ax2.tick_params(colors=MUTED); [sp.set_color(GRID) for sp in ax2.spines.values()]; ax2.grid(color=GRID, lw=0.6)
        ax2.set_title("残っている折れた電柱 [本](浸水域は 10 日後から着手)", color=TXT, fontsize=13, loc="left"); ax2.legend(loc="upper right", ncol=3, fontsize=10, frameon=False, labelcolor=TXT)
        # グラフ 3: 停電中の需要家(応援の条件で比べる)
        ax3 = fig.add_axes([0.56, 0.08, 0.42, 0.22], facecolor=PANEL)
        for k, col, lab in (("no_aid", "#6b7a8f", "応援なし"), ("no_internal", "#9be37a", "社内融通なし"), ("aid30", "#6fd3ff", "応援 30%"), ("base", "#ff9b7a", "既定(応援 15%)")):
            ax3.plot(tt[m], cur[k][m] / 1e4, color=col, lw=2.4 if k == "base" else 1.4, ls="-" if k == "base" else "--", label=lab)
        ax3.plot(tt[m], parts[m, 1] / 1e4, color="#ffd86b", lw=1, ls=":", label="送電側だけ")
        ax3.set_xlim(0, xt(90)); ax3.set_ylim(0, cur["no_aid"].max() / 1e4 * 1.1); ax3.set_xticks(xt(ticks)); ax3.set_xticklabels(tl, color=MUTED); ax3.tick_params(colors=MUTED); [sp.set_color(GRID) for sp in ax3.spines.values()]; ax3.grid(color=GRID, lw=0.6)
        ax3.set_title("停電中の需要家 [万軒]", color=TXT, fontsize=13, loc="left"); ax3.legend(loc="upper right", ncol=3, fontsize=10, frameon=False, labelcolor=TXT)
        bp = summary["broken_poles_by_cause"]
        fig.text(0.02, 0.78, f"折れた電柱  揺れ {bp['揺れ']:,} 本・建物の全壊に巻き込まれ {bp['建物全壊']:,} 本・津波 {bp['津波']:,} 本", fontsize=15, color="#c9d3e0", bbox=dict(fc=BG, ec="none", alpha=0.85, pad=2))
        fig.text(0.02, 0.012, "電柱折損率(揺れ・建物全壊 0.17155×木造全壊率)・1 本あたり停電軒数・作業効率 1.69 本/人日は内閣府・県の手法、木造の建築年次は令和5年住宅・土地統計調査、電柱の本数は各社の有価証券報告書、人員 390 人/百万口と応援 15% は熊本・台風・福島県沖の実績。営業所の位置と全壊率曲線の幅は仮定", fontsize=10.5, color=MUTED)
        fig.savefig(os.path.join(tmp, f"f{fi:04d}.png"), facecolor=BG); plt.close(fig)
        if abs(t - 7) < 1e-9:
            import shutil; shutil.copy(os.path.join(tmp, f"f{fi:04d}.png"), a.out + "_still.png")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "8", "-i", os.path.join(tmp, "f%04d.png"), "-vf", "format=yuv420p", "-c:v", "libx264", "-crf", "22", "-movflags", "+faststart", a.out + ".mp4"], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", a.out + ".mp4", "-vf", "fps=6,scale=960:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128:stats_mode=diff[p];[s1][p]paletteuse=dither=none:diff_mode=rectangle", "-loop", "0", a.out + ".gif"], check=True)
    print("frames", len(times), "mp4 MB", round(os.path.getsize(a.out + ".mp4") / 1e6, 1), "gif MB", round(os.path.getsize(a.out + ".gif") / 1e6, 1))


if __name__ == "__main__":
    main()
