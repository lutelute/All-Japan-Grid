#!/usr/bin/env python3
"""Export Level-2 CGMES (a solvable power-flow case) per region.

For each region this builds the snapped pandapower network (``build_and_solve``),
exports it as CGMES EQ/TP/SSH/SV/GL via :mod:`src.cim.level2`, and — with
``--verify`` — round-trips it through pandapower ``cim2pp`` + ``runpp`` to
confirm the exported model still solves.

Requires pandapower, so run this on the compute server (not a laptop):
    python scripts/export_cim_level2.py --verify
    python scripts/export_cim_level2.py --regions okinawa hokkaido --verify

正典から書く(2026-10-21・既定): ``--topology canonical`` は地域別のスナップ済みの網(旧系譜)ではなく、
配布ケース(dist/matpower_national・scripts/export_matpower_canonical.py)と同じ正典の網を 4 つの
同期島ごとに組み、同じ素朴な NR で解いて(解けない島は同じく 66 kV の木を畳む)書き出す。
既定の出力先は dist/cim_canonical。旧系譜は --topology snapped で dist/cim_level2 へ(比較用に残す)。
    python scripts/export_cim_level2.py --topology canonical --verify
    python scripts/export_cim_level2.py --topology canonical --regions okinawa --verify
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pandapower as pp  # noqa: E402

from src.powerflow.pipeline import build_and_solve  # noqa: E402
from src.cim.boundary import BOUNDARY_VOLTAGES, generate_boundary  # noqa: E402
from src.cim.level2 import net_to_cgmes  # noqa: E402
from src.powerflow.load_estimator import load_demand_config  # noqa: E402
from src.regions import REGION_FREQUENCY_HZ  # noqa: E402


CANONICAL_ISLANDS = ("okinawa", "hokkaido", "east", "west")


def _canonical_net(island):
    """配布ケースと同じ正典の網を組んで解く。返り値は (解いた網, 解き方)。"""
    from scripts.export_matpower_canonical import build_canonical_net, solve_canonical
    from scripts.run_full_powerflow_from_db import ISLAND_FREQ

    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                           "docs", "data", "built", "all.json"), encoding="utf-8") as f:
        built = json.load(f)
    # 地点需要の CSV(data/external・git の外)があれば配布ケースと同じく使う。無い所(CI)では使わずに組む
    # (10-21 実測: 配布値との差は損失 0.05pt・vm 0.003pu 以内)
    from src.powerflow import point_demand as pdm
    use_pd = os.path.exists(pdm.CSV)
    net0 = build_canonical_net(island, built["nodes"], built["edges"], ISLAND_FREQ[island],
                               point_demand=use_pd)
    net, ok, how, red, _spread = solve_canonical(net0)
    mode = f"canonical-{how}" + ("" if use_pd else "-no-point-demand")
    if red:
        mode = f"canonical-{how}+fold{red.get('n_removed', '?')}"
    return net, (mode if ok else mode + "+not-converged")


def _extract_net(result):
    """Pull the last pandapower network out of build_and_solve's return tuple."""
    nets = [x for x in result if isinstance(x, pp.auxiliary.pandapowerNet)]
    return nets[-1] if nets else None


def _try_runpp(net):
    """Try AC power flow with several init strategies; True if any converges.

    max_iteration=100: borderline regions (chubu/kyushu/hokuriku) need more
    than 50 NR iterations — build_and_solve's own fallback chain allows up
    to 300, and judging solvability with a tighter budget than the element
    net was solved with would misclassify real solutions as failures.
    """
    attempts = (
        ("auto", "nr"), ("dc", "nr"), ("flat", "nr"),
        # Iwamoto damped Newton: slower but robust on the ill-conditioned
        # borderline regions (hokuriku's element net converges only here).
        ("dc", "iwamoto_nr"), ("flat", "iwamoto_nr"),
    )
    for init, algorithm in attempts:
        try:
            pp.runpp(net, init=init, algorithm=algorithm, max_iteration=100)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _cim_solves(net, region, tmp_dir):
    """True if ``net`` round-trips through CGMES (cim2pp) and AC-converges."""
    from pandapower.converter.cim.cim2pp.from_cim import from_cim
    from src.cim.boundary import generate_boundary

    summary = net_to_cgmes(net, region, tmp_dir,
                           f_hz=REGION_FREQUENCY_HZ.get(region, 50))
    generate_boundary(tmp_dir, summary["base_voltages"])
    files = [os.path.join(tmp_dir, f"{region}_L2_{p}.xml")
             for p in ["EQ", "TP", "SSH", "SV", "GL"]]
    files += [os.path.join(tmp_dir, "AllJapan_EQ_BD.xml"),
              os.path.join(tmp_dir, "AllJapan_TP_BD.xml")]
    try:
        net2 = from_cim(file_list=files)
    except Exception:  # noqa: BLE001
        return False
    if len(net2.ext_grid) == 0:
        return False
    return _try_runpp(net2)


