#!/usr/bin/env python3
"""南海トラフ停電シナリオ卓(1 枚の HTML)を組み立てる。

    PYTHONPATH=hazard/nankai/src:hazard/nankai/scripts python3 hazard/nankai/scripts/build_scenario_tool.py \
        --out docs/reports/nankai_hazard_2026-09-13/tool/nankai_scenario_tool.html

- 系統の前提(過負荷リレー・変圧器台帳・東京湾の津波)は動的カスケードを事前に全組み合わせで計算し、結果を埋め込む。
- 被害と復旧の前提(全壊率曲線・人員・応援・社内融通・着手日)はブラウザで計算し直す。計算は hazard/nankai/tool/model.js
  (make_restoration_workforce.py の build/simulate を移したもの。tool/test_model.mjs で Python と照合)。
- 埋め込むのは母線ごとの解析結果・入力(震度・浸水ランク・木造の建築年次の構成)と、各社が公表する事業所の位置だけ。
  送配電事業者の台帳の生値(変電所別の容量)は入れない。
"""
from __future__ import annotations
import argparse, base64, json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd, yaml

import make_restoration_workforce as W

NANKAI = W.NANKAI; ROOT = W.ROOT
TOOL = os.path.join(NANKAI, "tool")
ZONES = ["tokyo", "tohoku", "chubu", "hokuriku", "kansai", "chugoku", "shikoku", "kyushu", "hokkaido", "okinawa"]
TOKYO_BAY_BOX = [35.28, 35.80, 139.60, 140.20]

# 系統の前提の組み合わせ → 計算済みの run(東の run_v6_* は run_v7 と同じ東の設定。run_v7 の東 = run_v6 の東を確認済み)
WEST_RUNS = {"ol1_tr1": "run_v7", "ol0_tr1": "run_v7_nool", "ol1_tr0": "run_v6", "ol0_tr0": "grid_ol0_tr0_tb1"}
EAST_RUNS = {"ol1_tr1_tb1": "run_v7", "ol0_tr1_tb1": "run_v6_nool", "ol1_tr0_tb1": "run_v6_notrafo", "ol1_tr1_tb0": "run_v6_notb",
             "ol0_tr0_tb1": "grid_ol0_tr0_tb1", "ol0_tr1_tb0": "grid_ol0_tr1_tb0", "ol1_tr0_tb0": "grid_ol1_tr0_tb0", "ol0_tr0_tb0": "grid_ol0_tr0_tb0"}


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")


def q8(x) -> np.ndarray:
    return np.clip(np.round(np.asarray(x, float) * 255), 0, 255).astype(np.uint8)


def era_raw(b, sup, dd):
    """母線ごとの木造住宅の建築年次の構成(旧 1970 年以前 / 1971〜80 / 1981 以降)と木造の比率。build() と同じ参照順(市区町村 → 県の残り → 県全体)。"""
    code, pref = W.bus_municipality(b)
    d1 = dict(dd); d1["housing_eras"] = {"old_share_of_1970_or_earlier": {"value": 1.0}}
    eras = W.wooden_era_shares(sup, d1)          # split=1 → [1970 以前, 1971〜80, 1981 以降]
    hp = sup["municipal_housing"]; hp = hp[hp.area_type_code == "a"]
    p2c = dict(zip(hp.muni_name, hp.muni_code.str[:2]))
    S = np.zeros((len(b), 3)); ws = np.zeros(len(b))
    for i, c in enumerate(code):
        pc = p2c.get(pref[i], "??")
        for k in (c, pc + "rest" if c else "", pc + "000"):
            if k in eras:
                S[i], ws[i] = eras[k]; break
        else:
            S[i] = (0.2, 0.3, 0.5); ws[i] = 0.55
    return S, ws


