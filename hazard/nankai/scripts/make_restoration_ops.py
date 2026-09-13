#!/usr/bin/env python3
"""復旧オペレーション・シナリオ(v0 試作): 班の配置 → 班と資機材の被災 → 他社応援の到着 → 待ち行列で修理 → 停電の回復。

    PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/make_restoration_ops.py docs/reports/nankai_hazard_2026-09-13/restoration_ops

出力: <out>.mp4 (1920×1080, 12 fps) / <out>.gif (960×540) / <out>_still.png / <out>_summary.json
パラメータは config/restoration_ops_scenario.yaml(各値に sourced / reused / assumption の区別)。
1 つの代表モンテカルロサンプル(島ごとに 21 サンプル中、修理総量[班・日]が中央値のもの)を、
  (a) 既定モデル: restoration_default.yaml の班数を t=0 から全員稼働 + 3 日目から同数の応援(Simulator.damage 内の schedule と同一)
  (b) 本シナリオ: 巡視 0.5 日 → 被災で減った地元班 + 会社規模と距離で遅れて届く他社応援
の 2 通りの作業班制約で修理し、同じ系統モデル(CascadeModel.evaluate)で受電可能な母線を数えて比べる。
"""
from __future__ import annotations
import argparse, heapq, json, math, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import numpy as np, pandas as pd, yaml
from nankai.grid import GridCase
from nankai.montecarlo import Simulator
from nankai.hazard_field import jma_class
from nankai.aggregate import customers_per_mw, bus_prefecture

NANKAI = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.abspath(os.path.join(NANKAI, "..", ".."))
CONFIG = os.path.join(NANKAI, "config")


def val(x):
    return x["value"] if isinstance(x, dict) and "value" in x else (x["values"] if isinstance(x, dict) and "values" in x else x)


def gc_km(la1, lo1, la2, lo2):
    p1, p2 = np.radians(la1), np.radians(la2); dl = np.radians(np.asarray(lo2) - np.asarray(lo1))
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


