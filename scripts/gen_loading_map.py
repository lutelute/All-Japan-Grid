#!/usr/bin/env python3
"""ピーク断面ローディングマップPNG — 東西フル網のAC潮流で線路負荷率を地図に(2026-08-30).

オーナー要望「潮流計算ももっとやってほしい」。uc_to_pf_built と同一の正典手順
(build_island_net→attach→allocate→reactive→#37(仮)infeed→slacks→UC断面注入)で
東西それぞれのピーク時刻をACで解き、net.res_line.loading_percent を実線形
(edge path)で着色する。AC不成立時は dc_fallback と正直に表示。
変圧器(res_trafo)は地図線には出さないため、最大負荷率をHUDに併記して開示する。

出力: docs/slides/ajg/assets/loading_map_peak.png
"""
import copy, json, math, os, sys
import numpy as np
os.chdir("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid")
sys.path.insert(0, os.getcwd())
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

from scripts.run_full_powerflow_from_db import (
    BUILT, ISLAND_OF, _bus_lonlat, _k5, add_per_component_slacks,
    allocate_loads, attach_generators, GEN_ATTACH_DEFAULT, build_island_net)
from scripts.uc_to_pf_built import ISLAND_FREQ, solve_hour
from src.powerflow.load_estimator import load_demand_config
from src.powerflow.pipeline import add_reactive_compensation, add_provisional_infeed
from src.powerflow.pref_demand import pref_zone_gwh
from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot
from src.uc.scenario import build_national_scenario
from src.uc.solver import solve_uc

scn = build_national_scenario(scenario="fy2023r2")
uc = solve_uc(scn.to_uc_parameters())
assert uc.is_optimal
_gmap = {g.id: g for g in scn.generators}
charge_r = {}
for s in uc.schedules:
    g = _gmap.get(s.generator_id)
    if g is None:
        continue
    arr = charge_r.setdefault(g.region, [0.0] * len(s.power_output_mw))
    for i, pv in enumerate(s.power_output_mw):
        if pv < 0:
            arr[i] += -float(pv)

built = json.load(open(BUILT))
cfg = load_demand_config()
pref_gwh, _pw = pref_zone_gwh(built["nodes"], freq_fix=True)

