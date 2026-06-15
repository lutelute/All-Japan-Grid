"""geojson再生成のA/B: 現行lines vs 再生成lines(電圧伝播+鉄塔fetch由来)で
モデル連結性を比較する。他層(substations/plants)は同一に固定し、linesのみ差し替え。

build_network_snapped(data_dir=...) でlines geojsonの違いだけを隔離する。
連結性指標(成分・実変電所成分・孤立実変電所・最大成分・カバー率)を出力。

Usage:
    PYTHONPATH=. python scripts/rebuild_ab.py --region kansai
"""
import argparse
import os
import shutil

import networkx as nx

from src.powerflow.snapped_topology import build_network_snapped

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def metrics(net):
    g = nx.Graph()
    real = [s.id for s in net.substations if "_jct_" not in s.id]
    g.add_nodes_from(s.id for s in net.substations)
    for ln in net.transmission_lines:
        g.add_edge(ln.from_substation_id, ln.to_substation_id)
    n_comp = nx.number_connected_components(g)
    comp_of = {}
    for ci, comp in enumerate(nx.connected_components(g)):
        for n in comp:
            comp_of[n] = ci
    real_comps = set(comp_of[s] for s in real if s in comp_of)
    sizes = sorted((len(c) for c in nx.connected_components(g)), reverse=True)
    largest = sizes[0] if sizes else 0
    iso_real = sum(1 for s in real if g.degree(s) == 0)
    return {"real_subs": len(real), "branches": len(net.transmission_lines),
            "total_components": n_comp, "real_sub_components": len(real_comps),
            "isolated_real_subs": iso_real, "largest_comp": largest,
            "coverage_pct": round(100.0 * largest / max(len(net.substations), 1), 1)}


def setup_rebuild_dir(region, rebuild_lines):
    """linesは再生成・他層は現行へのコピーで揃えた一時data_dirを作る。"""
    d = f"/tmp/ab_rebuild_{region}"
    os.makedirs(d, exist_ok=True)
    for layer in ("substations", "plants", "lines"):
        src = os.path.join(DATA, f"{region}_{layer}.geojson")
        dst = os.path.join(d, f"{region}_{layer}.geojson")
        if layer == "lines":
            shutil.copy(rebuild_lines, dst)
        elif os.path.exists(src):
            shutil.copy(src, dst)
        # supplement も現行を踏襲(linesのsupplementは現行のまま=公平)
        ssrc = os.path.join(DATA, f"{region}_{layer}_supplement.geojson")
        if os.path.exists(ssrc):
            shutil.copy(ssrc, os.path.join(d, f"{region}_{layer}_supplement.geojson"))
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", required=True)
    ap.add_argument("--rebuild", default=None,
                    help="再生成lines geojson(既定 data/rebuild/{region}_lines.geojson)")
    args = ap.parse_args()
    region = args.region
    rebuild_lines = args.rebuild or os.path.join(DATA, "rebuild", f"{region}_lines.geojson")
    if not os.path.exists(rebuild_lines):
        raise SystemExit(f"再生成lines無し: {rebuild_lines}")

    print(f"=== {region} A/B: 現行lines vs 再生成lines ===")
    print("[A] 現行(data/)を構築中...")
    net_a = build_network_snapped(region, db=None)
    ma = metrics(net_a)

    d = setup_rebuild_dir(region, rebuild_lines)
    print(f"[B] 再生成(data_dir={d})を構築中...")
    net_b = build_network_snapped(region, db=None, data_dir=d)
    mb = metrics(net_b)

    keys = ["real_subs", "branches", "total_components", "real_sub_components",
            "isolated_real_subs", "largest_comp", "coverage_pct"]
    print(f"\n{'指標':<22}{'A現行':>12}{'B再生成':>12}{'Δ':>10}")
    for k in keys:
        a, b = ma[k], mb[k]
        print(f"{k:<22}{a:>12}{b:>12}{b - a:>+10}")


if __name__ == "__main__":
    main()
