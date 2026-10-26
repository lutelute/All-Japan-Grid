#!/usr/bin/env python3
"""電力会社エリア単位のケース書き出し(``ajgrid zone``).

正典の島を配布ケースと同じ手順で組んで AC で解き(scripts/export_matpower_canonical.py の
build_canonical_net / try_ac / fold_until)、エリア(bus.zone)の最大連結成分を切り出して
MATPOWER ケースとして書く(src/powerflow/zone_extract.py)。

    PYTHONPATH=. python3 scripts/export_zone_case.py chubu --island west [--out dist/zone_cases]

出力: <out>/<zone>.mat + CSV + 名前サイドカー(src/converter/matpower_case.export_net を共用)
      + <zone>_boundary.csv + <zone>_meta.json
境界の枝は 1 本ずつ gen 行(<zone>_genname.csv の fuel=boundary)になっている。出力は島の AC の
潮流に固定してあるので、境界の与え方(固定・容量内の変数など)は使う側が PMIN/PMAX を差し替えて決める。
境界の潮流は正典モデルが示す値であり、実測ではない。生成物はコミットしない。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(argv=None) -> int:
    import pandas as pd

    import src.powerflow.point_demand as pdm
    from scripts.export_matpower_canonical import build_canonical_net, solve_canonical, try_ac
    from src.converter.matpower_case import export_net
    from scripts.run_full_powerflow_from_db import ISLAND_FREQ
    from src.model.site_transformers import OBSERVED_PATH
    from src.powerflow.zone_extract import branch_rate_mva, extract_zone

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zone", help="bus.zone の値(chubu, kansai, ...)")
    ap.add_argument("--island", required=True, choices=sorted(ISLAND_FREQ),
                    help="エリアを含む同期島(中部は west と east にまたがる)")
    ap.add_argument("--out", default="dist/zone_cases")
    ap.add_argument("--no-validate", action="store_true")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)

    t0 = time.monotonic()
    built = json.load(open("docs/data/built/all.json", encoding="utf-8"))
    freq = ISLAND_FREQ[args.island]
    # 地点需要の CSV(data/external)は git の外。無ければ CI と同じく使わずに組む
    point_demand = pdm.CSV.exists()
    print(f"... build {args.island} (point_demand={point_demand})", file=sys.stderr, flush=True)
    net0 = build_canonical_net(args.island, built["nodes"], built["edges"], freq,
                               point_demand=point_demand)
    net, ok, how, red, _spread = solve_canonical(net0)
    if red:
        print("    素朴NRで解けない → 降下の大きいアンテナの木から畳んだ", file=sys.stderr, flush=True)
    if not ok:
        print(f"{args.island}: AC が解けない — 境界潮流が定まらないので書き出さない", file=sys.stderr)
        return 1

    sub, bd, info = extract_zone(net, args.zone)
    sub_solved, zone_ok, zone_how = try_ac(sub)
    b = sub_solved.res_bus.index
    rec = export_net(args.zone, sub_solved, zone_ok, args.out, validate=not args.no_validate,
                     regions=[args.zone], frequency=freq)

    # .mat の RATE_A は to_mpc の仮置き(100)なので、枝の容量を名前サイドカーに足す(行は export_net と同じ並び)
    bn_path = os.path.join(args.out, f"{args.zone}_branchname.csv")
    bn = pd.read_csv(bn_path)
    rate = [0.0] * len(bn)
    for kind in ("line", "trafo"):
        lo, _hi = sub_solved._pd2ppc_lookups["branch"].get(kind, (0, 0))
        live = sub_solved[kind].index[sub_solved[kind]["in_service"]]
        for k, i in enumerate(live):
            rate[lo + k] = branch_rate_mva(sub_solved, kind, i)
    bn["rate_mva"] = rate
    bn.to_csv(bn_path, index=False)

    gn = pd.read_csv(os.path.join(args.out, f"{args.zone}_genname.csv"))
    gn = gn[gn["fuel"] == "boundary"][["name", "row", "GEN_BUS"]].rename(
        columns={"row": "gen_row", "GEN_BUS": "BUS_I"})
    bd = bd.merge(gn, on="name", how="left", validate="one_to_one")
    bd.to_csv(os.path.join(args.out, f"{args.zone}_boundary.csv"), index=False)

    meta = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "head": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                               text=True, check=False).stdout.strip(),
        "island": args.island, "point_demand": point_demand,
        # 無いと変圧器の容量が変わり境界潮流もずれる(#97)
        "observed_pairs": os.path.exists(OBSERVED_PATH),
        "island_ac": {"converged": ok, "solve": how,
                      "folded_buses": (red or {}).get("n_removed", 0)},
        **info,
        "zone_ac": {"converged": zone_ok, "solve": zone_how,
                    "max_dvm_pu_vs_island": float((sub_solved.res_bus.vm_pu
                                                   - net.res_bus.vm_pu[b]).abs().max()),
                    "max_dva_deg_vs_island": float((sub_solved.res_bus.va_degree
                                                    - net.res_bus.va_degree[b]).abs().max())},
        "boundary_by_neighbor_mw": bd.groupby("neighbor_zone")["p_out_mw"].sum().round(1).to_dict(),
        "case": rec,
        "build_s": round(time.monotonic() - t0, 1),
        "note": ("境界の枝は 1 本ずつ gen 行(fuel=boundary、PMIN=PMAX=島の AC の潮流の符号反転)。"
                 "boundary.csv の p_out_mw はエリアから出る向きが正。値は正典モデルが示すもので実測"
                 "ではない。境界の与え方は使う側が決める。"),
    }
    with open(os.path.join(args.out, f"{args.zone}_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1, ensure_ascii=False)
    print(f"{args.zone}: bus={info['n_bus']} boundary={info['n_boundary']} "
          f"net_out={info['boundary_net_out_mw']}MW zone_ac={zone_ok}({zone_how}) "
          f"-> {args.out}/{args.zone}.*")
    return 0 if zone_ok else 1


if __name__ == "__main__":
    sys.exit(main())