results = {}
for island in ("east", "west"):
    regions = sorted(r for r, (isl, _f) in ISLAND_OF.items() if isl == island)
    net_dem = sum(np.asarray(scn.net_demand_r[r]) for r in regions)
    t = int(np.argmax(net_dem))
    geom = {}
    base, bus_of, _b = build_island_net(
        island, built["nodes"], built["edges"], ISLAND_FREQ[island], geom,
        dedup_nodes=True, freq_fix=True)
    attach_generators(base, bus_of, built["nodes"], island,
                      attach_mode=GEN_ATTACH_DEFAULT)
    allocate_loads(base, cfg, pref_gwh=pref_gwh)
    rfac = cfg.get("reactive_compensation_factor", 0.6)
    add_reactive_compensation(base, factor=rfac)
    infeed = add_provisional_infeed(base)
    add_per_component_slacks(base)
    fuel_by_zone = {r: uc_snapshot(uc, scn.generators, t, region=r)
                    for r in regions}
    demand = {}
    for r in regions:
        ch = charge_r.get(r) or []
        demand[r] = float(scn.net_demand_r[r][t]) + \
            (float(ch[t]) if t < len(ch) else 0.0)
        sp = (uc.regional_spill_mw.get(r) or [])
        v = float(sp[t]) if t < len(sp) else 0.0
        if v > 1e-6:
            tot = sum(fuel_by_zone[r].values())
            if tot > v:
                fuel_by_zone[r] = {k: mw * (tot - v) / tot
                                   for k, mw in fuel_by_zone[r].items()}
            else:
                fuel_by_zone[r] = {k: 0.0 for k in fuel_by_zone[r]}
    inject_dispatch_by_zone(base, fuel_by_zone, demand)
    net, mode = solve_hour(base, "ac")
    ld = net.res_line["loading_percent"].to_numpy()
    ld = np.where(np.isfinite(ld), ld, 0.0)
    tr = (float(net.res_trafo["loading_percent"].max())
          if len(net.res_trafo) else 0.0)
    vn_of = net.bus["vn_kv"]
    segs, cols, lws, tops = [], [], [], []
    bb_ld = []                      # 基幹(≥187kV)の負荷率
    order = np.argsort(ld)          # 高負荷を後で(上に)描く
    for li in order:
        row = net.line.iloc[li]
        if not bool(row.get("in_service", True)):
            continue
        try:
            flon, flat = _bus_lonlat(net, int(row.from_bus))
            tlon, tlat = _bus_lonlat(net, int(row.to_bus))
        except Exception:
            continue
        if any(v is None or not np.isfinite(v)
               for v in (flon, flat, tlon, tlat)):
            continue          # 合成スラック/(仮)infeed等の無座標バスはスキップ
        path = geom.get((_k5(flat, flon), _k5(tlat, tlon))) \
            or [[flon, flat], [tlon, tlat]]
        v = float(ld[li])
        if v < 40:
            c, w = "#2E4A7A", 0.5
        elif v < 70:
            c, w = "#E8C36A", 1.0
        elif v < 90:
            c, w = "#E8833A", 1.6
        else:
            c, w = "#D62728", 2.2
        segs.append([(pp_[0], pp_[1]) for pp_ in path])
        cols.append(c); lws.append(w)
        kv = float(vn_of.at[int(row.from_bus)])
        if kv >= 187:
            bb_ld.append(v)
        # ラベルは基幹系(≥187kV)かつ実名バスのみ — 合成ジャンクションと
        # 配電系スタブ(定格=代表値推定で%が暴れる)は誤解を招くため除外
        import re as _re
        _cl = lambda n: _re.sub(r"[\s・]*\d+(\.\d+)?\s*k?V?\s*$", "",
                                str(n)).strip()[:8]
        fn0 = str(net.bus.at[int(row.from_bus), "name"])
        tn0 = str(net.bus.at[int(row.to_bus), "name"])
        fn, tn = _cl(fn0), _cl(tn0)
        # fn == tn は同一構内の並列回線/電圧間渡り — 「同じ変電所同士を結ぶ線?」
        # と誤解されるだけなのでラベル候補から外し、次点を採用する
        if v >= 60 and kv >= 187 and fn and tn and fn != tn and \
                not any(x in (fn0 + tn0).lower()
                        for x in ("junc", "jun", "slack", "tie")):
            mx, my = (flon + tlon) / 2, (flat + tlat) / 2
            tops.append((v, mx, my, f"{fn}—{tn} {kv:.0f}kV {v:.0f}%",
                         (fn, tn)))
    tops.sort(key=lambda x: -x[0])
    seen_pair, uniq = set(), []
    for tp in tops:
        if tp[4] in seen_pair:
            continue
        seen_pair.add(tp[4]); uniq.append(tp)
    tops = uniq
    bb = np.array(bb_ld) if bb_ld else np.zeros(1)
    served = float(net.res_load.p_mw.sum()) if len(net.res_load) else 0.0
    results[island] = dict(t=t, mode=mode, segs=segs, cols=cols, lws=lws,
                           tops=tops[:3], demand=sum(demand.values()),
                           served=served, max_ld=float(ld.max()),
                           bb_max=float(bb.max()), bb_n90=int((bb >= 90).sum()),
                           n90=int((ld >= 90).sum()), n70=int((ld >= 70).sum()),
                           n_line=int(len(net.line)), tr_max=tr,
                           n_infeed=len(infeed))
    print(f"[{island}] t={t} mode={mode} served={served:,.0f}MW "
          f"max_line={ld.max():.0f}% (>90%:{results[island]['n90']}本 "
          f">70%:{results[island]['n70']}本) trafo_max={tr:.0f}%")

