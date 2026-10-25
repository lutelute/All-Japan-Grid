"""The transmission network for the page's maps: real routes of lines >= 110 kV from the canonical built model,
projected like the Japan map and simplified. usage: net_prep.py built/all.json out.json"""
import json, math, sys

LON0, LAT1, K = 128.4, 45.65, 70.7
CX = math.cos(math.radians(37.5))
OKI = (15.6, 6.4)


def proj(lat, lon):
    if lat < 27.5:
        lon, lat = lon + OKI[0], lat + OKI[1]
    return ((lon - LON0) * CX * K, (LAT1 - lat) * K)


def simplify(pts, eps):
    if len(pts) < 3:
        return pts
    a, b = pts[0], pts[-1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy) or 1e-9
    i, dmax = 0, -1
    for j in range(1, len(pts) - 1):
        d = abs(dy * pts[j][0] - dx * pts[j][1] + b[0] * a[1] - b[1] * a[0]) / L
        if d > dmax:
            i, dmax = j, d
    if dmax <= eps:
        return [a, b]
    return simplify(pts[:i + 1], eps)[:-1] + simplify(pts[i:], eps)


def path_of(e):
    raw = e.get("path")
    pts = json.loads(raw) if isinstance(raw, str) else raw
    if not pts:
        pts = [json.loads(e["a"]) if isinstance(e["a"], str) else e["a"], json.loads(e["b"]) if isinstance(e["b"], str) else e["b"]]
    return [proj(p[0], p[1]) for p in pts if p and p[0] is not None]


def d_of(pts):
    return "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts)


if __name__ == "__main__":
    b = json.load(open(sys.argv[1]))
    cls = {"500": [], "275": [], "154": []}
    for e in b["edges"]:
        kv = float(e["kv"] or 0)
        if kv < 110:
            continue
        c = "500" if kv >= 500 else "275" if kv >= 187 else "154"
        pts = simplify(path_of(e), 0.5)
        if len(pts) >= 2:
            cls[c].append(d_of(pts))
    subs = []
    for n in b["nodes"]:
        if float(n["kv"] or 0) >= 154 and int(n.get("deg") or 0) >= 3 and n["lat"] is not None:
            x, y = proj(float(n["lat"]), float(n["lon"]))
            subs.append(f"M{x:.1f},{y:.1f}h0")
    out = {"cls": {k: "".join(v) for k, v in cls.items()}, "n": {k: len(v) for k, v in cls.items()}, "subs": "".join(subs), "n_subs": len(subs)}
    json.dump(out, open(sys.argv[2], "w"), separators=(",", ":"))
    print(out["n"], out["n_subs"], len(json.dumps(out)) // 1024, "KB")
