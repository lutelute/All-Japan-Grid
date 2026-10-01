"""A40 zip の展開・読込 (共通)."""
import glob, os, re, zipfile, warnings
import geopandas as gpd
from a40_depth import parse_depth, rank_of

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.dirname(HERE)
EXT = os.path.join(DATA, "external", "ksj_A40")
DER = os.path.join(DATA, "derived")
TMP = os.path.join(EXT, "_extract")
CEA = "+proj=cea +lon_0=135 +datum=WGS84 +units=m +no_defs"  # 面積計算用 (等積円筒)

def list_zips():
    """{pref: [(version_int, zip_path), ...] newest first}"""
    out = {}
    for z in sorted(glob.glob(os.path.join(EXT, "A40-*_GML.zip"))):
        m = re.match(r"A40-(\d\d)_(\d\d)_GML\.zip$", os.path.basename(z))
        if not m: continue
        out.setdefault(m.group(2), []).append((int(m.group(1)), z))
    for p in out: out[p].sort(reverse=True)
    return out

def load_version(zpath, to_4326=True):
    """A40 zip → GeoDataFrame [pref_code, depth_rank, depth_min_m, depth_max_m, depth_class_src, source_version, geometry]"""
    name = os.path.basename(zpath)[:-8]
    d = os.path.join(TMP, name)
    if not glob.glob(os.path.join(d, "**", "*.shp"), recursive=True):
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(d, members=[m for m in zf.namelist() if m.rsplit(".", 1)[-1].lower() in ("shp", "shx", "dbf", "prj", "cpg")])
    shps = sorted(glob.glob(os.path.join(d, "**", "*.shp"), recursive=True))
    parts = []
    for shp in shps:
        cpg = glob.glob(os.path.splitext(shp)[0] + ".cpg")
        enc = open(cpg[0]).read().strip() if cpg else "cp932"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            g = gpd.read_file(shp, encoding=enc)
        cols = {c.upper(): c for c in g.columns}
        c_pref = cols.get("A40_002"); c_cls = cols.get("A40_003")
        if c_cls is None:
            raise RuntimeError(f"{shp}: no A40_003 column; cols={list(g.columns)}")
        parsed = g[c_cls].map(parse_depth)
        g["depth_min_m"] = parsed.map(lambda t: t[0])
        g["depth_max_m"] = parsed.map(lambda t: t[1])
        g["depth_rank"] = g["depth_min_m"].map(rank_of)
        g["depth_class_src"] = g[c_cls]
        g["pref_code"] = g[c_pref].astype(str).str.zfill(2) if c_pref else name.split("_")[1]
        g["source_version"] = name.split("_")[0]  # e.g. A40-16
        g["src_file"] = os.path.basename(shp)
        parts.append(g)
    import pandas as pd
    g = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=parts[0].crs)
    g = g[["pref_code", "depth_rank", "depth_min_m", "depth_max_m", "depth_class_src", "source_version", "src_file", "geometry"]]
    if to_4326:
        g = g.to_crs(4326)
    return g
