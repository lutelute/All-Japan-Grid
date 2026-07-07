#!/usr/bin/env python3
"""UC 24h × 潮流のGIFアニメーション — 全系統(4島)・全電圧階級(66kV+)の時系列可視化.

既定 = **全規模正典モデル**(built全ノード・v4銘板・全電圧階級)を4島すべて解く:
  east/hokkaido/okinawa = AC(prune ladder込み) / west = DC(誠実表示)。
容量較正(capacity_bridge)+境界注入(東西FC・北本)を適用。

各フレーム=1時刻の潮流解。線=|P|で太さ・濃さ(単一色相の逐次ランプ)、
発電=バブル(注入MW)、島間転送=ダイヤ(+=east流入)、下段=全国需要カーブ+時刻カーソル。
時刻間は線形補間でなめらかに。okinawaは左下インセット。

開示(docs/MODEL_INTERVENTIONS.md「読み方」): 線別の値は仮定合成の推定であり
個別引用不可 — フッターに常時明記。westはDC解であることをHUDに常時表示。

使い方:
    PYTHONPATH=. .venv/bin/python scripts/animate_powerflow_gif.py               # 全国・全規模
    PYTHONPATH=. .venv/bin/python scripts/animate_powerflow_gif.py --islands east --model backbone
出力: dist/pf_animation/*.gif (バイナリ非追跡・本スクリプトで決定的に再生成)
"""
import argparse
import copy
import json
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from PIL import Image

from scripts.run_full_powerflow_from_db import (
    BUILT,
    ISLAND_OF,
    _bus_lonlat,
    add_per_component_slacks,
    allocate_loads,
    attach_generators,
    build_island_net,
)
from scripts.uc_to_pf_built import (
    ISLAND_FREQ,
    ISLAND_MODE,
    build_backbone_net,
    island_boundary_flows,
    setup_boundary_sgens,
    solve_hour,
)
from src.powerflow.load_estimator import load_demand_config
from src.uc.capacity_bridge import apply_to_net, load_pf_calibration
from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot
from src.uc.scenario import build_national_scenario
from src.uc.solver import solve_uc

EXTENT = {   # (lon0, lon1, lat0, lat1) — 単島モード用
    "east": (137.2, 142.3, 34.7, 41.7),
    "west": (129.4, 138.0, 32.4, 37.4),
    "hokkaido": (139.2, 146.0, 41.2, 45.8),
    "okinawa": (127.5, 128.4, 26.0, 27.0),
}
NATIONAL_EXTENT = (128.8, 146.3, 30.4, 45.9)
OKINAWA_INSET = (127.55, 128.35, 26.05, 26.95)
INK = "#1a1a1a"
MUTED = "#6b6b6b"
SURFACE = "#fcfcfb"
GEN_C = "#1B7837"
IMP_C = "#CC3311"       # east流入(+)
EXP_C = "#2C7FB8"       # east流出(-)
LINE_LO = np.array([0.78, 0.80, 0.88])
LINE_HI = np.array([0.20, 0.19, 0.55])
# 島間転送ダイヤの表示位置(実回廊の代表点)
TIE_POS = {"東西FC": (137.95, 35.55), "北本": (140.85, 41.35)}


def prefecture_outlines(extent):
    path = os.path.join("data", "reference",
                        "japan_prefectures_simplified.geojson")
    segs = []
    lon0, lon1, lat0, lat1 = extent
    d = json.load(open(path, encoding="utf-8"))
    for f in d["features"]:
        g = f["geometry"]
        polys = (g["coordinates"] if g["type"] == "MultiPolygon"
                 else [g["coordinates"]])
        for poly in polys:
            for ring in poly:
                arr = np.asarray(ring, dtype=float)
                if (arr[:, 0].max() < lon0 or arr[:, 0].min() > lon1
                        or arr[:, 1].max() < lat0 or arr[:, 1].min() > lat1):
                    continue
                segs.append(arr)
    return segs


