#!/usr/bin/env python3
"""66/77kV 層を網として解くのをやめたら過負荷はどうなるか（what-if・未適用）。

`stepdown_sourcing_negative_2026-08-10.md` の結論: **降圧点は現在の出典では埋められない**。
keitouzu からは 14 箇所（全て沖縄）、OSM の同名一致からは 2km 以内 7 組しか出ず、
必要な east 951 / west 781 には遠く及ばない。`whatif_stepdown` の「+951 台で 603→422」は
**捏造でしか到達できない改善**だった。

そこで残る道は「66/77kV 層を網としてモデル化するのをやめる」— これは**捏造ではなく縮約**で、
送電系統モデルの標準的な作法でもある（配電は HV/MV 変電所の集約負荷として置く）。
`feedback_reduction_reality` の「帳簿付き集約＋実データ検証でリアリティを失わない」に沿う。

## 何をするか

66/77kV のバスに載っているものを、**同じ 66kV 連結成分の中で最寄りの降圧点**（変圧器の
低圧側）へ寄せる。線路は消さない（消すと連結性が変わって別の話になる）。

  現行            66kV のものはその場に置く
  縮約(需要のみ)   降圧点から d ホップ以上離れた 66/77kV **需要**を最寄り降圧点へ
  縮約(需要+発電)  **需要と発電を一緒に**寄せる

**需要だけ寄せると悪化する**（実測: east 551→568・west 291→357）。66/77kV 層は純輸入
（east −21GW）だが**発電も 25.4GW ぶん載っている**ので、需要だけ動かすと残った発電が
地元で消費されなくなり横流れが増える。等価回路としての縮約は両方を寄せて初めて成立する。

**寄せられない需要は寄せない。** どの降圧点からも到達できない需要（east 10.2%＝4,745MW /
west 24.6%＝13,762MW）はその場に残し、**「縮約で解決できなかった量」として帳簿に出す**。
そこを近傍の上位電圧へ繋ぐのは捏造なので行わない。

接続規則は本番既定（介入#24 = cap）で固定する。

usage:
    python3 scripts/capacity/whatif_lv_reduction.py --islands east west
"""
from __future__ import annotations

import argparse
import importlib.util
import json
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


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_modules():
    pf = _load(ROOT / "scripts" / "run_full_powerflow_from_db.py", "pf_full")
    rs = _load(ROOT / "scripts" / "capacity" / "repair_search.py", "rs_lv")
    return pf, rs


def lv_graph_and_entries(net):
    """同一電圧階級の線だけのグラフと、降圧点（変圧器の低圧側）の集合。"""
    kvof = {int(b): round(float(net.bus.at[b, "vn_kv"]), 1) for b in net.bus.index}
    entry = {int(r["lv_bus"]) for _i, r in net.trafo.iterrows() if r["in_service"]}
    g = nx.Graph()
    for _i, r in net.line.iterrows():
        if not r["in_service"]:
            continue
        u, v = int(r["from_bus"]), int(r["to_bus"])
        if kvof[u] == kvof[v]:
            g.add_edge(u, v)
    return g, entry, kvof


def nearest_entry(g, entries) -> dict[int, tuple[int, int]]:
    """各バス → (最寄り降圧点, ホップ数)。多元 BFS。"""
    out: dict[int, tuple[int, int]] = {}
    dq: deque[int] = deque()
    for b in entries:
        out[b] = (b, 0)
        dq.append(b)
    while dq:
        x = dq.popleft()
        if x not in g:
            continue
        src, d = out[x]
        for y in g.neighbors(x):
            if y not in out:
                out[y] = (src, d + 1)
                dq.append(y)
    return out


