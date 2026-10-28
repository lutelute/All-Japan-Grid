"""名古屋港の周りの大型機の繋ぎ先(介入#55 の追補)の測定。前 = main 6ede44e6 の正典と台帳、後 = いまの正典と台帳。

    PYTHONPATH=. python docs/reports/nagoya_port_sites_2026-10-29/measure.py

書くもの: stats.json(この報告の数字はすべてここから)。地点需要は使わない(CI でも回る)。
前の正典と台帳は git の履歴から読む(`git show 6ede44e6:...`)。
"""
import copy
import json
import math
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import scripts.export_matpower_canonical as emc  # noqa: E402
from scripts.run_full_powerflow_from_db import (  # noqa: E402
    ISLAND_FREQ, attach_default_for, attach_generators, build_island_net, load_plant_connections)

BEFORE = "6ede44e6"
PLANTS = ("碧南火力発電所", "川越火力発電所", "新名古屋火力発電所", "西名古屋火力発電所", "知多火力発電所",
          "知多第二火力発電所", "武豊火力発電所")
BOX = (34.78, 35.12, 136.60, 137.08)          # 名古屋港の周り(集中を数える範囲)


def show(path):
    return subprocess.run(["git", "show", f"{BEFORE}:{path}"], check=True, capture_output=True,
                          text=True).stdout


def old_ledger():
    rows = yaml.safe_load(show("config/plant_connections.yaml"))["plants"]
    return {str(r["name"]): {"kv": float(r["kv"]), "to": [str(t) for t in (r.get("to") or [])], "at": None}
            for r in rows}


def km(a, b):
    return 6371 * math.hypot(math.radians(a[0] - b[0]), math.radians(a[1] - b[1]) * math.cos(math.radians(a[0])))


def picks(built, ledger):
    """西の島の既定の規則+台帳で繋いだときの、名古屋港の機の繋ぎ先と、範囲内のバスごとの出力。"""
    net, bus_of, _ = build_island_net("west", built["nodes"], built["edges"], ISLAND_FREQ["west"], {})
    attach_generators(net, bus_of, built["nodes"], "west", attach_mode=attach_default_for("west"),
                      plant_ledger=ledger)
    pos = {b: (built["nodes"][i]["lat"], built["nodes"][i]["lon"]) for i, b in bus_of.items()}
    plants = json.loads(Path("data/chubu_plants.geojson").read_text(encoding="utf-8"))["features"]
    at = {f["properties"].get("name"): tuple(reversed(f["geometry"]["coordinates"][:2])) for f in plants
          if f["geometry"]["type"] == "Point"}
    out, per_bus = {}, defaultdict(float)
    for _, g in net.gen.iterrows():
        b = int(g.bus)
        p = pos.get(b)
        if p and BOX[0] < p[0] < BOX[1] and BOX[2] < p[1] < BOX[3]:
            per_bus[f"{net.bus.at[b, 'name']}|{float(net.bus.at[b, 'vn_kv']):.0f}"] += float(g.max_p_mw)
        if g["name"] in PLANTS:
            out[g["name"]] = {"mw": round(float(g.max_p_mw)), "bus": str(net.bus.at[b, "name"]),
                              "kv": float(net.bus.at[b, "vn_kv"]), "lat": round(p[0], 5), "lon": round(p[1], 5),
                              "km": round(km(at[g["name"]], p), 2)}
    top = sorted(((k, round(v)) for k, v in per_bus.items()), key=lambda t: -t[1])[:6]
    return out, top


def case(built, ledger):
    emc.load_plant_connections = lambda: ledger
    net0 = emc.build_canonical_net("west", built["nodes"], built["edges"], ISLAND_FREQ["west"],
                                   point_demand=False, plant_connections=True)
    net, ok, how, red, sp = emc.solve_canonical(net0)
    kv = net.bus.vn_kv
    ln = net.res_line.loading_percent[net.line.in_service & (kv.loc[net.line.from_bus].values >= 154)]
    tr = net.res_trafo.loading_percent[net.trafo.in_service]
    loss = net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum()
    return {"ac": bool(ok), "how": how,
            "size": [len(net.bus), len(net.line), len(net.trafo), red["n_removed"] if red else 0],
            "vm": [round(float(net.res_bus.vm_pu.min()), 4), round(float(net.res_bus.vm_pu.max()), 4)],
            "loss_pct": round(100 * loss / net.res_load.p_mw.sum(), 2),
            "line154_max": round(float(ln.max()), 1), "line154_over": int((ln > 100).sum()),
            "trafo_max": round(float(tr.max()), 1), "trafo_over": int((tr > 100).sum())}


def main():
    before = json.loads(show("docs/data/built/all.json"))
    after = json.loads(Path("docs/data/built/all.json").read_text(encoding="utf-8"))
    runs = {"before": (before, old_ledger()), "after": (after, load_plant_connections())}
    stats = {"before_commit": BEFORE}
    for tag, (built, led) in runs.items():
        pl, top = picks(built, led)
        stats[tag] = {"plants": pl, "top_buses_mw": top, "case_west": case(built, led)}
        print(tag, json.dumps(stats[tag], ensure_ascii=False)[:600], flush=True)
    (HERE / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