def solve_island_24h(island, scn, uc, model, bridge=False, boundary=False):
    """1島の24時刻を解き、(frames, line_seg, coords, bflows) を返す。

    bridge/boundary は uc_to_pf_built と同じくオプトイン(既定OFF=正典構成)。
    full+bridge の組合せは east でAC発散→見せかけ解を誘発した実績があり
    (ハマり⑩)、solve_hour の給電率ガードで却下される。"""
    regions = sorted(r for r, (isl, _f) in ISLAND_OF.items() if isl == island)
    built = json.load(open(BUILT, encoding="utf-8"))
    cfg = load_demand_config()
    t0 = time.monotonic()
    geom = {}
    base, bus_of, _ = build_island_net(island, built["nodes"], built["edges"],
                                       ISLAND_FREQ[island], geom)
    attach_generators(base, bus_of, built["nodes"], island)
    gzo = None
    if bridge:
        brep = apply_to_net(base, load_pf_calibration())
        gzo = {int(k): v for k, v in brep["zone_override"].items()}
    allocate_loads(base, cfg)
    if model == "backbone":
        base, _ledger = build_backbone_net(base)
    add_per_component_slacks(base)
    bpts = []
    if boundary:
        bpts, _ = setup_boundary_sgens(base, island)
    bflows = island_boundary_flows(uc, scn, set(regions))
    mode = "ac" if model == "backbone" else ISLAND_MODE[island]
    print(f"[{island}] 構築 {time.monotonic()-t0:.0f}s — "
          f"{len(base.bus)}バス mode={mode}")

    coords = {int(b): _bus_lonlat(base, int(b)) for b in base.bus.index}
    line_seg = {}
    for li in base.line.index:
        fb, tb = int(base.line.at[li, "from_bus"]), int(base.line.at[li, "to_bus"])
        pa, pb = coords[fb], coords[tb]
        if pa[0] is None or pb[0] is None:
            continue
        # 実OSM経路(ポリライン)で描く — 直線描画は実在しない交差に見える
        a5 = (round(pa[1], 5), round(pa[0], 5))
        b5 = (round(pb[1], 5), round(pb[0], 5))
        path = geom.get((a5, b5))
        line_seg[int(li)] = (path if path and len(path) >= 2
                             else [list(pa), list(pb)])

    frames = []
    for t in range(24):
        th = time.monotonic()
        net_t = copy.deepcopy(base)
        fuel = {r: uc_snapshot(uc, scn.generators, t, region=r) for r in regions}
        demand = {r: float(scn.net_demand_r[r][t]) for r in regions}
        inject_dispatch_by_zone(net_t, fuel, demand, gen_zone_override=gzo)
        for p in bpts:
            s = bflows.get(tuple(sorted(p["pair"])))
            if s is not None and t < len(s):
                net_t.sgen.at[p["sgen"], "p_mw"] = float(s[t]) * p["share"]
        net_s, used = solve_hour(net_t, mode)
        if not net_s.converged:
            print(f"[{island}] t={t}: 非収束 — スキップ(明示)")
            frames.append(None)
            continue
        served = float(net_s.res_load.p_mw.sum()) if len(net_s.res_load) else 0.0
        flows = {int(li): float(net_s.res_line.at[li, "p_from_mw"])
                 for li in net_s.res_line.index if int(li) in line_seg}
        gen_p = {}
        for gi in net_s.gen.index:
            p = float(net_s.res_gen.at[gi, "p_mw"]) \
                if gi in net_s.res_gen.index else 0.0
            if p > 1.0:
                b = int(net_s.gen.at[gi, "bus"])
                gen_p[b] = gen_p.get(b, 0.0) + p
        loss = (float(net_s.res_line.pl_mw.sum()
                      + net_s.res_trafo.pl_mw.sum()) if used != "dc" else 0.0)
        frames.append({"t": t, "flows": flows, "gen_p": gen_p,
                       "demand": sum(demand.values()), "served": served,
                       "slack": float(net_s.res_ext_grid.p_mw.sum()),
                       "loss": loss, "solver": used})
        print(f"[{island}] t={t:2d} {used} {time.monotonic()-th:.1f}s",
              flush=True)
    return frames, line_seg, coords, bflows


def merge_national(per_island):
    """島別結果を全国フレームへ統合。keyは(island, id)タプル。"""
    islands = list(per_island)
    line_seg, coords = {}, {}
    for isl in islands:
        _, ls, co, _ = per_island[isl]
        for li, seg in ls.items():
            line_seg[(isl, li)] = seg
        for b, xy in co.items():
            coords[(isl, b)] = xy
    frames = []
    for t in range(24):
        fs = {isl: per_island[isl][0][t] for isl in islands}
        if all(f is None for f in fs.values()):
            frames.append(None)
            continue
        flows, gen_p = {}, {}
        demand = slack = loss = 0.0
        solver = []
        for isl, f in fs.items():
            if f is None:
                solver.append(f"{isl[0]}:×")
                continue
            for li, v in f["flows"].items():
                flows[(isl, li)] = v
            for b, v in f["gen_p"].items():
                gen_p[(isl, b)] = v
            demand += f["demand"]; slack += f["slack"]; loss += f["loss"]
            served = f.get("served")
            solver.append(f"{isl[0]}:{f['solver'].replace('_fallback','*')}")
        frames.append({"t": t, "flows": flows, "gen_p": gen_p,
                       "demand": demand, "slack": slack, "loss": loss,
                       "solver": " ".join(solver)})
    # 島間転送(表示用) — east側のbflowsから(+=east流入)
    ties = {}
    if "east" in per_island:
        bf = per_island["east"][3]
        for key, series in bf.items():
            label = "北本" if "hokkaido" in key else "東西FC"
            ties[label] = [ties.get(label, [0.0] * 24)[t] + float(series[t])
                           for t in range(24)]
    return frames, line_seg, coords, ties


