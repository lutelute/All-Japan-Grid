"""1 サンプルの解析を「1 手ずつ」記録するトレーサ。

各手 = {phase, line(擬似コードの行), title, text, hl(強調: buses/lines/gens/zones), delta(状態の差分)}。
ビューアは delta を順に適用して任意の手の状態を再現する。
"""
from __future__ import annotations
import heapq
import numpy as np
import pandas as pd
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components

from .hazard_field import jma_class
from .fragility import p_exceed, substation_class, trip_probability, _rank_table

PSEUDO = [
    "地震動場をサンプルする: I_i = メッシュ震度 + 空間相関ノイズ, PGA_i = g(PGV_i)",
    "for 変電所サイト s: p_s = F_kv(PGA_s) + 津波(ρ_s);  u ~ U(0,1);  if u < p_s: 停止(DS)",
    "for 線路 l: p_l = 1 − (1 − p_tower(PGA))^n_towers + 津波;  u < p_l → 停止",
    "for 発電機 g: 震度階級の停止率曲線 f_c(t);  u ~ U(0,1);  停止期間 τ = sup{t : u < f_c(t)}",
    "生きている母線・枝で連結成分を求める;  供給源の無い成分 = 上流孤立",
    "for エリア z: δ_z = 1 − (G_z + T_z)/L_z;  if δ_z > 0.25: エリア全停(系統崩壊)",
    "for 成分 c: r_c = min(1, G_c/L_c);  供給 S_i = r_c · L_i(比例遮断)",
    "DC潮流 Bθ = P を解き f_ij = (θ_i−θ_j)/x_ij;  |f| > 1.25 S の枝を上位 3 本停止 → 5 へ戻る(最大 8 回)",
    "復旧ジョブを 電圧 → 需要 の順に並べ、空いた作業班に割り当てる: 完了 c_e = 開始 + τ_e",
    "for t in 時刻列: 生存集合 {e : c_e ≤ t} で 5〜8 を再評価 → 供給率(t)",
]


def _fmt(x, nd=2):
    return f"{x:.{nd}f}"


