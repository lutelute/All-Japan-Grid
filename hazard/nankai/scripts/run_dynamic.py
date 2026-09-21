#!/usr/bin/env python3
"""動的カスケード(揺れの到達 → 発電機停止 → 周波数 → リレー → 系統分離 → 停電)のモンテカルロ。

    PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/run_dynamic.py --islands west east --samples 200 --workers 10 \
        --out hazard/nankai/output/run_v2_dyn

run_v1(静的: エリアの供給不足率 25% 超で全停)との違い:
  - 直後の停電を「いつ・なぜ」まで時刻つきで解く(record_times_s: 0 秒〜3 時間)
  - エリア全停の規則を使わず、周波数崩壊した島の母線にだけ復電時刻(restoration_default.yaml blackout.restore_h_*)を付けて
    90 日の復旧時系列(Simulator.evaluate_timeline)につなぐ
出力(島ごと): run_v1 と同じ bus_results.parquet(phys_t* / served_t*)に dyn_* 列を追加、dyn_samples.csv(サンプル × 時刻の
MW 内訳と島の数)、dyn_summary.csv(時刻ごとの平均と分位)、timeline_summary.csv / sample_timeline.csv / meta.json
"""
from __future__ import annotations
import argparse, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import numpy as np, pandas as pd, yaml
from multiprocessing import get_context

NANKAI = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
G = {}


