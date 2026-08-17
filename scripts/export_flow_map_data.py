#!/usr/bin/env python3
"""潮流方向・発電稼働率マップ(docs/flow_map.html)のデータをエクスポートする.

オーナー要望(2026-08-18): 「UCで定格に対してどれくらいの発電量とか、
実績で潮流方向見せたりとか、そういうのも実装しておいてほしい」

出力(docs/data/flow_map/):
  flows_{island}.geojson  線ごとの p_mw(幾何のfrom→to順で符号付き)・loading_pct・
                          obs_dir(観測潮流実績との方向一致: true/false/null)
  gens_{island}.geojson   発電接続バスごとの Pmax合計・Pg合計・稼働率(cf)・主燃料
  uc_utilization.json     UC(fy2023)の region|fuel別 定格容量・24hコミット/ディスパッチ

観測方向の扱い(ライセンス): 観測の生値(MW)は書かない。モデル潮流の向きと
観測実績の主方向(正逆)の**一致フラグのみ**を出す(検証情報・接続事実の範囲)。
前処理は本番既定(罠3追補チェックリスト: #19/#20/#24/#26/#30/#31)。
"""
from __future__ import annotations

import json
import sys
import warnings
from collections import defaultdict
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "docs" / "data" / "flow_map"
OBS = ROOT / "data/external/system_disclosure/normalized/line_observations.csv"


def norm_name(s: str) -> str:
    import re
    import unicodedata
    s = unicodedata.normalize("NFKC", str(s or ""))
    return re.sub(r"[\s・()（）]", "", s)


def load_obs_direction() -> dict:
    """{正規化線名: {'frm':正規化from局, 'to':正規化to局, 'forward':bool}}
    forward=True は観測の主方向が from→to(年平均が正)。生値は保持しない。"""
    import csv
    out = {}
    if not OBS.exists():
        return out
    with OBS.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                mean = float(r.get("flow_mean_mw") or "nan")
            except ValueError:
                continue
            if mean != mean or not r.get("from_node") or not r.get("to_node"):
                continue
            k = norm_name(r.get("name"))
            if not k:
                continue
            out[k] = {"frm": norm_name(r["from_node"]),
                      "to": norm_name(r["to_node"]),
                      "forward": mean >= 0}
    return out


def export_island(island: str, freq: int, nodes, edges, cfg, pref_gwh,
                  demand, obs_dir) -> dict:
    from scripts.run_full_powerflow_from_db import (
        add_per_component_slacks, allocate_loads, attach_generators,
        balance_by_zone, build_island_net, solve_island)
    import src.powerflow.point_demand as pdm

    geom = {}
    net, bus_of, _ = build_island_net(island, nodes, edges, freq, geom)
    attach_generators(net, bus_of, nodes, island, attach_mode="cap", stats=True)
    pinned, _ = pdm.match_buses(net, demand)
    allocate_loads(net, cfg, pref_gwh=pref_gwh, point_demand=pinned)
    from src.powerflow.pipeline import add_reactive_compensation
    add_reactive_compensation(net, factor=cfg.get(
        "reactive_compensation_factor", 0.6))
    add_per_component_slacks(net)
    balance_by_zone(net, cfg, use_zone_src=True)
    net_dc, dc, net_ac, ac = solve_island(net, max_ac_buses=99999)
    conv = bool(ac.get("converged"))
    net_u = net_ac if conv else net_dc

    # --- 線: 方向つき潮流 ---
    feats = []
    n_obs_match = n_obs_mismatch = 0
    bus_name = {b: norm_name(net_u.bus.at[b, "name"]) for b in net_u.bus.index}
    for li in net_u.line.index:
        if not bool(net_u.line.at[li, "in_service"]):
            continue
        try:
            p = float(net_u.res_line.at[li, "p_from_mw"])
            ld = float(net_u.res_line.at[li, "loading_percent"])
        except Exception:  # noqa: BLE001
            continue
        if p != p:
            continue
        fb, tb = int(net_u.line.at[li, "from_bus"]), int(net_u.line.at[li, "to_bus"])
        g = net_u.bus.at[fb, "geo"], net_u.bus.at[tb, "geo"]
        try:
            c0 = json.loads(g[0])["coordinates"]
            c1 = json.loads(g[1])["coordinates"]
        except Exception:  # noqa: BLE001
            continue
        nm = str(net_u.line.at[li, "name"] or "")
        # 観測方向: 線名一致+両端局名の対応で判定
        od = None
        o = obs_dir.get(norm_name(nm.split(" ")[0]))
        if o:
            fn, tn = bus_name.get(fb, ""), bus_name.get(tb, "")
            pair = None
            if o["frm"] and o["to"] and fn and tn:
                if o["frm"] in fn and o["to"] in tn:
                    pair = "same"
                elif o["frm"] in tn and o["to"] in fn:
                    pair = "swap"
            if pair:
                model_fwd = (p >= 0) if pair == "same" else (p < 0)
                od = bool(model_fwd == o["forward"])
                if od:
                    n_obs_match += 1
                else:
                    n_obs_mismatch += 1
        feats.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [c0, c1]},
            "properties": {"name": nm, "p_mw": round(p, 1),
                           "loading_pct": round(ld, 1),
                           **({"obs_dir": od} if od is not None else {})},
        })
    (OUT / f"flows_{island}.geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "features": feats},
        ensure_ascii=False, separators=(",", ":")))

    # --- 発電バス: 定格 vs 出力 ---
    gb = defaultdict(lambda: {"pmax": 0.0, "pg": 0.0, "fuel": defaultdict(float)})
    res_g = net_u.res_gen if conv else None
    for gi in net_u.gen.index:
        b = int(net_u.gen.at[gi, "bus"])
        pmax = float(net_u.gen.at[gi, "max_p_mw"] or 0)
        try:
            pg = float(res_g.at[gi, "p_mw"]) if res_g is not None else \
                float(net_u.gen.at[gi, "p_mw"] or 0)
        except Exception:  # noqa: BLE001
            pg = 0.0
        if pg != pg:
            pg = 0.0
        gb[b]["pmax"] += pmax
        gb[b]["pg"] += pg
        gb[b]["fuel"][str(net_u.gen.at[gi, "type"] or "?")] += pmax
    gfeats = []
    for b, v in gb.items():
        if v["pmax"] < 1.0:
            continue
        try:
            c = json.loads(net_u.bus.at[b, "geo"])["coordinates"]
        except Exception:  # noqa: BLE001
            continue
        main_fuel = max(v["fuel"].items(), key=lambda x: x[1])[0]
        gfeats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": c},
            "properties": {"name": str(net_u.bus.at[b, "name"]),
                           "pmax_mw": round(v["pmax"], 1),
                           "pg_mw": round(v["pg"], 1),
                           "cf": round(v["pg"] / v["pmax"], 3) if v["pmax"] else 0,
                           "fuel": main_fuel},
        })
    (OUT / f"gens_{island}.geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "features": gfeats},
        ensure_ascii=False, separators=(",", ":")))
    print(f"[{island}] AC={'OK' if conv else 'DC'} lines={len(feats)} "
          f"(観測方向 一致{n_obs_match}/不一致{n_obs_mismatch}) genバス={len(gfeats)}",
          flush=True)
    return {"ac": conv, "n_lines": len(feats), "n_genbus": len(gfeats),
            "obs_dir_match": n_obs_match, "obs_dir_mismatch": n_obs_mismatch}


