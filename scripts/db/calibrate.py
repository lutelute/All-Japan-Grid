"""Land measured-flow aggregates (q50/p95 per disclosure corridor) in the DB.

    PYTHONPATH=. python scripts/db/calibrate.py                # tokyo -> data/grid.db
    PYTHONPATH=. python scripts/db/calibrate.py --db /tmp/x.db \
        --csv .../jisseki_kikan.csv --csv154 '...154kV0*.csv' --csv66 '...'

The raw CSVs are fetched per REPRODUCIBILITY §4 into data/external/
(gitignored, not redistributable); this step derives the per-corridor
aggregates the pipeline is allowed to keep and consumes them via
``src.db.calibration``: boundary corridor weighting at solve time and
``external_tepco --flows --from-db`` no longer need the CSVs present.

Band assignment is trunk-first (200 -> 140 -> 60), identical to the
matcher, so trunk supply lines listed again in lower-class files stay
trunk truths.
"""

import argparse
import glob as _glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from src.db.calibration import (  # noqa: E402
    SOURCE_TEPCO,
    upsert_measured_bus_loads,
    upsert_measured_stats,
)
from src.db.grid_db import GridDatabase  # noqa: E402
from src.validation.external_tepco import (  # noqa: E402
    tepco_busbar_demands,
    tepco_flow_stats,
    tepco_terminal_offtakes,
)


def _window(paths) -> str | None:
    """``<first>..<last>`` timestamp across the files' 日時 column."""
    import pandas as pd

    lo = hi = None
    for p in paths:
        try:
            col = pd.read_csv(p, encoding="cp932", usecols=[0]).iloc[:, 0]
        except Exception:
            continue
        vals = col.dropna().astype(str)
        if len(vals) == 0:
            continue
        lo = min(lo, vals.iloc[0]) if lo else vals.iloc[0]
        hi = max(hi, vals.iloc[-1]) if hi else vals.iloc[-1]
    return f"{lo}..{hi}" if lo else None


def calibrate_rows(csv, csv154=None, csv66=None) -> list[dict]:
    """One row per corridor with trunk-first band floors and q50/p95."""
    rows: dict[str, dict] = {}
    for floor, pattern in ((200.0, csv), (140.0, csv154), (60.0, csv66)):
        if not pattern:
            continue
        paths = sorted(_glob.glob(pattern)) or [pattern]
        paths = [p for p in paths if os.path.exists(p)]
        if not paths:
            continue
        q50 = tepco_flow_stats(paths, q=0.5)
        p95 = tepco_flow_stats(paths, q=0.95)
        win = _window(paths)
        for key, v in p95.items():
            if key in rows:          # trunk-first: first band wins
                continue
            rows[key] = {"line_key": key, "kv_floor": floor,
                         "q50_mw": q50.get(key, v), "p95_mw": v,
                         "window": win, "source": SOURCE_TEPCO}
    return list(rows.values())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="data/grid.db")
    ap.add_argument("--region", default="tokyo")
    ap.add_argument("--csv", default="data/external/tepco/jisseki_kikan.csv")
    ap.add_argument("--csv154", default="data/external/tepco/jisseki_154kV0*.csv")
    ap.add_argument("--csv66",
                    default="data/external/tepco/jisseki_[cfgikmnsty]*.csv")
    args = ap.parse_args(argv)

    if not os.path.exists(args.csv):
        print(f"no CSV at {args.csv} — fetch it first (REPRODUCIBILITY §4)")
        return 2
    rows = calibrate_rows(args.csv, args.csv154, args.csv66)
    if not rows:
        print("no corridors parsed — nothing written")
        return 2
    db = GridDatabase(args.db)
    n = upsert_measured_stats(db, args.region, rows)
    by_floor = {}
    for r in rows:
        by_floor[r["kv_floor"]] = by_floor.get(r["kv_floor"], 0) + 1
    bands = "  ".join(f"{int(k)}kV:{v}" for k, v in sorted(by_floor.items(),
                                                           reverse=True))
    print(f"{args.region}: {n} corridors -> {args.db} "
          f"(measured_line_stats; {bands}; window {rows[0]['window']})")

    # per-substation measured demand (M3): busbar map + radial ends
    win = rows[0]["window"]
    loads = [dict(sub_key=k, method="busbar", window=win, **v)
             for k, v in tepco_busbar_demands(args.csv66).items()]
    busbar_keys = {r["sub_key"] for r in loads}
    term = tepco_terminal_offtakes(args.csv, args.csv154, args.csv66)
    loads += [dict(sub_key=k, method="terminal_line", window=win,
                   q50_mw=v["q50_mw"], p95_mw=v["p95_mw"],
                   n_cols=v["n_cols"])
              for k, v in term.items() if k not in busbar_keys]
    if loads:
        nl = upsert_measured_bus_loads(db, args.region, loads)
        tot = sum(r["q50_mw"] for r in loads)
        print(f"{args.region}: {nl} measured bus loads -> {args.db} "
              f"(busbar {len(busbar_keys)} + terminal "
              f"{nl - len(busbar_keys)}; q50 total {tot:,.0f} MW)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
