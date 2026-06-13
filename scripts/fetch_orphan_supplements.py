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


def _base_grid(region: str, cell: float = 0.001):
    """基底extractのみの頂点グリッド(連鎖完結=基底網への到達の判定用)。"""
    grid = set()
    path = f"data/{region}_lines.geojson"
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
    return grid


def _other_region_grid(region: str, cell: float = 0.001):
    """他9地域の基底線レイヤの頂点グリッド(縄張り規律: 既在線の越境取込を防ぐ)。"""
    from src.regions import REGIONS
    g = set()
    for r in REGIONS:
        if r == region:
            continue
        path = f"data/{r}_lines.geojson"
        if not os.path.exists(path):
            continue
        d = json.load(open(path, encoding="utf-8"))
        for ft in d["features"]:
            gm = ft["geometry"]
            if gm["type"] == "LineString":
                cs = gm["coordinates"]
            elif gm["type"] == "MultiLineString":
                cs = [c for part in gm["coordinates"] for c in part]
            else:
                continue
            for lon, la in cs[::3]:
                g.add((round(la / cell), round(lon / cell)))
    return g


def _run_bulk(args, grid, cell):
    """地域bboxタイルで power=line|cable を全取得し欠落分を一括補完。"""
    from src.powerflow.snapped_topology import _freq_excluded
    from src.regions import REGION_FREQUENCY_HZ
    region_hz = REGION_FREQUENCY_HZ.get(args.region, 50)
    other = _other_region_grid(args.region, cell)
    own_base = _base_grid(args.region, cell)

    def in_other(la, lo):
        ci, cj = round(la / cell), round(lo / cell)
        return any((ci + di, cj + dj) in other
                   for di in (-1, 0, 1) for dj in (-1, 0, 1))

    def near_own(la, lo, r=20):   # ~2km — 境界共有帯は自網扱い
        ci, cj = round(la / cell), round(lo / cell)
        return any((ci + di, cj + dj) in own_base
                   for di in range(-r, r + 1) for dj in range(-r, r + 1))

    d0 = json.load(open(f"data/{args.region}_lines.geojson", encoding="utf-8"))
    las, los = [], []
    for ft in d0["features"][::5]:
        g = ft["geometry"]
        cs = g["coordinates"] if g["type"] == "LineString" else (
            [c for pt_ in g["coordinates"] for c in pt_]
            if g["type"] == "MultiLineString" else [])
        for lon, la in cs[::4]:
            las.append(la)
            los.append(lon)
    lo0, lo1 = min(los), max(los)
    la0, la1 = min(las), max(las)
    n = args.bulk
    spath = f"data/{args.region}_lines_supplement.geojson"
    sub_path = f"data/{args.region}_substations_supplement.geojson"
    plant_path = f"data/{args.region}_plants_supplement.geojson"
    existing = {"type": "FeatureCollection", "features": []}
    sub_existing = {"type": "FeatureCollection", "features": []}
    plant_existing = {"type": "FeatureCollection", "features": []}
    if os.path.exists(plant_path):
        plant_existing = json.load(open(plant_path, encoding="utf-8"))
    have_ids = set()
    sub_have = set()
    if os.path.exists(spath):
        existing = json.load(open(spath, encoding="utf-8"))
        have_ids = {f["properties"].get("osm_way_id")
                    for f in existing["features"]}
    if os.path.exists(sub_path):
        sub_existing = json.load(open(sub_path, encoding="utf-8"))
        sub_have = {f["properties"].get("osm_way_id")
                    for f in sub_existing["features"]}
    # 既存変電所の座標グリッド(重複補完の防止)
    sub_grid = set()
    for sp_ in (f"data/{args.region}_substations.geojson", sub_path):
        if not os.path.exists(sp_):
            continue
        for ft in json.load(open(sp_, encoding="utf-8"))["features"]:
            g = ft["geometry"]
            if g["type"] == "Point":
                pts = [g["coordinates"]]
            elif g["type"] == "Polygon":
                pts = g["coordinates"][0]
            elif g["type"] == "MultiPolygon":
                pts = g["coordinates"][0][0]
            else:
                continue
            for lon, la in pts:
                sub_grid.add((round(la / cell), round(lon / cell)))
    today = dt.date.today().isoformat()
    added = 0
    sub_added = 0
    seen_ids = set()
    for i in range(n):
        for j in range(n):
            bb = (f"{la0 + (la1-la0)*i/n:.3f},{lo0 + (lo1-lo0)*j/n:.3f},"
                  f"{la0 + (la1-la0)*(i+1)/n:.3f},{lo0 + (lo1-lo0)*(j+1)/n:.3f}")
            q = (f'[out:json][timeout:180];(way({bb})'
                 f'["power"~"^(line|cable)$"];'
                 f'way({bb})["power"="substation"];'
                 f'node({bb})["power"="substation"];'
                 f'way({bb})["power"="plant"];);out tags geom;')
            ok = False
            for attempt in (1, 2):
                r = subprocess.run(
                    ["curl", "-sS", "-A",
                     "Mozilla/5.0 (research; grid-topology)",
                     "--max-time", "240", "--data-urlencode", f"data={q}", EP],
                    capture_output=True, timeout=260)
                try:
                    els = json.loads(r.stdout).get("elements", [])
                    ok = True
                    break
                except Exception:   # noqa: BLE001
                    print(f"  tile {i},{j} attempt{attempt} FAIL — 60s冷却",
                          flush=True)
                    time.sleep(60)
            if not ok:
                print(f"  tile {i},{j}: 取得不能(スキップ・再実行で回収可)",
                      flush=True)
                continue
            t_add = 0
            for e in els:
                wid = e.get("id")
                tags_ = e.get("tags") or {}
                if tags_.get("power") in ("substation", "plant"):
                    is_plant = tags_.get("power") == "plant"
                    if wid in sub_have or wid in seen_ids:
                        continue
                    seen_ids.add(wid)
                    if e.get("type") == "node":
                        la_, lo_ = e.get("lat"), e.get("lon")
                        geom_s = {"type": "Point", "coordinates": [lo_, la_]}
                    else:
                        g_ = e.get("geometry") or []
                        if len(g_) < 3:
                            continue
                        la_ = sum(p["lat"] for p in g_) / len(g_)
                        lo_ = sum(p["lon"] for p in g_) / len(g_)
                        geom_s = {"type": "Polygon",
                                  "coordinates": [[[p["lon"], p["lat"]]
                                                   for p in g_]]}
                    ci_, cj_ = round(la_ / cell), round(lo_ / cell)
                    if any((ci_ + di, cj_ + dj) in sub_grid
                           for di in (-1, 0, 1) for dj in (-1, 0, 1)):
                        continue
                    props_ = dict(tags_)
                    props_.update({"osm_way_id": wid,
                                   "supplement_fetched": today,
                                   "supplement_source":
                                       "overpass bulk bbox (I3)"})
                    target = plant_existing if is_plant else sub_existing
                    target["features"].append(
                        {"type": "Feature", "properties": props_,
                         "geometry": geom_s})
                    sub_have.add(wid)
                    sub_grid.add((ci_, cj_))
                    sub_added += 1
                    continue
                if not wid or wid in seen_ids or wid in have_ids:
                    continue
                seen_ids.add(wid)
                geom = e.get("geometry") or []
                if len(geom) < 2:
                    continue
                mid = geom[len(geom) // 2]
                ci, cj = round(mid["lat"] / cell), round(mid["lon"] / cell)
                if any((ci + di, cj + dj) in grid
                       for di in (-1, 0, 1) for dj in (-1, 0, 1)):
                    continue
                # 縄張り規律(台帳99): 他地域に既在 かつ 自網から遠い(>2km)
                # 線は取り込まない(中部60Hz・東北の深部流入を防ぎつつ、
                # 県境の共有帯は保持 — 一律除外は正当な境界設備まで削った)
                if (in_other(mid["lat"], mid["lon"])
                        and not near_own(mid["lat"], mid["lon"])):
                    continue
                # 地域の同期網テスト(_freq_excludedと同基準)
                if _freq_excluded(e.get("tags") or {}, region_hz):
                    continue
                props = dict(e.get("tags") or {})
                props.update({"osm_way_id": wid,
                              "supplement_fetched": today,
                              "supplement_source": "overpass bulk bbox (I3)"})
                existing["features"].append({
                    "type": "Feature", "properties": props,
                    "geometry": {"type": "LineString",
                                 "coordinates": [[p["lon"], p["lat"]]
                                                 for p in geom]},
                })
                have_ids.add(wid)
                for pt in geom:
                    grid.add((round(pt["lat"] / cell),
                              round(pt["lon"] / cell)))
                added += 1
                t_add += 1
            print(f"  tile {i},{j}: {len(els)}取得 → +{t_add}", flush=True)
            time.sleep(args.sleep)
    with open(spath, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False)
    with open(sub_path, "w", encoding="utf-8") as f:
        json.dump(sub_existing, f, ensure_ascii=False)
    with open(plant_path, "w", encoding="utf-8") as f:
        json.dump(plant_existing, f, ensure_ascii=False)
    print(f"{spath}: bulk +{added} (total {len(existing['features'])})")
    print(f"{sub_path}: +{sub_added} substations "
          f"(total {len(sub_existing['features'])})")
    return 0


def _run_chase(args, grid, cell):
    """端点追跡: 断片線の実端点→around:300→受理ウェイの先端→…(最大Nラウンド)。"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from collections import defaultdict
    from src.powerflow.snapped_topology import build_network_snapped

    base = _base_grid(args.region, cell)

    def near(gset, la, lo):
        ci, cj = round(la / cell), round(lo / cell)
        return any((ci + di, cj + dj) in gset
                   for di in (-1, 0, 1) for dj in (-1, 0, 1))

    print("断片の実端点を抽出中(ビルド)...", flush=True)
    net = build_network_snapped(args.region)
    subs = {s.id for s in net.substations if "_jct_" not in s.id}
    adj = defaultdict(set)
    line_of = defaultdict(list)
    for ln in net.transmission_lines:
        if "_xfmr_" in ln.id:
            continue
        a, b = ln.from_substation_id, ln.to_substation_id
        adj[a].add(b)
        adj[b].add(a)
        line_of[a].append(ln)
        line_of[b].append(ln)
    seen = set()
    centers = []
    for n in list(adj):
        if n in seen:
            continue
        stack = [n]
        comp = set()
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            comp.add(x)
            stack.extend(adj[x] - seen)
        if comp & subs:
            continue
        for c in comp:
            for ln in line_of[c]:
                for la, lo in (ln.coordinates[0], ln.coordinates[-1]):
                    centers.append((la, lo))
    centers = list({(round(a, 5), round(b, 5)) for a, b in centers})
    print(f"chase種(断片端点): {len(centers)}", flush=True)

    spath = f"data/{args.region}_lines_supplement.geojson"
    existing = {"type": "FeatureCollection", "features": []}
    have_ids = set()
    if os.path.exists(spath):
        existing = json.load(open(spath, encoding="utf-8"))
        have_ids = {f["properties"].get("osm_way_id")
                    for f in existing["features"]}
    today = dt.date.today().isoformat()
    total_added = 0
    completed = 0
    for rnd in range(1, args.chase + 1):
        if not centers:
            break
        clauses = [f'way(around:300,{la},{lo})'
                   f'["power"~"line|cable|minor_line"];'
                   for la, lo in centers]
        elements = []
        failed = []
        for i in range(0, len(clauses), args.chunk):
            q = ("[out:json][timeout:150];("
                 + "".join(clauses[i:i + args.chunk]) + ");out tags geom;")
            r = subprocess.run(
                ["curl", "-sS", "-A",
                 "Mozilla/5.0 (research; grid-topology)",
                 "--max-time", "200", "--data-urlencode", f"data={q}", EP],
                capture_output=True, timeout=220)
            try:
                elements.extend(json.loads(r.stdout).get("elements", []))
            except Exception:   # noqa: BLE001
                failed.append(i)
            time.sleep(args.sleep)
        if failed and len(failed) > len(clauses) / args.chunk / 2:
            print(f"  round{rnd}: 失敗率高 — 300s冷却して再試行", flush=True)
            time.sleep(300)
        for i in failed:
            q = ("[out:json][timeout:150];("
                 + "".join(clauses[i:i + args.chunk]) + ");out tags geom;")
            r = subprocess.run(
                ["curl", "-sS", "-A",
                 "Mozilla/5.0 (research; grid-topology)",
                 "--max-time", "200", "--data-urlencode", f"data={q}", EP],
                capture_output=True, timeout=220)
            try:
                elements.extend(json.loads(r.stdout).get("elements", []))
            except Exception:   # noqa: BLE001
                pass
            time.sleep(args.sleep)
        next_centers = []
        added = 0
        seen_ids = set()
        for e in elements:
            wid = e.get("id")
            if not wid or wid in seen_ids or wid in have_ids:
                continue
            seen_ids.add(wid)
            geom = e.get("geometry") or []
            if len(geom) < 2:
                continue
            mid = geom[len(geom) // 2]
            if near(grid, mid["lat"], mid["lon"]):
                continue
            props = dict(e.get("tags") or {})
            props.update({"osm_way_id": wid, "supplement_fetched": today,
                          "supplement_source": f"overpass chase r{rnd} (I3)"})
            existing["features"].append({
                "type": "Feature", "properties": props,
                "geometry": {"type": "LineString",
                             "coordinates": [[p["lon"], p["lat"]]
                                             for p in geom]},
            })
            have_ids.add(wid)
            added += 1
            for pt in (geom[0], geom[-1]):
                if near(base, pt["lat"], pt["lon"]):
                    completed += 1      # 基底網に到達=連鎖完結
                else:
                    next_centers.append((round(pt["lat"], 5),
                                         round(pt["lon"], 5)))
            for pt in geom:
                grid.add((round(pt["lat"] / cell),
                          round(pt["lon"] / cell)))
        total_added += added
        print(f"  round{rnd}: 種{len(centers)} → 受理+{added} 完結端{completed} "
              f"次種{len(set(next_centers))}", flush=True)
        centers = list(set(next_centers))
    with open(spath, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False)
    print(f"{spath}: chase計+{total_added} (total {len(existing['features'])}) "
          f"基底網到達端 {completed}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", required=True)
    ap.add_argument("--census",
                    default="docs/reports/orphan_census_2026-06-13.json")
    ap.add_argument("--around", type=int, default=400)
    ap.add_argument("--chunk", type=int, default=25)
    ap.add_argument("--sleep", type=float, default=10.0)
    ap.add_argument("--bulk", type=int, default=0,
                    help="バルク補完: 地域bboxをN×Nタイルに分割し power=line|cable"
                         "を全取得→幾何差分→欠落ウェイを一括補完(chaseの上位互換。"
                         "スコープは基底と同じ line|cable、minor_lineは含めない)")
    ap.add_argument("--chase", type=int, default=0,
                    help="端点追跡パス: 断片線の実端点を種に around:300 を"
                         "N ラウンド再帰(受理ウェイの先端→次の種)。"
                         "基底網の頂点に到達した連鎖は完結として停止")
    ap.add_argument("--names-pass", action="store_true",
                    help="第2パス: 断片+サプリ線の名称で回廊全体を一括補完"
                         "(佐久間東幹線型の連鎖を一発で完結させる)")
    args = ap.parse_args(argv)

    census = json.load(open(args.census, encoding="utf-8"))
    frags = census["regions"].get(args.region) or []
    if not frags and not args.chase:
        print(f"no fragments for {args.region} in census")
        return 0

    grid, cell = _vertex_grid(args.region)

    def known(la, lo):
        ci, cj = round(la / cell), round(lo / cell)
        return any((ci + di, cj + dj) in grid
                   for di in (-1, 0, 1) for dj in (-1, 0, 1))

    if args.bulk:
        return _run_bulk(args, grid, cell)
    if args.chase:
        return _run_chase(args, grid, cell)

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
