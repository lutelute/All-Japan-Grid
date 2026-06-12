"""UC検証 Phase A-1 — 代表日のUC解を発電実績（nas03）と地域×燃料で突合する。

docs/UC_VALIDATION_PLAN.md §2 の最初の実装。fy2025r1 の代表日
（2025-08-06、実測需要で構築済み）のUC解を、同日の各社「エリア需給実績」
（電源種別・30分値、nas03/PWS_DB）と比較する — **実日付・地域別・
燃料分解あり**の最初の検証。

使い方:
    AJGRID_NAS03_ROOT="ssh://pwslab@100.102.148.23/volume1/PWS_DB" \\
      python3 scripts/uc_validate.py --scenario fy2025r1 --date 2025-08-06 \\
      --companies hokkaido,tohoku,tepco,hokuriku,shikoku

出力: docs/reports/uc_validation_<scenario>_<date>.json + uc_runs(kind=validation)

比較の語彙（UC→実績、開示付き）:
- nuclear/lng/coal/hydro/geothermal/biomass/pumped_hydro/battery は直接対応
- UC oil ↔ 実績 火力(石油)+火力(その他)（区分差は開示）
- UC solar/wind（シナリオ参照値の地域配分）↔ 実績 太陽光/風力発電実績
  （抑制量は別記）
- 実績「水力」は一般水力（揚水は別列）= UC hydro と整合
"""

import argparse
import datetime as _dt
import json
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from src.dataspace import DataSpace  # noqa: E402
from src.dataspace.connectors.nas03 import COMPANY_TO_REGION  # noqa: E402
from src.uc.pf_injection import uc_snapshot  # noqa: E402
from src.uc.scenario import build_national_scenario  # noqa: E402
from src.uc.solver import solve_uc  # noqa: E402

# UC燃料 → 実績側キー（集計対応。値はリスト=実績側の合算）
UC_TO_MEASURED = {
    "nuclear": ["nuclear"],
    "lng": ["lng"],
    "coal": ["coal"],
    "oil": ["oil", "thermal_other"],   # 区分差: 実績「火力(その他)」を石油側へ
    "hydro": ["hydro"],
    "geothermal": ["geothermal"],
    "biomass": ["biomass"],
    "solar": ["solar"],
    "wind": ["wind"],
    "pumped_hydro": ["pumped_hydro"],
    "battery": ["battery"],
}


def _git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return "unknown"


def uc_region_fuel_24h(scn, uc, region) -> dict:
    """UC解の地域×燃料×24h MW（thermal+storageはschedules、RE/RoRはシナリオ参照）。"""
    out = {}
    for t in range(24):
        snap = uc_snapshot(uc, scn.generators, t, region=region)
        for fuel, mw in snap.items():
            out.setdefault(fuel, [0.0] * 24)[t] += mw
    # UCは純需要で解く — solar/wind/RoR水力は需要から控除済みなので
    # シナリオ参照系列を「UC側の供給」として復元する
    if region in scn.solar_gen_r:
        out["solar"] = [float(v) for v in scn.solar_gen_r[region]]
    if region in scn.wind_gen_r:
        out["wind"] = [float(v) for v in scn.wind_gen_r[region]]
    if scn.hydro_ror_gen_r and region in scn.hydro_ror_gen_r:
        ror = scn.hydro_ror_gen_r[region]
        base = out.get("hydro", [0.0] * 24)
        out["hydro"] = [float(b) + float(r) for b, r in zip(base, ror)]
    return out


