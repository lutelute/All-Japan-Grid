"""柵外 25 m の節点を変電所に入れる条件(core.BUFFER_PORTALS)を、日本の公表と物理で採点する(2026-10-08)。

    PYTHONPATH=. .venv/bin/python docs/reports/station_layers_2026-10-07/portal_check.py

station(移植元の既定: 構内の導体か機器と共有する節点だけ)を基準に、enters / any が余分につなぐ線路の端
(way と敷地の組)を 1 件ずつ判定する。

1. 公表の線区間(潮流実績の両端の変電所名)
   - confirmed: 敷地の名前が、その線名の公表の端のどれか
   - definite_error: 線名の公表が両端そろっていて、敷地がどの端でもなく、分岐点(…T・…分岐)も無い
   - branch_undeterminable: 分岐点があり、分岐先の変電所は公表に出ない
   - single_ended: 公表が片端だけ(東京電力)で、敷地が公表の端でない
   - no_official: 線名が公表に無い
2. 電圧: 敷地の voltage タグがあり、線の電圧がそのどれでもない → voltage_mismatch(物理で確かな誤り)
3. 形: その節点で会う、敷地に入る導体が、敷地の中で終わる(feeds_in)か、通り抜ける(passes_through)か
"""
import csv, json, pickle, re, sys, unicodedata
from collections import defaultdict, Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import numpy as np, shapely  # noqa: E402
import src.stations.core as core  # noqa: E402
from src.stations.extract_pbf import read_sites  # noqa: E402
from src.stations.tags import parse_voltage_kv, split_list  # noqa: E402

sites = read_sites(ROOT / "data/osm_pbf/japan-power.osm.pbf")
got = pickle.load(open(ROOT / "data/stations/read_cache.pkl", "rb"))
skey = [core.key_of(f["properties"]["osm_type"], f["properties"]["osm_id"]) for f in sites]
sprops = dict(zip(skey, (f["properties"] for f in sites)))
lines = {f"w{f['properties']['osm_id']}": f for f in got["lines"]}


def stem(s):
    s = unicodedata.normalize("NFKC", s or ""); s = re.sub(r"\(.*?\)|（.*?）", "", s); s = re.sub(r"\s+", "", s)
    return re.sub(r"(変電所|開閉所|発電所|変換所|変)$", "", s)


def lstem(s):
    s = unicodedata.normalize("NFKC", s or ""); s = re.sub(r"\(.*?\)|（.*?）", "", s); s = re.sub(r"\s+", "", s)
    s = re.sub(r"[0-9・･]+L$", "", s); return re.sub(r"(線|幹線|支線)$", "", s)


BRANCH = re.compile(r"(\d+T|T$|分岐|鉄塔)")
# 線名は事業者ごとに照らす(別の地域の同名の線と取り違えない)。敷地の地域は構造 DB との対応(crosswalk)から
off_st, off_two, off_branch = defaultdict(set), defaultdict(bool), defaultdict(bool)
for r in csv.DictReader(open(ROOT / "data/external/system_disclosure/normalized/line_observations.csv")):
    ln = (r["utility"], lstem(r["name"]))
    f, t = r["from_node"].strip(), r["to_node"].strip()
    for st in (f, t):
        if st:
            off_st[ln].add(stem(st))
            if BRANCH.search(unicodedata.normalize("NFKC", st)):
                off_branch[ln] = True
    if f and t:
        off_two[ln] = True


def attachments(mode):
    core.BUFFER_PORTALS = mode
    d = core.model(sites, got["lines"], got["elements"], extension_m=100)
    out = {}
    for e in d["equipment"]:
        ns = lines[e["osm_id"]]["properties"]["node_ids"] if e["osm_id"] in lines else None
        if e["kind"] == "line" and ns:
            a, b = e.get("segment") or [0, len(ns) - 1]
            for s, n in zip(e.get("end_sites") or (), (ns[a], ns[b])):
                if s:
                    out[(e["osm_id"], s)] = n
        elif e["kind"] == "internal" and e.get("conductor_rule") == "inside_one_footprint" and e["site"] and ns:
            out.setdefault((e["osm_id"], e["site"]), None)
    return out


