#!/usr/bin/env python3
"""介入#43(降圧点欠損)の census と静的ゲート — 島ごとに OFF / #43a / #43a+#43b を比べる.

本番経路(run_full_powerflow_from_db: build → attach → allocate → reactive → #37 → [#43b] →
slack → balance → solve_island)で 1 断面(需要ピーク・UC 注入なし)を解き、
  収束(AC/DC)・slack・vm_min・実在線の過負荷本数・最大負荷率・synthetic slack 数
を比べる。uc_to_pf_built(UC 注入あり・fy2023r2 ピーク)のゲートは別途 JSON で取る。

usage:
  PYTHONPATH=. python3 scripts/stepdown_gap_census.py --islands east west --census-only
  PYTHONPATH=. python3 scripts/stepdown_gap_census.py --islands east --gate
  PYTHONPATH=. python3 scripts/stepdown_gap_census.py --islands east --gate --attach cap capkv
出力: docs/reports/stepdown_gap_census_<date>.{json,md}
"""
from __future__ import annotations

import argparse
import copy
import datetime as _dt
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

REPORTS = "docs/reports"
SYNTH_MARKERS = ("(仮)", "同定", "取付", "スタブ", "leadin", "intra-substation", "#43a")


def _real_line_mask(net):
    nm = net.line["name"].astype(str)
    return net.line["in_service"] & ~nm.apply(lambda s: any(m in s for m in SYNTH_MARKERS))


def _metrics(net_s, conv, mode):
    out = {"mode": mode, "converged": bool(conv)}
    if not conv:
        return out
    out["slack_mw"] = round(float(net_s.res_ext_grid.p_mw.sum()), 1)
    out["slack_abs_sum_mw"] = round(float(net_s.res_ext_grid.p_mw.abs().sum()), 1)
    if mode == "ac":
        vm = net_s.res_bus.vm_pu[net_s.bus.in_service]
        out["vm_min"] = round(float(vm.min()), 4)
        out["n_bus_vm_lt_0_9"] = int((vm < 0.9).sum())
        out["loss_mw"] = round(float(net_s.res_line.pl_mw.sum() + net_s.res_trafo.pl_mw.sum()), 1)
    mask = _real_line_mask(net_s)
    lp = net_s.res_line.loading_percent[mask].dropna()
    out["n_real_line"] = int(mask.sum())
    out["n_over_real"] = int((lp > 100).sum())
    out["n_over_real_120"] = int((lp > 120).sum())
    out["max_loading_real"] = round(float(lp.max()), 1) if len(lp) else None
    lp_all = net_s.res_line.loading_percent[net_s.line.in_service].dropna()
    out["n_over_all"] = int((lp_all > 100).sum())
    lt = net_s.res_trafo.loading_percent[net_s.trafo.in_service].dropna()
    out["n_over_trafo"] = int((lt > 100).sum())
    return out


