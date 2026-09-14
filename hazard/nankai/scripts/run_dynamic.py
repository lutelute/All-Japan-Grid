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
    case = GridCase.load(island); sim = Simulator(case, network=cfg.get("network", {}).get("model", "mesh"))
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
                 "config": "config/dynamics_default.yaml", "overrides": overrides or {}, "blackout_rule": "周波数崩壊した島の母線のみ(静的な供給不足 25% 規則は不使用)"})
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
