"""変電所の敷地を横切る HV の線(観測層)を、正典モデル(built)が変電所の節点につないでいるか。

    python3 docs/reports/station_layers_2026-10-07/crossing_check.py > crossing_check.json

All-EU-Grid が欧州で「敷地を横切るだけの HV の way 55 本中 51 本を bus-branch モデルが母線につないでいた」と
報告した(2026-10-08)のを受けた点検。観測層(data/stations/japan_rows.json.gz)で、1 本の way が敷地の中の区間と
両側の外の区間に切られている所(66 kV 以上)を「横切る」とし、その区間の近く(50 m)に同じ電圧の built の節点が
あるかを見る。変電所の節点(sub=1)か次数 3 以上ならモデルは変電所につないでいる。
構内の配線との接続の証拠(views の binding が wired)があるかも並べる。
"""
import gzip
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

from shapely.geometry import LineString, Point

ROOT = Path(__file__).resolve().parents[3]
rows = json.load(gzip.open(ROOT / "data/stations/japan_rows.json.gz", "rt"))
built = json.loads((ROOT / "docs/data/built/all.json").read_text())
eq, terms, binding = rows["data"]["equipment"], rows["data"]["terminals"], rows["views"]["binding"]
t_by_eq = defaultdict(list)
for t in terms:
    t_by_eq[t["equipment_id"]].append(t)
pieces = defaultdict(list)
for e in eq:
    if e["kind"] == "line" and e.get("lvl") and e["lvl"][0] and e["lvl"][0] >= 66:
        pieces[(e["osm_id"], e["lvl"][0])].append(e)
K = math.cos(math.radians(36))


def xy(lat, lon):
    return lon * K * 111.32, lat * 110.57          # km


grid = defaultdict(list)
for n in built["nodes"]:
    grid[(round(n["lat"], 2), round(n["lon"], 2))].append(n)
out = []
for (way, kv), ps in pieces.items():
    for p in ps:
        es = p.get("end_sites") or []
        if len(es) != 2 or not es[0] or es[0] != es[1]:
            continue
        site = es[0]
        if sum(1 for q in ps if q is not p and (q.get("end_sites") or [None, None]).count(site) == 1) < 2:
            continue
        ls = LineString([xy(y, x) for x, y in p["coords"]])
        near = {}
        for x, y in p["coords"]:
            for dla in (-0.01, 0, 0.01):
                for dlo in (-0.01, 0, 0.01):
                    for n in grid.get((round(y + dla, 2), round(x + dlo, 2)), []):
                        if abs(n["kv"] - kv) <= 0.5 and ls.distance(Point(xy(n["lat"], n["lon"]))) <= 0.05:
                            near[n["id"]] = n
        joined = [n for n in near.values() if n.get("sub") == 1 or (n.get("deg") or 0) >= 3]
        out.append({"osm_way": way, "kv": kv, "site": site, "site_name": rows["site_names"].get(site),
                    "binding": sorted(binding.get(t["terminal_id"], {}).get("binding") for t in t_by_eq[p["equipment_id"]]),
                    "built": "joined_to_station" if joined else ("split" if near else "passes"),
                    "built_nodes": [{"name": n.get("name"), "sub": n.get("sub"), "deg": n.get("deg")} for n in joined]})
json.dump({"n_crossing": len(out), "built": dict(Counter(r["built"] for r in out)),
           "joined_without_wiring": sum(1 for r in out if r["built"] == "joined_to_station" and "wired" not in r["binding"]),
           "rows": out}, sys.stdout, ensure_ascii=False, indent=1)