# ───────────────────────── シナリオ計算 ─────────────────────────
def representative(sim, n, seed0):
    cand = []
    for k in range(n):
        rng = np.random.default_rng(seed0 + k); d = sim.damage(rng); d.blackout_until = sim._blackout(d, rng)
        cand.append((float(sum(j["duration_d"] for j in d.jobs)), seed0 + k, d))
    cand.sort(key=lambda c: c[0])
    tot, seed, d = cand[len(cand) // 2]
    return d, seed, [c[0] for c in cand]


def build_islands(cfg):
    S = cfg["representative_sample"]; out = {}
    for isl in cfg["scope"]["islands"]:
        case = GridCase.load(isl); sim = Simulator(case)
        d, seed, tots = representative(sim, int(S["n_candidates"]), int(S["seed0"]))
        b = case.bus
        cpm = customers_per_mw(b.groupby("zone").pd_mw.sum().to_dict())
        cust = b.pd_mw.to_numpy() * b.zone.map(cpm).fillna(0).to_numpy()
        # 代表サンプルの既定スケジュールが Simulator.damage 内の作業班スケジュールと一致することを確認
        done = sim.rm.schedule([dict(j) for j in d.jobs], None)
        chk = max([abs(done[j["id"]] - (d.done_site if j["id"][0] == "s" else d.done_line)[j["id"][1]]) for j in d.jobs] or [0.0])
        out[isl] = dict(case=case, sim=sim, d=d, seed=seed, totals=tots, cust=cust, pref=bus_prefecture(case), cls=jma_class(d.intensity), sched_check=chk)
    return out


def build_bases(I, cfg, crews_base):
    ms = float(cfg["local_crews"]["bases"]["min_share"]); bases = []
    for isl, D in I.items():
        b = D["case"].bus; zone = b.zone.to_numpy(); load = b.pd_mw.to_numpy() + 1e-3; lat = b.lat.to_numpy(); lon = b.lon.to_numpy()
        for z in np.unique(zone):
            mz = zone == z; L = load[mz].sum()
            prefs = pd.Series(load[mz], index=D["pref"][mz]).groupby(level=0).sum().sort_values(ascending=False)
            prefs = prefs[[isinstance(p, str) for p in prefs.index]]
            big = prefs.index[0]; groups = {p: [p] for p in prefs.index if prefs[p] / L >= ms}
            for p in prefs.index:
                if prefs[p] / L < ms:
                    groups[big].append(p)
            for p, members in groups.items():
                idx = np.where(mz & np.isin(D["pref"], members))[0]
                w = load[idx] / load[idx].sum(); cla, clo = float((w * lat[idx]).sum()), float((w * lon[idx]).sum())
                m = idx[np.argmin(gc_km(cla, clo, lat[idx], lon[idx]))]
                bases.append(dict(island=isl, zone=z, pref=p, lat=float(lat[m]), lon=float(lon[m]), idx=idx, w=w,
                                  crews_nom=float(crews_base.get(z, 10)) * load[idx].sum() / L))
    return bases


def availability(bases, I, cfg, t):
    """t: 時刻配列[日] → 各拠点の (稼働可能班数, 要員在籍率, 資機材率) [n_base, T]。"""
    P = cfg["personnel"]; E = cfg["equipment"]
    us_tbl = val(P["unavailable_by_class"]); ut = float(val(P["tsunami_unavailable"]))
    ts_, tt_, ps = float(val(P["tau_shake_d"])), float(val(P["tau_tsunami_d"])), float(val(P["permanent_share"]))
    eq_ts = float(val(E["loss_if_inundated"])); eq_cls = val(E["loss_by_class"]); rs = float(val(E["resupply_d"]))
    t = np.asarray(t, float)[None, :]
    gs = ps + (1 - ps) * np.exp(-t / ts_); gt = ps + (1 - ps) * np.exp(-t / tt_); ge = np.clip(1 - t / rs, 0, 1)
    eff = np.zeros((len(bases), t.shape[1])); pers = np.zeros_like(eff); equip = np.zeros_like(eff)
    for k, B in enumerate(bases):
        D = I[B["island"]]; idx = B["idx"]
        cls = D["cls"][idx]; ts = D["sim"].bus_ts[idx] >= 1
        u_s = np.array([float(us_tbl.get(str(c), 0.0)) for c in cls]); u_t = np.where(ts, ut, 0.0)
        e0 = np.maximum(np.where(ts, eq_ts, 0.0), np.array([float(eq_cls.get(str(c), 0.0)) for c in cls]))
        # (u_s, u_t, e0) の組ごとに需要重みを合算してから時間方向を計算(母線×時刻の巨大配列を作らない)
        keys = pd.DataFrame({"us": u_s, "ut": u_t, "e0": e0, "w": B["w"]}).groupby(["us", "ut", "e0"]).w.sum().reset_index()
        for _, g_ in keys.iterrows():
            pa = (1 - g_.us * gs[0]) * (1 - g_.ut * gt[0]); ea = 1 - g_.e0 * ge[0]
            pers[k] += g_.w * pa; equip[k] += g_.w * ea; eff[k] += B["crews_nom"] * g_.w * pa * ea
    return eff, pers, equip


def mutual_aid(I, cfg, crews_base, jobs_by_zone):
    A = cfg["mutual_aid"]; cust = yaml.safe_load(open(os.path.join(CONFIG, "customers.yaml"), encoding="utf-8"))["contracts_thousand"]
    H = float(val(A["own_damage_horizon_d"])); kpm = float(val(A["crews_per_million_customers"]))
    r = {}; backlog = {}
    for z in cust:
        cd = float(sum(j["duration_d"] for j in jobs_by_zone.get(z, [])))
        backlog[z] = cd; r[z] = cd / (float(crews_base.get(z, 10)) * H)
    excluded = set((A.get("excluded") or {}).keys())
    senders = {z: kpm * cust[z] / 1000.0 * max(0.0, 1.0 - r[z]) for z in cust if z not in excluded and r[z] < 1.0}
    senders = {z: v for z, v in senders.items() if v > 0.5}
    recv = [z for z in cust if r[z] > float(val(A["receiver_threshold_r"]))]
    tot_bl = sum(backlog[z] for z in recv)
    # 受け手エリアの到着目標: 修理総量で重み付けした被災サイト重心に最も近い被災サイト
    targets = {}
    for z in recv:
        pts = []
        for isl, D in I.items():
            sim = D["sim"]
            for j in D["d"].jobs:
                if j["zone"] != z:
                    continue
                kind, i = j["id"]
                if kind == "s":
                    row = sim.site_rows[i]; pts.append((float(D["case"].bus.lat.iloc[row]), float(D["case"].bus.lon.iloc[row]), j["duration_d"]))
        P_ = np.array(pts); w = P_[:, 2] / P_[:, 2].sum(); cla, clo = (w * P_[:, 0]).sum(), (w * P_[:, 1]).sum()
        m = np.argmin(gc_km(cla, clo, P_[:, 0], P_[:, 1])); targets[z] = (float(P_[m, 0]), float(P_[m, 1]))
    hq = {z: (v[0], v[1], v[2]) for z, v in val(A["headquarters"]["coords"]).items()} if "coords" in A["headquarters"] else A["headquarters"]
    dec, mob = float(val(A["decision_delay_d"])), float(val(A["mobilization_d"]))
    det, spd, hpd = float(val(A["detour_factor"])), float(val(A["convoy_speed_kmh"])), float(val(A["drive_h_per_day"]))
    inarea = float(val(A["in_area_delay_d"])); fer = A["hokkaido_ferry"]; W = A["waves"]
    road_d = lambda la1, lo1, la2, lo2: float(gc_km(la1, lo1, la2, lo2)) * det / (spd * hpd)
    convoys = []
    for s, pool in senders.items():
        for z in recv:
            if z == s:
                continue
            share = backlog[z] / tot_bl; tla, tlo = targets[z]; hla, hlo, _ = hq[s]
            if s == "hokkaido":
                p1 = fer["port_from"]; p2 = fer["port_to"]
                legs = [(hla, hlo, p1[0], p1[1], road_d(hla, hlo, p1[0], p1[1]), "road"), (p1[0], p1[1], p2[0], p2[1], float(fer["sea_d"]), "sea"),
                        (p2[0], p2[1], tla, tlo, road_d(p2[0], p2[1], tla, tlo), "road")]
                km = float(gc_km(hla, hlo, p1[0], p1[1]) + gc_km(p2[0], p2[1], tla, tlo)) * det
            else:
                legs = [(hla, hlo, tla, tlo, road_d(hla, hlo, tla, tlo), "road")]
                km = float(gc_km(hla, hlo, tla, tlo)) * det
            extra = inarea * min(1.0, r[z]); travel = sum(l[4] for l in legs) + extra
            for wv, (off, sh) in enumerate(zip(W["offsets_d"], W["shares"])):
                dep = dec + mob + float(off)
                convoys.append(dict(sender=s, zone=z, wave=wv, crews=pool * share * float(sh), depart=dep, arrive=dep + travel, legs=legs, road_km=km, travel_d=travel))
    return dict(r=r, backlog=backlog, senders=senders, receivers=recv, targets=targets, convoys=convoys, hq=hq)


def run_queues(I, bases, cfg, aid, crews_base, dt=1 / 24, horizon=400.0):
    """エリアごとの待ち行列(非割込み・優先順 = 電圧↓→需要↓)。容量 = floor(地元の稼働可能班 + 到着済み応援)。"""
    tg = np.arange(0.0, horizon + dt / 2, dt)
    eff, _, _ = availability(bases, I, cfg, tg)
    patrol = float(val(cfg["patrol_d"])); ret = float(val(cfg["mutual_aid"]["return_after_clear_d"]))
    zones = sorted(set(j["zone"] for D in I.values() for j in D["d"].jobs))
    res = {}
    for z in zones:
        jobs = [(isl, j) for isl, D in I.items() for j in D["d"].jobs if j["zone"] == z]
        jobs.sort(key=lambda x: (-float(x[1].get("kv", 0)), -float(x[1].get("load_mw", 0))))
        local = eff[[k for k, B in enumerate(bases) if B["zone"] == z]].sum(0)
        cz = [c for c in aid["convoys"] if c["zone"] == z]
        n = len(jobs); qi = 0; run = []; done = {}; t_clear = None
        qlen = np.zeros(len(tg)); nrun = np.zeros(len(tg)); aid_now = np.zeros(len(tg)); cap_arr = np.zeros(len(tg))
        for s, t in enumerate(tg):
            while run and run[0] <= t + 1e-9:
                heapq.heappop(run)
            present = sum(c["crews"] for c in cz if c["arrive"] <= t)
            if t_clear is not None and t > t_clear + ret:
                present = 0.0
            cap = 0.0 if t < patrol else local[s] + present
            while qi < n and len(run) < int(math.floor(cap + 1e-6)):
                isl, j = jobs[qi]; en = t + float(j["duration_d"]); heapq.heappush(run, en); done[(isl, j["id"])] = en; qi += 1
            if t_clear is None and qi == n and not run:
                t_clear = t
            qlen[s] = n - qi; nrun[s] = len(run); aid_now[s] = present; cap_arr[s] = cap
        res[z] = dict(tg=tg, local=local, aid=aid_now, cap=cap_arr, queue=qlen, running=nrun, done=done, n=n, t_clear=t_clear)
    return res


def ops_done_arrays(I, Q):
    out = {}
    for isl, D in I.items():
        # 修理ジョブのある要素は「未完了(inf)」で初期化し、待ち行列で完了したものだけ時刻を入れる
        ds = np.where(D["d"].done_site > 0, np.inf, 0.0); dl = np.where(D["d"].done_line > 0, np.inf, 0.0)
        for z, R in Q.items():
            for (i2, (kind, i)), en in R["done"].items():
                if i2 == isl:
                    (ds if kind == "s" else dl)[i] = en
        out[isl] = (ds, dl)
    return out


def customers_out(I, done_arrays, times):
    """各時刻の停電需要家数(物理: 受電可能でない母線の需要家)。"""
    tot = np.zeros(len(times))
    for isl, D in I.items():
        sim, d = D["sim"], D["d"]; ds, dl = done_arrays[isl]
        for k, t in enumerate(times):
            ba = (~(ds > t))[sim.bus_site]; bra = ~(dl > t); go = ~(d.done_gen > t)
            sim.cm.load = sim.load0 * sim._load_factor(d, t)      # evaluate_timeline と同じ需要減を入れる(過負荷連鎖が需要に依存するため)
            r = sim.cm.evaluate(ba, bra, sim._gen_cap(t, go))
            sim.cm.load = sim.load0
            phys = r.connected & ~(d.blackout_until > t)
            tot[k] += float(((~phys) * D["cust"]).sum())
    return tot


# ───────────────────────── 描画 ─────────────────────────
BG = "#061419"; PANEL = "#0a1f26"; GRID = "#17343c"; TXT = "#e8f1ef"; MUTED = "#8ea7aa"; TEAL = "#2ec4b6"; ORANGE = "#ff8a3d"; RED = "#ff5a5a"
SENDER_COL = ["#7aa7ff", "#c49bff", "#ffd166", "#8bd17c", "#ef6f9d", "#f4a261"]
ZONE_COL = {"chubu": "#ff8a3d", "kansai": "#ef6f9d", "shikoku": "#ffd166", "chugoku": "#8bd17c", "kyushu": "#7aa7ff", "tokyo": "#c49bff", "hokuriku": "#9fe3dc", "tohoku": "#cccccc"}
JA = {"hokkaido": "北海道", "tohoku": "東北", "tokyo": "東京", "chubu": "中部", "hokuriku": "北陸", "kansai": "関西", "chugoku": "中国", "shikoku": "四国", "kyushu": "九州", "okinawa": "沖縄"}


def xt(t):
    return np.log10(1 + np.asarray(t, float))


def clock(t):
    d = int(t + 1e-9); h = int(round((t - d) * 24))
    if h == 24:
        d += 1; h = 0
    return f"{h} 時間" if d == 0 else (f"{d} 日" if h == 0 else f"{d} 日 {h} 時間")


def render(I, bases, aid, Q, times, cust_ops, cust_base, cfg, out):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    from matplotlib.colors import LinearSegmentedColormap
    plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
    W, H = 1920, 1080
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100, facecolor=BG)
    patrol = float(val(cfg["patrol_d"])); A = cfg["mutual_aid"]
    # ── 地図(左 51%)。左上の日本海に文字、右下の太平洋に凡例
    LON0, LON1, LAT0, LAT1 = 128.9, 146.2, 30.7, 45.7; k = math.cos(math.radians(38))
    axm = fig.add_axes([0.0, 0.0, 0.51, 1.0]); axm.set_facecolor(BG); axm.set_xlim(LON0, LON1); axm.set_ylim(LAT0, LAT1); axm.set_aspect(1 / k); axm.axis("off")
    g = json.load(open(os.path.join(ROOT, "data", "reference", "japan_prefectures_simplified.geojson"), encoding="utf-8"))
    polys = []
    for f in g["features"]:
        geom = f["geometry"]; rings = geom["coordinates"][:1] if geom["type"] == "Polygon" else [p[0] for p in geom["coordinates"]]
        polys += [np.array(r) for r in rings]
    axm.add_collection(PolyCollection(polys, facecolors="#10262e", edgecolors="#23434c", linewidths=0.5))
    # 被災サイト(変電所・送電線の中点)
    sx, sy, skv, sdone_o = [], [], [], []
    for isl, D in I.items():
        sim, d, case = D["sim"], D["d"], D["case"]; ds_o, dl_o = OPS[isl]
        for j in d.jobs:
            kind, i = j["id"]
            if kind == "s":
                row = sim.site_rows[i]; la, lo = case.bus.lat.iloc[row], case.bus.lon.iloc[row]; dn = ds_o[i]
            else:
                la, lo = case.branch.mid_lat.iloc[i], case.branch.mid_lon.iloc[i]; dn = dl_o[i]
            if np.isfinite(la) and np.isfinite(lo):
                sx.append(lo); sy.append(la); skv.append(float(j.get("kv", 66))); sdone_o.append(dn)
    sx, sy, skv, sdone_o = map(np.array, (sx, sy, skv, sdone_o))
    ssize = np.clip(skv / 18, 6, 30)
    site_sc = axm.scatter(sx, sy, s=ssize, c=ORANGE, lw=0, alpha=0.95, zorder=3)
    # 地元の拠点: 外輪 = 被災前の班数、塗り = 稼働できる班数(色 = 稼働率)
    bx = np.array([B["lon"] for B in bases]); by = np.array([B["lat"] for B in bases]); bnom = np.array([B["crews_nom"] for B in bases])
    size_of = lambda c: 8 + 14 * np.asarray(c)
    cmap = LinearSegmentedColormap.from_list("avail", [(0, RED), (0.5, RED), (0.72, "#ffb347"), (0.9, TEAL), (1.0, TEAL)])
    axm.scatter(bx, by, s=size_of(bnom), facecolors="none", edgecolors="#7e9da2", lw=1.0, zorder=4)
    base_sc = axm.scatter(bx, by, s=size_of(bnom), c=np.ones(len(bx)), cmap=cmap, vmin=0, vmax=1, alpha=0.9, lw=0, zorder=5)
    base_x = axm.scatter([], [], marker="x", s=46, c="white", lw=1.6, zorder=6)
    # 応援: 送り手の本店と車列
    senders = list(aid["senders"].keys()); scol = {s: SENDER_COL[i % len(SENDER_COL)] for i, s in enumerate(senders)}
    for s in senders:
        la, lo, _ = aid["hq"][s]
        axm.scatter([lo], [la], marker="s", s=90, c=scol[s], edgecolors="white", lw=1.0, zorder=9)
        axm.text(lo + 0.32, la + 0.05, f"{JA[s]}  {aid['senders'][s]:.0f} 班", color=scol[s], fontsize=14, fontweight="bold", zorder=10, va="center")
    wp = A["hokkaido_ferry"].get("sea_waypoints") or []
    pairs = {}
    for c in aid["convoys"]:
        pairs.setdefault((c["sender"], c["zone"]), []).append(c)
    convoy_art = []
    for (s, z), cs in pairs.items():
        legs = cs[0]["legs"]
        # 描画用の折れ線と、各区間の所要時間の割り当て(海路は航路点で分割)
        seg_pts = [(legs[0][1], legs[0][0])]; seg_t = []
        for l in legs:
            if l[5] == "sea" and wp:
                chain = [(l[1], l[0])] + [(q[1], q[0]) for q in wp] + [(l[3], l[2])]
                L = np.array([gc_km(chain[m][1], chain[m][0], chain[m + 1][1], chain[m + 1][0]) for m in range(len(chain) - 1)]); L = L / L.sum()
                for m in range(len(chain) - 1):
                    seg_pts.append(chain[m + 1]); seg_t.append(l[4] * L[m])
            else:
                seg_pts.append((l[3], l[2])); seg_t.append(l[4])
        seg_t[-1] += cs[0]["travel_d"] - sum(seg_t)   # 被災域内の遅延は最終区間に含める
        ln, = axm.plot([], [], color=scol[s], lw=1.3, alpha=0.0, zorder=4)
        dots = axm.scatter([], [], s=60, c=scol[s], edgecolors="white", lw=0.9, zorder=11)
        convoy_art.append(dict(s=s, z=z, cs=cs, pts=np.array(seg_pts), segt=np.array(seg_t), line=ln, dots=dots))
    for z, (la, lo) in aid["targets"].items():
        axm.text(lo, la - 0.36, JA[z], color=ZONE_COL.get(z, TXT), fontsize=13, fontweight="bold", ha="center", va="top", zorder=8)
    # ── 左上: タイトル・時計・KPI
    fig.text(0.016, 0.948, "復旧オペレーション・シナリオ", color=TXT, fontsize=30, fontweight="bold")
    fig.text(0.017, 0.915, "南海トラフ Mw9.1 × All-Japan-Grid ・ 代表 1 サンプル", color=MUTED, fontsize=14)
    fig.text(0.017, 0.872, "発災から", color=MUTED, fontsize=15)
    clock_t = fig.text(0.016, 0.805, "", color=TXT, fontsize=50, fontweight="bold")
    phase_t = fig.text(0.017, 0.765, "", color=ORANGE, fontsize=17, fontweight="bold")
    kpi_t = fig.text(0.017, 0.742, "", color=TXT, fontsize=14, linespacing=1.6, va="top", family=["Hiragino Sans"])
    nonsend = [z for z in aid["receivers"]]
    eta_lines = []
    for s in senders:
        cs = [c for c in aid["convoys"] if c["sender"] == s and c["wave"] == 0]
        a0 = min(cs, key=lambda c: c["arrive"]); a1 = max(cs, key=lambda c: c["arrive"])
        via = " (海路)" if s == "hokkaido" else ""
        eta_lines.append((s, f"{JA[s]}{via}: 第1陣 {a0['arrive']:.1f}日({JA[a0['zone']]}) 〜 {a1['arrive']:.1f}日({JA[a1['zone']]})"))
    fig.text(0.017, 0.592, f"他社応援の到着(第1陣・{len(aid['receivers'])} エリアに分散)", color=MUTED, fontsize=12.5)
    for i, (s, line) in enumerate(eta_lines):
        fig.text(0.017, 0.566 - 0.024 * i, line, color=scol[s], fontsize=12.5)
    rtxt = "・".join(f"{JA[z]} {aid['r'][z]:.0f}" for z in sorted(aid["receivers"], key=lambda z: -aid["r"][z]))
    y_r = 0.566 - 0.024 * len(eta_lines) - 0.006
    fig.text(0.017, y_r, "自社被害度 r(1 以上の会社は送り手になれない)", color=MUTED, fontsize=11)
    fig.text(0.017, y_r - 0.021, rtxt, color=MUTED, fontsize=11)
    # 右下(太平洋): 凡例
    lg = [("●", TEAL, "地元の作業班拠点(大きさ = 稼働できる班数、外の輪 = 被災前)"), ("●", "#ffb347", "色 = 稼働率(緑 9 割以上・橙 7 割・赤 5 割以下)"),
          ("×", "white", "班の 4 割以上が動けない拠点"), ("●", ORANGE, "未修理の変電所・送電線"), ("■", SENDER_COL[1], "応援の送り手の本店と車列(点が移動中の班)")]
    for i, (mk, col, txt) in enumerate(lg):
        fig.text(0.262, 0.215 - 0.026 * i, mk, color=col, fontsize=12); fig.text(0.276, 0.215 - 0.026 * i, txt, color=MUTED, fontsize=11.5)
    # ── 右: グラフ 3 枚
    X0, WX = 0.555, 0.43
    ax1 = fig.add_axes([X0, 0.665, WX, 0.27]); ax2 = fig.add_axes([X0, 0.385, WX, 0.2]); ax3 = fig.add_axes([X0, 0.115, WX, 0.2])
    ticks = [0, 1, 3, 7, 14, 30, 90]; tl = ["直後", "1日", "3日", "1週", "2週", "1月", "3月"]
    for ax in (ax1, ax2, ax3):
        ax.set_facecolor(PANEL); ax.set_xlim(0, xt(90)); ax.set_xticks(xt(ticks)); ax.set_xticklabels(tl, color=MUTED, fontsize=11)
        ax.tick_params(colors=MUTED, labelsize=11); ax.grid(color=GRID, lw=0.8); [sp.set_color(GRID) for sp in ax.spines.values()]
    recv = aid["receivers"]; tgQ = next(iter(Q.values()))["tg"]
    in_recv = np.array([B["zone"] in recv for B in bases])          # 文字の班数もグラフと同じ被災エリアに揃える(送り手の地元班を二重に数えない)
    local_r = sum(Q[z]["local"] for z in recv if z in Q)
    aid_by_s = {s: np.zeros(len(tgQ)) for s in senders}
    for z in recv:
        if z not in Q:
            continue
        R = Q[z]; alive = np.ones(len(tgQ), bool)
        if R["t_clear"] is not None:
            alive = tgQ <= R["t_clear"] + float(val(A["return_after_clear_d"]))
        for c in aid["convoys"]:
            if c["zone"] == z:
                aid_by_s[c["sender"]] += np.where((tgQ >= c["arrive"]) & alive, c["crews"], 0.0)
    nom_r = sum(CREWS_BASE.get(z, 10) for z in recv)
    base_model = np.where(tgQ >= float(RP["crews"]["mutual_aid_start_d"]), nom_r * float(RP["crews"]["mutual_aid_factor"]), nom_r)
    ymax1 = max(float((local_r + sum(aid_by_s.values())).max()), float(base_model.max())) * 1.22
    ax1.set_ylim(0, ymax1); ax1.set_title(f"被災 {len(recv)} エリアに投入できる送変電の作業班", color=TXT, fontsize=15, loc="left", pad=8)
    ax1.plot(xt(tgQ), base_model, color="#b7c3c4", lw=1.6, ls="--", zorder=6)
    hd = [Patch(color=TEAL, label="地元(稼働可)")] + [Patch(color=scol[s], label=f"応援: {JA[s]}") for s in senders] + [Line2D([], [], color="#b7c3c4", ls="--", label="既定モデル(被災なし・3日目から同数の応援)")]
    leg = ax1.legend(handles=hd, loc="upper left", ncol=3, frameon=False, fontsize=11, labelcolor=MUTED, handlelength=1.2, columnspacing=1.2)
    ax2.set_title("待ち行列 — まだ着手できない修理(件)", color=TXT, fontsize=15, loc="left", pad=8)
    ymax2 = max(float(Q[z]["queue"].max()) for z in recv if z in Q) * 1.12; ax2.set_ylim(0, ymax2)
    ax3.set_title("停電中の需要家(万軒・物理・代表 1 サンプル)", color=TXT, fontsize=15, loc="left", pad=8)
    ymax3 = float(max(cust_ops.max(), cust_base.max())) / 1e4 * 1.18; ax3.set_ylim(0, ymax3)
    fig.text(0.985, 0.068, "横軸は対数目盛", color="#6f878b", fontsize=10.5, ha="right")
    fig.text(0.016, 0.034, FOOTER[0], color="#6f878b", fontsize=10.5); fig.text(0.016, 0.012, FOOTER[1], color="#6f878b", fontsize=10.5)
    dyn = []; frames = []; tmp = tempfile.mkdtemp()
    dt = tgQ[1] - tgQ[0]
    first_arr = min(c["arrive"] for c in aid["convoys"]); last_arr = max(c["arrive"] for c in aid["convoys"])

    XR = xt(90)

    def lab_at(xnow):
        """現在時刻の横にラベル。右端に近づいたら線の左側へ回す(はみ出し防止)。"""
        return (xnow + 0.012, "left") if xnow < XR * 0.8 else (xnow - 0.045, "right")

    def upto(arr_t, arr_v, t):
        m = arr_t <= t + 1e-9
        return xt(arr_t[m]), arr_v[m]

    for fi, t in enumerate(times):
        for a_ in dyn:
            a_.remove()
        dyn = []
        s_idx = min(int(round(t / dt)), len(tgQ) - 1)
        remain = sdone_o > t + 1e-9
        site_sc.set_offsets(np.c_[sx[remain], sy[remain]]); site_sc.set_sizes(ssize[remain])
        effk = availability(bases, I, cfg, [t])[0][:, 0]; ratio = effk / np.maximum(bnom, 1e-9)
        base_sc.set_sizes(size_of(effk)); base_sc.set_array(ratio); bad = ratio < 0.6
        base_x.set_offsets(np.c_[bx[bad], by[bad]] if bad.any() else np.empty((0, 2)))
        for C in convoy_art:
            cs = C["cs"]; dep = min(c["depart"] for c in cs); arrN = max(c["arrive"] for c in cs); pts = C["pts"]
            if t < dep:
                C["line"].set_alpha(0.0); C["dots"].set_offsets(np.empty((0, 2))); continue
            C["line"].set_data(pts[:, 0], pts[:, 1]); C["line"].set_alpha(0.6 if t < arrN else 0.14)
            C["line"].set_linestyle((0, (4, 3)) if C["s"] == "hokkaido" else "-")
            pos = []
            cum = np.r_[0, np.cumsum(C["segt"])]
            for c in cs:
                if c["depart"] <= t < c["arrive"]:
                    el = t - c["depart"]; kk = min(np.searchsorted(cum, el, side="right") - 1, len(C["segt"]) - 1); ff = (el - cum[kk]) / max(C["segt"][kk], 1e-9)
                    pos.append(pts[kk] + (pts[kk + 1] - pts[kk]) * ff)
            C["dots"].set_offsets(np.array(pos) if pos else np.empty((0, 2)))
        clock_t.set_text(clock(t))
        if t < patrol:
            ph = "巡視・安全確認 — まだ修理に着手できない"
        elif t < first_arr:
            ph = "地元の班だけで着手 — 被災した拠点は人も車両も欠ける"
        elif t <= last_arr:
            ph = "他社の応援が順に到着する"
        elif t < 30:
            ph = "待ち行列を消化 — 短い修理から片付く"
        else:
            ph = "長い修理(津波被災の変電所)が最後まで残る"
        phase_t.set_text(ph)
        aid_now = float(sum(v[s_idx] for v in aid_by_s.values()))
        qn = int(sum(Q[z]["queue"][s_idx] for z in Q)); rn = int(sum(Q[z]["running"][s_idx] for z in Q))
        kpi_t.set_text(f"地元の班　稼働 {effk[in_recv].sum():,.0f} / 被災前 {bnom[in_recv].sum():,.0f} 班(被災 {len(recv)} エリア)\n他社応援　到着 {aid_now:,.0f} 班(送り手 {len(senders)} 社)\n修理　　　作業中 {rn:,} 件・待ち {qn:,} 件\n停電　　　{cust_ops[fi]/1e4:,.0f} 万軒(既定モデル {cust_base[fi]/1e4:,.0f} 万軒)")
        # グラフ1
        x_, loc_ = upto(tgQ, local_r, t); bottom = loc_.copy()
        dyn.append(ax1.fill_between(x_, 0, loc_, color=TEAL, alpha=0.85, lw=0))
        for s in senders:
            _, v = upto(tgQ, aid_by_s[s], t)
            dyn.append(ax1.fill_between(x_, bottom, bottom + v, color=scol[s], alpha=0.95, lw=0)); bottom = bottom + v
        if len(x_):
            lx, ha = lab_at(x_[-1]); dyn.append(ax1.text(lx, bottom[-1] + ymax1 * 0.05, f"{bottom[-1]:,.0f} 班", color=TXT, fontsize=11.5, va="center", ha=ha))
        dyn.append(ax1.axvline(xt(t), color="white", lw=1.0, alpha=0.5))
        # グラフ2(ラベルは重ならないよう縦にずらす)
        labs = []
        for z in recv:
            if z not in Q:
                continue
            x_, v = upto(tgQ, Q[z]["queue"], t)
            ln, = ax2.plot(x_, v, color=ZONE_COL.get(z, TXT), lw=2.2); dyn.append(ln)
            if len(v):
                labs.append([v[-1], z, x_[-1]])
        labs.sort(key=lambda r: r[0]); gap = ymax2 * 0.095; ylast = -1e9
        right_mode = bool(labs) and lab_at(labs[0][2])[1] == "right"
        for n_, r_ in enumerate(labs):
            yy = max(r_[0], ylast + gap); ylast = yy; lx, ha = lab_at(r_[2])
            if right_mode:           # 右端では線と重ならない上側の空白に縦に並べる
                yy = ymax2 * 0.9 - gap * (len(labs) - 1 - n_)
            dyn.append(ax2.text(lx, yy, f"{JA[r_[1]]} {int(r_[0])}", color=ZONE_COL.get(r_[1], TXT), fontsize=10.5, va="center", ha=ha))
        dyn.append(ax2.axvline(xt(t), color="white", lw=1.0, alpha=0.5))
        # グラフ3
        m = times <= t + 1e-9
        ln, = ax3.plot(xt(times[m]), cust_ops[m] / 1e4, color=ORANGE, lw=2.6); dyn.append(ln)
        ln, = ax3.plot(xt(times[m]), cust_base[m] / 1e4, color="#cfd8d9", lw=1.6, ls="--"); dyn.append(ln)
        yo, yb = cust_ops[fi] / 1e4, cust_base[fi] / 1e4; sep = ymax3 * 0.10
        if abs(yo - yb) >= sep:
            ya, yb2 = yo, yb
        else:
            mid = (yo + yb) / 2; up = sep / 2 if yo >= yb else -sep / 2; ya, yb2 = mid + up, mid - up
        lx, ha = lab_at(xt(t))
        if ha == "right":            # 右端では線と重ならない上側の空白へ
            ya, yb2 = ymax3 * 0.86, ymax3 * 0.74
        dyn.append(ax3.text(lx, ya, f"本シナリオ {yo:,.0f} 万", color=ORANGE, fontsize=11.5, va="center", ha=ha))
        dyn.append(ax3.text(lx, yb2, f"既定モデル {yb:,.0f} 万", color="#cfd8d9", fontsize=10.5, va="center", ha=ha))
        dyn.append(ax3.axvline(xt(t), color="white", lw=1.0, alpha=0.5))
        p = os.path.join(tmp, f"f{fi:04d}.png"); fig.savefig(p, facecolor=BG); frames.append(p)
    return frames


