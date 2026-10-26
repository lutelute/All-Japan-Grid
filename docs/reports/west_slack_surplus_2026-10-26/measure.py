"""介入#54(issue #99)の前後を、正典の解き方そのもので測る。

    PYTHONPATH=. python docs/reports/west_slack_surplus_2026-10-26/measure.py

前 = `build_canonical_net(connected=False)` + `solve_canonical(spread=False)`(2026-10-26 までの正典)、
後 = モデル既定(介入#54 ON)。西と東は、取引を入れる試算(案3・未採用)も解く。

物差し:
  1. 主成分のスラック(余りを吸っていないか)
  2. エリアをまたぐ枝の潮流の合計を、OCCTO の連系線の計画潮流(同じ需要水準のコマ・occto_reference.json)と比べる
  3. 各社が公表する線路の潮流実績(2024 年度の年平均)の向き。照合は潮流マップと同じ
     `scripts/export_obs_compare.match_all`。A/B(両端が解決)で、平均がはっきり片向き(|平均| ≥ p95 の 1 割)の線だけ。
     書き出すのは事業者ごとの「向きが合った本数 / 比べた本数」だけ(線ごとの値は書かない)
地点需要の表(data/external)と線路の潮流実績(data/external)が無いときは、それぞれ使わずに測る。
"""
import copy
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from scripts.export_matpower_canonical import build_canonical_net, solve_canonical  # noqa: E402
from scripts.run_full_powerflow_from_db import ISLAND_FREQ, bus_component_index  # noqa: E402
from src.powerflow import point_demand as pdm  # noqa: E402
from src.powerflow.line_keys import line_keys  # noqa: E402


def main_slack(net):
    comp = bus_component_index(net)
    return next(i for i in net.ext_grid.index if comp.get(int(net.ext_grid.at[i, "bus"])) == 0)


def zone_pairs(net):
    """エリア(bus.zone)をまたぐ線と変圧器の潮流の合計。キーは名前の辞書順で前→後、前から後へを正。"""
    zb = net.bus["zone"]
    flows = defaultdict(float)
    l500 = {}
    for tab, res, a_col, b_col, p_col in (("line", "res_line", "from_bus", "to_bus", "p_from_mw"),
                                          ("trafo", "res_trafo", "hv_bus", "lv_bus", "p_hv_mw")):
        t, r = getattr(net, tab), getattr(net, res)
        for i in t.index[t.in_service]:
            a, b = zb.at[int(t.at[i, a_col])], zb.at[int(t.at[i, b_col])]
            p = float(r.at[i, p_col])
            if a == b or p != p:
                continue
            key, s = ((a, b), 1) if a < b else ((b, a), -1)
            flows[key] += s * p
            if tab == "line" and {a, b} == {"chubu", "kansai"} and float(net.bus.at[int(t.at[i, a_col]), "vn_kv"]) >= 500:
                l500[str(t.at[i, "name"])] = round(p if a == "chubu" else -p, 1)
    return {f"{a}->{b}": round(v, 1) for (a, b), v in sorted(flows.items())}, l500


def obs_direction(net, matched):
    k2i = {k: i for i, k in line_keys(net).items() if k}
    agree, tot = Counter(), Counter()
    for m in matched:
        if m["conf"] not in ("A", "B") or abs(m["obs"]["mean"]) < 0.1 * m["obs"]["p95"]:
            continue
        v, ok = 0.0, False
        for k, sg, _ in m["segs"][0]:
            i = k2i.get(k)
            if i is not None and float(net.res_line.at[i, "p_from_mw"]) == float(net.res_line.at[i, "p_from_mw"]):
                v += sg * float(net.res_line.at[i, "p_from_mw"])
                ok = True
        if ok and abs(v) >= 1:
            tot[m["util"]] += 1
            agree[m["util"]] += (v > 0) == (m["obs"]["mean"] > 0)
    return {u: [agree[u], tot[u]] for u in sorted(tot)} | {"all": [sum(agree.values()), sum(tot.values())]}


def add_exchange(net, export):
    """案3(試算・未採用): 主成分の各エリアの目標に、OCCTO のエリアの送り出し(+)/受け入れ(−)を足す。"""
    comp = bus_component_index(net)
    load, gens = defaultdict(float), defaultdict(list)
    for _, r in net.load.iterrows():
        if r["in_service"] and comp.get(int(r["bus"])) == 0:
            load[net.bus.at[int(r["bus"]), "zone"]] += float(r["p_mw"])
    for gi, r in net.gen.iterrows():
        if comp.get(int(r["bus"])) != 0:
            continue
        z = r.get("zone_src")
        gens[z if isinstance(z, str) and z else net.bus.at[int(r["bus"]), "zone"]].append(gi)
    for z, gis in gens.items():
        cap = float(net.gen.loc[gis, "max_p_mw"].sum())
        if cap > 0:
            s = min(max(load.get(z, 0.0) + export.get(z, 0.0), 0.0) / cap, 1.0)
            net.gen.loc[gis, "p_mw"] = net.gen.loc[gis, "max_p_mw"] * s


