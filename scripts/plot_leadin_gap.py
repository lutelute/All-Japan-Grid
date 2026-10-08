#!/usr/bin/env python3
"""「変電所に入っていく線」を使わずに代表点へ直線を引いている箇所を可視化する。

オーナー観察(2026-08-19)「ちゃんと変電所に入っていく線を生かしてほしい」
「OSMは意外と物理的に線をちゃんと残してあるので」の裏取り。

leadin / namebind は OSM の線端から**変電所の代表点**へ直線を張る合成エッジ。
ところが OSM 側は変電所ポリゴンの中まで線を描いていることが多い。
その対比を、実データの拡大図と地域別の充足率で示す。

出力: docs/reports/figs/leadin_gap_cases.png / leadin_gap_rate.png
"""
from __future__ import annotations
import json, math, os
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from shapely.geometry import shape, Point
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent.parent
FIGS = ROOT / "docs/reports/figs"
for _f in ("Hiragino Sans", "Hiragino Kaku Gothic ProN", "YuGothic"):
    plt.rcParams["font.family"] = _f
    break
plt.rcParams["axes.unicode_minus"] = False
BG, C_OSM, C_SYN, C_POLY = "#faf8f1", "#3a6ea5", "#cf4f5f", "#b3812f"


def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    return 6371*2*math.asin(math.sqrt(math.sin((la2-la1)/2)**2 +
        math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2))


