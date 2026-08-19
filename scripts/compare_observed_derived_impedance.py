#!/usr/bin/env python3
"""公表インピーダンス(observed)でAGJの線路パラメータ推定(derived)を答え合わせする。

docs/OBSERVED_VS_DERIVED.md の規約どおり、**第三のファイルを作る**だけで
どちらの原本も書き換えない。

比較の筋道:
  observed は 1000MVAベースの % で与えられる。基準インピーダンスは
      Z_base = kV^2 / 1000  [Ω]
  なので            X_ohm = X_pct/100 * kV^2/1000
  AGJ の derived は config/line_types.yaml の電圧階級別 x_ohm_per_km × こう長。
  こう長は持っていないので、逆に **公表値が示唆する等価こう長**
      L_implied = X_ohm / x_ohm_per_km
  を求め、モデルの端点間**直線距離**と比べる。

  比 L_implied / L_straight は、送電線が直線でない分だけ 1 より大きくなるのが自然
  （迂回係数。実系統では概ね 1.1〜1.3）。
  1 から大きく外れるなら、標準値そのものかトポロジ（端点の取り違え）を疑う。

並列回線(1L/2L)は同一区間・同一値なので、**回線サフィックスを落として重複を除く**。
インピーダンスは1回線あたりの量であり、重複計上すると分布が歪む。
"""
from __future__ import annotations

import math
import re
import os
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
NORM = Path(os.environ.get("AGJ_DISCLOSURE_NORM",
                           ROOT / "data" / "external" / "system_disclosure" / "normalized"))
OUT = Path(os.environ.get("AGJ_DISCLOSURE_OUT", NORM))
LINE_TYPES = ROOT / "config" / "line_types.yaml"
REPORT = ROOT / "docs" / "reports"

CIRCUIT_RX = re.compile(r"[0-9０-９]+\s*[LＬ]\s*$")


def haversine(a_lat, a_lon, b_lat, b_lon) -> float:
    r = 6371.0088
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = p2 - p1
    dl = math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def nearest_class(kv: float, classes: list[int]) -> int:
    return min(classes, key=lambda c: abs(c - kv))


def main() -> int:
    cw = pd.read_csv(NORM / "crosswalk_impedance_to_model.csv")
    lt = yaml.safe_load(LINE_TYPES.read_text(encoding="utf-8"))
    classes = [int(k) for k in lt if str(k).isdigit()]

    d = cw[cw.both_resolved].copy()
    # 並列回線の重複除去（1L/2L は同一区間・同一値）
    d["base_name"] = d.line_name.map(lambda s: CIRCUIT_RX.sub("", str(s)).strip())
    d = d.drop_duplicates(subset=["utility", "base_name", "from_node", "to_node"])

    d["L_straight_km"] = d.apply(
        lambda r: haversine(r.from_lat, r.from_lon, r.to_lat, r.to_lon), axis=1
    )
    d["vclass"] = d.voltage_kv.map(lambda k: nearest_class(k, classes))
    d["x_std"] = d.vclass.map(lambda c: lt[c]["x_ohm_per_km"])
    d["r_std"] = d.vclass.map(lambda c: lt[c]["r_ohm_per_km"])
    # observed の % → Ω（1000MVAベース）
    d["X_ohm_obs"] = d.X_pct / 100 * d.voltage_kv**2 / 1000
    d["R_ohm_obs"] = d.R_pct / 100 * d.voltage_kv**2 / 1000
    d["L_implied_km"] = d.X_ohm_obs / d.x_std
    d["X_derived_pct"] = 100 * (d.x_std * d.L_straight_km) * 1000 / d.voltage_kv**2

    v = d[(d.L_straight_km > 0.5) & (d.X_pct > 0)].copy()
    v["detour"] = v.L_implied_km / v.L_straight_km
    v["x_ratio"] = v.X_pct / v.X_derived_pct

    print(f"両端解決 {len(d)} 本（並列重複を除去後） / 距離>0.5km かつ X>0 の {len(v)} 本で評価\n")
    print("=== 迂回係数 L_implied / L_straight ===")
    print(v.detour.describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9]).round(3).to_string())
    print("\n=== 電圧階級別 ===")
    g = v.groupby("vclass").agg(
        n=("detour", "size"),
        detour_med=("detour", "median"),
        x_ratio_med=("x_ratio", "median"),
        L_str_med=("L_straight_km", "median"),
    ).round(3)
    print(g.to_string())
    print("\n=== 事業者別（迂回係数の中央値）===")
    print(v.groupby("utility").detour.agg(n="size", med="median").round(3).to_string())

    # R/X 比の観測 vs 標準
    v["xr_obs"] = v.X_ohm_obs / v.R_ohm_obs
    v["xr_std"] = v.x_std / v.r_std
    print("\n=== X/R 比: 公表 vs line_types.yaml 標準 ===")
    print(
        v.groupby("vclass")[["xr_obs", "xr_std"]].median().round(2).to_string()
    )

    out = OUT / "compare_observed_derived_impedance.csv"
    v.to_csv(out, index=False, encoding="utf-8")
    print(f"\n→ {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
