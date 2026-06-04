#!/usr/bin/env python3
"""Export Level-2 CGMES (a solvable power-flow case) per region.

For each region this builds the snapped pandapower network (``build_and_solve``),
exports it as CGMES EQ/TP/SSH/SV/GL via :mod:`src.cim.level2`, and — with
``--verify`` — round-trips it through pandapower ``cim2pp`` + ``runpp`` to
confirm the exported model still solves.

Requires pandapower, so run this on the compute server (not a laptop):
    python scripts/export_cim_level2.py --verify
    python scripts/export_cim_level2.py --regions okinawa hokkaido --verify
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pandapower as pp  # noqa: E402

from scripts.export_powerflow_pages import build_and_solve  # noqa: E402
from src.cim.boundary import generate_boundary  # noqa: E402
from src.cim.level2 import net_to_cgmes  # noqa: E402
from src.powerflow.load_estimator import load_demand_config  # noqa: E402

# Regional synchronous-system frequency (Hz).
REGION_FREQUENCY_HZ = {
    "hokkaido": 50, "tohoku": 50, "tokyo": 50,
    "chubu": 60, "hokuriku": 60, "kansai": 60,
    "chugoku": 60, "shikoku": 60, "kyushu": 60, "okinawa": 60,
}


def _extract_net(result):
    """Pull the last pandapower network out of build_and_solve's return tuple."""
    nets = [x for x in result if isinstance(x, pp.auxiliary.pandapowerNet)]
    return nets[-1] if nets else None


def _verify(region: str, out_dir: str) -> str:
    """Round-trip the exported CGMES through cim2pp + runpp; return a verdict."""
    from pandapower.converter.cim.cim2pp.from_cim import from_cim

    files = [os.path.join(out_dir, f"{region}_L2_{p}.xml")
             for p in ["EQ", "TP", "SSH", "SV", "GL"]]
    files += [os.path.join(out_dir, "AllJapan_EQ_BD.xml"),
              os.path.join(out_dir, "AllJapan_TP_BD.xml")]
    try:
        net2 = from_cim(file_list=files)
    except Exception as e:  # noqa: BLE001
        return f"import-FAIL:{type(e).__name__}"
    if len(net2.ext_grid) == 0:
        return "no-slack"
    try:
        pp.runpp(net2)
    except Exception as e:  # noqa: BLE001
        return f"runpp-FAIL:{type(e).__name__}"
    return (f"OK gen={len(net2.gen)} ext={len(net2.ext_grid)} "
            f"vmin={float(net2.res_bus.vm_pu.min()):.3f}")


def main() -> int:
    """Export Level-2 CGMES for the requested regions; print a summary table."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regions", nargs="*", default=list(REGION_FREQUENCY_HZ))
    parser.add_argument("--out-dir", default="dist/cim_level2")
    parser.add_argument("--topology", default="snapped")
    parser.add_argument("--no-reconnect", action="store_true",
                        help="disable 5 km island reconnection")
    parser.add_argument("--verify", action="store_true",
                        help="round-trip each region through cim2pp + runpp")
    args = parser.parse_args()

    cfg = load_demand_config()
    reconnect = not args.no_reconnect
    rows = []
    header = f"{'region':10s} {'bus':>5s} {'line':>5s} {'trafo':>5s} {'load':>5s} {'gen':>5s}  verify"
    print(header)
    print("-" * len(header))
    for region in args.regions:
        try:
            result = build_and_solve(region, cfg, topology=args.topology, reconnect=reconnect)
        except Exception as e:  # noqa: BLE001
            print(f"{region:10s} build-and-solve FAILED: {str(e)[:50]}")
            continue
        net = _extract_net(result)
        if net is None:
            print(f"{region:10s} (no pandapower network returned)")
            continue
        summary = net_to_cgmes(net, region, args.out_dir,
                               f_hz=REGION_FREQUENCY_HZ.get(region, 50))
        rows.append(summary)
        print(f"{region:10s} {summary['buses']:5d} {summary['lines']:5d} "
              f"{summary['trafos']:5d} {summary['loads']:5d} {summary['gens']:5d}  (exported)")

    # shared boundary set (EQ_BD/TP_BD) covering the union of referenced voltages
    all_kv = sorted({v for r in rows for v in r.get("base_voltages", [])}, reverse=True)
    bsum = generate_boundary(args.out_dir, all_kv)
    print(f"\nBoundary: {bsum['eq_bd_objects']} BaseVoltages "
          "-> AllJapan_EQ_BD.xml / AllJapan_TP_BD.xml")

    if args.verify:
        print("\nverify (boundary-aware cim2pp + runpp):")
        for r in rows:
            r["verify"] = _verify(r["region"], args.out_dir)
            print(f"  {r['region']:10s} {r['verify']}")

    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "cim_level2_index.json"), "w", encoding="utf-8") as fh:
        json.dump({"profiles": ["EQ", "TP", "SSH", "SV", "GL", "EQ_BD", "TP_BD"],
                   "boundary_voltages_kv": all_kv, "regions": rows},
                  fh, ensure_ascii=False, indent=2)
    print(f"\nWrote {len(rows)} region(s) + boundary to {args.out_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