BG = "#0D1120"
X0, X1, Y0, Y1 = 128.9, 142.9, 30.7, 41.9
fig = plt.figure(figsize=(12.8, 7.2), dpi=150)
fig.patch.set_facecolor(BG)
# 下端0.105を注記帯として空ける(旧: 地図が下端まで伸び、四国・九州の線と
# 「定格は推定」の開示が重なった — この開示は技術報告の要なので確実に読ませる)
ax = fig.add_axes([0.0, 0.105, 1.0, 0.895]); ax.set_facecolor(BG)
ax.set_xlim(X0, X1); ax.set_ylim(Y0, Y1)
ax.set_aspect(1.0 / math.cos(math.radians(36.0))); ax.axis("off")
for island in ("east", "west"):
    r = results[island]
    ax.add_collection(LineCollection(r["segs"], colors=r["cols"],
                                     linewidths=r["lws"], alpha=0.9, zorder=3))
    # ラベルは余白の固定スロットへ(重なり防止) — 東=右余白/西=左余白
    slots = ([(0.995, 0.70), (0.995, 0.645), (0.995, 0.59)]
             if island == "east" else
             [(0.005, 0.46), (0.005, 0.405), (0.005, 0.35)])
    for (v, mx, my, lab, _pr), (sx, sy) in zip(r["tops"], slots):
        ax.annotate(lab, xy=(mx, my), xycoords="data",
                    xytext=(sx, sy), textcoords="axes fraction",
                    ha="right" if island == "east" else "left",
                    color="#FFB4A8", fontsize=8.5, zorder=9,
                    arrowprops=dict(arrowstyle="-", color="#FFB4A8",
                                    lw=0.6, alpha=0.55))
e, w = results["east"], results["west"]
# タイトルはスライド側のテキストボックスへ(PowerPointで編集可能にするため
# — オーナー指摘「GIFに焼き込むと編集できない」)
ax.text(0.02, 0.965,
        f"東: {e['t']}時 需要{e['demand']/1e3:.1f}GW 解={e['mode']}  "
        f"基幹(≥187kV)最大{e['bb_max']:.0f}%・90%超{e['bb_n90']}本"
        f"(全電圧では{e['n90']}本/{e['n_line']:,}本)\n"
        f"西: {w['t']}時 需要{w['demand']/1e3:.1f}GW 解={w['mode']}  "
        f"基幹最大{w['bb_max']:.0f}%・90%超{w['bb_n90']}本"
        f"(全電圧では{w['n90']}本/{w['n_line']:,}本)",
        transform=ax.transAxes, color="#C8CDD8", fontsize=10, va="top",
        linespacing=1.5)
for i, (c, lab) in enumerate((("#2E4A7A", "<40%"), ("#E8C36A", "40–70%"),
                              ("#E8833A", "70–90%"), ("#D62728", ">90%"))):
    ax.plot([0.025 + i * 0.105, 0.050 + i * 0.105], [0.812, 0.812],
            transform=ax.transAxes, color=c, lw=3.5)
    ax.text(0.056 + i * 0.105, 0.805, lab, transform=ax.transAxes,
            color="#A7B0CB", fontsize=9)
fig.text(0.030, 0.014,
         f"fy2023r2・UCピーク断面をuc_to_pf_built正典手順(#37(仮)infeed込み)で注入しAC求解。"
         f"ラベル=基幹系(≥187kV・実名)の負荷率上位。\n"
         "重要な開示: 線路定格は電圧階級の代表値推定(OSMに定格情報なし)のため、"
         "負荷率は絶対値でなく相対的な混雑指標。>90%の大半は66-77kV系の推定定格超過。\n"
         f"変圧器は地図に出さず開示: 最大負荷率 東{e['tr_max']:.0f}% / 西{w['tr_max']:.0f}%。"
         "線形は実OSMジオメトリ(edge path)。",
         color="#9AA3C0", fontsize=8.5, va="bottom", linespacing=1.5)
out = "docs/slides/ajg/assets/loading_map_peak.png"
fig.savefig(out, dpi=150, facecolor=BG)
print(f"-> {out} ({os.path.getsize(out)/1e6:.1f}MB)")
