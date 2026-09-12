#!/usr/bin/env python3
"""南海トラフ地震 電力ハザードマップ — 一括実行。

    PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/run_pipeline.py \
        --islands west east --samples 200 --seed 0 --out hazard/nankai/output/run_YYYYMMDD

出力(島ごと): bus_results / branch_results / gen_results (parquet), timeline_summary.csv,
  potential.parquet, hazard.png, pout_t*.png, potential.png, curve.png, restoration.gif,
  municipalities.geojson(行政界があれば), summary.json
"""
from __future__ import annotations
import argparse, json, os, shutil, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import numpy as np, pandas as pd, yaml

from nankai.grid import GridCase
from nankai.montecarlo import Simulator
from nankai.hazard_field import default_field, TsunamiField, GMPEField, MeshField
from nankai.potential import potential_index
from nankai import maps
from nankai.aggregate import to_municipalities, bus_prefecture, naikakufu_region_of, customers_per_mw

NANKAI = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--islands", nargs="*", default=["west", "east"])
    ap.add_argument("--samples", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=os.path.join(NANKAI, "output", time.strftime("run_%Y%m%d_%H%M")))
    ap.add_argument("--field", choices=["auto", "gmpe", "mesh"], default="auto")
    ap.add_argument("--no-tsunami", action="store_true")
    ap.add_argument("--no-gif", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    scenario = yaml.safe_load(open(os.path.join(NANKAI, "config", "scenario_nankai.yaml"), encoding="utf-8"))
    summary = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "samples": a.samples, "seed": a.seed, "islands": {}}
    ts = TsunamiField() if not a.no_tsunami else None
    for isl in a.islands:
        t0 = time.time()
        od = os.path.join(a.out, isl); os.makedirs(od, exist_ok=True)
        case = GridCase.load(isl)
        field = default_field(prefer_mesh=(a.field != "gmpe")) if a.field != "mesh" else default_field(True)
        sim = Simulator(case, field=field, tsunami=ts, use_tsunami=not a.no_tsunami)
        print(f"[{isl}] buses={case.n_bus} load={sim.cm.load.sum():.0f}MW field={getattr(field,'name','gmpe')} tsunami={sim.ts.available and not a.no_tsunami}", flush=True)
        res = sim.run(a.samples, seed=a.seed)
        bus, summ = sim.save(res, od)
        # ポテンシャル法(中央値場)
        hs = sim.field.sample(sim.lat, sim.lon, randomize=False)
        pot = potential_index(sim, hs, horizon="day2")
        pot_im = potential_index(sim, hs, horizon="immediate")
        pot["potential_pout_immediate"] = pot_im.potential_pout.values
        pot.to_parquet(os.path.join(od, "potential.parquet"), index=False)
        m = bus.merge(pot, on="bus_id")
        w = m.pd_mw.values
        def wcorr(x, y):
            xm = np.average(x, weights=w); ym = np.average(y, weights=w)
            return float(np.sum(w * (x - xm) * (y - ym)) / np.sqrt(np.sum(w * (x - xm) ** 2) * np.sum(w * (y - ym) ** 2)))
        comp = {"corr_pout_t0": float(np.corrcoef(m.potential_pout_immediate, m.pout_t0)[0, 1]),
                "corr_pout_t2": float(np.corrcoef(m.potential_pout, m.pout_t2)[0, 1]),
                "corr_pout_t7": float(np.corrcoef(m.potential_pout, m.pout_t7)[0, 1]),
                "wcorr_pout_t2": wcorr(m.potential_pout.values, m.pout_t2.values),
                "corr_expected_days": float(np.corrcoef(m.potential_pout, m.expected_outage_days)[0, 1])}
        # 地図
        ext = maps.EXTENT_WEST if isl == "west" else (134.5, 141.5, 33.5, 38.5)
        fname = getattr(field, "name", "gmpe")
        maps.hazard_map(bus, os.path.join(od, "hazard.png"), scenario=scenario, extent=ext,
                        title=("想定震度(J-SHIS 南海トラフ最大クラス Mw9.1・計測震度期待値, 空間相関ノイズ込み平均)" if fname != "gmpe" else "想定震度(近似震源域+司・翠川式の合成場, 平均)"))
        for t in (0, 1, 4, 7, 30):
            if f"pout_phys_t{t}" in bus:
                lab = "直後" if t == 0 else f"{t}日後"
                row = summ[summ.t_days == t].iloc[0]
                maps.outage_map(bus, f"pout_phys_t{t}", os.path.join(od, f"pout_t{t}.png"), f"解析ベース 停電確率(物理) {lab} (N={a.samples})", extent=ext,
                                note=f"受電可能 {float(row.phys_frac):.0%} / 供給率 {float(row.served_frac):.0%}")
        maps.outage_map(bus, "expected_outage_days_phys", os.path.join(od, "expected_days.png"), "期待停電日数(物理; 0〜90日の積分)", extent=ext,
                        vmin=0, vmax=float(np.quantile(bus.expected_outage_days_phys, 0.98)), label="日", cmap="viridis_r")
        # 内閣府2013 五地域比較(物理停電の軒数)
        try:
            tg = yaml.safe_load(open(os.path.join(NANKAI, "config", "calibration_targets.yaml"), encoding="utf-8"))["naikakufu_2013"]["outage_households"]
            targets = {"基本": {r: tg["①東海_基本"][r] for r in ("tokai", "kinki", "sanyo", "shikoku", "kyushu")},
                       "陸側": {r: tg["①東海_陸側"][r] for r in ("tokai", "kinki", "sanyo", "shikoku", "kyushu")}}
            reg = naikakufu_region_of(bus_prefecture(case)); cpm = customers_per_mw(bus.groupby("zone").pd_mw.sum().to_dict())
            cust = bus.pd_mw.to_numpy() * bus.zone.map(cpm).fillna(0).to_numpy()
            ours = {}
            for t in (0, 1, 4, 7):
                for r in ("tokai", "kinki", "sanyo", "shikoku", "kyushu"):
                    m_ = reg == r
                    ours[(r, t)] = float(((1 - bus[f"phys_t{t}"].to_numpy()[m_]) * cust[m_]).sum())
            summary.setdefault("naikakufu_compare", {})[isl] = {f"{r}_t{t}": round(v) for (r, t), v in ours.items()}
            maps.naikakufu_comparison_png(ours, targets, os.path.join(od, "naikakufu_compare.png"), title=f"内閣府2013想定との比較({isl}; 五地域・停電軒数)")
        except Exception as e:  # noqa: BLE001
            print("  naikakufu compare skipped:", e)
        maps.outage_map(m, "potential_pout", os.path.join(od, "potential.png"), "ポテンシャル法 停電指標(損傷のみ・復旧期)", extent=ext)
        maps.outage_map(m, "potential_pout_immediate", os.path.join(od, "potential_immediate.png"), "ポテンシャル法 停電指標(直後・トリップ含む)", extent=ext)
        maps.restoration_curve_png(summ, os.path.join(od, "curve.png"))
        if not a.no_gif:
            maps.restoration_gif(bus, sim.timeline, os.path.join(od, "restoration.gif"), summ=summ, extent=ext)
            shutil.rmtree(os.path.join(od, "restoration.gif.frames"), ignore_errors=True)
        # 自治体集約
        mu = to_municipalities(bus, sim.timeline)
        muni_stats = None
        if mu is not None:
            mu.to_file(os.path.join(od, "municipalities.geojson"), driver="GeoJSON")
            try:
                maps.html_map(os.path.join(od, "municipalities.geojson"), bus, sim.timeline, os.path.join(od, "hazard_map.html"), title=f"南海トラフ地震 電力ハザードマップ ({isl})")
            except Exception as e:  # noqa: BLE001
                print("  html map skipped:", e)
            mu.drop(columns="geometry").to_csv(os.path.join(od, "municipalities.csv"), index=False)
            muni_stats = {"n_muni": int(len(mu)), "outage_customers_t0": float(mu.outage_customers_t0.sum()),
                          "outage_customers_t1": float(mu.outage_customers_t1.sum()), "outage_customers_t7": float(mu.outage_customers_t7.sum()),
                          "outage_customers_t30": float(mu.outage_customers_t30.sum()), "note": "outage_customers は供給率(供給力不足込み)ベース"}
        summary["islands"][isl] = {"n_bus": case.n_bus, "load_mw": float(sim.cm.load.sum()), "field": getattr(field, "name", "gmpe"),
                                   "tsunami": bool(sim.ts.available and not a.no_tsunami), "buses_in_tsunami_zone": int((sim.bus_ts > 0).sum()),
                                   "timeline": summ[["t_days", "served_frac", "sites_out", "lines_out", "gens_out", "gen_cap_mw"]].round(3).to_dict("records"),
                                   "potential_vs_analysis": comp, "municipalities": muni_stats, "elapsed_s": round(time.time() - t0, 1)}
        print(f"[{isl}] done {time.time()-t0:.0f}s  served@0={summ.served_frac.iloc[0]:.2f} @1d={float(summ[summ.t_days==1].served_frac.iloc[0]):.2f} @7d={float(summ[summ.t_days==7].served_frac.iloc[0]):.2f}  corr(pot,t2)={comp['corr_pout_t2']:.2f}", flush=True)
    json.dump(summary, open(os.path.join(a.out, "summary.json"), "w"), ensure_ascii=False, indent=1)
    print("->", a.out)


if __name__ == "__main__":
    main()
