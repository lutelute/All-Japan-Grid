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


# 同名異所の誤マッチ除去（2026-08-19）。
# 名前が exact 一致でも、同名の変電所が全国に複数あると別地点に解決される。
# 実測で東北 275kV に弦距離 466km、関西 154kV に 438km の「線」が現れた。
# 1 回線の亘長として物理的にありえない対応付けを電圧階級ごとに棄却する。
# 値は「その電圧階級の基幹線として現実的な上限」で、厳密な根拠のある定数ではない
# ため、棄却した本数と内訳を必ず表示する（黙って捨てない）。
SPAN_LIMIT_KM = {66: 50, 77: 50, 110: 100, 132: 100, 154: 100,
                 187: 150, 220: 150, 275: 250, 500: 400}


# 地中ケーブルは架空線より x が 1/3〜1/5 なので、架空線の標準値で比べると
# 比が 0.3 前後になる。誤マッチではなく線種違いなので分けて数える。
CABLE_RX = re.compile(r"地中|ケーブル|洞道|C\.?V")
# 幾何の矛盾チェック: 実線長 >= 弦距離 なので、線種が合っていれば比 >= 1 が原則。
# 比が 0.5 を割るのは「モデルの弦距離が実線長の 2 倍以上」を意味し、
# 幾何的に説明できない ＝ 同名異所の誤マッチとみなす（地中線は除く）。
RATIO_FLOOR = 0.5


def span_limit(kv: float) -> float:
    return SPAN_LIMIT_KM.get(int(kv), 300)


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

    d["span_limit_km"] = d.voltage_kv.map(span_limit)
    over = d[d.L_straight_km > d.span_limit_km]
    if len(over):
        print(f"⚠ 同名異所の疑いで棄却 {len(over)} 本（弦距離が電圧階級の上限超え）:")
        print(over[["utility", "voltage_kv", "line_name", "L_straight_km",
                    "match_level"]].sort_values("L_straight_km", ascending=False)
              .head(12).to_string(index=False))
        print()
    d = d[d.L_straight_km <= d.span_limit_km]

    v = d[(d.L_straight_km > 0.5) & (d.X_pct > 0)].copy()
    v["x_ratio_pre"] = v.X_pct / v.X_derived_pct
    v["is_cable"] = v.line_name.astype(str).str.contains(CABLE_RX)
    susp = v[(v.x_ratio_pre < RATIO_FLOOR) & (~v.is_cable)]
    if len(susp):
        print(f"⚠ 幾何矛盾で棄却 {len(susp)} 本（比<{RATIO_FLOOR}＝弦距離が実線長の2倍超・地中線を除く）:")
        print(susp[["utility", "voltage_kv", "line_name", "L_straight_km",
                    "x_ratio_pre", "match_level"]].sort_values("x_ratio_pre")
              .head(12).round(2).to_string(index=False))
        print()
    n_cable = int(v.is_cable.sum())
    if n_cable:
        print(f"※ 地中線 {n_cable} 本は線種が違う（架空線の標準値で比べると比が下がる）ため別掲\n")
    v = v[(v.x_ratio_pre >= RATIO_FLOOR) | (v.is_cable)].copy()
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
