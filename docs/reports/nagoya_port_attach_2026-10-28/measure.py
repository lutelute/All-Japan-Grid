"""名古屋港の周りの大型機の繋ぎ先と、配布ケースの網の前後(繋ぎ先の規則 cap → 島別の既定)。

    PYTHONPATH=. python docs/reports/nagoya_port_attach_2026-10-28/measure.py

前 = 2026-10-28 までの配布ケース(`build_canonical_net` が `cap` を書き込んでいた)、
後 = 島別の既定(介入#41・西と北海道は `capkv`)。地点需要は使わない(正典の島の試験と同じ・CI でも回る)。
書くもの: stats.json(この報告の数字はすべてここから)。
"""
import copy
import json
import math
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
    ISLAND_FREQ, attach_default_for, attach_generators, build_island_net)

BOX = (34.8, 35.12, 136.6, 137.1)        # 名古屋港・知多・碧南・川越(lat, lat, lon, lon)


def hav(a, b, c, d):
    p = math.radians
    x = math.sin(p(c - a) / 2) ** 2 + math.cos(p(a)) * math.cos(p(c)) * math.sin(p(d - b) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(x))


def plants_table(built):
    """≥200 MW の機ごとに、規則ごとの繋ぎ先(バス名・電圧・距離)。"""
    nodes, edges = built["nodes"], built["edges"]
    net0, bus_of, _ = build_island_net("west", nodes, edges, ISLAND_FREQ["west"], {})
    node_of_bus = {b: i for i, b in bus_of.items()}
    feats = {f"chubu_g{k}": f for k, f in enumerate(
        json.loads(Path("data/chubu_plants.geojson").read_text(encoding="utf-8"))["features"])}
    out = {}
    for mode in ("cap", "capkv"):
        net = copy.deepcopy(net0)
        attach_generators(net, bus_of, nodes, "west", attach_mode=mode)
        for _, g in net.gen.iterrows():
            f = feats.get(g.get("src_feature"))
            if f is None or g.max_p_mw < 200:
                continue
            lon, lat = f["geometry"]["coordinates"][:2]
            if not (BOX[0] <= lat <= BOX[1] and BOX[2] <= lon <= BOX[3]):
                continue
            n = nodes[node_of_bus[int(g.bus)]]
            rec = out.setdefault(str(g["name"]), {"mw": round(float(g.max_p_mw)), "lonlat": [lon, lat]})
            rec[mode] = {"bus": str(net.bus.at[int(g.bus), "name"]), "kv": float(net.bus.at[int(g.bus), "vn_kv"]),
                         "km": round(hav(lat, lon, n["lat"], n["lon"]), 1), "lonlat": [n["lon"], n["lat"]]}
    return dict(sorted(out.items(), key=lambda t: -t[1]["mw"]))


def case(built, island, mode):
    net0 = build_canonical_net(island, built["nodes"], built["edges"], ISLAND_FREQ[island],
                               point_demand=False, attach_mode=mode)
    net, ok, how, red, sp = solve_canonical(net0)
    kv = net.bus.vn_kv
    ln = net.res_line.loading_percent[net.line.in_service & (kv.loc[net.line.from_bus].values >= 154)]
    tr = net.res_trafo.loading_percent[net.trafo.in_service]
    gbus = defaultdict(float)
    for _, g in net.gen.iterrows():
        gbus[int(g.bus)] += float(g.max_p_mw)
    loss = net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum()
    return {"ac": bool(ok), "how": how,
            "size": [len(net.bus), len(net.line), len(net.trafo), red["n_removed"] if red else 0],
            "vm": [round(float(net.res_bus.vm_pu.min()), 4), round(float(net.res_bus.vm_pu.max()), 4)],
            "loss_pct": round(100 * loss / net.res_load.p_mw.sum(), 2),
            "line154_max": round(float(ln.max()), 1), "line154_over": int((ln > 100).sum()),
            "trafo_max": round(float(tr.max()), 1), "trafo_over": int((tr > 100).sum()),
            "slack_after_mw": sp.get("slack_after_mw") if sp else None,
            "top_gen_bus": [[str(net.bus.at[b, "name"]), float(net.bus.at[b, "vn_kv"]), round(m)]
                            for b, m in sorted(gbus.items(), key=lambda t: -t[1])[:5]]}


def main():
    built = json.loads(Path("docs/data/built/all.json").read_text(encoding="utf-8"))
    stats = {"plants": plants_table(built), "case": {}}
    for isl in ("hokkaido", "west"):
        for tag, mode in (("before", "cap"), ("after", attach_default_for(isl))):
            stats["case"][f"{isl}/{tag}"] = {"mode": mode, **case(built, isl, mode)}
            print(isl, tag, stats["case"][f"{isl}/{tag}"], flush=True)
    (HERE / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
