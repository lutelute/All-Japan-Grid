#!/usr/bin/env python3
"""#35 の追記 35b(線の上の双子)の前と後。同じコミットで、35b を切って(AJG_HYGIENE_ON_PATH=0)回した
全段の出力(前)と、既定のまま回した全段の出力(後)を突き合わせる。

    # 前: 別の作業ツリーで
    AJG_HYGIENE_ON_PATH=0 PYTHONPATH=. python3 scripts/regenerate_all.py --skip-... (図やページの段は飛ばしてよい)
    # 後: この作業ツリーで regenerate_all を既定のまま
    PYTHONPATH=. python3 docs/reports/canon_region_dedup_2026-11-07/saku_fix.py <前の作業ツリー>
→ saku_fix.json
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "sensitivity"))
from compare import KEYS, canon_stats  # noqa: E402

PLANTS = ["八那池第一水力発電所", "大字高野町佐久穂町発電所", "松原発電所", "小諸市立東小学校", "小諸市立美南ガ丘小学校"]


def load(root, path):
    with open(os.path.join(root, path), encoding="utf-8") as fh:
        return json.load(fh)


def gens(d, island):
    import n1_screening as ns
    from src.powerflow.pref_demand import pref_zone_gwh
    cfg = ns.load_demand_config()
    pref_gwh, _ = pref_zone_gwh(d["nodes"])
    net = ns.production_net(island, d["nodes"], d["edges"], cfg, pref_gwh, cap_calib=None)
    at = collections.defaultdict(set)
    for i in net.gen.index:
        nm = str(net.gen.at[i, "name"])
        if nm in PLANTS:
            at[nm].add(str(net.bus.at[int(net.gen.at[i, "bus"]), "name"]))
    return {"n_gen": int(len(net.gen)), "plants": {k: sorted(v) for k, v in sorted(at.items())}}


def main(off_root):
    on_root = ROOT
    ca, cb = load(on_root, "docs/data/built/all.json"), load(off_root, "docs/data/built/all.json")
    led = load(on_root, "docs/data/fragments/node_hygiene_ledger.json")
    frs = [f for f in led["fragments"] if f.get("kind") == "on_path_twin"]
    ids_b = {n["id"]: n for n in cb["nodes"]}
    # 35b が消した点は、前(35b を切った全段)の正典でどうなっていたか
    fate = []
    for f in frs:
        for n in f["dropped_nodes"]:
            m = ids_b.get(n["id"])
            fate.append({"id": n["id"], "name": n.get("name"), "island_from": f["island"],
                         "region_at_hygiene": n.get("region"),
                         "region_before": (m or {}).get("region"), "in_before": m is not None,
                         "relabel_before": (m or {}).get("freq_fix") or (m or {}).get("mixed_pref")})
    pb, pa = load(off_root, "docs/data/powerflow_full/summary.json")["islands"], \
        load(on_root, "docs/data/powerflow_full/summary.json")["islands"]
    nb, na = load(off_root, "docs/data/n1_canon/summary.json")["islands"], \
        load(on_root, "docs/data/n1_canon/summary.json")["islands"]
    res = {
        "what": "#35 の追記 35b(線の上の双子)の前と後。前 = 同じコミットで 35b を切って回した全段、後 = 既定",
        "n_fragments": len(frs), "n_nodes_dropped": sum(len(f["dropped_nodes"]) for f in frs),
        "n_edges_dropped": sum(1 for e in led["removed_edges"] if e.get("why") == "on_path_twin"),
        "fragments": [{"island": f["island"], "twin_island": f["twin_island"],
                       "nodes": [(n["id"], n.get("name"), n["lat"], n["lon"]) for n in f["dropped_nodes"]]}
                      for f in frs],
        "fate_before": fate,
        "canon": {"before": canon_stats(cb), "after": canon_stats(ca)},
        "powerflow": {isl: {k: [pb[isl].get(k), pa[isl].get(k)] for k in KEYS} for isl in pb},
        "n1": {x.get("island"): {k: [x.get(k), y.get(k)] for k in x if not isinstance(x.get(k), (list, dict))}
               for x, y in zip(nb, na)},
        "gens": {isl: {"before": gens(cb, isl), "after": gens(ca, isl)} for isl in ("east", "west")},
    }
    json.dump(res, open(os.path.join(HERE, "saku_fix.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    c = res["canon"]
    print("正典", {k: (c["before"][k], c["after"][k]) for k in c["before"] if c["before"][k] != c["after"][k]})
    for isl, row in res["powerflow"].items():
        print("潮流", isl, {k: v for k, v in row.items() if v[0] != v[1]})
    for isl, row in res["n1"].items():
        print("N-1", isl, {k: v for k, v in row.items() if v[0] != v[1]})
    for isl, g in res["gens"].items():
        print("発電機", isl, g["before"]["n_gen"], "→", g["after"]["n_gen"], g["before"]["plants"], "→", g["after"]["plants"])
    print("前の正典での行方", collections.Counter((x["in_before"], x["region_at_hygiene"], x["region_before"])
                                         for x in fate))


if __name__ == "__main__":
    main(sys.argv[1])