import gzip  # noqa: E402
_xw = json.load(gzip.open(ROOT / "data/stations/japan_rows.json.gz", "rt"))["crosswalk"]
region_of = {k: sids[0].split("_site_")[0] for k, sids in _xw.items() if sids}
base = attachments("station")
loc = core.SiteLocator(sites, 25.0)
by_node = defaultdict(set)
for w, f in lines.items():
    for n in f["properties"]["node_ids"]:
        by_node[n].add(w)
inside_nodes = {}
xy = {}
for f in got["lines"]:
    for n, c in zip(f["properties"]["node_ids"], f["geometry"]["coordinates"]):
        xy.setdefault(n, c)
order = list(xy)
for n, r in zip(order, loc.locate(shapely.points(np.array([xy[n] for n in order], dtype=float)))):
    if r[0] is not None and r[1] in ("covered", "innermost_nested"):
        inside_nodes[n] = skey[r[0]]


def shape_of(w, s, node):
    """その節点で会う他の導体のうち、敷地 s に入るものが中で終わるか通り抜けるか。"""
    if node is None:
        return "no_node"
    kinds = set()
    for o in by_node.get(node, ()):
        if o == w:
            continue
        ns = lines[o]["properties"]["node_ids"]
        if not any(inside_nodes.get(n) == s for n in ns):
            continue
        ends_in = inside_nodes.get(ns[0]) == s or inside_nodes.get(ns[-1]) == s
        kinds.add("feeds_in" if ends_in else "passes_through")
    return "feeds_in" if "feeds_in" in kinds else ("passes_through" if kinds else "no_entering_way")


def judge(w, s):
    p = lines[w]["properties"] if w in lines else {}
    ln = (region_of.get(s), lstem(p.get("name")))
    site_stem = stem(sprops[s].get("name"))
    if ln[0] is None:
        return "no_region"
    if not ln[1] or ln not in off_st:
        return "no_official"
    if site_stem and site_stem in off_st[ln]:
        return "confirmed"
    if not off_two[ln]:
        return "single_ended"
    if off_branch[ln]:
        return "branch_undeterminable"
    return "definite_error"


# 基準: station のままの接続(規則を足す前)を同じ物差しで照らした正答率
report = {"station_baseline": dict(Counter(judge(w, s) for (w, s) in base))}
for mode in ("enters", "any"):
    extra = {k: v for k, v in attachments(mode).items() if k not in base}
    verdict, volt, shape, cross = Counter(), Counter(), Counter(), Counter()
    for (w, s), node in extra.items():
        p = lines[w]["properties"] if w in lines else {}
        ln = (region_of.get(s), lstem(p.get("name")))
        site_stem = stem(sprops[s].get("name"))
        if ln[0] is None:
            v = "no_region"
        elif not ln[1] or ln not in off_st:
            v = "no_official"
        elif site_stem and site_stem in off_st[ln]:
            v = "confirmed"
        elif not off_two[ln]:
            v = "single_ended"
        elif off_branch[ln]:
            v = "branch_undeterminable"
        else:
            v = "definite_error"
        verdict[v] += 1
        site_kv = {round(k, 1) for k in (parse_voltage_kv(t) for t in split_list(sprops[s].get("voltage"))) if k}
        line_kv = {round(k, 1) for k in (parse_voltage_kv(t) for t in split_list(p.get("voltage"))) if k}
        if site_kv and line_kv:
            vm = "voltage_match" if line_kv & site_kv else "voltage_mismatch"
        else:
            vm = "voltage_unknown"
        volt[vm] += 1
        sh = shape_of(w, s, node)
        shape[sh] += 1
        cross[(sh, v)] += 1
        cross[(sh, vm)] += 1
    report[mode] = {"extra_attachments": len(extra), "official": dict(verdict), "voltage": dict(volt),
                    "shape": dict(shape), "by_shape": {f"{a}|{b}": n for (a, b), n in sorted(cross.items())}}
print(json.dumps(report, ensure_ascii=False, indent=1))
