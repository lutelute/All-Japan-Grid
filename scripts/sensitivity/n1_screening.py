#!/usr/bin/env python3
"""N-1 全枝スクリーニング — 全枝を順に開放したときの過負荷を LODF で一括評価する。

枝 k を開放したとき枝 j の潮流は f_j + LODF[j,k]·f_k（直流近似）で閉じているので、
全枝分の「開放後の最大負荷率・過負荷本数・最悪被害枝」が行列 1 枚の列演算で出る
（`src/powerflow/contingency.py`）。並列回線は 1 回線開放（残回線の容量で評価）。
開放で系統が分離する枝（橋）は LODF が定義できないので「分離側の負荷・発電」を別勘定にする。

**合成定格の錯視を主結果に混ぜない**: 監視枝を「実在線（OSM 実線形・回収線・公表接続）
＋銘板つき変圧器」に限った順位を主表にし、同一敷地タイ（同定）・発電所取付線・
ヒューリスティック容量の変圧器・(仮)給電変圧器など**合成定格の要素が最悪枝になる開放**は
別表で開示する（北海道 318% の教訓: 68.6MVA 定格の 255m 同定タイが最悪線だった）。

usage:
  PYTHONPATH=. python3 scripts/sensitivity/n1_screening.py --islands hokkaido okinawa --ac-verify 5
  PYTHONPATH=. python3 scripts/sensitivity/n1_screening.py --islands east west --ac-verify 5
出力: docs/reports/n1_screening_<date>.{json,md}, docs/assets/sensitivity/n1_<island>_<date>.png
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(ROOT)

import numpy as np
import pandapower as pp
from pandapower.pypower.makePTDF import makePTDF

from benchmark_sensitivity import main_component_subnet, production_net
from scripts.run_full_powerflow_from_db import (ISLAND_FREQ, _bus_lonlat, _k5,
                                                load_demand_config, solve_island)
from src.powerflow import contingency as cg

REPORTS = ROOT / "docs" / "reports"
FIGS = ROOT / "docs" / "assets" / "sensitivity"
BUILT = ROOT / "docs" / "data" / "built" / "all.json"

# 実在線とみなす要素クラス（監視の主集合）。それ以外は合成定格＝別表。
PHYSICAL_CLASSES = ("osm_line", "osm_recovered", "disclosure_edge", "trafo_nameplate")
CLASS_LABEL = {
    "osm_line": "OSM実線", "osm_recovered": "OSM実線(回収)", "disclosure_edge": "公表接続(直線)",
    "trafo_nameplate": "変圧器(銘板)", "trafo_heuristic": "変圧器(推定容量)",
    "provisional_infeed": "(仮)給電変圧器#37", "same_site_tie": "同一敷地タイ(同定)",
    "disclosure_stub": "公表接続の取付スタブ", "leadin": "発電所取付線", "intra_sub_stub": "所内スタブ",
    "synthetic_tie": "合成連系タイ", "unknown": "不明",
}


# ── 要素の分類（built のエッジ属性を座標キーで引き戻す） ─────────────────
def edge_lookup(edges):
    lk = {}
    for e in edges:
        ka, kb = _k5(*e["a"]), _k5(*e["b"])
        lk.setdefault((ka, kb), []).append(e)
        lk.setdefault((kb, ka), []).append(e)
    return lk


def _edge_of(sub, li, lk):
    fa, ta = int(sub.line.at[li, "from_bus"]), int(sub.line.at[li, "to_bus"])
    lo1, la1 = _bus_lonlat(sub, fa)
    lo2, la2 = _bus_lonlat(sub, ta)
    if la1 is None or la2 is None:
        return None
    cands = lk.get((_k5(la1, lo1), _k5(la2, lo2)))
    if not cands:
        return None
    nm = str(sub.line.at[li, "name"])
    for e in cands:
        if str(e.get("name") or "") == nm:
            return e
    return cands[0]


def classify(sub, tbl, eid, lk) -> str:
    if tbl == "trafo":
        nm = str(sub.trafo.at[eid, "name"])
        if "(仮)" in nm:
            return "provisional_infeed"
        return "trafo_nameplate" if "@nameplate" in nm else "trafo_heuristic"
    if tbl != "line":
        return "unknown"
    nm = str(sub.line.at[eid, "name"])
    e = _edge_of(sub, eid, lk) or {}
    if e.get("same_site") or "同定" in nm:
        return "same_site_tie"
    if e.get("stub") or "〔取付〕" in nm:
        return "disclosure_stub"
    if e.get("tie") or e.get("dc_tie") or e.get("dc"):
        return "synthetic_tie"
    if nm == "leadin":
        return "leadin"
    if "intra-substation" in nm:
        return "intra_sub_stub"
    if e.get("recovery"):
        return "osm_recovered"
    if e.get("disclosure"):
        return "disclosure_edge"
    return "osm_line"


def _elem_row(sub, tbl, eid, k, cls, kv, par, f0, cap, base_loading):
    tab = getattr(sub, tbl)
    nm = str(tab.at[eid, "name"])
    if tbl == "line":
        a, b = int(tab.at[eid, "from_bus"]), int(tab.at[eid, "to_bus"])
    else:
        a, b = int(tab.at[eid, "hv_bus"]), int(tab.at[eid, "lv_bus"])
    return {
        "ppc_idx": int(k), "table": tbl, "elem": int(eid), "name": nm,
        "elem_class": cls, "class_label": CLASS_LABEL.get(cls, cls),
        "kv": round(float(kv), 1), "parallel": int(par),
        "from": str(sub.bus.at[a, "name"]), "to": str(sub.bus.at[b, "name"]),
        "f0_mw": round(float(f0), 1),
        "cap_mw": (round(float(cap), 1) if np.isfinite(cap) else None),
        "base_loading_pct": (round(float(base_loading), 1) if np.isfinite(base_loading) else None),
    }


def _ac_loading_map(net_ac, elems, cap, mon):
    """AC 解の |P| / 容量 [%]（監視枝のみ・prune で落ちた枝は nan）。"""
    L = np.full(len(elems), np.nan)
    for k, (tbl, eid) in enumerate(elems):
        if not mon[k] or tbl is None:
            continue
        if tbl == "line":
            res, col = net_ac.res_line, "p_from_mw"
        elif tbl == "trafo":
            res, col = net_ac.res_trafo, "p_hv_mw"
        else:
            continue
        if eid in res.index and np.isfinite(cap[k]) and cap[k] > 0:
            v = res.at[eid, col]
            L[k] = abs(float(v)) / cap[k] * 100.0 if np.isfinite(v) else np.nan
    return L


def run(island, nodes, edges, cfg, pref_gwh, args) -> dict:
    t_all = time.perf_counter()
    net = production_net(island, nodes, edges, cfg, pref_gwh)
    sub, _main = main_component_subnet(net)
    pp.rundcpp(sub)
    ppc = sub._ppc
    ref = int(sub._pd2ppc_lookups["bus"][int(sub.ext_grid.bus.iloc[0])])
    t0 = time.perf_counter()
    ptdf = makePTDF(ppc["baseMVA"], ppc["bus"], ppc["branch"], slack=ref)
    sec_ptdf = time.perf_counter() - t0

    nl = ptdf.shape[0]
    f0 = cg.ppc_flows_mw(ppc)
    cap = cg.branch_capacity_mw(sub, nl, args.cap_factor)
    par = cg.branch_parallel(sub, nl)
    kv = cg.branch_kv(ppc)
    elems = cg.branch_elements(sub)
    status = ppc["branch"][:, cg.BR_STATUS].real.astype(float) > 0
    lk = edge_lookup(edges)
    cls = np.array([classify(sub, t, e, lk) if t else "unknown" for t, e in elems])
    physical = np.isin(cls, PHYSICAL_CLASSES)
    # 監視の下限電圧: 島の最高階級が下限に届かない(沖縄=132kV)ときは最高階級に落とす
    min_kv = float(args.min_kv)
    if not ((kv >= min_kv - 0.5) & status).any():
        min_kv = float(np.max(kv[status]))
        print(f"  監視下限 {args.min_kv:.0f}kV に届く枝が無いため {min_kv:.0f}kV に下げた")
    in_scope = (kv >= min_kv - 0.5) & status
    mon_phys = in_scope & physical
    mon_all = in_scope

    res_p = cg.screen(ptdf, ppc["branch"], f0, cap, par, monitor=mon_phys,
                      single_circuit=not args.no_single_circuit)
    res_a = cg.screen(ptdf, ppc["branch"], f0, cap, par, monitor=mon_all,
                      single_circuit=not args.no_single_circuit)

    # 分離（橋）
    load, gen = cg.bus_load_gen_mw(ppc)
    side = cg.islanded_side(ppc["branch"], len(ppc["bus"]), ref, res_p.islanding, load, gen)
    isl_rows = []
    for k, s in side.items():
        tbl, eid = elems[k]
        if tbl is None:
            continue
        row = _elem_row(sub, tbl, eid, k, cls[k], kv[k], par[k], f0[k], cap[k], res_p.base_loading[k])
        row.update({"isolated_n_bus": s["n_bus"], "isolated_load_mw": round(s["load_mw"], 1),
                    "isolated_gen_mw": round(s["gen_mw"], 1)})
        isl_rows.append(row)
    isl_rows.sort(key=lambda r: -r["isolated_load_mw"])
    n_pseudo = int(res_p.islanding.sum() - len(side))

    def rank_rows(res, top, worst_filter=None):
        rows = []
        for k in res.ranking(top=nl):
            j = int(res.post_worst_new[k])          # 基準で過負荷でない枝の中の最悪
            if worst_filter is not None and (j < 0 or not worst_filter(j)):
                continue
            tbl, eid = elems[k]
            if tbl is None:
                continue
            row = _elem_row(sub, tbl, eid, k, cls[k], kv[k], par[k], f0[k], cap[k], res.base_loading[k])
            jo = int(res.post_worst[k])
            row.update({
                "post_max_loading_pct": round(float(res.post_max_loading[k]), 1),
                "post_max_new_loading_pct": round(float(res.post_max_new[k]), 1),
                "post_max_delta_pt": round(float(res.post_max_delta[k]), 1),
                "post_n_over": int(res.post_n_over[k]),
                "post_n_new_over": int(res.post_n_new_over[k]),
                "worst": (_elem_row(sub, elems[j][0], elems[j][1], j, cls[j], kv[j], par[j],
                                    f0[j], cap[j], res.base_loading[j]) if j >= 0 else None),
                "worst_incl_base": (_elem_row(sub, elems[jo][0], elems[jo][1], jo, cls[jo], kv[jo],
                                              par[jo], f0[jo], cap[jo], res.base_loading[jo])
                                    if jo >= 0 else None),
            })
            rows.append(row)
            if len(rows) >= top:
                break
        return rows

    top_phys = rank_rows(res_p, args.top)
    # 別表: 全枝監視での順位のうち、最悪枝が合成定格の要素になる開放
    top_synth = rank_rows(res_a, args.top, worst_filter=lambda j: not physical[j])

    # ── AC 検証（上位 K 件・本番の solve_island で開放して解き直す） ─────────
    ac_rows = []
    if args.ac_verify > 0 and top_phys:
        _, _, net_ac0, ac0 = solve_island(net, max_ac_buses=10**9)
        base_ac = None
        if ac0.get("converged") and net_ac0 is not None:
            base_ac = _ac_loading_map(net_ac0, elems, cap, mon_phys)
        not_base = mon_phys & ~res_p.base_over
        for row in top_phys[: args.ac_verify]:
            tbl, eid, k = row["table"], row["elem"], row["ppc_idx"]
            tab = getattr(net, tbl)
            single = (not args.no_single_circuit) and int(par[k]) >= 2
            cap_ac = cap.copy()
            if single:
                # 1 回線開放 = parallel を 1 減らして解き直す（残回線の容量で見る）
                tab.at[eid, "parallel"] = int(par[k]) - 1
                cap_ac[k] = cap[k] * (par[k] - 1) / par[k]
            else:
                tab.at[eid, "in_service"] = False
            t0 = time.perf_counter()
            try:
                _, _, net_ac, ac = solve_island(net, max_ac_buses=10**9)
            finally:
                if single:
                    tab.at[eid, "parallel"] = int(par[k])
                else:
                    tab.at[eid, "in_service"] = True
            sec = time.perf_counter() - t0
            r = {"ppc_idx": k, "name": row["name"], "table": tbl, "elem": eid,
                 "outage": "single_circuit" if single else "all_circuits",
                 "dc_post_max_loading_pct": row["post_max_loading_pct"],
                 "dc_post_max_new_loading_pct": row["post_max_new_loading_pct"],
                 "dc_worst": row["worst"]["name"] if row["worst"] else None,
                 "dc_n_new_over": row["post_n_new_over"],
                 "ac_converged": bool(ac.get("converged")), "ac_served_frac": ac.get("served_frac"),
                 "ac_sec": round(sec, 1)}
            if ac.get("converged") and net_ac is not None:
                L = _ac_loading_map(net_ac, elems, cap_ac, mon_phys)
                Ln = np.where(not_base, L, np.nan)
                jm = int(np.nanargmax(Ln)) if np.isfinite(Ln).any() else -1
                r["ac_post_max_new_loading_pct"] = round(float(Ln[jm]), 1) if jm >= 0 else None
                r["ac_worst"] = str(getattr(net, elems[jm][0]).at[elems[jm][1], "name"]) if jm >= 0 else None
                r["ac_post_max_loading_pct"] = round(float(np.nanmax(L)), 1) if np.isfinite(L).any() else None
                j = row["worst"]["ppc_idx"] if row["worst"] else -1
                r["ac_loading_on_dc_worst_pct"] = (round(float(L[j]), 1)
                                                   if j >= 0 and np.isfinite(L[j]) else None)
                if base_ac is not None and j >= 0 and np.isfinite(base_ac[j]):
                    r["ac_base_loading_on_dc_worst_pct"] = round(float(base_ac[j]), 1)
                r["ac_n_new_over"] = int(np.nansum(Ln > cg.OVER_PCT))
                r["ac_n_over_physical"] = int(np.nansum(L > cg.OVER_PCT))
            ac_rows.append(r)
            print(f"    AC検証 {row['name'][:24]:24s} [{r['outage']}]: DC新規側 {row['post_max_new_loading_pct']:7.1f}% "
                  f"(新規{row['post_n_new_over']}) → AC {'conv' if r['ac_converged'] else 'FAIL'} "
                  f"{r.get('ac_post_max_new_loading_pct', '—')}% (新規{r.get('ac_n_new_over', '—')}) ({sec:.0f}s)")

    # ── 集計 ──────────────────────────────────────────────────────────
    ok = res_p.outage_ok & np.isfinite(res_p.post_max_loading)
    cls_count = {c: int((cls == c).sum()) for c in sorted(set(cls))}
    out = {
        "island": island, "n_bus": int(len(sub.bus)), "n_bus_full": int(len(net.bus)),
        "n_branch": int(nl), "n_in_service": int(status.sum()),
        "n_outage_evaluated": int(ok.sum()), "n_islanding": int(res_p.islanding.sum()),
        "n_islanding_pseudo": n_pseudo, "single_circuit": not args.no_single_circuit,
        "min_kv": min_kv, "min_kv_requested": args.min_kv, "capacity_factor": args.cap_factor,
        "n_monitor_physical": int(mon_phys.sum()), "n_monitor_all": int(mon_all.sum()),
        "base_n_over_physical": int(res_p.base_over.sum()), "base_n_over_all": int(res_a.base_over.sum()),
        "base_max_loading_physical_pct": round(float(np.nanmax(np.where(mon_phys, res_p.base_loading, 0))), 1),
        "n_outage_causing_new_over_physical": int((ok & (res_p.post_n_new_over > 0)).sum()),
        "n_outage_causing_new_over_all": int((ok & (res_a.post_n_new_over > 0)).sum()),
        "n_outage_new_over_120_physical": int((ok & (res_p.post_max_new > 120)).sum()),
        "n_outage_new_over_120_all": int((ok & (res_a.post_max_new > 120)).sum()),
        "max_new_loading_physical_pct": round(float(np.nanmax(res_p.post_max_new[ok])), 1) if ok.any() else None,
        "elem_class_counts": cls_count,
        "sec_build_ptdf": round(sec_ptdf, 2), "sec_screen_physical": round(res_p.sec, 2),
        "sec_screen_all": round(res_a.sec, 2), "sec_total": round(time.perf_counter() - t_all, 1),
        "top_physical": top_phys, "top_synthetic_worst": top_synth,
        "islanding_top": isl_rows[: args.top],
        "islanding_total_load_mw": round(sum(r["isolated_load_mw"] for r in isl_rows), 1),
        "islanding_n_over_100mw": int(sum(1 for r in isl_rows if r["isolated_load_mw"] >= 100)),
        "ac_verify": ac_rows,
        "_plot": {"sub": sub, "elems": elems, "top": top_phys, "isl": isl_rows[:10]},
    }
    print(f"[{island:9s}] 主成分 {out['n_bus']:,}バス {nl:,}枝 | PTDF {sec_ptdf:.1f}s "
          f"screen {res_p.sec:.1f}s×2 | 評価 {out['n_outage_evaluated']:,} 橋 {out['n_islanding']:,} "
          f"| 基準過負荷(実在≥{min_kv:.0f}kV) {out['base_n_over_physical']} "
          f"| 新規過負荷を生む開放 実在 {out['n_outage_causing_new_over_physical']} / 全 {out['n_outage_causing_new_over_all']} "
          f"| 分離負荷≥100MW {out['islanding_n_over_100mw']}")
    return out


def draw_map(r, date, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    plt.rcParams["font.family"] = ["Hiragino Sans", "DejaVu Sans"]
    sub, elems = r["_plot"]["sub"], r["_plot"]["elems"]

    def seg(tbl, eid):
        tab = getattr(sub, tbl)
        a, b = ((int(tab.at[eid, "from_bus"]), int(tab.at[eid, "to_bus"])) if tbl == "line"
                else (int(tab.at[eid, "hv_bus"]), int(tab.at[eid, "lv_bus"])))
        p, q = _bus_lonlat(sub, a), _bus_lonlat(sub, b)
        return None if p[0] is None or q[0] is None else [p, q]

    base = [s for s in (seg(t, e) for t, e in elems if t) if s]
    fig, ax = plt.subplots(figsize=(7.5, 7.5))
    ax.add_collection(LineCollection(base, colors="#c8c8c8", linewidths=0.4, zorder=1))
    worst = [s for s in (seg(w["worst"]["table"], w["worst"]["elem"]) for w in r["_plot"]["top"] if w["worst"]) if s]
    ax.add_collection(LineCollection(worst, colors="#ff9f1c", linewidths=2.2, zorder=3, label="最悪の新規被害枝"))
    outs = [s for s in (seg(w["table"], w["elem"]) for w in r["_plot"]["top"]) if s]
    ax.add_collection(LineCollection(outs, colors="#d62828", linewidths=2.6, zorder=4, label="開放で新たに過負荷を生む枝(上位)"))
    isl = [s for s in (seg(w["table"], w["elem"]) for w in r["_plot"]["isl"]) if s]
    if isl:
        ax.add_collection(LineCollection(isl, colors="#6a4c93", linewidths=2.0, linestyles="--", zorder=2,
                                         label="開放で分離(分離負荷 上位10)"))
    xs = [p[0] for s in base for p in s]; ys = [p[1] for s in base for p in s]
    ax.set_xlim(min(xs) - 0.1, max(xs) + 0.1); ax.set_ylim(min(ys) - 0.1, max(ys) + 0.1)
    ax.set_aspect(1.2); ax.grid(alpha=0.25)
    ax.set_title(f"{r['island']} — N-1 全枝スクリーニング（{date}）\n"
                 f"{r['n_outage_evaluated']:,}枝を {r['sec_screen_physical']:.1f}s で一括評価・"
                 f"新たに過負荷を生む開放 {r['n_outage_causing_new_over_physical']} 本（実在線監視・≥{r['min_kv']:.0f}kV）",
                 fontsize=11, fontweight="bold")
    ax.set_xlabel("経度"); ax.set_ylabel("緯度")
    ax.legend(loc="lower right", fontsize=8.5)
    fig.tight_layout(); fig.savefig(path, dpi=125); plt.close(fig)


def _tbl(rows, kind="post"):
    if not rows:
        return ["（該当なし）"]
    if kind == "post":
        L = ["| # | 開放する枝 | 種別 | kV | 回線 | 開放枝の基準負荷率 | 新規過負荷 本数 | 新規側の最大負荷率 | 最大増分 | 最悪の新規被害枝 (種別・基準→開放後) |",
             "|---:|---|---|---:|---:|---:|---:|---:|---:|---|"]
        for i, r in enumerate(rows, 1):
            w = r["worst"]
            wtxt = "—"
            if w:
                wtxt = (f"{w['name']} ({w['class_label']}, {w['kv']:.0f}kV, "
                        f"{w['base_loading_pct'] if w['base_loading_pct'] is not None else '—'}→"
                        f"{r['post_max_new_loading_pct']:.0f}%)")
            L.append(f"| {i} | {r['name']} | {r['class_label']} | {r['kv']:.0f} | {r['parallel']} | "
                     f"{r['base_loading_pct'] if r['base_loading_pct'] is not None else '—'}% | "
                     f"**{r['post_n_new_over']}** | **{r['post_max_new_loading_pct']:.0f}%** | "
                     f"+{r['post_max_delta_pt']:.0f}pt | {wtxt} |")
    else:
        L = ["| # | 開放する枝 | 種別 | kV | 分離バス数 | 分離側の負荷 | 分離側の発電 |",
             "|---:|---|---|---:|---:|---:|---:|"]
        for i, r in enumerate(rows, 1):
            L.append(f"| {i} | {r['name']} | {r['class_label']} | {r['kv']:.0f} | {r['isolated_n_bus']} | "
                     f"**{r['isolated_load_mw']:,.0f} MW** | {r['isolated_gen_mw']:,.0f} MW |")
    return L


def write_md(res, date, path, args):
    L = [f"# N-1 全枝スクリーニング — LODF で全枝開放を一括評価（{date}）", "",
         "枝 k を開放したときの枝 j の潮流は `f_j + LODF[j,k]·f_k`（直流近似）で閉じているので、",
         "全枝分の「開放後の最大負荷率・過負荷本数・最悪被害枝」が行列 1 枚の列演算で出る。",
         "並列回線は **1 回線開放**（残回線容量で評価）、開放で分離する枝（橋）は LODF が定義できないため",
         "**分離側の負荷・発電を別勘定**にした。", "",
         "**合成定格の錯視を主結果に混ぜない**: 主表は監視枝を「実在線（OSM実線形・回収線・公表接続）＋銘板つき変圧器」に限った順位。",
         "同一敷地タイ（同定）・発電所取付線・推定容量の変圧器などが最悪枝になる開放は別表で開示する。", "",
         "| 島 | 主成分 | 枝 | 評価した開放 | 橋(分離) | 監視枝(実在/全) | 基準過負荷(実在) | 新規過負荷を生む開放 実在/全 | 新規側 >120% (実在) | 分離負荷≥100MW | PTDF | 一括評価 |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in res:
        L.append(f"| {r['island']} | {r['n_bus']:,} | {r['n_branch']:,} | {r['n_outage_evaluated']:,} | "
                 f"{r['n_islanding']:,} | {r['n_monitor_physical']:,}/{r['n_monitor_all']:,} | "
                 f"{r['base_n_over_physical']} | **{r['n_outage_causing_new_over_physical']}** / {r['n_outage_causing_new_over_all']} | "
                 f"{r['n_outage_new_over_120_physical']} | "
                 f"{r['islanding_n_over_100mw']} | {r['sec_build_ptdf']:.1f}s | {r['sec_screen_physical']:.1f}s |")
    L += ["", f"監視は ≥{args.min_kv:.0f}kV（最高階級が届かない島はその階級: "
          + "、".join(f"{r['island']} {r['min_kv']:.0f}kV" for r in res)
          + f"）・容量係数 {args.cap_factor}（理論値 √3·V·I に対する較正。公表運用容量との比較では約 0.5）。", ""]
    for r in res:
        L += [f"## {r['island']}", "",
              f"要素の内訳: " + "、".join(f"{CLASS_LABEL.get(k, k)} {v:,}" for k, v in r["elem_class_counts"].items()), "",
              f"### 実在線監視 — 開放すると新たに過負荷を生む枝（上位 {len(r['top_physical'])}）", "",
              f"基準ケースで既に >100% の実在監視枝: {r['base_n_over_physical']} 本（最大 {r['base_max_loading_physical_pct']}%）。"
              f"基準の過負荷は開放と無関係に居座るので、指標は**基準で過負荷でない枝の側**で取る"
              f"（新規過負荷本数 → 新規側の最大負荷率）。新規側が 120% を超える開放: {r['n_outage_new_over_120_physical']:,} 本。", ""]
        L += _tbl(r["top_physical"]) + [""]
        if r["ac_verify"]:
            L += ["### AC 検証（上位を本番 solve_island で開放して解き直し）", "",
                  "| 開放する枝 | 開放 | DC 新規側最大 (新規本数) | AC | AC 新規側最大 (新規本数) | DC最悪新規枝の AC 負荷率（基準→開放後） | 秒 |",
                  "|---|---|---:|---|---:|---|---:|"]
            for a in r["ac_verify"]:
                L.append(f"| {a['name']} | {'1回線' if a['outage'] == 'single_circuit' else '全回線'} | "
                         f"{a['dc_post_max_new_loading_pct']:.0f}% ({a['dc_n_new_over']}) | "
                         f"{'収束 (給電' + str(round((a.get('ac_served_frac') or 0) * 100)) + '%)' if a['ac_converged'] else '**非収束**'} | "
                         f"{a.get('ac_post_max_new_loading_pct', '—')}% ({a.get('ac_n_new_over', '—')}) | "
                         f"{a.get('ac_base_loading_on_dc_worst_pct', '—')} → {a.get('ac_loading_on_dc_worst_pct', '—')}% | "
                         f"{a['ac_sec']} |")
            L += ["", "AC の負荷率は |P|/容量（直流の定義に揃えた）。1 回線開放は parallel を 1 減らして解き直し、"
                  "残回線の容量で評価。prune はしごで落ちた枝は比較から除外。", ""]
        L += [f"### 別表 — 合成定格の要素が最悪枝になる開放（錯視の開示・上位 {len(r['top_synthetic_worst'])}）", ""]
        L += _tbl(r["top_synthetic_worst"]) + [""]
        L += [f"### 分離（橋）— 開放で切り離される負荷の大きい枝（上位 {len(r['islanding_top'])}）", "",
              f"橋 {r['n_islanding']:,} 本（うち数値的な擬似橋 {r['n_islanding_pseudo']}）。分離側の負荷合計 {r['islanding_total_load_mw']:,.0f} MW。"
              "放射系の末端はそもそも N-1 で守れない（実系統では配電側の切替で対処）ので、ここは「モデルが放射になっている箇所」の一覧として読む。", ""]
        L += _tbl(r["islanding_top"], "isl") + [""]
        if not args.no_map:
            L += [f"![{r['island']}](../assets/sensitivity/n1_{r['island']}_{date}.png)", ""]
    L += ["## 前提と限界", "",
          "- 直流近似・熱容量のみ（無効電力・電圧・安定度・保護協調は見ない）。合成インピーダンス（電圧階級の標準定数）上の線形化",
          "- 容量は理論値（線路 √3·V·I·回線数、変圧器 sn·回線数）。公表運用容量ではない（`--cap-factor` で較正）",
          "- 対象は各島の最大連結成分。連系線・FC・非通電の合成タイ（介入#31）は開放候補に入らない",
          "- 発電機の再配分（AGC・予備力）は考慮しない＝開放直後の潮流再配分だけ",
          "- **screening であって運用可否の判定ではない**。順位で候補を絞り、確定は AC・実データ・実系統の定格で",
          "", "---", "生成: `scripts/sensitivity/n1_screening.py`", ""]
    path.write_text("\n".join(L), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--islands", nargs="*", default=None)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--ac-verify", type=int, default=0, help="上位 K 件を本番 AC で開放して解き直す")
    ap.add_argument("--cap-factor", type=float, default=1.0, help="容量係数（理論値→運用容量の較正。既定 1.0）")
    ap.add_argument("--min-kv", type=float, default=154.0, help="監視する枝の下限電圧（既定 154kV）")
    ap.add_argument("--no-single-circuit", action="store_true", help="並列回線も全回線開放として扱う")
    ap.add_argument("--date", default=None)
    ap.add_argument("--out-dir", default=None, help="レポート出力先（既定 docs/reports）")
    ap.add_argument("--no-map", action="store_true")
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True, text=True).stdout.strip()
    out_dir = Path(args.out_dir) if args.out_dir else REPORTS
    out_dir.mkdir(parents=True, exist_ok=True)
    FIGS.mkdir(parents=True, exist_ok=True)

    d = json.load(open(BUILT, encoding="utf-8"))
    nodes, edges = d["nodes"], d["edges"]
    cfg = load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(nodes)

    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    jpath = out_dir / f"n1_screening_{date}.json"
    # 島ごとに書き足す(重い島の途中で落ちても先に済んだ島の結果は残る・別実行の結果と合流できる)
    payload = []
    if jpath.exists():
        try:
            payload = json.load(open(jpath, encoding="utf-8")).get("islands", [])
        except (ValueError, OSError):
            payload = []
    order = {k: i for i, k in enumerate(ISLAND_FREQ)}
    for isl in (args.islands or list(ISLAND_FREQ.keys())):
        r = run(isl, nodes, edges, cfg, pref_gwh, args)
        if not args.no_map:
            draw_map(r, date, FIGS / f"n1_{r['island']}_{date}.png")
        payload = [x for x in payload if x["island"] != isl]
        payload.append({k: v for k, v in r.items() if k != "_plot"})
        payload.sort(key=lambda x: order.get(x["island"], 99))
        json.dump({"date": date, "git_head": head, "args": vars(args), "islands": payload},
                  open(jpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        write_md(payload, date, out_dir / f"n1_screening_{date}.md", args)
    print(f"→ {out_dir / f'n1_screening_{date}.md'}")


if __name__ == "__main__":
    main()