def init(island, seed, overrides=None):
    import arrival_physics as ap
    from nankai.grid import GridCase
    from nankai.montecarlo import Simulator
    from nankai.dyn_cascade import DynCascade
    cfg = yaml.safe_load(open(os.path.join(NANKAI, "config", "dynamics_default.yaml"), encoding="utf-8"))
    for k, v in (overrides or {}).items():                 # 感度計算: "relays.overload_min_kv=275" など
        node = cfg
        keys = k.split(".")
        for kk in keys[:-1]:
            node = node[kk]
        node[keys[-1]] = yaml.safe_load(v)
    case = GridCase.load(island)
    go = cfg.get("grid_overrides", {}).get("tepco_transformer_capacity", {})
    led = None
    zones = {"east": ["tokyo"], "west": ["chubu"]}.get(island, [])
    zones = [z for z in zones if z in (go.get("zones") or ["tokyo", "chubu"])]
    if zones and go.get("enabled", False):                            # 公表台帳で変圧器容量を置き換え(grid_overrides.py)
        from nankai.grid_overrides import apply_transformer_capacity
        db = os.environ.get("HAZARD_SUPPORT_DB") or os.path.join(NANKAI, go["db"])
        led = pd.concat([apply_transformer_capacity(case, db, zone=z, scale_impedance=bool(go.get("scale_impedance", True))).assign(zone=z) for z in zones], ignore_index=True)
        if led.empty:
            raise SystemExit(f"grid_overrides.tepco_transformer_capacity が有効なのに台帳が読めない: {db}\n"
                             "  補助 DB(pws-160core ~/agj-hazard-data/hazard_support.sqlite・nas03 db/)を HAZARD_SUPPORT_DB で指すか、"
                             "--set grid_overrides.tepco_transformer_capacity.enabled=false で前の版(run_v4_red)と同じにする")
    adds = (cfg.get("branch_additions") or {}).get("value", []) or []   # 感度: 系統図にある経路を直結で足す(OSM の経路が別の変電所を経由している場合)
    if adds:
        names = case.bus.name.astype(str).to_numpy(); la, lo = case.bus.lat.to_numpy(float), case.bus.lon.to_numpy(float)
        rows = []
        for a in adds:
            fi, ti, lf, lt = (int(np.where(names == a[k])[0][0]) for k in ("f", "t", "like_f", "like_t"))
            bb = case.branch
            tpl = bb[((bb.f == lf) & (bb.t == lt)) | ((bb.f == lt) & (bb.t == lf))].iloc[0].copy()
            L = float(np.hypot((lo[fi] - lo[ti]) * 111.32 * np.cos(np.radians(la[fi])), (la[fi] - la[ti]) * 110.57))
            par = int(a.get("parallel", tpl["parallel"]))          # 回線数(公表の線路名 1･2L 等)。x は並列数に反比例、容量は比例
            tpl["x_pu"] = float(tpl["x_pu"]) * L / max(float(tpl["length_km"]), 1e-3) * int(tpl["parallel"]) / par
            tpl["cap_mw"] = float(tpl["cap_mw"]) * par / int(tpl["parallel"]); tpl["parallel"] = par; tpl["length_km"] = L
            tpl["f"], tpl["t"] = fi, ti; tpl["f_bus"], tpl["t_bus"] = case.bus.bus_id.iloc[fi], case.bus.bus_id.iloc[ti]
            tpl["name"] = a.get("name", f"{a['f']}-{a['t']}"); tpl["branch_id"] = int(bb.branch_id.max()) + 1 + len(rows)
            tpl["mid_lat"], tpl["mid_lon"] = (la[fi] + la[ti]) / 2, (lo[fi] + lo[ti]) / 2
            rows.append(tpl)
        case.branch = pd.concat([case.branch, pd.DataFrame(rows)], ignore_index=True)
        G["branch_additions"] = [(a["f"], a["t"]) for a in adds]
    rms = (cfg.get("branch_removals") or {}).get("value", []) or []   # 感度: OSM で付け替わった経路を外す(branch_additions の後に実行=雛形が残っているうちに張り直す)
    if rms:
        names = case.bus.name.astype(str).to_numpy(); bb = case.branch
        drop = np.zeros(len(bb), bool)
        for r in rms:
            fi = int(np.where(names == r["f"])[0][0]); ti = int(np.where(names == r["t"])[0][0])
            drop |= ((bb.f == fi) & (bb.t == ti)) | ((bb.f == ti) & (bb.t == fi))
        case.branch = bb[~drop].reset_index(drop=True)
        G["branch_removals"] = [(r["f"], r["t"]) for r in rms]; G["branch_removed_n"] = int(drop.sum())
    sim = Simulator(case, network=cfg.get("network", {}).get("model", "mesh"))
    G["override_ledger"] = led
    boxes = cfg.get("tsunami_exclude_boxes", {}).get("value", []) or []     # 感度: 箱の中の母線は津波の被害を 0 にする(A40 の波源が南海トラフでない海岸)
    if boxes:
        lat, lon = case.bus.lat.to_numpy(float), case.bus.lon.to_numpy(float)
        m = np.zeros(case.n_bus, bool)
        for bx in boxes:
            m |= (lat >= bx[0]) & (lat <= bx[1]) & (lon >= bx[2]) & (lon <= bx[3])
        sim.bus_ts = np.where(m, 0, sim.bus_ts)
        sim.site_ts = np.zeros(len(sim.site_rows), int); np.maximum.at(sim.site_ts, sim.bus_site, sim.bus_ts)
        sim.br_ts = np.maximum(sim.bus_ts[sim.bf], sim.bus_ts[sim.bt]); sim.gen_ts = sim.bus_ts[sim.gb]
        G["tsunami_excluded_buses"] = int(m.sum())
    if (cfg.get("tsunami_site_rank") or {}).get("mode", "max") == "representative":   # 感度: サイトの浸水深を最高電圧の母線の地点の値にする(既定はサイト内の最大)
        kv = case.bus.kv.to_numpy(float); rep = sim.site_rows.copy()
        for si in range(len(sim.site_rows)):
            m = np.where(sim.bus_site == si)[0]; rep[si] = m[np.argmax(kv[m])]
        sim.site_ts = sim.bus_ts[rep]
    fo = cfg.get("fragility_overrides") or {}                             # 感度: 脆弱性の値を部分的に上書き
    if fo:
        def _merge(dst, src):
            for k, v in src.items():
                if isinstance(v, dict) and isinstance(dst.get(k), dict):
                    _merge(dst[k], v)
                else:
                    dst[k] = v
        _merge(sim.fm.p, fo)
    ts = ap.point_s_arrival_s(case.bus.lat.values, case.bus.lon.values)
    tt = ap.point_tsunami_arrival_s(case.bus.lat.values, case.bus.lon.values, inland_km_per_min=float(cfg["tsunami_timing"]["inland_km_per_min"]))
    G.update(sim=sim, dc=DynCascade(sim, cfg, ts, tt), cfg=cfg, seed=seed)