def _rebalance_generation(net, reserve: float = 1.05) -> None:
    """Scale gen/sgen dispatch to the current demand (in place).

    After demand scaling the original full-demand dispatch would leave
    the SSH physically meaningless (e.g. generation 3.5x load with the
    slack absorbing the surplus — REVIEW_FINDINGS P0 #3), so generation
    is rescaled proportionally to ``total_load * reserve``, mirroring
    build_and_solve's balance_power target.
    """
    active = net.load[net.load.get("in_service", True) == True]  # noqa: E712
    load = float(active["p_mw"].clip(lower=0).sum())
    gen_p = float(net.gen["p_mw"].sum()) if len(net.gen) else 0.0
    sgen_p = float(net.sgen["p_mw"].sum()) if len(net.sgen) else 0.0
    total = gen_p + sgen_p
    if total <= 0 or load <= 0:
        return
    factor = load * reserve / total
    if len(net.gen):
        net.gen["p_mw"] = net.gen["p_mw"] * factor
    if len(net.sgen):
        net.sgen["p_mw"] = net.sgen["p_mw"] * factor


def _ensure_solvable(net, region):
    """Return a network whose CGMES round-trip AC-converges.

    Judged by the ACTUAL round-trip (net_to_cgmes -> cim2pp -> runpp),
    not the element net. Since the export now preserves parallel
    circuits, in_service flags and km lengths, the round-trip should be
    electrically identical to the element net and regions are expected
    to pass "native". The legacy fallback ladder (reset parallels, then
    scale demand — now with generation rebalanced to match) remains as
    a documented last resort for ill-conditioned regions.
    """
    tmp = os.path.join("/tmp", f"_chk_{region}")
    if _cim_solves(net, region, tmp):
        return net, "native"
    base = copy.deepcopy(net)
    if "parallel" in base.line.columns:
        base.line["parallel"] = 1
    if "parallel" in base.trafo.columns:
        base.trafo["parallel"] = 1
    for lf in [0.8, 0.6, 0.5, 0.4, 0.3, 0.2]:
        n = copy.deepcopy(base)
        n.load["p_mw"] = n.load["p_mw"] * lf
        n.load["q_mvar"] = n.load["q_mvar"] * lf
        _rebalance_generation(n)
        if _cim_solves(n, region, tmp):
            return n, f"demand-scaled(x{lf})"
    return net, "unsolvable"


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
    # Use the SAME solver budget (_try_runpp: 100 iters + iwamoto fallback)
    # that _ensure_solvable used to judge solvability — otherwise a region
    # judged 'native' can spuriously report runpp-FAIL here (kyushu).
    if _try_runpp(net2):
        return (f"OK gen={len(net2.gen)} ext={len(net2.ext_grid)} "
                f"vmin={float(net2.res_bus.vm_pu.min()):.3f}")
    return "runpp-FAIL"


