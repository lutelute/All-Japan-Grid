"""チャンク並列 uc_annual の結果JSONをマージして年間レポートを作る。

使い方:
    python scripts/uc_annual_merge.py docs/reports/uc_annual_chunk*.json \
        --label fy2023_parallel

各チャンクは fuel_energy_mwh（warmup除外済み絶対量）とコストを持つ。
日数の重複・欠落を検証してから合算する。
"""

import argparse
import datetime as _dt
import glob
import json
import os
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("chunks", nargs="+", help="チャンクJSON（glob可）")
    ap.add_argument("--label", default="merged")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    paths: list = []
    for pat in args.chunks:
        paths.extend(sorted(glob.glob(pat)))
    if not paths:
        print("チャンクJSONが見つかりません")
        return 1

    chunks = []
    for p in paths:
        with open(p) as f:
            chunks.append((p, json.load(f)))

    # ── 連続性検証: [start_day, end_day) が隙間なく覆うか ──
    spans = sorted(
        (c["meta"]["start_day"], c["meta"]["end_day"], p) for p, c in chunks
    )
    gaps = []
    expect = spans[0][0]
    for s, e, p in spans:
        if s != expect:
            gaps.append(f"day {expect} -> {s} ({os.path.basename(p)})")
        expect = e
    statuses = {c["result"]["status"] for _, c in chunks}

    fuel_energy: dict = {}
    total_cost = 0.0
    solve_times = []
    n_windows = 0
    n_retried = 0
    for _, c in chunks:
        for k, v in c.get("fuel_energy_mwh", {}).items():
            fuel_energy[k] = fuel_energy.get(k, 0.0) + float(v)
        total_cost += c["result"]["total_cost_oku"]
        solve_times.append(c["result"]["solve_time_s"])
        n_windows += c["result"]["n_windows"]
        n_retried += c["result"].get("n_retried", 0)

    total = sum(fuel_energy.values())
    share = {
        k: round(v / total * 100, 2)
        for k, v in sorted(fuel_energy.items(), key=lambda kv: -kv[1])
        if v > 0
    } if total else {}

    report = {
        "meta": {
            "date": _dt.date.today().isoformat(),
            "merged_from": [os.path.basename(p) for p, _ in chunks],
            "day_span": [spans[0][0], spans[-1][1]],
            "coverage_gaps": gaps,
            "scenario": chunks[0][1]["meta"]["scenario"],
            "window_h": chunks[0][1]["meta"]["window_h"],
            "step_h": chunks[0][1]["meta"]["step_h"],
        },
        "result": {
            "status": "Optimal" if statuses == {"Optimal"} and not gaps
                      else f"PARTIAL({sorted(statuses)}, gaps={len(gaps)})",
            "n_chunks": len(chunks),
            "n_windows": n_windows,
            "n_retried": n_retried,
            "wall_time_s_max_chunk": max(solve_times),
            "cpu_time_s_sum": round(sum(solve_times), 1),
            "total_cost_oku": round(total_cost, 1),
            "total_energy_twh": round(total / 1e6, 2),
        },
        "fuel_share_pct": share,
        "fuel_energy_mwh": {k: round(v, 1) for k, v in fuel_energy.items()},
    }
    out = args.out or (
        f"docs/reports/uc_annual_{args.label}_{report['meta']['date']}.json"
    )
    with open(out, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"Saved: {out}")
    print(f"status: {report['result']['status']}  "
          f"cost ¥{report['result']['total_cost_oku']}億/年  "
          f"{report['result']['total_energy_twh']} TWh")
    for fuel, pct in share.items():
        print(f"  {fuel:12s} {pct:6.2f}%")
    return 0 if report["result"]["status"] == "Optimal" else 1


if __name__ == "__main__":
    sys.exit(main())
