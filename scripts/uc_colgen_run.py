"""Run the UC-specific solver (src/uc/colgen.py) on a synthetic case: the bound by column generation, then the band MILP.

    python -m scripts.uc_colgen_run --units 800 --hours 48 --out results/.../colgen_800x48.json
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np

from src.uc.benchmark_cases import synthetic_case
from src.uc.colgen import solve_band, solve_colgen


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--units", type=int, default=800)
    ap.add_argument("--hours", type=int, default=48)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--cg-time", type=float, default=600)
    ap.add_argument("--band-time", type=float, default=300)
    ap.add_argument("--band-gap", type=float, default=1e-4)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    t0 = time.monotonic()
    cg = solve_colgen(synthetic_case(args.units, args.hours, args.seed), time_limit_s=args.cg_time, threads=args.threads,
                      keep_prices=True, log=lambda d: print(json.dumps({k: d[k] for k in ("it", "master", "best_lb", "gap", "new", "cols", "s")}), flush=True))
    t_cg = time.monotonic() - t0
    ub = cg.ubar
    floating = (ub > 1e-6) & (ub < 1 - 1e-6)
    print("bound", cg.lower_bound, "floating unit-hours", int(floating.sum()), "units", int(floating.any(1).sum()), flush=True)
    band, n_sunk = solve_band(synthetic_case(args.units, args.hours, args.seed), cg, time_limit_s=args.band_time,
                              gap=args.band_gap, threads=args.threads)
    t_all = time.monotonic() - t0
    out = {"schema_version": 1, "kind": "uc_colgen", "units": args.units, "hours": args.hours, "seed": args.seed,
           "threads": args.threads, "lower_bound": cg.lower_bound, "cg_seconds": round(t_cg, 1), "cg_iterations": cg.iterations,
           "columns": cg.columns, "floating_unit_hours": int(floating.sum()), "floating_units": int(floating.any(1).sum()),
           "sunk_unit_hours": n_sunk, "band": {"status": band.status, "cost": band.total_cost, "gap": band.gap,
                                               "verified": band.feasibility_verified, "seconds": round(t_all - t_cg, 1)},
           "upper_bound": band.total_cost, "gap_ub_lb": (band.total_cost - cg.lower_bound) / band.total_cost if band.total_cost else None,
           "seconds": round(t_all, 1), "trace": cg.trace,
           "ubar": np.round(ub, 3).tolist(), "unit_ids": cg.unit_ids}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, separators=(",", ":")) + "\n")
    print(json.dumps({k: out[k] for k in ("lower_bound", "upper_bound", "gap_ub_lb", "cg_seconds", "seconds", "floating_units")}),
          json.dumps(out["band"]), flush=True)


if __name__ == "__main__":
    main()
