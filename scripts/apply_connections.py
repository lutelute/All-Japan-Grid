#!/usr/bin/env python3
"""E3: 人間が承認した接続を supplement に統合し、島削減をA/B検証する — 2026-06-14。

接続編集ツール(docs/connection_editor.html)が書き出した approved_connections_*.geojson、
または候補JSON(connection_candidates_*.json)から strength で絞った接続を、
`data/{region}_lines_supplement.geojson` に加算統合(source=manual・dedup)する。
build_network_snapped が既に supplement を取り込むので、統合すれば島が繋がる。

物理接続=真・捏造禁止: **既定は書き込まず島数のA/Bのみ**。実際に採用するには `--apply`。
採用すべきは人間がOSM地図(編集ツール)で実在確認した接続だけ。

  # 編集ツールのエクスポートを検証(書き込まない)
  PYTHONPATH=. python3 scripts/apply_connections.py --region tokyo --approved ~/Downloads/approved_connections_tokyo_2026-06-14.geojson
  # strong候補からサンプル検証(パイプライン確認)
  PYTHONPATH=. python3 scripts/apply_connections.py --region tokyo --from-candidates docs/reports/connection_candidates_tokyo.json --min-strength strong
  # 実際にsupplementへ統合(人間確認後)
  PYTHONPATH=. python3 scripts/apply_connections.py --region tokyo --approved <file> --apply
"""
import sys
import os
import json
import argparse
import tempfile
import shutil

import networkx as nx

from src.powerflow.snapped_topology import build_network_snapped

STRENGTH_ORDER = {"strong": 0, "medium": 1, "weak": 2}


def _island_count(region, data_dir=None):
    net = build_network_snapped(region, data_dir=data_dir)
    g = nx.Graph()
    g.add_nodes_from(s.id for s in net.substations)
    for ln in net.transmission_lines:
        g.add_edge(ln.from_substation_id, ln.to_substation_id)
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    return len(comps), (len(comps[0]) if comps else 0)


def _features_from_candidates(path, min_strength):
    d = json.load(open(path, encoding="utf-8"))
    thr = STRENGTH_ORDER.get(min_strength, 1)
    feats = []
    for c in d.get("candidates", []):
        if STRENGTH_ORDER.get(c.get("strength", "weak"), 2) > thr:
            continue
        kv = c.get("kv") or c.get("main_kv") or 0
        feats.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [
                [c["island_pt"][1], c["island_pt"][0]],
                [c["main_pt"][1], c["main_pt"][0]]]},
            "properties": {
                "power": "line", "voltage": (int(kv * 1000) or None),
                "name": "manual_connection", "source": "manual",
                "supplement_source": "connection_candidates",
                "island_node": c["island_node"], "candidate_main": c["candidate_main"],
                "evidence": c["evidence"], "strength": c["strength"]}})
    return feats


def _key(f):
    p = f.get("properties", {})
    return f"{p.get('island_node')}|{p.get('candidate_main')}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", default="tokyo")
    ap.add_argument("--approved", help="編集ツールのエクスポート geojson")
    ap.add_argument("--from-candidates", help="候補JSONから生成(サンプル検証用)")
    ap.add_argument("--min-strength", default="medium", choices=["strong", "medium", "weak"])
    ap.add_argument("--apply", action="store_true",
                    help="data/のsupplementに実際に書き込む(既定は書き込まずA/Bのみ)")
    a = ap.parse_args(argv)

    if a.approved:
        new_feats = json.load(open(a.approved, encoding="utf-8")).get("features", [])
    elif a.from_candidates:
        new_feats = _features_from_candidates(a.from_candidates, a.min_strength)
    else:
        print("--approved か --from-candidates が必要")
        return 2
    print(f"接続候補(採用対象): {len(new_feats)}件")
    if not new_feats:
        return 0

    data_dir = "data"
    supp = os.path.join(data_dir, f"{a.region}_lines_supplement.geojson")
    existing = {"type": "FeatureCollection", "features": []}
    if os.path.exists(supp):
        existing = json.load(open(supp, encoding="utf-8"))
    seen = {_key(f) for f in existing["features"]}
    added = [f for f in new_feats if _key(f) not in seen]
    merged = {"type": "FeatureCollection", "features": existing["features"] + added}
    print(f"supplement: 既存{len(existing['features'])} + 新規{len(added)} = {len(merged['features'])}")

    # A/B(既定・書き込まない): tmp data_dir に既存geojsonをsymlink + merged lines supplement
    nb, mb = _island_count(a.region)
    tmp = tempfile.mkdtemp(prefix="agj_ab_")
    try:
        for fn in os.listdir(data_dir):
            if (fn.startswith(a.region + "_") and fn.endswith(".geojson")
                    and "_lines_supplement" not in fn):
                os.symlink(os.path.abspath(os.path.join(data_dir, fn)),
                           os.path.join(tmp, fn))
        with open(os.path.join(tmp, f"{a.region}_lines_supplement.geojson"), "w",
                  encoding="utf-8") as fh:
            json.dump(merged, fh, ensure_ascii=False)
        na, ma = _island_count(a.region, data_dir=tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("=== A/B 島数(連結成分) ===")
    print(f"  before: {nb} (最大成分{mb})")
    print(f"  after : {na} (最大成分{ma})  Δ島={na - nb}")

    if a.apply:
        with open(supp, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, ensure_ascii=False, indent=1)
        print(f"✓ 書き込み: {supp} ({len(merged['features'])}件)")
    else:
        print("(--apply 未指定: 書き込みなし。人間がOSM地図で実在確認した接続のみ --apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
