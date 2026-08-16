#!/usr/bin/env python3
"""G_DB第2弾: 号機単位のG表(動的定数つき)を出荷する(2026-08-17 並列キャンペーン).

入力: generator_master.csv(OCCTO/HKS大規模297号機+FIT38万件)
出力: data/external/system_disclosure/normalized/g_table_units.csv
  gen_id, name, fuel, gen_class(sync/ibr), capacity_mw, H_s(機械ベース),
  xd2_pu, source
定数は型式別典型値(IEEJ/教科書帯)。個別実測ではないことをgen_classと
sourceで開示する。FITはIBR(H=0)として全件同梱(集約側で使う)。

実行: python3 scripts/build_g_table.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data/external/system_disclosure/normalized/generator_master.csv"
OUT = ROOT / "data/external/system_disclosure/normalized/g_table_units.csv"

# 燃料文字列(和文=OCCTO/HKS・英文=OSM/FIT区分) → (class, H_s, xd2)
FUEL_PARAMS = [
    (("原子力", "nuclear"), ("sync", 6.0, 0.25)),
    (("火力（石炭）", "石炭", "coal"), ("sync", 5.0, 0.22)),
    (("火力（ガス）", "ＬＮＧ", "lng", "gas"), ("sync", 5.5, 0.22)),
    (("火力（石油）", "石油", "oil"), ("sync", 4.5, 0.22)),
    (("地熱", "geothermal"), ("sync", 4.0, 0.22)),
    (("バイオマス", "biomass", "廃棄物", "waste"), ("sync", 4.0, 0.22)),
    (("揚水", "pumped"), ("sync", 3.5, 0.25)),
    (("水力", "hydro"), ("sync", 3.5, 0.25)),
    (("太陽光", "solar"), ("ibr", 0.0, 0.0)),
    (("風力", "wind"), ("ibr", 0.0, 0.0)),
    (("蓄電", "battery"), ("ibr", 0.0, 0.0)),
]


def classify(fuel: str, cap_mw: float):
    f = str(fuel or "")
    for keys, params in FUEL_PARAMS:
        if any(k in f for k in keys):
            return params
    if cap_mw and cap_mw < 2.0:
        return ("ibr", 0.0, 0.0)      # 型式不明の小容量=FIT様IBR
    return ("sync", 4.5, 0.25)        # 不明・中大型=同期機典型


def main() -> int:
    df = pd.read_csv(SRC, low_memory=False)
    rows = []
    for _, r in df.iterrows():
        cap = r.get("capacity_mw")
        cap = float(cap) if pd.notna(cap) else None
        cls, H, xd2 = classify(r.get("fuel"), cap or 0.0)
        rows.append({
            "gen_id": r.get("gen_id"), "name": r.get("name"),
            "fuel": r.get("fuel"), "gen_class": cls,
            "capacity_mw": cap, "H_s": H, "xd2_pu": xd2,
            "scale": r.get("scale"), "source": r.get("source"),
            "const_source": "typical(IEEJ/教科書帯)・個別実測でない",
        })
    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False)
    big = out[out.scale == "large"]
    print(f"G表: {len(out):,}行 → {OUT.relative_to(ROOT)}")
    print("large 297号機のclass:", big.gen_class.value_counts().to_dict())
    print("large fuel→class例:",
          big.groupby("fuel").gen_class.first().to_dict())
    print("FIT側: ibr", int((out.scale == 'fit')[out.gen_class == 'ibr'].sum()),
          "/ sync扱い", int((out.scale == 'fit')[out.gen_class == 'sync'].sum()),
          "(FIT中小水力・バイオマス等)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
