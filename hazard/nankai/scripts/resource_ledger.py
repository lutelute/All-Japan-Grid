#!/usr/bin/env python3
"""復旧の資源勘定(人・日/資材/電源車)を N サンプル平均で出す。

    PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/resource_ledger.py --samples 20 --out <run_dir> [--island west]
"""
from __future__ import annotations
import argparse, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import numpy as np, pandas as pd
from nankai.grid import GridCase
from nankai.montecarlo import Simulator
from nankai.trace import _schedule_logged
from nankai.resources import ledger, plot_ledger, load_resource_params


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--samples", type=int, default=20); ap.add_argument("--out", required=True); ap.add_argument("--island", default="west"); a = ap.parse_args()
    case = GridCase.load(a.island); sim = Simulator(case); rng = np.random.default_rng(21); P = load_resource_params()
    days = [0, 1, 2, 3, 4, 5, 7, 10, 14, 21, 30, 45, 60, 90]
    acc = None; mats = {}; tf_need = []; pd_tot = []; njobs = []
    zones_bus = case.bus.zone.to_numpy()
    for s in range(a.samples):
        d = sim.damage(rng); d.blackout_until = sim._blackout(d, rng)
        # damage() が持つジョブ(実際の修理時間)を同じ優先規則で割り当て直し、開始/終了を得る
        assign = []; _schedule_logged(sim.rm, [dict(j) for j in d.jobs], assign)
        iso = {}
        for t in days:
            site_ok = ~(d.done_site > t); ba = site_ok[sim.bus_site]; bra = ~(d.done_line > t); go = ~(d.done_gen > t)
            r = sim.cm.evaluate(ba, bra, sim._gen_cap(t, go), run_pf=False)
            m = ba & ~r.connected & ~(d.blackout_until > t)
            iso[float(t)] = {z: float(sim.cm.load[m & (zones_bus == z)].sum()) for z in np.unique(zones_bus)}
        L = ledger(sim, assign, d.site_ds, d.site_cause, d.line_cause, iso, days=days, params=P)
        if acc is None:
            acc = {"persons": {z: np.zeros(len(days)) for z in L["zones"]}, "trucks_need": {z: np.zeros(len(days)) for z in L["zones"]}, "trucks_avail": L["trucks_avail"], "zones": L["zones"], "days": L["days"], "transformer_stock": L["transformer_stock"]}
        for z in L["zones"]:
            acc["persons"][z] += L["persons"][z] / a.samples; acc["trucks_need"][z] += L["trucks_need"][z] / a.samples
        for m, q in L["materials"].items():
            mats[m] = mats.get(m, 0) + q / a.samples
        tf_need.append(L["transformer_need"]); pd_tot.append(L["person_days_total"]); njobs.append(L["n_jobs"])
    acc["materials"] = mats; acc["transformer_need"] = float(np.mean(tf_need)); acc["person_days_total"] = float(np.mean(pd_tot)); acc["n_jobs"] = float(np.mean(njobs)); acc["person_days_cum"] = {}
    os.makedirs(a.out, exist_ok=True)
    plot_ledger(acc, os.path.join(a.out, "resource_ledger.png"), title=f"復旧の資源勘定({a.island}・N={a.samples} 平均)")
    rows = [{"day": float(t), **{f"persons_{z}": float(acc['persons'][z][k]) for z in acc["zones"]}, **{f"trucks_need_{z}": float(acc['trucks_need'][z][k]) for z in acc["zones"]}, **{f"trucks_avail_{z}": float(acc['trucks_avail'][z][k]) for z in acc["zones"]}} for k, t in enumerate(days)]
    pd.DataFrame(rows).to_csv(os.path.join(a.out, "resource_ledger.csv"), index=False)
    json.dump({"materials_mean": mats, "transformer_need_mean": acc["transformer_need"], "transformer_stock": acc["transformer_stock"], "person_days_total_mean": acc["person_days_total"], "n_jobs_mean": acc["n_jobs"],
               "peak_persons": {z: float(acc["persons"][z].max()) for z in acc["zones"]}, "peak_trucks_need": {z: float(acc["trucks_need"][z].max()) for z in acc["zones"]}}, open(os.path.join(a.out, "resource_ledger.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps({"person_days_total": round(acc["person_days_total"]), "n_jobs": round(acc["n_jobs"]), "transformers": round(acc["transformer_need"], 1), "stock": acc["transformer_stock"], "peak_persons": {z: round(acc["persons"][z].max()) for z in acc["zones"]}, "peak_trucks": {z: round(acc["trucks_need"][z].max()) for z in acc["zones"]}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
