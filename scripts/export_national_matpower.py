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
    return export_net(island_id, net, ac_ok, out_dir, validate=validate,
                      regions=isl["regions"], frequency=isl["frequency"])


def export_net(island_id, net, ac_ok, out_dir, validate=True,
               regions=None, frequency=None):
    """解けた(または解けなかった)pandapower netをMATPOWERケースとして書く。

    系譜非依存の書き出し部(2026-08-20分割): snapped系(export_island)からも
    正典系(scripts/export_matpower_canonical.py)からも呼ぶ。
    """
    import pandapower as pp
    import pandas as pd
    from pandapower.converter.matpower import to_mpc
    from scipy.io import savemat

    from src.converter.matpower_exporter import canonical_mpc

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

    # Name mappings (issue #26): the names exist in the pandapower net and
    # were dropped at to_mpc's numeric conversion. Row-aligned via
    # _pd2ppc_lookups so BUS_I / branch row / gen row resolve to substation,
    # line and plant names — the machine joins a DB pipeline needs.
    import numpy as np

    from scripts.export_powerflow_pages import _parse_bus_coords

    lk = net._pd2ppc_lookups
    n_ppc_bus = inner["bus"].shape[0]
    bus_name = [""] * n_ppc_bus
    bus_lat = [None] * n_ppc_bus
    bus_lon = [None] * n_ppc_bus
    bus_zone = [""] * n_ppc_bus
    for pp_i in net.bus.index:
        row = int(lk["bus"][pp_i])
        if not (0 <= row < n_ppc_bus) or bus_name[row]:
            continue
        bus_name[row] = str(net.bus.at[pp_i, "name"])
        z = net.bus.at[pp_i, "zone"]
        bus_zone[row] = z if isinstance(z, str) else ""
        lon, lat = _parse_bus_coords(net, pp_i)
        bus_lat[row], bus_lon[row] = lat, lon
    pd.DataFrame({
        "BUS_I": inner["bus"][:, 0].astype(int),
        "name": bus_name,
        "base_kv": inner["bus"][:, 9],
        "zone_region": bus_zone,
        "lat": bus_lat, "lon": bus_lon,
    }).to_csv(os.path.join(out_dir, f"{island_id}_busname.csv"),
              index=False)

    n_br = inner["branch"].shape[0]
    br_name = [""] * n_br
    br_kind = [""] * n_br
    br_par = [1] * n_br
    lo, hi = lk["branch"].get("line", (0, 0))
    live_lines = [i for i in net.line.index if net.line.at[i, "in_service"]]
    for k, li in enumerate(live_lines):
        row = lo + k
        if row < hi and row < n_br:
            br_name[row] = str(net.line.at[li, "name"])[:80]
            br_kind[row] = "line"
            if "parallel" in net.line.columns:
                br_par[row] = int(net.line.at[li, "parallel"])
    lo, hi = lk["branch"].get("trafo", (0, 0))
    live_tr = [i for i in net.trafo.index if net.trafo.at[i, "in_service"]]
    for k, ti in enumerate(live_tr):
        row = lo + k
        if row < hi and row < n_br:
            br_name[row] = str(net.trafo.at[ti, "name"])[:80]
            br_kind[row] = "trafo"
    pd.DataFrame({
        "row": range(1, n_br + 1),
        "F_BUS": inner["branch"][:, 0].astype(int),
        "T_BUS": inner["branch"][:, 1].astype(int),
        "kind": br_kind,
        "name": br_name,
        "parallel": br_par,
    }).to_csv(os.path.join(out_dir, f"{island_id}_branchname.csv"),
              index=False)

    n_g = inner["gen"].shape[0]
    g_name = [""] * n_g
    g_fuel = [""] * n_g
    g_kind = [""] * n_g
    n_eg = int(net.ext_grid["in_service"].sum())
    for k, ei in enumerate(i for i in net.ext_grid.index
                           if net.ext_grid.at[i, "in_service"]):
        if k < n_g:
            g_name[k] = str(net.ext_grid.at[ei, "name"])
            g_kind[k] = "slack"
    for k, gi in enumerate(i for i in net.gen.index
                           if net.gen.at[i, "in_service"]):
        row = n_eg + k
        if row < n_g:
            g_name[row] = str(net.gen.at[gi, "name"])[:80]
            g_fuel[row] = (str(net.gen.at[gi, "type"]).split(";")[0]
                           if "type" in net.gen.columns else "")
            g_kind[row] = "gen"
    pd.DataFrame({
        "row": range(1, n_g + 1),
        "GEN_BUS": inner["gen"][:, 0].astype(int),
        "kind": g_kind,
        "name": g_name,
        "fuel": g_fuel,
        "PG": inner["gen"][:, 1],
        "PMAX": inner["gen"][:, 8],
    }).to_csv(os.path.join(out_dir, f"{island_id}_genname.csv"),
              index=False)

    # mpc.bus_name — MATPOWER's official optional field (cell array)
    mpc["mpc"]["bus_name"] = np.array(
        [n or f"bus_{i+1}" for i, n in enumerate(bus_name)], dtype=object)

    mat_path = os.path.join(out_dir, f"{island_id}.mat")
    savemat(mat_path, mpc, do_compression=True)

    stems = {}
    for name, cols in (("bus", BUS_COLS), ("branch", BR_COLS),
                       ("gen", GEN_COLS)):
        df = pd.DataFrame(inner[name][:, :len(cols)], columns=cols)
        path = os.path.join(out_dir, f"{island_id}_{name}.csv")
        df.to_csv(path, index=False)
        stems[name] = len(df)

    rec = {"island": island_id, "regions": regions,
           "frequency_hz": frequency,
           "n_bus": stems["bus"], "n_branch": stems["branch"],
           "n_gen": stems["gen"],
           "n_ref_buses": int((inner["bus"][:, 1] == 3).sum()),
           "ac_converged": ac_ok, "mat": os.path.basename(mat_path)}
    if validate:
        try:
            rec["validation"] = _roundtrip_check(
                mat_path, inner, frequency, ac_ok)
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
