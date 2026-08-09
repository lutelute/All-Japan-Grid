#!/usr/bin/env python3
"""修復前後の過負荷を地図で並べる（before/after ペア）。

`repair_search.py` が数字で出した「どの構成が最良か」を、**どこが直ったか**として見る。
過負荷は数字だと 603→N 本としか見えないが、地図にすると需要地の周りに輪のように
分布しているのか、幹線に沿っているのかが分かる。次の仮説はそこから出る。

before = 現行モデル（gen=base / 降圧点なし / 太陽光既定 10MW）
after  = `--gen/--sd/--solar` で指定する構成（既定は探索の最良）

usage:
    python3 scripts/capacity/repair_map.py --islands east west --gen cap --sd --solar 0.10
出力: docs/assets/analysis/repair_map_{island}_<date>.png
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
ASSETS = ROOT / "docs" / "assets" / "analysis"

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection

if platform.system() == "Darwin":
    plt.rcParams["font.family"] = ["Hiragino Sans", "Hiragino Kaku Gothic ProN",
                                   "Apple SD Gothic Neo", "sans-serif"]
else:
    try:
        import japanize_matplotlib  # noqa: F401
    except ImportError:
        pass


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def segments(pf, net):
    """(通常線, 過負荷線) の座標セグメントと過負荷の負荷率。"""
    normal, over, over_pct = [], [], []
    for li in net.line.index:
        if not bool(net.line.at[li, "in_service"]):
            continue
        fb, tb = int(net.line.at[li, "from_bus"]), int(net.line.at[li, "to_bus"])
        x1, y1 = pf._bus_lonlat(net, fb)
        x2, y2 = pf._bus_lonlat(net, tb)
        if x1 is None or x2 is None or (x1 == 0 and y1 == 0) or (x2 == 0 and y2 == 0):
            continue
        seg = [(x1, y1), (x2, y2)]
        lp = net.res_line.at[li, "loading_percent"] if li in net.res_line.index else None
        if lp is not None and lp == lp and float(lp) > 100.0:
            over.append(seg)
            over_pct.append(float(lp))
        else:
            normal.append(seg)
    return normal, over, over_pct


def panel(ax, pf, net, title, stats):
    normal, over, over_pct = segments(pf, net)
    ax.add_collection(LineCollection(normal, colors="#c9d3dd", linewidths=0.35, zorder=1))
    if over:
        order = sorted(range(len(over)), key=lambda i: over_pct[i])
        segs = [over[i] for i in order]
        pcts = [over_pct[i] for i in order]
        lc = LineCollection(segs, linewidths=[1.0 + min(2.6, p / 500.0) for p in pcts],
                            zorder=3, cmap="autumn_r")
        lc.set_array(__import__("numpy").array(pcts))
        lc.set_clim(100, max(400.0, min(2000.0, max(pcts))))
        ax.add_collection(lc)
    xs = [p[0] for s in normal + over for p in s]
    ys = [p[1] for s in normal + over for p in s]
    if xs:
        mx, my = (max(xs) - min(xs)) * 0.03, (max(ys) - min(ys)) * 0.03
        ax.set_xlim(min(xs) - mx, max(xs) + mx)
        ax.set_ylim(min(ys) - my, max(ys) + my)
    ax.set_aspect(1.0 / max(0.2, __import__("math").cos(
        __import__("math").radians(sum(ys) / len(ys) if ys else 36.0))))
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color("#dde3ea")
    ax.set_title(title, fontsize=11, fontweight="bold", pad=8)
    ax.text(0.015, 0.015, stats, transform=ax.transAxes, fontsize=9, va="bottom",
            bbox=dict(boxstyle="round,pad=0.45", fc="white", ec="#dde3ea", alpha=0.92))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="*", default=["east", "west"])
    ap.add_argument("--gen", default="cap")
    ap.add_argument("--sd", action="store_true", default=False)
    ap.add_argument("--solar", type=float, default=0.10)
    ap.add_argument("--min-hops", type=int, default=3)
    ap.add_argument("--radius-km", type=float, default=10.0)
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                                       text=True).stdout.strip()

    rs = _load(ROOT / "scripts" / "capacity" / "repair_search.py", "rs")
    pf, wgv, wsd = rs.load_modules()
    with open(pf.BUILT, encoding="utf-8") as f:
        db = json.load(f)
    nodes, edges = db["nodes"], db["edges"]
    cfg = pf.load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(nodes)

    ASSETS.mkdir(parents=True, exist_ok=True)
    for island in args.islands:
        outs = []
        for label, (gen, sd, solar) in (
                ("before", ("base", False, 10.0)),
                ("after", (args.gen, args.sd, args.solar))):
            r = rs.run_config(pf, wgv, wsd, island, nodes, edges, cfg, pref_gwh,
                              gen, sd, solar, args.min_hops, args.radius_km,
                              1.5, 25.0, keep_net=True)
            outs.append((label, gen, sd, solar, r.pop("_net"), r))
        fig, axes = plt.subplots(1, 2, figsize=(13.2, 7.2))
        for ax, (label, gen, sd, solar, net, r) in zip(axes, outs):
            o = r["overload"]
            head = ("現行モデル" if label == "before" else
                    f"修復後（接続={gen} / 降圧点{'あり' if sd else 'なし'} / 太陽光{solar:g}MW）")
            stats = (f"過負荷 {o['n_over']:,} / {o['n_line']:,} 本（{o['over_share']:.2%}）\n"
                     f"最大負荷率 {o['max_pct']:,.0f}%\n"
                     f"超過潮流 {o['excess_mw']:,.0f} MW\n"
                     f"出典のない容量 {r['fab_unsourced_mw']:,.0f} MW"
                     f" / 捏造設備 {r['fab_n_fab_trafo']:,} 台")
            panel(ax, pf, net, head, stats)
        fig.suptitle(f"{island} — 修復前後の過負荷（DC・{date}・未適用）",
                     fontsize=13.5, fontweight="bold")
        fig.tight_layout(rect=(0, 0, 1, 0.95))
        p = ASSETS / f"repair_map_{island}_{date}.png"
        fig.savefig(p, dpi=150)
        plt.close(fig)
        print(f"→ {p.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
