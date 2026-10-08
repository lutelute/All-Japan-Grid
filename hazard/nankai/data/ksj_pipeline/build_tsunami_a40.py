#!/usr/bin/env python3
"""A40 津波浸水想定 (国土数値情報) → hazard/nankai/data/derived/tsunami_inundation_A40.gpkg (+ simplified geojson)

入力: external/ksj_A40/A40-VV_PP_GML.zip (fetch_ksj.sh で取得; 対象県の全年版)
出力:
  derived/tsunami_inundation_A40.gpkg
     layer "inundation"           : 原典ポリゴンそのまま (EPSG:4326)
        [pref_code, depth_rank, depth_min_m, depth_max_m, depth_class_src, source_version, geometry]
     layer "inundation_dissolved" : (pref_code, source_version, depth_class_src) で dissolve
        [pref_code, depth_rank, depth_min_m, depth_max_m, depth_class_src, source_version, area_km2, geometry]
  derived/tsunami_inundation_A40_simplified.geojson : dissolved 層を simplify(0.0005deg) (60MB超なら出力しない)
  derived/tsunami_inundation_A40_summary.json      : 県別統計 (manifest 用)

版の扱い (POLICY): 既定は最新版のみ ("newest"). MLIT は「過年度分と合わせて利用/重複箇所は最新を優先」と注記して
おり、新版が部分更新の県は "merge_muni" = 最新版 + 最新版に浸水域が無い市区町村に限り旧版で補完 (市区町村単位).
判定材料は analyze_a40_versions.py の出力 (docs/DATA_MANIFEST.md に記載).
"""
import json, os, sys, time, warnings, math
import geopandas as gpd, pandas as pd, shapely
from a40_common import list_zips, load_version, DER, CEA
from a40_depth import RANKS, rank_label
warnings.filterwarnings("ignore")

POLICY = {
    # pref: ("newest", None) | ("merge_muni", [older versions to supplement with, newest→oldest])
    "28": ("merge_muni", [16]),   # 兵庫: A40-18 は部分更新 (analyze_a40_versions.py 参照)
}
OUT = os.path.join(DER, "tsunami_inundation_A40.gpkg")
OUTJ = os.path.join(DER, "tsunami_inundation_A40_simplified.geojson")
OUTS = os.path.join(DER, "tsunami_inundation_A40_summary.json")
SIMPLIFY_TOL = 0.0005
GEOJSON_MAX_MB = 60

