"""fy2023 UC を解いて 地域×燃料×24h のディスパッチをビューア用JSONに書き出す。

観測フロー可視化ツール（backbone_actual.html / actual.html）の
「UC最適 vs 実績」パネル用のデータ。

fy2023 シナリオは需要が**合成**（demand.shape_24h × regional_peak_mw）なので、
nas03 / ssh 無しで完全オフラインに解ける。したがってこの出力は
**メリットオーダー（燃料構成）の構造チェック**であって、実測需要の検証ではない。
実測需要での厳密検証は scripts/uc_validate.py（nas03 のエリア需給実績と突合）で、
成果物は docs/reports/uc_validation_*.json。ビューアは両方を分けて見せる。

uc_region_fuel_24h は uc_validate.py と同じロジックだが、あちらは import 時に
DataSpace を巻き込む（os.chdir 副作用も）ため、ここでは依存の軽い形でインライン化する。

出力: data/external/system_disclosure/viz/uc_dispatch.json
  { scenario, demand, note, step_min:60, n_steps:24,
    series: { <region_en>: { <uc_fuel>: [24個のMW] } } }
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from src.regions import REGIONS  # noqa: E402
from src.uc.pf_injection import uc_snapshot  # noqa: E402
from src.uc.scenario import build_national_scenario  # noqa: E402
from src.uc.solver import solve_uc  # noqa: E402


def uc_region_fuel_24h(scn, uc, region) -> dict:
    """UC解の 地域×燃料×24h MW。

    thermal+storage は schedules（uc_snapshot）から、変動RE/RoR水力は
    純需要で控除済みなのでシナリオ参照系列を「UC側の供給」として復元する。
    （uc_validate.py::uc_region_fuel_24h と同一ロジック）
    """
    out: dict = {}
    for t in range(24):
        snap = uc_snapshot(uc, scn.generators, t, region=region)
        for fuel, mw in snap.items():
            out.setdefault(fuel, [0.0] * 24)[t] += mw
    if region in scn.solar_gen_r:
        out["solar"] = [float(v) for v in scn.solar_gen_r[region]]
    if region in scn.wind_gen_r:
        out["wind"] = [float(v) for v in scn.wind_gen_r[region]]
    if scn.hydro_ror_gen_r and region in scn.hydro_ror_gen_r:
        ror = scn.hydro_ror_gen_r[region]
        base = out.get("hydro", [0.0] * 24)
        out["hydro"] = [float(b) + float(r) for b, r in zip(base, ror)]
    return out


def main() -> int:
    scenario = "fy2023"
    print(f"UC構築中（{scenario}・合成需要）...")
    scn = build_national_scenario(scenario=scenario)
    print("UC求解中（24h 全国MILP、HiGHS→CBC自動fallback）...")
    uc = solve_uc(scn.to_uc_parameters())
    print("  status:", uc.status)
    if not uc.is_optimal:
        print("最適解が得られなかった。中止。")
        return 1

    series: dict = {}
    for r in REGIONS:
        try:
            fr = uc_region_fuel_24h(scn, uc, r)
        except Exception as e:  # noqa: BLE001
            print(f"  {r}: skip ({e})")
            continue
        # NaN/Inf を弾く（allow_nan=False で書くため。0 埋めはしない）
        clean = {}
        for fuel, arr in fr.items():
            vals = [round(float(v), 2) for v in arr]
            if any(v != v or v in (float("inf"), float("-inf")) for v in vals):
                continue
            if sum(abs(v) for v in vals) < 1e-6:
                continue   # 全ゼロ燃料は載せない（見た目のノイズ）
            clean[fuel] = vals
        series[r] = clean

    out = {
        "scenario": scenario,
        "demand": "synthetic (shape_24h × regional_peak_mw) — 実測需要ではない",
        "note": ("メリットオーダーの構造チェック用。実測需要の厳密検証は "
                 "docs/reports/uc_validation_*.json（nas03 エリア需給実績と突合）"),
        "step_min": 60, "n_steps": 24,
        "region_key": "en (hokkaido/tohoku/tokyo/chubu/hokuriku/kansai/"
                      "chugoku/shikoku/kyushu/okinawa)",
        "fuel_key": "uc-normalized (nuclear/coal/lng/oil/hydro/pumped_hydro/"
                    "geothermal/wind/solar/biomass/battery)",
        "series": series,
    }
    dest = "data/external/system_disclosure/viz/uc_dispatch.json"
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, allow_nan=False,
                  separators=(",", ":"))
    nfuel = sum(len(v) for v in series.values())
    print(f"書き出し {len(series)}地域 × 燃料計{nfuel}系列 → {dest}")

    # B: 実測需要検証レポート（fy2025r1 夏ピーク代表日）をビューアが読める場所へ複製。
    # これで1コマンドでビューアの両入力（A: uc_dispatch, B: uc_validation）が揃う。
    import shutil
    val_src = "docs/reports/uc_validation_fy2025r1_2025-08-06.json"
    val_dst = "data/external/system_disclosure/viz/uc_validation.json"
    if os.path.exists(val_src):
        shutil.copyfile(val_src, val_dst)
        print(f"実測需要検証を複製 → {val_dst}")
    else:
        print(f"注意: {val_src} が無いのでB(実測需要検証)は空になる")
    # 中身の目視用サマリ
    for r in REGIONS:
        if r in series and series[r]:
            tot = {f: round(sum(a) / 1000, 1) for f, a in series[r].items()}
            print(f"  {r}: " + " ".join(f"{f}={v}GWh" for f, v in tot.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
