#!/usr/bin/env python3
"""公開用の単独 HTML(タイル不要・データ内蔵)を run ディレクトリから組む。

    PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/build_artifact.py <run_dir> <out_html>
"""
from __future__ import annotations
import json, os, sys
import numpy as np, pandas as pd, geopandas as gpd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PREF = os.path.join(ROOT, "data", "reference", "japan_prefectures_simplified.geojson")
TS = [0, 0.5, 1, 2, 4, 7, 14, 30, 90]


def rnd(geom, nd=4):
    from shapely import set_precision
    return set_precision(geom, 10 ** -nd)


def main(run_dir, out_html):
    munis = []; pts = []; curves = {}; compare = json.load(open(os.path.join(run_dir, "naikakufu_compare.json")))
    for isl in ("west", "east"):
        g = gpd.read_file(os.path.join(run_dir, isl, "municipalities.geojson"))
        g["geometry"] = rnd(g.geometry.simplify(0.0025, preserve_topology=True))
        for _, r in g.iterrows():
            if r.geometry is None or r.geometry.is_empty:
                continue
            munis.append({"type": "Feature", "geometry": json.loads(json.dumps(r.geometry.__geo_interface__)),
                          "properties": {"n": f"{r.pref_name} {r.muni_name}", "l": round(float(r.load_mw), 1), "c": int(r.customers), "i": round(float(r.intensity_mean), 2),
                                         "d": round(float(r.expected_outage_days), 1), "p": [round(float(1 - r[f"phys_t{t:g}"]), 3) for t in TS], "s": [round(float(1 - r[f"served_t{t:g}"]), 3) for t in TS]}})
        b = pd.read_parquet(os.path.join(run_dir, isl, "bus_results.parquet")); b = b[~b.is_junction]
        for _, r in b.iterrows():
            pts.append([round(float(r.lat), 4), round(float(r.lon), 4), str(r.site), int(r.kv), round(float(r.pd_mw), 1), round(float(r.intensity_mean), 2), int(r.tsunami_rank),
                        round(float(r.expected_outage_days_phys), 1), [round(float(r[f"pout_phys_t{t:g}"]), 2) for t in TS]])
        s = pd.read_csv(os.path.join(run_dir, isl, "timeline_summary.csv"))
        curves[isl] = {"t": s.t_days.round(2).tolist(), "phys": (s.phys_frac * 100).round(1).tolist(), "served": (s.served_frac * 100).round(1).tolist(),
                       "p10": (s.served_mw_p10 / s.load_mw * 100).round(1).tolist(), "p90": (s.served_mw_p90 / s.load_mw * 100).round(1).tolist(), "load": float(s.load_mw.iloc[0])}
    pref = gpd.read_file(PREF); pref["geometry"] = rnd(pref.geometry.simplify(0.01, preserve_topology=True))
    pref_fc = json.loads(pref[["geometry"]].to_json())
    meta = json.load(open(os.path.join(run_dir, "summary.json")))
    data = {"ts": TS, "muni": {"type": "FeatureCollection", "features": munis}, "pts": pts, "curves": curves, "pref": pref_fc,
            "compare": {k: v for k, v in compare.items() if k.startswith("five") or k.endswith("_t0") or k.endswith("_t1") or k.endswith("_t4") or k.endswith("_t7")},
            "n": meta["samples"], "generated": meta["generated"]}
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    tpl = open(os.path.join(os.path.dirname(__file__), "templates", "artifact_map.html"), encoding="utf-8").read()
    css = open(os.path.join(os.path.dirname(__file__), "templates", "leaflet-1.9.4.min.css"), encoding="utf-8").read()
    html = tpl.replace("/*__LEAFLET_CSS__*/", css.replace("</style", "<\\/style")).replace("/*__DATA__*/null", js)
    open(out_html, "w", encoding="utf-8").write(html)
    print("html MB", round(len(html.encode()) / 1e6, 2), "munis", len(munis), "pts", len(pts))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
