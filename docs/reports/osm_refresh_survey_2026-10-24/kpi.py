"""正典 all.json の KPI(読むだけ): ノード・枝・本系統・島ごとの成分数・孤立変電所。"""
import json, sys, collections
sys.path.insert(0, sys.argv[2] if len(sys.argv) > 2 else ".")
from src.powerflow.connectivity import compute_connectivity
A = json.load(open(sys.argv[1], encoding="utf-8"))
nodes, edges = A["nodes"], A["edges"]
cc = compute_connectivity(nodes, edges)
k5 = lambda n: (round(n["lat"], 5), round(n["lon"], 5))
main = cc["main_keys"]
off = [n for n in nodes if k5(n) not in main]
iso_sub = [n for n in off if n.get("sub")]
twins = collections.Counter((k5(n), float(n.get("kv") or 0)) for n in nodes)
print(json.dumps({
    "n_nodes": len(nodes), "n_edges": len(edges),
    "main_nodes": sum(1 for n in nodes if k5(n) in main), "off_main": len(off),
    "isolated_subs": len(iso_sub),
    "components_by_island": cc["meta"]["components"],
    "n_stitch": cc["meta"].get("n_stitch"), "n_tie": cc["meta"].get("n_tie"),
    "same_coord_kv_twins": sum(1 for v in twins.values() if v > 1),
    "sum_par": sum(int(e.get("par") or 1) for e in edges),
    "flags": dict(collections.Counter(k for e in edges for k in ("disclosure", "recovery", "stub", "same_site", "sat_conn", "kv_corrected", "par_src") if e.get(k))),
}, ensure_ascii=False, indent=1))
