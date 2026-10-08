#!/usr/bin/env python3
"""N03 行政区域 (国土数値情報) → hazard/nankai/data/derived/municipalities.gpkg / _simplified.geojson

入力: hazard/nankai/data/external/ksj_N03/N03-YYYYMMDD_PP_GML.zip (fetch_ksj.sh で取得)
出力: derived/municipalities.gpkg (layer "muni", EPSG:4326)
      derived/municipalities_simplified.geojson (tolerance 0.002 deg)
列: muni_code (N03_007), pref_code, pref_name (N03_001), muni_name (N03_004 + 政令市の区名 N03_005; 郡名は含めない)
市区町村コード単位で dissolve (政令市は区単位のまま)。
"""
import glob, os, sys, zipfile, time
import geopandas as gpd, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.dirname(HERE)
EXT = os.path.join(DATA, "external", "ksj_N03")
DER = os.path.join(DATA, "derived")
TMP = os.path.join(EXT, "_extract")
os.makedirs(DER, exist_ok=True); os.makedirs(TMP, exist_ok=True)

zips = sorted(glob.glob(os.path.join(EXT, "N03-*_GML.zip")))
print(f"{len(zips)} N03 zips")
parts = []
for z in zips:
    t0 = time.time()
    name = os.path.basename(z)[:-8]
    d = os.path.join(TMP, name)
    with zipfile.ZipFile(z) as zf:
        zf.extractall(d, members=[m for m in zf.namelist() if m.rsplit(".", 1)[-1] in ("shp", "shx", "dbf", "prj", "cpg")])
    shp = glob.glob(os.path.join(d, "**", "*.shp"), recursive=True)[0]
    cpg = glob.glob(os.path.join(d, "**", "*.cpg"), recursive=True)
    enc = open(cpg[0]).read().strip() if cpg else "cp932"
    g = gpd.read_file(shp, encoding=enc)
    g = g[g.N03_007.notna()].copy()
    g["muni_code"] = g.N03_007.astype(str).str.zfill(5)
    g["pref_code"] = g.muni_code.str[:2]
    g["pref_name"] = g.N03_001
    # N03-2024 以降: N03_003=郡・政令市名(政令市の区行では None), N03_004=市区町村名(区行では市名), N03_005=政令市の区名
    ward = g["N03_005"].fillna("") if "N03_005" in g.columns else ""
    g["muni_name"] = g.N03_004.fillna("") + ward
    src_epsg = g.crs.to_epsg()
    g = g.to_crs(4326)
    dis = g[["muni_code", "pref_code", "pref_name", "muni_name", "geometry"]].dissolve(by="muni_code", aggfunc="first").reset_index()
    parts.append(dis)
    print(f"  {name}: {len(g)} polys -> {len(dis)} munis  src_crs={src_epsg} enc={enc} ({time.time()-t0:.1f}s)", flush=True)

muni = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")
muni = muni[["muni_code", "pref_code", "pref_name", "muni_name", "geometry"]]
assert muni.muni_code.is_unique, "duplicate muni_code across files"
out = os.path.join(DER, "municipalities.gpkg")
if os.path.exists(out): os.remove(out)
muni.to_file(out, layer="muni", driver="GPKG")
print(f"wrote {out}: {len(muni)} rows, {os.path.getsize(out)/1e6:.1f} MB")

simp = muni.copy()
simp["geometry"] = simp.geometry.simplify(0.002, preserve_topology=True)
simp = simp[~simp.geometry.is_empty]
outj = os.path.join(DER, "municipalities_simplified.geojson")
simp.to_file(outj, driver="GeoJSON", COORDINATE_PRECISION=5)
print(f"wrote {outj}: {len(simp)} rows, {os.path.getsize(outj)/1e6:.1f} MB")
print(muni.groupby("pref_code").size().to_string())
