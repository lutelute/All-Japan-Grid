"""Export the national model as MATPOWER cases — .mat + CSV tables (N4).

    PYTHONPATH=. python scripts/export_national_matpower.py
        [--out dist/matpower_national] [--islands east west] [--no-validate]

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

BUS_COLS = ["BUS_I", "TYPE", "PD", "QD", "GS", "BS", "AREA", "VM", "VA",
            "BASE_KV", "ZONE", "VMAX", "VMIN"]
BR_COLS = ["F_BUS", "T_BUS", "R", "X", "B", "RATE_A", "RATE_B", "RATE_C",
           "TAP", "SHIFT", "STATUS", "ANGMIN", "ANGMAX"]
GEN_COLS = ["GEN_BUS", "PG", "QG", "QMAX", "QMIN", "VG", "MBASE", "STATUS",
            "PMAX", "PMIN"]


def _roundtrip_check(mat_path, inner, f_hz, ac_ok):
    """Re-import the saved case via from_mpc, re-solve, compare states."""
    import numpy as np
    import pandapower as pp
    from pandapower.converter.matpower import from_mpc

    net2 = from_mpc(mat_path, f_hz=f_hz, casename_mpc_file="mpc")
    if ac_ok:
        pp.runpp(net2)
    else:
        pp.rundcpp(net2)
    # from_mpc creates buses in mpc row order — compare row-by-row on
    # in-service rows (TYPE != 4).
    act = inner["bus"][:, 1] != 4
    va2 = net2.res_bus.va_degree.values[: len(act)]
    dva = float(np.nanmax(np.abs(va2[act] - inner["bus"][act, 8])))
    out = {"roundtrip": "ok", "max_dva_deg": round(dva, 6),
           "resolved": bool(net2.converged)}
    if ac_ok:
        vm2 = net2.res_bus.vm_pu.values[: len(act)]
        out["max_dvm_pu"] = round(
            float(np.nanmax(np.abs(vm2[act] - inner["bus"][act, 7]))), 8)
    return out


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
    # MATPOWER convention: 100 MVA system base. Rebasing only changes the
    # p.u. scaling, not the physics (verified ΔVA ~1e-6 deg); the rebased
    # net is re-solved so the exported tables and the embedded VM/VA agree.
    net.sn_mva = 100.0
    if ac_ok:
        pp.runpp(net)
    else:
        pp.rundcpp(net)
    mpc = canonical_mpc(to_mpc(net, mode="pf",
                               init="results" if ac_ok else "flat"))
    inner = mpc["mpc"]

    mat_path = os.path.join(out_dir, f"{island_id}.mat")
    savemat(mat_path, mpc, do_compression=True)

    stems = {}
    for name, cols in (("bus", BUS_COLS), ("branch", BR_COLS),
                       ("gen", GEN_COLS)):
        df = pd.DataFrame(inner[name][:, :len(cols)], columns=cols)
        path = os.path.join(out_dir, f"{island_id}_{name}.csv")
        df.to_csv(path, index=False)
        stems[name] = len(df)

    rec = {"island": island_id, "regions": isl["regions"],
           "frequency_hz": isl["frequency"],
           "n_bus": stems["bus"], "n_branch": stems["branch"],
           "n_gen": stems["gen"],
           "n_ref_buses": int((inner["bus"][:, 1] == 3).sum()),
           "ac_converged": ac_ok, "mat": os.path.basename(mat_path)}
    if validate:
        try:
            rec["validation"] = _roundtrip_check(
                mat_path, inner, isl["frequency"], ac_ok)
        except Exception as e:  # noqa: BLE001 — record, don't hide
            rec["validation"] = {"roundtrip": f"failed:{type(e).__name__}",
                                 "detail": str(e)[:200]}
    return rec


def main(argv=None) -> int:
    from src.powerflow.national import build_island_networks

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="dist/matpower_national")
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
                     "buses, 100 MVA base) + the same tables as CSV; no "
                     "gencost (no fabricated costs) — runpf-ready, not "
                     "runopf; multi-component islands carry one REF per "
                     "component"),
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
