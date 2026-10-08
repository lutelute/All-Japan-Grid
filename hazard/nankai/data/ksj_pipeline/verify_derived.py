#!/usr/bin/env python3
"""derived/ の成果物を独立に検算する (層一覧・件数・CRS・ランク分布・既知地点の点内包テスト)."""
import os, json, warnings
import geopandas as gpd, pandas as pd, pyogrio, shapely
warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); DER = os.path.join(os.path.dirname(HERE), "derived")
G = os.path.join(DER, "tsunami_inundation_A40.gpkg")
print("layers:", pyogrio.list_layers(G).tolist())
for lyr in ("inundation", "inundation_dissolved"):
    info = pyogrio.read_info(G, layer=lyr); print(lyr, "features", info["features"], "crs", info["crs"], "fields", info["fields"].tolist())
d = gpd.read_file(G, layer="inundation_dissolved")
print("dissolved rows", len(d), "prefs", sorted(d.pref_code.unique()), "total area km2", round(d.area_km2.sum(), 1))
print(d.groupby("depth_rank").agg(rows=("area_km2", "size"), area_km2=("area_km2", "sum")).round(1).to_string())
bad = d[(d.depth_max_m.notna()) & (d.depth_min_m >= d.depth_max_m)]
print("min>=max rows:", len(bad))
print("null rank rows:", int(d.depth_rank.isna().sum()))
# raw layer: 行数を県別に (attribute only read)
raw = pyogrio.read_dataframe(G, layer="inundation", read_geometry=False)
print("raw rows", len(raw)); print(raw.groupby("pref_code").size().to_string())
# 点内包テスト: 既知の低地・高台
pts = {"浜岡原発付近(御前崎)": (138.142, 34.623), "高知市役所": (133.531, 33.559), "名古屋駅": (136.881, 35.171),
       "大阪駅": (135.495, 34.702), "宮崎市役所": (131.424, 31.908), "東京駅": (139.767, 35.681), "富士山頂": (138.727, 35.363),
       "須崎市役所(高知)": (133.283, 33.397), "串本町役場": (135.777, 33.474), "豊岡市役所": (134.820, 35.544)}
tree = shapely.STRtree(d.geometry.values)
for k, (x, y) in pts.items():
    p = shapely.Point(x, y); idx = tree.query(p, predicate="intersects")
    hits = d.iloc[idx][["pref_code", "source_version", "depth_class_src", "depth_rank"]].values.tolist()
    print(f"  {k}: {hits if len(hits) else '浸水想定外'}")
m = gpd.read_file(os.path.join(DER, "municipalities.gpkg"), layer="muni")
print("muni rows", len(m), "crs", m.crs.to_epsg(), "codes unique", m.muni_code.is_unique, "prefs", m.pref_code.nunique())
j = gpd.sjoin(gpd.GeoDataFrame(geometry=[shapely.Point(v) for v in pts.values()], crs=4326), m, predicate="within")
print(j[["muni_code", "pref_name", "muni_name"]].assign(pt=list(pts.keys())[:len(j)]).to_string())
s = json.load(open(os.path.join(DER, "tsunami_inundation_A40_summary.json")))
print("simplified geojson:", s["_simplified_geojson"], "gpkg MB", s["_gpkg_size_mb"])