def main():
    global OPS, CREWS_BASE, RP, FOOTER
    ap = argparse.ArgumentParser(); ap.add_argument("out"); ap.add_argument("--config", default=os.path.join(CONFIG, "restoration_ops_scenario.yaml")); a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8")); RP = yaml.safe_load(open(os.path.join(CONFIG, "restoration_default.yaml"), encoding="utf-8"))
    CREWS_BASE = RP["crews"]["base"]
    I = build_islands(cfg)
    bases = build_bases(I, cfg, CREWS_BASE)
    jobs_by_zone = {}
    for D in I.values():
        for j in D["d"].jobs:
            jobs_by_zone.setdefault(j["zone"], []).append(j)
    aid = mutual_aid(I, cfg, CREWS_BASE, jobs_by_zone)
    Q = run_queues(I, bases, cfg, aid, CREWS_BASE)
    OPS = ops_done_arrays(I, Q)
    # 描画時刻
    R = cfg["render"]; times = []
    for s, e, st in R["frame_times_d"]:
        times += list(np.arange(float(s), float(e) - 1e-9, float(st)))
    times.append(90.0); times = np.array(sorted(set(np.round(times, 4))))
    base_arrays = {isl: (D["d"].done_site, D["d"].done_line) for isl, D in I.items()}
    cust_ops = customers_out(I, OPS, times); cust_base = customers_out(I, base_arrays, times)
    # 検算: 既定スケジュールの停電需要家を Simulator.evaluate_timeline(phys)と突き合わせる
    chk = {}
    for tt in (0.0, 1.0, 7.0, 30.0):
        tot = 0.0
        for isl, D in I.items():
            sim = D["sim"]; T = list(sim.timeline); k = T.index(tt)
            _, phys, _ = sim.evaluate_timeline(D["d"]); tot += float(((1 - phys[k]) * D["cust"]).sum())
        chk[tt] = (tot, float(cust_base[np.argmin(abs(times - tt))]))
    A = cfg["mutual_aid"]
    FOOTER = ("仮定: 班数 = restoration_default.yaml(仮定値) ・ 要員の不在 震度6弱 20%・6強 35%・7 50%・浸水域 80%(指数回復・1 割は戻らない) ・ 浸水域の車両・資機材は全損→7 日で線形回復 ・ 巡視 0.5 日",
              f"応援 = 供給地点数(customers.yaml) × {val(A['crews_per_million_customers']):g} 班/百万口 × (1 − 自社被害度) ・ 道路距離 = 大円 × {val(A['detour_factor']):g}・{val(A['convoy_speed_kmh']):g} km/h × {val(A['drive_h_per_day']):g} h/日 ・ 北海道は海路 1 日 ・ 沖縄は除外 ・ 対象は送変電の修理のみ(配電・電源車なし) ・ 実在の応援計画ではない")
    frames = render(I, bases, aid, Q, times, cust_ops, cust_base, cfg, a.out)
    # 出力(各時刻 hold_frames コマ・節目で長く止める)
    fps = int(R["fps"]); hold = int(R["hold_frames"]); hat = {float(k): int(v) for k, v in R["hold_at_d"].items()}
    lst = os.path.join(os.path.dirname(frames[0]), "l.txt")
    with open(lst, "w") as f:
        for p, t in zip(frames, times):
            f.write(f"file '{p}'\nduration {hat.get(round(float(t), 4), hold) / fps}\n")
        f.write(f"file '{frames[-1]}'\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-vf", "scale=1920:1080,format=yuv420p", "-r", str(fps), "-c:v", "libx264", "-crf", "20", "-movflags", "+faststart", a.out + ".mp4"], check=True)
    pal = os.path.join(os.path.dirname(frames[0]), "pal.png")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", a.out + ".mp4", "-vf", "fps=6,scale=960:-1:flags=lanczos,palettegen=stats_mode=diff", pal], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", a.out + ".mp4", "-i", pal, "-lavfi", "fps=6,scale=960:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle", "-loop", "0", a.out + ".gif"], check=True)
    import shutil; shutil.copy(frames[-1], a.out + "_still.png")
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.out + ".mp4"], capture_output=True, text=True).stdout.strip())
    summ = {
        "representative_seed": {isl: D["seed"] for isl, D in I.items()},
        "candidate_total_crew_days": {isl: [round(x) for x in D["totals"]] for isl, D in I.items()},
        "schedule_reproduces_simulator_max_abs_diff_d": {isl: D["sched_check"] for isl, D in I.items()},
        "bases": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in B.items() if k not in ("idx", "w")} for B in bases],
        "own_damage_r": {z: round(v, 2) for z, v in aid["r"].items()},
        "backlog_crew_days": {z: round(v) for z, v in aid["backlog"].items()},
        "senders_crews": {z: round(v, 1) for z, v in aid["senders"].items()},
        "receivers": aid["receivers"],
        "convoys": [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in c.items() if k != "legs"} for c in aid["convoys"]],
        "zone_clear_day": {z: (round(R_["t_clear"], 2) if R_["t_clear"] is not None else None) for z, R_ in Q.items()},
        "jobs_by_zone": {z: R_["n"] for z, R_ in Q.items()},
        "customers_out_10k": {f"{tt:g}": {"scenario": round(float(cust_ops[np.argmin(abs(times - tt))]) / 1e4, 1), "default_model": round(float(cust_base[np.argmin(abs(times - tt))]) / 1e4, 1)} for tt in (0, 0.5, 1, 3, 7, 14, 30, 60, 90)},
        "check_default_vs_evaluate_timeline_customers": {f"{k:g}": [round(v[0]), round(v[1])] for k, v in chk.items()},
        "local_available_crews_all_bases": {f"{tt:g}": round(float(availability(bases, I, cfg, [tt])[0][:, 0].sum()), 1) for tt in (0, 1, 3, 7, 14, 30)},
        "nominal_crews_all_bases": round(float(sum(B["crews_nom"] for B in bases)), 1),
        "video": {"mp4_mb": round(os.path.getsize(a.out + ".mp4") / 1e6, 2), "gif_mb": round(os.path.getsize(a.out + ".gif") / 1e6, 2), "duration_s": round(dur, 1), "unique_frames": len(frames)},
    }
    json.dump(summ, open(a.out + "_summary.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: summ[k] for k in ("representative_seed", "schedule_reproduces_simulator_max_abs_diff_d", "own_damage_r", "senders_crews", "receivers", "zone_clear_day", "customers_out_10k", "check_default_vs_evaluate_timeline_customers", "local_available_crews_all_bases", "nominal_crews_all_bases", "video")}, ensure_ascii=False, indent=0))


if __name__ == "__main__":
    main()