def lerp_frames(frames, n_tween):
    out = []
    valid = [f for f in frames if f]
    for i, f in enumerate(valid):
        g = valid[(i + 1) % len(valid)]
        for k in range(n_tween):
            a = k / n_tween
            fl = {li: (1 - a) * f["flows"].get(li, 0) + a * g["flows"].get(li, 0)
                  for li in set(f["flows"]) | set(g["flows"])}
            gp = {b: (1 - a) * f["gen_p"].get(b, 0) + a * g["gen_p"].get(b, 0)
                  for b in set(f["gen_p"]) | set(g["gen_p"])}
            out.append({**f, "flows": fl, "gen_p": gp,
                        "tlabel": f["t"], "frac": a})
    return out


def _draw_net(ax, fr, line_seg, coords, pmax, gmax, key_filter=None):
    lis = [li for li in fr["flows"]
           if key_filter is None or key_filter(li)]
    if lis:
        segs = [np.asarray(line_seg[li], dtype=float) for li in lis]
        mags = np.array([abs(fr["flows"][li]) for li in lis])
        rel = np.sqrt(np.clip(mags / pmax, 0, 1))
        colors = LINE_LO[None, :] + rel[:, None] * (LINE_HI - LINE_LO)[None, :]
        lws = 0.4 + 2.8 * rel
        ax.add_collection(LineCollection(segs, colors=colors, linewidths=lws,
                                         zorder=3, capstyle="round"))
    bs = [b for b in fr["gen_p"]
          if key_filter is None or key_filter(b)]
    if bs:
        xs = [coords[b][0] for b in bs]
        ys = [coords[b][1] for b in bs]
        ss = [6 + 500 * fr["gen_p"][b] / gmax for b in bs]
        ax.scatter(xs, ys, s=ss, c=GEN_C, alpha=0.32, linewidths=0.4,
                   edgecolors=GEN_C, zorder=4)


