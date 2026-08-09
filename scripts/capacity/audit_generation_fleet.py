#!/usr/bin/env python3
"""潮流モデルの発電フリートが、どれだけ実データに基づいているかを監査する。

較正の結果、過負荷の原因は需要でも容量でもなく**潮流を作る側**に絞られた
（`docs/reports/demand_validation_*.md`）。そこで発電フリートを調べたところ、
容量の半分近くが既定値による合成だと分かった。

三つの層に分けて数える:
  1. **実容量** — `capacity_mw` に正の値が入っている
  2. **合成容量** — 値が無いか非正のため `_DEFAULT_CAP`（燃料別の既定値）で埋めた
  3. **実績との差** — NAS の電源種別実績（`data/dataspace/fuelmix_by_area.csv`）と比較

`capacity_mw = -1` は「容量不明」の番兵値。潮流モデルは `cap <= 0` を既定値に
置換するので健全に動くが、**単純に合計すると負になる**（九州の太陽光 2,374 件は
全て -1 なので合計 -2,374MW）。集計を書く側が知っておく必要がある。

usage: python3 scripts/capacity/audit_generation_fleet.py
出力: docs/reports/generation_fleet_audit_<date>.{md,json}
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

REPORTS = ROOT / "docs" / "reports"
PLANTS_GLOB = str(ROOT / "data" / "*_plants.geojson")
FUELMIX = ROOT / "data" / "dataspace" / "fuelmix_by_area.csv"

# 潮流モデル（scripts/run_full_powerflow_from_db.py）が容量欠損時に充てる既定値。
# ここを変えるときは向こうと揃えること。
DEFAULT_CAP = {"nuclear": 1000.0, "coal": 600.0, "gas": 400.0, "oil": 300.0,
               "hydro": 50.0, "solar": 10.0, "wind": 10.0, "biomass": 20.0}
CAP_FALLBACK = 30.0
AREA_ALIAS = {"tokyo": "tepco"}      # 実績側の社名との対応


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                                       text=True).stdout.strip()

    _solar_real_values: list[float] = []
    real = defaultdict(float); synth = defaultdict(float)
    n_real = defaultdict(int); n_synth = defaultdict(int)
    neg = defaultdict(int)
    solar_real = defaultdict(float); solar_synth = defaultdict(float)
    by_fuel_synth = defaultdict(int); by_fuel_total = defaultdict(int)

    for f in sorted(glob.glob(PLANTS_GLOB)):
        reg = Path(f).name.replace("_plants.geojson", "")
        for ft in json.load(open(f)).get("features", []):
            p = ft["properties"]
            fuel = str(p.get("fuel_type") or p.get("plant:source") or "unknown").lower()
            by_fuel_total[fuel] += 1
            try:
                cap = float(p.get("capacity_mw"))
            except (TypeError, ValueError):
                cap = None
            if cap is not None and cap < 0:
                neg[reg] += 1
            if cap is None or cap <= 0:
                v = DEFAULT_CAP.get(fuel, CAP_FALLBACK)
                synth[reg] += v; n_synth[reg] += 1; by_fuel_synth[fuel] += 1
                if "solar" in fuel:
                    solar_synth[reg] += v
            else:
                real[reg] += cap; n_real[reg] += 1
                if "solar" in fuel:
                    solar_real[reg] += cap
                    _solar_real_values.append(cap)

    # 実績（NAS 由来の集約）との比較
    actual_solar = {}
    if FUELMIX.exists():
        for r in csv.DictReader(open(FUELMIX)):
            if r["fuel"] == "solar":
                actual_solar[r["area"]] = float(r["max_mwh"])

    # 既定値の妥当性: 実容量が付いた太陽光の分布と比べる
    solar_vals = sorted(v for v in _solar_real_values if v > 0)
    solar_med = solar_vals[len(solar_vals) // 2] if solar_vals else None
    regions = sorted(set(real) | set(synth))
    rows = []
    for reg in regions:
        r, s = real[reg], synth[reg]
        area = AREA_ALIAS.get(reg, reg)
        act = actual_solar.get(area)
        mdl_solar = solar_real[reg] + solar_synth[reg]
        rows.append({
            "region": reg, "real_mw": round(r, 1), "synth_mw": round(s, 1),
            "synth_share": round(s / (r + s), 4) if (r + s) else None,
            "n_real": n_real[reg], "n_synth": n_synth[reg],
            "n_negative_sentinel": neg[reg],
            "model_solar_mw": round(mdl_solar, 1),
            "model_solar_real_mw": round(solar_real[reg], 1),
            "actual_solar_peak_mw": round(act, 1) if act else None,
            "model_over_actual_solar": round(mdl_solar / act, 4) if act else None,
        })

    TR = sum(real.values()); TS = sum(synth.values())
    payload = {
        "date": date, "default_cap": DEFAULT_CAP, "cap_fallback": CAP_FALLBACK,
        "total_real_mw": round(TR, 1), "total_synth_mw": round(TS, 1),
        "synth_share": round(TS / (TR + TS), 4),
        "n_plants": sum(n_real.values()) + sum(n_synth.values()),
        "n_negative_sentinel": sum(neg.values()),
        "regions": rows,
        "synth_by_fuel": {k: {"n_synth": by_fuel_synth.get(k, 0), "n_total": v,
                              "share": round(by_fuel_synth.get(k, 0) / v, 4)}
                          for k, v in sorted(by_fuel_total.items(), key=lambda x: -x[1])},
    }
    json.dump(payload, open(REPORTS / f"generation_fleet_audit_{date}.json", "w"),
              ensure_ascii=False, indent=1)

    L = [
        f"# 発電フリートはどれだけ実データに基づいているか（{date}）",
        "",
        "較正の結果、過負荷の原因は需要でも容量でもなく**潮流を作る側**に絞られた",
        "（`demand_validation_*.md`）。そこで発電フリートを調べた。",
        "",
        "## 結論 — 容量の半分は既定値",
        "",
        f"| | 容量 | 割合 |",
        "|---|---:|---:|",
        f"| `capacity_mw` に正の値がある（実容量） | {TR:,.0f} MW | {TR/(TR+TS):.1%} |",
        f"| 欠損・非正のため既定値で埋めた（合成） | **{TS:,.0f} MW** | **{TS/(TR+TS):.1%}** |",
        f"| 合計 | {TR+TS:,.0f} MW | |",
        "",
        f"発電所 {payload['n_plants']:,} 件のうち **{sum(n_synth.values()):,} 件（"
        f"{sum(n_synth.values())/payload['n_plants']:.1%}）が既定値**。",
        f"うち `capacity_mw = -1` の番兵値が {payload['n_negative_sentinel']:,} 件ある。",
        "",
        "## エリア別",
        "",
        "| エリア | 実容量 | 合成容量 | 合成の割合 | 番兵値 | モデル太陽光 | 実績ピーク | 比 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        act = f"{r['actual_solar_peak_mw']:,.0f} MW" if r["actual_solar_peak_mw"] else "—"
        ratio = f"{r['model_over_actual_solar']:.1%}" if r["model_over_actual_solar"] else "—"
        L.append(f"| {r['region']} | {r['real_mw']:,.0f} MW | {r['synth_mw']:,.0f} MW | "
                 f"{r['synth_share']:.1%} | {r['n_negative_sentinel']:,} | "
                 f"{r['model_solar_mw']:,.0f} MW | {act} | {ratio} |")
    L += [
        "",
        "**九州と沖縄は実容量がゼロ** — 全発電所が `capacity_mw = -1` で、容量はすべて",
        "燃料別の既定値から作られている。九州の太陽光 2,374 件はいずれも既定 10MW なので",
        "23.7GW という一様な合成値になる。",
        "",
        "## 太陽光は「不足」ではなく「過剰」だった",
        "",
        "OSM 由来の実容量だけを見るとモデルの太陽光は 6,274MW で実績ピーク 56,684MW の",
        "1 割しかない。ところが**既定値を織り込むと逆転する** — 容量欠損の太陽光 1 件ごとに",
        "一律 10MW が充てられ、件数が多いぶん合計が膨らむ。",
        "",
        "| | |",
        "|---|---|",
        "| OSM の実容量のみ | 6,274 MW（実績の 11%） |",
        "| 既定値込み（潮流モデルが実際に使う値） | 180,131 MW（実績の **318%**） |",
        "",
        "エリア別では東京 610%・中部 309%・九州 260% と、**軒並み 2〜6 倍**。",
        "",
        f"原因は既定値の桁違い — 実容量が付いた太陽光 {len(solar_vals):,} 件の中央値は "
        f"**{solar_med:.2f} MW** なのに、既定値は {DEFAULT_CAP['solar']:.0f} MW で "
        f"**{DEFAULT_CAP['solar']/solar_med:.0f} 倍**ある。OSM の太陽光ノードは小規模な"
        "設備が大半で、そこに一律の大きな既定値を与えたことが水増しの正体。",
        "地点数が多い太陽光に一律の既定容量を与えたことで、",
        "**注入が「OSM に太陽光ノードが多い場所」へ過剰に集まる**構造になっている。",
        "",
        "実系統では太陽光が正午に需要の 2〜6 割（九州 57.9%・東北 54.3%・四国 53.1%）を",
        "供給する。モデルはその総量を超える太陽光を、実態とは違う分布で置いている。",
        "潮流モデルは最終的にゾーン需要へスケールするので総量は合うが、",
        "**空間配分は歪んだまま**で、これが潮流のずれの有力な原因になる。",
        "",
        "## 注意 — 容量を単純に合計してはいけない",
        "",
        "`capacity_mw = -1` は「容量不明」の番兵値。潮流モデル本体は `cap <= 0` を既定値に",
        "置換するので健全に動くが、**集計側が素直に合計すると負になる**",
        "（九州の太陽光は合計 −2,374MW）。本監査はその罠を数値で開示するためのもの。",
        "",
        "## 直し方の方向（未適用）",
        "",
        "- 番兵値 `-1` を `null` にして「値が無い」ことを型で表す。負の容量は物理的に無い",
        f"- **太陽光の既定容量 {DEFAULT_CAP['solar']:.0f}MW を見直す。** 実容量が付いた太陽光 "
        f"{len(solar_vals):,} 件の中央値は **{solar_med:.2f} MW** で、既定値はその "
        f"**{DEFAULT_CAP['solar']/solar_med:.0f} 倍**。件数の多さと相まって "
        f"約 {(17622-len(solar_vals))*(DEFAULT_CAP['solar']-solar_med)/1000:,.0f} GW を水増ししている",
        "- 太陽光は OSM の地点数に頼らず、**エリア別の実績ピークを制約として配分**する方が実態に近い",
        "  （屋根置きは地点を特定できないので、需要地に按分するのが現実的）",
        "- いずれもモデルの挙動を変えるので、人間判断＋`docs/MODEL_INTERVENTIONS.md` 記帳が必要",
        "",
        "---",
        "生成: `scripts/capacity/audit_generation_fleet.py`",
        "",
    ]
    (REPORTS / f"generation_fleet_audit_{date}.md").write_text("\n".join(L), encoding="utf-8")

    print(f"総容量 {TR+TS:,.0f} MW / うち合成 {TS:,.0f} MW ({TS/(TR+TS):.1%})")
    print(f"発電所 {payload['n_plants']:,} 件 / 既定値 {sum(n_synth.values()):,} 件 / "
          f"番兵値-1 {payload['n_negative_sentinel']:,} 件")
    for r in rows:
        if r["actual_solar_peak_mw"]:
            print(f"  {r['region']:9s} 合成 {r['synth_share']:5.1%}  "
                  f"太陽光 モデル {r['model_solar_mw']:7,.0f} vs 実績 {r['actual_solar_peak_mw']:7,.0f} MW "
                  f"({r['model_over_actual_solar']:5.1%})")
    print(f"→ docs/reports/generation_fleet_audit_{date}.md")


if __name__ == "__main__":
    main()
