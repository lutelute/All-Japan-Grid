"""main(今の層)・A(11-07 の JSON+今の正典)・B(11-09 の JSON+今の正典)の路線・鉄塔の層を比べる。

    python3 cmp_runs.py <runs dir> <repo dir> <out json>
"""
import collections
import json
import math
import os
import sys

RUNS, REPO, OUT = sys.argv[1:4]
REGIONS = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku", "kansai", "chugoku", "shikoku", "kyushu", "okinawa"]
BAND = (36.8, 41.5, 137.8, 139.0)          # 東北の lon_min を広げた帯(#61)
SADO = (37.70, 38.40, 138.15, 138.60)


def ek(c):
    a, b = c[0], c[-1]
    q = lambda x: str(int(round(x * 1e4)))
    return ",".join([q(a[0]), q(a[1]), q(b[0]), q(b[1]), str(len(c))])


def km(c):
    s = 0.0
    for (x1, y1), (x2, y2) in zip(c, c[1:]):
        s += math.hypot((x2 - x1) * 111.32 * math.cos(math.radians((y1 + y2) / 2)), (y2 - y1) * 110.57)
    return s


def inbox(lat, lon, b):
    return b[0] <= lat <= b[1] and b[2] <= lon <= b[3]


def cum(xs):
    out, s = [], 0
    for x in xs:
        s += x
        out.append(s)
    return out


lines = json.load(open(os.path.join(REPO, "docs/data/map/lines_all.geojson"), encoding="utf-8"))["features"]
res = {}
for tag, sub in (("main", "main_osm_routes"), ("A", "A/osm_routes"), ("B", "B/osm_routes")):
    d = os.path.join(RUNS, sub)
    meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
    keys = json.load(open(os.path.join(d, "edge_routes.json"), encoding="utf-8"))["map"]
    r = {"counts": {k: meta["counts"][k] for k in ("ways", "routes", "towers", "towers_on_line", "towers_ref",
                                                   "map_edges", "map_edges_mapped", "edge_keys")},
         "source_sha": meta["source"]["sha256"][:12], "built_sha": meta["source"]["built_all_sha256"][:12]}
    tw_reg, band_tw, sado_tw, rt_reg, band_rt = {}, 0, 0, {}, 0
    for reg in REGIONS:
        t = json.load(open(os.path.join(d, f"towers_{reg}.json"), encoding="utf-8"))
        tw_reg[reg] = t["n"]
        lat = [v / 1e5 for v in cum(t["lat"])]
        lon = [v / 1e5 for v in cum(t["lon"])]
        band_tw += sum(1 for a, b in zip(lat, lon) if inbox(a, b, BAND) and not inbox(a, b, SADO))
        sado_tw += sum(1 for a, b in zip(lat, lon) if inbox(a, b, SADO))
        rt = json.load(open(os.path.join(d, f"routes_{reg}.json"), encoding="utf-8"))["routes"]
        rt_reg[reg] = len(rt)
    r["towers_by_region"] = tw_reg
    r["routes_by_region"] = rt_reg
    r["towers_band_mainland"] = band_tw
    r["towers_sado"] = sado_tw
    # 今の地図の線のうち路線を引けるもの(検査と同じく頂点 3 つ以上の線で数える)
    shaped = [f for f in lines if len(f["geometry"]["coordinates"]) > 2]
    hit = sum(1 for f in shaped if ek(f["geometry"]["coordinates"]) in keys)
    kall = khit = 0.0
    bk_all = bk_hit = 0.0
    for f in lines:
        c = f["geometry"]["coordinates"]
        L = km(c)
        kall += L
        mid = c[len(c) // 2]
        isb = inbox(mid[1], mid[0], BAND)
        if isb:
            bk_all += L
        if ek(c) in keys:
            khit += L
            if isb:
                bk_hit += L
    r["link"] = {"shaped": len(shaped), "shaped_hit": hit, "shaped_rate": round(hit / len(shaped), 4),
                 "km_all": round(kall), "km_hit": round(khit), "km_rate": round(khit / kall, 4),
                 "band_km_all": round(bk_all), "band_km_hit": round(bk_hit)}
    res[tag] = r

for tag, sub in (("main", "main_route_audit"), ("A", "A/route_audit"), ("B", "B/route_audit")):
    a = json.load(open(os.path.join(RUNS, sub, "audit.json"), encoding="utf-8"))
    cols = a["cols"]
    ci = cols.index(next(c for c in cols if c.startswith("class") or c.startswith("種類"))) if any(
        c.startswith("class") or c.startswith("種類") for c in cols) else 0
    cnt = collections.Counter()
    for row in a["rows"]:
        v = row[ci]
        cnt[a["classes"][v] if isinstance(v, int) else v] += 1
    res[tag]["audit"] = dict(sorted(cnt.items()))
    res[tag]["audit_cols"] = cols[:4]

json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False, indent=1))