def run_config(pf, island, nodes, edges, cfg, pref_gwh, implicit, lv_r, attach,
               max_ac_buses=20000, census_only=False):
    from src.powerflow.pipeline import add_provisional_infeed, add_reactive_compensation
    from src.powerflow.stepdown_gap import aggregate_lv_islands, census
    t0 = time.perf_counter()
    net, bus_of, bstats = pf.build_island_net(
        island, nodes, edges, pf.ISLAND_FREQ[island], {}, dedup_nodes=True,
        site_trafos=False, deenergize_unbuilt=False, implicit_stepdown=implicit)
    pf.attach_generators(net, bus_of, nodes, island, attach_mode=attach)
    pf.allocate_loads(net, cfg, pref_gwh=pref_gwh)
    add_reactive_compensation(net, factor=cfg.get("reactive_compensation_factor", 0.6))
    infeed = add_provisional_infeed(net)
    rep = {"island": island, "implicit_stepdown": implicit, "lv_aggregate_km": lv_r,
           "attach": attach, "n_bus": len(net.bus), "n_line": len(net.line),
           "n_trafo": len(net.trafo), "n_implicit_stepdown": bstats["n_implicit_stepdown"],
           "n_stepdown_nameplate": sum(1 for r in bstats["implicit_stepdown_ledger"]
                                       if r["capacity"] == "nameplate"),
           "n_infeed37": len(infeed), "build_s": round(time.perf_counter() - t0, 1)}
    rep["census"] = census(net)
    if lv_r and lv_r > 0:
        rep["lv_aggregate"] = aggregate_lv_islands(net, r_max_km=lv_r)
        rep["lv_aggregate"].pop("aggregated", None)
        rep["lv_aggregate"]["unserved_top"] = rep["lv_aggregate"].pop("unserved")[:10]
    if census_only:
        return rep, bstats
    n_comp, n_slack, n_synth = pf.add_per_component_slacks(net)
    rep["n_components"] = n_comp
    rep["n_synth_slack"] = n_synth
    pf.balance_by_zone(net, cfg, use_zone_src=pf.GEN_ZONE_BY_OPERATOR)
    net_dc, dc, net_ac, ac = pf.solve_island(net, max_ac_buses)
    rep["dc"] = _metrics(net_dc, dc.get("converged"), "dc")
    if ac.get("converged"):
        rep["ac"] = _metrics(net_ac, True, "ac")
        rep["ac"]["served_frac"] = ac.get("served_frac")
    else:
        rep["ac"] = {"mode": "ac", "converged": False}
    rep["solve_s"] = round(time.perf_counter() - t0, 1)
    return rep, bstats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--islands", nargs="+", default=["east", "west"])
    ap.add_argument("--census-only", action="store_true")
    ap.add_argument("--gate", action="store_true", help="OFF / #43a / #43a+#43b の 3 構成を解く")
    ap.add_argument("--lv-r", type=float, default=5.0)
    ap.add_argument("--attach", nargs="*", default=None,
                    help="接続規則(既定=島別既定)。複数指定で cap vs capkv 等を比較")
    ap.add_argument("--date", default=_dt.date.today().isoformat())
    ap.add_argument("--max-ac-buses", type=int, default=20000)
    args = ap.parse_args(argv)

    import scripts.run_full_powerflow_from_db as pf
    from src.powerflow.pref_demand import pref_zone_gwh
    with open(pf.BUILT, encoding="utf-8") as f:
        db = json.load(f)
    nodes, edges = db["nodes"], db["edges"]
    cfg = pf.load_demand_config()
    pref_gwh, _ = pref_zone_gwh(nodes)

    rep = {"date": args.date, "islands": {}}
    for island in args.islands:
        attaches = args.attach or [pf.attach_default_for(island)]
        configs = [("off", False, 0.0)]
        if args.gate:
            configs += [("43a", True, 0.0), ("43a+43b", True, args.lv_r)]
        rows = {}
        for attach in attaches:
            for label, implicit, lv_r in configs:
                key = f"{label}/{attach}"
                print(f"== {island} {key} ...", flush=True)
                r, _ = run_config(pf, island, nodes, edges, cfg, pref_gwh, implicit, lv_r,
                                  attach, max_ac_buses=args.max_ac_buses,
                                  census_only=args.census_only)
                rows[key] = r
                if not args.census_only:
                    a = r["ac"]
                    print(f"   AC conv={a['converged']} slack={a.get('slack_mw')} vm_min={a.get('vm_min')} "
                          f"over_real={a.get('n_over_real')} max={a.get('max_loading_real')} | "
                          f"DC over_real={r['dc'].get('n_over_real')} max={r['dc'].get('max_loading_real')} "
                          f"| synth_slack={r.get('n_synth_slack')} {r['solve_s']}s", flush=True)
                c = r["census"]
                print(f"   census: mismatch {c['mismatch']['n_line_ends']}端/{c['mismatch']['n_sites']}サイト "
                      f"{c['mismatch']['by_pair']} | lv_islands {c['lv_islands']['n']}成分 "
                      f"{c['lv_islands']['n_bus']}バス {c['lv_islands']['load_mw']}MW "
                      f"(≥100MW {c['lv_islands']['n_ge_100mw']}) dist={c['lv_islands']['by_distance']}",
                      flush=True)
        rep["islands"][island] = rows

    os.makedirs(REPORTS, exist_ok=True)
    jp = os.path.join(REPORTS, f"stepdown_gap_census_{args.date}.json")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=lambda o: int(o) if hasattr(o, "__int__") else str(o))
    print(f"-> {jp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
