#!/usr/bin/env python3
"""送電網・変電所・発電所を地図ビュー用に軽量化して書き出す。

AGJ の資産（送電線 40,077 / 変電所 6,962 / 発電所 19,138）はそのままだと
`lines_all.geojson` だけで 18.9MB あり、地図の初期表示に載せるには重い。
表示に要らないプロパティを落とし、座標を 5 桁（≒1m）に丸めて絞る。

分類は OSM タグをそのまま使う（推定を足さない）:
  線路   power=line / power=cable、location=underground ほか
  変電所 category = transmission / distribution / traction / industrial /
                    transition / generation / converter / minor_distribution / unknown
  発電所 fuel_type / capacity_mw

出力: data/external/system_disclosure/viz/{lines,substations,plants}.geojson
      （ビューアと同じ場所。OSM由来なので ODbL、出典表示のうえ再配布は可能だが、
        いまは実測潮流ビューと同居させて同一オリジンで読ませる目的で置く）
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DOCS = ROOT / "docs" / "data"
OUT = ROOT / "data" / "external" / "system_disclosure" / "viz"

REGIONS = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
           "kansai", "chugoku", "shikoku", "kyushu", "okinawa"]


def kv_of(props: dict) -> float | None:
    """OSM の voltage タグ（"275000" や "154000;66000"）を kV にする。

    複数電圧が併記された線は **最大値** を採る。表示上その線が属する階級として
    扱いたいのは高い方であり、低い方で描くと基幹系が細く消えてしまうため。
    """
    v = props.get("voltage")
    if v is None:
        return None
    vals = [int(x) for x in re.findall(r"\d+", str(v))]
    vals = [x for x in vals if x > 0]
    return max(vals) / 1000 if vals else None


def round_coords(c, nd=5):
    if isinstance(c[0], (int, float)):
        return [round(c[0], nd), round(c[1], nd)]
    return [round_coords(x, nd) for x in c]


def simplify_geom(geom: dict, tol: float):
    """線形を間引く。送電線は鉄塔間が直線なので頂点の多くは表示に効かない。

    tol は度単位（0.0002° ≒ 20m）。トポロジは保つ（preserve_topology=True）。
    間引きは**表示用の派生物にだけ**適用する。計算や照合に使う正本の幾何は触らない。
    """
    if tol <= 0:
        return geom
    try:
        from shapely.geometry import mapping, shape
        g = shape(geom).simplify(tol, preserve_topology=True)
        if g.is_empty:
            return geom
        return mapping(g)
    except Exception:  # noqa: BLE001 — 間引きに失敗したら原形のまま出す
        return geom


def centroid(geom: dict):
    g, c = geom.get("type"), geom.get("coordinates")
    if g == "Point":
        return c[:2]
    ring = c[0] if g == "Polygon" else (c[0][0] if g == "MultiPolygon" else None)
    if not ring:
        return None
    return [sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)]


def write(name: str, features: list, note: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"{name}.geojson"
    dest.write_text(json.dumps(
        {"type": "FeatureCollection", "features": features,
         "metadata": {"source": "OpenStreetMap (ODbL) via All-Japan-Grid", "note": note}},
        ensure_ascii=False, allow_nan=False, separators=(",", ":")),
        encoding="utf-8")
    print(f"{name:12s} {len(features):6d} features  {dest.stat().st_size/1e6:6.2f} MB")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-kv", type=float, default=0.0)
    ap.add_argument("--tol", type=float, default=0.0002,
                    help="線形の間引き許容誤差[度]。0.0002≒20m。0で無効")
    args = ap.parse_args()

    # --- 送電線 -------------------------------------------------------
    lines = []
    for region in REGIONS:
        path = DATA / f"{region}_lines.geojson"
        if not path.exists():
            continue
        for f in json.loads(path.read_text(encoding="utf-8"))["features"]:
            p = f["properties"]
            geom = f.get("geometry") or {}
            if geom.get("type") not in ("LineString", "MultiLineString"):
                continue
            kv = kv_of(p)
            if kv is not None and kv < args.min_kv:
                continue
            loc = p.get("location") or ""
            lines.append({
                "type": "Feature",
                "properties": {
                    "n": p.get("name") or "",
                    "kv": kv,
                    "c": 1 if (p.get("power") == "cable" or loc == "underground") else 0,
                    "r": region,
                    "op": p.get("operator") or "",
                    "ct": p.get("circuits") or "",
                },
                "geometry": simplify_geom(
                    {"type": geom["type"],
                     "coordinates": round_coords(geom["coordinates"])}, args.tol),
            })
    write("lines", lines, "power=line/cable。c=1 は地下ケーブル/地中区間")

    # --- 変電所 -------------------------------------------------------
    subs = []
    src = DOCS / "substations.geojson"
    if src.exists():
        for f in json.loads(src.read_text(encoding="utf-8"))["features"]:
            p = f["properties"]
            xy = centroid(f.get("geometry") or {})
            if not xy:
                continue
            subs.append({
                "type": "Feature",
                "properties": {
                    "n": p.get("name") or p.get("_display_name") or "",
                    "kv": p.get("voltage_kv"),
                    "cat": p.get("category") or "unknown",
                    "r": p.get("region") or "",
                    "op": p.get("operator_short") or p.get("operator") or "",
                },
                "geometry": {"type": "Point", "coordinates": round_coords(xy)},
            })
    write("substations", subs, "category は OSM の substation タグ由来（推定を足していない）")

    # --- 発電所 -------------------------------------------------------
    plants = []
    src = DOCS / "plants_all.geojson"
    if src.exists():
        for f in json.loads(src.read_text(encoding="utf-8"))["features"]:
            p = f["properties"]
            xy = centroid(f.get("geometry") or {})
            if not xy:
                continue
            # capacity_mw は欠損を **-1 という番兵** で表しており（実測3,936件）、
            # そのまま容量として扱うと sqrt(-1)=NaN になり円が描けない。
            # 0以下は「不明」として None に落とす。19,138件のうち容量が分かるのは
            # 1,280件（6.7%）しかない — 件数だけ誇らず、この差を表示側にも出す。
            mw = p.get("capacity_mw")
            if mw in ("", None) or (isinstance(mw, (int, float)) and mw <= 0):
                mw = None
            plants.append({
                "type": "Feature",
                "properties": {
                    "n": p.get("_display_name") or "",
                    "f": p.get("fuel_type") or "",
                    "mw": mw,
                    "r": p.get("_region") or "",
                },
                "geometry": {"type": "Point", "coordinates": round_coords(xy)},
            })
    n_mw = sum(1 for f in plants if f["properties"]["mw"] is not None)
    write("plants", plants,
          f"fuel_type / capacity_mw。容量が判明しているのは {n_mw}/{len(plants)} 件"
          "（-1 は原データの欠損番兵として None に落とした）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
