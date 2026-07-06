#!/usr/bin/env python3
"""UC側の島需給恒等式ダンプ — PF島slackの「島間融通」成分を定量化する.

PF島モデル(uc_to_pf_built)は島間連系(東西FC・北本DC)を持たないため、
UCが島外融通で賄った分は PF では slack が肩代わりする。本診断器は
UC解から時刻別に

    requested(注入要求 = uc_snapshot合計)
    demand(PF負荷 = net_demand_r合計)
    gap = requested - demand  (負 = 島は輸入超過)
    島境界の連系フロー内訳

をダンプする。slack分解の恒等式(east 2026-07-07で機械精度成立):

    slack ≈ 損失 + (demand - requested) + 注入clip + 注入unmatched

使い方:
    PYTHONPATH=. .venv/bin/python scripts/uc_island_gap.py --island east

出力: docs/reports/uc_island_gap_<island>_<date>.json
"""
import argparse
import datetime as _dt
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from scripts.run_full_powerflow_from_db import ISLAND_OF  # noqa: E402
from src.uc.pf_injection import uc_snapshot  # noqa: E402
from src.uc.scenario import build_national_scenario  # noqa: E402
from src.uc.solver import solve_uc  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--island", default="east",
                    choices=["hokkaido", "east", "west", "okinawa"])
    ap.add_argument("--scenario", default="fy2023r2")
    args = ap.parse_args()

    scn = build_national_scenario(scenario=args.scenario)
    uc = solve_uc(scn.to_uc_parameters())
    print("UC:", uc.status)
    if not uc.is_optimal:
        return 1

    regions = sorted(r for r, (isl, _f) in ISLAND_OF.items()
                     if isl == args.island)
    island_regions = set(regions)

    flows = {}
    for fr in getattr(uc, "interconnection_flows", []) or []:
        ic = next((i for i in scn.interconnections
                   if i.id == fr.interconnection_id), None)
        if ic is not None:
            flows[f"{ic.from_region}->{ic.to_region}"] = fr.flow_mw

    rows = []
    for t in range(24):
        req = sum(sum(uc_snapshot(uc, scn.generators, t, region=r).values())
                  for r in regions)
        dem = sum(float(scn.net_demand_r[r][t]) for r in regions)
        net_import = 0.0
        detail = {}
        for key, fmw in flows.items():
            fr_r, to_r = key.split("->")
            if (to_r in island_regions) == (fr_r in island_regions):
                continue  # 島境界を跨がない連系
            f = float(fmw[t]) if t < len(fmw) else 0.0
            net_import += f if to_r in island_regions else -f
            detail[key] = round(f, 1)
        rows.append({"t": t, "requested_mw": round(req, 1),
                     "demand_mw": round(dem, 1),
                     "uc_gap_mw": round(req - dem, 1),
                     "net_import_mw": round(net_import, 1),
                     "boundary_flows": detail})
        print(f"t={t:2d} req={req:8,.0f} dem={dem:8,.0f} "
              f"gap={req - dem:+8,.0f} import={net_import:+8,.0f} {detail}")

    date = _dt.date.today().isoformat()
    out = {"_meta": {"island": args.island, "scenario": args.scenario,
                     "date": date, "script": "scripts/uc_island_gap.py"},
           "hours": rows}
    path = os.path.join("docs", "reports",
                        f"uc_island_gap_{args.island}_{date}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"-> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