def one(s):
    sim, dc, seed = G["sim"], G["dc"], G["seed"]
    rng = np.random.default_rng([seed, s])
    d = sim.damage(rng)
    r = dc.run(d, rng)
    # 周波数崩壊した島の母線に、サイトごとの復電時刻を付ける(静的な「供給不足 25%」規則の置き換え)
    bo = sim.rm.p["blackout"]
    until = np.zeros(sim.case.n_bus)
    cb = r["collapsed_bus"]
    if cb.any():
        tsite = np.exp(np.log(bo["restore_h_median"]) + bo["restore_h_beta"] * rng.normal(size=len(sim.site_rows))) / 24.0
        until[cb] = tsite[sim.bus_site[cb]]
    d.blackout_until = until
    served, phys, info = sim.evaluate_timeline(d)
    for row in info:
        row["sample"] = s
    rec = {k: r[k] for k in ("t", "energized_mw", "n_islands", "n_islands_100mw", "n_islands_1gw", "shed_mw", "collapsed_mw", "isolated_mw", "site_out_mw", "f_min", "f_max")}
    return dict(s=s, bus_state=r["bus_state"].astype(np.float16), collapsed=cb, isolated=r["isolated_bus"], site_out=r["site_out_bus"],
                served=served.astype(np.float16), phys=phys.astype(np.float16), info=info, rec=rec,
                site_fail=(d.done_site > 0), line_fail=d.line_fail.copy(), gen_fail=(d.done_gen > 0), intensity=d.intensity.astype(np.float32),
                n_log={k: int(v) for k, v in pd.Series([e[1] for e in r["log"]]).value_counts().items()})