def render(frames, line_seg, coords, ties, out_path, national,
           island="east", n_tween=3, model="full", subtitle=""):
    extent = NATIONAL_EXTENT if national else EXTENT[island]
    lon0, lon1, lat0, lat1 = extent
    pref = prefecture_outlines(extent)
    pref_ok = prefecture_outlines(OKINAWA_INSET) if national else []
    valid = [f for f in frames if f]
    pmax = max(max(abs(v) for v in f["flows"].values()) for f in valid)
    gmax = max(max(f["gen_p"].values()) for f in valid if f["gen_p"])
    dem_curve = [f["demand"] if f else np.nan for f in frames]
    tweens = lerp_frames(frames, n_tween)
    print(f"フレーム描画: {len(tweens)}枚 (|P|max={pmax:,.0f}MW)")

    plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
    images = []
    aspect = 1.0 / np.cos(np.deg2rad((lat0 + lat1) / 2))
    for fi, fr in enumerate(tweens):
        fig = plt.figure(figsize=(9.0, 9.6), dpi=100, facecolor=SURFACE)
        ax = fig.add_axes([0.02, 0.150, 0.96, 0.745])
        ax.set_facecolor(SURFACE)
        for arr in pref:
            ax.plot(arr[:, 0], arr[:, 1], color="#e2e0dc", lw=0.6, zorder=1)
        if national:
            _draw_net(ax, fr, line_seg, coords, pmax, gmax,
                      key_filter=lambda k: k[0] != "okinawa")
        else:
            _draw_net(ax, fr, line_seg, coords, pmax, gmax)
        # 島間転送ダイヤ(+=east流入)
        hh = fr["tlabel"] + fr["frac"]
        for label, series in ties.items():
            t0i = fr["tlabel"]; t1i = (t0i + 1) % 24
            v = (1 - fr["frac"]) * series[t0i] + fr["frac"] * series[t1i]
            xy = TIE_POS.get(label)
            if not xy or not (lon0 < xy[0] < lon1 and lat0 < xy[1] < lat1):
                continue
            c = IMP_C if v >= 0 else EXP_C
            ax.scatter([xy[0]], [xy[1]], marker="D",
                       s=90 + 240 * abs(v) / 2100, c=c, zorder=6,
                       edgecolors="white", linewidths=1.2)
            ax.annotate(f"{label} {v:+,.0f}MW", xy=xy, xytext=(8, 6),
                        textcoords="offset points", fontsize=9,
                        color=c, fontweight="bold", zorder=7)
        ax.set_xlim(lon0, lon1); ax.set_ylim(lat0, lat1)
        ax.set_aspect(aspect); ax.axis("off")
        # okinawaインセット
        if national:
            axo = fig.add_axes([0.045, 0.185, 0.15, 0.115])
            axo.set_facecolor(SURFACE)
            for arr in pref_ok:
                axo.plot(arr[:, 0], arr[:, 1], color="#e2e0dc", lw=0.6,
                         zorder=1)
            _draw_net(axo, fr, line_seg, coords, pmax, gmax,
                      key_filter=lambda k: k[0] == "okinawa")
            axo.set_xlim(OKINAWA_INSET[0], OKINAWA_INSET[1])
            axo.set_ylim(OKINAWA_INSET[2], OKINAWA_INSET[3])
            axo.set_aspect(1.11)
            axo.set_xticks([]); axo.set_yticks([])
            for s in axo.spines.values():
                s.set_color("#cccccc")
            axo.set_title("okinawa", fontsize=7.5, color=MUTED, pad=2)
        # HUD(サブタイトル=左・統計=右で行を分けて衝突回避)
        title = ("全国系統 24時間潮流 — 全規模・全電圧階級(66kV+)" if national
                 else f"{island} 島 24時間潮流"
                      + ("(backbone)" if model == "backbone" else "(全規模)"))
        fig.text(0.04, 0.960, title, fontsize=15, fontweight="bold", color=INK)
        fig.text(0.04, 0.934, subtitle, fontsize=8.5, color=MUTED)
        fig.text(0.96, 0.952, f"{int(hh):02d}:{int(60*(hh%1)):02d}",
                 fontsize=20, fontweight="bold", color=INK, ha="right",
                 family="monospace")
        fig.text(0.96, 0.912,
                 f"需要 {fr['demand']/1000:,.1f} GW · slack "
                 f"{fr['slack']/fr['demand']*100:+.1f}% · 損失(AC島) "
                 f"{fr['loss']/1000:,.2f} GW · {fr['solver']}",
                 fontsize=9, color=MUTED, ha="right")
        fig.text(0.04, 0.118, "— 線潮流 |P| (太く濃いほど大 · 平方根スケール)   "
                              "● 発電注入   ◆ 島間転送(+ = east流入)",
                 fontsize=8.5, color=MUTED)
        fig.text(0.04, 0.008,
                 "線別の値は仮定合成の推定であり個別引用不可 — "
                 "docs/MODEL_INTERVENTIONS.md「読み方」参照",
                 fontsize=7.5, color="#9a9a9a")
        # 需要カーブ
        axd = fig.add_axes([0.06, 0.062, 0.88, 0.052])
        axd.set_facecolor(SURFACE)
        axd.plot(range(24), [d / 1000 for d in dem_curve], color="#4443A6",
                 lw=1.6)
        axd.axvline(hh, color=IMP_C, lw=1.4)
        axd.set_xlim(0, 23)
        axd.set_xticks([0, 6, 12, 18, 23])
        axd.set_xticklabels(["0時", "6時", "12時", "18時", "23時"], fontsize=7)
        axd.set_yticks([])
        axd.text(0.005, 0.85, "需要カーブ(全国)" if national else "需要カーブ",
                 transform=axd.transAxes, fontsize=7, color=MUTED, va="top")
        for s in axd.spines.values():
            s.set_visible(False)
        fig.canvas.draw()
        images.append(Image.fromarray(
            np.asarray(fig.canvas.buffer_rgba())[:, :, :3]))
        plt.close(fig)
        if fi % 12 == 0:
            print(f"  frame {fi}/{len(tweens)}", flush=True)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    images[0].save(out_path, save_all=True, append_images=images[1:],
                   duration=110, loop=0, optimize=True)
    print(f"-> {out_path} ({os.path.getsize(out_path)/1e6:.1f}MB, "
          f"{len(images)}フレーム)")