def trace_sample(sim, seed: int = 7, max_line_events: int = 60, max_gen_events: int = 40, max_jobs: int = 220) -> dict:
    case = sim.case; rng = np.random.default_rng(seed)
    fm = sim.fm; rm = sim.rm; cm = sim.cm
    n = case.n_bus; lat, lon = sim.lat, sim.lon
    bus_name = case.bus.name.astype(str).to_numpy(); site_name = case.bus.site.astype(str).to_numpy()
    load = cm.load; zones = case.bus.zone.to_numpy()
    steps = []

    def ev(phase, line, title, text, hl=None, delta=None, t=None):
        steps.append({"ph": phase, "ln": line, "ti": title, "tx": text, "hl": hl or {}, "d": delta or {}, **({"t": t} if t is not None else {})})

    # ── 1. 地震動 ────────────────────────────────────────────
    hs = sim.field.sample(lat, lon, rng=rng, randomize=True)
    I = hs.intensity; PGA = hs.pga_g; icls = jma_class(I)
    cnt = pd.Series(icls).value_counts().to_dict()
    ev(1, 0, "地震動場を 1 回サンプル", f"J-SHIS の期待震度に相関距離 25 km のノイズ(σ=0.12)を乗せた。母線の震度階級: " + "、".join(f"{k} {v}" for k, v in sorted(cnt.items(), key=lambda kv: -kv[1])) + "。PGA は PGV からの換算。",
       delta={"I": [round(float(x), 2) for x in I]})
    # ── 2. 変電所 ────────────────────────────────────────────
    pga_site = np.zeros(len(sim.site_rows)); np.maximum.at(pga_site, sim.bus_site, PGA)
    i_site = np.zeros(len(sim.site_rows)); np.maximum.at(i_site, sim.bus_site, I)
    sp_ = fm.p["substation"]; ff = int(sp_["functional_failure_ds"])
    p_shake = fm.substation_pout(sim.site_kv, pga_site, i_site); p_shake[sim.site_is_junction] = 0.0
    p_ts = _rank_table(sp_["tsunami"]["pfail_by_rank"], sim.site_ts); p_ts[sim.site_is_junction] = 0.0
    u1 = rng.random(len(sim.site_rows)); u2 = rng.random(len(sim.site_rows))
    out_shake = u1 < p_shake; out_ts = u2 < p_ts
    site_ds = np.where(out_shake | out_ts, ff, 0); site_cause = np.where(out_ts, 2, np.where(out_shake, 1, 0))
    cl = sp_["classes"]; adj = float(sp_.get("japan_adjustment", 1.0))
    p4 = np.zeros(len(pga_site))
    for name in ("low", "medium", "high"):
        m = np.array([substation_class(k, cl) == name for k in sim.site_kv])
        if m.any():
            p4[m] = p_exceed(pga_site[m], cl[name]["median"][3] * adj, cl[name]["beta"][3])
    u3 = rng.random(len(sim.site_rows))
    site_ds = np.where(out_shake & ~out_ts & (u3 < p4 / np.maximum(p_shake, 1e-9)), 4, site_ds)
    order = np.argsort(-(p_shake + p_ts))
    n_fail = 0
    for s_ in order:
        if not (out_shake[s_] or out_ts[s_]):
            continue
        b0 = sim.site_rows[s_]; buses = np.where(sim.bus_site == s_)[0]
        cause = "津波" if out_ts[s_] else "揺れ"
        detail = (f"浸水深ランク {int(sim.site_ts[s_])} → 停止確率 {_fmt(p_ts[s_])}、u = {_fmt(u2[s_])} < p → 停止" if out_ts[s_]
                  else f"震度 {_fmt(i_site[s_],1)}({icls[b0]}) → PGA {_fmt(pga_site[s_])} g → HAZUS×5 で停止確率 {_fmt(p_shake[s_], 3)}、u = {_fmt(u1[s_], 3)} < p → 停止(DS{int(site_ds[s_])})")
        ev(2, 1, f"変電所 {site_name[b0]} ({int(sim.site_kv[s_])} kV) が{cause}で停止", detail + f"。需要 {sim.site_load[s_]:.0f} MW、母線 {len(buses)} 本。",
           hl={"b": [int(x) for x in buses]}, delta={"bus": {int(x): ("S" if cause == "揺れ" else "T") for x in buses}})
        n_fail += 1
    near = np.where(~(out_shake | out_ts) & ~sim.site_is_junction & (p_shake > 0.05))[0]
    ev(2, 1, f"残り {int((~sim.site_is_junction).sum()) - n_fail} サイトは継続", f"u ≥ p で継続。停止確率 5% 超でも耐えたサイトが {len(near)} か所(例: " + "、".join(f"{site_name[sim.site_rows[s_]]} p={_fmt(p_shake[s_])} u={_fmt(u1[s_])}" for s_ in near[np.argsort(-p_shake[near])][:4]) + ")。",
       hl={"b": [int(sim.site_rows[s_]) for s_ in near[:200]]})
    # ── 3. 線路 ─────────────────────────────────────────────
    pga_br = np.maximum(PGA[sim.bf], PGA[sim.bt]); i_br = np.maximum(I[sim.bf], I[sim.bt])
    lp = fm.p["line"]; tw = lp["tower"]
    pt = p_exceed(pga_br, tw["median"], tw["beta"]); nt = np.maximum(sim.br_len / tw["spacing_km"], 1.0)
    p_line = 1 - (1 - pt) ** nt; p_line = np.where(sim.br_par >= 2, p_line * lp.get("parallel_reduction", 0.5), p_line)
    p_lts = _rank_table(lp["tsunami"]["pfail_by_rank"], sim.br_ts, 0.5)
    p_short = trip_probability(jma_class(i_br), lp.get("short_outage", {})) if lp.get("short_outage") else np.zeros(len(pga_br))
    ul = rng.random(len(pga_br)); ut = rng.random(len(pga_br)); us = rng.random(len(pga_br))
    line_cause = np.where(ut < p_lts, 2, np.where(ul < p_line, 1, np.where(us < p_short, 3, 0)))
    lf = line_cause > 0
    brname = case.branch.name.astype(str).to_numpy(); brkind = case.branch.kind.to_numpy()
    k_fail = np.where(lf)[0]; k_fail = k_fail[np.argsort(-(p_line + p_lts + p_short)[k_fail])]
    for k in k_fail[:max_line_events]:
        c = {1: "鉄塔倒壊(揺れ)", 2: "津波", 3: "がいし等の短期停止"}[int(line_cause[k])]
        txt = {1: f"PGA {_fmt(pga_br[k])} g、長さ {sim.br_len[k]:.1f} km → 鉄塔 {nt[k]:.0f} 基 → 停止確率 {_fmt(p_line[k], 4)}、u = {_fmt(ul[k], 4)} < p",
               2: f"浸水深ランク {int(sim.br_ts[k])} → 停止確率 {_fmt(p_lts[k])}、u = {_fmt(ut[k])} < p",
               3: f"震度 {_fmt(i_br[k],1)} → 短期停止確率 {_fmt(p_short[k], 3)}、u = {_fmt(us[k], 3)} < p"}[int(line_cause[k])]
        ev(3, 2, f"{'変圧器' if brkind[k]=='trafo' else '線路'} {brname[k][:28]} ({int(sim.br_kv[k])} kV) が{c}", txt, hl={"l": [int(k)]}, delta={"line": {int(k): "F"}})
    if len(k_fail) > max_line_events:
        ev(3, 2, f"ほか {len(k_fail) - max_line_events} 本が停止", "同じ手順(確率と一様乱数の比較)。", delta={"line": {int(k): "F" for k in k_fail[max_line_events:]}})
    ev(3, 2, f"線路・変圧器 {int(lf.sum())} / {len(lf)} 本が停止", f"鉄塔倒壊 {int((line_cause==1).sum())}、津波 {int((line_cause==2).sum())}、短期停止 {int((line_cause==3).sum())}。地震動単独の倒壊は稀(1 基あたり中央値 12 g)。")
    # ── 4. 発電機 ────────────────────────────────────────────
    gout, gds, gcause = fm.generator_state(sim.gcls, PGA[sim.gb], I[sim.gb], sim.gen_ts, rng)
    gout = np.where(sim.gslack, 0.0, gout); gds = np.where(sim.gslack, 0, gds); gcause = np.where(sim.gslack, 0, gcause)
    gff = int(fm.p["generator"]["functional_failure_ds"]); done_gen = gout.copy()
    for i in np.where(gds >= gff)[0]:
        done_gen[i] = max(done_gen[i], rm.repair_time_days("generator", int(gds[i]), int(gcause[i]), rng))
    gname = case.gen.name.astype(str).to_numpy(); gp = sim.gp
    big = np.where((done_gen > 0) & ~sim.gslack)[0]; big = big[np.argsort(-gp[big])]
    shown = 0; agg = {}
    for i in big:
        if shown < max_gen_events and gp[i] >= 100:
            c = {3: "震度別停止率曲線(自動停止/損傷)", 2: "津波浸水", 1: "損傷(脆弱性曲線)"}.get(int(gcause[i]), "停止")
            ev(4, 3, f"発電所 {gname[i][:24]} {gp[i]:.0f} MW が停止 ({sim.gcls[i]})", f"{c}。震度 {_fmt(I[sim.gb[i]],1)}({icls[sim.gb[i]]}) → 停止期間 {done_gen[i]:.1f} 日。", hl={"b": [int(sim.gb[i])]}, delta={"gen": {int(i): round(float(done_gen[i]), 2)}})
            shown += 1
        else:
            agg[int(i)] = round(float(done_gen[i]), 2)
    tot = gp[big].sum(); ev(4, 3, f"停止発電 合計 {tot/1000:.1f} GW / {gp[~sim.gslack].sum()/1000:.1f} GW", f"100 MW 未満や表示しきれない {len(agg)} 基は同じ規則でまとめて停止。", delta={"gen": agg})
    # ── 復旧スケジュール(先に計算しておく; 提示は 9 で) ─────────
    jobs = []
    for s_ in np.where(site_ds >= ff)[0]:
        jobs.append({"id": ("s", int(s_)), "zone": sim.site_zone[s_], "kv": sim.site_kv[s_], "load_mw": sim.site_load[s_], "duration_d": rm.repair_time_days("substation", int(site_ds[s_]), int(site_cause[s_]), rng)})
    so = fm.p["line"].get("short_outage", {"median_d": 2.0, "beta": 0.5})
    for k in np.where(lf)[0]:
        dur = float(np.exp(np.log(so["median_d"]) + so["beta"] * rng.normal())) if line_cause[k] == 3 else rm.repair_time_days("line", 4, int(line_cause[k]), rng)
        jobs.append({"id": ("l", int(k)), "zone": sim.br_zone[k], "kv": sim.br_kv[k], "load_mw": 0.0, "duration_d": dur})
    assign = []
    done = _schedule_logged(rm, jobs, assign)
    done_site = np.zeros(len(site_ds)); done_line = np.zeros(len(lf))
    for (kind, i), t in done.items():
        (done_site if kind == "s" else done_line)[i] = t
    # ── 5〜8: 直後の評価を 1 手ずつ ─────────────────────────
    bus_alive = ~(done_site > 0)[sim.bus_site]; br_alive = ~(done_line > 0); gen_ok = ~(done_gen > 0)
    gen_cap = sim._gen_cap(0.0, gen_ok); lf0 = sim._load_factor_from_I(I, 0.0) if hasattr(sim, "_load_factor_from_I") else None
    load0 = load.copy()
    steps_pf = _evaluate_steps(sim, bus_alive, br_alive, gen_cap, load0, I, zones, ev, lat, lon, site_name, brname, t_label="直後")
    served0, phys0, blackout = steps_pf
    # ── 9. 復旧の割当 ──────────────────────────────────────
    ev(9, 8, f"復旧ジョブ {len(jobs)} 件を並べる", "変電所と線路の停止をジョブにし、エリアごとに 電圧が高い順 → 需要が大きい順 に並べる。作業班: " + "、".join(f"{z} {c}" for z, c in rm.p["crews"]["base"].items() if z in set(sim.site_zone)) + "。3 日目から応援で 2 倍。")
    for a in assign[:max_jobs]:
        kind, i = a["id"]
        if kind == "s":
            nm = f"変電所 {site_name[sim.site_rows[i]]} ({int(sim.site_kv[i])} kV, 需要 {sim.site_load[i]:.0f} MW)"; hl = {"b": [int(x) for x in np.where(sim.bus_site == i)[0]]}; d = {"rest_site": {int(i): round(a["end"], 2)}}
        else:
            nm = f"線路 {brname[i][:24]} ({int(sim.br_kv[i])} kV)"; hl = {"l": [int(i)]}; d = {"rest_line": {int(i): round(a["end"], 2)}}
        ev(9, 8, f"[{a['zone']}] 班 {a['crew']+1} ← {nm}", f"開始 {a['start']:.1f} 日、修理 {a['dur']:.1f} 日 → 完了 {a['end']:.1f} 日。" + ("応援班。" if a.get("aid") else ""), hl=hl, delta=d)
    if len(assign) > max_jobs:
        rest = {"rest_site": {}, "rest_line": {}}
        for a in assign[max_jobs:]:
            kind, i = a["id"]; rest["rest_site" if kind == "s" else "rest_line"][int(i)] = round(a["end"], 2)
        ev(9, 8, f"ほか {len(assign) - max_jobs} 件を同じ規則で割当", f"最終完了 {max(a['end'] for a in assign):.0f} 日。", delta=rest)
    # ── 10. 時刻列で再評価 ─────────────────────────────────
    T = sim.timeline; labels = {0: "直後", 0.25: "6 時間", 0.5: "12 時間"}
    for t in T[1:]:
        site_ok = ~(done_site > t); ba = site_ok[sim.bus_site]; bra = ~(done_line > t); go = ~(done_gen > t)
        sim.cm.load = sim.load0 * sim._load_factor(_DS(I), t)
        r = cm.evaluate(ba, bra, sim._gen_cap(t, go))
        sim.cm.load = sim.load0
        out = r.served_frac.copy(); ph = r.connected.astype(float)
        bo = blackout > t; out[bo] = 0; ph[bo] = 0
        lab = labels.get(float(t), f"{t:g} 日")
        ev(10, 9, f"t = {lab}: 生存集合で再評価", f"受電可能 {float((ph*load).sum()/load.sum()):.0%}、供給率 {float((out*load).sum()/load.sum()):.0%}。停止中の変電所 {int((~site_ok & ~sim.site_is_junction).sum())}、線路 {int((~bra).sum())}、発電機 {int((~go & ~sim.gslack).sum())}、系統崩壊中 {float(load[bo].sum()/1000):.1f} GW。",
           delta={"state": [round(float(x), 2) for x in out], "phys": [int(x) for x in ph]}, t=float(t))
    return {"pseudo": PSEUDO, "steps": steps,
            "bus": {"lat": [round(float(x), 4) for x in lat], "lon": [round(float(x), 4) for x in lon], "load": [round(float(x), 1) for x in load], "name": [str(x)[:20] for x in bus_name], "junction": [int(x) for x in sim.junction]},
            "line": {"f": [int(x) for x in sim.bf], "t": [int(x) for x in sim.bt], "kv": [int(x) for x in sim.br_kv]},
            "gen": {"b": [int(x) for x in sim.gb], "p": [round(float(x), 1) for x in gp], "name": [str(x)[:20] for x in gname]},
            "timeline": [float(x) for x in T], "seed": seed, "island": case.island}


