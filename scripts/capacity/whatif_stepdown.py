#!/usr/bin/env python3
"""欠けている降圧点を補ったら過負荷は消えるか（what-if・未適用）。

診断の到達点（`docs/reports/overload_vs_topology_2026-08-09.md` の続き）:

  east は 66/77kV バスが 4,727 個あるのに**変圧器は 630 台しかない**。
  66/77kV 需要のうち降圧点に直結しているのは 20.7% だけで、42% は 3 ホップ以上先、
  **10.2%（4,745MW）はどの降圧点からも到達できない**（west は 24.6%＝13,762MW）。

実系統では 66kV 変電所はそれぞれ上位電圧から降圧を受ける。モデルにそれが無いと、
基幹の電力が **66kV の導体を横に何ホップも流れて**需要へ届くことになる。
66kV 線 1 回線の容量はモデル実測で中央値 137MVA。ここに数十変電所ぶんの需要が
乗れば 1,000% 超の負荷率になる — 観測されている過負荷の姿と一致する。

本スクリプトはその機構を検証する: **上位電圧のバスが既にモデル内の近くにある場所だけ**に
降圧変圧器を足し、過負荷がどう動くかを測る。変電所そのものは足さない（足すと
「無い設備を作った」ことになる）。変圧器の定数はモデル既存のもの（vk 12.0% /
vkr 0.5% / 100MVA 刻み）をそのまま使う — 外から定数を持ち込まない。

**これは仮説の検証であって修正案ではない**。ここで過負荷が消えるなら、
「モデルに欠けているのは基幹の線ではなく降圧点である」が裏づけられる。
実際に埋めるなら OSM か公開系統図から出典付きで 1 件ずつ入れる必要がある
（`docs/MODEL_INTERVENTIONS.md` の①根拠②帳簿③無効化）。

usage:
    python3 scripts/capacity/whatif_stepdown.py --islands okinawa hokkaido
    python3 scripts/capacity/whatif_stepdown.py            # 全4島（DC・約6分）
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import subprocess
import sys
import time
from collections import defaultdict, deque
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
REPORTS = ROOT / "docs" / "reports"

LV_CLASSES = (66.0, 77.0)
VK_PERCENT = 12.0          # モデル既存の変圧器と同じ定数を使う
VKR_PERCENT = 0.5
SN_STEP = 100.0            # モデルの標準サイズ（485/630 台が 100MVA）


def load_pf():
    path = ROOT / "scripts" / "run_full_powerflow_from_db.py"
    spec = importlib.util.spec_from_file_location("pf_full", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pf_full"] = mod
    spec.loader.exec_module(mod)
    return mod


def hops_to_stepdown(net) -> dict[int, int]:
    """各バスが「同じ電圧階級の線だけを辿って」降圧点まで何ホップか。"""
    kvof = {int(b): round(float(net.bus.at[b, "vn_kv"]), 1) for b in net.bus.index}
    entry = {int(r["lv_bus"]) for _i, r in net.trafo.iterrows() if r["in_service"]}
    g = nx.Graph()
    for _i, r in net.line.iterrows():
        if not r["in_service"]:
            continue
        u, v = int(r["from_bus"]), int(r["to_bus"])
        if kvof[u] == kvof[v]:
            g.add_edge(u, v)
    dist: dict[int, int] = {}
    dq: deque[int] = deque()
    for b in entry:
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
    return dist


def add_stepdowns(pf, net, min_hops: int, radius_km: float) -> dict:
    """降圧点から遠い 66/77kV 需要バスに、近傍の上位電圧バスから変圧器を足す。"""
    import pandapower as pp

    kvof = {int(b): round(float(net.bus.at[b, "vn_kv"]), 1) for b in net.bus.index}
    dist = hops_to_stepdown(net)
    load_at: dict[int, float] = defaultdict(float)
    for _i, r in net.load.iterrows():
        if r["in_service"]:
            load_at[int(r["bus"])] += float(r["p_mw"])

    # 上位電圧バスの座標索引（変圧器の高圧側になれる候補）
    hv = []
    for b in net.bus.index:
        if kvof[int(b)] <= max(LV_CLASSES):
            continue
        x, y = pf._bus_lonlat(net, b)
        if x is None or (x == 0 and y == 0):
            continue
        hv.append((int(b), y, x))          # (bus, lat, lon)
    if not hv:
        return {"n_added": 0, "added_mva": 0.0, "n_far_buses": 0, "far_load_mw": 0.0}

    targets = []
    for b, p in load_at.items():
        if kvof[b] not in LV_CLASSES or p <= 0:
            continue
        d = dist.get(b)
        if d is None or d >= min_hops:
            targets.append((b, p, d))
    far_load = sum(p for _b, p, _d in targets)

    n_added = 0
    added_mva = 0.0
    by_ratio: dict[str, int] = defaultdict(int)
    for b, p, _d in targets:
        x, y = pf._bus_lonlat(net, b)
        if x is None:
            continue
        best = None
        best_d = radius_km
        for hb, hlat, hlon in hv:
            dd = pf._haversine_km(y, x, hlat, hlon)
            if dd < best_d:
                best_d, best = dd, hb
        if best is None:
            continue          # 近くに上位電圧が通っていない → 変電所ごと欠けている
        # 容量はその母線の需要をまかなえる最小の 100MVA 刻み（余裕率 1.2）
        sn = max(SN_STEP, math.ceil(p * 1.2 / SN_STEP) * SN_STEP)
        try:
            pp.create_transformer_from_parameters(
                net, hv_bus=int(best), lv_bus=int(b), sn_mva=sn,
                vn_hv_kv=float(net.bus.at[best, "vn_kv"]),
                vn_lv_kv=float(net.bus.at[b, "vn_kv"]),
                vk_percent=VK_PERCENT, vkr_percent=VKR_PERCENT,
                pfe_kw=0.0, i0_percent=0.0,
                name=f"whatif_stepdown_{best}_{b}")
            n_added += 1
            added_mva += sn
            by_ratio[f"{kvof[int(best)]:.0f}/{kvof[b]:.0f}"] += 1
        except (ValueError, TypeError):
            pass
    return {"n_added": n_added, "added_mva": round(added_mva, 1),
            "n_far_buses": len(targets), "far_load_mw": round(far_load, 1),
            "by_ratio": dict(sorted(by_ratio.items(), key=lambda x: -x[1])[:8])}


def overload_stats(net) -> dict:
    if not len(net.res_line):
        return {"n_line": 0, "n_over": 0, "max_pct": None, "excess_mw": 0.0,
                "over_share": 0.0, "over_lv": 0, "over_hv": 0}
    df = net.res_line.join(net.line[["in_service", "from_bus"]], rsuffix="_l")
    df = df[df["in_service"].fillna(False)]
    lp = df["loading_percent"].dropna()
    if not len(lp):
        return {"n_line": 0, "n_over": 0, "max_pct": None, "excess_mw": 0.0,
                "over_share": 0.0, "over_lv": 0, "over_hv": 0}
    oi = lp[lp > 100.0].index
    excess = float((df.loc[oi, "p_from_mw"].abs() * (1.0 - 100.0 / lp[oi])).sum()) if len(oi) else 0.0
    kv = df.loc[oi, "from_bus"].map(lambda b: float(net.bus.at[int(b), "vn_kv"]))
    return {"n_line": int(len(lp)), "n_over": int(len(oi)),
            "max_pct": round(float(lp.max()), 1), "excess_mw": round(excess, 1),
            "over_share": round(len(oi) / len(lp), 4),
            "over_lv": int((kv <= 110.0).sum()), "over_hv": int((kv >= 154.0).sum())}


def run(pf, island, nodes, edges, cfg, pref_gwh, add: bool,
        min_hops: int, radius_km: float) -> dict:
    t0 = time.time()
    net, bus_of, bstats = pf.build_island_net(
        island, nodes, edges, pf.ISLAND_FREQ[island], {},
        dedup_nodes=True, site_trafos=False, deenergize_unbuilt=False)
    pf.attach_generators(net, bus_of, nodes, island)
    pf.allocate_loads(net, cfg, pref_gwh=pref_gwh)
    info = {"n_added": 0, "added_mva": 0.0, "n_far_buses": 0, "far_load_mw": 0.0}
    if add:
        info = add_stepdowns(pf, net, min_hops, radius_km)
    from src.powerflow.pipeline import add_reactive_compensation
    add_reactive_compensation(net, factor=cfg.get("reactive_compensation_factor", 0.6))
    n_comp, _ns, _nsy = pf.add_per_component_slacks(net)
    pf.balance_by_zone(net, cfg)
    net_dc, dc, _a, _b = pf.solve_island(net, max_ac_buses=0)
    return {"island": island, "variant": "＋降圧点" if add else "既定",
            "n_trafo": int(net.trafo["in_service"].sum()), "n_components": n_comp,
            **info, "dc_converged": bool(dc.get("converged")),
            "overload": overload_stats(net_dc), "seconds": round(time.time() - t0, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="*",
                    default=["hokkaido", "east", "west", "okinawa"])
    ap.add_argument("--min-hops", type=int, default=3,
                    help="降圧点からこのホップ数以上離れた需要バスを対象にする")
    ap.add_argument("--radius-km", type=float, default=10.0,
                    help="上位電圧バスをこの半径内に限って探す（無ければ変電所ごと欠けている）")
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                                       text=True).stdout.strip()

    pf = load_pf()
    with open(pf.BUILT, encoding="utf-8") as f:
        db = json.load(f)
    nodes, edges = db["nodes"], db["edges"]
    cfg = pf.load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(nodes)

    res = []
    for island in args.islands:
        for add in (False, True):
            r = run(pf, island, nodes, edges, cfg, pref_gwh, add,
                    args.min_hops, args.radius_km)
            o = r["overload"]
            print(f"[{island:9s}] {r['variant']:7s} 変圧器 {r['n_trafo']:5,}台"
                  f"(+{r['n_added']:,}/{r['added_mva']:,.0f}MVA)  "
                  f"過負荷 {o['n_over']:4,}/{o['n_line']:,} ({o['over_share']:5.2%}) "
                  f"低圧 {o['over_lv']:4,} 高圧 {o['over_hv']:3,}  最大 {o['max_pct']}%  "
                  f"超過 {o['excess_mw']:,.0f}MW  {r['seconds']:.0f}s", flush=True)
            res.append(r)

    (REPORTS / f"whatif_stepdown_{date}.json").write_text(
        json.dumps({"date": date, "min_hops": args.min_hops,
                    "radius_km": args.radius_km, "runs": res},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    L = [f"# 欠けている降圧点を補うと過負荷はどうなるか（what-if・{date}）", "",
         "east は 66/77kV バスが 4,727 個あるのに**変圧器は 630 台**。66/77kV 需要のうち",
         "降圧点に直結しているのは 20.7% で、42% は 3 ホップ以上先、**10.2%（4,745MW）は",
         "どの降圧点からも到達できない**（west は 24.6%＝13,762MW）。実系統では 66kV 変電所は",
         "それぞれ上位電圧から降圧を受けるので、この形は**モデル固有の欠損**である。", "",
         f"上位電圧のバスが既にモデル内 {args.radius_km:.0f}km 以内にある場所だけに降圧変圧器を足し",
         f"（降圧点から {args.min_hops} ホップ以上離れた需要バスが対象）、過負荷の動きを測った。",
         "変電所そのものは足していない。変圧器の定数はモデル既存のもの",
         f"（vk {VK_PERCENT}% / vkr {VKR_PERCENT}% / {SN_STEP:.0f}MVA 刻み）をそのまま使う。", "",
         "## 結果", "",
         "| 島 | 構成 | 変圧器 | 追加 | 過負荷 | 低圧(≤110kV) | 高圧(≥154kV) | 最大負荷率 | 超過潮流 |",
         "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in res:
        o = r["overload"]
        L.append(f"| {r['island']} | {r['variant']} | {r['n_trafo']:,} | "
                 f"{r['n_added']:,} 台 / {r['added_mva']:,.0f} MVA | "
                 f"{o['n_over']:,} ({o['over_share']:.2%}) | {o['over_lv']:,} | "
                 f"{o['over_hv']:,} | {o['max_pct']}% | {o['excess_mw']:,.0f} MW |")
    L += ["", "## 対象となった需要バス", "",
          "| 島 | 降圧点から遠い需要バス | その需要 | 上位電圧が近くにあり補えた |",
          "|---|---:|---:|---:|"]
    for r in res:
        if r["variant"] == "既定":
            continue
        L.append(f"| {r['island']} | {r['n_far_buses']:,} | {r['far_load_mw']:,.0f} MW | "
                 f"{r['n_added']:,} |")
    L += ["", "追加した変圧比の内訳:", ""]
    for r in res:
        if r["variant"] == "既定" or not r.get("by_ratio"):
            continue
        L.append(f"- **{r['island']}**: " +
                 " / ".join(f"{k}kV {v}台" for k, v in r["by_ratio"].items()))
    L += ["", "---",
          "**これは仮説の検証であって修正案ではない**。実際に埋めるなら OSM か公開系統図から",
          "出典付きで 1 件ずつ入れる必要がある（`docs/MODEL_INTERVENTIONS.md` の",
          "①根拠②帳簿③無効化）。", "",
          "生成: `scripts/capacity/whatif_stepdown.py`（DC・介入#19/#20/#21 既定ON相当）", ""]
    (REPORTS / f"whatif_stepdown_{date}.md").write_text("\n".join(L), encoding="utf-8")
    print(f"→ docs/reports/whatif_stepdown_{date}.md")


if __name__ == "__main__":
    main()
