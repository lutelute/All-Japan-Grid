"""N-1 の開放ごとの結果を書き出す(#168 の東 125 → 145 の説明。先生の問い 2026-11-09)。

scripts/sensitivity/n1_screening.py の run と同じ手順で網を作り、実在の線を見張る数え方
(n_outage_causing_new_over_physical)で、開放ごとに「新たに過負荷になる枝」の一覧まで出す。
網を作るコードと正典(all.json)を別々に指定できるので、前と後を同じコードで比べられる。

    python3 n1_east_dump.py <コードの根> <all.json> east <出力.json>

前 = #167 の先頭 cd7c90d2 の正典、後 = この PR の e69f883e の正典。出力は 600 KB ほどあるので
コミットしない(n1_east.py が、要るところだけ n1_east.json にまとめる)。
"""
import json
import sys
from pathlib import Path

root, built, island = Path(sys.argv[1]), Path(sys.argv[2]).resolve(), sys.argv[3]
outp = Path(sys.argv[4]).resolve()   # n1_screening の import が cwd を root に移すので先に絶対にする
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "scripts" / "sensitivity"))
import numpy as np  # noqa: E402
import n1_screening as ns  # noqa: E402  (os.chdir(root))
import pandapower as pp  # noqa: E402
from pandapower.pypower.makePTDF import makePTDF  # noqa: E402
from src.powerflow import contingency as cg  # noqa: E402
from src.powerflow.pref_demand import pref_zone_gwh  # noqa: E402

d = json.load(open(built, encoding="utf-8"))
nodes, edges = d["nodes"], d["edges"]
cfg = ns.load_demand_config()
pref_gwh, _ = pref_zone_gwh(nodes)
net = ns.production_net(island, nodes, edges, cfg, pref_gwh, cap_calib=None)
sub, _ = ns.main_component_subnet(net)
pp.rundcpp(sub)
ppc = sub._ppc
ref = int(sub._pd2ppc_lookups["bus"][int(sub.ext_grid.bus.iloc[0])])
ptdf = makePTDF(ppc["baseMVA"], ppc["bus"], ppc["branch"], slack=ref)
nl = ptdf.shape[0]
f0 = cg.ppc_flows_mw(ppc)
cap = cg.branch_capacity_mw(sub, nl, 1.0)
par = cg.branch_parallel(sub, nl)
kv = cg.branch_kv(ppc)
elems = cg.branch_elements(sub)
status = ppc["branch"][:, cg.BR_STATUS].real.astype(float) > 0
lk = ns.edge_lookup(edges)
cls = np.array([ns.classify(sub, t, e, lk) if t else "unknown" for t, e in elems])
physical = np.isin(cls, ns.PHYSICAL_CLASSES)
in_scope = (kv >= 154.0 - 0.5) & status
mon = in_scope & physical
res = cg.screen(ptdf, ppc["branch"], f0, cap, par, monitor=mon, single_circuit=True)
ok = res.outage_ok & np.isfinite(res.post_max_loading)


def bus_ll(b):
    lo, la = ns._bus_lonlat(sub, int(b))
    return [la, lo]


def info(k):
    tbl, eid = elems[k]
    if tbl is None:
        return {"k": int(k)}
    tab = getattr(sub, tbl)
    if tbl == "line":
        a, b = int(tab.at[eid, "from_bus"]), int(tab.at[eid, "to_bus"])
        length = float(tab.at[eid, "length_km"])
    else:
        a, b = int(tab.at[eid, "hv_bus"]), int(tab.at[eid, "lv_bus"])
        length = 0.0
    return {"k": int(k), "table": tbl, "name": str(tab.at[eid, "name"]), "cls": str(cls[k]),
            "kv": float(kv[k]), "par": int(par[k]), "len_km": round(length, 3),
            "from": str(sub.bus.at[a, "name"]), "to": str(sub.bus.at[b, "name"]),
            "a": bus_ll(a), "b": bus_ll(b),
            "f0": round(float(f0[k]), 2), "cap": (round(float(cap[k]), 2) if np.isfinite(cap[k]) else None),
            "base_pct": (round(float(res.base_loading[k]), 2) if np.isfinite(res.base_loading[k]) else None),
            "mon": bool(mon[k]), "base_over": bool(res.base_over[k])}


# 新たな過負荷を生む開放ごとに、新たに過負荷になる枝を出す
causing = np.where(ok & (res.post_n_new_over > 0))[0]
rows = []
for k in causing:
    f = cg.post_contingency_flows(ptdf, ppc["branch"], f0, int(k), par, single_circuit=True)
    capf = np.where(np.isfinite(cap) & (cap > 0), cap, np.inf)
    L = np.abs(f) / capf * 100.0
    p = int(par[k])
    if p > 1:
        L[k] = abs(f[k]) / (capf[k] * (p - 1) / p) * 100.0
    else:
        L[k] = 0.0
    newover = np.where(mon & ~res.base_over & (L > cg.OVER_PCT))[0]
    r = info(k)
    r["post_max_new"] = round(float(res.post_max_new[k]), 2)
    r["n_new"] = int(res.post_n_new_over[k])
    r["new_over"] = [dict(info(j), post_pct=round(float(L[j]), 2)) for j in newover]
    rows.append(r)

base_over = [info(j) for j in np.where(res.base_over)[0]]
# 見張る枝の全部(前と後の基準の負荷率を比べるため)
monitored = [info(j) for j in np.where(mon)[0]]
allbr = [info(j) for j in range(nl) if status[j]]
out = {"island": island, "n_bus": int(len(sub.bus)), "n_branch": int(nl),
       "n_ok": int(ok.sum()), "n_causing": int(len(causing)), "n_base_over": int(res.base_over.sum()),
       "causing": rows, "base_over": base_over, "monitored": monitored, "all": allbr,
       "gens": [{"name": str(sub.gen.at[g, "name"]), "bus": str(sub.bus.at[int(sub.gen.at[g, "bus"]), "name"]),
                 "p": float(sub.res_gen.at[g, "p_mw"]) if g in sub.res_gen.index else None}
                for g in sub.gen.index if bool(sub.gen.at[g, "in_service"])]}
json.dump(out, open(outp, "w", encoding="utf-8"), ensure_ascii=False)
print(island, "bus", out["n_bus"], "causing", out["n_causing"], "base_over", out["n_base_over"])
