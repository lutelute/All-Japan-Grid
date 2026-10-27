"""介入#55 の測定: 台帳の機が公表の電圧に載るか(規則ごと)と、配布ケースの網の前後。

    PYTHONPATH=. python docs/reports/plant_connections_2026-10-28/measure.py

書くもの: stats.json(この報告の数字はすべてここから)。地点需要は使わない(CI でも回る)。
"""
import copy
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from scripts.export_matpower_canonical import build_canonical_net, solve_canonical  # noqa: E402
from scripts.run_full_powerflow_from_db import (  # noqa: E402
    ISLAND_FREQ, attach_default_for, attach_generators, build_island_net, load_plant_connections)

MODES = ("nearest", "cap", "kvfit", "capkv")


def plant_table(built, ledger):
    """台帳の機ごとに、規則ごとの繋ぎ先の電圧と、島の既定+台帳の繋ぎ先。"""
    rows = {}
    for island in ("west", "hokkaido"):
        net0, bus_of, _ = build_island_net(island, built["nodes"], built["edges"], ISLAND_FREQ[island], {})
        runs = [(m, m, None) for m in MODES] + [("ledger", attach_default_for(island), ledger)]
        for tag, mode, led in runs:
            net = copy.deepcopy(net0)
            attach_generators(net, bus_of, built["nodes"], island, attach_mode=mode, plant_ledger=led)
            for _, g in net.gen.iterrows():
                if g["name"] not in ledger:
                    continue
                r = rows.setdefault(g["name"], {"island": island, "mw": round(float(g.max_p_mw)),
                                                "pub_kv": ledger[g["name"]]["kv"]})
                r[tag] = {"bus": str(net.bus.at[int(g.bus), "name"]),
                          "kv": float(net.bus.at[int(g.bus), "vn_kv"])}
        print(island, "done", flush=True)
    for r in rows.values():
        r["default"] = attach_default_for(r["island"])
    score = {}
    for tag in MODES + ("ledger",):
        hit = [n for n, r in rows.items() if abs(r[tag]["kv"] - r["pub_kv"]) < 0.5]
        score[tag] = {"n": len(hit), "of": len(rows),
                      "mw": sum(rows[n]["mw"] for n in hit), "of_mw": sum(r["mw"] for r in rows.values())}
    return dict(sorted(rows.items(), key=lambda t: (t[1]["island"], -t[1]["mw"]))), score


def case(built, island, use_ledger):
    net0 = build_canonical_net(island, built["nodes"], built["edges"], ISLAND_FREQ[island],
                               point_demand=False, plant_connections=use_ledger)
    net, ok, how, red, sp = solve_canonical(net0)
    kv = net.bus.vn_kv
    ln = net.res_line.loading_percent[net.line.in_service & (kv.loc[net.line.from_bus].values >= 154)]
    tr = net.res_trafo.loading_percent[net.trafo.in_service]
    loss = net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum()
    return {"ac": bool(ok), "how": how,
            "size": [len(net.bus), len(net.line), len(net.trafo), red["n_removed"] if red else 0],
            "vm": [round(float(net.res_bus.vm_pu.min()), 4), round(float(net.res_bus.vm_pu.max()), 4)],
            "loss_pct": round(100 * loss / net.res_load.p_mw.sum(), 2),
            "line154_max": round(float(ln.max()), 1), "line154_over": int((ln > 100).sum()),
            "trafo_max": round(float(tr.max()), 1), "trafo_over": int((tr > 100).sum()),
            "slack_after_mw": sp.get("slack_after_mw") if sp else None}


def main():
    built = json.loads(Path("docs/data/built/all.json").read_text(encoding="utf-8"))
    ledger = load_plant_connections()
    rows, score = plant_table(built, ledger)
    stats = {"plants": rows, "score": score, "case": {}}
    for isl in ("west", "hokkaido"):
        for tag, use in (("before", False), ("after", True)):
            stats["case"][f"{isl}/{tag}"] = case(built, isl, use)
            print(isl, tag, stats["case"][f"{isl}/{tag}"], flush=True)
    (HERE / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
