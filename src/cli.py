"""Unified command-line interface for All-Japan-Grid (``ajgrid``).

A single front door over the pipeline that the Phase C promotion moved
into ``src/``: build & solve a region's network, export CIM/CGMES, drive
the unified grid database, and serve the live map. Each sub-command is a
thin dispatcher to the existing entry points — the tool, not a rewrite.

    python -m src.cli solve okinawa --topology snapped --reconnect
    python -m src.cli cim --regions okinawa --verify
    python -m src.cli db ingest
    python -m src.cli db enrich --lines --audit
    python -m src.cli db export --verify
    python -m src.cli map            # serve docs/ at http://localhost:8080
    python -m src.cli regions

(``./ajgrid <args>`` is a convenience wrapper for ``python -m src.cli``.)
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


def cmd_db(_args, rest):
    """Drive the unified grid DB: db {ingest|export|curate|enrich} ..."""
    if not rest or rest[0] not in ("ingest", "export", "curate", "enrich"):
        print("usage: ajgrid db {ingest|export|curate|enrich} [args...]")
        return 2
    return _run(f"scripts/db/{rest[0]}.py", rest[1:])


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
        "db", help="grid DB: ingest|export|curate|enrich (pass-through)",
        add_help=False).set_defaults(func=cmd_db)

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
