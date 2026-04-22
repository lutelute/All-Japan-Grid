#!/usr/bin/env python3
"""
GeoJSON 軽量化スクリプト

1. 座標精度を 7桁 → 4桁 (送電線・変電所)
2. plants の不要プロパティを削除 (使用するのは name/fuel_type/capacity_mw のみ)
3. geometry simplification (lines のみ、Douglas-Peucker tolerance=0.0001°)
"""

import json
import math
from pathlib import Path

DATA = Path(__file__).parent.parent / "docs" / "data"

COORD_PRECISION = 4        # 4桁 ≈ 11m 精度 (可視化には十分)
LINE_TOLERANCE   = 0.0001  # ~10m、zoom6-12 では不可視

# plants で保持するプロパティ (描画に必要な最小セット)
PLANT_KEEP_PROPS = {"name", "fuel_type", "capacity_mw", "_display_name", "_region", "_region_ja"}

# ── ユーティリティ ─────────────────────────────────────────
def round_coord(c):
    if isinstance(c[0], (int, float)):
        return [round(c[0], COORD_PRECISION), round(c[1], COORD_PRECISION)]
    return [round_coord(p) for p in c]

def round_geom(geom):
    if geom is None:
        return geom
    t = geom["type"]
    if t == "Point":
        geom["coordinates"] = round_coord(geom["coordinates"])
    elif t in ("LineString", "MultiPoint"):
        geom["coordinates"] = round_coord(geom["coordinates"])
    elif t in ("Polygon", "MultiLineString"):
        geom["coordinates"] = [round_coord(ring) for ring in geom["coordinates"]]
    elif t == "MultiPolygon":
        geom["coordinates"] = [[round_coord(ring) for ring in poly] for poly in geom["coordinates"]]
    return geom

# Douglas-Peucker simplification
def point_line_dist(p, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    if dx == 0 and dy == 0:
        return math.hypot(p[0]-a[0], p[1]-a[1])
    t = ((p[0]-a[0])*dx + (p[1]-a[1])*dy) / (dx*dx + dy*dy)
    t = max(0, min(1, t))
    return math.hypot(p[0]-a[0]-t*dx, p[1]-a[1]-t*dy)

def rdp(pts, tol):
    if len(pts) < 3:
        return pts
    dmax, idx = 0, 0
    for i in range(1, len(pts)-1):
        d = point_line_dist(pts[i], pts[0], pts[-1])
        if d > dmax:
            dmax, idx = d, i
    if dmax > tol:
        left  = rdp(pts[:idx+1], tol)
        right = rdp(pts[idx:],   tol)
        return left[:-1] + right
    return [pts[0], pts[-1]]

def simplify_coords(coords, tol):
    if not coords or not isinstance(coords[0], (list, tuple)):
        return coords
    if isinstance(coords[0][0], (int, float)):
        return rdp(coords, tol)
    return [simplify_coords(ring, tol) for ring in coords]

def simplify_geom(geom, tol):
    if geom is None:
        return geom
    t = geom["type"]
    if t == "LineString":
        geom["coordinates"] = simplify_coords(geom["coordinates"], tol)
    elif t == "MultiLineString":
        geom["coordinates"] = [simplify_coords(ls, tol) for ls in geom["coordinates"]]
    return geom

# ── 処理関数 ─────────────────────────────────────────────

def slim_lines(path: Path, simplify=True):
    d = json.loads(path.read_text(encoding="utf-8"))
    before = len(json.dumps(d, separators=(",",":")))
    for f in d["features"]:
        if simplify:
            simplify_geom(f["geometry"], LINE_TOLERANCE)
        round_geom(f["geometry"])
        # properties はそのまま (4プロパティのみで元々軽い)
    out = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    after = len(out)
    path.write_text(out, encoding="utf-8")
    print(f"  {path.name}: {before/1e6:.1f}MB → {after/1e6:.1f}MB ({100*(before-after)/before:.0f}%削減)")

def slim_subs(path: Path):
    d = json.loads(path.read_text(encoding="utf-8"))
    before = len(json.dumps(d, separators=(",",":")))
    for f in d["features"]:
        round_geom(f["geometry"])
    out = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    after = len(out)
    path.write_text(out, encoding="utf-8")
    print(f"  {path.name}: {before/1e6:.1f}MB → {after/1e6:.1f}MB ({100*(before-after)/before:.0f}%削減)")

def slim_plants(path: Path):
    d = json.loads(path.read_text(encoding="utf-8"))
    before = len(json.dumps(d, separators=(",",":")))
    for f in d["features"]:
        round_geom(f["geometry"])
        p = f["properties"]
        # 保持キーのみに絞る
        f["properties"] = {k: v for k, v in p.items() if k in PLANT_KEEP_PROPS}
    out = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    after = len(out)
    path.write_text(out, encoding="utf-8")
    print(f"  {path.name}: {before/1e6:.1f}MB → {after/1e6:.1f}MB ({100*(before-after)/before:.0f}%削減)")

# ── メイン ───────────────────────────────────────────────

def main():
    print("=== 送電線 (simplify + coord precision) ===")
    for name in ["lines_275kv.geojson", "lines_154kv.geojson", "lines_all.geojson"]:
        p = DATA / name
        if p.exists(): slim_lines(p, simplify=True)

    print("\n=== 変電所 (coord precision only) ===")
    for name in ["subs_275kv.geojson", "subs_154kv.geojson", "subs_all.geojson"]:
        p = DATA / name
        if p.exists(): slim_subs(p)

    print("\n=== 発電所 (property pruning + coord precision) ===")
    for name in ["plants_utility.geojson", "plants_ipp.geojson", "plants_all.geojson"]:
        p = DATA / name
        if p.exists(): slim_plants(p)

if __name__ == "__main__":
    main()
