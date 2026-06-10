"""Unified command-line interface for All-Japan-Grid (``ajgrid``).

A single front door over the whole pipeline: build & solve a region's
network, export & strictly validate CIM/CGMES, drive the unified grid
database, report provenance coverage, and serve the live map. Each
sub-command is a thin dispatcher to the existing entry points — the tool,
not a rewrite.

After ``pip install -e .`` this is the ``ajgrid`` console command:

    ajgrid regions                                   # list the 10 regions
    ajgrid solve okinawa --topology snapped --reconnect
    ajgrid cim --regions okinawa --verify            # export CIM/CGMES L2
    ajgrid validate --all --dir dist/cim_level2      # strict CGMES check
    ajgrid db ingest                                 # raw + restore curation
    ajgrid db enrich --p03 <GML>                     # authoritative P03
    ajgrid db export --verify
    ajgrid coverage                                  # validated-vs-synthetic
    ajgrid map                                       # serve docs/ at :8080

(``./ajgrid <args>`` and ``python -m src.cli <args>`` work without install.)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(script_rel, args):
    """Run a repo script with the current interpreter, passing args through."""
    return subprocess.call(
        [sys.executable, os.path.join(ROOT, script_rel), *args], cwd=ROOT)


# ── sub-commands ─────────────────────────────────────────────────────────────

def cmd_regions(_args, _rest):
    from src.regions import REGION_JA, REGION_FREQUENCY_HZ, REGIONS
    for r in REGIONS:
        print(f"  {r:10s} {REGION_JA[r]:<4s} {REGION_FREQUENCY_HZ[r]} Hz")
    return 0


def cmd_solve(args, _rest):
    """Build a region's snapped/legacy network and solve DC+AC."""
    from src.powerflow.load_estimator import load_demand_config
    from src.powerflow.pipeline import build_and_solve

    result = build_and_solve(
        args.region, load_demand_config(),
        topology=args.topology, reconnect=args.reconnect)
    if result is None:
        print(f"{args.region}: no network (missing data?)")
        return 1
    _dc, dc_res, net_ac, ac_res, info, _geom = result
    print(f"{args.region} [{info['topology']}]: "
          f"{info['n_buses']} buses, {info['n_lines']} lines, "
          f"{info['n_gens']} gens, {info['n_trafos']} trafos, "
          f"{info['n_components']} components")
    print(f"  DC: {'converged' if dc_res['converged'] else 'FAILED'}")
    if ac_res['converged']:
        print(f"  AC: converged, vmin={ac_res.get('vm_pu_min', 0):.3f} pu")
    else:
        print(f"  AC: FAILED ({ac_res.get('error', '')[:60]})")
    return 0


def cmd_cim(_args, rest):
    return _run("scripts/export_cim_level2.py", rest)


def cmd_validate(_args, rest):
    """Validation front door: CGMES strictness or topology/PF quality KPIs.

    ``--topology`` routes to the KPI report (fragmentation, synthetic-line
    rate, convergence vs a pinned baseline); anything else passes through
    to the strict CGMES validator, unchanged.
    """
    if "--topology" in rest:
        from src.validation.topology_metrics import main as topo_main
        return topo_main([a for a in rest if a != "--topology"])
    return _run("scripts/validate_cgmes.py", rest)


def cmd_db(_args, rest):
    """Drive the unified grid DB: db {ingest|export|curate|enrich} ..."""
    if not rest or rest[0] not in ("ingest", "export", "curate", "enrich"):
        print("usage: ajgrid db {ingest|export|curate|enrich} [args...]")
        return 2
    return _run(f"scripts/db/{rest[0]}.py", rest[1:])


def cmd_coverage(args, _rest):
    """Print the provenance & validation coverage report (honest limits)."""
    from scripts.coverage_report import gather, render
    if not os.path.exists(args.db):
        print(f"no DB at {args.db} — build one with `ajgrid db ingest`")
        return 2
    print(render(gather(args.db)))
    return 0


def cmd_map(args, _rest):
    print(f"Serving docs/ at http://localhost:{args.port}  (Ctrl-C to stop)")
    return subprocess.call(
        [sys.executable, "-m", "http.server", str(args.port), "-d", "docs"],
        cwd=ROOT)


# ── parser ───────────────────────────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        prog="ajgrid", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("regions", help="list the 10 regions").set_defaults(
        func=cmd_regions)

    s = sub.add_parser("solve", help="build & solve a region's power flow")
    s.add_argument("region")
    s.add_argument("--topology", choices=["legacy", "snapped"], default="snapped")
    s.add_argument("--reconnect", action="store_true")
    s.set_defaults(func=cmd_solve)

    sub.add_parser(
        "cim", help="export CIM/CGMES Level 2 (passes args to the script)",
        add_help=False).set_defaults(func=cmd_cim)

    sub.add_parser(
        "validate",
        help="CGMES strict check (pass-through) or --topology quality KPIs",
        add_help=False).set_defaults(func=cmd_validate)

    sub.add_parser(
        "db", help="grid DB: ingest|export|curate|enrich (pass-through)",
        add_help=False).set_defaults(func=cmd_db)

    cov = sub.add_parser(
        "coverage", help="provenance & validation coverage report (honest limits)")
    cov.add_argument("--db", default="data/grid.db")
    cov.set_defaults(func=cmd_coverage)

    m = sub.add_parser("map", help="serve the live map from docs/")
    m.add_argument("--port", type=int, default=8080)
    m.set_defaults(func=cmd_map)
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    # Sub-commands flagged add_help=False take their own args verbatim.
    args, rest = parser.parse_known_args(argv)
    return args.func(args, rest)


if __name__ == "__main__":
    raise SystemExit(main())
