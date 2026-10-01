#!/usr/bin/env python3
"""公表インピーダンスの検証を **実線形** で地図に描く（直線ではなく）。

これまでの図は公表線の from→to を直線で結んでいたため「地図が直線だらけ」だった。
モデルのグラフ上で両端をつなぐ経路を Dijkstra で探し、その **実線形** を描く。
経路が取れない線だけ点線（＝モデルに線形が無いことを示す）。

対象は crosswalk の両端解決 全 423 本。X 比が計算できるものは色、
できないもの（並列重複・短距離・棄却）は灰色で「位置は分かる」ようにする。

出力: docs/reports/figs/impedance_routed_map.png
"""
from __future__ import annotations
import heapq, json, math, os, sys
from collections import defaultdict
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
NORM = Path(os.environ.get("AGJ_DISCLOSURE_NORM",
                           ROOT / "data/external/system_disclosure/normalized"))
FIGS = ROOT / "docs/reports/figs"
for _f in ("Hiragino Sans", "Hiragino Kaku Gothic ProN", "YuGothic"):
    plt.rcParams["font.family"] = _f
    break
plt.rcParams["axes.unicode_minus"] = False
BG = "#faf8f1"
SNAP_KM = 3.0        # 端点をモデルの頂点へ寄せる許容
MAX_RATIO = 3.0      # 経路/弦 がこれを超えたら経路として採らない


def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    return 6371*2*math.asin(math.sqrt(math.sin((la2-la1)/2)**2 +
        math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2))


def k5(p):
    return (round(p[0], 5), round(p[1], 5))


def build_graph(edges):
    adj = defaultdict(list)
    geo = {}
    for i, e in enumerate(edges):
        p = e.get("path") or [e["a"], e["b"]]
        w = sum(hav(p[j], p[j+1]) for j in range(len(p)-1)) or 0.001
        ka, kb = k5(e["a"]), k5(e["b"])
        adj[ka].append((kb, w, i)); adj[kb].append((ka, w, i))
        geo[i] = p
    grid = defaultdict(list)
    for v in adj:
        grid[(int(v[0]/0.05), int(v[1]/0.05))].append(v)
    return adj, geo, grid


def near(grid, p, rkm):
    cx, cy = int(p[0]/0.05), int(p[1]/0.05)
    out = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for v in grid.get((cx+dx, cy+dy), []):
                d = hav(p, v)
                if d <= rkm:
                    out.append((d, v))
    return sorted(out)[:8]


def route(adj, grid, A, B, chord):
    st, gl = near(grid, A, SNAP_KM), near(grid, B, SNAP_KM)
    if not st or not gl:
        return None
    goal = {v: d for d, v in gl}
    limit = max(chord * MAX_RATIO, chord + 20)
    dist, prev = {}, {}
    pq = [(d, i, v, None, None) for i, (d, v) in enumerate(st)]
    heapq.heapify(pq)
    seq = len(pq)
    hit = None
    while pq:
        dc, _, v, pv, ei = heapq.heappop(pq)
        if v in dist:
            continue
        dist[v] = dc; prev[v] = (pv, ei)
        if dc > limit:
            break
        if v in goal:
            hit = v; break
        for w, wt, wi in adj[v]:
            if w not in dist:
                seq += 1
                heapq.heappush(pq, (dc+wt, seq, w, v, wi))
    if hit is None:
        return None
    chain, eids = [hit], []
    v = hit
    while prev.get(v) and prev[v][0] is not None:
        eids.append(prev[v][1]); v = prev[v][0]; chain.append(v)
    chain.reverse(); eids.reverse()
    return chain, eids, dist[hit] + goal[hit]