muni = gpd.read_file(os.path.join(DER, "municipalities.gpkg"), layer="muni")[["muni_code", "geometry"]]
zips = list_zips()
prefs = sorted(zips) if len(sys.argv) == 1 else sys.argv[1:]
if os.path.exists(OUT): os.remove(OUT)
summary = {}
first = True
first_dis = True
n_dis = 0
for p in prefs:
    t0 = time.time()
    mode, supp = POLICY.get(p, ("newest", None))
    newest_v, newest_z = zips[p][0]
    g = load_version(newest_z)
    used = [f"A40-{newest_v}"]
    supp_info = []
    if mode == "merge_muni":
        pts = g.representative_point()
        covered = set(gpd.sjoin(gpd.GeoDataFrame(geometry=pts, crs=g.crs), muni, predicate="within").muni_code)
        mp = muni[muni.muni_code.str.startswith(p)]
        for v in supp:
            z = dict(zips[p])[v]
            go = load_version(z)
            jo = gpd.sjoin(gpd.GeoDataFrame({"i": range(len(go))}, geometry=go.representative_point(), crs=go.crs), mp, how="left", predicate="within")
            jo = jo.drop_duplicates("i")
            # 市区町村に属さない旧版行 (海上・埋立地等) は最新版ポリゴンと交差しない限り残す
            nan_i = jo.i[jo.muni_code.isna()].values
            hit = set()
            if len(nan_i):
                tree = shapely.STRtree(g.geometry.values)
                q = tree.query(go.geometry.values[nan_i], predicate="intersects")
                hit = set(nan_i[q[0]])
            keep_mask = (~jo.muni_code.isin(covered) & jo.muni_code.notna()) | (jo.muni_code.isna() & ~jo.i.isin(hit))
            add = go.loc[jo.i[keep_mask].values]
            add_munis = sorted(jo.muni_code[keep_mask].dropna().unique())
            g = gpd.GeoDataFrame(pd.concat([g, add], ignore_index=True), crs=g.crs)
            used.append(f"A40-{v}")
            supp_info.append({"version": f"A40-{v}", "rows_added": int(len(add)), "munis": add_munis})
            covered |= set(add_munis)
    # validity
    inv = ~g.geometry.is_valid
    n_invalid = int(inv.sum())
    if n_invalid:
        g.loc[inv, "geometry"] = g.loc[inv, "geometry"].make_valid()
    g = g[~g.geometry.is_empty]
    g["area_km2"] = g.to_crs(CEA).area / 1e6
    unparsed = g[g.depth_rank.isna()]
    if len(unparsed):
        print(f"  !! {p}: {len(unparsed)} rows with unparsed class: {unparsed.depth_class_src.unique().tolist()}")
    raw = g[["pref_code", "depth_rank", "depth_min_m", "depth_max_m", "depth_class_src", "source_version", "geometry"]].copy()
    raw["depth_rank"] = raw.depth_rank.astype("Int64")
    raw.to_file(OUT, layer="inundation", driver="GPKG", mode="w" if first else "a")
    first = False
    # dissolve
    t1 = time.time()
    keys = ["pref_code", "source_version", "depth_class_src"]
    dis = g.dissolve(by=keys, aggfunc={"depth_rank": "first", "depth_min_m": "first", "depth_max_m": "first", "area_km2": "sum"}).reset_index()
    dis = dis[["pref_code", "depth_rank", "depth_min_m", "depth_max_m", "depth_class_src", "source_version", "area_km2", "geometry"]]
    dis["depth_rank"] = dis.depth_rank.astype("Int64")
    dis.to_file(OUT, layer="inundation_dissolved", driver="GPKG", mode="w" if first_dis else "a")
    first_dis = False
    n_dis += len(dis)
    del dis
    cls = g.groupby(["source_version", "depth_class_src"], dropna=False).agg(rows=("depth_rank", "size"), area_km2=("area_km2", "sum"), depth_rank=("depth_rank", "first"), depth_min_m=("depth_min_m", "first"), depth_max_m=("depth_max_m", "first")).reset_index()
    summary[p] = {
        "mode": mode, "versions_used": used, "supplement": supp_info,
        "versions_available": [f"A40-{v}" for v, _ in zips[p]],
        "rows": int(len(g)), "area_km2": round(float(g.area_km2.sum()), 2), "invalid_fixed": n_invalid,
        "unparsed_rows": int(len(unparsed)),
        "bbox": [round(float(x), 4) for x in g.total_bounds],
        "classes": [{"source_version": r.source_version, "depth_class_src": r.depth_class_src, "depth_rank": (None if pd.isna(r.depth_rank) else int(r.depth_rank)),
                     "depth_min_m": (None if pd.isna(r.depth_min_m) else float(r.depth_min_m)), "depth_max_m": (None if pd.isna(r.depth_max_m) else float(r.depth_max_m)),
                     "rows": int(r.rows), "area_km2": round(float(r.area_km2), 3)} for r in cls.itertuples()],
    }
    print(f"{p}: {mode} {used} rows={len(g)} area={g.area_km2.sum():.1f}km2 invalid_fixed={n_invalid} dissolve={time.time()-t1:.0f}s total={time.time()-t0:.0f}s", flush=True)

print(f"wrote {OUT}: {os.path.getsize(OUT)/1e6:.1f} MB; dissolved rows={n_dis}")
dis = gpd.read_file(OUT, layer="inundation_dissolved")

simp = dis.copy()
simp["geometry"] = simp.geometry.simplify(SIMPLIFY_TOL, preserve_topology=True)
simp = simp[~simp.geometry.is_empty]
simp["area_km2"] = simp.area_km2.round(3)
if os.path.exists(OUTJ): os.remove(OUTJ)
simp.to_file(OUTJ, driver="GeoJSON", COORDINATE_PRECISION=5)
mb = os.path.getsize(OUTJ) / 1e6
if mb > GEOJSON_MAX_MB:
    os.remove(OUTJ); print(f"simplified geojson {mb:.1f} MB > {GEOJSON_MAX_MB} MB -> removed")
    summary["_simplified_geojson"] = {"written": False, "size_mb": round(mb, 1)}
else:
    print(f"wrote {OUTJ}: {mb:.1f} MB")
    summary["_simplified_geojson"] = {"written": True, "size_mb": round(mb, 1), "tolerance_deg": SIMPLIFY_TOL}
summary["_rank_table"] = [{"depth_rank": k, "min_m": a, "max_m": (None if b == math.inf else b), "label": rank_label(k)} for k, a, b in RANKS]
summary["_gpkg_size_mb"] = round(os.path.getsize(OUT) / 1e6, 1)
json.dump(summary, open(OUTS, "w"), ensure_ascii=False, indent=1)
print(f"wrote {OUTS}")
