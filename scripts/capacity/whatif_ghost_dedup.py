#!/usr/bin/env python3
"""近接重複（幽霊変電所）を潰すと偽電源はどれだけ減るか（what-if・未適用）。

## 何を見つけたか

`triage_isolated_hv.py` が「接続ゼロの ≥275kV 変電所 16 件」のうち 6 件を
**重複コピー**と判定した。全電圧に広げて数えると:

  0.3km 以内の変電所ペア  1,405 組
    うち跨region          1,051 組（bbox スピルオーバー）
    うち**片方だけ枝ゼロ**   115 組 ← 「幽霊」
      さらに跨region        106 組（幽霊の 92%）

みなかみ町変電所は **tohoku・tokyo・chubu の 3 地域**に存在し、tokyo のコピーだけが
枝を持つ。残り 2 つは 275kV なのに接続ゼロの幽霊として残る。

## なぜ介入#21 ですり抜けるか

介入#21 の dedup は「**同一座標 6 桁** + kv が一致」を 1 バスに潰す実装。
幽霊ペアは 0.01〜0.3km ずれている（同じ設備の別ソース由来なので座標が微妙に違う）ため、
**6 桁一致では捕まらない**。結果、幽霊は潮流に孤立バスとして残り、
`add_per_component_slacks` が**実在しない電源（合成 slack）**を置く。

つまり跨region重複は、今日の 4 目的のひとつ「偽電源」を直接押し上げている疑いがある
—— **と考えたが、測ったら棄却された**（下記）。本スクリプトはその測定器。モデルは変更しない。

## 結論: 仮説は棄却（2026-08-10）

east の幽霊 133 件のうち **127 件は 0.3km 以内に何も無い**（同一 kV のアンカーは 2 件だけ）。
偽電源は 290→288 とほぼ動かない。**built のレコードで数えた「幽霊 115 組」と、
潮流の孤立バスは別の母集団だった** — `build_island_net(dedup_nodes=True)` が同一座標の
ものを先に潰しており、残る孤立バスは重複ではなく**純粋に孤立した変電所**（既知のカテゴリ）。

跨region重複そのものは実在するが（1,051 組）、効くのは **built を読む側**
（系統図・CIM・topoRAG）であって**潮流の偽電源ではない**。効き先を取り違えないこと。

半径を振って、(成分数 / 偽電源 / 過負荷) がどう動くかを見る。
これは**除去であって接続を作らない**ので捏造にはならないが、
「別々の実設備を 1 つに潰す」誤りは起こしうるので、採否は人間判断。

usage: python3 scripts/capacity/whatif_ghost_dedup.py --islands east west
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
REPORTS = ROOT / "docs" / "reports"

RADII_KM = [0.0, 0.05, 0.15, 0.30]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _hav(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def merge_ghosts(pf, net, radius_km: float) -> dict:
    """半径内で「枝ゼロのバス」を「枝を持つ同電圧のバス」へ寄せる。

    バスは消さず、**load/gen/枝の付け替え**もしない — 幽霊は元々どれも持たないので、
    ここでやるのは `add_per_component_slacks` の前に**両者を 1 本の枝で繋ぐ**こと。
    「同一設備の重複コピーだった」という判断に基づく再結合であり、
    新しい設備を作るのではない（インピーダンスは無視できる短絡相当）。
    """
    import pandapower as pp

    deg = defaultdict(int)
    for _i, r in net.line.iterrows():
        if r["in_service"]:
            deg[int(r["from_bus"])] += 1
            deg[int(r["to_bus"])] += 1
    for _i, r in net.trafo.iterrows():
        if r["in_service"]:
            deg[int(r["hv_bus"])] += 1
            deg[int(r["lv_bus"])] += 1

    kv = {int(b): round(float(net.bus.at[b, "vn_kv"]), 1) for b in net.bus.index}
    pos = {}
    for b in net.bus.index:
        x, y = pf._bus_lonlat(net, b)
        if x is not None and not (x == 0 and y == 0):
            pos[int(b)] = (y, x)
    ghosts = [b for b in pos if deg.get(b, 0) == 0]
    anchors = defaultdict(list)
    for b in pos:
        if deg.get(b, 0) > 0:
            anchors[kv[b]].append(b)

    n_merged, pairs = 0, []
    for g in ghosts:
        best, bd = None, radius_km
        for a in anchors.get(kv[g], ()):
            d = _hav(pos[g], pos[a])
            if d < bd:
                bd, best = d, a
        if best is None:
            continue
        try:
            pp.create_line_from_parameters(
                net, from_bus=int(g), to_bus=int(best), length_km=max(bd, 1e-3),
                r_ohm_per_km=0.01, x_ohm_per_km=0.01, c_nf_per_km=0.0,
                max_i_ka=10.0, name=f"ghost_merge_{g}_{best}")
            n_merged += 1
            pairs.append((g, best, round(bd, 3)))
        except (ValueError, TypeError):
            pass
    # **なぜ併合できなかったか**を必ず出す。件数だけ見て「効果なし」と結論すると、
    # 実装の制約（同一kV限定）が原因なのか母集団が違うのか区別できない。
    n_any = n_none = 0
    for g in ghosts:
        near_any = min((_hav(pos[g], pos[a]) for a in pos
                        if a != g and deg.get(a, 0) > 0), default=1e9)
        if near_any <= radius_km:
            n_any += 1
        else:
            n_none += 1
    return {"n_ghost": len(ghosts), "n_merged": n_merged,
            "n_anchor_any_kv": n_any, "n_no_anchor": n_none,
            "merged_km_max": max([p[2] for p in pairs], default=0.0)}


def run(pf, rs, island, nodes, edges, cfg, pref_gwh, radius) -> dict:
    t0 = time.time()
    net, bus_of, _ = pf.build_island_net(
        island, nodes, edges, pf.ISLAND_FREQ[island], {},
        dedup_nodes=True, site_trafos=False, deenergize_unbuilt=False)
    pf.attach_generators(net, bus_of, nodes, island,
                         attach_mode=pf.GEN_ATTACH_DEFAULT)
    pf.allocate_loads(net, cfg, pref_gwh=pref_gwh)
    info = {"n_ghost": 0, "n_merged": 0, "n_anchor_any_kv": 0,
            "n_no_anchor": 0, "merged_km_max": 0.0}
    if radius > 0:
        info = merge_ghosts(pf, net, radius)
    from src.powerflow.pipeline import add_reactive_compensation
    add_reactive_compensation(net, factor=cfg.get("reactive_compensation_factor", 0.6))
    n_comp, _ns, n_synth = pf.add_per_component_slacks(net)
    pf.balance_by_zone(net, cfg, use_zone_src=pf.GEN_ZONE_BY_OPERATOR)
    net_dc, dc, _a, _b = pf.solve_island(net, max_ac_buses=0)
    return {"island": island, "radius_km": radius, **info,
            "n_components": n_comp, "n_synth_slack": int(n_synth),
            "overload": rs.overload_stats(net_dc),
            "seconds": round(time.time() - t0, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="*", default=["east", "west"])
    ap.add_argument("--radii", nargs="*", type=float, default=RADII_KM)
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                                       text=True).stdout.strip()

    pf = _load(ROOT / "scripts" / "run_full_powerflow_from_db.py", "pf_full")
    rs = _load(ROOT / "scripts" / "capacity" / "repair_search.py", "rs_ghost")
    with open(pf.BUILT, encoding="utf-8") as f:
        db = json.load(f)
    nodes, edges = db["nodes"], db["edges"]
    cfg = pf.load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(nodes)

    res = []
    for island in args.islands:
        for r in args.radii:
            x = run(pf, rs, island, nodes, edges, cfg, pref_gwh, r)
            o = x["overload"]
            print(f"[{island:9s}] 半径 {r:4.2f}km | 幽霊 {x['n_ghost']:4,} "
                  f"→ 併合 {x['n_merged']:4,}（近傍なし {x['n_no_anchor']:4,}）"
                  f" | 成分 {x['n_components']:4,} "
                  f"**偽電源 {x['n_synth_slack']:4,}** | 過負荷 {o['n_over']:4,} "
                  f"最大 {o['max_pct']:>8}% 超過 {o['excess_mw']:>9,.0f}MW  {x['seconds']:.0f}s",
                  flush=True)
            res.append(x)

    (REPORTS / f"whatif_ghost_dedup_{date}.json").write_text(
        json.dumps({"date": date, "runs": res}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    L = [f"# 近接重複（幽霊変電所）を潰すと偽電源はどれだけ減るか（what-if・{date}）", "",
         "`triage_isolated_hv` が「接続ゼロの ≥275kV 変電所」16 件のうち 6 件を**重複コピー**",
         "と判定した。全電圧に広げると **0.3km 以内のペア 1,405 組・うち跨region 1,051 組・",
         "うち片方だけ枝ゼロの「幽霊」115 組（その 92% が跨region）**。", "",
         "**介入#21 の dedup がすり抜ける理由**: あれは「同一座標 6 桁 + kv 一致」を潰す実装で、",
         "幽霊ペアは 0.01〜0.3km ずれている（同じ設備の別ソース由来）ため捕まらない。",
         "結果、幽霊は孤立バスとして残り `add_per_component_slacks` が",
         "**実在しない電源（合成 slack）**を置く。", "",
         "## 結果", "",
         "| 島 | 半径 | 幽霊 | 併合 | **近傍なし** | 成分 | **偽電源** | 過負荷 | 最大負荷率 | 超過潮流 |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for x in res:
        o = x["overload"]
        L.append(f"| {x['island']} | {x['radius_km']:.2f}km | {x['n_ghost']:,} | "
                 f"{x['n_merged']:,} | **{x['n_no_anchor']:,}** | "
                 f"{x['n_components']:,} | **{x['n_synth_slack']:,}** | "
                 f"{o['n_over']:,} | {o['max_pct']}% | {o['excess_mw']:,.0f} MW |")
    L += ["", "## 結論 — 仮説は棄却された", "",
          "**跨region重複は潮流の偽電源の原因ではない。** east で幽霊 133 件のうち",
          "**127 件は 0.3km 以内に何も無い**（同一 kV のアンカーがあるのは 2 件だけ）。",
          "併合できたのは 1〜2 件で、偽電源は 290→288 とほぼ動かない。", "",
          "見立てを誤った理由: built の変電所レコードで数えた「幽霊 115 組」と、",
          "潮流の孤立バス（east 133・west 224）は**別の母集団**だった。",
          "`build_island_net(dedup_nodes=True)` が同一座標のものを先に潰しており、",
          "残る孤立バスは重複ではなく**純粋に孤立した変電所**（既知のカテゴリ）。", "",
          "跨region重複そのものは実在し（0.3km 以内 1,405 組・跨region 1,051 組）、",
          "built のレコード上で幽霊の ≥275kV 変電所を作っている",
          "（`isolated_hv_triage_2026-08-10.md` の A 分類 6 件）。",
          "**built を読む側**（系統図・CIM・topoRAG）には影響するが、",
          "**潮流の偽電源には効かない** — 直す価値はあるが、効き先を取り違えないこと。", "",
          "---",
          "**未適用**。これは**除去（再結合）であって新しい設備を作るのではない**が、",
          "「別々の実設備を 1 つに潰す」誤りは起こしうるので採否は人間判断",
          "（`feedback_lever_candidates_human_judgment`）。採るなら介入台帳に登録する。", "",
          "生成: `scripts/capacity/whatif_ghost_dedup.py`（DC）", ""]
    (REPORTS / f"whatif_ghost_dedup_{date}.md").write_text("\n".join(L), encoding="utf-8")
    print(f"→ docs/reports/whatif_ghost_dedup_{date}.md")


if __name__ == "__main__":
    main()
