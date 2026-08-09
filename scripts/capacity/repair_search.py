#!/usr/bin/env python3
"""修復候補を「組み合わせ」で探索し、捏造量ともっともらしさのパレート境界を出す。

2026-08-09 の診断連鎖は過負荷の真因を 3 つ挙げた。しかし**いずれも単独で**測っており、
単独では次のように読める:

  - 太陽光の既定値 10MW → 実測中央値 0.10MW に正すと east の最大負荷率は
    1,668% → 3,371%、超過潮流は 122GW → 139GW と**悪化する**
    （`whatif_solar_default_2026-08-09.md`）
  - 発電機の接続電圧を直すと east 超過潮流 −26%（`whatif_gen_voltage_2026-08-09.md`）
  - 降圧点を足すと east 過負荷 603 → 422 本（`whatif_stepdown_2026-08-09.md`）

**交互作用のある系で一度に一つしか動かさないのは古典的な誤りである。**
「正すと悪化する」は、他の欠陥が残っているときにこそ典型的に起きる — 膨らんだ太陽光は
系統中に薄く広がった注入なので、それを取り除くと発電は実在の火力・原子力へ集中する。
その火力・原子力が 66kV バスに繋がっていて（真因A）、66kV から上位へ抜ける降圧点も
無い（真因B）なら、集中した注入は 66kV の導体を横に流れるしかない。
**単独の是正が悪化を生む機構がここにある。** 三つ同時に正して初めて答えが出る。

本スクリプトは 3 軸の全組み合わせ（4×2×2 = 16 通り／島）を回す:

  gen   base | site | cap | kvfit   発電機の接続先の選び方（whatif_gen_voltage と同一実装）
  sd    off  | on                   欠けた降圧点の補充（whatif_stepdown と同一実装）
  solar 10.0 | 0.10 MW              太陽光の既定容量（whatif_solar_default と同一の梃子）

## もう一つの軸 — 捏造量を第一級の目的関数にする

`docs/MODEL_INTERVENTIONS.md` の原則は「モデルを解けるように見せる介入は全部登録しろ」
である。ならば探索も「過負荷が減ったか」だけで採点してはいけない。**その修復が
出典のない構造をどれだけ増やしたか**を同時に測り、両者のパレート境界を出す。

  捏造容量 (MW)  出典が無く既定値で埋めた発電容量の合計（太陽光の是正はこれを**減らす**）
  捏造設備 (台)  OSM にも公開系統図にも無い、こちらで足した変圧器の台数
  超過潮流 (MW)  定格を超えて流れている分＝物理的に成立していない量

3 目的の非劣解（Pareto 集合）を出すので、重み付けという恣意を入れずに
「どこまで嘘をつけばどこまでもっともらしくなるか」を人間が読める形で置ける。
採否は人間判断（[[feedback_lever_candidates_human_judgment]]）— 機械はここまで。

## 測定器そのものを疑う

過負荷指標は pandapower の `loading_percent`（電流基準）に依存する。この診断系列では
**並列回線数の取り違えを 4 回踏んでいる**ので、`|P| / (max_i_ka × kV × √3 × parallel)`
という**電力基準の独立経路**でも負荷率を計算し、両者の食い違いを毎回報告する。
食い違うなら結論より先に測定を疑う（[[feedback_verify_before_claiming]]）。

usage:
    python3 scripts/capacity/repair_search.py --islands okinawa hokkaido
    python3 scripts/capacity/repair_search.py --islands east west   # 約40分
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

GEN_MODES = ["base", "site", "cap", "kvfit"]
SOLAR_LEVELS = [10.0, 0.10]      # 現行 / OSM 実容量の中央値
SD_LEVELS = [False, True]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_modules():
    """潮流本体と 2 本の what-if を読み込む。

    修復オペレータは **what-if スクリプトの関数をそのまま呼ぶ**。ここで書き直すと
    「診断と本番の実装が食い違って二度誤った」を三度目にする。
    """
    pf = _load(ROOT / "scripts" / "run_full_powerflow_from_db.py", "pf_full")
    wgv = _load(ROOT / "scripts" / "capacity" / "whatif_gen_voltage.py", "wgv")
    wsd = _load(ROOT / "scripts" / "capacity" / "whatif_stepdown.py", "wsd")
    return pf, wgv, wsd


# ──────────────────────────────────────────────────────────────────────────
#  もっともらしさ（過負荷）— 独立な二経路で測る
# ──────────────────────────────────────────────────────────────────────────
def overload_stats(net) -> dict:
    """過負荷指標。pandapower の loading_percent（電流基準）を一次経路とする。"""
    if not len(net.res_line):
        return {"n_line": 0, "n_over": 0, "max_pct": None, "excess_mw": 0.0,
                "over_share": 0.0, "over_lv": 0, "over_hv": 0, "p95_pct": None}
    df = net.res_line.join(net.line[["in_service", "from_bus"]], rsuffix="_l")
    df = df[df["in_service"].fillna(False)]
    lp = df["loading_percent"].dropna()
    if not len(lp):
        return {"n_line": 0, "n_over": 0, "max_pct": None, "excess_mw": 0.0,
                "over_share": 0.0, "over_lv": 0, "over_hv": 0, "p95_pct": None}
    oi = lp[lp > 100.0].index
    excess = float((df.loc[oi, "p_from_mw"].abs() * (1.0 - 100.0 / lp[oi])).sum()) if len(oi) else 0.0
    kv = df.loc[oi, "from_bus"].map(lambda b: float(net.bus.at[int(b), "vn_kv"]))
    return {"n_line": int(len(lp)), "n_over": int(len(oi)),
            "max_pct": round(float(lp.max()), 1),
            "p95_pct": round(float(lp.quantile(0.95)), 1),
            "excess_mw": round(excess, 1),
            "over_share": round(len(oi) / len(lp), 4),
            "over_lv": int((kv <= 110.0).sum()), "over_hv": int((kv >= 154.0).sum())}


def overload_stats_power(net) -> dict:
    """独立経路: 電力基準で負荷率を組み直す。

    定格 = max_i_ka × kV × √3 × parallel（MVA）、負荷率 = |P| / 定格。
    DC 解では Q=0 なので |S| = |P| となり、電流基準の loading_percent と一致するはず。
    一致しなければ **並列回線数・df・電圧の取り違え**が測定側にある。

    kV は**両端の低い方**を使う。混在電圧線（本モデルは採用している）では同じ P に対し
    低圧側の電流が大きく、pandapower は max(i_from, i_to) で採るため、from 側基準だと
    負荷率を過小評価する。hokkaido 110/66kV 線で 21.9% vs 36.5%（14.6pt）の食い違いとして
    実際に検出された — 測定器の誤りであってモデルの誤りではない。
    """
    if not len(net.res_line):
        return {"n_over": 0, "max_pct": None, "excess_mw": 0.0, "max_gap_pt": None}
    lines = net.line
    res = net.res_line
    n_over = 0
    excess = 0.0
    mx = 0.0
    max_gap = 0.0
    for li in lines.index:
        if not bool(lines.at[li, "in_service"]):
            continue
        p = res.at[li, "p_from_mw"] if li in res.index else None
        if p is None or (isinstance(p, float) and math.isnan(p)):
            continue
        kv = min(float(net.bus.at[int(lines.at[li, "from_bus"]), "vn_kv"]),
                 float(net.bus.at[int(lines.at[li, "to_bus"]), "vn_kv"]))
        par = max(1, int(lines.at[li, "parallel"] or 1))
        df_ = float(lines.at[li, "df"]) if "df" in lines.columns else 1.0
        rating = float(lines.at[li, "max_i_ka"]) * kv * math.sqrt(3.0) * par * (df_ or 1.0)
        if rating <= 0:
            continue
        pct = abs(float(p)) / rating * 100.0
        mx = max(mx, pct)
        ref = res.at[li, "loading_percent"] if li in res.index else None
        if ref is not None and not (isinstance(ref, float) and math.isnan(ref)):
            max_gap = max(max_gap, abs(pct - float(ref)))
        if pct > 100.0:
            n_over += 1
            excess += abs(float(p)) * (1.0 - 100.0 / pct)
    return {"n_over": n_over, "max_pct": round(mx, 1),
            "excess_mw": round(excess, 1), "max_gap_pt": round(max_gap, 2)}


# ──────────────────────────────────────────────────────────────────────────
#  捏造量 — 出典のない構造をどれだけ増やしたか
# ──────────────────────────────────────────────────────────────────────────
def fabrication_stats(pf, net, sinfo: dict) -> dict:
    """出典の無い量を数える。

    発電容量: `capacity_mw` が無く既定値で埋まったレコード（値が既定値ちょうど）。
              太陽光の既定値を下げるとここが直接減る＝**捏造を減らす修復**。
    設備:     こちらで足した変圧器（OSM にも公開系統図にも無い）。
    """
    n_def, def_mw = 0, 0.0
    by_fuel: dict[str, float] = defaultdict(float)
    for _i, r in net.gen.iterrows():
        t = r.get("type")
        d = pf._DEFAULT_CAP.get(t, pf._CAP_FALLBACK) if isinstance(t, str) else pf._CAP_FALLBACK
        if abs(float(r["max_p_mw"]) - d) < 1e-6:
            n_def += 1
            def_mw += float(r["max_p_mw"])
            by_fuel[str(t)] += float(r["max_p_mw"])
    total = float(net.gen["max_p_mw"].sum()) if len(net.gen) else 0.0
    return {"n_gen_default": n_def, "unsourced_mw": round(def_mw, 1),
            "nameplate_mw": round(total, 1),
            "unsourced_share": round(def_mw / total, 4) if total else 0.0,
            "unsourced_by_fuel": {k: round(v, 1) for k, v in
                                  sorted(by_fuel.items(), key=lambda x: -x[1])[:5]},
            "n_fab_trafo": int(sinfo.get("n_added", 0)),
            "fab_trafo_mva": float(sinfo.get("added_mva", 0.0))}


def pareto_front(rows: list[dict], objectives: list[str]) -> list[int]:
    """全目的を最小化する非劣解の添字。重み付けをしないので恣意が入らない。"""
    keep = []
    for i, a in enumerate(rows):
        dominated = False
        for j, b in enumerate(rows):
            if i == j:
                continue
            le = all(b[o] <= a[o] for o in objectives)
            lt = any(b[o] < a[o] for o in objectives)
            if le and lt:
                dominated = True
                break
        if not dominated:
            keep.append(i)
    return keep


# ──────────────────────────────────────────────────────────────────────────
#  残差の診断 — 「次に何を疑うべきか」を機械が出す（自己改善ループの環を閉じる）
# ──────────────────────────────────────────────────────────────────────────
def residual_diagnosis(net, top_n: int = 12) -> dict:
    """最良構成でなお残る過負荷が何者かを特徴づけ、次の仮説の材料を出す。"""
    if not len(net.res_line):
        return {}
    df = net.res_line.join(net.line[["in_service", "from_bus", "to_bus", "parallel", "name"]],
                           rsuffix="_l")
    df = df[df["in_service"].fillna(False)]
    lp = df["loading_percent"].dropna()
    oi = list(lp[lp > 100.0].index)
    if not oi:
        return {"n_over": 0}

    deg: dict[int, int] = defaultdict(int)
    for li in net.line.index:
        if not bool(net.line.at[li, "in_service"]):
            continue
        deg[int(net.line.at[li, "from_bus"])] += 1
        deg[int(net.line.at[li, "to_bus"])] += 1
    for ti in net.trafo.index:
        if not bool(net.trafo.at[ti, "in_service"]):
            continue
        deg[int(net.trafo.at[ti, "hv_bus"])] += 1
        deg[int(net.trafo.at[ti, "lv_bus"])] += 1

    gen_at: dict[int, float] = defaultdict(float)
    for _i, r in net.gen.iterrows():
        gen_at[int(r["bus"])] += float(r["p_mw"])
    load_at: dict[int, float] = defaultdict(float)
    for _i, r in net.load.iterrows():
        if r["in_service"]:
            load_at[int(r["bus"])] += float(r["p_mw"])

    by_kv: dict[str, int] = defaultdict(int)
    n_radial = n_single = 0
    worst = []
    for li in oi:
        fb, tb = int(df.at[li, "from_bus"]), int(df.at[li, "to_bus"])
        kv = round(float(net.bus.at[fb, "vn_kv"]), 1)
        by_kv[f"{kv:g}"] += 1
        if min(deg[fb], deg[tb]) <= 1:
            n_radial += 1
        if max(1, int(df.at[li, "parallel"] or 1)) == 1:
            n_single += 1
        worst.append({
            "loading_pct": round(float(df.at[li, "loading_percent"]), 1),
            "p_mw": round(float(df.at[li, "p_from_mw"]), 1),
            "kv": kv, "parallel": int(df.at[li, "parallel"] or 1),
            "deg_from": deg[fb], "deg_to": deg[tb],
            "gen_from_mw": round(gen_at.get(fb, 0.0), 1),
            "gen_to_mw": round(gen_at.get(tb, 0.0), 1),
            "load_from_mw": round(load_at.get(fb, 0.0), 1),
            "load_to_mw": round(load_at.get(tb, 0.0), 1),
            "name": str(df.at[li, "name"])[:60]})
    worst.sort(key=lambda x: -x["loading_pct"])
    gen_side = sum(1 for w in worst if max(w["gen_from_mw"], w["gen_to_mw"]) >
                   max(w["load_from_mw"], w["load_to_mw"]))
    return {"n_over": len(oi), "by_kv": dict(sorted(by_kv.items(),
                                                    key=lambda x: -x[1])),
            "n_radial_endpoint": n_radial, "n_single_circuit": n_single,
            "n_gen_dominated": gen_side, "n_load_dominated": len(oi) - gen_side,
            "worst": worst[:top_n]}


# ──────────────────────────────────────────────────────────────────────────
def run_config(pf, wgv, wsd, island, nodes, edges, cfg, pref_gwh,
               gen_mode: str, stepdown: bool, solar_mw: float,
               min_hops: int, radius_km: float, site_km: float, kvfit_km: float,
               keep_net: bool = False) -> dict:
    """1 構成を本番のパイプラインで通す。順序は what-if 2 本と厳密に同じ。"""
    t0 = time.time()
    saved = pf._DEFAULT_CAP.get("solar")
    pf._DEFAULT_CAP["solar"] = solar_mw
    try:
        net, bus_of, _bstats = pf.build_island_net(
            island, nodes, edges, pf.ISLAND_FREQ[island], {},
            dedup_nodes=True, site_trafos=False, deenergize_unbuilt=False)
        if gen_mode == "base":
            n = pf.attach_generators(net, bus_of, nodes, island)
            kvh: dict[float, float] = defaultdict(float)
            for _gi, gr in net.gen.iterrows():
                kvh[round(float(net.bus.at[int(gr["bus"]), "vn_kv"]), 1)] += float(gr["max_p_mw"])
            tot = sum(kvh.values()) or 1.0
            ginfo = {"n_gen": n, "n_moved": 0, "moved_mw": 0.0,
                     "kv_share": {str(k): round(v / tot, 4) for k, v in sorted(kvh.items())},
                     "share_at_or_below_110kv": round(
                         sum(v for k, v in kvh.items() if k <= 110.0) / tot, 4)}
        else:
            ginfo = wgv.attach_generators_variant(
                pf, net, bus_of, nodes, island, gen_mode,
                site_km=site_km, kvfit_km=kvfit_km)
        pf.allocate_loads(net, cfg, pref_gwh=pref_gwh)
        sinfo = {"n_added": 0, "added_mva": 0.0, "n_far_buses": 0, "far_load_mw": 0.0}
        if stepdown:
            sinfo = wsd.add_stepdowns(pf, net, min_hops, radius_km)
        fab = fabrication_stats(pf, net, sinfo)
        from src.powerflow.pipeline import add_reactive_compensation
        add_reactive_compensation(net, factor=cfg.get("reactive_compensation_factor", 0.6))
        n_comp, _ns, _nsy = pf.add_per_component_slacks(net)
        pf.balance_by_zone(net, cfg)
        net_dc, dc, _a, _b = pf.solve_island(net, max_ac_buses=0)
    finally:
        if saved is not None:
            pf._DEFAULT_CAP["solar"] = saved

    out = {"island": island, "gen": gen_mode, "sd": bool(stepdown), "solar_mw": solar_mw,
           "n_gen": ginfo.get("n_gen"), "n_moved": ginfo.get("n_moved"),
           "moved_mw": ginfo.get("moved_mw"),
           "share_le_110kv": ginfo.get("share_at_or_below_110kv"),
           "kv_share": ginfo.get("kv_share"),
           "n_trafo": int(net.trafo["in_service"].sum()), "n_components": n_comp,
           **{f"fab_{k}": v for k, v in fab.items()},
           "dc_converged": bool(dc.get("converged")),
           "overload": overload_stats(net_dc),
           "overload_power_basis": overload_stats_power(net_dc),
           "seconds": round(time.time() - t0, 1)}
    if keep_net:
        out["_net"] = net_dc
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="*", default=["hokkaido", "east", "west", "okinawa"])
    ap.add_argument("--gen-modes", nargs="*", default=GEN_MODES)
    ap.add_argument("--solar", nargs="*", type=float, default=SOLAR_LEVELS)
    ap.add_argument("--min-hops", type=int, default=3)
    ap.add_argument("--radius-km", type=float, default=10.0)
    ap.add_argument("--site-km", type=float, default=1.5)
    ap.add_argument("--kvfit-km", type=float, default=25.0)
    ap.add_argument("--tag", default="", help="出力ファイル名の接尾（島を分けて回すとき）")
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                                       text=True).stdout.strip()
    tag = f"_{args.tag}" if args.tag else ""

    pf, wgv, wsd = load_modules()
    with open(pf.BUILT, encoding="utf-8") as f:
        db = json.load(f)
    nodes, edges = db["nodes"], db["edges"]
    cfg = pf.load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(nodes)

    path = REPORTS / f"repair_search_{date}{tag}.json"
    res: list[dict] = []
    residuals: dict[str, dict] = {}
    done: set[tuple] = set()
    if path.exists():
        # 途中で殺されても失った計算をやり直さない（実際に一度失っている）
        prev = json.loads(path.read_text(encoding="utf-8"))
        res = prev.get("runs", [])
        residuals = prev.get("residual", {})
        done = {(r["island"], r["gen"], bool(r["sd"]), r["solar_mw"]) for r in res}
        print(f"[resume] {len(done)} 構成を再利用（{path.name}）", flush=True)

    def checkpoint() -> None:
        """1 構成ごとに書き出す。長時間実行が落ちても計算を捨てない。"""
        path.write_text(json.dumps(
            {"date": date, "islands": args.islands, "gen_modes": args.gen_modes,
             "solar_levels": args.solar, "min_hops": args.min_hops,
             "radius_km": args.radius_km, "runs": res, "residual": residuals,
             "complete": False}, ensure_ascii=False, indent=1), encoding="utf-8")

    for island in args.islands:
        for gen_mode in args.gen_modes:
            for sd in SD_LEVELS:
                for solar in args.solar:
                    if (island, gen_mode, sd, solar) in done:
                        continue
                    r = run_config(pf, wgv, wsd, island, nodes, edges, cfg, pref_gwh,
                                   gen_mode, sd, solar, args.min_hops, args.radius_km,
                                   args.site_km, args.kvfit_km)
                    o, o2 = r["overload"], r["overload_power_basis"]
                    print(f"[{island:9s}] gen={gen_mode:5s} sd={'on ' if sd else 'off'} "
                          f"solar={solar:5.2f}MW | 過負荷 {o['n_over']:4,}/{o['n_line']:,} "
                          f"({o['over_share']:6.2%}) 最大 {o['max_pct']:>8}% "
                          f"超過 {o['excess_mw']:>10,.0f}MW | 捏造 容量 "
                          f"{r['fab_unsourced_mw']:>9,.0f}MW 設備 {r['fab_n_fab_trafo']:4,}台 "
                          f"| 独立経路 超過 {o2['excess_mw']:>10,.0f}MW "
                          f"(乖離 {o2['max_gap_pt']}pt) {r['seconds']:.0f}s", flush=True)
                    res.append(r)
                    checkpoint()

    # 残差診断は「全構成を見た上での最良」に対して取る（resume でも同じ答えになる）
    for island in args.islands:
        rows = [r for r in res if r["island"] == island]
        if not rows or island in residuals:
            continue
        b = min(rows, key=lambda r: r["overload"]["excess_mw"])
        rr = run_config(pf, wgv, wsd, island, nodes, edges, cfg, pref_gwh,
                        b["gen"], b["sd"], b["solar_mw"], args.min_hops,
                        args.radius_km, args.site_km, args.kvfit_km, keep_net=True)
        key = f"gen={b['gen']} sd={'on' if b['sd'] else 'off'} solar={b['solar_mw']}"
        residuals[island] = {"config": key, **residual_diagnosis(rr.pop("_net"))}
        print(f"[{island:9s}] 最良 {key} → 残差診断 "
              f"{residuals[island].get('n_over')} 本", flush=True)
        checkpoint()

    # パレート境界（島ごと・3目的の最小化）
    fronts: dict[str, list[dict]] = {}
    for island in args.islands:
        rows = [r for r in res if r["island"] == island]
        flat = [{"unsourced_mw": r["fab_unsourced_mw"],
                 "n_fab_trafo": r["fab_n_fab_trafo"],
                 "excess_mw": r["overload"]["excess_mw"]} for r in rows]
        idx = pareto_front(flat, ["unsourced_mw", "n_fab_trafo", "excess_mw"])
        fronts[island] = [rows[i] for i in idx]

    out = {"date": date, "islands": args.islands, "gen_modes": args.gen_modes,
           "solar_levels": args.solar, "min_hops": args.min_hops,
           "radius_km": args.radius_km, "runs": res,
           "pareto": {k: [{"gen": r["gen"], "sd": r["sd"], "solar_mw": r["solar_mw"],
                           "unsourced_mw": r["fab_unsourced_mw"],
                           "n_fab_trafo": r["fab_n_fab_trafo"],
                           "excess_mw": r["overload"]["excess_mw"],
                           "n_over": r["overload"]["n_over"],
                           "max_pct": r["overload"]["max_pct"]} for r in v]
                      for k, v in fronts.items()},
           "residual": residuals, "complete": True}
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
