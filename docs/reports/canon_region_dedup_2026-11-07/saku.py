#!/usr/bin/env python3
"""#163 で、佐久の水力 3 件が東に結ばれ、小諸の太陽光が東から外れた件(先生の問い 2026-11-09)。

gens_dump.py の出力(東と西・前と後)と、前と後の正典を突き合わせ、5 つの発電所の付き先と、
東に残った切れ端(小海町変電所_2 の東京の写し)を図とまとめにする。

    python3 saku.py <前の all.json> <後の all.json> <東・前> <東・後> <西・前> <西・後>
→ saku.json・fig_saku.png
"""
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#c9c8c2"
CHUBU, TOKYO = "#2a78d6", "#e34948"
PLANTS = ["小諸市立東小学校", "小諸市立美南ガ丘小学校", "八那池第一水力発電所", "大字高野町佐久穂町発電所", "松原発電所"]
# 地物の座標(data/tokyo_plants.geojson・chubu_plants.geojson。どちらの取り出しにも同じ osm_id で入っている)
PLANT_XY = {"小諸市立東小学校": (36.31366, 138.45784), "小諸市立美南ガ丘小学校": (36.30034, 138.45518),
            "八那池第一水力発電所": (36.05642, 138.46667), "大字高野町佐久穂町発電所": (36.15698, 138.48434),
            "松原発電所": (36.05251, 138.45342)}
FRAG = {"tokyo_sub_1234", "tokyo_jct_36.0905:138.4764:77", "tokyo_jct_36.1252:138.4671:77",
        "tokyo_jct_36.0789:138.4743:77"}
BOX = (138.30, 138.75, 35.97, 36.40)
k5 = lambda p: (round(p[0], 5), round(p[1], 5))  # noqa: E731


def gens(path):
    G = json.load(open(path, encoding="utf-8"))["gens"]
    out = {}
    for g in G:
        if g["name"] in PLANTS:
            out.setdefault(g["name"], []).append({"src": g["src"], "bus": g["bus"], "kv": g["kv"],
                                                  "lat": g["lat"], "lon": g["lon"]})
    return {"n_gen": len(G), "plants": out}


