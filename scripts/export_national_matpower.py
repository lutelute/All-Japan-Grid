"""Export the national model as MATPOWER-style bus/branch/gen tables (N4).

    PYTHONPATH=. python scripts/export_national_matpower.py [--out dist/matpower_national]

Builds the four synchronous islands (hokkaido / east / west / okinawa),
runs the standard pipeline up to a DC solve so pandapower constructs
the ppc, and dumps each island's bus / branch / gen arrays as CSV with
a provenance meta.json (HEAD, date, island stats). Generated artifact —
outputs are NOT committed; the script is the reproducible recipe.
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


def export_island(island_id, isl, out_dir):
    import pandapower as pp
    import pandas as pd

    from src.converter.pandapower_builder import PandapowerBuilder
    from src.powerflow.load_estimator import estimate_loads, load_demand_config
    from src.powerflow.transforms import (
        balance_power_by_zone,
        fix_topology,
        fix_zero_voltages,
        insert_transformers,
        select_slack_bus,
    )

    net = PandapowerBuilder().build(isl["net"]).net
    fix_zero_voltages(net)
    insert_transformers(net)
    fix_topology(net, multi_slack=True)
    select_slack_bus(net)
    cfg = load_demand_config()
    estimate_loads(net, region="national", demand_config=cfg)
    balance_power_by_zone(net, cfg)
    pp.rundcpp(net)

    ppc = net._ppc
    stems = {}
    for name, arr, cols in (("bus", ppc["bus"], BUS_COLS),
                            ("branch", ppc["branch"], BR_COLS),
                            ("gen", ppc["gen"], GEN_COLS)):
        df = pd.DataFrame(arr[:, :len(cols)].real.astype(float), columns=cols)
        path = os.path.join(out_dir, f"{island_id}_{name}.csv")
        df.to_csv(path, index=False)
        stems[name] = {"rows": len(df), "path": path}
    return {"island": island_id, "regions": isl["regions"],
            "frequency_hz": isl["frequency"],
            "n_bus": stems["bus"]["rows"], "n_branch": stems["branch"]["rows"],
            "n_gen": stems["gen"]["rows"]}


def main(argv=None) -> int:
    from src.powerflow.national import build_island_networks

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="dist/matpower_national")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)

    islands, async_links = build_island_networks()
    meta = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(
                timespec="seconds"),
            "head": subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                   capture_output=True, text=True,
                                   check=False).stdout.strip(),
            "base_mva": 100.0,
            "async_links": [str(a) for a in async_links],
            "note": ("per-island MATPOWER ppc tables (p.u. on 100 MVA); "
                     "all four islands AC-convergent as of ledger 63"),
            "islands": []}
    for island_id, isl in islands.items():
        print(f"  ... {island_id}", file=sys.stderr)
        meta["islands"].append(export_island(island_id, isl, args.out))
    with open(os.path.join(args.out, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1, ensure_ascii=False)
    for i in meta["islands"]:
        print(f"  {i['island']:9} bus {i['n_bus']:>6,} branch "
              f"{i['n_branch']:>6,} gen {i['n_gen']:>6,} ({i['frequency_hz']}Hz)")
    print(f"-> {args.out}/ (+meta.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
