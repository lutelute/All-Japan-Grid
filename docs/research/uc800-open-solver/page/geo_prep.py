"""Compact the national UC geo export + prefecture outlines into page data (projected, simplified)."""
import json, math, sys
from pathlib import Path

geo = json.loads(Path(sys.argv[1]).read_text())
prefs = json.loads(Path(sys.argv[2]).read_text())["features"]
out_path = Path(sys.argv[3])

LON0, LAT1, K = 128.4, 45.65, 70.7
CX = math.cos(math.radians(37.5))
OKI = (15.6, 6.4)          # Okinawa main island moved into the Pacific corner
def proj(lon, lat, oki=False):
    if oki:
        lon, lat = lon + OKI[0], lat + OKI[1]
    return ((lon - LON0) * CX * K, (LAT1 - lat) * K)

REG = {"hokkaido": "北海道", "tohoku": "東北", "tokyo": "東京", "chubu": "中部", "hokuriku": "北陸",
       "kansai": "関西", "chugoku": "中国", "shikoku": "四国", "kyushu": "九州", "okinawa": "沖縄"}
PREF_REG = {1: "hokkaido", **{i: "tohoku" for i in (2, 3, 4, 5, 6, 7, 15)},
            **{i: "tokyo" for i in (8, 9, 10, 11, 12, 13, 14, 19)}, **{i: "chubu" for i in (20, 21, 22, 23, 24)},
            **{i: "hokuriku" for i in (16, 17, 18)}, **{i: "kansai" for i in (25, 26, 27, 28, 29, 30)},
            **{i: "chugoku" for i in (31, 32, 33, 34, 35)}, **{i: "shikoku" for i in (36, 37, 38, 39)},
            **{i: "kyushu" for i in (40, 41, 42, 43, 44, 45, 46)}, 47: "okinawa"}
ANCHOR = {"hokkaido": (142.9, 43.45), "tohoku": (140.75, 39.5), "tokyo": (139.75, 36.15), "chubu": (137.55, 35.35),
          "hokuriku": (136.75, 36.75), "kansai": (135.55, 34.75), "chugoku": (132.75, 34.85), "shikoku": (133.35, 33.65),
          "kyushu": (130.85, 32.65), "okinawa": (127.95, 26.45)}

def dp(pts, tol):
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts); keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1; L = math.hypot(dx, dy) or 1e-9
        best, idx = -1, None
        for i in range(a + 1, b):
            x, y = pts[i]
            d = abs(dy * (x - x1) - dx * (y - y1)) / L
            if d > best:
                best, idx = d, i
        if best > tol:
            keep[idx] = True; stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]

paths = {r: [] for r in REG}
for f in prefs:
    pid = f["properties"]["pref_id"]; r = PREF_REG[pid]; oki = pid == 47
    polys = [f["geometry"]["coordinates"]] if f["geometry"]["type"] == "Polygon" else f["geometry"]["coordinates"]
    for poly in polys:
        ring = poly[0]
        clon = sum(p[0] for p in ring) / len(ring); clat = sum(p[1] for p in ring) / len(ring)
        if oki:
            if not (127.0 < clon < 128.6 and 25.9 < clat < 27.0):
                continue
        elif not (127 < clon < 146.5 and 30.0 < clat < 46) or (clon > 135 and clat < 31.5):
            continue
        pts = [proj(lon, lat, oki) for lon, lat in ring]
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        if max(xs) - min(xs) < 3 and max(ys) - min(ys) < 3:
            continue
        # closed ring: split at the point farthest from the start, simplify each half
        far = max(range(len(pts)), key=lambda i: (pts[i][0] - pts[0][0]) ** 2 + (pts[i][1] - pts[0][1]) ** 2)
        pts = dp(pts[:far + 1], 0.9) + dp(pts[far:], 0.9)[1:]
        if len(pts) < 4:
            continue
        paths[r].append("M" + "L".join(f"{x:.0f},{y:.0f}" for x, y in pts) + "Z")

FUEL = {"nuclear": "nuc", "coal": "coal", "lng": "lng", "oil": "oil", "hydro": "hydro", "pumped_hydro": "hydro"}
regions = list(REG)
plants, nocoord = [], {}
for g in geo["generators"]:
    fuel = FUEL.get(g["fuel"], "other")
    on = sum(1 << t for t, v in enumerate(g["on"]) if v)
    row = {"f": fuel, "raw": g["fuel"], "c": round(g["cap"]), "r": regions.index(g["region"]), "n": g["name"] or g["id"],
           "m": [round(x) for x in g["mw"]], "o": on}
    if g["lat"]:
        x, y = proj(g["lon"], g["lat"], g["region"] == "okinawa" or g["lat"] < 27.5)
        row["x"], row["y"] = round(x, 1), round(y, 1)
    else:
        nocoord.setdefault(g["region"], [0, 0]); nocoord[g["region"]][0] += 1; nocoord[g["region"]][1] += g["cap"]
    plants.append(row)

T = geo["hours"]
def total(series):
    return [round(sum(v[t] for v in series.values())) for t in range(T)]
bands = {k: [0.0] * T for k in ["nuc", "coal", "lng", "oil", "hydro", "solar", "wind", "other", "charge"]}
for g in geo["generators"]:
    fuel = FUEL.get(g["fuel"], "other")
    for t, p in enumerate(g["mw"]):
        if p < 0:
            bands["charge"][t] += p
        else:
            bands[fuel][t] += p
for t in range(T):
    bands["hydro"][t] += sum(v[t] for v in geo["hydro_ror"].values())
    bands["solar"][t] = sum(v[t] for v in geo["solar"].values())
    bands["wind"][t] = sum(v[t] for v in geo["wind"].values())
bands = {k: [round(x) for x in v] for k, v in bands.items()}
demand = total(geo["demand"])
resid = [sum(bands[k][t] for k in bands) - demand[t] for t in range(T)]

xs = [p["x"] for p in plants if "x" in p]; ys = [p["y"] for p in plants if "y" in p]
anchors = {r: [round(v, 1) for v in proj(*ANCHOR[r], r == "okinawa")] for r in REG}
ox, oy = anchors["okinawa"]
out = {"meta": {k: geo[k] for k in ["scenario", "status", "termination", "total_cost", "gap", "verified", "solve_s", "hours",
                                    "objective_overstatement"]},
       "vb": [round(14.3 * CX / math.cos(math.radians(37.5)) * K), round((LAT1 - 30.25) * K)],
       "regions": [{"k": r, "name": REG[r], "x": anchors[r][0], "y": anchors[r][1], "d": "".join(paths[r]),
                    "demand": [round(v) for v in geo["demand"][r]], "solar": [round(v) for v in geo["solar"].get(r, [0] * T)]}
                   for r in REG],
       "oki_box": [round(ox - 62), round(oy - 70), 124, 118],
       "plants": plants, "nocoord": nocoord,
       "links": [{"a": regions.index(l["from"]), "b": regions.index(l["to"]), "cap": l["cap"], "name": l["name"],
                  "f": [round(x) for x in l["flow"]]} for l in geo["links"]],
       "bands": bands, "demand": demand}
s = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
out_path.write_text(s)
print(len(s), "bytes; path pts", sum(d.count("L") for d in (r["d"] for r in out["regions"])))
print("vb", out["vb"], "plants x range", min(xs), max(xs), "y", min(ys), max(ys))
print("balance residual (bands - gross demand)", min(resid), max(resid))
print("nocoord", nocoord)
print("anchors", anchors)
