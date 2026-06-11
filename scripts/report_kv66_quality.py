"""Per-region 66 kV-band quality ledger (M4-4 of docs/PLAN_66KV.md).

    PYTHONPATH=. python scripts/report_kv66_quality.py \
        [--json docs/reports/kv66_quality_<date>.json] [--regions tokyo ...]

For every region, the 60–140 kV layer of the BUILT model is profiled:
how many branches it has, where their voltages came from (tag /
corridor propagation / unknown-default), how fragmented the layer is,
how tree-like it is (cycle rank — the radial-operation proxy upside),
and the radial-end share. This is the honest per-region statement of
"can this region's sub-transmission carry a meaningful power flow",
the 66 kV analogue of the trunk topology sweep.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def kv66_metrics(region: str) -> dict | None:
    import networkx as nx

    from src.powerflow.snapped_topology import build_network_snapped

    net = build_network_snapped(region)
    if net is None:
        return None
    G = nx.Graph()
    n_branch = 0
    prov = {"tag": 0, "prop": 0, "unk": 0}
    for ln in net.transmission_lines:
        if "_xfmr_" in ln.id:
            continue
        kv = float(ln.voltage_kv or 0)
        if not (60.0 <= kv < 140.0):
            continue
        n_branch += 1
        # builder provenance string: "conn=...;circuits=...;kv=tag|prop|unk"
        src = "tag"
        for part in (getattr(ln, "description", "") or "").split(";"):
            if part.startswith("kv="):
                src = part[3:]
        prov[src if src in prov else "unk"] += 1
        G.add_edge(ln.from_substation_id, ln.to_substation_id)
    if n_branch == 0:
        return {"region": region, "n_branches": 0}
    subs = [n for n in G.nodes if "_jct_" not in n]
    n_nodes, n_edges = G.number_of_nodes(), G.number_of_edges()
    n_comp = nx.number_connected_components(G)
    largest = max((len(c) for c in nx.connected_components(G)), default=0)
    radial = sum(1 for n in subs if G.degree(n) == 1)
    return {
        "region": region,
        "n_branches": n_branch,
        "n_substations": len(subs),
        "n_components": n_comp,
        "largest_comp_share": round(largest / n_nodes, 3) if n_nodes else 0.0,
        "cycle_rank": n_edges - n_nodes + n_comp,
        "radial_end_share": round(radial / len(subs), 3) if subs else 0.0,
        "kv_provenance": prov,
        "kv_tag_share": round(prov["tag"] / n_branch, 3),
    }


def render(rows) -> str:
    head = (f"{'region':9s} {'branch':>6s} {'subs':>5s} {'comps':>5s} "
            f"{'cover':>6s} {'loops':>5s} {'radial':>6s} {'kv tag':>6s}")
    out = [head, "-" * len(head)]
    for r in rows:
        if not r or r.get("n_branches", 0) == 0:
            out.append(f"{(r or {}).get('region', '?'):9s} {'-':>6s}")
            continue
        out.append(
            f"{r['region']:9s} {r['n_branches']:>6d} {r['n_substations']:>5d} "
            f"{r['n_components']:>5d} {100 * r['largest_comp_share']:>5.1f}% "
            f"{r['cycle_rank']:>5d} {100 * r['radial_end_share']:>5.1f}% "
            f"{100 * r['kv_tag_share']:>5.1f}%")
    return "\n".join(out)


def main(argv=None) -> int:
    from src.regions import REGIONS

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--regions", nargs="*", default=list(REGIONS))
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    rows = []
    for region in args.regions:
        print(f"  ... {region}", file=sys.stderr)
        try:
            rows.append(kv66_metrics(region))
        except FileNotFoundError:
            rows.append({"region": region, "n_branches": 0})
    print(render(rows))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=1, ensure_ascii=False)
        print(f"\nreport -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
