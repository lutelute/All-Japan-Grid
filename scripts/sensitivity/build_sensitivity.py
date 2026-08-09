#!/usr/bin/env python3
"""感度行列（PTDF / LODF）を出荷可能な形で構築する。

PTDF は「バス注入の変化が各枝の潮流をどれだけ動かすか」の線形感度で、
一度作れば潮流は行列ベクトル積 1 回で得られる。LODF は「ある枝の停止が他の枝の
潮流をどれだけ動かすか」で、N-1 の一括評価に使う。

PTDF は**連結かつ単一 slack** の網でしか定義できない。本モデルは島ごとに数百の成分へ
断片化しているため、到達範囲診断（`pf_frontier_*.md`）で「需要の約 90% を保持する」と
確認した**最大連結成分**を対象にする。潮流本体と同一の `build_island_net` +
無効電力補償を通すので、ここで作る行列は実際に解いている系統そのものに対応する。

**出荷方針**: 行列本体は密で巨大（west の LODF だけで約 310MB）なため git には入れず、
本スクリプトで再生成する。代わりに**索引表（バス・枝の対応と容量・橋フラグ）と
sha256 指紋**を同梱し、再生成したものが同じであることを検証できるようにする。

usage: python3 scripts/sensitivity/build_sensitivity.py [--islands hokkaido ...]
出力:
  dist/sensitivity/{island}_sensitivity.npz   PTDF / LODF 本体（git 管理外・再生成）
  dist/sensitivity/{island}_bus.csv           行列の列 → バスの対応
  dist/sensitivity/{island}_branch.csv        行列の行 → 枝の対応（容量・橋フラグ込み）
  dist/sensitivity/meta.json                  版・統計・指紋
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
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
from pandapower.pypower.idx_brch import BR_X, F_BUS, T_BUS
from pandapower.pypower.idx_bus import BASE_KV
from pandapower.pypower.makeLODF import makeLODF
from pandapower.pypower.makePTDF import makePTDF

from scripts.run_full_powerflow_from_db import (
    GEN_ATTACH_DEFAULT, ISLAND_FREQ, add_per_component_slacks, allocate_loads,
    attach_generators,
    balance_by_zone, build_island_net, load_demand_config,
)

OUT = ROOT / "dist" / "sensitivity"
BUILT = ROOT / "docs" / "data" / "built" / "all.json"

VERSION = "1.0.1"
CHANGELOG = {
    "1.0.0": "初出荷。最大連結成分の PTDF/LODF・索引表(容量/橋フラグ込み)・"
             "sha256指紋。潮流本体と同一の build_island_net + 無効電力補償を通す。"
             "橋の判定は LODF の分母(自己感度 PTDF[k,f]-PTDF[k,t] が 1)で行う"
             "— makeLODF は inf を返さないため isfinite では検出できない。",
    "1.0.1": "介入#24 の既定ON化(2026-08-09・発電機の接続規則 nearest→cap)に追随。"
             "**行列の物理的内容は変わっていない** — slack は『各成分で最大発電機を"
             "持つ母線』なので接続規則を変えると参照バスが動き、PTDF は参照依存の"
             "ぶんだけずれる。east のみ該当(slack_col 4275→5179)で hokkaido/west/"
             "okinawa は sha256 まで完全一致(west は861機46GW繋ぎ替わったが最大機の"
             "母線が動かず不変)。実測: PTDF の差は行ごとに定数(行内 std 3.7e-12)="
             "参照の付け替えのみ、LODF は橋(分母≈0・2,287枝で新旧一致)を除いた"
             "2,671万要素で最大差 2.2e-11=数値誤差。索引表(bus/branch csv)は不変。",
}


def main_component_net(island: str, nodes, edges, cfg, pref_gwh):
    """潮流本体と同じ手順で島を組み、最大連結成分に単一 slack を置いて返す。"""
    net, bus_of, _ = build_island_net(island, nodes, edges, ISLAND_FREQ[island], {})
    attach_generators(net, bus_of, nodes, island, attach_mode=GEN_ATTACH_DEFAULT)
    allocate_loads(net, cfg, pref_gwh=pref_gwh)
    from src.powerflow.pipeline import add_reactive_compensation
    add_reactive_compensation(net, factor=cfg.get("reactive_compensation_factor", 0.6))
    add_per_component_slacks(net)
    balance_by_zone(net, cfg)

    g = top.create_nxgraph(net, respect_switches=False)
    main = sorted(max(nx.connected_components(g), key=len))
    sub = pp.select_subnet(net, main, keep_everything_else=True)
    if len(sub.ext_grid) > 1:                 # PTDF は参照バス 1 枚を要する
        sub.ext_grid = sub.ext_grid.iloc[:1]
    elif len(sub.ext_grid) == 0:
        pp.create_ext_grid(sub, bus=int(sub.bus.index[0]), vm_pu=1.0, name="ptdf_ref")
    if len(sub.gen):
        sub.gen["slack"] = False
    return net, sub, bus_of


def branch_table(sub, ppc, ptdf, nodes, bus_of) -> tuple[list[dict], np.ndarray]:
    """ppc 枝順の索引表と、橋（LODF が定義できない枝）のフラグ。"""
    kvb = ppc["bus"][:, BASE_KV].real.astype(float)
    fb = ppc["branch"][:, F_BUS].real.astype(int)
    tb = ppc["branch"][:, T_BUS].real.astype(int)
    # 橋 = LODF の分母がゼロになる枝。自己感度がちょうど 1。
    self_sens = ptdf[np.arange(len(fb)), fb] - ptdf[np.arange(len(tb)), tb]
    bridge = np.abs(1.0 - self_sens) < 1e-9

    lk = sub._pd2ppc_lookups["branch"]
    rows = []
    for k in range(ptdf.shape[0]):
        tbl = eid = None
        for name, (s, e) in lk.items():
            if s <= k < e:
                tbl, eid = name, int(getattr(sub, name).index[k - s])
                break
        cap = float("nan")
        elem_name = ""
        if tbl == "line":
            r = sub.line.loc[eid]
            cap = float(np.sqrt(3) * sub.bus.at[int(r["from_bus"]), "vn_kv"]
                        * r["max_i_ka"] * r["parallel"])
            elem_name = str(r.get("name", ""))
        elif tbl == "trafo":
            r = sub.trafo.loc[eid]
            cap = float(r["sn_mva"] * r["parallel"])
            elem_name = str(r.get("name", ""))
        rows.append({
            "row": k, "element": tbl or "", "element_id": eid if eid is not None else "",
            "name": elem_name,
            "from_ppc_bus": int(fb[k]), "to_ppc_bus": int(tb[k]),
            "kv": round(float(max(kvb[fb[k]], kvb[tb[k]])), 3),
            "capacity_mva": round(cap, 2) if np.isfinite(cap) else "",
            "x_pu": round(float(ppc["branch"][k, BR_X].real), 6),
            "is_bridge": int(bridge[k]),
        })
    return rows, bridge


def bus_table(sub, ppc, nodes, bus_of) -> list[dict]:
    """ppc バス順の索引表。built のノード ID と座標まで辿れるようにする。"""
    bus2node = {}
    for ni, b in (bus_of.items() if isinstance(bus_of, dict) else enumerate(bus_of)):
        if b is not None and b >= 0:
            bus2node.setdefault(int(b), int(ni))
    lbl2ppc = sub._pd2ppc_lookups["bus"]
    row2lbl = {}
    for lbl in sub.bus.index:
        row2lbl.setdefault(int(lbl2ppc[int(lbl)]), int(lbl))

    kvb = ppc["bus"][:, BASE_KV].real.astype(float)
    rows = []
    for r in range(len(ppc["bus"])):
        lbl = row2lbl.get(r)
        ni = bus2node.get(lbl) if lbl is not None else None
        n = nodes[ni] if ni is not None else {}
        rows.append({
            "col": r, "pp_bus": lbl if lbl is not None else "",
            "built_node_id": n.get("id", ""),
            "kv": round(float(kvb[r]), 3),
            "lat": round(n["lat"], 6) if "lat" in n else "",
            "lon": round(n["lon"], 6) if "lon" in n else "",
        })
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(island: str, nodes, edges, cfg, pref_gwh, want_lodf: bool) -> dict:
    t0 = time.perf_counter()
    full, sub, bus_of = main_component_net(island, nodes, edges, cfg, pref_gwh)
    pp.rundcpp(sub)
    ppc = sub._ppc
    ref = int(sub._pd2ppc_lookups["bus"][int(sub.ext_grid.bus.iloc[0])])
    t_prep = time.perf_counter() - t0

    t0 = time.perf_counter()
    ptdf = makePTDF(ppc["baseMVA"], ppc["bus"], ppc["branch"], slack=ref)
    t_ptdf = time.perf_counter() - t0

    brows, bridge = branch_table(sub, ppc, ptdf, nodes, bus_of)
    urows = bus_table(sub, ppc, nodes, bus_of)

    payload = {"ptdf": ptdf.astype(np.float32),
               "base_mva": np.array([ppc["baseMVA"]]),
               "slack_col": np.array([ref])}
    res = {
        "island": island, "version": VERSION,
        "n_bus_full_island": int(len(full.bus)),
        "n_bus": int(ptdf.shape[1]), "n_branch": int(ptdf.shape[0]),
        "main_bus_share": round(ptdf.shape[1] / len(full.bus), 4),
        "slack_col": ref,
        "n_bridge": int(bridge.sum()), "bridge_share": round(float(bridge.mean()), 4),
        "sec_prepare": round(t_prep, 1), "sec_ptdf": round(t_ptdf, 2),
        "ptdf_mb": round(ptdf.nbytes / 1e6, 1),
    }
    if want_lodf:
        t0 = time.perf_counter()
        lodf = makeLODF(ppc["branch"], ptdf)
        res["sec_lodf"] = round(time.perf_counter() - t0, 2)
        res["lodf_mb"] = round(lodf.nbytes / 1e6, 1)
        payload["lodf"] = np.nan_to_num(lodf, nan=0.0, posinf=0.0,
                                        neginf=0.0).astype(np.float32)
        payload["is_bridge"] = bridge.astype(np.int8)

    OUT.mkdir(parents=True, exist_ok=True)
    npz = OUT / f"{island}_sensitivity.npz"
    np.savez_compressed(npz, **payload)
    write_csv(OUT / f"{island}_bus.csv", urows)
    write_csv(OUT / f"{island}_branch.csv", brows)
    res["file_mb"] = round(npz.stat().st_size / 1e6, 1)
    res["sha256"] = sha256(npz)
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
        print(f"[{isl:9s}] 主成分 {r['n_bus']:5,}バス({r['main_bus_share']:.1%}) "
              f"{r['n_branch']:5,}枝 橋{r['bridge_share']:.0%} | "
              f"PTDF {r['sec_ptdf']:5.2f}s {r['ptdf_mb']:6.0f}MB"
              + (f" | LODF {r.get('sec_lodf',0):5.2f}s {r.get('lodf_mb',0):6.0f}MB" if args.lodf else "")
              + f" | 保存 {r['file_mb']}MB")

    meta_path = OUT / "meta.json"
    meta = {}
    if meta_path.exists():                    # 部分再生成でも他島の記録を残す
        try:
            meta = json.load(open(meta_path))
        except Exception:
            meta = {}
    islands = {r["island"]: r for r in meta.get("islands", [])} if isinstance(meta.get("islands"), list) else {}
    for r in out:
        islands[r["island"]] = r
    json.dump({
        "generated": subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                                    text=True).stdout.strip(),
        "sensitivity_version": VERSION,
        "changelog": CHANGELOG,
        "source": "docs/data/built/all.json（潮流本体と同一の build_island_net + 無効電力補償）",
        "scope": "各島の最大連結成分（PTDF は連結・単一 slack を要するため）",
        "note": "行列本体(npz)は密で巨大なため git 管理外。本スクリプトで再生成し "
                "sha256 で同一性を確認する。索引表(bus/branch csv)は同梱。",
        "islands": [islands[k] for k in sorted(islands)],
    }, open(meta_path, "w"), ensure_ascii=False, indent=1)
    print(f"→ {meta_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
