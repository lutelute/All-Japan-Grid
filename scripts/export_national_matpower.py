"""Export the national model as MATPOWER cases — .mat + CSV tables (N4).

    PYTHONPATH=. python scripts/export_national_matpower.py
        [--out dist/matpower_snapped] [--islands east west] [--no-validate]

2026-10-20 から配布ケース(dist/matpower_national)は正典系譜の
scripts/export_matpower_canonical.py が書く。このスクリプトは旧 snapped 系譜の
比較用で、書き出し部 export_net は両方から使う。

Builds the four synchronous islands (hokkaido / east / west / okinawa)
with the canonical national solver (``solve_island`` — the AC-convergent
model of ledger 63), rebases to the MATPOWER-conventional 100 MVA system
base (results-invariant; the rebased net is re-solved so tables and
state agree), and writes per island:

- ``<island>.mat`` — canonical MATPOWER case v2 (baseMVA / version /
  bus / branch / gen at loadcase input widths, 1-based bus numbering)
  loadable by MATPOWER ``loadcase``/``runpf``, PYPOWER, psdat and
  pandapower ``from_mpc``;
- ``<island>_{bus,branch,gen}.csv`` — the same tables as CSV;
- ``meta.json`` — provenance (HEAD, baseMVA, async links) plus the
  round-trip validation: each .mat is re-imported via ``from_mpc`` and
  re-solved, and the max |ΔVM| / |ΔVA| against the exporting solution
  is recorded. A multi-component island carries one REF bus per
  component (MATPOWER solves this; the count is recorded).

No ``gencost`` is emitted — we do not fabricate costs: the cases are
``runpf``-ready, not ``runopf``-ready. Generated artifact — outputs are
NOT committed; the script is the reproducible recipe.
"""

import argparse
import datetime as dt
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 書き出し部(列の名前・export_net・往復の確認)は src/converter/matpower_case.py に移した(2026-10-24・B1)。
# このスクリプトの export_island と旧来の import 先(scripts.export_national_matpower.export_net)はそのまま使える。
from src.converter.matpower_case import (  # noqa: E402,F401
    BR_COLS, BUS_COLS, GEN_COLS, _roundtrip_check, export_net)


def export_island(island_id, isl, out_dir, validate=True):
    import pandapower as pp
    import pandas as pd
    from pandapower.converter.matpower import to_mpc
    from scipy.io import savemat

    from scripts.run_national_powerflow import solve_island
    from src.converter.matpower_exporter import canonical_mpc
    from src.powerflow.load_estimator import load_demand_config

    cfg = load_demand_config()
    net_dc, dc, net_ac, ac, _syn, _nsh, _diag = solve_island(
        island_id, isl, cfg, 0.6)
    ac_ok = bool(ac.get("converged"))
    net = net_ac if ac_ok else net_dc
    return export_net(island_id, net, ac_ok, out_dir, validate=validate,
                      regions=isl["regions"], frequency=isl["frequency"])


def main(argv=None) -> int:
    from src.powerflow.national import build_island_networks

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="dist/matpower_snapped")
    ap.add_argument("--islands", nargs="*",
                    help="subset of islands (default: all four)")
    ap.add_argument("--no-validate", action="store_true",
                    help="skip the from_mpc round-trip re-solve")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)

    islands, async_links = build_island_networks()
    if args.islands:
        islands = {k: v for k, v in islands.items() if k in args.islands}
    meta = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(
                timespec="seconds"),
            "head": subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                   capture_output=True, text=True,
                                   check=False).stdout.strip(),
            "base_mva": 100.0,
            "matpower_version": "2",
            "async_links": [str(a) for a in async_links],
            "note": ("canonical MATPOWER case v2 per island (.mat: baseMVA/"
                     "version/bus/branch/gen at loadcase widths, 1-based "
                     "buses, 100 MVA base, mpc.bus_name cell array) + the "
                     "same tables as CSV + name sidecars (issue #26): "
                     "{island}_busname.csv (BUS_I,name,base_kv,zone,lat,"
                     "lon), {island}_branchname.csv (row,F_BUS,T_BUS,kind,"
                     "name,parallel), {island}_genname.csv (row,GEN_BUS,"
                     "kind=slack|gen,name,fuel,PG,PMAX); no gencost (no "
                     "fabricated costs) — runpf-ready, not runopf; "
                     "multi-component islands carry one REF per component"),
            "islands": []}
    for island_id, isl in islands.items():
        print(f"  ... {island_id}", file=sys.stderr)
        meta["islands"].append(export_island(island_id, isl, args.out,
                                             validate=not args.no_validate))
    with open(os.path.join(args.out, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1, ensure_ascii=False)
    for i in meta["islands"]:
        v = i.get("validation", {})
        vtxt = (f" roundtrip dVA={v.get('max_dva_deg', '-')}"
                f" dVM={v.get('max_dvm_pu', '-')}"
                if v.get("roundtrip") == "ok"
                else f" validation={v.get('roundtrip', 'skipped')}")
        print(f"  {i['island']:9} bus {i['n_bus']:>6,} branch "
              f"{i['n_branch']:>6,} gen {i['n_gen']:>5,} "
              f"ref {i['n_ref_buses']:>3} ({i['frequency_hz']}Hz, "
              f"AC={'OK' if i['ac_converged'] else 'NG'}){vtxt}")
    print(f"-> {args.out}/ (+meta.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