def main():
    built = json.loads((ROOT/"docs/data/built/all.json").read_text())
    syn = [e for e in built["edges"] if (e.get("name") or "") in ("leadin", "namebind")]
    cases, rates = [], []
    for r in ("tokyo", "chubu", "kansai", "tohoku", "chugoku", "kyushu",
              "shikoku", "hokkaido", "hokuriku", "okinawa"):
        sp, lp = ROOT/f"data/{r}_substations.geojson", ROOT/f"data/{r}_lines.geojson"
        if not lp.exists():
            continue
        subs = [f for f in json.loads(sp.read_text())["features"]
                if f["geometry"]["type"] == "Polygon"]
        polys = [shape(f["geometry"]) for f in subs]
        tree = STRtree(polys)
        lines = json.loads(lp.read_text())["features"]
        inside = {}
        for lf in lines:
            g = shape(lf["geometry"]); cs = lf["geometry"]["coordinates"]
            for pi in tree.query(g):
                p = polys[int(pi)]
                if p.intersects(g) and any(p.covers(Point(c[0], c[1])) for c in cs):
                    inside.setdefault(int(pi), []).append(lf)
        rates.append((r, len(polys), len(inside)))
        if len(cases) >= 6:
            continue
        bb = (min(p.bounds[0] for p in polys), min(p.bounds[1] for p in polys),
              max(p.bounds[2] for p in polys), max(p.bounds[3] for p in polys))
        for e in sorted(syn, key=lambda e: -hav(e["a"], e["b"])):
            lat, lon = e["b"]
            if not (bb[1] <= lat <= bb[3] and bb[0] <= lon <= bb[2]):
                continue
            pt = Point(lon, lat); best, bd = None, 9e9
            for i in [int(i) for i in tree.query(pt.buffer(0.02))]:
                d = polys[i].distance(pt)
                if d < bd:
                    bd, best = d, i
            if best is None or best not in inside:
                continue
            cases.append((r, e, polys[best], inside[best],
                          subs[best]["properties"].get("name") or ""))
            break

    # --- 実例の拡大図 ---
    n = len(cases)
    fig, axes = plt.subplots(2, 3, figsize=(13.5, 8.8), facecolor=BG)
    for ax, (r, e, poly, ins, sname) in zip(axes.ravel(), cases):
        lat0 = e["b"][0]; k = math.cos(math.radians(lat0))
        xs, ys = poly.exterior.xy
        ax.fill([x*k for x in xs], list(ys), color=C_POLY, alpha=.16, zorder=2)
        ax.plot([x*k for x in xs], list(ys), color=C_POLY, lw=1.3, zorder=3)
        for lf in ins:
            c = lf["geometry"]["coordinates"]
            ax.plot([p[0]*k for p in c], [p[1] for p in c], color=C_OSM,
                    lw=2.0, zorder=4, solid_capstyle="round")
        ax.plot([e["a"][1]*k, e["b"][1]*k], [e["a"][0], e["b"][0]],
                color=C_SYN, lw=2.6, ls=(0, (5, 3)), zorder=6)
        ax.plot(e["a"][1]*k, e["a"][0], "o", color=C_SYN, ms=6, mec="white",
                mew=1.2, zorder=7)
        ax.plot(e["b"][1]*k, e["b"][0], "s", color=C_SYN, ms=7, mec="white",
                mew=1.2, zorder=7)
        b = poly.bounds
        mx = max(b[2]-b[0], b[3]-b[1], abs(e["a"][1]-e["b"][1]),
                 abs(e["a"][0]-e["b"][0]))*0.62 + 0.004
        cx, cy = (e["a"][1]+e["b"][1])/2, (e["a"][0]+e["b"][0])/2
        ax.set_xlim((cx-mx)*k, (cx+mx)*k); ax.set_ylim(cy-mx, cy+mx)
        ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
        ax.set_facecolor("#fffdf6")
        for s in ax.spines.values():
            s.set_color("#dcd8cc")
        ax.set_title(f"{sname[:16] or r}　{e.get('name')} "
                     f"{hav(e['a'], e['b']):.2f} km {e.get('kv') or 0:.0f}kV\n"
                     f"構内に入る OSM 線が {len(ins)} 本あるのに代表点へ直線",
                     fontsize=9.5, color="#1a1a17", pad=6)
    for ax in axes.ravel()[n:]:
        ax.axis("off")
    handles = [Line2D([], [], color=C_OSM, lw=2.2, label="OSM の線（構内まで描かれている）"),
               Line2D([], [], color=C_POLY, lw=1.6, label="変電所ポリゴン（OSM）"),
               Line2D([], [], color=C_SYN, lw=2.4, ls=(0, (5, 3)),
                      label="合成の直線（線端 → 変電所代表点）")]
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False, fontsize=10,
               bbox_to_anchor=(.5, .005))
    fig.suptitle("入っていく線があるのに、代表点へ直線を引いている — leadin / namebind の実例",
                 fontsize=13, x=.03, ha="left", y=.985, color="#1a1a17")
    fig.tight_layout(rect=[0, .045, 1, .95])
    out = FIGS/"leadin_gap_cases.png"
    fig.savefig(out, dpi=175, facecolor=BG); plt.close(fig)
    print(f"  {out.name} ({n} 例)")

    # --- 地域別の充足率 ---
    rates.sort(key=lambda x: -x[2]/x[1])
    fig, ax = plt.subplots(figsize=(9.6, 5.0), facecolor=BG)
    ax.set_facecolor("#fffdf6")
    JA = {"tokyo": "東京", "chubu": "中部", "kansai": "関西", "tohoku": "東北",
          "chugoku": "中国", "kyushu": "九州", "shikoku": "四国",
          "hokkaido": "北海道", "hokuriku": "北陸", "okinawa": "沖縄"}
    labs = [JA.get(r, r) for r, _, _ in rates]
    vals = [i/n*100 for _, n, i in rates]
    ax.bar(labs, vals, color=C_OSM, width=.62)
    for i, (v, (_, tot, ins)) in enumerate(zip(vals, rates)):
        ax.text(i, v+1.2, f"{v:.0f}%", ha="center", fontsize=10, fontweight="bold")
        ax.text(i, 3, f"{ins}/{tot}", ha="center", fontsize=8, color="white")
    ax.set_ylim(0, 105); ax.set_ylabel("OSM 線が構内まで入っている変電所の割合", fontsize=10)
    ax.grid(axis="y", alpha=.22, color="#dcd8cc")
    for s in ax.spines.values():
        s.set_color("#dcd8cc")
    tn = sum(x[1] for x in rates); ti = sum(x[2] for x in rates)
    ax.set_title(f"OSM は「変電所に入っていく線」をかなり残している — 全国 {ti:,}/{tn:,} = "
                 f"{ti/tn*100:.1f}%", fontsize=12.5, loc="left", color="#1a1a17", pad=10)
    fig.tight_layout()
    out2 = FIGS/"leadin_gap_rate.png"
    fig.savefig(out2, dpi=180, facecolor=BG); plt.close(fig)
    print(f"  {out2.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
