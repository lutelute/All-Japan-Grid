#!/usr/bin/env python3
"""66/77kV 層の「網として解ける準備がどこまで出来ているか」を数値で測る計器。

## なぜ要るか

66kV 層は**モデルの過半**（ノード 9,676/17,336・変電所 5,281・エッジ 66kV 7,655＋77kV 2,447）で、
RE 接続可能量の研究はこの層が無いと成立しない。捨てる対象ではない。

一方、いまこの層を「網として解く」だけの情報は無い — 2026-06-11 の 66kV プログラムが
逆推定3手法の交差検証で天井を証明し、2026-08-10 に降圧点の出典探索という別経路から
同じ天井に到達した（`stepdown_sourcing_negative_2026-08-10.md`）。

その二つを両立させる唯一の道は、**「いつか埋まる」を精神論でなく計器にすること**。
6月の再開条件（OSM都心ケーブル収載 / 他社線別開示 / 常開点情報 / TSO別実績）は
README の注記に留まっていて、データが来たかどうかを機械が判定できない。
本スクリプトはその判定を数値にする — **データが改善したら勝手に上がる**。

## 測るもの（潮流は解かない＝軽い。繰り返し回して時系列で追える）

  規模      66/77kV のノード・変電所・エッジ・需要
  降圧点    変圧器の数と、**出典で裏づく降圧点**の数（keitouzu / OSM 同名一致）
  到達性    66/77kV 需要のうち降圧点から何ホップか・**到達不能な量**
  連結性    66/77kV バスのうち島の主成分に載っている割合
  素性      電圧タグ欠落（kv=0）・66kV に載る発電の合成容量率

usage:
    python3 scripts/capacity/lv_readiness.py
出力: docs/reports/lv_readiness_<date>.{json,md}（時系列で追うための定点観測）
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import subprocess
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
REPORTS = ROOT / "docs" / "reports"
KEITOUZU = ROOT / "data" / "external" / "keitouzu"

LV_CLASSES = (66.0, 77.0)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def sourced_stepdowns(pf, nodes) -> dict:
    """**出典で裏づく降圧点**を数える。ここが増えれば層は解けるようになる。"""
    out = {"keitouzu": 0, "keitouzu_regions": {}, "osm_same_name_2km": 0,
           "osm_same_name_any": 0, "osm_pairs": []}
    # ① open-keitouzu: 同一変電所に上位(>=110kV)と 66/77kV の両方の線が接続
    sub_csv, route_csv = KEITOUZU / "substations.csv", KEITOUZU / "routes.csv"
    if sub_csv.exists() and route_csv.exists():
        subs = {r["uuid"]: r for r in csv.DictReader(open(sub_csv, encoding="utf-8"))}
        kvs = defaultdict(set)
        for r in csv.DictReader(open(route_csv, encoding="utf-8")):
            v = r.get("voltage_kv", "")
            if not v.isdigit():
                continue
            for end in ("from_substation", "to_substation"):
                if r.get(end):
                    kvs[r[end]].add(int(v))
        cand = [u for u, s in kvs.items()
                if any(k in (66, 77) for k in s) and any(k >= 110 for k in s)]
        out["keitouzu"] = len(cand)
        out["keitouzu_regions"] = dict(
            Counter(subs.get(u, {}).get("region", "?") for u in cand))
    # ② OSM の変電所同名一致（介入#22 と同じ正規化）
    byname = defaultdict(list)
    for v in nodes:
        if v.get("sub") != 1 or not v.get("name"):
            continue
        nm = pf._norm_site_name(v["name"])
        if nm:
            byname[nm].append(v)
    pairs = []
    for nm, grp in byname.items():
        lo = [g for g in grp if g["kv"] in LV_CLASSES]
        hi = [g for g in grp if g["kv"] >= 110.0]
        for a in lo:
            if not hi:
                continue
            b = min(hi, key=lambda h: pf._haversine_km(a["lat"], a["lon"],
                                                       h["lat"], h["lon"]))
            km = pf._haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
            pairs.append((nm, a["kv"], b["kv"], round(km, 2)))
    out["osm_same_name_any"] = len(pairs)
    close = [p for p in pairs if p[3] <= 2.0]
    out["osm_same_name_2km"] = len(close)
    out["osm_pairs"] = sorted(close, key=lambda p: p[3])[:12]
    return out


def island_metrics(pf, island, nodes, edges, cfg, pref_gwh) -> dict:
    net, bus_of, _ = pf.build_island_net(
        island, nodes, edges, pf.ISLAND_FREQ[island], {},
        dedup_nodes=True, site_trafos=False, deenergize_unbuilt=False)
    pf.attach_generators(net, bus_of, nodes, island,
                         attach_mode=pf.GEN_ATTACH_DEFAULT)
    pf.allocate_loads(net, cfg, pref_gwh=pref_gwh)

    kv = {int(b): round(float(net.bus.at[b, "vn_kv"]), 1) for b in net.bus.index}
    lv_bus = {b for b, v in kv.items() if v in LV_CLASSES}
    entries = {int(r["lv_bus"]) for _i, r in net.trafo.iterrows()
               if r["in_service"] and kv.get(int(r["lv_bus"])) in LV_CLASSES}

    # 同一階級の線だけのグラフで降圧点からの距離
    g = nx.Graph()
    for _i, r in net.line.iterrows():
        if not r["in_service"]:
            continue
        u, v = int(r["from_bus"]), int(r["to_bus"])
        if kv[u] == kv[v]:
            g.add_edge(u, v)
    dist: dict[int, int] = {}
    dq: deque[int] = deque()
    for b in entries:
        dist[b] = 0
        dq.append(b)
    while dq:
        x = dq.popleft()
        if x not in g:
            continue
        for y in g.neighbors(x):
            if y not in dist:
                dist[y] = dist[x] + 1
                dq.append(y)

    load_at = defaultdict(float)
    for _i, r in net.load.iterrows():
        if r["in_service"]:
            load_at[int(r["bus"])] += float(r["p_mw"])
    lv_demand = sum(p for b, p in load_at.items() if b in lv_bus)
    by_hop = defaultdict(float)
    unreachable = 0.0
    for b, p in load_at.items():
        if b not in lv_bus:
            continue
        d = dist.get(b)
        if d is None:
            unreachable += p
        else:
            by_hop[min(d, 5)] += p

    # 主成分に載っている 66kV バスの割合
    gg = nx.Graph()
    gg.add_nodes_from(net.bus.index)
    for _i, r in net.line.iterrows():
        if r["in_service"]:
            gg.add_edge(int(r["from_bus"]), int(r["to_bus"]))
    for _i, r in net.trafo.iterrows():
        if r["in_service"]:
            gg.add_edge(int(r["hv_bus"]), int(r["lv_bus"]))
    main = max(nx.connected_components(gg), key=len) if len(gg) else set()
    lv_in_main = len(lv_bus & main)

    # 66kV に載る発電の合成容量率
    lv_gen = lv_gen_synth = 0.0
    for _i, r in net.gen.iterrows():
        if kv.get(int(r["bus"])) not in LV_CLASSES:
            continue
        cap = float(r["max_p_mw"])
        lv_gen += cap
        t = r.get("type")
        d = pf._DEFAULT_CAP.get(t, pf._CAP_FALLBACK) if isinstance(t, str) else pf._CAP_FALLBACK
        if abs(cap - d) < 1e-6:
            lv_gen_synth += cap
    tot = lv_demand or 1.0
    return {
        "island": island,
        "n_lv_bus": len(lv_bus), "n_lv_in_main": lv_in_main,
        "lv_main_share": round(lv_in_main / len(lv_bus), 4) if lv_bus else 0.0,
        "n_stepdown": len(entries),
        "bus_per_stepdown": round(len(lv_bus) / len(entries), 1) if entries else None,
        "lv_demand_mw": round(lv_demand, 1),
        "share_hop0": round(by_hop.get(0, 0.0) / tot, 4),
        "share_hop_ge3": round(sum(v for k, v in by_hop.items() if k >= 3) / tot, 4),
        "unreachable_mw": round(unreachable, 1),
        "unreachable_share": round(unreachable / tot, 4),
        "lv_gen_mw": round(lv_gen, 1),
        "lv_gen_synth_share": round(lv_gen_synth / lv_gen, 4) if lv_gen else 0.0,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="*",
                    default=["hokkaido", "east", "west", "okinawa"])
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                                       text=True).stdout.strip()

    pf = _load(ROOT / "scripts" / "run_full_powerflow_from_db.py", "pf_full")
    with open(pf.BUILT, encoding="utf-8") as f:
        db = json.load(f)
    nodes, edges = db["nodes"], db["edges"]
    cfg = pf.load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(nodes)

    scale = {
        "n_node_total": len(nodes),
        "n_lv_node": sum(1 for v in nodes if v.get("kv") in LV_CLASSES),
        "n_lv_sub": sum(1 for v in nodes
                        if v.get("kv") in LV_CLASSES and v.get("sub") == 1),
        "n_node_untagged_kv": sum(1 for v in nodes if not v.get("kv")),
        "n_edge_lv": sum(1 for e in edges if e.get("kv") in LV_CLASSES),
        "n_edge_untagged_kv": sum(1 for e in edges if not e.get("kv")),
    }
    scale["lv_node_share"] = round(scale["n_lv_node"] / scale["n_node_total"], 4)
    src = sourced_stepdowns(pf, nodes)

    isl = []
    for island in args.islands:
        m = island_metrics(pf, island, nodes, edges, cfg, pref_gwh)
        isl.append(m)
        print(f"[{island:9s}] 66/77kVバス {m['n_lv_bus']:5,}（主成分 {m['lv_main_share']:5.1%}）"
              f" 降圧点 {m['n_stepdown']:4,}（1点あたり {m['bus_per_stepdown']} バス）"
              f" 需要 {m['lv_demand_mw']:8,.0f}MW"
              f" 直結 {m['share_hop0']:5.1%} / 3ホップ超 {m['share_hop_ge3']:5.1%}"
              f" / **到達不能 {m['unreachable_share']:5.1%}**"
              f" 発電合成率 {m['lv_gen_synth_share']:5.1%}", flush=True)

    out = {"date": date, "scale": scale, "sourced_stepdowns": src, "islands": isl,
           "reopen_conditions_2026_06": [
               "OSM 都心地中ケーブルの収載", "他社の線別開示の発見",
               "常開点情報", "TSO別需給実績フェッチャ（再エネ実績）"]}
    (REPORTS / f"lv_readiness_{date}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    L = [f"# 66/77kV 層の準備度 — 定点観測（{date}）", "",
         "66kV 層は**モデルの過半**であり、RE 接続可能量の研究はこの層が無いと成立しない。",
         "捨てる対象ではない。一方いま「網として解く」だけの情報は無く、その天井は",
         "2026-06-11（逆推定3手法の交差検証）と 2026-08-10（降圧点の出典探索）に",
         "**二度独立に証明**されている。", "",
         "両立させる道は「いつか埋まる」を精神論でなく計器にすること — **本レポートは",
         "定点観測であり、データが改善すれば数字が勝手に上がる**。", "",
         "## 層の規模 — 捨てるという話ではない", "",
         f"- 66/77kV ノード **{scale['n_lv_node']:,} / {scale['n_node_total']:,}"
         f"（{scale['lv_node_share']:.1%}）**・うち変電所 {scale['n_lv_sub']:,}",
         f"- 66/77kV エッジ {scale['n_edge_lv']:,}",
         f"- 電圧タグ欠落: ノード {scale['n_node_untagged_kv']:,} / "
         f"エッジ {scale['n_edge_untagged_kv']:,}（**充填余地**）", "",
         "## 出典で裏づく降圧点 — ここが増えれば層は解ける", "",
         f"- open-keitouzu: **{src['keitouzu']} 箇所**"
         f"（地域内訳 {src['keitouzu_regions']}）",
         f"- OSM 変電所同名一致: 2km 以内 **{src['osm_same_name_2km']} 組**"
         f"（距離無制限だと {src['osm_same_name_any']} 組＝大half は同名別地）", "",
         "## 島ごとの到達性", "",
         "| 島 | 66/77kVバス | 主成分 | 降圧点 | 1点あたり | 需要 | 直結 | 3ホップ超 | **到達不能** | 発電合成率 |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for m in isl:
        L.append(f"| {m['island']} | {m['n_lv_bus']:,} | {m['lv_main_share']:.1%} | "
                 f"{m['n_stepdown']:,} | {m['bus_per_stepdown']} バス | "
                 f"{m['lv_demand_mw']:,.0f} MW | {m['share_hop0']:.1%} | "
                 f"{m['share_hop_ge3']:.1%} | **{m['unreachable_share']:.1%}"
                 f"（{m['unreachable_mw']:,.0f} MW）** | {m['lv_gen_synth_share']:.1%} |")
    L += ["", "## 再開条件（2026-06-11 の 66kV プログラムより）", ""]
    for c in out["reopen_conditions_2026_06"]:
        L.append(f"- {c}")
    L += ["", "どれか一つでも入手できたら、この定点観測の数字が動く。**動いたら層を",
          "網として解き直す**。それまでは潮流の見出し結果は基幹モデル（≥154kV）で出し、",
          "66kV 層は仮 DB・接続可能量研究・回帰基準として第一級のまま維持する。", "",
          "---", "生成: `scripts/capacity/lv_readiness.py`（潮流は解かない）", ""]
    (REPORTS / f"lv_readiness_{date}.md").write_text("\n".join(L), encoding="utf-8")
    print(f"→ docs/reports/lv_readiness_{date}.md")


if __name__ == "__main__":
    main()
