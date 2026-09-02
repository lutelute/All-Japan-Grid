#!/usr/bin/env python3
"""IBR 連系可能量 — SCR(短絡容量比)制約と熱容量制約を全地点で一度に出す(トラックC②・2026-09-02).

「どこに何MWのインバータ電源を繋げられるか」を 2 つの物差しで測る:
  1. **SCR 制約**(系統強度): 地点のテブナン短絡容量 S_sc に対し、IBR 容量 P_ibr との比
     SCR = S_sc/P_ibr が SCR_min(既定 3.0・IEEE 1204-1997 の弱系統目安)を下回らない範囲。
       P_max_scr = max(S_sc/SCR_min − 既設IBR, 0)
     S_sc は `src/powerflow/short_circuit.py`(同期機 xd'' 典型値・疎 LU・V=1pu)。
  2. **熱容量制約**(既存 `scripts/sensitivity/hosting_capacity.py` を import して再計算):
     PTDF 列ごとの 空き容量/|PTDF| の最小値。
  両者の小さい方が地点の連系可能量、どちらで決まったかを binding に記録する。

usage: PYTHONPATH=. python3 scripts/sensitivity/ibr_hosting_scr.py \\
           [--islands hokkaido west ...] [--scr-min 3] [--min-kv 66] [--no-thermal] [--no-map]
出力: docs/reports/ibr_hosting_scr_<date>.{json,md}、docs/assets/sensitivity/ibr_scr_<island>.png

限界(帳簿): 線路インピーダンスは階級別合成値・機械定数は型式別典型値(machine_agg)・
既設 IBR は OSM 容量(#25 太陽光既定 0.10MW を含む)・SCR は目安であって接続可否判断ではない。
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

REPORTS = ROOT / "docs" / "reports"
FIGS = ROOT / "docs" / "assets" / "sensitivity"
BUILT = ROOT / "docs" / "data" / "built" / "all.json"

KV_BANDS = [(60, 80, "66-77kV"), (100, 160, "110-154kV"), (180, 300, "187-275kV"), (450, 600, "500kV")]


def build_production_net(island, nodes, edges, cfg, pref_gwh):
    """本番(run_full_powerflow_from_db)と同一手順。bus_of(built ノード→バス)も返す。"""
    from scripts.run_full_powerflow_from_db import (
        GEN_ZONE_BY_OPERATOR, ISLAND_FREQ, add_per_component_slacks, allocate_loads,
        attach_default_for, attach_generators, balance_by_zone, build_island_net)
    from src.powerflow.pipeline import add_reactive_compensation
    net, bus_of, _ = build_island_net(island, nodes, edges, ISLAND_FREQ[island], {})
    attach_generators(net, bus_of, nodes, island, attach_mode=attach_default_for(island))
    allocate_loads(net, cfg, pref_gwh=pref_gwh)
    add_reactive_compensation(net, factor=cfg.get("reactive_compensation_factor", 0.6))
    add_per_component_slacks(net)
    balance_by_zone(net, cfg, use_zone_src=GEN_ZONE_BY_OPERATOR)
    return net, bus_of


def run(island: str, nodes, edges, cfg, pref_gwh, scr_min: float = 3.0,
        min_kv: float = 66.0, with_thermal: bool = True, thermal_min_kv: float = 154.0) -> dict:
    from benchmark_sensitivity import main_component_subnet
    from src.dynamics.machine_agg import aggregate_machines
    from src.powerflow.short_circuit import existing_ibr_mw, scr_hosting, short_circuit_mva

    t0 = time.perf_counter()
    net, bus_of = build_production_net(island, nodes, edges, cfg, pref_gwh)
    sub, _main = main_component_subnet(net)
    sec_build = time.perf_counter() - t0

    t0 = time.perf_counter()
    agg = aggregate_machines(sub)
    sc = short_circuit_mva(sub, agg=agg)                 # V=1pu・線路充電/負荷無視
    sec_sc = time.perf_counter() - t0
    n = len(sc.s_sc_mva)

    # 既設 IBR を ppc 行へ
    ibr = np.zeros(n)
    for lbl, mw in existing_ibr_mw(sub, agg=agg).items():
        row = sc.bus_row_of_label.get(int(lbl))
        if row is not None:
            ibr[row] += mw
    pmax_scr, scr_now = scr_hosting(sc.s_sc_mva, ibr, scr_min)

    # 行 → 地理座標・電圧・名前(built ノード)
    lat = np.full(n, np.nan); lon = np.full(n, np.nan); names = [""] * n
    kv = np.full(n, np.nan)
    bus2node = {}
    for ni, b in (bus_of.items() if isinstance(bus_of, dict) else enumerate(bus_of)):
        if b is not None and b >= 0:
            bus2node.setdefault(int(b), int(ni))
    for lbl, row in sc.bus_row_of_label.items():
        kv[row] = float(sub.bus.at[lbl, "vn_kv"])
        ni = bus2node.get(int(lbl))
        if ni is not None and not names[row]:
            lat[row] = nodes[ni]["lat"]; lon[row] = nodes[ni]["lon"]
            names[row] = str(nodes[ni].get("name") or nodes[ni].get("id") or lbl)

    # 熱容量制約(既存実装を再計算して (lat,lon,kv) で突き合わせる)
    pmax_th = np.full(n, np.nan)
    thermal_note = "skipped(--no-thermal)"
    sec_th = 0.0
    if with_thermal:
        try:
            from hosting_capacity import run as thermal_run
            t0 = time.perf_counter()
            th = thermal_run(island, nodes, edges, cfg, pref_gwh, min_kv=thermal_min_kv)
            sec_th = time.perf_counter() - t0
            key = {}
            for i in range(len(th["hc"])):
                if np.isfinite(th["lat"][i]):
                    key[(round(float(th["lat"][i]), 5), round(float(th["lon"][i]), 5),
                         round(float(th["kv"][i]), 1))] = float(th["hc"][i])
            n_match = 0
            for row in range(n):
                if np.isfinite(lat[row]):
                    v = key.get((round(float(lat[row]), 5), round(float(lon[row]), 5), round(float(kv[row]), 1)))
                    if v is not None:
                        pmax_th[row] = v; n_match += 1
            thermal_note = (f"hosting_capacity.run(min_kv={thermal_min_kv}) 再計算・{n_match}/{n} 行を座標+電圧で照合・"
                            f"基準ケース過負荷枝 {th['n_branch_over_capacity']} 本(過負荷があると熱容量側は 0 になる地点が出る)")
        except Exception as e:                          # noqa: BLE001 — 熱容量側は補助
            thermal_note = f"failed: {type(e).__name__}: {e}"

    with np.errstate(invalid="ignore"):
        both = np.isfinite(pmax_scr) & np.isfinite(pmax_th)
        pmax = np.where(both, np.minimum(pmax_scr, pmax_th), np.where(np.isfinite(pmax_scr), pmax_scr, pmax_th))
    binding = np.array(["n/a"] * n, dtype=object)
    binding[np.isfinite(pmax_scr) & ~np.isfinite(pmax_th)] = "scr(thermal n/a)"
    binding[both & (pmax_scr <= pmax_th)] = "scr"
    binding[both & (pmax_scr > pmax_th)] = "thermal"
    # 熱容量側の 0 は「基準ケースに既に過負荷枝がある」ことによる既知の退化(hosting_capacity
    # レポート参照)。地点の優劣を表さないので別カテゴリに分けて開示する。
    binding[both & (pmax_scr > pmax_th) & (pmax_th <= 0.0)] = "thermal=0(基準過負荷)"

    scope = np.isfinite(sc.s_sc_mva) & (kv >= min_kv - 0.5)
    weak = scope & (ibr > 0) & (scr_now < scr_min)
    band_stats = {}
    for lo, hi, lab in KV_BANDS:
        m = scope & (kv >= lo) & (kv <= hi)
        if m.any():
            band_stats[lab] = {"n_bus": int(m.sum()),
                               "s_sc_median_mva": float(np.nanmedian(sc.s_sc_mva[m])),
                               "s_sc_p10_mva": float(np.nanpercentile(sc.s_sc_mva[m], 10)),
                               "pmax_scr_median_mw": float(np.nanmedian(pmax_scr[m])),
                               "n_weak_scr_below_min": int(weak[m].sum())}
    rows = []
    for row in np.where(scope)[0]:
        rows.append({"bus": int(sc.label_of_row[row]), "name": names[row], "kv": float(kv[row]),
                     "lat": None if not np.isfinite(lat[row]) else round(float(lat[row]), 5),
                     "lon": None if not np.isfinite(lon[row]) else round(float(lon[row]), 5),
                     "s_sc_mva": round(float(sc.s_sc_mva[row]), 1),
                     "ibr_existing_mw": round(float(ibr[row]), 2),
                     "scr_existing": None if not np.isfinite(scr_now[row]) or np.isinf(scr_now[row]) else round(float(scr_now[row]), 2),
                     "pmax_scr_mw": round(float(pmax_scr[row]), 1),
                     "pmax_thermal_mw": None if not np.isfinite(pmax_th[row]) else round(float(pmax_th[row]), 1),
                     "pmax_mw": None if not np.isfinite(pmax[row]) else round(float(pmax[row]), 1),
                     "binding": str(binding[row])})
    weak_rows = sorted([r for r in rows if r["scr_existing"] is not None and r["scr_existing"] < scr_min],
                       key=lambda r: r["scr_existing"])
    n_conn = int(np.isfinite(sc.s_sc_mva).sum())
    return {
        "island": island, "n_bus_full": int(len(net.bus)), "n_bus_main": int(n),
        "n_bus_connected_to_source": n_conn, "n_bus_in_scope": int(scope.sum()),
        "min_kv": min_kv, "scr_min": scr_min, "base_mva": sc.base_mva,
        "n_sync_sources": sc.n_source, "sync_source_mva": round(sc.source_mva, 1),
        "ibr_existing_total_mw": round(float(ibr.sum()), 1),
        "machine_stats": agg["stats"],
        "sec_build_net": round(sec_build, 1), "sec_short_circuit_all_buses": round(sec_sc, 2),
        "sec_thermal": round(sec_th, 1), "thermal_note": thermal_note,
        "sc_note": sc.note,
        "band_stats": band_stats,
        "n_weak_scr_below_min": int(weak.sum()),
        "binding_counts": {k: int((binding[scope] == k).sum())
                           for k in ("scr", "thermal", "thermal=0(基準過負荷)", "scr(thermal n/a)", "n/a")},
        "weak_top": weak_rows[:25],
        "buses": rows,
        "_arrays": {"lat": lat, "lon": lon, "kv": kv, "s_sc": sc.s_sc_mva, "scope": scope,
                    "weak": weak, "binding": binding, "pmax": pmax, "pmax_scr": pmax_scr},
    }


def draw_map(r: dict, out_png: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = ["Hiragino Sans", "DejaVu Sans"]
    a = r["_arrays"]
    m = a["scope"] & np.isfinite(a["lat"]) & np.isfinite(a["s_sc"]) & (a["s_sc"] > 0)
    if not m.any():
        return
    fig, axes = plt.subplots(1, 2, figsize=(13, 6.8))
    ax = axes[0]
    lo, hi = np.percentile(a["s_sc"][m], [3, 97])
    sc = ax.scatter(a["lon"][m], a["lat"][m], c=np.clip(a["s_sc"][m], lo, hi),
                    s=5 + a["kv"][m] / 25, cmap="RdYlGn",
                    norm=matplotlib.colors.LogNorm(lo, hi), alpha=0.9, linewidths=0)
    w = a["weak"] & m
    if w.any():
        ax.scatter(a["lon"][w], a["lat"][w], marker="x", s=60, c="black", linewidths=1.2,
                   label=f"既設IBRで SCR<{r['scr_min']:.0f}（{int(w.sum())}地点）")
        ax.legend(loc="lower right", fontsize=9)
    plt.colorbar(sc, ax=ax, fraction=0.04, label="短絡容量 S_sc [MVA]（緑=強い / 赤=弱い）")
    ax.set_title(f"{r['island']} — テブナン短絡容量（≥{r['min_kv']:.0f}kV・{int(m.sum()):,}地点）\n"
                 f"同期機 {r['n_sync_sources']} 群 {r['sync_source_mva']:,.0f} MVA・{r['sec_short_circuit_all_buses']:.1f}s",
                 fontsize=11, fontweight="bold")
    ax.set_xlabel("経度"); ax.set_ylabel("緯度"); ax.set_aspect(1.2); ax.grid(alpha=0.25)

    ax = axes[1]
    pm = a["pmax_scr"]
    mm = m & np.isfinite(pm) & (pm > 0)
    if mm.any():
        lo2, hi2 = np.percentile(pm[mm], [3, 97])
        sc2 = ax.scatter(a["lon"][mm], a["lat"][mm], c=np.clip(pm[mm], lo2, hi2),
                         s=5 + a["kv"][mm] / 25, cmap="viridis",
                         norm=matplotlib.colors.LogNorm(lo2, hi2), alpha=0.9, linewidths=0)
        plt.colorbar(sc2, ax=ax, fraction=0.04, label=f"P_max_scr [MW]（S_sc/{r['scr_min']:.0f} − 既設IBR）")
    z = m & np.isfinite(pm) & (pm <= 0)
    if z.any():
        ax.scatter(a["lon"][z], a["lat"][z], marker="x", s=40, c="red", linewidths=1.0,
                   label=f"既設IBRで枠なし（{int(z.sum())}）")
        ax.legend(loc="lower right", fontsize=9)
    ax.set_title(f"{r['island']} — SCR 制約の連系可能量（SCR_min={r['scr_min']:.1f}）\n"
                 f"熱容量側は基準過負荷で 0 が多く地図にしない（表を参照）",
                 fontsize=11, fontweight="bold")
    ax.set_xlabel("経度"); ax.set_aspect(1.2); ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_png, dpi=125)
    plt.close(fig)


def write_report(res: list[dict], date: str, validation: dict | None) -> None:
    payload = [{k: v for k, v in r.items() if k != "_arrays"} for r in res]
    json.dump({"date": date, "validation": validation, "islands": payload},
              open(REPORTS / f"ibr_hosting_scr_{date}.json", "w"), ensure_ascii=False, indent=1)
    L = [f"# IBR 連系可能量 — SCR（系統強度）と熱容量の 2 物差し（{date}）", "",
         "インバータ電源(IBR)を繋ぐとき、送電線が埋まる前に**系統が弱くて制御が不安定になる**地点がある。",
         "その目安が SCR = 短絡容量 S_sc / IBR 容量（IEEE 1204-1997: SCR<3 で弱系統）。",
         "S_sc はテブナン等価 `S_sc = baseMVA·V²/|Z_th|`（`src/powerflow/short_circuit.py`・V=1pu・",
         "線路充電と負荷は無視・同期機は xd'' 典型値を機械ベース→系統ベース換算、IBR と合成 slack は電流源にしない）。",
         "", "| 島 | 主成分バス | 電源到達 | 同期機群 / MVA | 既設IBR [MW] | S_sc 算出 | 熱容量側 | SCR<3 の既設地点 |",
         "|---|---:|---:|---:|---:|---:|---|---:|"]
    for r in res:
        L.append(f"| {r['island']} | {r['n_bus_main']:,} | {r['n_bus_connected_to_source']:,} | "
                 f"{r['n_sync_sources']} / {r['sync_source_mva']:,.0f} | {r['ibr_existing_total_mw']:,.0f} | "
                 f"**{r['sec_short_circuit_all_buses']:.1f} s** | {r['sec_thermal']:.0f} s | {r['n_weak_scr_below_min']} |")
    L += ["", "## 電圧帯別の系統強度と SCR 連系可能量（主成分・≥min_kv）", "",
          "| 島 | 帯 | 地点 | S_sc 中央値 | S_sc 下位10% | P_max_scr 中央値 | SCR<3 既設 |", "|---|---|---:|---:|---:|---:|---:|"]
    for r in res:
        for lab, b in r["band_stats"].items():
            L.append(f"| {r['island']} | {lab} | {b['n_bus']:,} | {b['s_sc_median_mva']:,.0f} MVA | "
                     f"{b['s_sc_p10_mva']:,.0f} MVA | {b['pmax_scr_median_mw']:,.0f} MW | {b['n_weak_scr_below_min']} |")
    L += ["", "## binding — 連系可能量を決めた制約", "",
          "熱容量側(`hosting_capacity`)は**基準ケースに過負荷枝があると 0 になる**(既知の退化)。",
          "その地点は `thermal=0(基準過負荷)` に分けた — 地点の優劣ではなく容量データの噛み合わせ問題の印。",
          "", "| 島 | scr | thermal(>0) | thermal=0(基準過負荷) | scr(熱容量側 n/a) | n/a | 熱容量側の注記 |",
          "|---|---:|---:|---:|---:|---:|---|"]
    for r in res:
        b = r["binding_counts"]
        L.append(f"| {r['island']} | {b['scr']:,} | {b['thermal']:,} | {b.get('thermal=0(基準過負荷)', 0):,} | "
                 f"{b['scr(thermal n/a)']:,} | {b['n/a']:,} | {r['thermal_note']} |")
    L += ["", "## 既設 IBR の SCR が低い地点（弱系統の候補・SCR_min 以上でも上位を開示）", "",
          "既設 IBR は OSM 由来容量(FIT 全量ではない)なので SCR は**大きめ**に出る。桁外れの既設容量は",
          "OSM の容量タグ誤りの可能性があり、独立検証してから引用すること。", ""]
    for r in res:
        ex = sorted([b for b in r["buses"] if b.get("scr_existing") is not None], key=lambda b: b["scr_existing"])[:8]
        L += [f"### {r['island']}", ""]
        if not ex:
            L += ["既設 IBR なし", ""]
            continue
        L += ["| バス | 名前 | kV | S_sc [MVA] | 既設IBR [MW] | SCR | P_max_scr [MW] |", "|---:|---|---:|---:|---:|---:|---:|"]
        for w in ex:
            L.append(f"| {w['bus']} | {w['name'][:28]} | {w['kv']:.0f} | {w['s_sc_mva']:,.0f} | {w['ibr_existing_mw']:,.1f} | "
                     f"{w['scr_existing']:.2f} | {w['pmax_scr_mw']:,.0f} |")
        L.append("")
    L += ["", "## 弱系統 — 既設 IBR で SCR が SCR_min を割る地点（島別上位）", ""]
    for r in res:
        L += [f"### {r['island']}（{r['n_weak_scr_below_min']} 地点）", ""]
        if not r["weak_top"]:
            L += ["該当なし", ""]
            continue
        L += ["| バス | 名前 | kV | S_sc [MVA] | 既設IBR [MW] | SCR | P_max_scr [MW] | 熱容量側 [MW] |", "|---:|---|---:|---:|---:|---:|---:|---:|"]
        for w in r["weak_top"][:15]:
            th = "—" if w["pmax_thermal_mw"] is None else f"{w['pmax_thermal_mw']:,.0f}"
            L.append(f"| {w['bus']} | {w['name'][:28]} | {w['kv']:.0f} | {w['s_sc_mva']:,.0f} | {w['ibr_existing_mw']:,.1f} | "
                     f"**{w['scr_existing']:.2f}** | {w['pmax_scr_mw']:,.0f} | {th} |")
        L.append("")
    L += ["## 桁外れの既設 IBR（≥1,000 MW/バス）— 引用禁止・上流の容量出典の誤同定", "",
          "IBR 型(solar/wind/battery)の OSM 地物に、火力・原子力の**出典付き容量**(`capacity_mw_sourced`)が",
          "同定されている例がある(例: 高浜原子力 3,392MW が群馬の太陽光 8 地物に、姫路第二 4,119MW・松浦火力 2,000MW が",
          "近傍の太陽光地物に)。座標キー同定の誤りであり、これらの地点の SCR/P_max_scr は**使わない**こと。",
          "修正は `apply_capacity_sources.py` / `sourced_capacity_index` 側(容量出典トラック)の仕事。", ""]
    any_big = False
    for r in res:
        big = sorted([b for b in r["buses"] if b["ibr_existing_mw"] >= 1000.0], key=lambda b: -b["ibr_existing_mw"])
        if big:
            any_big = True
            L += [f"| {r['island']}: バス | 名前 | kV | 既設IBR [MW] | S_sc [MVA] | SCR |", "|---:|---|---:|---:|---:|---:|"]
            for w in big:
                L.append(f"| {w['bus']} | {w['name'][:28]} | {w['kv']:.0f} | {w['ibr_existing_mw']:,.0f} | {w['s_sc_mva']:,.0f} | "
                         f"{'—' if w['scr_existing'] is None else f'{w['scr_existing']:.2f}'} |")
            L.append("")
    if not any_big:
        L += ["該当なし", ""]
    for r in res:
        L.append(f"![{r['island']}](../assets/sensitivity/ibr_scr_{r['island']}.png)")
    L += ["", "## 検証", ""]
    if validation:
        for k, v in validation.items():
            L.append(f"- {k}: {v}")
    L += ["", "## 前提と限界", "",
          "- 三相対称短絡・V=1.0pu（IEC 60909 の電圧係数 c は掛けていない。calc_sc の skss と比べるときは ×1.1）",
          "- 線路インピーダンスは電圧階級別の合成値、機械定数は型式別典型値（`src/dynamics/machine_agg.TYPE_PARAMS`）",
          "- 既設 IBR は OSM 由来容量（介入#25 の太陽光既定 0.10MW を含む）。FIT 実配置の全量ではない",
          "- IBR 自身の短絡電流寄与（定格の 1.0〜1.2 倍程度）は無視＝保守側。合成 slack も電流源にしない",
          "- 対象は各島の最大連結成分。孤立断片上の地点は算出対象外",
          "- **SCR は目安であって接続可否判断ではない**。候補地の絞り込みに使い、確定は系統側の実データで",
          "", "---", "生成: `scripts/sensitivity/ibr_hosting_scr.py`", ""]
    (REPORTS / f"ibr_hosting_scr_{date}.md").write_text("\n".join(L), encoding="utf-8")


def validate() -> dict:
    """calc_sc(pandapower.shortcircuit)との突合。ext_grid 等価化で c=1.1 を揃える。"""
    import copy
    import pandapower as pp
    import pandapower.networks as pn
    from pandapower.shortcircuit import calc_sc
    from src.dynamics.machine_agg import aggregate_machines
    from src.powerflow.short_circuit import short_circuit_mva
    out = {}
    c9 = pn.case9()
    agg = aggregate_machines(c9)
    ref_net = copy.deepcopy(c9)
    ref_net.ext_grid = ref_net.ext_grid.iloc[0:0]
    ref_net.gen = ref_net.gen.iloc[0:0]
    for m in agg["sync"]:
        pp.create_ext_grid(ref_net, int(m["bus"]), s_sc_max_mva=1.1 * m["S_mva"] / m["xd2"], rx_max=0.0)
    calc_sc(ref_net, fault="3ph", case="max", ip=False, ith=False)
    ref = ref_net.res_bus_sc["skss_mw"].to_numpy()
    r = short_circuit_mva(c9)
    mine = np.array([r.s_sc_mva[r.bus_row_of_label[b]] for b in c9.bus.index])
    out["case9_vs_calc_sc_relerr_max"] = float(np.abs(mine * 1.1 / ref - 1).max())
    r2 = short_circuit_mva(c9, include_shunts=True)
    mine2 = np.array([r2.s_sc_mva[r2.bus_row_of_label[b]] for b in c9.bus.index])
    out["case9_with_line_charging_relerr_max"] = float(np.abs(mine2 * 1.1 / ref - 1).max())
    out["note"] = ("case9 の同期機を等価 ext_grid(s_sc=c·S/xd'')に置換した calc_sc(IEC 60909, c=1.1)と "
                   "線路充電無視で一致(相対誤差<1e-12)。線路充電を含めると最大 ~12% ずれる=IEC 60909 が "
                   "充電容量を無視する前提の再確認")
    return out


def arrays_from_buses(r: dict) -> dict:
    """JSON の buses 行から地図用配列を復元する(--from-json 用)。"""
    b = r["buses"]
    lat = np.array([np.nan if x["lat"] is None else x["lat"] for x in b], dtype=float)
    lon = np.array([np.nan if x["lon"] is None else x["lon"] for x in b], dtype=float)
    kv = np.array([x["kv"] for x in b], dtype=float)
    s_sc = np.array([x["s_sc_mva"] for x in b], dtype=float)
    pmax_scr = np.array([x["pmax_scr_mw"] for x in b], dtype=float)
    pmax = np.array([np.nan if x["pmax_mw"] is None else x["pmax_mw"] for x in b], dtype=float)
    scr = np.array([np.inf if x["scr_existing"] is None else x["scr_existing"] for x in b], dtype=float)
    ibr = np.array([x["ibr_existing_mw"] for x in b], dtype=float)
    weak = (ibr > 0) & (scr < r["scr_min"])
    binding = np.array([x["binding"] for x in b], dtype=object)
    return {"lat": lat, "lon": lon, "kv": kv, "s_sc": s_sc, "scope": np.ones(len(b), dtype=bool),
            "weak": weak, "binding": binding, "pmax": pmax, "pmax_scr": pmax_scr}


def main() -> None:
    from scripts.run_full_powerflow_from_db import ISLAND_FREQ, load_demand_config
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-json", default=None,
                    help="既存の結果 JSON から MD と地図だけ再生成する(再計算なし)")
    ap.add_argument("--islands", nargs="*", default=None)
    ap.add_argument("--scr-min", type=float, default=3.0)
    ap.add_argument("--min-kv", type=float, default=66.0, help="レポート対象バスの下限電圧")
    ap.add_argument("--thermal-min-kv", type=float, default=154.0,
                    help="熱容量側で制約に取る枝の下限電圧(hosting_capacity と同じ既定 154kV)")
    ap.add_argument("--no-thermal", action="store_true")
    ap.add_argument("--no-map", action="store_true")
    ap.add_argument("--no-validate", action="store_true")
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True, text=True).stdout.strip()
    FIGS.mkdir(parents=True, exist_ok=True)

    if args.from_json:
        prev = json.load(open(args.from_json, encoding="utf-8"))
        res = []
        for r in prev["islands"]:
            b = r.get("binding_counts", {})
            if "thermal=0(基準過負荷)" not in b:      # 旧 JSON: buses 行から再分類
                z = sum(1 for x in r["buses"] if x["binding"] == "thermal" and (x["pmax_thermal_mw"] or 0) <= 0)
                for x in r["buses"]:
                    if x["binding"] == "thermal" and (x["pmax_thermal_mw"] or 0) <= 0:
                        x["binding"] = "thermal=0(基準過負荷)"
                b["thermal"] = b.get("thermal", 0) - z
                b["thermal=0(基準過負荷)"] = z
            r["_arrays"] = arrays_from_buses(r)
            if not args.no_map:
                draw_map(r, FIGS / f"ibr_scr_{r['island']}.png")
            res.append(r)
        write_report(res, prev.get("date", date), prev.get("validation"))
        print(f"→ 再生成: docs/reports/ibr_hosting_scr_{prev.get('date', date)}.md / .json")
        return

    d = json.load(open(BUILT))
    nodes, edges = d["nodes"], d["edges"]
    cfg = load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(nodes)

    validation = None if args.no_validate else validate()
    res = []
    for isl in (args.islands or list(ISLAND_FREQ.keys())):
        r = run(isl, nodes, edges, cfg, pref_gwh, scr_min=args.scr_min, min_kv=args.min_kv,
                with_thermal=not args.no_thermal, thermal_min_kv=args.thermal_min_kv)
        if not args.no_map:
            draw_map(r, FIGS / f"ibr_scr_{isl}.png")
        res.append(r)
        b = r["binding_counts"]
        print(f"[{isl:9s}] main {r['n_bus_main']:,} / 到達 {r['n_bus_connected_to_source']:,} | "
              f"同期機 {r['n_sync_sources']}群 {r['sync_source_mva']:,.0f}MVA・既設IBR {r['ibr_existing_total_mw']:,.0f}MW | "
              f"S_sc {r['sec_short_circuit_all_buses']:.1f}s | SCR<{args.scr_min:.0f} 既設 {r['n_weak_scr_below_min']} | "
              f"binding scr {b['scr']} / thermal {b['thermal']} / scr(n/a) {b['scr(thermal n/a)']} | {r['thermal_note'][:60]}")
    write_report(res, date, validation)
    print(f"→ docs/reports/ibr_hosting_scr_{date}.md / .json")


if __name__ == "__main__":
    main()
