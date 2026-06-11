"""National N-1 screening — top-corridor outages on the island models (S1).

    PYTHONPATH=. python scripts/n1_screening.py [--islands east west]
        [--top 50] [--json docs/reports/n1_screening_<date>.json]

For each island, the base DC solve ranks REAL corridors by loading
(non-physical elements — intra-substation stubs, recon bridges, tap
joints — are excluded by their non-binding ratings, ledger 65; bundle-
refined ratings from ledger 66 apply). Each of the top corridors is
taken out in turn: if the outage splits the graph the stranded bus
count is recorded (no fake solve); otherwise the island is re-solved
DC and NEW overloads (>100% on real lines vs the base set) are counted.

This is a screening, not a security assessment: synthetic ratings and
a single demand snapshot bound what the numbers can claim — recorded
in the output note.
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def screen_island(island_id, isl, cfg, top_n=50):
    import networkx as nx
    import pandapower as pp

    from scripts.run_national_powerflow import solve_island

    net_dc, dc, _net_ac, _ac, _syn, _nsh, _diag = solve_island(
        island_id, isl, cfg, 0.6)
    if not dc.get("converged"):
        return {"island": island_id, "error": "base DC not converged"}

    names = net_dc.line["name"].astype(str)
    phys = (~(names.str.contains("intra-substation")
              | names.str.startswith("recon_line")
              | (net_dc.line["length_km"] <= 0.06))
            & net_dc.line["in_service"])
    ld = net_dc.res_line["loading_percent"]
    base_over = set(net_dc.line.index[(ld > 100) & phys])
    ranked = ld[phys.reindex(ld.index).fillna(False)].sort_values(
        ascending=False).head(top_n)

    results = []
    for li in ranked.index:
        # connectivity check without the corridor
        G = nx.Graph()
        for i in net_dc.line.index:
            if i == li or not net_dc.line.at[i, "in_service"]:
                continue
            G.add_edge(int(net_dc.line.at[i, "from_bus"]),
                       int(net_dc.line.at[i, "to_bus"]))
        for t in net_dc.trafo.itertuples():
            if t.in_service:
                G.add_edge(int(t.hv_bus), int(t.lv_bus))
        fb, tb = int(net_dc.line.at[li, "from_bus"]), int(net_dc.line.at[li, "to_bus"])
        rec = {"line": str(net_dc.line.at[li, "name"])[:40],
               "base_loading_pct": round(float(ld.at[li]), 1)}
        if fb in G and tb in G and not nx.has_path(G, fb, tb):
            comp = nx.node_connected_component(G, tb)
            slacks = {int(e.bus) for e in net_dc.ext_grid.itertuples()
                      if e.in_service}
            stranded = comp if not (comp & slacks) else \
                nx.node_connected_component(G, fb)
            rec["verdict"] = "splits"
            rec["stranded_buses"] = len(stranded)
        else:
            net_dc.line.at[li, "in_service"] = False
            try:
                pp.rundcpp(net_dc)
                ld2 = net_dc.res_line["loading_percent"]
                new_over = set(net_dc.line.index[(ld2 > 100) & phys
                                                 & net_dc.line["in_service"]])
                rec["verdict"] = "ok" if not (new_over - base_over) \
                    else "cascading_overloads"
                rec["new_overloads"] = len(new_over - base_over)
                worst = (ld2[phys & net_dc.line["in_service"]]).max()
                rec["post_max_loading_pct"] = round(float(worst), 1)
            except Exception as e:        # noqa: BLE001 — record, continue
                rec["verdict"] = f"solve_failed:{type(e).__name__}"
            net_dc.line.at[li, "in_service"] = True
        results.append(rec)
    pp.rundcpp(net_dc)   # restore base state results

    n_split = sum(1 for r in results if r["verdict"] == "splits")
    n_casc = sum(1 for r in results if r["verdict"] == "cascading_overloads")
    return {"island": island_id, "n_screened": len(results),
            "base_overloads": len(base_over),
            "n_splits": n_split, "n_cascading": n_casc,
            "n_ok": sum(1 for r in results if r["verdict"] == "ok"),
            "worst": sorted([r for r in results
                             if r["verdict"] != "ok"],
                            key=lambda r: -(r.get("new_overloads", 0)
                                            + r.get("stranded_buses", 0)))[:8],
            "results": results}


def main(argv=None) -> int:
    from src.powerflow.load_estimator import load_demand_config
    from src.powerflow.national import build_island_networks

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--islands", nargs="*", default=["east", "west"])
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    islands, _async = build_island_networks()
    cfg = load_demand_config()
    out = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(
               timespec="seconds"),
           "note": ("screening on synthetic ratings + one demand snapshot — "
                    "ordering and structural verdicts are meaningful, exact "
                    "margins are not"),
           "islands": []}
    for iid in args.islands:
        print(f"  ... {iid}", file=sys.stderr)
        out["islands"].append(screen_island(iid, islands[iid], cfg,
                                            top_n=args.top))
    for isl in out["islands"]:
        if "error" in isl:
            print(f"{isl['island']}: {isl['error']}")
            continue
        print(f"{isl['island']}: {isl['n_screened']} outages -> "
              f"ok {isl['n_ok']} / cascading {isl['n_cascading']} / "
              f"splits {isl['n_splits']} (base overloads {isl['base_overloads']})")
        for w in isl["worst"][:4]:
            print(f"   {w['line']:30} {w['verdict']:20} "
                  f"+over={w.get('new_overloads', '-')} "
                  f"stranded={w.get('stranded_buses', '-')}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1, ensure_ascii=False)
        print(f"-> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
