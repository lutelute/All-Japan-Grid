"""docs/reports/ の既存UCレポートを uc_runs 索引へ一括登録する。

正本はレポートJSON（このスクリプトは読み取りのみ）。再実行可能
（report_path キーの upsert なので重複しない）。

使い方:
    python scripts/db/backfill_uc_runs.py            # data/grid.db へ
    python scripts/db/backfill_uc_runs.py --db path/to.db --dry-run
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(os.path.join(os.path.dirname(__file__), "..", ".."))

from src.uc.run_recorder import DEFAULT_DB, record_run  # noqa: E402

# ファイル名プレフィクス → kind（具体的なものを先に照合する）
_KIND_PATTERNS = [
    ("uc_pf_national_", "pf_national"),
    ("uc_pf_link_", "pf_link"),
    ("uc_benchmark_", "benchmark"),
    ("uc_annual_", "annual"),
]


def _extract(kind: str, rep: dict) -> dict:
    """レポート構造（kind別）から UCRun 列を取り出す。"""
    meta = rep.get("meta", {})
    fields = {"git_head": meta.get("git_head")}
    if kind == "benchmark":
        dev = (rep.get("dispatch", {})
               .get("share_deviation_vs_reference") or {})
        scen = meta.get("scenario", "")
        fields.update(
            scenario_id=(scen.split("uc_scenario=")[-1]
                         if "uc_scenario=" in scen else scen),
            scenario_sha256=meta.get("scenario_sha256"),
            demand_profile_sha=meta.get("demand_profile_sha"),
            status=rep.get("solve", {}).get("status"),
            total_cost_jpy=rep.get("solve", {}).get("total_cost_jpy"),
            solve_time_s=rep.get("solve", {}).get("solve_time_s"),
            l1_total_pp=dev.get("l1_total_pp"),
            summary_json=json.dumps(
                rep.get("dispatch", {}).get("fuel_share_pct", {}),
                ensure_ascii=False),
        )
    elif kind == "annual":
        res = rep.get("result", {})
        cost_oku = res.get("total_cost_oku")
        fields.update(
            scenario_id=meta.get("scenario"),
            status=res.get("status"),
            total_cost_jpy=cost_oku * 1e8 if cost_oku is not None else None,
            solve_time_s=res.get("cpu_time_s_sum"),
            summary_json=json.dumps(rep.get("fuel_share_pct", {}),
                                    ensure_ascii=False),
        )
    elif kind == "pf_link":
        pf = rep.get("pf", {})
        hours = pf.get("hours")
        n_fail = pf.get("n_failed_hours")
        if hours is not None and n_fail is not None:
            status = ("converged" if n_fail == 0
                      else f"{n_fail}/{len(hours)} failed")
        else:  # 旧形式（単一断面、hours配列なし）: uc_ac_converged が正
            status = ("converged"
                      if pf.get("uc_ac_converged", pf.get("all_converged"))
                      else "failed")
        fields.update(
            scenario_id=meta.get("scenario"), status=status,
            summary_json=json.dumps(
                {"region": meta.get("region"),
                 "hour": meta.get("hour"),
                 "all_hours": meta.get("all_hours", False)},
                ensure_ascii=False),
        )
    elif kind == "pf_national":
        islands = rep.get("islands", {})
        ok = all(i.get("converged") for i in islands.values()) and islands
        fields.update(
            scenario_id=meta.get("scenario"),
            status="converged" if ok else "failed",
            summary_json=json.dumps(
                {iid: {"mode": i.get("mode"),
                       "converged": i.get("converged"),
                       "n_buses": i.get("n_buses")}
                 for iid, i in islands.items()},
                ensure_ascii=False),
        )
    return {k: v for k, v in fields.items() if v is not None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    n_ok = n_skip = 0
    for path in sorted(glob.glob("docs/reports/uc_*.json")):
        base = os.path.basename(path)
        kind = next((k for pre, k in _KIND_PATTERNS
                     if base.startswith(pre)), None)
        if kind is None:
            continue
        try:
            with open(path) as f:
                rep = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  skip {base}: {exc}")
            n_skip += 1
            continue
        run_date = rep.get("meta", {}).get("date") or "unknown"
        fields = _extract(kind, rep)
        if args.dry_run:
            print(f"  [dry] {kind:12s} {run_date} {base} "
                  f"status={fields.get('status')}")
            n_ok += 1
            continue
        if record_run(path, kind=kind, run_date=run_date,
                      db_path=args.db, **fields):
            n_ok += 1
        else:
            n_skip += 1
    print(f"backfill: {n_ok} recorded, {n_skip} skipped -> {args.db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
