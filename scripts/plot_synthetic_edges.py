#!/usr/bin/env python3
"""「直線で無理やり繋いでいる」箇所を全国地図に出す。

正典 `docs/data/built/all.json` のエッジを出自で塗り分ける:
  OSM実線形     — 地図に実在する線をそのまま辿ったもの（薄灰）
  disclosure    — 公表資料で接続が確定したが、線形が無いので**直線**で張ったもの（赤）
  tie / dc_tie  — 連系線（実在するが幾何を持たない・青）
  stub          — EGGC の取付スタブ（緑・ごく短い）

出力: docs/reports/figs/synthetic_edges_map.png
      docs/reports/figs/synthetic_edges_top.png（長い直線の周辺を拡大）
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BUILT = ROOT / "docs/data/built/all.json"
TRACE_CUR = ROOT / "docs/data/eggc_trace_current.json"
FIGS = ROOT / "docs/reports/figs"

for _fam in ("Hiragino Sans", "Hiragino Kaku Gothic ProN", "YuGothic", "Arial Unicode MS"):
    plt.rcParams["font.family"] = _fam
    break
plt.rcParams["axes.unicode_minus"] = False

BG = "#faf8f1"
C_OSM = "#9fb4c9"
C_DIS = "#cf4f5f"
C_TIE = "#3a6ea5"
C_STUB = "#1f9e8a"


def hav(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    return 6371 * 2 * math.asin(math.sqrt(
        math.sin((la2 - la1) / 2) ** 2
        + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2))


def cat(e):
    if e.get("stub"):
        return "stub"
    if "dc_tie" in e or "tie" in e:
        return "tie"
    if "same_site" in e:
        return "same_site"
    if "conn_class" in e or "disclosure" in e:
        return "dis"
    return "osm"


def xy(pts, k):
    return [p[1] * k for p in pts], [p[0] for p in pts]


def main() -> int:
    b = json.loads(BUILT.read_text(encoding="utf-8"))
    E = b["edges"]
    groups = {"osm": [], "dis": [], "tie": [], "stub": [], "same_site": []}
    for e in E:
        groups[cat(e)].append(e)
    dis = sorted(groups["dis"], key=lambda e: -hav(e["a"], e["b"]))
    dis_km = sum(hav(e["a"], e["b"]) for e in dis)

    # 現行判定（なぜ直線のままなのか）を名前で引けるようにする
    reason = {}
    if TRACE_CUR.exists():
        for r in json.loads(TRACE_CUR.read_text(encoding="utf-8"))["records"]:
            reason[(round(r["a"][0], 3), round(r["a"][1], 3))] = r["verdict"]

    k = math.cos(math.radians(36.0))
    fig, ax = plt.subplots(figsize=(10.5, 10.0), facecolor=BG)
    ax.set_facecolor("#fffdf6")
    for e in groups["osm"]:                       # 背景（間引いて軽く）
        p = e.get("path") or [e["a"], e["b"]]
        if len(p) > 6:
            p = p[::3] + [p[-1]]
        x, y = xy(p, k)
        ax.plot(x, y, color=C_OSM, lw=.35, alpha=.55, zorder=1,
                solid_capstyle="butt")
    for e in groups["tie"]:
        x, y = xy([e["a"], e["b"]], k)
        ax.plot(x, y, color=C_TIE, lw=1.6, ls=(0, (6, 3)), zorder=3, alpha=.9)
    for e in groups["dis"]:
        L = hav(e["a"], e["b"])
        x, y = xy([e["a"], e["b"]], k)
        ax.plot(x, y, color=C_DIS, lw=.8 + min(2.6, L / 8), zorder=4, alpha=.92,
                solid_capstyle="round")
    for e in groups["stub"]:
        x, y = xy([e["a"], e["b"]], k)
        ax.plot(x, y, color=C_STUB, lw=2.0, zorder=5)

    for e in dis[:8]:                              # 長い順に注記
        mid = ((e["a"][0] + e["b"][0]) / 2, (e["a"][1] + e["b"][1]) / 2)
        x, y = xy([mid], k)
        ax.annotate(f"{(e.get('name') or '')[:14]} {hav(e['a'], e['b']):.0f}km",
                    (x[0], y[0]), fontsize=7.5, color="#8a2f3c", zorder=9,
                    xytext=(9, 5), textcoords="offset points",
                    bbox=dict(boxstyle="round,pad=.2", fc="white", ec=C_DIS,
                              alpha=.85, lw=.6))

    # 沖縄まで入れると本土が小さくなるので本土に寄せる（沖縄は本数を注記）
    oki = [e for e in dis if e["a"][0] < 28.0]
    ax.set_ylim(30.3, 45.8)
    ax.set_xlim(128.2 * k, 146.4 * k)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color("#dcd8cc")
    ax.text(.012, .012, f"※本土のみ表示（沖縄の直線接続は {len(oki)} 本）",
            transform=ax.transAxes, fontsize=9, color="#928f84")
    tot_n = len(E)
    tot_km = sum(hav(e["a"], e["b"]) if not e.get("path") else
                 sum(hav(e["path"][i], e["path"][i + 1])
                     for i in range(len(e["path"]) - 1)) for e in E)
    ax.set_title(
        "「直線で繋いでいる」のはどこか — 出自で塗り分けた全国送電網\n"
        f"OSM実線形 {len(groups['osm']):,} 本 ({len(groups['osm'])/tot_n*100:.1f}%) に対し、"
        f"直線で張った実証接続は {len(dis)} 本・{dis_km:,.0f} km "
        f"（本数で {len(dis)/tot_n*100:.1f}% / 亘長で {dis_km/tot_km*100:.1f}%）",
        fontsize=12.5, loc="left", color="#1a1a17", pad=12)
    handles = [
        Line2D([], [], color=C_OSM, lw=1.6, label="OSM実線形（地図の線をそのまま辿った）"),
        Line2D([], [], color=C_DIS, lw=2.2, label="実証接続の直線（線形が無く直接繋いだ）"),
        Line2D([], [], color=C_TIE, lw=1.8, ls=(0, (6, 3)), label="連系線・直流連系（実在するが幾何なし）"),
        Line2D([], [], color=C_STUB, lw=2.2, label="EGGC の取付スタブ"),
    ]
    ax.legend(handles=handles, loc="upper right", fontsize=9.5, frameon=True,
              facecolor="white", edgecolor="#dcd8cc")
    fig.tight_layout()
    out = FIGS / "synthetic_edges_map.png"
    fig.savefig(out, dpi=185, facecolor=BG)
    plt.close(fig)
    print(f"  {out.name}")

    # --- 長い直線の周辺を拡大（なぜ直線なのかが見える） ---
    top = dis[:6]
    fig, axes = plt.subplots(2, 3, figsize=(13.5, 9.2), facecolor=BG)
    for ax, e in zip(axes.ravel(), top):
        A, B = e["a"], e["b"]
        lat0 = (A[0] + B[0]) / 2
        kk = math.cos(math.radians(lat0))
        m = 0.06
        la = [min(A[0], B[0]) - m, max(A[0], B[0]) + m]
        lo = [min(A[1], B[1]) - m, max(A[1], B[1]) + m]
        for o in groups["osm"]:
            p = o.get("path") or [o["a"], o["b"]]
            if not any(la[0] <= q[0] <= la[1] and lo[0] <= q[1] <= lo[1] for q in p):
                continue
            x, y = xy(p, kk)
            ax.plot(x, y, color=C_OSM if o.get("main") else "#e0a6ae",
                    lw=1.1, alpha=.75, zorder=2)
        x, y = xy([A, B], kk)
        ax.plot(x, y, color=C_DIS, lw=2.6, ls=(0, (6, 3)), zorder=5)
        ax.plot(*xy([A], kk), "o", color=C_DIS, ms=5, mec="white", mew=1.1, zorder=6)
        ax.plot(*xy([B], kk), "o", color=C_DIS, ms=5, mec="white", mew=1.1, zorder=6)
        v = reason.get((round(A[0], 3), round(A[1], 3)))
        why = {"no_route": "OSMに線が無い", "kept_detour": "近くの線は別系統",
               "replaced": "吸着候補"}.get(v, "判定記録なし")
        ax.set_title(f"{(e.get('name') or '(無名)')[:20]}　{hav(A, B):.1f} km "
                     f"{e.get('kv') or 0:.0f}kV\n{why}",
                     fontsize=10, color="#1a1a17", pad=6)
        ax.set_xlim(lo[0] * kk, lo[1] * kk)
        ax.set_ylim(la[0], la[1])
        ax.set_aspect("equal")
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_facecolor("#fffdf6")
        for s in ax.spines.values():
            s.set_color("#dcd8cc")
    fig.suptitle("長い直線ほど「無理」が見える — 上位6本の周辺（破線＝直線で張った接続）",
                 fontsize=13, x=.035, ha="left", y=.985, color="#1a1a17")
    fig.tight_layout(rect=[0, 0, 1, .95])
    out2 = FIGS / "synthetic_edges_top.png"
    fig.savefig(out2, dpi=175, facecolor=BG)
    plt.close(fig)
    print(f"  {out2.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
