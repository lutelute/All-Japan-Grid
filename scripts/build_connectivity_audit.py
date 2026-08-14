#!/usr/bin/env python3
"""建造モデルの連結性を「目で見える」形に落とす監査。

問題意識（オーナー 2026-08）: コード上は node が edge で繋がっているので
「繋がっている」ように見えるが、物理的・幾何的に本当に繋がっているかは別。
人の目には破綻（宙に浮いた終端・孤立した変電所）が見える。**途切れ終点を赤く**
塗って、その食い違いを可視化する。

入力: docs/data/built/all.json（全国stitch済みの正典。node.main は
       周波数島ごと・越境stitch(110m)・ACタイを入れた後の最大成分=本系統）
出力（配信ディレクトリ=localhost:8099 で見える。gitignore の派生物）:
  data/external/system_disclosure/viz/audit_nodes.geojson
  data/external/system_disclosure/viz/audit_edges.geojson
  data/external/system_disclosure/viz/audit_summary.json

ノード分類（見えるべき優先度＝赤の強さ）:
  isolated_sub : 本系統外の変電所（実設備が孤立＝最も問題。濃い赤）
  orphan_tip   : deg==1 かつ 本系統外（宙に浮いた終端＝主犯候補。赤）
  fragment     : その他の本系統外ノード（小成分の一部。橙）
  main         : 本系統（最大成分）。背景として沈める
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SRC = ROOT / "docs" / "data" / "built" / "all.json"
OUT = ROOT / "data" / "external" / "system_disclosure" / "viz"


def classify(n: dict) -> str:
    if n.get("main"):
        return "main"
    if n.get("sub"):
        return "isolated_sub"
    if n.get("deg") == 1:
        return "orphan_tip"
    return "fragment"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recompute", action="store_true",
                    help="all.json の main フラグを信用せず compute_connectivity で"
                         "再計算する（正典は書かない）。フラグが古い計算（例: 島判定"
                         "バグ修正 e54186f 以前の --write）で焼かれている場合に使う")
    args = ap.parse_args()

    if not SRC.exists():
        print(f"{SRC} が無い。先に built モデルを生成する")
        return 1
    d = json.loads(SRC.read_text(encoding="utf-8"))
    nodes = d.get("nodes", [])
    edges = d.get("edges", [])
    if not nodes:
        print("all.json に nodes が無い")
        return 1

    recomputed = False
    if args.recompute:
        from src.powerflow.connectivity import compute_connectivity

        def _k5(la, lo):
            return (round(la, 5), round(lo, 5))
        cc = compute_connectivity(nodes, edges)
        mk = cc["main_keys"]
        n_flip = 0
        for n in nodes:            # メモリ上のみ。正典 all.json は書かない
            new = _k5(n["lat"], n["lon"]) in mk
            if bool(n.get("main")) != new:
                n_flip += 1
            n["main"] = new
        for e in edges:
            a, b = e.get("a"), e.get("b")
            if a and b:
                e["main"] = (tuple(a) in mk and tuple(b) in mk)
        recomputed = True
        print(f"--recompute: main フラグを再計算（{n_flip} ノードが反転・正典不変）")

    OUT.mkdir(parents=True, exist_ok=True)

    # ---- nodes ----
    nfeat = []
    cls_count: Counter = Counter()
    cls_by_region: dict = {}
    for n in nodes:
        c = classify(n)
        cls_count[c] += 1
        if c != "main":
            cls_by_region.setdefault(n.get("region"), Counter())[c] += 1
        lat, lon = n.get("lat"), n.get("lon")
        if lat is None or lon is None:
            continue
        nfeat.append({
            "type": "Feature",
            "properties": {
                "cls": c,
                "kv": n.get("kv"),
                "deg": n.get("deg"),
                "sub": bool(n.get("sub")),
                "region": n.get("region"),
                "name": n.get("name") or "",
                "id": n.get("id"),
            },
            "geometry": {"type": "Point",
                         "coordinates": [round(float(lon), 5), round(float(lat), 5)]},
        })

    # ---- edges（main と 断片 で描き分けるため main フラグを持たせる）----
    efeat = []
    for e in edges:
        path = e.get("path") or [e.get("a"), e.get("b")]
        if not path or any(p is None for p in path):
            continue
        coords = [[round(float(p[1]), 5), round(float(p[0]), 5)] for p in path]
        efeat.append({
            "type": "Feature",
            "properties": {"main": bool(e.get("main")), "kv": e.get("kv")},
            "geometry": {"type": "LineString", "coordinates": coords},
        })

    (OUT / "audit_nodes.geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "features": nfeat},
        ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    (OUT / "audit_edges.geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "features": efeat},
        ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8")

    st = d.get("stats", {})
    summary = {
        "source": "docs/data/built/all.json",
        "recomputed": recomputed,
        "note": ("main は周波数島ごと・越境stitch(110m)・ACタイ適用後の最大成分。"
                 "赤/橙は合成接続を入れてもなお本系統に載らない断片。"
                 + ("main フラグは --recompute で再計算（正典のフラグは不使用）。"
                    if recomputed else "")),
        "n_nodes": len(nodes),
        "class_counts": dict(cls_count),
        "n_components": st.get("n_components"),
        "main_size": st.get("main_size"),
        "n_island_nodes": st.get("n_island_nodes"),
        "n_stitch": st.get("n_stitch"),
        "n_tie": st.get("n_tie"),
        "islands": st.get("islands"),
        "off_main_by_region": {r: dict(c) for r, c in
                               sorted(cls_by_region.items(),
                                      key=lambda kv: -sum(kv[1].values()))},
    }
    (OUT / "audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"nodes {len(nfeat)} / edges {len(efeat)} → {OUT.relative_to(ROOT)}")
    print("分類:", dict(cls_count))
    print(f"本系統外の変電所(濃赤) {cls_count['isolated_sub']} / "
          f"孤立終点(赤) {cls_count['orphan_tip']} / "
          f"その他断片(橙) {cls_count['fragment']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