def main(ab, aa, eb, ea, wb, wa):
    res = {"what": "#163 の前と後で、5 つの発電所(長野県の小諸・小海町・佐久穂町)が潮流計算の網のどこに付くか",
           "east": {"before": gens(eb), "after": gens(ea)}, "west": {"before": gens(wb), "after": gens(wa)}}
    canons = {t: json.load(open(p, encoding="utf-8")) for t, p in (("before", ab), ("after", aa))}
    res["fragment_after"] = [n for n in canons["after"]["nodes"] if n["id"] in FRAG]
    res["fragment_before"] = [n for n in canons["before"]["nodes"] if n["id"] in FRAG]
    json.dump(res, open(os.path.join(HERE, "saku.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for isl in ("east", "west"):
        for t in ("before", "after"):
            p = res[isl][t]["plants"]
            print(isl, t, res[isl][t]["n_gen"], {k: sorted({x["bus"] for x in v}) for k, v in p.items()})
    fig_(canons, res)


def fig_(canons, res):
    fig, axes = plt.subplots(1, 2, figsize=(14, 7.6))
    fig.patch.set_facecolor("#fcfcfb")
    for ax, t, title in ((axes[0], "before", "前（main・#58 の前）"), (axes[1], "after", "後（#163・#58）")):
        d = canons[t]
        reg = {}
        for n in d["nodes"]:
            reg.setdefault(k5((n["lat"], n["lon"])), set()).add(n.get("region"))
        segs_c, segs_t, segs_hv = [], [], []
        for e in d["edges"]:
            pts = e.get("path") or [e["a"], e["b"]]
            if not any(BOX[0] <= p[1] <= BOX[1] and BOX[2] <= p[0] <= BOX[3] for p in pts):
                continue
            ra, rb = reg.get(k5(e["a"]), set()), reg.get(k5(e["b"]), set())
            east = bool(ra) and bool(rb) and ra <= {"tokyo", "tohoku"} and rb <= {"tokyo", "tohoku"}
            seg = [(p[1], p[0]) for p in pts]
            if east and float(e.get("kv") or 0) >= 275:
                segs_hv.append(seg)
            elif east:
                segs_t.append(seg)
            else:
                segs_c.append(seg)
        ax.add_collection(LineCollection(segs_hv, colors="#f2b8b5", linewidths=1.2, zorder=1))
        ax.add_collection(LineCollection(segs_c, colors=CHUBU, linewidths=1.0, alpha=0.75, zorder=2))
        ax.add_collection(LineCollection(segs_t, colors=TOKYO, linewidths=2.8, zorder=3))
        for n in d["nodes"]:
            if n.get("sub") == 1 and BOX[0] <= n["lon"] <= BOX[1] and BOX[2] <= n["lat"] <= BOX[3]:
                east = n.get("region") in ("tokyo", "tohoku")
                ax.plot(n["lon"], n["lat"], "s", ms=11 if east else 3.5, color=TOKYO if east else CHUBU,
                        mec=INK if east else "#fcfcfb", mew=1.0 if east else 0.6, zorder=4)
        # 発電所と、東の網での付き先
        ge = res["east"][t]["plants"]
        for nm, (la, lo) in PLANT_XY.items():
            hydro = "水力" in nm or "発電所" in nm
            ax.plot(lo, la, "^" if hydro else "o", ms=9, color=INK, mec="#fcfcfb", mew=0.8, zorder=6)
            for g in ge.get(nm, []):
                ax.annotate("", (g["lon"], g["lat"]), xytext=(lo, la), textcoords="data", zorder=5,
                            arrowprops=dict(arrowstyle="->", color=TOKYO, lw=1.4, ls="--", shrinkA=5, shrinkB=4))
        lab = {"小諸市立東小学校": ("小諸の小学校 2 校（太陽光・地物 7 件）", (-8, 10), "right"),
               "八那池第一水力発電所": ("八那池第一水力（中部電力）", (-10, 8), "right"),
               "松原発電所": ("松原発電所（水力・中部電力）", (-10, -14), "right"),
               "大字高野町佐久穂町発電所": ("名前の無い水力（佐久穂町・\n東京電力海瀬発電所の点から 0.19 km）", (-10, -4), "right")}
        for nm, (txt, off, ha) in lab.items():
            la, lo = PLANT_XY[nm]
            ax.annotate(txt, (lo, la), xytext=off, textcoords="offset points", fontsize=8.5, color=INK, ha=ha,
                        bbox=dict(boxstyle="round,pad=0.15", fc="#fcfcfb", ec="none", alpha=0.85), zorder=7)
        if t == "before":
            ax.annotate("小海町変電所_2: 東京の点は無い\n（ノード衛生 #35 が幻の断片として消していた）", (138.46627, 36.05629),
                        xytext=(40, -48), textcoords="offset points", fontsize=8.5, color=INK, ha="left",
                        arrowprops=dict(arrowstyle="-", color=INK2, lw=0.6),
                        bbox=dict(boxstyle="round,pad=0.15", fc="#fcfcfb", ec="none", alpha=0.85), zorder=7)
            ax.annotate("軽井沢東変電所（東京の写し・66 kV）\n← 小学校の太陽光が東でここに付いていた", (138.64481, 36.34303),
                        xytext=(-20, 20), textcoords="offset points", fontsize=8.5, color=INK, ha="right",
                        bbox=dict(boxstyle="round,pad=0.15", fc="#fcfcfb", ec="none", alpha=0.85), zorder=7)
        else:
            ax.annotate("小海町変電所_2 の東京の点（後だけ）。東京の写しの\n勝間〜小海町変電所線（赤の太線）と 4 バスの\n"
                        "切れ端になり、水力 3 件が東でここに付いた", (138.46627, 36.05629), xytext=(40, -48),
                        textcoords="offset points", fontsize=8.5, color=INK, ha="left",
                        arrowprops=dict(arrowstyle="-", color=INK2, lw=0.6),
                        bbox=dict(boxstyle="round,pad=0.15", fc="#fcfcfb", ec="none", alpha=0.85), zorder=7)
        ax.set_xlim(BOX[0], BOX[1])
        ax.set_ylim(BOX[2], BOX[3])
        ax.set_aspect(1.24)
        ax.set_xticks([])
        ax.set_yticks([])
        for s_ in ax.spines.values():
            s_.set_color(MUTED)
        ax.set_title(f"{title}\n赤の四角 = 東の変電所の点・赤の太線 = 東の 154 kV 以下の線・薄赤 = 上を通る東京電力の 500 kV\n"
                     "青 = 西（中部）・赤い点線の矢印 = 東の網での付き先",
                     fontsize=9.5, color=INK, loc="left")
    fig.text(0.01, 0.015, "▲ = 水力・● = 太陽光。西の網では、前も後も 5 つとも中部の写しで付いている"
                          "（小学校 → 小諸市変電所、水力 → 小海町変電所_2・東京電力海瀬発電所の点）。",
             fontsize=8.5, color=INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(os.path.join(HERE, "fig_saku.png"), dpi=130, facecolor=fig.get_facecolor())
    print("→ fig_saku.png")


if __name__ == "__main__":
    main(*sys.argv[1:7])