class _DS:
    def __init__(self, I):
        self.intensity = I


def _schedule_logged(rm, jobs, log):
    crews = dict(rm.p["crews"]["base"]); aid_f = float(rm.p["crews"].get("mutual_aid_factor", 1.0)); aid_t = float(rm.p["crews"].get("mutual_aid_start_d", 1e9))
    done = {}; by_zone = {}
    for j in jobs:
        by_zone.setdefault(j.get("zone") or "other", []).append(j)
    for zone, js in by_zone.items():
        js.sort(key=lambda j: (-float(j.get("kv", 0)), -float(j.get("load_mw", 0))))
        c = int(crews.get(zone, 10)); free = [(0.0, i) for i in range(c)]; heapq.heapify(free); aid_added = False; ncrew = c
        for j in js:
            t0, cid = heapq.heappop(free)
            if not aid_added and t0 >= aid_t:
                extra = int(c * (aid_f - 1.0))
                for e in range(extra):
                    heapq.heappush(free, (aid_t, ncrew + e))
                ncrew += extra; aid_added = True
                heapq.heappush(free, (t0, cid)); t0, cid = heapq.heappop(free)
            tend = t0 + float(j["duration_d"]); done[j["id"]] = tend
            log.append({"id": j["id"], "zone": zone, "crew": cid, "start": t0, "dur": float(j["duration_d"]), "end": tend, "aid": cid >= c})
            heapq.heappush(free, (tend, cid))
    return done