def main() -> int:
    """Export Level-2 CGMES for the requested regions; print a summary table."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regions", nargs="*", default=None,
                        help="既定: 10 地域(旧系譜) / 4 島(--topology canonical)")
    parser.add_argument("--out-dir", default=None,
                        help="既定: dist/cim_level2(旧系譜) / dist/cim_canonical(--topology canonical)")
    parser.add_argument("--topology", default="canonical",
                        help="canonical(既定・正典の 4 島) / snapped・legacy(地域別・旧系譜・比較用)")
    parser.add_argument("--no-reconnect", action="store_true",
                        help="disable 5 km island reconnection")
    parser.add_argument("--verify", action="store_true",
                        help="round-trip each region through cim2pp + runpp")
    args = parser.parse_args()

    canonical = args.topology == "canonical"
    if args.regions is None:
        args.regions = list(CANONICAL_ISLANDS) if canonical else list(REGION_FREQUENCY_HZ)
    if args.out_dir is None:
        args.out_dir = "dist/cim_canonical" if canonical else "dist/cim_level2"
    cfg = load_demand_config()
    reconnect = not args.no_reconnect
    rows = []
    header = f"{'region':10s} {'bus':>5s} {'line':>5s} {'trafo':>5s} {'load':>5s} {'gen':>5s}  verify"
    print(header)
    print("-" * len(header))
    for region in args.regions:
        if canonical:
            from scripts.run_full_powerflow_from_db import ISLAND_FREQ
            net, solve_mode = _canonical_net(region)
            summary = net_to_cgmes(net, region, args.out_dir, f_hz=ISLAND_FREQ[region])
            summary["solve_mode"] = solve_mode
            summary["lineage"] = "canonical (docs/data/built/all.json)"
            rows.append(summary)
            print(f"{region:10s} {summary['buses']:5d} {summary['lines']:5d} "
                  f"{summary['trafos']:5d} {summary['loads']:5d} {summary['gens']:5d}  {solve_mode}")
            continue
        try:
            result = build_and_solve(region, cfg, topology=args.topology, reconnect=reconnect)
            # inside the try: build_and_solve returns bare None for a
            # missing/empty region, and iterating that must not abort
            # the whole multi-region export (REVIEW_FINDINGS Phase A 次点)
            net = _extract_net(result) if result is not None else None
        except Exception as e:  # noqa: BLE001
            print(f"{region:10s} build-and-solve FAILED: {str(e)[:50]}")
            continue
        if net is None:
            print(f"{region:10s} (no pandapower network returned)")
            continue
        net, solve_mode = _ensure_solvable(net, region)
        # Refresh res_bus on the network actually being exported so the SV
        # profile is the solved state of the SSH it ships with
        # (REVIEW_FINDINGS P0 #4: kansai shipped with zero SvVoltage).
        if not _try_runpp(net):
            solve_mode += "+sv-stale"
        summary = net_to_cgmes(net, region, args.out_dir,
                               f_hz=REGION_FREQUENCY_HZ.get(region, 50))
        summary["solve_mode"] = solve_mode
        rows.append(summary)
        print(f"{region:10s} {summary['buses']:5d} {summary['lines']:5d} "
              f"{summary['trafos']:5d} {summary['loads']:5d} {summary['gens']:5d}  {solve_mode}")

    # Shared boundary set (EQ_BD/TP_BD). The voltage set is the union of the
    # national defaults, this run AND the existing index, so a --regions
    # subset run can never orphan the BaseVoltage references of regions that
    # were not re-exported (REVIEW_FINDINGS P0 #5).
    index_path = os.path.join(args.out_dir, "cim_level2_index.json")
    existing: dict = {}
    if os.path.exists(index_path):
        try:
            with open(index_path, encoding="utf-8") as fh:
                existing = json.load(fh)
        except (ValueError, OSError):
            existing = {}
    all_kv = sorted(
        {round(float(v), 3) for v in BOUNDARY_VOLTAGES}
        | {round(float(v), 3) for v in existing.get("boundary_voltages_kv", [])}
        | {round(float(v), 3) for r in rows for v in r.get("base_voltages", [])},
        reverse=True)
    bsum = generate_boundary(args.out_dir, all_kv)
    print(f"\nBoundary: {bsum['eq_bd_objects']} BaseVoltages "
          "-> AllJapan_EQ_BD.xml / AllJapan_TP_BD.xml")

    if args.verify:
        print("\nverify (boundary-aware cim2pp + runpp):")
        for r in rows:
            r["verify"] = _verify(r["region"], args.out_dir)
            print(f"  {r['region']:10s} {r['verify']}")

    # Merge into the existing index instead of overwriting it, so a
    # --regions subset run keeps the other regions' entries.
    merged = {r["region"]: r for r in existing.get("regions", [])}
    for r in rows:
        merged[r["region"]] = r
    order = list(CANONICAL_ISLANDS) if canonical else list(REGION_FREQUENCY_HZ)
    merged_rows = sorted(
        merged.values(),
        key=lambda r: order.index(r["region"]) if r["region"] in order else 99)

    os.makedirs(args.out_dir, exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as fh:
        json.dump({"profiles": ["EQ", "TP", "SSH", "SV", "GL", "EQ_BD", "TP_BD"],
                   "boundary_voltages_kv": all_kv, "regions": merged_rows},
                  fh, ensure_ascii=False, indent=2)
    print(f"\nWrote {len(rows)} region(s) + boundary to {args.out_dir}/ "
          f"(index now holds {len(merged_rows)} regions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