def run_island(island, n, workers, seed, out, overrides=None):
    t0 = time.time()
    ctx = get_context("spawn")                  # macOS では数値計算ライブラリ読込後の fork が固まる(1 回踏んだ)
    init(island, seed, overrides)               # 親でも持つ(保存用)
    sim, cfg = G["sim"], G["cfg"]
    nb = sim.case.n_bus; T = sim.timeline; TD = np.array(cfg["record_times_s"], float)
    acc_dyn = np.zeros((len(TD), nb)); acc_srv = np.zeros((len(T), nb)); acc_phys = np.zeros((len(T), nb)); acc_srv_sq = np.zeros((len(T), nb)); acc_srv_out = np.zeros((len(T), nb))
    acc_col = np.zeros(nb); acc_iso = np.zeros(nb); acc_site = np.zeros(nb); acc_int = np.zeros(nb)
    site_fail = np.zeros(len(sim.site_rows)); line_fail = np.zeros(len(sim.bf)); gen_fail = np.zeros(len(sim.gb))
    rows = []; drows = []; logs = []
    with ctx.Pool(workers, initializer=init, initargs=(island, seed, overrides)) as pool:
        for k, r in enumerate(pool.imap_unordered(one, range(n), chunksize=1)):
            acc_dyn += r["bus_state"]; acc_srv += r["served"]; acc_srv_sq += r["served"].astype(float) ** 2; acc_phys += r["phys"]; acc_srv_out += (r["served"] < 0.5)
            acc_col += r["collapsed"]; acc_iso += r["isolated"]; acc_site += r["site_out"]; acc_int += r["intensity"]
            site_fail += r["site_fail"]; line_fail += r["line_fail"]; gen_fail += r["gen_fail"]
            rows.extend(r["info"])
            rec = r["rec"]
            for i, t in enumerate(rec["t"]):
                drows.append({"sample": r["s"], "t_s": float(t), **{kk: float(rec[kk][i]) for kk in rec if kk != "t"}})
            logs.append({"sample": r["s"], **r["n_log"]})
            if (k + 1) % 10 == 0 or k + 1 == n:
                print(f"  {island} {k+1}/{n}  {time.time()-t0:.0f}s", flush=True)
    N = float(n)
    res = {"served_mean": acc_srv / N, "served_std": np.sqrt(np.maximum(acc_srv_sq / N - (acc_srv / N) ** 2, 0)), "p_outage": acc_srv_out / N,
           "phys_mean": acc_phys / N, "p_outage_phys": 1 - acc_phys / N, "site_pfail": site_fail / N, "line_pfail": line_fail / N, "gen_pfail": gen_fail / N,
           "intensity_mean": acc_int / N, "samples": pd.DataFrame(rows), "n": n}
    od = os.path.join(out, island)
    bus, summ = sim.save(res, od)
    led = G.get("override_ledger")
    if led is not None and len(led):                                # 帳簿は output/(git 管理外)にだけ置く。台帳の生値を含むため
        led.to_csv(os.path.join(od, "grid_override_ledger.csv"), index=False)
    sp = G["sim"].fm.p["substation"]["tsunami"]                      # 帳簿: 17 万 V 以上の浸水対策(protected_kv_min)を受けたサイト
    if sp.get("protected_kv_min") is not None:
        sim0 = G["sim"]; kvm = float(sp["protected_kv_min"]); fac = float(sp.get("protected_factor", 0.0))
        m = (sim0.site_kv >= kvm) & (sim0.site_ts >= 1)
        if m.any():
            pf0 = np.array([float(sp["pfail_by_rank"].get(int(r), 0.0)) for r in sim0.site_ts[m]])
            pd.DataFrame({"site": sim0.case.bus.name.to_numpy()[sim0.site_rows[m]], "zone": sim0.site_zone[m],
                          "kv": sim0.site_kv[m], "tsunami_rank": sim0.site_ts[m], "pfail_before": pf0,
                          "pfail_after": pf0 * fac}).to_csv(os.path.join(od, "tsunami_site_ledger.csv"), index=False)
    for i, t in enumerate(TD):
        bus[f"dyn_energized_t{int(t)}s"] = acc_dyn[i] / N
    bus["p_collapse"] = acc_col / N; bus["p_isolated_dyn"] = acc_iso / N; bus["p_site_out_dyn"] = acc_site / N
    bus.to_parquet(os.path.join(od, "bus_results.parquet"), index=False)
    ds = pd.DataFrame(drows); ds.to_csv(os.path.join(od, "dyn_samples.csv"), index=False)
    L = float(sim.cm.load.sum())
    agg = ds.groupby("t_s").agg(energized_mw=("energized_mw", "mean"), energized_p10=("energized_mw", lambda x: np.quantile(x, 0.1)), energized_p90=("energized_mw", lambda x: np.quantile(x, 0.9)),
                                shed_mw=("shed_mw", "mean"), collapsed_mw=("collapsed_mw", "mean"), isolated_mw=("isolated_mw", "mean"), site_out_mw=("site_out_mw", "mean"),
                                p_collapse_any=("collapsed_mw", lambda x: float((x > 1000).mean())),
                                n_islands_mean=("n_islands", "mean"), n_islands_p50=("n_islands", "median"), n_islands_p90=("n_islands", lambda x: np.quantile(x, 0.9)), n_islands_max=("n_islands", "max"),
                                n_100mw_mean=("n_islands_100mw", "mean"), n_100mw_max=("n_islands_100mw", "max"), n_1gw_mean=("n_islands_1gw", "mean"), n_1gw_max=("n_islands_1gw", "max"),
                                f_min_p10=("f_min", lambda x: np.nanquantile(x, 0.1)), f_min_p50=("f_min", lambda x: np.nanquantile(x, 0.5))).reset_index()
    agg["load_mw"] = L; agg["energized_frac"] = agg.energized_mw / L
    agg.to_csv(os.path.join(od, "dyn_summary.csv"), index=False)
    pd.DataFrame(logs).fillna(0).to_csv(os.path.join(od, "dyn_event_counts.csv"), index=False)
    meta = json.load(open(os.path.join(od, "meta.json")))
    meta.update({"mode": "dynamic", "record_times_s": TD.tolist(), "seed": seed, "workers": workers, "elapsed_s": round(time.time() - t0, 1),
                 "config": "config/dynamics_default.yaml", "overrides": overrides or {},
                 "grid_override": ({"n_branches": int(len(led)), "cap_old_mw": round(float(led.cap_old.sum())), "cap_new_mw": round(float(led.cap_new.sum()))} if led is not None and len(led) else None), "blackout_rule": "周波数崩壊した島の母線のみ(静的な供給不足 25% 規則は不使用)"})
    json.dump(meta, open(os.path.join(od, "meta.json"), "w"), ensure_ascii=False, indent=1)
    print(f"{island}: done {time.time()-t0:.0f}s")
    print(agg[["t_s", "energized_frac", "shed_mw", "collapsed_mw", "isolated_mw", "site_out_mw", "n_islands_mean", "n_islands_p90", "n_islands_max", "n_100mw_mean", "n_1gw_mean", "f_min_p10", "f_min_p50", "p_collapse_any"]].round(3).to_string(index=False))


def main():
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--islands", nargs="+", default=["west", "east"]); ap_.add_argument("--samples", type=int, default=200)
    ap_.add_argument("--workers", type=int, default=10); ap_.add_argument("--seed", type=int, default=0); ap_.add_argument("--out", required=True)
    ap_.add_argument("--set", nargs="*", default=[], help='設定の上書き(感度計算) 例: relays.overload_min_kv=275 relays.overload_enabled=false')
    a = ap_.parse_args()
    ov = dict(x.split("=", 1) for x in a.set)
    for isl in a.islands:
        run_island(isl, a.samples, a.workers, a.seed, a.out, ov)


if __name__ == "__main__":
    main()
