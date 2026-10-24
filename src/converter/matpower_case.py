"""解けた pandapower の網を MATPOWER のケース(.mat + CSV + 名前サイドカー)として書く.

配布ケースの正本 scripts/export_matpower_canonical.py が使う書き出し部。
2026-10-24 に scripts/export_national_matpower.py(旧 snapped 系譜の比較用)から
移した(docs/reports/project_structure_2026-10-21.md の B1)。それまで正典の書き出しは、
座標を読む関数のために退役した scripts/export_powerflow_pages.py を import していて、
その先の旧系譜(build_and_solve・reconstruction)まで読み込んでいた。
中身は移す前と同じ(出力はバイト一致を確かめた)。旧来の import 先からも使える。
"""

import json
import os

BUS_COLS = ["BUS_I", "TYPE", "PD", "QD", "GS", "BS", "AREA", "VM", "VA",
            "BASE_KV", "ZONE", "VMAX", "VMIN"]
BR_COLS = ["F_BUS", "T_BUS", "R", "X", "B", "RATE_A", "RATE_B", "RATE_C",
           "TAP", "SHIFT", "STATUS", "ANGMIN", "ANGMAX"]
GEN_COLS = ["GEN_BUS", "PG", "QG", "QMAX", "QMIN", "VG", "MBASE", "STATUS",
            "PMAX", "PMIN"]


def parse_bus_coords(net, idx):
    """Extract (lon, lat) from pandapower bus geo column."""
    if "geo" in net.bus.columns:
        geo_raw = net.bus.at[idx, "geo"]
        if isinstance(geo_raw, str):
            try:
                geo_obj = json.loads(geo_raw)
                coords = geo_obj.get("coordinates", [])
                if len(coords) >= 2:
                    return float(coords[0]), float(coords[1])
            except (json.JSONDecodeError, TypeError):
                pass
        elif hasattr(geo_raw, '__len__') and len(geo_raw) >= 2:
            return float(geo_raw[0]), float(geo_raw[1])
    if hasattr(net, "bus_geodata") and not net.bus_geodata.empty and idx in net.bus_geodata.index:
        row = net.bus_geodata.loc[idx]
        return float(row["x"]), float(row["y"])
    return None, None


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
        lon, lat = parse_bus_coords(net, pp_i)
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
