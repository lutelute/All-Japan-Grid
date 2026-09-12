#!/usr/bin/env python3
"""複数版がある県について、市区町村ごとに各版の浸水面積(km2)を比較し、新版が全域置換か部分更新かを判定する材料を出す."""
import os, sys, warnings
import geopandas as gpd, pandas as pd
from a40_common import list_zips, load_version, DER, CEA
warnings.filterwarnings("ignore")
muni = gpd.read_file(os.path.join(DER, "municipalities.gpkg"), layer="muni")[["muni_code", "muni_name", "geometry"]]
zips = list_zips()
prefs = [p for p in sorted(zips) if len(zips[p]) > 1]
if len(sys.argv) > 1: prefs = sys.argv[1:]
for p in prefs:
    print(f"\n===== pref {p}: versions {[v for v, _ in zips[p]]}")
    tabs = []
    for v, z in zips[p]:
        g = load_version(z)
        g["area_km2"] = g.to_crs(CEA).area / 1e6
        pts = g.copy(); pts["geometry"] = g.representative_point()
        j = gpd.sjoin(pts, muni[muni.muni_code.str.startswith(p)], how="left", predicate="within")
        t = j.groupby("muni_code", dropna=False)["area_km2"].sum().rename(f"v{v}")
        tabs.append(t)
        print(f"  A40-{v}: n={len(g)} total={g.area_km2.sum():.1f} km2 unparsed={g.depth_rank.isna().sum()} classes={sorted(g.depth_class_src.dropna().unique().tolist())}")
        print(f"     bbox={[round(x,3) for x in g.total_bounds]}")
    T = pd.concat(tabs, axis=1).fillna(0.0)
    T = T.join(muni.set_index("muni_code")["muni_name"], how="left")
    newest = T.columns[0]
    older = [c for c in T.columns if c.startswith("v") and c != newest]
    for c in older:
        only_old = T[(T[c] > 0) & (T[newest] == 0)]
        both = T[(T[c] > 0) & (T[newest] > 0)]
        print(f"  -- {c} vs {newest}: munis only in {c}: {len(only_old)} (area {only_old[c].sum():.1f} km2 = {100*only_old[c].sum()/max(T[c].sum(),1e-9):.1f}% of {c}); both: {len(both)}; only in {newest}: {int(((T[c]==0)&(T[newest]>0)).sum())}")
        if len(only_old): print(only_old[[c, newest, "muni_name"]].round(2).to_string())
    print(T.round(2).sort_values(newest, ascending=False).head(60).to_string())
