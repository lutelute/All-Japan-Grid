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


def occto_area_rows(occto_dir: str) -> list[dict]:
    """OCCTO kohyo_02 (area demand) + kohyo_04 (IC planned flow) ->
    measured_area_stats rows. Signs keep OCCTO's forward convention."""
    import glob as _g

    import pandas as pd

    rows: list[dict] = []
    dem = []
    for p_ in sorted(_g.glob(os.path.join(occto_dir, "kohyo_02_*.csv"))):
        df = pd.read_csv(p_, skiprows=1, encoding="utf-8-sig")
        dem.append(df[["対象年月日", "エリア名", "エリア需要(MW)"]])
    if dem:
        d = pd.concat(dem)
        d["v"] = pd.to_numeric(d["エリア需要(MW)"], errors="coerce")
        win = f'{d["対象年月日"].min()}..{d["対象年月日"].max()}'
        for area, g in d.groupby("エリア名"):
            v = g["v"].dropna()
            if len(v) < 100:
                continue
            rows.append({"area": str(area), "metric": "demand_mw",
                         "q50_mw": float(v.median()),
                         "p95_mw": float(v.quantile(0.95)), "window": win})
    ics = []
    for p_ in sorted(_g.glob(os.path.join(occto_dir, "kohyo_04_*.csv"))):
        df = pd.read_csv(p_, skiprows=1, encoding="utf-8-sig")
        ics.append(df[["対象年月日", "連系線名", "順方向計画潮流(MW)"]])
    if ics:
        d = pd.concat(ics)
        d["v"] = pd.to_numeric(d["順方向計画潮流(MW)"], errors="coerce")
        win = f'{d["対象年月日"].min()}..{d["対象年月日"].max()}'
        for name, g in d.groupby("連系線名"):
            v = g["v"].dropna()
            if len(v) < 100:
                continue
            rows.append({"area": str(name), "metric": "ic_flow_mw",
                         "q50_mw": float(v.abs().median()),
                         "p95_mw": float(v.abs().quantile(0.95)),
                         "signed_q50_mw": float(v.median()), "window": win})
    return rows


_JUKYU_FUELS = {"原子力": "nuclear", "火力(LNG)": "gas", "火力(石炭)": "coal",
                "火力(石油)": "oil", "火力(その他)": "thermal_other",
                "水力": "hydro", "地熱": "geothermal", "バイオマス": "biomass",
                "太陽光発電実績": "solar", "風力発電実績": "wind",
                "揚水": "pumped", "蓄電池": "battery", "連系線": "interconnect"}


def tso_jukyu_rows(jukyu_dir: str, area: str = "東京") -> list[dict]:
    """TSO エリア需給実績 (OCCTO共通様式) -> per-fuel measured_area_stats
    rows (metric=gen_by_fuel:<fuel>, q50/p95 of MW; UTF-8-sig, 2-row
    header)."""
    import glob as _g

    import pandas as pd

    frames = []
    for p_ in sorted(_g.glob(os.path.join(jukyu_dir, "eria_jukyu_*.csv"))):
        try:
            df = pd.read_csv(p_, skiprows=1, encoding="utf-8-sig")
            frames.append(df)
        except Exception:
            continue
    if not frames:
        return []
    d = pd.concat(frames)
    win = f'{d["DATE"].iloc[0]}..{d["DATE"].iloc[-1]}'
    rows = []
    for col, fuel in _JUKYU_FUELS.items():
        if col not in d.columns:
            continue
        v = pd.to_numeric(d[col], errors="coerce").dropna()
        if len(v) < 100:
            continue
        rows.append({"area": area, "metric": f"gen_by_fuel:{fuel}",
                     "q50_mw": float(v.abs().median()),
                     "p95_mw": float(v.abs().quantile(0.95)),
                     "signed_q50_mw": float(v.median()),
                     "window": win, "source": "tso_jukyu"})
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="data/grid.db")
    ap.add_argument("--region", default="tokyo")
    ap.add_argument("--csv", default="data/external/tepco/jisseki_kikan.csv")
    ap.add_argument("--csv154", default="data/external/tepco/jisseki_154kV0*.csv")
    ap.add_argument("--csv66",
                    default="data/external/tepco/jisseki_[cfgikmnsty]*.csv")
    ap.add_argument("--occto", default="data/external/occto",
                    help="dir of kohyo_02/_04 CSVs ('' to skip)")
    ap.add_argument("--tso-jukyu", default="data/external/tso_jukyu/tokyo",
                    help="dir of eria_jukyu_*.csv ('' to skip)")
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

    # OCCTO area demand + interconnector flows (M10 reconciliation layer)
    if args.occto and os.path.isdir(args.occto):
        rows2 = occto_area_rows(args.occto)
        if rows2:
            from src.db.calibration import upsert_measured_area_stats
            na = upsert_measured_area_stats(db, rows2)
            ics = sum(1 for r in rows2 if r["metric"] == "ic_flow_mw")
            print(f"occto: {na} area stats -> {args.db} "
                  f"({na - ics} demand areas + {ics} interconnectors)")

    # per-fuel supply actuals from the TSO common-format CSVs (F2)
    if args.tso_jukyu and os.path.isdir(args.tso_jukyu):
        rows3 = tso_jukyu_rows(args.tso_jukyu)
        if rows3:
            from src.db.calibration import upsert_measured_area_stats
            nf = upsert_measured_area_stats(db, rows3)
            print(f"tso_jukyu: {nf} per-fuel stats -> {args.db} "
                  f"(window {rows3[0]['window']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
