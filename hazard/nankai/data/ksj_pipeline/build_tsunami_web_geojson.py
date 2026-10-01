#!/usr/bin/env python3
"""Web 表示用の軽量 GeoJSON を試作する (dissolved 層 → 微小部分を除去 → simplify → (pref, depth_rank) で再 dissolve).
原典を忠実に保つ層ではない (微小ポリゴンを落とす) ので、解析には gpkg を使うこと。50MB 以下に収まった場合のみ出力を残す."""
import os, sys, time, warnings
import geopandas as gpd, pandas as pd, shapely
from a40_common import DER, CEA
warnings.filterwarnings("ignore")
MIN_PART_KM2 = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0025   # 50m x 50m
TOL = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0005
MAX_MB = 50
OUT = os.path.join(DER, "tsunami_inundation_A40_web.geojson")
t0 = time.time()
d = gpd.read_file(os.path.join(DER, "tsunami_inundation_A40.gpkg"), layer="inundation_dissolved")
tot = d.area_km2.sum()
e = d.explode(index_parts=False, ignore_index=True)
e["part_km2"] = e.to_crs(CEA).area / 1e6
keep = e[e.part_km2 >= MIN_PART_KM2].copy()
dropped_km2 = float(e.part_km2.sum() - keep.part_km2.sum())
print(f"parts {len(e):,} -> {len(keep):,}; dropped area {dropped_km2:.1f} km2 of {tot:.1f} ({100*dropped_km2/tot:.2f}%) [{time.time()-t0:.0f}s]", flush=True)
keep["geometry"] = keep.geometry.simplify(TOL, preserve_topology=True)
keep = keep[~keep.geometry.is_empty]
w = keep.dissolve(by=["pref_code", "depth_rank"], aggfunc={"part_km2": "sum"}).reset_index()
w = w.rename(columns={"part_km2": "area_km2"})
w["area_km2"] = w.area_km2.round(2)
w["depth_rank"] = w.depth_rank.astype(int)
if os.path.exists(OUT): os.remove(OUT)
w.to_file(OUT, driver="GeoJSON", COORDINATE_PRECISION=5)
mb = os.path.getsize(OUT) / 1e6
print(f"rows {len(w)} size {mb:.1f} MB [{time.time()-t0:.0f}s]")
if mb > MAX_MB:
    os.remove(OUT); print(f"> {MAX_MB} MB -> removed")
else:
    print(f"kept {OUT}")