def export_uc_utilization() -> None:
    """UC(fy2023)の region|fuel 別 定格・24hコミット/ディスパッチ→稼働率."""
    src = ROOT / "docs/reports/uc_pv_compare_2026-08-17.json"
    if not src.exists():
        print("uc_pv_compare が無いため UC稼働率はスキップ")
        return
    d = json.loads(src.read_text())["pv"]
    # 定格 = uc_pv_compare出力のtotal_mw(region|fuel別のシナリオ容量合計・同一解の正)
    cap = {k: float(v) for k, v in d.get("total_mw", {}).items()}
    out = {}
    for k, arr in d["dispatch_mw"].items():
        c = cap.get(k) or (max(d["committed_mw"].get(k, [0])) or 0)
        out[k] = {"capacity_mw": round(c, 1),
                  "dispatch24_mw": [round(x, 1) for x in arr],
                  "committed24_mw": [round(x, 1) for x in
                                     d["committed_mw"].get(k, [])],
                  "cf_peak": round(max(arr) / c, 3) if c else None,
                  "cf_mean": round(sum(arr) / 24 / c, 3) if c else None}
    (OUT / "uc_utilization.json").write_text(
        json.dumps({"scenario": "fy2023(2026-08-17解)", "groups": out},
                   ensure_ascii=False, indent=1))
    print(f"UC稼働率: {len(out)}系列 (region|fuel)", flush=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    import src.powerflow.point_demand as pdm
    from scripts.run_full_powerflow_from_db import load_demand_config
    from src.powerflow.pref_demand import pref_zone_gwh
    built = json.loads((ROOT / "docs/data/built/all.json").read_text())
    nodes, edges = built["nodes"], built["edges"]
    cfg = load_demand_config()
    pref_gwh, _ = pref_zone_gwh(nodes)
    demand = pdm.load_point_demand()
    obs_dir = load_obs_direction()
    print(f"観測方向テーブル: {len(obs_dir)}線", flush=True)
    meta = {}
    for island, freq in (("hokkaido", 50), ("east", 50), ("west", 60),
                         ("okinawa", 60)):
        meta[island] = export_island(island, freq, nodes, edges, cfg,
                                     pref_gwh, demand, obs_dir)
    export_uc_utilization()
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print("done ->", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