def measured_region_fuel_24h(rows, date_str) -> dict:
    """実績30分値（MW平均）→ 1時間平均×24hの燃料別系列。"""
    by_fuel: dict = {}
    cnt: dict = {}
    for rec in rows:
        # dt例: "2025/8/6 0:30" / "2025/08/06 00:30"
        try:
            hh = int(rec["dt"].split()[1].split(":")[0])
        except (IndexError, ValueError):
            continue
        for fuel, v in rec.items():
            if fuel == "dt" or not isinstance(v, (int, float)):
                continue
            by_fuel.setdefault(fuel, [0.0] * 24)[hh] += v
            cnt.setdefault(fuel, [0] * 24)[hh] += 1
    for fuel, series in by_fuel.items():
        c = cnt[fuel]
        by_fuel[fuel] = [s / c[h] if c[h] else 0.0
                         for h, s in enumerate(series)]
    return by_fuel


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scenario", default="fy2025r1")
    ap.add_argument("--date", default="2025-08-06",
                    help="検証日（シナリオの代表日と一致させる）")
    ap.add_argument("--companies",
                    default="hokkaido,tohoku,tepco,hokuriku,shikoku",
                    help="新形式在庫のある会社（カンマ区切り）")
    ap.add_argument("--force-fetch", action="store_true",
                    help="DataSpaceキャッシュを無視して実績を再取得")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    companies = [c.strip() for c in args.companies.split(",") if c.strip()]
    month = args.date.replace("-", "")[:6]

    # ── 1. UC ──
    print(f"UC求解中... ({args.scenario})")
    scn = build_national_scenario(scenario=args.scenario)
    uc = solve_uc(scn.to_uc_parameters())
    print(f"  {uc.status}")
    if not uc.is_optimal:
        return 1

    # ── 2. 実績取得（必要月×社のみ、DataSpace経由=キャッシュ+provenance） ──
    ds = DataSpace()
    report_regions = {}
    l1_rows = []
    for company in companies:
        region = COMPANY_TO_REGION[company]
        print(f"実績取得: {company} ({region}) {month} ...")
        meas_raw = ds.fetch("nas03_generation_records",
                            {"company": company, "month": month,
                             "date": args.date},
                            force=args.force_fetch)
        meas = measured_region_fuel_24h(meas_raw["rows"], args.date)
        ucr = uc_region_fuel_24h(scn, uc, region)

        fuels = sorted(set(UC_TO_MEASURED) & (set(ucr) | {"solar", "wind"}))
        per_fuel = {}
        for fuel in UC_TO_MEASURED:
            uc_mwh = float(np.sum(ucr.get(fuel, [])))
            m_mwh = float(sum(np.sum(meas.get(k, []))
                              for k in UC_TO_MEASURED[fuel]))
            if uc_mwh < 1 and m_mwh < 1:
                continue
            # 形状相関（両方に24h系列があり分散が0でない場合）
            corr = None
            us = np.array(ucr.get(fuel, [0.0] * 24))
            ms = np.array([sum(meas.get(k, [0.0] * 24)[h]
                               for k in UC_TO_MEASURED[fuel])
                           for h in range(24)])
            if us.std() > 1e-6 and ms.std() > 1e-6:
                corr = round(float(np.corrcoef(us, ms)[0, 1]), 3)
            per_fuel[fuel] = {
                "uc_mwh": round(uc_mwh, 1),
                "measured_mwh": round(m_mwh, 1),
                "diff_mwh": round(uc_mwh - m_mwh, 1),
                "shape_corr": corr,
            }
        uc_tot = sum(v["uc_mwh"] for v in per_fuel.values())
        m_tot = sum(v["measured_mwh"] for v in per_fuel.values())
        l1_pp = (sum(abs(v["uc_mwh"] / uc_tot - v["measured_mwh"] / m_tot)
                     for v in per_fuel.values()) * 100
                 if uc_tot > 0 and m_tot > 0 else None)
        report_regions[region] = {
            "company": company,
            "demand_measured_mwh": round(
                float(np.sum(meas.get("demand", []))), 1),
            "per_fuel": per_fuel,
            "share_l1_pp": round(l1_pp, 2) if l1_pp is not None else None,
            "curtailment_mwh": {
                "solar": round(float(np.sum(meas.get("solar_curtailed", []))), 1),
                "wind": round(float(np.sum(meas.get("wind_curtailed", []))), 1),
            },
        }
        l1_rows.append((region, l1_pp))
        print(f"  {region}: L1 {l1_pp:.1f}pp" if l1_pp is not None
              else f"  {region}: L1 n/a")

    report = {
        "meta": {
            "date": _dt.date.today().isoformat(),
            "git_head": _git_head(),
            "scenario": args.scenario,
            "validation_date": args.date,
            "companies": companies,
            "vocabulary_notes": [
                "UC oil = 実績 火力(石油)+火力(その他)（区分差の開示）",
                "UC solar/wind はシナリオ参照値（fy2025r1はFY2023容量踏襲="
                "FY2025導入増未較正のバイアスをここで実測する）",
                "実績は30分MW平均→1h平均、UCは1h値",
            ],
        },
        "regions": report_regions,
        "summary": {
            "l1_pp_by_region": {r: round(v, 2) for r, v in l1_rows
                                if v is not None},
            "l1_pp_mean": round(
                float(np.mean([v for _, v in l1_rows if v is not None])), 2)
            if any(v is not None for _, v in l1_rows) else None,
        },
    }
    out = args.out or (f"docs/reports/uc_validation_{args.scenario}_"
                       f"{args.date}.json")
    with open(out, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"Saved: {out}")
    print(f"地域別L1: {report['summary']['l1_pp_by_region']} "
          f"(平均 {report['summary']['l1_pp_mean']}pp)")

    from src.uc.run_recorder import record_run
    record_run(out, kind="validation", run_date=report["meta"]["date"],
               git_head=report["meta"]["git_head"],
               scenario_id=args.scenario,
               status="ok",
               l1_total_pp=report["summary"]["l1_pp_mean"],
               summary_json=json.dumps(
                   report["summary"]["l1_pp_by_region"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