def _cache_dump(path, frames, line_seg, coords, ties):
    j = lambda k: f"{k[0]}|{k[1]}"  # noqa: E731
    doc = {"ties": ties,
           "line_seg": {j(k): v for k, v in line_seg.items()},
           "coords": {j(k): v for k, v in coords.items()},
           "frames": [None if f is None else
                      {**f, "flows": {j(k): v for k, v in f["flows"].items()},
                       "gen_p": {j(k): v for k, v in f["gen_p"].items()}}
                      for f in frames]}
    with open(path, "w") as fp:
        json.dump(doc, fp)
    print(f"cache -> {path} ({os.path.getsize(path)/1e6:.1f}MB)")


def _cache_load(path):
    u = lambda s: (s.split("|")[0], int(s.split("|")[1]))  # noqa: E731
    d = json.load(open(path))
    frames = [None if f is None else
              {**f, "flows": {u(k): v for k, v in f["flows"].items()},
               "gen_p": {u(k): v for k, v in f["gen_p"].items()}}
              for f in d["frames"]]
    line_seg = {u(k): v for k, v in d["line_seg"].items()}
    coords = {u(k): v for k, v in d["coords"].items()}
    return frames, line_seg, coords, d["ties"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="+",
                    default=["hokkaido", "east", "west", "okinawa"],
                    choices=["east", "west", "hokkaido", "okinawa"])
    ap.add_argument("--model", choices=["full", "backbone"], default="full",
                    help="full=全規模・全電圧階級(既定・正典) / backbone=縮約")
    ap.add_argument("--bridge", action="store_true",
                    help="容量較正を適用(オプトイン・uc_to_pf_builtと同じ)")
    ap.add_argument("--boundary-injection", action="store_true",
                    help="境界注入を適用(オプトイン)")
    ap.add_argument("--tween", type=int, default=3)
    ap.add_argument("--render-only", action="store_true",
                    help="解かずにキャッシュ(前回のsolve結果)から描画のみ")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    national = len(args.islands) > 1
    cfg_tag = (args.model + ("_bridge" if args.bridge else "")
               + ("_bnd" if args.boundary_injection else ""))
    cache = os.path.join("dist", "pf_animation",
                         f"cache_{'-'.join(sorted(args.islands))}_{cfg_tag}.json")

    if national:
        if args.render_only and os.path.exists(cache):
            frames, line_seg, coords, ties = _cache_load(cache)
        else:
            print("UC求解中...")
            scn = build_national_scenario(scenario="fy2023r2")
            uc = solve_uc(scn.to_uc_parameters())
            assert uc.is_optimal, uc.status
            per_island = {isl: solve_island_24h(
                isl, scn, uc, args.model, bridge=args.bridge,
                boundary=args.boundary_injection) for isl in args.islands}
            frames, line_seg, coords, ties = merge_national(per_island)
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            _cache_dump(cache, frames, line_seg, coords, ties)
        f12 = frames[12]
        if f12:
            print(f"サニティ t=12: 需要{f12['demand']:,.0f} "
                  f"slack{f12['slack']:+,.0f} 損失(AC){f12['loss']:,.0f}MW "
                  f"{f12['solver']}")
        out = args.out or os.path.join(
            "dist", "pf_animation", f"national_pf_24h_{cfg_tag}.gif")
        subtitle = ("UC(fy2023r2) → built正典(v4銘板)"
                    + (" + 容量較正" if args.bridge else "")
                    + (" + 境界注入(FC/北本)" if args.boundary_injection else "")
                    + " · west=DC解(誠実表示)")
        if not args.boundary_injection:
            ties = {}   # PFへ注入していない転送は描かない(誤解防止)
        render(frames, line_seg, coords, ties, out, True,
               n_tween=args.tween, model=args.model, subtitle=subtitle)
    else:
        print("UC求解中...")
        scn = build_national_scenario(scenario="fy2023r2")
        uc = solve_uc(scn.to_uc_parameters())
        assert uc.is_optimal, uc.status
        isl = args.islands[0]
        frames, line_seg, coords, bflows = solve_island_24h(
            isl, scn, uc, args.model, bridge=args.bridge,
            boundary=args.boundary_injection)
        ties = {}
        if isl == "east":
            for key, series in bflows.items():
                label = "北本" if "hokkaido" in key else "東西FC"
                ties[label] = [float(v) for v in series]
        out = args.out or os.path.join(
            "dist", "pf_animation", f"{isl}_pf_24h_{cfg_tag}.gif")
        subtitle = ("UC(fy2023r2) → built正典(v4銘板)"
                    + (" + 容量較正" if args.bridge else "")
                    + (" + 境界注入(FC/北本)" if args.boundary_injection else ""))
        if not args.boundary_injection:
            ties = {}
        render(frames, line_seg, coords, ties, out, False, island=isl,
               n_tween=args.tween, model=args.model, subtitle=subtitle)


if __name__ == "__main__":
    main()
