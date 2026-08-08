#!/usr/bin/env python3
"""感度行列（PTDF / LODF）を建造モデルから構築する。

PTDF は「バス注入の変化が各枝の潮流をどれだけ動かすか」の線形感度で、
一度作れば潮流は行列ベクトル積 1 回で得られる（反復解法が不要）。
LODF は「ある枝の停止が他の枝の潮流をどれだけ動かすか」で、N-1 の一括評価に使う。

PTDF は**連結かつ単一 slack** の網でしか定義できない。本モデルは島ごとに
数百の成分へ断片化しているため、昨日の到達範囲診断（pf_frontier）で
「需要の約 90% を保持する」と確認した**最大連結成分**を対象にする。

潮流本体と同一の build_island_net + 無効電力補償を通すので、
ここで作る行列は実際に解いている系統そのものに対応する。

usage: python3 scripts/sensitivity/build_sensitivity.py [--islands hokkaido ...]
出力: dist/sensitivity/{island}_ptdf.npz  （PTDF / LODF / バス・枝の対応表）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(ROOT)   # config/*.yaml は repo ルート相対で読まれる

import networkx as nx
import numpy as np
import pandapower as pp
import pandapower.topology as top
from pandapower.pypower.makePTDF import makePTDF
from pandapower.pypower.makeLODF import makeLODF
from pandapower.pypower.idx_brch import F_BUS, T_BUS

from scripts.run_full_powerflow_from_db import (
    ISLAND_FREQ, allocate_loads, attach_generators, build_island_net,
    load_demand_config,
)

OUT = ROOT / "dist" / "sensitivity"
BUILT = ROOT / "docs" / "data" / "built" / "all.json"


def main_component_net(island: str, nodes, edges, cfg, pref_gwh):
    """潮流本体と同じ手順で島を組み、最大連結成分だけを取り出して単一 slack を置く。"""
    freq = ISLAND_FREQ[island]
    net, bus_of, _ = build_island_net(island, nodes, edges, freq, {})
    attach_generators(net, bus_of, nodes, island)
    allocate_loads(net, cfg, pref_gwh=pref_gwh)
    from src.powerflow.pipeline import add_reactive_compensation
    add_reactive_compensation(net, factor=cfg.get("reactive_compensation_factor", 0.6))

    g = top.create_nxgraph(net, respect_switches=False)
    main = max(nx.connected_components(g), key=len)
    sub = pp.select_subnet(net, sorted(main), keep_everything_else=True)

    # slack は最大の発電機バスに 1 枚だけ（PTDF の定義に必要）
    if len(sub.ext_grid):
        sub.ext_grid = sub.ext_grid.iloc[:1]
    else:
        cand = sub.gen if len(sub.gen) else sub.sgen
        bus = int(cand.loc[cand["p_mw"].idxmax(), "bus"]) if len(cand) else int(sub.bus.index[0])
        pp.create_ext_grid(sub, bus=bus, vm_pu=1.0, name="ptdf_slack")
    if len(sub.gen):          # 単一 slack を保つため gen は PV のまま（slack にしない）
        sub.gen["slack"] = False

    # 主成分を1枚の slack で解くには需給を釣り合わせる必要がある。
    # 本体は成分ごとの合成 slack + balance_by_zone で吸収するが、ここは成分が1つなので
    # 発電を一律スケールして総需要（+予備率）に合わせ、残差だけを slack に残す。
    # これをしないと east/west は AC が発散し、精度比較そのものが成立しない。
    total_load = float(sub.load["p_mw"].sum())
    reserve = 1.0 + cfg.get("reserve_margin", 0.05)
    for tbl in ("gen", "sgen"):
        tab = getattr(sub, tbl)
        if len(tab) and tab["p_mw"].sum() > 0:
            share = tab["p_mw"].sum() / sum(
                getattr(sub, t)["p_mw"].sum() for t in ("gen", "sgen") if len(getattr(sub, t)))
            tab["p_mw"] *= (total_load * reserve * share) / tab["p_mw"].sum()
    return net, sub


def build(island: str, nodes, edges, cfg, pref_gwh, want_lodf: bool) -> dict:
    t0 = time.time()
    full, net = main_component_net(island, nodes, edges, cfg, pref_gwh)
    t_build = time.time() - t0

    t0 = time.time()
    pp.rundcpp(net)
    t_dc = time.time() - t0
    ppc = net._ppc
    nb, nbr = ppc["bus"].shape[0], ppc["branch"].shape[0]

    slack_ppc = int(net._pd2ppc_lookups["bus"][int(net.ext_grid.bus.iloc[0])])
    t0 = time.time()
    ptdf = makePTDF(ppc["baseMVA"], ppc["bus"], ppc["branch"], slack=slack_ppc)
    t_ptdf = time.time() - t0

    res = {
        "island": island,
        "n_bus": int(nb), "n_branch": int(nbr),
        "n_bus_full": int(len(full.bus)),
        "main_bus_share": round(nb / len(full.bus), 4),
        "sec_build": round(t_build, 1), "sec_dcpf": round(t_dc, 2),
        "sec_ptdf": round(t_ptdf, 1),
        "ptdf_mb": round(ptdf.nbytes / 1e6, 1),
        "slack_ppc_index": slack_ppc,
    }

    payload = {
        "ptdf": ptdf.astype(np.float32),
        "branch_f": ppc["branch"][:, F_BUS].real.astype(np.int32),
        "branch_t": ppc["branch"][:, T_BUS].real.astype(np.int32),
        "base_mva": np.array([ppc["baseMVA"]]),
        "slack": np.array([slack_ppc]),
    }
    if want_lodf:
        t0 = time.time()
        lodf = makeLODF(ppc["branch"], ptdf)
        res["sec_lodf"] = round(time.time() - t0, 1)
        res["lodf_mb"] = round(lodf.nbytes / 1e6, 1)
        payload["lodf"] = np.nan_to_num(lodf, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)

    OUT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT / f"{island}_sensitivity.npz", **payload)
    res["file_mb"] = round((OUT / f"{island}_sensitivity.npz").stat().st_size / 1e6, 1)
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="*", default=None)
    ap.add_argument("--lodf", action=argparse.BooleanOptionalAction, default=True,
                    help="LODF も作る（枝×枝の密行列。大きい島では重い）")
    args = ap.parse_args()

    d = json.load(open(BUILT))
    nodes, edges = d["nodes"], d["edges"]
    cfg = load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(nodes)

    out = []
    for isl in (args.islands or list(ISLAND_FREQ.keys())):
        r = build(isl, nodes, edges, cfg, pref_gwh, args.lodf)
        out.append(r)
        print(f"[{isl:9s}] 主成分 {r['n_bus']:5d}バス({r['main_bus_share']:.1%}) {r['n_branch']:5d}枝 | "
              f"PTDF {r['sec_ptdf']:6.1f}s {r['ptdf_mb']:7.1f}MB"
              + (f" | LODF {r.get('sec_lodf',0):6.1f}s {r.get('lodf_mb',0):7.1f}MB" if args.lodf else "")
              + f" | 保存 {r['file_mb']}MB")
    json.dump(out, open(OUT / "build_meta.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
