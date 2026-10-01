#!/usr/bin/env python3
"""正典系譜(built + build_island_net + 標準注入)の pandapower net から
ハザード解析用の自己完結ケース(parquet)を切り出す。

    PYTHONPATH=. python3 hazard/nankai/scripts/extract_grid_case.py --islands east west

出力: hazard/nankai/data/derived/grid_<island>_{bus,branch,gen}.parquet + meta
- bus:    bus_id, name, site, kv, zone, lat, lon, pd_mw, is_slack
- branch: branch_id, kind(line/trafo), f_bus, t_bus, x_pu(100MVA), cap_mw, parallel,
          length_km, name, in_service, mid_lat, mid_lon, kv
- gen:    gen_id, bus_id, name, fuel, p_mw, pmax_mw, kind

容量は本体と同じ定義(線路 √3·V·I·par × 介入#45較正係数 / 変圧器 sn_mva·par)。
"""
from __future__ import annotations
import argparse, json, os, sys, time, re
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import numpy as np, pandas as pd

OUT = os.path.join(ROOT, "hazard/nankai/data/derived")
SUFFIX = re.compile(r"\s*\d+(\.\d+)?kV$|_\d+$")

def _bus_geo(net):
    """pandapower 2.x (bus_geodata) / 3.x (bus.geo: GeoJSON文字列) 両対応で x,y を返す。"""
    if hasattr(net, "bus_geodata") and len(getattr(net, "bus_geodata", [])):
        return net.bus_geodata[["x", "y"]]
    xs, ys = [], []
    for g in net.bus["geo"]:
        try:
            d = json.loads(g) if isinstance(g, str) else None
            c = d["coordinates"] if d else (None, None)
        except Exception:
            c = (None, None)
        xs.append(c[0]); ys.append(c[1])
    return pd.DataFrame({"x": xs, "y": ys}, index=net.bus.index)


def site_of(name: str) -> str:
    s = str(name)
    s = re.sub(r"\s*\d+(\.\d+)?kV$", "", s)
    s = re.sub(r"_\d+$", "", s)
    return s

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="*", default=["east", "west"])
    a = ap.parse_args()
    from scripts.export_matpower_canonical import build_canonical_net
    from scripts.run_full_powerflow_from_db import ISLAND_FREQ
    built = json.load(open("docs/data/built/all.json"))
    nodes, edges = built["nodes"], built["edges"]
    os.makedirs(OUT, exist_ok=True)
    meta = {"islands": {}}
    for isl in a.islands:
        t0 = time.time()
        net = build_canonical_net(isl, nodes, edges, ISLAND_FREQ[isl])
        sn = 100.0
        bus = net.bus.copy()
        geo = _bus_geo(net)
        load = net.load.groupby("bus").p_mw.sum()
        slack_buses = set(net.ext_grid.bus.tolist())
        b = pd.DataFrame({
            "bus_id": bus.index.astype(int),
            "name": bus.name.astype(str).values,
            "kv": bus.vn_kv.astype(float).values,
            "zone": bus.zone.astype(str).values,
            "lon": geo.loc[bus.index, "x"].astype(float).values,
            "lat": geo.loc[bus.index, "y"].astype(float).values,
        })
        b["site"] = [site_of(n) for n in b.name]
        b["pd_mw"] = b.bus_id.map(load).fillna(0.0).astype(float)
        b["is_slack"] = b.bus_id.isin(slack_buses)
        b["is_junction"] = b.name.str.contains("junction|jct", case=False, regex=True)
        # lines
        ln = net.line
        kvf = bus.loc[ln.from_bus, "vn_kv"].to_numpy(float)
        cap = np.sqrt(3) * kvf * ln.max_i_ka.to_numpy(float) * ln.parallel.to_numpy(float)
        x_pu = (ln.x_ohm_per_km * ln.length_km / ln.parallel).to_numpy(float) / (kvf ** 2 / sn)
        lat = b.set_index("bus_id").lat; lon = b.set_index("bus_id").lon
        L = pd.DataFrame({
            "kind": "line", "f_bus": ln.from_bus.astype(int).values, "t_bus": ln.to_bus.astype(int).values,
            "x_pu": x_pu, "cap_mw": cap, "parallel": ln.parallel.astype(int).values,
            "length_km": ln.length_km.astype(float).values, "name": ln.name.astype(str).values,
            "in_service": ln.in_service.astype(bool).values, "kv": kvf,
        })
        tr = net.trafo
        kvh = bus.loc[tr.hv_bus, "vn_kv"].to_numpy(float)
        # x_pu on 100 MVA: vk_percent/100 * sn/sn_mva / parallel
        xt = (tr.vk_percent.to_numpy(float) / 100.0) * (sn / tr.sn_mva.to_numpy(float)) / tr.parallel.to_numpy(float)
        T = pd.DataFrame({
            "kind": "trafo", "f_bus": tr.hv_bus.astype(int).values, "t_bus": tr.lv_bus.astype(int).values,
            "x_pu": xt, "cap_mw": (tr.sn_mva * tr.parallel).to_numpy(float), "parallel": tr.parallel.astype(int).values,
            "length_km": 0.0, "name": tr.name.astype(str).values, "in_service": tr.in_service.astype(bool).values, "kv": kvh,
        })
        br = pd.concat([L, T], ignore_index=True)
        br.insert(0, "branch_id", np.arange(len(br)))
        br["mid_lat"] = (lat.loc[br.f_bus].values + lat.loc[br.t_bus].values) / 2
        br["mid_lon"] = (lon.loc[br.f_bus].values + lon.loc[br.t_bus].values) / 2
        # gens
        g = net.gen
        cols = {c: c for c in g.columns}
        G = pd.DataFrame({
            "gen_id": g.index.astype(int), "bus_id": g.bus.astype(int).values,
            "name": g.name.astype(str).values, "p_mw": g.p_mw.astype(float).values,
            "pmax_mw": g.max_p_mw.astype(float).values if "max_p_mw" in g else np.nan,
            "in_service": g.in_service.astype(bool).values,
        })
        for c in ("fuel", "type", "fuel_type", "kind", "source", "operator", "attach"):
            if c in g.columns:
                G[c] = g[c].astype(str).values
        G["kind"] = "gen"
        E = pd.DataFrame({"gen_id": -1 - net.ext_grid.index.astype(int), "bus_id": net.ext_grid.bus.astype(int).values,
                          "name": net.ext_grid.name.astype(str).values, "p_mw": 0.0, "pmax_mw": np.inf,
                          "in_service": True, "kind": "slack"})
        G = pd.concat([G, E], ignore_index=True)
        b.to_parquet(f"{OUT}/grid_{isl}_bus.parquet", index=False)
        br.to_parquet(f"{OUT}/grid_{isl}_branch.parquet", index=False)
        G.to_parquet(f"{OUT}/grid_{isl}_gen.parquet", index=False)
        meta["islands"][isl] = {"n_bus": len(b), "n_branch": len(br), "n_line": len(L), "n_trafo": len(T),
                                "n_gen": int((G.kind == "gen").sum()), "n_slack": len(E),
                                "pd_mw": round(float(b.pd_mw.sum()), 1), "pg_mw": round(float(G.p_mw.sum()), 1),
                                "gen_columns": list(g.columns), "build_s": round(time.time() - t0, 1)}
        print(isl, meta["islands"][isl], flush=True)
    meta["source"] = "docs/data/built/all.json via scripts/export_matpower_canonical.build_canonical_net"
    meta["generated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    json.dump(meta, open(f"{OUT}/grid_meta.json", "w"), ensure_ascii=False, indent=1)

if __name__ == "__main__":
    main()
