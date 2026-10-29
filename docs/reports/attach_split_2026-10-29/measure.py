"""東の繋ぎ先の規則(#41 改訂)・台帳の 4 行(#55)・154 kV の分割(#56)の前後を、同じ物差しで測る.

    PYTHONPATH=. python docs/reports/attach_split_2026-10-29/measure.py --island east --case split
    PYTHONPATH=. python docs/reports/attach_split_2026-10-29/measure.py --canonical east   # 正典の島の試験の値

case(東):
  base    main の既定(東 cap・台帳 21 行・分割なし)
  rule    東 capkv・台帳 21 行
  ledger  東 capkv・台帳 25 行(この枝の既定)
  split   この枝の既定 + 154 kV の分割(#56)
西は rule と ledger が同じ(西はもとから capkv、苓北は未解決)なので base・ledger・split。

網は感度の経路(`scripts/sensitivity/benchmark_sensitivity.production_net`)と同じ手順で組み、
地点需要(#30)は使わない。物差し:
- AC(本番の solve_island・上限 9,000 バス・損失を発電機へ配る)が解けたか・最低電圧・損失
- 154 kV 以上の線の定格超過の本数と最大負荷率、全部の線の定格超過の本数
- 三相短絡電流(主成分・昇圧変圧器 x=0.14 pu・c=1.1)の 154 kV 級と 500 kV の中央値・63 kA 超の母線数
- 154 kV 以下に載る 300 MW 以上の火力・原子力
- 台帳の東の機が載った電圧(公表の電圧と合うか)

書くもの: out/<island>_<case>.json(この報告の数字はすべてここから)。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "sensitivity"))

NEW_ROWS = ("姉崎火力発電所", "横浜火力発電所", "勿来発電所", "苓北火力発電所")
WATCH = NEW_ROWS + ("川崎火力発電所",)        # 台帳に載せなかった川崎も、どの電圧に載るかは見る
THERMAL = ("coal", "lng", "gas", "oil", "nuclear", "biomass", "thermal")


def fault_stats(net):
    from benchmark_sensitivity import main_component_subnet
    from src.dynamics.machine_agg import aggregate_machines
    from src.powerflow.short_circuit import build_sc_ybus, thevenin_diag
    sub, _ = main_component_subnet(net)
    agg = aggregate_machines(sub)
    Y, row_of, _lor, base = build_sc_ybus(sub)
    src = {}
    for m in agg["sync"]:
        r = row_of.get(int(m["bus"]))
        if r is not None:
            x = (float(m["xd2"]) + 0.14) * base / float(m["S_mva"])
            src[r] = src.get(r, 0j) + 1.0 / complex(0.0, x)
    z = thevenin_diag(Y, src)
    kv = np.full(Y.shape[0], np.nan)
    for lbl, r in row_of.items():
        kv[r] = float(sub.bus.at[lbl, "vn_kv"])
    with np.errstate(divide="ignore", invalid="ignore"):
        ika = 1.1 * base / np.abs(z) / (np.sqrt(3.0) * kv)
    out = {}
    for lo, hi in ((100, 160), (450, 600)):
        m = np.isfinite(ika) & (kv >= lo) & (kv <= hi)
        if m.any():
            out[f"{lo}-{hi}kV"] = {"n": int(m.sum()), "median": round(float(np.median(ika[m])), 1),
                                   "p90": round(float(np.percentile(ika[m], 90)), 1),
                                   "max": round(float(ika[m].max()), 1),
                                   "n_gt63": int((ika[m] > 63).sum())}
    return out


def build(island, case, nodes, edges, cfg, pref_gwh):
    from scripts.run_full_powerflow_from_db import (
        CONNECTED_DISPATCH, GEN_ZONE_BY_OPERATOR, ISLAND_FREQ, add_per_component_slacks, allocate_loads,
        attach_generators, balance_by_zone, build_island_net, load_plant_connections)
    from src.powerflow.compensation import add_reactive_compensation
    from src.powerflow.subtransmission_split import split_subtransmission

    ledger = load_plant_connections()
    if case in ("base", "rule"):
        ledger = {k: v for k, v in ledger.items() if k not in NEW_ROWS}
    mode = "cap" if (island == "east" and case == "base") else \
        {"hokkaido": "capkv", "west": "capkv", "east": "capkv", "okinawa": "cap"}[island]
    net, bus_of, _ = build_island_net(island, nodes, edges, ISLAND_FREQ[island], {})
    gst = attach_generators(net, bus_of, nodes, island, attach_mode=mode, plant_ledger=ledger, stats=True)
    split = split_subtransmission(net) if case == "split" else None
    allocate_loads(net, cfg, pref_gwh=pref_gwh)
    add_reactive_compensation(net, factor=cfg.get("reactive_compensation_factor", 0.6))
    add_per_component_slacks(net)
    balance_by_zone(net, cfg, use_zone_src=GEN_ZONE_BY_OPERATOR, connected=CONNECTED_DISPATCH)
    return net, mode, gst, split


def main_case(island, case, out):
    from scripts.run_full_powerflow_from_db import CONNECTED_DISPATCH, load_demand_config, solve_island
    from src.powerflow.pref_demand import pref_zone_gwh

    t0 = time.perf_counter()
    d = json.loads((ROOT / "docs" / "data" / "built" / "all.json").read_text(encoding="utf-8"))
    nodes, edges = d["nodes"], d["edges"]
    cfg = load_demand_config()
    pref_gwh, _ = pref_zone_gwh(nodes)
    net, mode, gst, split = build(island, case, nodes, edges, cfg, pref_gwh)

    big_low, east_rows = {}, {}
    for _, g in net.gen.iterrows():
        cap = g.get("max_p_mw")
        cap = float(cap) if cap is not None and np.isfinite(cap) else float(g["p_mw"])
        kv = float(net.bus.at[int(g["bus"]), "vn_kv"])
        nm = str(g["name"])
        if cap >= 300 and str(g.get("type") or "").lower() in THERMAL and bool(g["in_service"]) and kv <= 160:
            big_low.setdefault(nm, (round(cap), kv))
        if nm in WATCH:
            east_rows.setdefault(nm, []).append({"mw": round(cap), "kv": kv,
                                                 "bus": str(net.bus.at[int(g["bus"]), "name"])})
    res = {"island": island, "case": case, "attach_mode": mode,
           "plant_ledger": gst.get("plant_ledger"),
           "split": ({k: v for k, v in split.items() if k != "opened"} if split else None),
           "big_thermal_le154": {"n": len(big_low), "mw": int(sum(v[0] for v in big_low.values())),
                                 "top": sorted(big_low, key=lambda k: -big_low[k][0])[:12]},
           "new_rows": east_rows, "fault": fault_stats(net)}
    _ndc, _dc, net_ac, ac = solve_island(net, max_ac_buses=9000, spread=CONNECTED_DISPATCH)
    res["ac_converged"] = bool(ac.get("converged"))
    if ac.get("converged"):
        rl = net_ac.res_line
        kvl = net_ac.bus.loc[net_ac.line["from_bus"], "vn_kv"].to_numpy()
        ld = rl["loading_percent"].to_numpy()
        ins = net_ac.line["in_service"].to_numpy().astype(bool)
        m154 = ins & (kvl >= 150)
        res.update({"vm_min": round(float(net_ac.res_bus.vm_pu.min()), 4),
                    "max_loading_154plus": round(float(np.nanmax(ld[m154])), 1),
                    "n_over_154plus": int((ld[m154] > 100).sum()),
                    "n_over_all": int((ld[ins] > 100).sum()),
                    "loss_mw": round(float(rl["pl_mw"].sum()), 1)})
    else:
        res["ac_error"] = str(ac.get("error") or ac.get("rejected") or "")[:200]
    res["sec"] = round(time.perf_counter() - t0, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k not in ("new_rows", "big_thermal_le154")},
                     ensure_ascii=False), flush=True)


def canonical(island, out, attach=None, rows="new"):
    """正典の島の試験(tests/test_canonical_islands.py の RECORD)と同じ組み方・解き方の値。

    attach: 繋ぎ先の規則(None = この枝の島別既定)。rows="old" は台帳の 4 行を除く(main の台帳)、
    "new" は 25 行すべて、それ以外は名前がそれで始まる行だけを除く(1 行ずつの切り分け)。
    """
    import src.powerflow.full_from_built as F
    from scripts.export_matpower_canonical import build_canonical_net, solve_canonical
    from scripts.run_full_powerflow_from_db import ISLAND_FREQ
    drop = NEW_ROWS if rows == "old" else tuple(r for r in NEW_ROWS if r.startswith(rows))
    if drop:
        orig = F.load_plant_connections
        F.load_plant_connections = lambda path=F.PLANT_CONNECTIONS_PATH: {
            k: v for k, v in orig(path).items() if k not in drop}
    d = json.loads((ROOT / "docs" / "data" / "built" / "all.json").read_text(encoding="utf-8"))
    net0 = build_canonical_net(island, d["nodes"], d["edges"], ISLAND_FREQ[island], point_demand=False,
                               attach_mode=attach)
    net, ok, how, red, spread = solve_canonical(net0)
    vm = net.res_bus.vm_pu.dropna()
    loss = net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum()
    rec = {"island": island, "attach": attach or F.attach_default_for(island), "rows": rows,
           "ok": bool(ok), "how": how,
           "reduction": {k: v for k, v in (red or {}).items() if not isinstance(v, (list, dict))},
           "record": [len(net.bus), len(net.line), len(net.trafo), (red or {}).get("n_removed", 0),
                      round(float(vm.min()), 4), round(float(vm.max()), 4),
                      round(100 * float(loss) / float(net.res_load.p_mw.sum()), 2)],
           "spread": spread}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(rec, ensure_ascii=False, default=str), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--island")
    ap.add_argument("--case", choices=["base", "rule", "ledger", "split"])
    ap.add_argument("--canonical")
    ap.add_argument("--attach", choices=["cap", "capkv"])
    ap.add_argument("--rows", default="new")
    a = ap.parse_args()
    if a.canonical:
        tag = "".join(f"_{t}" for t in (a.attach, a.rows if a.rows != "new" else None) if t)
        canonical(a.canonical, HERE / "out" / f"canonical_{a.canonical}{tag}.json", a.attach, a.rows)
    else:
        main_case(a.island, a.case, HERE / "out" / f"{a.island}_{a.case}.json")
