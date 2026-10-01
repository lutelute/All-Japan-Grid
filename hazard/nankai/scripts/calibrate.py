#!/usr/bin/env python3
"""較正スイープ: 主要パラメータを振って直後の停電軒数と復旧曲線を較正目標と比べる。

    PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/calibrate.py --samples 20 --out hazard/nankai/output/calib

出力: calib_table.csv(各変種の served@t と 停電軒数@0), 目標は config/calibration_targets.yaml(あれば)。
"""
from __future__ import annotations
import argparse, copy, itertools, json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import numpy as np, pandas as pd, yaml
from nankai.grid import GridCase
from nankai.montecarlo import Simulator
from nankai.fragility import FragilityModel, load_params, _deep_update
from nankai.restoration import RestorationModel, load_restoration_params
from nankai.hazard_field import TsunamiField, default_field, GMPEField
from nankai.aggregate import customers_per_mw, bus_prefecture, naikakufu_region_of

NANKAI = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

VARIANTS = {
    "field": ["jshis", "gmpe"],                # 地震動場
    "sub_model": ["hazus3", "hazus5", "jma"],  # 変電所: HAZUS×3 / HAZUS×5 / 震度階級表(機能停止≥1日)
    "p_out_mod": [0.3],                        # moderate で停電する確率
    "blackout_th": [0.15, 0.35],               # zone 供給不足しきい値
    "crew_x": [1.0, 2.0],                      # 作業班倍率
    "repair_x": [1.0],                         # 修理時間中央値倍率
}
TARGET_T = [0, 1, 4, 7]


def make_models(v):
    fp = load_params("fragility"); rp = load_restoration_params()
    sm = v.get("sub_model", "hazus3")
    if sm == "jma":
        fp["substation"]["model"] = "jma_table"
    else:
        fp["substation"]["model"] = "hazus"; fp["substation"]["japan_adjustment"] = float(sm.replace("hazus", ""))
    if "sub_adj" in v:
        fp["substation"]["japan_adjustment"] = v["sub_adj"]
    fp["substation"]["p_out_by_ds"][2] = v["p_out_mod"]
    if "blackout_th" in v and rp.get("blackout"):
        rp["blackout"]["deficit_threshold"] = v["blackout_th"]
    for z in rp["crews"]["base"]:
        rp["crews"]["base"][z] = int(rp["crews"]["base"][z] * v["crew_x"])
    for k in ("substation", "line"):
        for d, r in rp[k]["ds"].items():
            r["median_d"] = r["median_d"] * v["repair_x"]
    return FragilityModel(fp), RestorationModel(rp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="*", default=["west"])
    ap.add_argument("--samples", type=int, default=20)
    ap.add_argument("--out", default=os.path.join(NANKAI, "output", "calib"))
    ap.add_argument("--grid", default=None, help="JSON: 変種の辞書(既定は VARIANTS)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    grid = json.loads(a.grid) if a.grid else VARIANTS
    keys = list(grid)
    ts = TsunamiField()
    rows = []
    cases = {isl: GridCase.load(isl) for isl in a.islands}
    for vals in itertools.product(*[grid[k] for k in keys]):
        v = dict(zip(keys, vals)); fm, rm = make_models(v)
        row = {**v, "n": a.samples}; t0 = time.time()
        reg_out = {}
        for isl, case in cases.items():
            zl = case.bus.groupby("zone").pd_mw.sum().to_dict(); cpm = customers_per_mw(zl)
            cust = case.bus.pd_mw.to_numpy() * case.bus.zone.map(cpm).fillna(0).to_numpy()
            reg = naikakufu_region_of(bus_prefecture(case))
            field = GMPEField() if v.get("field") == "gmpe" else default_field(True)
            sim = Simulator(case, field=field, tsunami=ts, fragility=fm, restoration=rm)
            res = sim.run(a.samples, seed=0, progress=False)
            for ti, t in enumerate(sim.timeline):
                if t in (0, 0.5, 1, 2, 3, 4, 7, 14, 30, 60, 90):
                    row[f"{isl}_served_{t:g}"] = float((res["served_mean"][ti] * sim.cm.load).sum() / sim.cm.load.sum())
                if t in TARGET_T:
                    for r in ("tokai", "kinki", "sanyo", "shikoku", "kyushu"):
                        m = reg == r
                        reg_out[(r, t)] = reg_out.get((r, t), 0.0) + float(((1 - res["phys_mean"][ti][m]) * cust[m]).sum())
                        reg_out[(r + "_tot", t)] = reg_out.get((r + "_tot", t), 0.0) + float(((1 - res["served_mean"][ti][m]) * cust[m]).sum())
            row[f"{isl}_blackout_mw_0"] = float(res["samples"].query("t_days==0").blackout_mw.mean())
            row[f"{isl}_sites_pfail"] = float(res["site_pfail"][~sim.site_is_junction].mean())
        for (r, t), val in reg_out.items():
            row[f"out_{r}_t{t}"] = val
        for t in TARGET_T:
            row[f"out_five_t{t}"] = sum(reg_out[(r, t)] for r in ("tokai", "kinki", "sanyo", "shikoku", "kyushu"))
            row[f"outtot_five_t{t}"] = sum(reg_out[(r + "_tot", t)] for r in ("tokai", "kinki", "sanyo", "shikoku", "kyushu"))
        row["sec"] = round(time.time() - t0, 1)
        rows.append(row)
        print(f"{v}  five-region PHYS out: t0={row['out_five_t0']/1e4:.0f}万 t1={row['out_five_t1']/1e4:.0f}万 t4={row['out_five_t4']/1e4:.0f}万 t7={row['out_five_t7']/1e4:.0f}万 | "
              f"incl.shortage t0={row['outtot_five_t0']/1e4:.0f} t1={row['outtot_five_t1']/1e4:.0f} t4={row['outtot_five_t4']/1e4:.0f} t7={row['outtot_five_t7']/1e4:.0f} | "
              f"west served@0={row.get('west_served_0', float('nan')):.2f} @1={row.get('west_served_1', float('nan')):.2f} @7={row.get('west_served_7', float('nan')):.2f} ({row['sec']}s)", flush=True)
        pd.DataFrame(rows).to_csv(os.path.join(a.out, "calib_table.csv"), index=False)
    print("内閣府2013 基本ケース(五地域): t0=1930万 t1=640〜1070万 t4=33万 t7=29万 / 電灯軒数 2470万")


if __name__ == "__main__":
    main()