def _evaluate_steps(sim, bus_alive, br_alive, gen_cap, load0, I, zones, ev, lat, lon, site_name, brname, t_label="直後"):
    """5〜8 を 1 手ずつ記録しながら直後の状態を評価する(cascade.evaluate と同じ計算)。"""
    cm = sim.cm; n = cm.n
    lf = sim._load_factor(_DS(I), 0.0); load = load0 * lf
    bus_alive = bus_alive.copy(); br_alive = br_alive.copy()
    gen_cap = np.where(bus_alive[sim.gb], gen_cap, 0.0)
    # 5 連結成分
    lab = cm._components(bus_alive, br_alive); nc = lab.max() + 1
    L = np.bincount(lab, weights=np.where(bus_alive, load, 0.0), minlength=nc); G = np.bincount(lab[sim.gb], weights=gen_cap, minlength=nc)
    sl = sim.gslack & bus_alive[sim.gb] & cm.base_is_fragment[sim.gb]; Ginf = np.bincount(lab[sim.gb], weights=sl.astype(float), minlength=nc) > 0
    has = (G > 1e-6) | Ginf; iso = bus_alive & ~has[lab]
    sizes = np.bincount(lab)
    ev(5, 4, f"連結成分を計算: {nc} 成分", f"最大成分 {int(sizes.max())} 母線。生きているのに供給源の無い成分にある母線 = 上流孤立 {int(iso.sum())} 本(需要 {load[iso].sum():.0f} MW)。", hl={"b": [int(x) for x in np.where(iso)[0]]}, delta={"bus": {int(x): "I" for x in np.where(iso)[0]}})
    # 6 エリア需給
    bo = sim.rm.p.get("blackout") or {}; blackout = np.zeros(n)
    gz = zones[sim.gb].copy(); ovr = bo.get("supply_zone_override_by_pref") or {}
    if ovr:
        from .aggregate import bus_prefecture
        pref = bus_prefecture(sim.case)[sim.gb]
        for p_, z_ in ovr.items():
            gz[pref == p_] = z_
    hit = np.zeros(n, bool)
    for z in sorted(np.unique(zones)):
        mz = zones == z; Lz = float(np.where(bus_alive & mz, load, 0.0).sum()); Gz = float(np.where(bus_alive[sim.gb] & (gz == z), gen_cap, 0.0).sum())
        imp = float(bo.get("import_cap_mw", {}).get(z, 0.0)); dz = 1 - min(1.0, (Gz + imp) / max(Lz, 1e-9)) if Lz > 0 else 0.0
        h = dz > float(bo.get("deficit_threshold", 9)) and Lz >= float(bo.get("min_component_load_mw", 0))
        if h:
            hit |= mz
        ev(6, 5, f"エリア {z}: 不足率 {dz:.0%} → {'系統崩壊' if h else '維持'}", f"残存需要 {Lz/1000:.1f} GW、生存供給力 {Gz/1000:.1f} GW、連系線受電上限 {imp/1000:.1f} GW → δ = 1 − ({Gz/1000:.1f}+{imp/1000:.1f})/{Lz/1000:.1f} = {dz:.2f}。しきい値 0.25。",
           hl={"z": [z]}, delta=({"bus": {int(x): "B" for x in np.where(mz & bus_alive)[0]}} if h else {}))
    if hit.any():
        rng = np.random.default_rng(1000)
        ts = np.exp(np.log(bo["restore_h_median"]) + bo["restore_h_beta"] * rng.normal(size=len(sim.site_rows))) / 24.0
        blackout[hit] = ts[sim.bus_site[hit]]
    # 7 比例遮断
    ratio = np.where(Ginf, 1.0, np.where(L > 1e-6, np.minimum(1.0, G / np.maximum(L, 1e-9)), 1.0))
    served = np.where(bus_alive, load, 0.0) * ratio[lab]
    big = [c for c in np.argsort(-L)[:6] if L[c] > 100]
    for c in big:
        ev(7, 6, f"成分 {c}({int(sizes[c])} 母線): 需給比 r = min(1, {G[c]/1000:.1f}/{L[c]/1000:.1f}) = {ratio[c]:.2f}", ("供給が足りるので遮断なし。" if ratio[c] >= 0.999 else f"供給力不足 {(1-ratio[c]):.0%} を比例遮断(計画停電相当)。"), hl={"b": [int(x) for x in np.where((lab == c) & bus_alive)[0][:1500]]},
           delta={"shed": {int(x): round(float(ratio[c]), 2) for x in np.where((lab == c) & bus_alive)[0]}} if ratio[c] < 0.999 else {})
    # 8 DC潮流と過負荷連鎖
    it = 0; tripped_all = []
    while True:
        gen_scale = np.where(L > 1e-6, np.minimum(1.0, (L * ratio) / np.maximum(G, 1e-9)), 0.0)
        pinj = np.bincount(sim.gb, weights=gen_cap * gen_scale[lab[sim.gb]], minlength=n) - served
        flows = cm._dc_flows(lab, bus_alive, br_alive, pinj, Ginf)
        over = (np.abs(flows) > cm.cap * cm.overload_trip) & br_alive
        ol = np.where(over)[0]; ratio_ol = np.where(over, np.abs(flows) / cm.cap, 0.0)
        top = np.argsort(-ratio_ol)[:min(3, len(ol))] if len(ol) else []
        ev(8, 7, f"DC潮流を解く(反復 {it+1}): 過負荷 {len(ol)} 本", ("緊急定格(1.25×容量)を超える枝なし → 連鎖終了。" if len(ol) == 0 else f"最大 {ratio_ol.max():.0%} の負荷率。上位 3 本を停止する。"),
           hl={"l": [int(k) for k in ol[:200]]}, delta={"flow": {int(k): round(float(np.abs(flows[k]) / cm.cap[k]), 2) for k in ol[:400]}})
        if len(ol) == 0 or it >= cm.max_iter:
            break
        for k in top:
            br_alive[k] = False; tripped_all.append(int(k))
            ev(8, 7, f"枝 {brname[k][:26]} ({int(sim.br_kv[k])} kV) を停止: 負荷率 {ratio_ol[k]:.0%}", f"潮流 {abs(flows[k]):.0f} MW / 緊急定格 {cm.cap[k]*cm.overload_trip:.0f} MW。保護リレー(過電流・距離)の動作に相当。", hl={"l": [int(k)]}, delta={"line": {int(k): "X"}})
        it += 1
        lab = cm._components(bus_alive, br_alive); nc = lab.max() + 1
        L = np.bincount(lab, weights=np.where(bus_alive, load, 0.0), minlength=nc); G = np.bincount(lab[sim.gb], weights=gen_cap, minlength=nc)
        sl = sim.gslack & bus_alive[sim.gb] & cm.base_is_fragment[sim.gb]; Ginf = np.bincount(lab[sim.gb], weights=sl.astype(float), minlength=nc) > 0
        ratio = np.where(Ginf, 1.0, np.where(L > 1e-6, np.minimum(1.0, G / np.maximum(L, 1e-9)), 1.0)); served = np.where(bus_alive, load, 0.0) * ratio[lab]
        has = (G > 1e-6) | Ginf; iso2 = bus_alive & ~has[lab]
        ev(5, 4, f"連結成分を再計算: {nc} 成分", f"停止した枝で新たに孤立した母線 {int((iso2 & ~iso).sum())} 本。", hl={"b": [int(x) for x in np.where(iso2 & ~iso)[0]]}, delta={"bus": {int(x): "I" for x in np.where(iso2 & ~iso)[0]}})
        iso = iso2
    frac = np.where(load > 1e-9, served / np.maximum(load, 1e-9), np.where(bus_alive, 1.0, 0.0)); frac = np.clip(frac, 0, 1)
    phys = (bus_alive & has[lab]).astype(float)
    bo_m = blackout > 0; frac[bo_m] = 0; phys[bo_m] = 0
    ev(10, 9, f"t = {t_label}: 直後の状態", f"受電可能 {float((phys*load).sum()/load.sum()):.0%}、供給率 {float((frac*load).sum()/load.sum()):.0%}。連鎖で停止した枝 {len(tripped_all)} 本。", delta={"state": [round(float(x), 2) for x in frac], "phys": [int(x) for x in phys]}, t=0.0)
    return frac, phys, blackout
