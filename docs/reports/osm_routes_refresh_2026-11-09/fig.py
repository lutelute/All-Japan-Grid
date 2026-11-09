#!/usr/bin/env python3
"""路線・鉄塔の層の作り直し(2026-11-09)の前と後の図と数。

    python3 docs/reports/osm_routes_refresh_2026-11-09/fig.py [--before-rev d0d7ca58]

前 = --before-rev の docs/data/osm_routes(#58〜#61 の前の正典と、#61 の前の四角で作った層)
後 = 作業ツリーの docs/data/osm_routes
地図の線はどちらも作業ツリーの docs/data/map/lines_all.geojson(今の正典)。「路線を引ける線」は
edge_routes.json の鍵(始点・終点・頂点数)が当たる線。
出力: fig_niigata_sado.png・numbers.json(この場所)
"""
import argparse
import json
import math
import os
import subprocess

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
REGIONS = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku", "kansai", "chugoku", "shikoku", "kyushu", "okinawa"]
BAND = (36.8, 41.5, 137.8, 139.0)          # 東北の lon_min を広げた帯(#61)
SADO = (37.70, 38.40, 138.15, 138.60)
VIEW = (36.75, 38.45, 137.75, 139.55)      # 図の範囲(lat0, lat1, lon0, lon1)
LINKED, UNLINKED, TOWER, BOX = "#2a6fdb", "#e8590c", "#3b3b3b", "#868e96"


def git_json(rev, path):
    return json.loads(subprocess.check_output(["git", "-C", ROOT, "show", f"{rev}:{path}"]))


def work_json(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        return json.load(fh)


def ek(c):
    a, b = c[0], c[-1]
    q = lambda x: str(int(round(x * 1e4)))
    return ",".join([q(a[0]), q(a[1]), q(b[0]), q(b[1]), str(len(c))])


def km(c):
    s = 0.0
    for (x1, y1), (x2, y2) in zip(c, c[1:]):
        s += math.hypot((x2 - x1) * 111.32 * math.cos(math.radians((y1 + y2) / 2)), (y2 - y1) * 110.57)
    return s


def inbox(lat, lon, b):
    return b[0] <= lat <= b[1] and b[2] <= lon <= b[3]


def cum(xs):
    s, out = 0, []
    for x in xs:
        s += x
        out.append(s / 1e5)
    return out


def layer(load):
    keys = load("docs/data/osm_routes/edge_routes.json")["map"]
    meta = load("docs/data/osm_routes/meta.json")
    pts = []
    for reg in REGIONS:
        t = load(f"docs/data/osm_routes/towers_{reg}.json")
        pts += list(zip(cum(t["lat"]), cum(t["lon"])))
    return keys, meta, pts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before-rev", default="d0d7ca58")
    args = ap.parse_args()
    lines = work_json("docs/data/map/lines_all.geojson")["features"]
    sides = {"before": layer(lambda p: git_json(args.before_rev, p)), "after": layer(work_json)}

    nums = {}
    for side, (keys, meta, pts) in sides.items():
        n = {"towers": meta["counts"]["towers"], "routes": meta["counts"]["routes"],
             "towers_band": sum(1 for a, b in pts if inbox(a, b, BAND) and not inbox(a, b, SADO)),
             "towers_sado": sum(1 for a, b in pts if inbox(a, b, SADO)),
             "osm_sha256": meta["source"]["sha256"][:12], "built_all_sha256": meta["source"]["built_all_sha256"][:12]}
        shaped = [f for f in lines if len(f["geometry"]["coordinates"]) > 2]
        n["shaped_lines"] = len(shaped)
        n["shaped_linked"] = sum(1 for f in shaped if ek(f["geometry"]["coordinates"]) in keys)
        ka = kh = ba = bh = 0.0
        for f in lines:
            c = f["geometry"]["coordinates"]
            L = km(c)
            mid = c[len(c) // 2]
            hit = ek(c) in keys
            ka += L
            kh += L if hit else 0
            if inbox(mid[1], mid[0], BAND):
                ba += L
                bh += L if hit else 0
        n.update(km_all=round(ka), km_linked=round(kh), band_km_all=round(ba), band_km_linked=round(bh))
        nums[side] = n

    fig, axes = plt.subplots(1, 2, figsize=(13, 7.8), constrained_layout=True)
    lat0, lat1, lon0, lon1 = VIEW
    for ax, side, title in ((axes[0], "before", "前（main d0d7ca58 の層）"), (axes[1], "after", "後（作り直した層）")):
        keys, meta, pts = sides[side]
        n = nums[side]
        segs_l, segs_u = [], []
        for f in lines:
            c = f["geometry"]["coordinates"]
            if not any(lon0 <= x <= lon1 and lat0 <= y <= lat1 for x, y in c):
                continue
            (segs_l if ek(c) in keys else segs_u).append(c)
        ax.add_collection(LineCollection(segs_l, colors=LINKED, linewidths=1.0, zorder=2))
        ax.add_collection(LineCollection(segs_u, colors=UNLINKED, linewidths=1.4, zorder=3))
        vis = [(a, b) for a, b in pts if lat0 <= a <= lat1 and lon0 <= b <= lon1]
        ax.scatter([b for a, b in vis], [a for a, b in vis], s=0.6, c=TOWER, lw=0, zorder=4)
        # 前の東北の西の端(139.0°)と、東京・中部の北の端(37.0°)
        ax.plot([139.0, 139.0], [37.0, lat1], ls="--", lw=1.0, c=BOX, zorder=1)
        ax.plot([lon0, 139.0], [37.0, 37.0], ls="--", lw=1.0, c=BOX, zorder=1)
        lab = dict(fontsize=8.5, color="#495057", bbox=dict(fc="white", ec="none", alpha=0.85, pad=1.5), zorder=5)
        ax.text(138.98, 38.40, "前の東北の四角の西の端（139.0°）", va="top", ha="right", **lab)
        ax.text(137.80, 37.03, "東京・中部の四角の北の端（37.0°）", va="bottom", **lab)
        ax.set_xlim(lon0, lon1)
        ax.set_ylim(lat0, lat1)
        ax.set_aspect(1 / math.cos(math.radians((lat0 + lat1) / 2)))
        ax.set_title(f"{title}\n鉄塔: 新潟の西 {n['towers_band']:,} 基・佐渡 {n['towers_sado']:,} 基\n"
                     f"帯の正典の線のうち、路線を引けるもの: {n['band_km_linked']:,} / {n['band_km_all']:,} km",
                     fontsize=10, loc="left")
        ax.tick_params(labelsize=8, colors="#495057")
        for s in ax.spines.values():
            s.set_color("#ced4da")
    h = [plt.Line2D([], [], c=LINKED, lw=1.6, label="正典の線（路線を引ける）"),
         plt.Line2D([], [], c=UNLINKED, lw=1.6, label="正典の線（路線を引けない）"),
         plt.Line2D([], [], ls="", marker="o", ms=3, c=TOWER, label="鉄塔（OSM）"),
         plt.Line2D([], [], c=BOX, ls="--", lw=1.0, label="前の地域の四角の端")]
    axes[1].legend(handles=h, loc="lower right", fontsize=8.5, frameon=True, framealpha=0.9)
    fig.savefig(os.path.join(HERE, "fig_niigata_sado.png"), dpi=130, bbox_inches="tight", pad_inches=0.25)
    with open(os.path.join(HERE, "numbers.json"), "w", encoding="utf-8") as fh:
        json.dump(nums, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(json.dumps(nums, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