def summarize(n, ok, how, red, sp, matched):
    e = main_slack(n)
    zp, l500 = zone_pairs(n)
    load = float(n.res_load.p_mw.sum())
    loss = float(n.res_line.pl_mw.sum() + n.res_trafo.pl_mw.sum())
    return {"ac": bool(ok), "solve": how, "folded_buses": (red or {}).get("n_removed", 0),
            "n_bus": len(n.bus), "n_line": len(n.line), "n_trafo": len(n.trafo),
            "main_slack": str(n.ext_grid.at[e, "name"]),
            "main_slack_lonlat": json.loads(n.bus.at[int(n.ext_grid.at[e, "bus"]), "geo"])["coordinates"][:2],
            "main_slack_zone": str(n.bus.at[int(n.ext_grid.at[e, "bus"]), "zone"]),
            "main_slack_mw": round(float(n.res_ext_grid.at[e, "p_mw"]), 1),
            "other_slacks_mw": round(float(n.res_ext_grid.p_mw.sum() - n.res_ext_grid.at[e, "p_mw"]), 1),
            "gen_mw": round(float(n.res_gen.p_mw.sum()), 1), "load_mw": round(load, 1),
            "loss_mw": round(loss, 1), "loss_pct": round(100 * loss / load, 2),
            "vm_min": round(float(n.res_bus.vm_pu.min()), 4), "vm_max": round(float(n.res_bus.vm_pu.max()), 4),
            "spread": sp, "zone_pairs": zp, "chubu_kansai_500kv": l500,
            "obs_direction": obs_direction(n, matched) if matched else None}


def line_delta(a, b):
    ka, kb = line_keys(a), line_keys(b)
    pa = {k: float(a.res_line.at[i, "p_from_mw"]) for i, k in ka.items() if k}
    pb = {k: float(b.res_line.at[i, "p_from_mw"]) for i, k in kb.items() if k}
    d = [abs(pb[k] - pa[k]) for k in pa.keys() & pb.keys() if pa[k] == pa[k] and pb[k] == pb[k]]
    return {"n_lines": len(d), "gt50_mw": sum(x > 50 for x in d), "gt200_mw": sum(x > 200 for x in d),
            "max_mw": round(max(d), 1) if d else 0.0}


def main():
    built = json.loads((ROOT / "docs/data/built/all.json").read_text(encoding="utf-8"))
    ref = json.loads((HERE / "occto_reference.json").read_text(encoding="utf-8"))
    use_pd = os.path.exists(pdm.CSV)
    matched = []
    try:
        from scripts.export_obs_compare import OBS, load_obs, match_all
        if OBS.exists():
            matched, _ = match_all(load_obs(), built)
    except Exception as ex:  # noqa: BLE001
        print("線路の潮流実績を使わない:", ex, file=sys.stderr)
    out = {"point_demand": use_pd, "line_observations": bool(matched), "islands": {}}
    for isl in ("okinawa", "hokkaido", "east", "west"):
        mi = [m for m in matched if m["island"] == isl]
        rec = {}
        nets = {}
        for tag, conn in (("before", False), ("after", True)):
            net0 = build_canonical_net(isl, built["nodes"], built["edges"], ISLAND_FREQ[isl],
                                       point_demand=use_pd, connected=conn)
            n, ok, how, red, sp = solve_canonical(net0, spread=conn)
            rec[tag] = summarize(n, ok, how, red, sp, mi)
            nets[tag] = n
            print(isl, tag, {k: rec[tag][k] for k in ("ac", "main_slack", "main_slack_mw", "loss_pct", "zone_pairs")},
                  flush=True)
        rec["line_delta"] = line_delta(nets["before"], nets["after"])
        if isl in ref.get("area_export", {}):
            net0 = build_canonical_net(isl, built["nodes"], built["edges"], ISLAND_FREQ[isl],
                                       point_demand=use_pd, connected=True)
            add_exchange(net0, ref["area_export"][isl])
            n, ok, how, red, sp = solve_canonical(net0, spread=True)
            rec["trial_exchange"] = summarize(n, ok, how, red, sp, mi)
            rec["trial_exchange"]["export_target_mw"] = ref["area_export"][isl]
            print(isl, "trial", rec["trial_exchange"]["zone_pairs"], flush=True)
        out["islands"][isl] = rec
    (HERE / "stats.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
