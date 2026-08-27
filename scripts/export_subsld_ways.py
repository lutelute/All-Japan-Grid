#!/usr/bin/env python3
"""SubSLD Pages ビューア用の実線形エクスポート(オーナーFB 2026-08-27).

built の edge.path は簡約・途中切れがあり、端点補完すると中心一点への
「スターバースト」偽表示になる(実害FB)。PNG版GeoPaneと同じく**生のOSM way
実線形**を描くため、data/{region}_lines.geojson を簡約(≈20m)して地域別
compact JSON に落とす。ビューアは選択地域をオンデマンド取得して重畳する。

出力: docs/data/subsld_ways/{region}.json
  {"ways": [[kv, [[lat,lon], ...]], ...]}   kv=0 は電圧無タグ(灰で描く)
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from scripts.substation_scope import _vclasses  # noqa: E402
from src.regions import REGIONS                  # noqa: E402

try:
    from shapely.geometry import LineString
    HAVE_SHAPELY = True
except Exception:   # noqa: BLE001
    HAVE_SHAPELY = False


def simplify(coords, tol=0.0002):
    if HAVE_SHAPELY and len(coords) > 3:
        try:
            g = LineString(coords).simplify(tol)
            return list(g.coords)
        except Exception:   # noqa: BLE001
            return coords
    return coords


def main() -> int:
    out_dir = os.path.join("docs", "data", "subsld_ways")
    os.makedirs(out_dir, exist_ok=True)
    total = 0
    for r in REGIONS:
        src = json.load(open(f"data/{r}_lines.geojson"))
        ways = []
        for ft in src["features"]:
            g = ft.get("geometry") or {}
            props = ft.get("properties") or {}
            vcs = _vclasses(props.get("voltage"))
            kv = int(vcs[0]) if vcs else 0
            parts = ([g.get("coordinates")] if g.get("type") == "LineString"
                     else g.get("coordinates") or [])
            for part in parts:
                if not part or len(part) < 2:
                    continue
                cs = simplify([(c[0], c[1]) for c in part])
                ways.append([kv, [[round(y, 5), round(x, 5)]
                                  for x, y in cs]])
        dst = os.path.join(out_dir, f"{r}.json")
        json.dump({"ways": ways}, open(dst, "w"),
                  ensure_ascii=False, separators=(",", ":"))
        kb = os.path.getsize(dst) / 1024
        total += kb
        print(f"{r:<9} {len(ways):>6} ways  {kb:,.0f}KB")
    print(f"計 {total/1024:.1f}MB -> {out_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