def reduce_lv(pf, net, min_hops: int, move_gen: bool) -> dict:
    """降圧点から min_hops 以上離れた 66/77kV の需要（と任意で発電）を最寄り降圧点へ寄せる。

    **負荷だけ寄せると悪化する**（2026-08-10 実測: east 551→568・west 291→357）。
    66/77kV 層は純輸入（east −21GW）だが、**発電も 25.4GW ぶん載っている**。
    負荷だけ動かすと、その場に残った発電が地元で消費されなくなり横流れが増える。
    等価回路としての縮約は**需要と発電を一緒に**寄せなければ成立しない。
    """
    g, entries, kvof = lv_graph_and_entries(net)
    near = nearest_entry(g, entries)

    moved_n = moved_mw = 0.0
    moved_n = 0
    stranded_n, stranded_mw = 0, 0.0
    hops_hist: dict[int, int] = defaultdict(int)
    km_sum = 0.0
    for li in net.load.index:
        if not bool(net.load.at[li, "in_service"]):
            continue
        b = int(net.load.at[li, "bus"])
        if kvof.get(b) not in LV_CLASSES:
            continue
        p = float(net.load.at[li, "p_mw"])
        if p <= 0:
            continue
        hit = near.get(b)
        if hit is None:
            # どの降圧点からも到達できない = 縮約で解決できない
            stranded_n += 1
            stranded_mw += p
            continue
        src, d = hit
        if d < min_hops:
            continue
        x1, y1 = pf._bus_lonlat(net, b)
        x2, y2 = pf._bus_lonlat(net, src)
        if x1 is not None and x2 is not None:
            km_sum += pf._haversine_km(y1, x1, y2, x2) * p
        net.load.at[li, "bus"] = int(src)
        moved_n += 1
        moved_mw += p
        hops_hist[d] += 1

    gen_n, gen_mw, gen_stranded_mw = 0, 0.0, 0.0
    if move_gen:
        for gi in net.gen.index:
            b = int(net.gen.at[gi, "bus"])
            if kvof.get(b) not in LV_CLASSES:
                continue
            cap = float(net.gen.at[gi, "max_p_mw"])
            hit = near.get(b)
            if hit is None:
                gen_stranded_mw += cap
                continue
            src, d = hit
            if d < min_hops:
                continue
            net.gen.at[gi, "bus"] = int(src)
            gen_n += 1
            gen_mw += cap
    return {"n_moved": moved_n, "moved_mw": round(moved_mw, 1),
            "mean_move_km": round(km_sum / moved_mw, 2) if moved_mw else 0.0,
            "n_stranded": stranded_n, "stranded_mw": round(stranded_mw, 1),
            "n_gen_moved": gen_n, "gen_moved_mw": round(gen_mw, 1),
            "gen_stranded_mw": round(gen_stranded_mw, 1),
            "hops": dict(sorted(hops_hist.items())[:8])}