def main():
    cw = pd.read_csv(NORM / "crosswalk_impedance_to_model.csv")
    cw = cw[cw.both_resolved].copy()
    # 比は「並列重複除去後」の代表 1 本にしか付いていない。1L/2L は同一区間・
    # 同一値なので、回線番号を落としたキーで全回線に配る（灰色を減らす）。
    import re as _re
    _circ = _re.compile(r"[0-9０-９]*[LＬ]$|[0-9０-９]+回線$|[0-9０-９]+号線$")
    _base = lambda s_: _circ.sub("", str(s_)).strip()
    try:
        cmp_ = pd.read_csv(NORM / "compare_observed_derived_impedance.csv")
        ratio = {}
        for _, r in cmp_.iterrows():
            if r.X_derived_pct > 0:
                ratio[(r.utility, _base(r.line_name))] = r.X_pct / r.X_derived_pct
    except Exception:
        ratio = {}
    built = json.loads((ROOT / "docs/data/built/all.json").read_text())
    edges = built["edges"]
    adj, geo, grid = build_graph(edges)
    print(f"グラフ頂点 {len(adj)} / 公表(両端解決) {len(cw)} 本")

    k = math.cos(math.radians(36.0))
    fig, ax = plt.subplots(figsize=(11.0, 10.6), facecolor=BG)
    ax.set_facecolor("#fffdf6")
    for e in edges:                                   # 背景
        p = e.get("path") or [e["a"], e["b"]]
        if len(p) > 6:
            p = p[::4] + [p[-1]]
        ax.plot([q[1]*k for q in p], [q[0] for q in p], color="#dfe5ea", lw=.32,
                alpha=.8, zorder=1)
    cmap = plt.get_cmap("coolwarm")
    lo, hi = 0.7, 1.8
    n_route = n_line = n_drop = 0
    routed = []
    for _, r in cw.iterrows():
        A, B = [r.from_lat, r.from_lon], [r.to_lat, r.to_lon]
        chord = hav(A, B)
        if chord < 0.3:
            continue
        lim = {66: 50, 77: 50, 110: 100, 132: 100, 154: 100, 187: 150,
               220: 150, 275: 250, 500: 400}.get(int(r.voltage_kv), 300)
        if chord > lim:          # 同名異所の誤マッチ（#47）は描かない
            n_drop += 1
            continue
        rt = route(adj, grid, A, B, chord)
        rr = ratio.get((r.utility, _base(r.line_name)))
        col = cmap((min(max(rr, lo), hi)-lo)/(hi-lo)) if rr and rr == rr else "#9aa5ae"
        lw = 1.0 + min(2.4, chord/45)
        if rt:
            _, eids, rlen = rt
            routed.append({"utility": r.utility, "line_name": r.line_name,
                           "voltage_kv": r.voltage_kv, "chord_km": round(chord, 3),
                           "route_km": round(rlen, 3)})
            n_route += 1
            for ei in eids:
                p = geo[ei]
                ax.plot([q[1]*k for q in p], [q[0] for q in p], color=col, lw=lw,
                        zorder=4, alpha=.95, solid_capstyle="round")
        else:
            n_line += 1
            ax.plot([A[1]*k, B[1]*k], [A[0], B[0]], color=col, lw=lw*.9,
                    ls=(0, (4, 3)), zorder=3, alpha=.85)
    ax.set_ylim(30.3, 45.8); ax.set_xlim(128.2*k, 146.4*k)
    ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color("#dcd8cc")
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(lo, hi))
    cb = fig.colorbar(sm, ax=ax, fraction=.03, pad=.02)
    cb.set_label("X 公表 / X モデル（灰＝比を算出していない線）", fontsize=10)
    cb.outline.set_edgecolor("#dcd8cc")
    ax.set_title("公表インピーダンスで裏の取れた線を「実線形」で描く\n"
                 f"両端解決 {len(cw)} 本 → 経路が取れた {n_route} 本は実線形で描画"
                 + (f"／ 経路なし {n_line} 本は点線（線形が未収載）" if n_line else "")
                 + (f"／ 誤マッチ {n_drop} 本は除外" if n_drop else ""),
                 fontsize=11.5, loc="left", color="#1a1a17", pad=12)
    handles = [Line2D([], [], color="#cf4f5f", lw=2.4, label="経路が取れた（実線形で描画）"),
               Line2D([], [], color="#9aa5ae", lw=2.0, ls=(0, (4, 3)),
                      label="経路が無い（直線・線形は未収載）"),
               Line2D([], [], color="#dfe5ea", lw=1.6, label="全国送電網")]
    ax.legend(handles=handles, loc="upper right", fontsize=9.5, frameon=True,
              facecolor="white", edgecolor="#dcd8cc")
    fig.tight_layout()
    out = FIGS / "impedance_routed_map.png"
    fig.savefig(out, dpi=180, facecolor=BG); plt.close(fig)
    import csv as _csv
    rp = FIGS.parent / "route_len.csv"
    with open(rp, "w", encoding="utf-8", newline="") as fh:
        w = _csv.DictWriter(fh, fieldnames=["utility", "line_name", "voltage_kv",
                                            "chord_km", "route_km"])
        w.writeheader(); w.writerows(routed)
    print(f"  {out.name}  実線形 {n_route} / 直線 {n_line}")
    print(f"  経路長を {rp.name} に出力（{len(routed)} 本）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
