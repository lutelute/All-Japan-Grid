"""I3: fetch the ways our extracts missed around isolated-fragment tips.

    PYTHONPATH=. python scripts/fetch_orphan_supplements.py --region tokyo
        [--census docs/reports/orphan_census_2026-06-13.json]
        [--around 400] [--chunk 25]

The original regional extracts dropped real ways (probe 2026-06-13:
佐久間東/西幹線 275 kV, 東千葉房総線 154 kV missing around tokyo's
isolated fragments). For every fragment centre in the census this
queries Overpass (private.coffee) for power=line/cable/minor_line ways
within ``--around`` metres, keeps the ones whose geometry is absent
from the region's current line layer (vertex-grid test, ~100 m), and
APPENDS them to ``data/{region}_lines_supplement.geojson`` — a tracked
additive file the builder merges (the base extract is never mutated).
Each feature carries provenance: osm way id, fetch date, source.
Re-runs dedupe by way id.
"""

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EP = "https://overpass.private.coffee/api/interpreter"


def _vertex_grid(region: str, cell: float = 0.001):
    grid = set()
    for suffix in ("lines", "lines_supplement"):
        path = f"data/{region}_{suffix}.geojson"
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        for feat in d["features"]:
            g = feat["geometry"]
            if g["type"] == "LineString":
                cs = g["coordinates"]
            elif g["type"] == "MultiLineString":
                cs = [c for part in g["coordinates"] for c in part]
            else:
                continue
            for lon, la in cs:
                grid.add((round(la / cell), round(lon / cell)))
    return grid, cell


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", required=True)
    ap.add_argument("--census",
                    default="docs/reports/orphan_census_2026-06-13.json")
    ap.add_argument("--around", type=int, default=400)
    ap.add_argument("--chunk", type=int, default=25)
    ap.add_argument("--sleep", type=float, default=10.0)
    ap.add_argument("--names-pass", action="store_true",
                    help="第2パス: 断片+サプリ線の名称で回廊全体を一括補完"
                         "(佐久間東幹線型の連鎖を一発で完結させる)")
    args = ap.parse_args(argv)

    census = json.load(open(args.census, encoding="utf-8"))
    frags = census["regions"].get(args.region) or []
    if not frags:
        print(f"no fragments for {args.region} in census")
        return 0

    grid, cell = _vertex_grid(args.region)

    def known(la, lo):
        ci, cj = round(la / cell), round(lo / cell)
        return any((ci + di, cj + dj) in grid
                   for di in (-1, 0, 1) for dj in (-1, 0, 1))

    if args.names_pass:
        # 断片線とサプリ済みウェイの名称を収集し、地域bbox内で同名ウェイを全取得
        import re as _re
        names = set()
        for f in frags:
            nm = (f.get("name_sample") or "").strip()
            if nm and nm not in ("?", "-") and len(nm) >= 3:
                for part in nm.replace(";", "/").split("/"):
                    part = part.strip()
                    if len(part) >= 3:
                        names.add(part)
        spath0 = f"data/{args.region}_lines_supplement.geojson"
        if os.path.exists(spath0):
            for ft in json.load(open(spath0, encoding="utf-8"))["features"]:
                nm = (ft["properties"].get("name") or "").strip()
                for part in nm.replace(";", "/").split("/"):
                    part = part.strip()
                    if len(part) >= 3:
                        names.add(part)
        # bbox = 地域線レイヤの範囲
        d0 = json.load(open(f"data/{args.region}_lines.geojson", encoding="utf-8"))
        las, los = [], []
        for ft in d0["features"][::7]:
            g = ft["geometry"]
            cs = g["coordinates"] if g["type"] == "LineString" else (
                [c for pt_ in g["coordinates"] for c in pt_]
                if g["type"] == "MultiLineString" else [])
            for lon, la in cs[::5]:
                las.append(la); los.append(lon)
        bbox = f"{min(las):.2f},{min(los):.2f},{max(las):.2f},{max(los):.2f}"
        esc = [_re.escape(n) for n in sorted(names) if not _re.search(r"[0-9]+kV", n)]
        clauses = []
        for i in range(0, len(esc), 12):
            pat = "|".join(esc[i:i + 12])
            clauses.append(f'way({bbox})["power"]["name"~"{pat}"];')
        print(f"names-pass: {len(esc)}名称 / {len(clauses)}クエリ", flush=True)
    else:
        clauses = [f'way(around:{args.around},{f["lat"]},{f["lon"]})'
                   f'["power"~"line|cable|minor_line"];' for f in frags]
    elements = []
    chunk_n = 1 if args.names_pass else args.chunk
    for i in range(0, len(clauses), chunk_n):
        q = ("[out:json][timeout:150];("
             + "".join(clauses[i:i + chunk_n]) + ");out tags geom;")
        r = subprocess.run(
            ["curl", "-sS", "-A", "Mozilla/5.0 (research; grid-topology)",
             "--max-time", "200", "--data-urlencode", f"data={q}", EP],
            capture_output=True, timeout=220)
        try:
            got = json.loads(r.stdout).get("elements", [])
            elements.extend(got)
            print(f"  chunk {i // args.chunk}: {len(got)} ways", flush=True)
        except Exception as e:   # noqa: BLE001 — throttle etc.; keep going
            print(f"  chunk {i // args.chunk}: FAIL {type(e).__name__}",
                  flush=True)
        time.sleep(args.sleep)

    spath = f"data/{args.region}_lines_supplement.geojson"
    existing = {"type": "FeatureCollection", "features": []}
    have_ids = set()
    if os.path.exists(spath):
        existing = json.load(open(spath, encoding="utf-8"))
        have_ids = {f["properties"].get("osm_way_id")
                    for f in existing["features"]}

    today = dt.date.today().isoformat()
    added = 0
    seen = set()
    for e in elements:
        wid = e.get("id")
        if not wid or wid in seen or wid in have_ids:
            continue
        seen.add(wid)
        geom = e.get("geometry") or []
        if len(geom) < 2:
            continue
        mid = geom[len(geom) // 2]
        if known(mid["lat"], mid["lon"]):
            continue   # already in the extract — not a gap
        props = dict(e.get("tags") or {})
        props.update({"osm_way_id": wid, "supplement_fetched": today,
                      "supplement_source": "overpass orphan-tip around "
                                           f"{args.around}m (I3)"})
        existing["features"].append({
            "type": "Feature",
            "properties": props,
            "geometry": {"type": "LineString",
                         "coordinates": [[p["lon"], p["lat"]] for p in geom]},
        })
        added += 1
    with open(spath, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False)
    print(f"{spath}: +{added} ways (total {len(existing['features'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