def dyn_block(run, island, bus_ids):
    od = os.path.join(NANKAI, "output", run, island)
    br = pd.read_parquet(os.path.join(od, "bus_results.parquet")).set_index("bus_id").loc[bus_ids]
    tl = sorted({float(c[6:]) for c in br.columns if c.startswith("phys_t")})
    pb = np.stack([1 - br[f"phys_t{t:g}"].to_numpy(float) for t in tl], 1)          # [nbus, T] 送電側で停電する確率
    e10 = br["dyn_energized_t600s"].to_numpy(float)
    sm = pd.read_csv(os.path.join(od, "dyn_summary.csv")); L = float(sm.load_mw.iloc[0])
    ds = pd.read_csv(os.path.join(od, "dyn_samples.csv"))
    g = lambda t, c: ds[ds.t_s == t][c]
    v = ds[ds.t_s == 600].n_islands.value_counts().sort_index()
    return dict(
        run=run, timeline_days=tl, load_gw=L / 1e3,
        t_s=sm.t_s.tolist(), energized=(sm.energized_mw / L).round(4).tolist(), p10=(sm.energized_p10 / L).round(4).tolist(),
        shed=(sm.shed_mw / L).round(4).tolist(), collapsed=(sm.collapsed_mw / L).round(4).tolist(),
        isolated=(sm.isolated_mw / L).round(4).tolist(), site_out=(sm.site_out_mw / L).round(4).tolist(),
        near_total=round(float((g(10800, "collapsed_mw") > 0.8 * L).mean()), 4), split10=round(float((g(600, "n_islands") >= 2).mean()), 4),
        islands10={int(k): int(n) for k, n in v.items()}, overload_trips=round(float(pd.read_csv(os.path.join(od, "dyn_event_counts.csv")).get("overload_trip", pd.Series([0])).mean()), 2),
        pb=b64(q8(pb)), e10=b64(q8(e10)))


def japan_outline():
    import shapely.geometry as sg
    gj = json.load(open(os.path.join(ROOT, "data", "reference", "japan_prefectures_simplified.geojson"), encoding="utf-8"))
    rings = []
    for f in gj["features"]:
        g = sg.shape(f["geometry"]).simplify(0.012, preserve_topology=True)
        polys = [g] if g.geom_type == "Polygon" else list(g.geoms)
        for p in polys:
            xy = np.asarray(p.exterior.coords)
            if len(xy) < 4 or xy[:, 1].max() < 30.5 or xy[:, 1].min() > 45.8 or p.area < 0.002:
                continue
            rings.append(np.round(xy, 3).tolist())
    return rings


