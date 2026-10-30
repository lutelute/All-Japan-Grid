"""台帳(介入#55)の全機を地図・空中写真で見直した追補の測定。前 = main 5e1223fb の台帳、後 = いまの台帳。

    PYTHONPATH=. python docs/reports/plant_sites_by_eye_2026-10-30/measure.py

書くもの: stats.json(この報告の数字はすべてここから)。地点需要は使わない(CI でも回る)。
正典(built)は前後で同じなので、いまのものを使う。前の台帳は git の履歴から読む(`git show 5e1223fb:...`)。
"""
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
import scripts.run_full_powerflow_from_db as rfp  # noqa: E402
from scripts.run_full_powerflow_from_db import (  # noqa: E402
    ISLAND_FREQ, attach_default_for, attach_generators, build_island_net, load_plant_connections)

BEFORE = "5e1223fb"
ISLANDS = ("west", "hokkaido")
NAGOYA = (34.78, 35.12, 136.60, 137.08)       # 名古屋港の周り(集中を数える範囲)


def old_ledger():
    rows = yaml.safe_load(subprocess.run(["git", "show", f"{BEFORE}:config/plant_connections.yaml"], check=True,
                                         capture_output=True, text=True).stdout)["plants"]
    return {str(r["name"]): {"kv": float(r["kv"]), "to": [str(t) for t in (r.get("to") or [])],
                             "at": tuple(float(v) for v in r["at"]) if r.get("at") else None} for r in rows}


def km(a, b):
    return 6371 * math.hypot(math.radians(a[0] - b[0]), math.radians(a[1] - b[1]) * math.cos(math.radians(a[0])))


def sites(names):
    out = {}
    for f in sorted(Path("data").glob("*_plants.geojson")):
        for ft in json.loads(f.read_text(encoding="utf-8"))["features"]:
            n = ft["properties"].get("name")
            if n in names and ft["geometry"]["type"] == "Point":
                out.setdefault(n, (ft["geometry"]["coordinates"][1], ft["geometry"]["coordinates"][0]))
    return out


def picks(built, isl, ledger, names):
    """島の既定の規則+台帳で繋いだときの、台帳の機の繋ぎ先と、名古屋港の周りのバスごとの出力。"""
    net, bus_of, _ = build_island_net(isl, built["nodes"], built["edges"], ISLAND_FREQ[isl], {})
    attach_generators(net, bus_of, built["nodes"], isl, attach_mode=attach_default_for(isl), plant_ledger=ledger)
    pos = {b: (built["nodes"][i]["lat"], built["nodes"][i]["lon"]) for i, b in bus_of.items()}
    at = sites(names)
    out, per_bus = {}, defaultdict(float)
    for _, g in net.gen.iterrows():
        b = int(g.bus)
        p = pos.get(b)
        if p and NAGOYA[0] < p[0] < NAGOYA[1] and NAGOYA[2] < p[1] < NAGOYA[3]:
            per_bus[f"{net.bus.at[b, 'name']}|{float(net.bus.at[b, 'vn_kv']):.0f}"] += float(g.max_p_mw)
        if g["name"] in names and g["name"] in at:
            out[g["name"]] = {"mw": round(float(g.max_p_mw)), "bus": str(net.bus.at[b, "name"]),
                              "kv": float(net.bus.at[b, "vn_kv"]), "lat": round(p[0], 5), "lon": round(p[1], 5),
                              "km": round(km(at[g["name"]], p), 2)}
    top = sorted(((k, round(v)) for k, v in per_bus.items()), key=lambda t: -t[1])[:6]
    return out, top


def case(built, isl, ledger):
    # build_canonical_net は呼ばれるたびに run_full_powerflow_from_db から台帳を読むので、そちらを差し替える
    # (emc の名前を差し替えても効かない。nagoya_port_sites_2026-10-29/measure.py はこれで前後が台帳を反映していなかった)
    rfp.load_plant_connections = lambda: ledger
    net0 = emc.build_canonical_net(isl, built["nodes"], built["edges"], ISLAND_FREQ[isl],
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
    built = json.loads(Path("docs/data/built/all.json").read_text(encoding="utf-8"))
    runs = {"before": old_ledger(), "after": load_plant_connections()}
    names = set(runs["before"]) | set(runs["after"]) | {"新名古屋火力発電所"}
    stats = {"before_commit": BEFORE}
    for tag, led in runs.items():
        stats[tag] = {"plants": {}, "case": {}}
        for isl in ISLANDS:
            pl, top = picks(built, isl, led, names)
            stats[tag]["plants"].update(pl)
            if isl == "west":
                stats[tag]["top_buses_mw_nagoya"] = top
            stats[tag]["case"][isl] = case(built, isl, led)
        print(tag, json.dumps(stats[tag]["case"], ensure_ascii=False), flush=True)
    (HERE / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