def run(pf, rs, island, nodes, edges, cfg, pref_gwh, variant: str,
        min_hops: int) -> dict:
    t0 = time.time()
    net, bus_of, _ = pf.build_island_net(
        island, nodes, edges, pf.ISLAND_FREQ[island], {},
        dedup_nodes=True, site_trafos=False, deenergize_unbuilt=False)
    pf.attach_generators(net, bus_of, nodes, island,
                         attach_mode=pf.GEN_ATTACH_DEFAULT)
    pf.allocate_loads(net, cfg, pref_gwh=pref_gwh)
    info = {"n_moved": 0, "moved_mw": 0.0, "mean_move_km": 0.0,
            "n_stranded": 0, "stranded_mw": 0.0, "n_gen_moved": 0,
            "gen_moved_mw": 0.0, "gen_stranded_mw": 0.0, "hops": {}}
    if variant != "現行":
        info = reduce_lv(pf, net, min_hops, move_gen=(variant == "縮約(需要+発電)"))
    from src.powerflow.pipeline import add_reactive_compensation
    add_reactive_compensation(net, factor=cfg.get("reactive_compensation_factor", 0.6))
    n_comp, _ns, n_synth = pf.add_per_component_slacks(net)
    pf.balance_by_zone(net, cfg)
    net_dc, dc, _a, _b = pf.solve_island(net, max_ac_buses=0)
    return {"island": island, "variant": variant,
            "n_components": n_comp, "n_synth_slack": int(n_synth), **info,
            "dc_converged": bool(dc.get("converged")),
            "overload": rs.overload_stats(net_dc),
            "overload_power_basis": rs.overload_stats_power(net_dc),
            "seconds": round(time.time() - t0, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="*",
                    default=["hokkaido", "east", "west", "okinawa"])
    ap.add_argument("--min-hops", type=int, default=1,
                    help="降圧点からこのホップ数以上離れた需要を寄せる（1=直結以外すべて）")
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                                       text=True).stdout.strip()

    pf, rs = load_modules()
    with open(pf.BUILT, encoding="utf-8") as f:
        db = json.load(f)
    nodes, edges = db["nodes"], db["edges"]
    cfg = pf.load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(nodes)

    res = []
    for island in args.islands:
        for variant in ("現行", "縮約(需要のみ)", "縮約(需要+発電)"):
            r = run(pf, rs, island, nodes, edges, cfg, pref_gwh, variant, args.min_hops)
            o, o2 = r["overload"], r["overload_power_basis"]
            print(f"[{island:9s}] {r['variant']:14s} | 過負荷 {o['n_over']:4,}/{o['n_line']:,} "
                  f"({o['over_share']:6.2%}) 最大 {o['max_pct']:>8}% "
                  f"超過 {o['excess_mw']:>10,.0f}MW | 寄せた {r['n_moved']:5,}件/"
                  f"{r['moved_mw']:>8,.0f}MW(平均{r['mean_move_km']:5.1f}km) "
                  f"発電 {r['n_gen_moved']:5,}機/{r['gen_moved_mw']:>8,.0f}MW "
                  f"寄せられず {r['n_stranded']:4,}件/{r['stranded_mw']:>8,.0f}MW "
                  f"| 偽電源 {r['n_synth_slack']:4,} 乖離{o2['max_gap_pt']}pt {r['seconds']:.0f}s",
                  flush=True)
            res.append(r)

    (REPORTS / f"whatif_lv_reduction_{date}.json").write_text(
        json.dumps({"date": date, "min_hops": args.min_hops,
                    "gen_attach": pf.GEN_ATTACH_DEFAULT, "runs": res},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    L = [f"# 66/77kV 層を網として解くのをやめたら過負荷はどうなるか（what-if・{date}）", "",
         "`stepdown_sourcing_negative_2026-08-10.md` で、**降圧点は現在の出典では埋められない**",
         "と分かった（keitouzu 14箇所は全て沖縄・OSM 同名は 2km 以内 7 組。必要数は east 951/west 781）。",
         "`whatif_stepdown` の改善は**捏造でしか到達できない**ものだった。", "",
         "残る道は「66/77kV 層を網としてモデル化するのをやめる」— **捏造ではなく縮約**であり、",
         "送電系統モデルの標準的な作法（配電は HV/MV 変電所の集約負荷として置く）でもある。",
         f"66/77kV の需要を、同一成分の最寄り降圧点へ寄せる（{args.min_hops} ホップ以上離れたもの）。",
         "**線路は消さない。寄せるのは負荷だけ。**", "",
         f"接続規則は本番既定（介入#24 = {pf.GEN_ATTACH_DEFAULT}）で固定。", "",
         "## 結果", "",
         "| 島 | 構成 | 過負荷 | 最大負荷率 | 超過潮流 | 偽電源 | 寄せた需要 | 平均移動 | **寄せられなかった需要** |",
         "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in res:
        o = r["overload"]
        L.append(f"| {r['island']} | {r['variant']} | {o['n_over']:,} ({o['over_share']:.2%}) | "
                 f"{o['max_pct']}% | {o['excess_mw']:,.0f} MW | {r['n_synth_slack']:,} | "
                 f"{r['n_moved']:,} 件 / {r['moved_mw']:,.0f} MW | {r['mean_move_km']:.1f} km | "
                 f"{r['n_stranded']:,} 件 / **{r['stranded_mw']:,.0f} MW** |")
    L += ["", "**寄せられなかった需要**＝どの降圧点からも到達できない 66/77kV 需要。",
          "そこを近傍の上位電圧へ繋ぐのは捏造なので行わない。**縮約で解決できない残り**として",
          "そのまま開示する — これがモデルの穴の正味の大きさになる。", "",
          "---",
          "**未適用**。採るなら縮約の帳簿（何をどこへ寄せたか）ごと",
          "`docs/MODEL_INTERVENTIONS.md` に登録する。", "",
          "生成: `scripts/capacity/whatif_lv_reduction.py`（DC）", ""]
    (REPORTS / f"whatif_lv_reduction_{date}.md").write_text("\n".join(L), encoding="utf-8")
    print(f"→ docs/reports/whatif_lv_reduction_{date}.md")


if __name__ == "__main__":
    main()