def python_reference(cfg, ops, b0, sup, cases):
    """Python 版の結果(照合用)。cases: [(名前, 上書き dict)]"""
    import copy
    out = {}
    dt = 1.0 / 24.0; T = np.arange(0, 90 + dt / 2, dt)
    for name, ov in cases:
        c = copy.deepcopy(cfg); dd = c["distribution_damage"]
        dd["wooden_collapse_curve"]["sigma"]["value"] = ov.get("sigma", 0.4)
        dd["building_collapse_poles"]["rate_basis"]["value"] = ov.get("basis", "wooden_stock")
        dd["housing_eras"]["old_share_of_1970_or_earlier"]["value"] = ov.get("old_split", 0.5)
        dd["building_collapse_poles"]["enabled"] = ov.get("collapse", True)
        c["workforce"]["staff_per_million_customers"]["value"] = ov.get("spm", 390)
        c["repair"]["tsunami_access_d"]["value"] = ov.get("access", 10.0)
        b, O = W.build(c, ops, b0.copy(), np.random.default_rng(0), sup)
        res, CV, r, senders, receivers, mob = W.simulate(c, ops, O, dict(send_share=ov.get("aid", 0.15), internal=ov.get("internal", True)), T)
        idx = {d: int(round(d / dt)) for d in (1, 7, 14)}
        rest = b.cust.values - b.lost_cust.values; off = b.office.values
        dist = {f"{d}d": float((rest * np.clip((b.out_s.values * res["dist_out_s"][i][off] + b.out_t.values * res["dist_out_t"][i][off]) / np.maximum(rest, 1e-9), 0, 1)).sum())
                for d, i in idx.items()}
        out[name] = dict(override=ov, broken_s=float(b.brk_s.sum()), broken_t=float(b.brk_t.sum()), staff=float(O.staff.sum()),
                         aid_total=float(CV.people.sum()) if len(CV) else 0.0, senders=senders, receivers=receivers,
                         own7=float(res["own"][idx[7]]), internal7=float(res["internal"][idx[7]]), aid7=float(res["aid"][idx[7]]), dist_any=dist)
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--no-reference", action="store_true"); a = ap.parse_args()
    cfg = yaml.safe_load(open(os.path.join(NANKAI, "config", "restoration_workforce.yaml"), encoding="utf-8"))
    ops = yaml.safe_load(open(os.path.join(NANKAI, "config", "restoration_ops_scenario.yaml"), encoding="utf-8"))
    sup = W.support_tables()
    b0 = W.load_buses(os.path.join(NANKAI, "output", "run_v7"))
    b, O = W.build(cfg, ops, b0.copy(), np.random.default_rng(0), sup)
    S, ws = era_raw(b0.copy(), sup, cfg["distribution_damage"])
    zi = {z: i for i, z in enumerate(ZONES)}
    lat, lon = b.lat.to_numpy(float), b.lon.to_numpy(float)
    box = (lat >= TOKYO_BAY_BOX[0]) & (lat <= TOKYO_BAY_BOX[1]) & (lon >= TOKYO_BAY_BOX[2]) & (lon <= TOKYO_BAY_BOX[3])
    isl = (b.island == "east").to_numpy()
    buses = dict(n=int(len(b)), island=b64(isl.astype(np.uint8)), zone=b64(b.zone.map(zi).to_numpy(np.uint8)),
                 lat=b64(lat.astype(np.float32)), lon=b64(lon.astype(np.float32)), cust=b64(b.cust.to_numpy(np.float32)),
                 intensity=b64(b.intensity_mean.to_numpy(np.float32)), ts_rank=b64(b.tsunami_rank.to_numpy(np.uint8)), tokyo_bay=b64(box.astype(np.uint8)),
                 era=b64(S.astype(np.float32).ravel()), wooden_share=b64(ws.astype(np.float32)), office=b64(b.office.to_numpy(np.uint16)))
    offices = dict(zone=[zi[z] for z in O.zone], lat=O.lat.round(4).tolist(), lon=O.lon.round(4).tolist(), name=O.name.tolist())
    ppc = W.poles_per_customer_by_company(sup)
    cust_c = yaml.safe_load(open(os.path.join(NANKAI, "config", "customers.yaml"), encoding="utf-8"))["contracts_thousand"]
    companies = dict(keys=ZONES, ja=[W.JA[z] for z in ZONES], contracts_thousand=[cust_c.get(z, 0) for z in ZONES],
                     poles_per_customer=[round(ppc.get(z, 0.25), 4) for z in ZONES],
                     hq=[ops["mutual_aid"]["headquarters"]["coords"].get(z, [None, None])[:2] for z in ZONES])
    # 並びの確認: 東西の母線 id(bus_results と一致させる)
    west_ids = b.bus_id[~isl].to_numpy(); east_ids = b.bus_id[isl].to_numpy()
    dyn = dict(west={k: dyn_block(r, "west", west_ids) for k, r in WEST_RUNS.items()},
               east={k: dyn_block(r, "east", east_ids) for k, r in EAST_RUNS.items()})
    dd = cfg["distribution_damage"]; rp = cfg["repair"]; wf = cfg["workforce"]; ma = cfg["mutual_aid"]; per = ops["personnel"]
    params = dict(
        shaking_break_rate=dd["shaking_break_rate"]["by_class"], tsunami_break_rate=dd["tsunami_break_rate"]["value"],
        customers_per_broken_pole=dd["customers_per_broken_pole"]["value"], not_restorable_tsunami_rank_min=dd["not_restorable_tsunami_rank_min"]["value"],
        collapse_coefficient=dd["building_collapse_poles"]["coefficient"], anchor_intensity=dd["wooden_collapse_curve"]["anchor_intensity"],
        anchor_rates=dd["wooden_collapse_curve"]["anchor_rates"], poles_per_person_day=rp["poles_per_person_day"]["value"], patrol_d=rp["patrol_d"]["value"],
        call_up_d=wf["call_up_d"]["value"], internal=dict(start_d=wf["internal_reallocation"]["start_d"], share=wf["internal_reallocation"]["share_from_light_offices"],
                                                          light_ratio=wf["internal_reallocation"]["light_backlog_ratio"]),
        receiver_threshold_r=ma["receiver_threshold_r"]["value"], sender_max_r=ma["sender_max_r"]["value"], decision_d=ma["decision_d"], mobilization_d=ma["mobilization_d"],
        detour_factor=ma["detour_factor"], convoy_speed_kmh=ma["convoy_speed_kmh"], drive_h_per_day=ma["drive_h_per_day"], waves=ma["waves"],
        unavailable_by_class=per["unavailable_by_class"]["values"], tsunami_unavailable=per["tsunami_unavailable"]["value"],
        tau_shake_d=per["tau_shake_d"]["value"], tau_tsunami_d=per["tau_tsunami_d"]["value"], permanent_share=per["permanent_share"]["value"],
        jma_classes=[[0.5, "1"], [1.5, "2"], [2.5, "3"], [3.5, "4"], [4.5, "5弱"], [5.0, "5強"], [5.5, "6弱"], [6.0, "6強"], [6.5, "7"]],
        defaults=dict(ol=1, tr=1, tb=1, collapse=True, sigma=dd["wooden_collapse_curve"]["sigma"]["value"], basis=dd["building_collapse_poles"]["rate_basis"]["value"],
                      old_split=dd["housing_eras"]["old_share_of_1970_or_earlier"]["value"], spm=wf["staff_per_million_customers"]["value"],
                      aid=ma["send_share"]["value"], internal=True, access=rp["tsunami_access_d"]["value"]))
    data = dict(generated=time.strftime("%Y-%m-%d %H:%M"), buses=buses, offices=offices, companies=companies, dyn=dyn, params=params, outline=japan_outline(),
                naikakufu_2025=yaml.safe_load(open(os.path.join(NANKAI, "config", "calibration_targets.yaml"), encoding="utf-8"))["naikakufu_2025"]["outage_households"]["①東海_基本"])
    os.makedirs(TOOL, exist_ok=True)
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    open(os.path.join(TOOL, "data.json"), "w", encoding="utf-8").write(js)
    if not a.no_reference:
        cases = [("default", {}), ("sigma06_all_aid30", dict(sigma=0.6, basis="all_dwellings", aid=0.30)),
                 ("spm300_noint_access14", dict(spm=300, internal=False, access=14.0, old_split=0.3)), ("nocollapse_noaid", dict(collapse=False, aid=0.0))]
        json.dump(python_reference(cfg, ops, b0, sup, cases), open(os.path.join(TOOL, "reference.json"), "w"), ensure_ascii=False, indent=1)
    tpl = open(os.path.join(TOOL, "index.template.html"), encoding="utf-8").read()
    html = (tpl.replace("/*__STYLE__*/", open(os.path.join(TOOL, "style.css"), encoding="utf-8").read())
               .replace("/*__MODEL__*/", open(os.path.join(TOOL, "model.js"), encoding="utf-8").read())
               .replace("/*__APP__*/", open(os.path.join(TOOL, "app.js"), encoding="utf-8").read())
               .replace("/*__DATA__*/", "window.NANKAI_DATA=" + js + ";"))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, "w", encoding="utf-8").write(html)
    print("html MB", round(os.path.getsize(a.out) / 1e6, 2), "buses", len(b), "offices", len(O))


if __name__ == "__main__":
    main()
