# 1987 電圧崩壊の報告 2〜8 を、09-15 の固定ネットと今の正典の東で測り直す（読むだけ・書き込みなし）
# 使い方: リポジトリの根で  .venv/bin/python recheck_1987.py
import copy, gzip, json, re, sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
import numpy as np, pandas as pd, pandapower as pp, networkx as nx
from matplotlib.path import Path


def fixed_net():
    return pp.from_json_string(gzip.decompress(open(
        "docs/reports/codex_ac_diagnosis_2026-09-15/input_network.json.gz", "rb").read()).decode())


def canon_net():
    from scripts.export_matpower_canonical import build_canonical_net
    from scripts.run_full_powerflow_from_db import ISLAND_FREQ
    b = json.load(open("docs/data/built/all.json"))
    return build_canonical_net("east", b["nodes"], b["edges"], ISLAND_FREQ["east"])


def xgraph(net):  # 電気的距離 = リアクタンス [pu, 100MVA]
    G = nx.Graph()
    def add(a, b, x):
        a, b = int(a), int(b)
        if G.has_edge(a, b):
            G[a][b]["w"] = 1 / (1 / G[a][b]["w"] + 1 / x)
        else:
            G.add_edge(a, b, w=x)
    for _, r in net.line[net.line.in_service].iterrows():
        add(r.from_bus, r.to_bus, max(r.x_ohm_per_km * r.length_km / r.parallel / (net.bus.vn_kv[r.from_bus] ** 2 / 100), 1e-9))
    for _, r in net.trafo[net.trafo.in_service].iterrows():
        add(r.hv_bus, r.lv_bus, r.vk_percent / 100 * 100 / (r.sn_mva * r.parallel))
    return G


def measure(net):
    out = {}
    tok = net.bus.zone == "tokyo"
    # 2: 都県別シェア
    prefs = json.load(open("data/reference/japan_prefectures_simplified.geojson"))["features"]
    ld = net.load[net.load.in_service & tok.reindex(net.load.bus).values]
    xy = np.array([json.loads(g)["coordinates"][:2] for g in net.bus.geo.reindex(ld.bus)])
    for f in prefs:
        polys = f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiPolygon" else [f["geometry"]["coordinates"]]
        m = np.zeros(len(ld), bool)
        for p in polys:
            m |= Path(np.array(p[0])).contains_points(xy)
        if ld.p_mw[m].sum() > 500:
            out["2 " + f["properties"]["pref_ja"]] = round(100 * ld.p_mw[m].sum() / ld.p_mw.sum(), 1)
    # 3: 昇圧変圧器
    g = net.gen[net.gen.in_service]
    lb = set(net.line.from_bus) | set(net.line.to_bus)
    out["3 昇圧変圧器らしき枝"] = int((net.trafo.lv_bus.isin(set(g.bus)) & ~net.trafo.lv_bus.isin(lb)
                                 & ~net.trafo.lv_bus.isin(set(net.load.bus))).sum())
    big = g[g.max_p_mw >= 100]
    out["3 100MW以上の機の接続電圧"] = big.groupby(net.bus.vn_kv.reindex(big.bus).values).max_p_mw.agg(["size", "sum"]).round(0).to_dict("index")
    # 4: 重複・燃料種別
    g4 = net.gen[net.gen.in_service & (net.gen.max_p_mw >= 100)]
    out["4 完全重複(name,bus,max_p)"] = g4[g4.duplicated(subset=["name", "bus", "max_p_mw"], keep=False)][["name", "max_p_mw"]].values.tolist()
    out["4 燃料種別の混入"] = net.gen.type[net.gen.type.isin(["gsimaps/ort", "gsimaps/seamlessphoto", "image"])].value_counts().to_dict()
    out["4 仙台火力"] = net.gen[net.gen.name.astype(str).str.contains("仙台火力")][["name", "type", "max_p_mw"]].values.tolist()
    mk = net.gen[net.gen.name == "真岡発電所"]
    out["4 真岡の接続電圧"] = net.bus.vn_kv.reindex(mk.bus).tolist()
    # 5: 154kV 未満の負荷を電気的に最も近い 154kV 以上の母線へ
    G = xgraph(net)
    lv = ld[net.bus.vn_kv.reindex(ld.bus).values < 154]
    src = set(net.bus.index[tok & (net.bus.vn_kv >= 154)]) & set(G.nodes)
    _, path = nx.multi_source_dijkstra(G, src, weight="w")
    df = pd.DataFrame([(path[int(r.bus)][0], r.p_mw, int(r.bus)) for _, r in lv.iterrows() if int(r.bus) in path],
                      columns=["src", "p", "bus"])
    agg = df.groupby("src").agg(n=("bus", "nunique"), p=("p", "sum")).sort_values("p", ascending=False)
    out["5 最大の集約先"] = (net.bus.name[agg.index[0]], int(agg.n.iloc[0]), round(agg.p.iloc[0]), round(100 * agg.p.iloc[0] / ld.p_mw.sum(), 1))
    j = net.bus.index[net.bus.name == "tokyo junction 35.6604:139.3722:275"][0]
    out["5 八王子 junction"] = (int(agg.n.get(j, 0)), round(agg.p.get(j, 0)))
    fv = net.bus.vn_kv.reindex(net.line.from_bus).values
    tv = net.bus.vn_kv.reindex(net.line.to_bus).values
    out["5 電圧の違う母線を直結する線(東/東京)"] = (int((fv != tv).sum()), int(((fv != tv) & (net.bus.zone.reindex(net.line.from_bus).values == "tokyo")).sum()))
    # 6: 500kV タグの小規模変電所
    b = net.bus[tok & (net.bus.vn_kv == 500) & ~net.bus.name.astype(str).str.contains("junction")]
    has_bulk = set(net.trafo.hv_bus[(net.trafo.vn_hv_kv >= 400) & (net.trafo.vn_lv_kv >= 150)])
    out["6 500kV母線 / うち500/275・500/154あり"] = (len(b), sum(i in has_bulk for i in b.index))
    out["6 東京の500/66kV変圧器"] = int(((net.trafo.vn_hv_kv == 500) & (net.trafo.vn_lv_kv == 66) & tok.reindex(net.trafo.hv_bus).values).sum())
    # 7: 直流潮流・大郷町 275/66
    n = copy.deepcopy(net)
    pp.rundcpp(n)
    va = n.res_bus.va_degree
    t = n.trafo.index[n.bus.name.reindex(n.trafo.hv_bus).values == "大郷町変電所 275kV"][0]
    out["7 位相の範囲"] = (round(va.min(), 1), round(va.max(), 1))
    out["7 大郷町275/66 位相差・潮流"] = (round(va[n.trafo.hv_bus[t]] - va[n.trafo.lv_bus[t]], 1), round(n.res_trafo.p_hv_mw[t]), n.trafo.sn_mva[t])
    mc = n.bus.index[n.bus.name == "宮城中央変電所 500kV"][0]
    out["7 宮城中央500kVの線の数"] = int(((n.line.from_bus == mc) | (n.line.to_bus == mc)).sum())
    # 8: 線の経路形状
    geo = net.line.geo
    out["8 line.geo 空"] = (int((geo.isna() | geo.astype(str).isin(["", "None", "nan"])).sum()), len(net.line))
    return out


if __name__ == "__main__":
    a, c = measure(fixed_net()), measure(canon_net())
    for k in sorted(a.keys() | c.keys()):
        print(f"{k}\n   固定: {a.get(k)}\n   正典: {c.get(k)}")
