"""Topology & power-flow quality KPIs.

Three measurement levels, from raw evidence to delivered product:

1. ``tag_coverage(region)`` — how much OSM evidence exists at all
   (voltage / circuits / cables / ref fill rates on line features).
   This bounds what any builder can honestly extract.
2. ``topology_metrics(region)`` — builder-level connectivity of the
   vertex-snap graph with NO synthetic additions: fragmentation
   (components), largest-component coverage, isolated substations,
   unknown-voltage share. The honest "how connected is OSM really".
3. ``solved_metrics(region)`` — the delivered model after reconnection,
   transforms and DC/AC solve: synthetic-line rate (how much of the
   published network is fabricated bridging), convergence, voltage
   sanity, loading. This is what the published pages are made of.

The headline KPI is ``synthetic_rate``: the fraction of solved-network
branches that are reconnector fabrications rather than OSM-traced lines
(2026-06 baseline: kansai ~15%, kyushu ~9%, tokyo ~6%). Topology work
(adaptive snapping, multi-voltage substations) must push it down; this
module is how we prove it moved.

CLI::

    python -m src.validation.topology_metrics okinawa shikoku --solve
    python -m src.validation.topology_metrics --all --solve --json docs/reports/topology_baseline.json
    python -m src.validation.topology_metrics --all --baseline docs/reports/topology_baseline.json

(also reachable as ``ajgrid validate --topology ...``).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.powerflow.snapped_topology import DATA_DIR

# Line-feature tags that carry electrical evidence. ``circuits`` is the
# direct OSM statement of parallel-circuit count (filled on ~50-60% of
# Japanese lines) — stronger evidence than the geometric inference the
# builder currently uses, hence tracked here as exploitable headroom.
_EVIDENCE_TAGS = ("voltage", "circuits", "cables", "wires", "ref", "operator")


def _filled(value) -> bool:
    return value not in (None, "", "null")


def tag_coverage(region: str, data_dir: str | None = None) -> dict | None:
    """Fill rates of electrically meaningful OSM tags on line features."""
    data_dir = data_dir or DATA_DIR
    path = os.path.join(data_dir, f"{region}_lines.geojson")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    feats = data.get("features", [])
    n = len(feats)
    counts = Counter()
    for ft in feats:
        props = ft.get("properties", {})
        for tag in _EVIDENCE_TAGS:
            if _filled(props.get(tag)):
                counts[tag] += 1
    return {
        "n_line_features": n,
        **{f"{tag}_fill": round(counts[tag] / n, 4) if n else 0.0
           for tag in _EVIDENCE_TAGS},
    }


def topology_metrics(region: str, builder: str = "snapped", snap_km: float = 1.5,
                     keep_stubs: bool = True, data_dir: str | None = None) -> dict | None:
    """Builder-level connectivity KPIs (no reconnection, no solving).

    ``n_components`` here is the honest OSM fragmentation; the solved
    network reaches 1 component only by adding synthetic bridges, which
    ``solved_metrics`` quantifies separately.
    """
    import networkx as nx

    t0 = time.time()
    if builder == "snapped":
        from src.powerflow.snapped_topology import build_network_snapped
        net = build_network_snapped(region, snap_km=snap_km,
                                    keep_stubs=keep_stubs, data_dir=data_dir)
    elif builder == "legacy":
        from src.powerflow.legacy_build import build_network_from_geojson
        net = build_network_from_geojson(region)
    else:
        raise ValueError(f"unknown builder: {builder}")
    if net is None:
        return None

    g = nx.Graph()
    g.add_nodes_from(s.id for s in net.substations)
    for ln in net.transmission_lines:
        g.add_edge(ln.from_substation_id, ln.to_substation_id)

    real_subs = [s.id for s in net.substations if "_jct_" not in s.id]
    junctions = [s.id for s in net.substations if "_jct_" in s.id]
    comps = list(nx.connected_components(g))
    sizes = sorted((len(c) for c in comps), reverse=True)
    largest = sizes[0] if sizes else 0
    n_nodes = g.number_of_nodes()

    kv_hist = Counter()
    unknown_kv = 0
    multi_circuit = 0
    max_parallel = 1
    circuit_km = 0.0
    conn_kinds = Counter()
    circuit_evidence = Counter()
    for ln in net.transmission_lines:
        kv = float(ln.voltage_kv or 0)
        if kv <= 0:
            unknown_kv += 1
        else:
            kv_hist[int(kv)] += 1
        par = int(getattr(ln, "num_parallel", 1) or 1)
        if par > 1:
            multi_circuit += 1
        max_parallel = max(max_parallel, par)
        circuit_km += float(ln.length_km or 0) * par
        # connection provenance written by the builder (conn=S-J;circuits=tag)
        desc = getattr(ln, "description", "") or ""
        for part in desc.split(";"):
            if part.startswith("conn="):
                conn_kinds["-".join(sorted(part[5:].split("-")))] += 1
            elif part.startswith("circuits="):
                circuit_evidence[part[9:]] += 1

    n_branches = len(net.transmission_lines)
    return {
        "builder": builder,
        "n_real_subs": len(real_subs),
        "n_junctions": len(junctions),
        "n_branches": n_branches,
        "n_gens": len(net.generators),
        "n_components": len(comps),
        "largest_comp_share": round(largest / n_nodes, 4) if n_nodes else 0.0,
        "isolated_real_subs": sum(1 for s in real_subs if g.degree(s) == 0),
        "stub_junctions": sum(1 for j in junctions if g.degree(j) == 1),
        "unknown_kv_branches": unknown_kv,
        "unknown_kv_share": round(unknown_kv / n_branches, 4) if n_branches else 0.0,
        "kv_histogram": {str(k): v for k, v in sorted(kv_hist.items())},
        "multi_circuit_branches": multi_circuit,
        "max_parallel": max_parallel,
        "circuit_km": round(circuit_km, 1),
        "conn_kinds": dict(conn_kinds),
        "circuit_evidence": dict(circuit_evidence),
        "evidenced_circuit_share": round(
            (circuit_evidence["tag"] + circuit_evidence["cables"])
            / max(sum(circuit_evidence.values()), 1), 4),
        "build_s": round(time.time() - t0, 2),
    }


def solved_metrics(region: str, topology: str = "snapped",
                   reconnect: bool = True, backbone_kv: float | None = None) -> dict | None:
    """Delivered-model KPIs: run the full build_and_solve pipeline.

    ``synthetic_rate`` = reconnector-fabricated branches / total solved
    branches — the price paid for n_components=1. Honest topology
    improvements reduce it; anything that *raises* it is hiding new
    fragmentation behind fabrication.

    ``backbone_kv`` measures the backbone model instead (sub-transmission
    aggregated away; see transforms.reduce_to_backbone).
    """
    from src.powerflow.load_estimator import load_demand_config
    from src.powerflow.pipeline import build_and_solve

    t0 = time.time()
    result = build_and_solve(region, load_demand_config(),
                             topology=topology, reconnect=reconnect,
                             backbone_kv=backbone_kv)
    if result is None:
        return None
    _net_dc, dc_res, net_ac, ac_res, info, _geom = result

    n_lines = info["n_lines"]
    out = {
        "topology": info["topology"],
        "n_buses": info["n_buses"],
        "n_lines": n_lines,
        "n_trafos": info["n_trafos"],
        "n_components": info["n_components"],
        "n_disabled_buses": info["n_buses"] - info["n_active_buses"],
        "n_synthetic_lines": info["n_synthetic_lines"],
        "synthetic_rate": round(info["n_synthetic_lines"] / n_lines, 4) if n_lines else 0.0,
        "total_load_mw": round(info["total_load_mw"], 1),
        "total_gen_mw": round(info["total_gen_mw"], 1),
        "dc_converged": bool(dc_res.get("converged")),
        "ac_converged": bool(ac_res.get("converged")),
        "solve_s": round(time.time() - t0, 2),
    }
    if info.get("backbone"):
        out["backbone"] = info["backbone"]
    if ac_res.get("converged"):
        out.update({
            "ac_vm_min": round(ac_res.get("vm_pu_min", 0.0), 4),
            "ac_vm_max": round(ac_res.get("vm_pu_max", 0.0), 4),
            "ac_va_spread_deg": round(
                ac_res.get("va_deg_max", 0.0) - ac_res.get("va_deg_min", 0.0), 1),
            "ac_max_loading_pct": round(ac_res.get("max_loading_pct", 0.0), 1),
        })
    elif net_ac is not None:
        out["ac_error"] = str(ac_res.get("error", ""))[:80]
    return out


def gather(regions, solve: bool = False, builder: str = "snapped",
           snap_km: float = 1.5, data_dir: str | None = None,
           backbone_kv: float | None = None, progress=None) -> list[dict]:
    """Compute all KPI levels for each region; returns one row per region."""
    rows = []
    for region in regions:
        if progress:
            progress(region)
        row = {"region": region, "snap_km": snap_km}
        if backbone_kv:
            row["backbone_kv"] = backbone_kv
        row["tags"] = tag_coverage(region, data_dir=data_dir)
        row["topology"] = topology_metrics(region, builder=builder,
                                           snap_km=snap_km, data_dir=data_dir)
        if solve:
            row["solved"] = solved_metrics(region, topology=builder,
                                           backbone_kv=backbone_kv)
        rows.append(row)
    return rows


# ── reporting ────────────────────────────────────────────────────────────────

_TABLE_HEADER = (
    f"{'region':9s} {'comps':>5s} {'cover':>6s} {'unknownV':>8s} "
    f"{'circ%':>5s} | {'buses':>5s} {'lines':>5s} {'synth':>5s} {'rate':>6s} "
    f"{'DC':>3s} {'AC':>3s} {'vm_min':>6s} {'load%':>6s}")


def render(rows) -> str:
    """One line per region: topology quality | solved quality."""
    lines = [_TABLE_HEADER, "-" * len(_TABLE_HEADER)]
    for row in rows:
        topo = row.get("topology") or {}
        tags = row.get("tags") or {}
        s = row.get("solved") or {}
        ac = {True: "ok", False: "NO"}.get(s.get("ac_converged"), "-")
        dc = {True: "ok", False: "NO"}.get(s.get("dc_converged"), "-")
        lines.append(
            f"{row['region']:9s} "
            f"{topo.get('n_components', '-'):>5} "
            f"{100 * topo.get('largest_comp_share', 0):>5.1f}% "
            f"{100 * topo.get('unknown_kv_share', 0):>7.1f}% "
            f"{100 * tags.get('circuits_fill', 0):>4.0f}% | "
            f"{s.get('n_buses', '-'):>5} {s.get('n_lines', '-'):>5} "
            f"{s.get('n_synthetic_lines', '-'):>5} "
            f"{100 * s.get('synthetic_rate', 0):>5.1f}% "
            f"{dc:>3s} {ac:>3s} "
            f"{s.get('ac_vm_min', float('nan')):>6.3f} "
            f"{s.get('ac_max_loading_pct', float('nan')):>6.1f}")
    return "\n".join(lines)


_DIFF_KEYS = (
    ("topology", "n_components"),
    ("topology", "largest_comp_share"),
    ("solved", "n_synthetic_lines"),
    ("solved", "synthetic_rate"),
    ("solved", "dc_converged"),
    ("solved", "ac_converged"),
    ("solved", "ac_vm_min"),
)


def compare(rows, baseline_rows) -> str:
    """Per-region KPI deltas vs a baseline report (regressions stand out)."""
    base = {r["region"]: r for r in baseline_rows}
    out = []
    for row in rows:
        b = base.get(row["region"])
        if not b:
            out.append(f"{row['region']}: (no baseline)")
            continue
        deltas = []
        for section, key in _DIFF_KEYS:
            cur = (row.get(section) or {}).get(key)
            old = (b.get(section) or {}).get(key)
            if cur is None and old is None:
                continue
            if cur != old:
                deltas.append(f"{key}: {old} -> {cur}")
        out.append(f"{row['region']}: " + ("; ".join(deltas) if deltas else "unchanged"))
    return "\n".join(out)


def main(argv=None):
    from src.regions import REGIONS

    ap = argparse.ArgumentParser(
        description="Topology / power-flow quality KPI report")
    ap.add_argument("regions", nargs="*", help="regions (default: --all)")
    ap.add_argument("--all", action="store_true", help="all 10 regions")
    ap.add_argument("--solve", action="store_true",
                    help="also run build_and_solve (synthetic rate, AC/DC)")
    ap.add_argument("--builder", choices=["snapped", "legacy"], default="snapped")
    ap.add_argument("--snap-km", type=float, default=1.5)
    ap.add_argument("--backbone", nargs="?", const=154.0, type=float, default=None,
                    metavar="KV", help="measure the >=KV backbone model instead")
    ap.add_argument("--json", help="write the full report to this path")
    ap.add_argument("--baseline", help="compare against a previous --json report")
    args = ap.parse_args(argv)

    regions = list(REGIONS) if (args.all or not args.regions) else args.regions
    rows = gather(regions, solve=args.solve, builder=args.builder,
                  snap_km=args.snap_km, backbone_kv=args.backbone,
                  progress=lambda r: print(f"  ... {r}", file=sys.stderr))

    print(render(rows))
    if args.json:
        os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=1, ensure_ascii=False)
        print(f"\nreport -> {args.json}")
    if args.baseline:
        with open(args.baseline, encoding="utf-8") as f:
            baseline_rows = json.load(f)
        print("\nvs baseline:")
        print(compare(rows, baseline_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
