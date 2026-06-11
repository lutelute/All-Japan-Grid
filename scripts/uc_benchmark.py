"""UCベンチマーク — データ品質・求解性能・ディスパッチ妥当性のKPI計測。

全国24hノーダルUC（scripts/gen_uc_regional.py と同一シナリオ）を解き、
改善前後で比較可能なKPIスナップショットを docs/reports/ にJSON出力する。

使い方:
    python scripts/uc_benchmark.py --label baseline
    python scripts/uc_benchmark.py --label after_dedup --baseline docs/reports/uc_benchmark_baseline_2026-06-11.json

KPI構成:
- data_quality: 台数・容量・重複（osm_id多重出現）・容量補完・storage表現
- solve:        status・求解時間・総コスト・gap・実効ソルバー
- dispatch:     燃料別エネルギーシェア・蓄電池等価サイクル・連系線利用率
"""

import argparse
import datetime as _dt
import hashlib
import json
import os
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from src.uc.scenario import build_national_scenario  # noqa: E402
from src.uc.solver import solve_uc  # noqa: E402


def _detect_effective_solver() -> str:
    """solver.py の _select_solver と同じ優先順で実効バックエンドを推定する。"""
    import pulp

    try:
        if hasattr(pulp, "HiGHS") and pulp.HiGHS(msg=False).available():
            return "highs(api)"
    except Exception:
        pass
    try:
        if hasattr(pulp, "HiGHS_CMD") and pulp.HiGHS_CMD().available():
            return "highs(cli)"
    except Exception:
        pass
    return "cbc"


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def _scenario_sha256(config) -> str:
    """シナリオ定義の指紋（再現性担保: どの断面で計測したか機械検証可能）。"""
    blob = json.dumps(config.raw, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def run_benchmark(reserve_margin: float, mip_gap: float,
                  scenario: str = "fy2023", duals: bool = False) -> dict:
    print(f"シナリオ構築中... ({scenario})")
    scn = build_national_scenario(scenario=scenario)
    stats = scn.load_stats

    n_thermal = sum(1 for g in scn.generators
                    if g.fuel_type not in ("battery", "pumped_hydro"))
    n_battery = sum(1 for g in scn.generators if g.fuel_type == "battery")
    batt_mw = sum(g.capacity_mw for g in scn.generators if g.fuel_type == "battery")
    batt_mwh = sum(g.storage_capacity_mwh for g in scn.generators
                   if g.fuel_type == "battery")
    print(f"  発電機: 熱電源{n_thermal}機 + 蓄電池{n_battery}台 "
          f"({batt_mw:,.0f} MW / {batt_mwh:,.0f} MWh)")
    print(f"  重複(osm_id): {stats.n_duplicates}機 "
          f"{stats.duplicate_capacity_mw:,.0f} MW")

    params = scn.to_uc_parameters(
        reserve_margin=reserve_margin, mip_gap=mip_gap, extract_duals=duals,
    )

    print("UC求解中...")
    t0 = time.monotonic()
    result = solve_uc(params)
    elapsed = time.monotonic() - t0
    print(f"  {result.status}, ¥{result.total_cost / 1e8:.2f}億/日, {elapsed:.1f}s")

    # ── ディスパッチKPI ──────────────────────────────────────
    gen_map = {g.id: g for g in scn.generators}
    fuel_energy: dict[str, float] = {}
    batt_discharge_mwh = 0.0
    batt_charge_mwh = 0.0
    for sched in result.schedules:
        g = gen_map[sched.generator_id]
        p = np.array(sched.power_output_mw)
        fuel_energy[g.fuel_type] = (
            fuel_energy.get(g.fuel_type, 0.0) + float(p.clip(min=0).sum())
        )
        if g.fuel_type == "battery":
            batt_discharge_mwh += float(p.clip(min=0).sum())
            batt_charge_mwh += float(-p.clip(max=0).sum())

    fuel_energy["solar"] = float(sum(s.sum() for s in scn.solar_gen_r.values()))
    fuel_energy["wind"] = float(sum(w.sum() for w in scn.wind_gen_r.values()))
    if scn.hydro_ror_gen_r:
        # 中小水力RoR控除分は hydro として計上（実態統計との比較整合）
        fuel_energy["hydro"] = fuel_energy.get("hydro", 0.0) + float(
            sum(h.sum() for h in scn.hydro_ror_gen_r.values())
        )
    total_mwh = sum(fuel_energy.values())
    fuel_share_pct = {
        k: round(v / total_mwh * 100, 2)
        for k, v in sorted(fuel_energy.items(), key=lambda kv: -kv[1])
        if v > 0
    }

    # ── 実績シェアとの乖離KPI（シナリオに reference_shares_pct がある場合） ──
    share_deviation = None
    ref = (scn.config.raw or {}).get("reference_shares_pct")
    if ref:
        # 統計の「水力」は揚水込み → モデル側は hydro+pumped_hydro 合算
        model = dict(fuel_share_pct)
        model["hydro"] = model.get("hydro", 0.0) + model.pop("pumped_hydro", 0.0)
        common = {k: abs(model.get(k, 0.0) - float(v)) for k, v in ref.items()}
        share_deviation = {
            "per_fuel_abs_pp": {k: round(v, 2) for k, v in common.items()},
            "l1_total_pp": round(sum(common.values()), 2),
        }

    # 連系線利用率（期間最大 |flow| / 容量）
    ic_caps = {ic.id: ic.capacity_mw for ic in scn.interconnections}
    ic_util = {}
    for icf in result.interconnection_flows:
        cap = ic_caps.get(icf.interconnection_id)
        if cap:
            peak = float(np.abs(np.array(icf.flow_mw)).max())
            ic_util[icf.interconnection_id] = round(peak / cap, 3)

    return {
        "meta": {
            "date": _dt.date.today().isoformat(),
            "git_head": _git_head(),
            "scenario": f"national_24h_nodal / uc_scenario={scn.config.name}",
            "scenario_sha256": _scenario_sha256(scn.config),
            "reserve_margin": reserve_margin,
            "mip_gap": mip_gap,
            "effective_solver": _detect_effective_solver(),
        },
        "data_quality": stats.as_dict(),
        "solve": {
            "status": result.status,
            "solve_time_s": round(elapsed, 1),
            "total_cost_jpy": round(result.total_cost),
            "total_cost_oku_per_day": round(result.total_cost / 1e8, 2),
            "gap": result.gap,
            "num_warnings": len(result.warnings),
            "n_generators": len(scn.generators),
            "n_thermal": n_thermal,
            "n_battery": n_battery,
            "battery_mw": batt_mw,
            "battery_mwh": batt_mwh,
        },
        "dispatch": {
            "total_energy_gwh_per_day": round(total_mwh / 1000, 1),
            "fuel_share_pct": fuel_share_pct,
            "battery_discharge_mwh": round(batt_discharge_mwh),
            "battery_charge_mwh": round(batt_charge_mwh),
            "battery_equivalent_cycles": (
                round(batt_discharge_mwh / batt_mwh, 3) if batt_mwh > 0 else None
            ),
            "interconnection_peak_utilisation": ic_util,
            "regional_lmp_mean": (
                {
                    r: round(float(np.mean(v)), 1)
                    for r, v in sorted(result.regional_lmp.items())
                }
                if result.regional_lmp else None
            ),
            "regional_lmp_peak": (
                {
                    r: round(float(np.max(v)), 1)
                    for r, v in sorted(result.regional_lmp.items())
                }
                if result.regional_lmp else None
            ),
            "share_deviation_vs_reference": share_deviation,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--label", default="snapshot", help="レポートのラベル")
    ap.add_argument("--scenario", default="fy2023",
                    help="UCシナリオ名 (config/uc_scenarios/) またはYAMLパス")
    ap.add_argument("--duals", action="store_true",
                    help="コミットメント固定LP再解で地域限界価格を抽出")
    ap.add_argument("--reserve-margin", type=float, default=0.05)
    ap.add_argument("--mip-gap", type=float, default=0.01)
    ap.add_argument("--out", default=None, help="出力JSONパス（省略時は docs/reports/ に自動命名）")
    ap.add_argument("--baseline", default=None,
                    help="比較対象の過去スナップショットJSON（差分を表示）")
    args = ap.parse_args()

    report = run_benchmark(args.reserve_margin, args.mip_gap,
                           scenario=args.scenario, duals=args.duals)

    out = args.out or (
        f"docs/reports/uc_benchmark_{args.label}_{report['meta']['date']}.json"
    )
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"Saved: {out}")

    print("\n── 燃料別シェア (エネルギーベース) ──")
    for fuel, pct in report["dispatch"]["fuel_share_pct"].items():
        print(f"  {fuel:12s} {pct:6.2f}%")
    dev = report["dispatch"].get("share_deviation_vs_reference")
    if dev:
        print(f"\n── 実績シェア乖離 (L1合計 {dev['l1_total_pp']}pp) ──")
        for fuel, pp in sorted(dev["per_fuel_abs_pp"].items(),
                               key=lambda kv: -kv[1]):
            print(f"  {fuel:12s} ±{pp:5.2f}pp")

    if args.baseline:
        with open(args.baseline) as f:
            base = json.load(f)
        print(f"\n── ベースライン比較 ({args.baseline}) ──")
        for section in ("data_quality", "solve"):
            for k, v in report[section].items():
                bv = base.get(section, {}).get(k)
                if isinstance(v, (int, float)) and isinstance(bv, (int, float)) and v != bv:
                    print(f"  {section}.{k}: {bv} -> {v}")

    return 0 if report["solve"]["status"] == "Optimal" else 1


if __name__ == "__main__":
    sys.exit(main())
