#!/usr/bin/env python3
"""EGGC で実線形に置き換わった線を **全数** 画像化する。

台帳 `routed_disclosure_edges.json` の累積 replaced が正（現時点 14 本）。
うち 12 本は適用前スナップショットで再走できるが、後発の 2 本は
現行正典からしか経路を復元できない（＝断片が既に main 化しているので
before の「赤い断片」は当時の色では描けない。図に注記する）。

出力（docs/reports/figs/）:
  eggc_gallery_all.png       全 14 本を 1 枚に（直線コードと実線形の重ね描き）
  eggc_area_<n>_<region>.png エリア別（30km 以内で連結する塊ごと）
  eggc_case_<nn>_<name>.png  特徴的な 10 本の before / after 2 パネル
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plot_eggc_figs import (  # noqa: E402
    BG, C_CHORD, C_MAIN, C_OFF, C_STUB, draw_scene, route_edge_idx, xy,
)

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs/reports/routed_disclosure_edges.json"
TRACE_PRE = ROOT / "docs/data/eggc_trace.json"
TRACE_CUR = ROOT / "docs/data/eggc_trace_current.json"
FIGS = ROOT / "docs/reports/figs"

REGION_JA = {"hokkaido": "北海道", "tohoku": "東北", "tokyo": "東京", "chubu": "中部",
             "hokuriku": "北陸", "kansai": "関西", "chugoku": "中国", "shikoku": "四国",
             "kyushu": "九州", "okinawa": "沖縄"}
CLUSTER_KM = 50.0


def hav(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    return 6371 * 2 * math.asin(math.sqrt(
        math.sin((la2 - la1) / 2) ** 2
        + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2))


def k4(p):
    return (round(p[0], 4), round(p[1], 4))


def load_cases():
    """台帳14本に、scene 付きトレースを紐付ける（端点一致）。"""
    led = json.loads(LEDGER.read_text(encoding="utf-8"))["replaced"]
    recs = []
    for path, tag in ((TRACE_PRE, "pre"), (TRACE_CUR, "current")):
        if path.exists():
            for r in json.loads(path.read_text(encoding="utf-8"))["records"]:
                if r.get("scene"):
                    recs.append((tag, r))
    out, missing = [], []
    for i, L in enumerate(led):
        key = {k4(L["a"]), k4(L["b"])}
        hit = None
        for tag, r in recs:                      # 適用前スナップショット優先
            if {k4(r["a"]), k4(r["b"])} == key and (hit is None or tag == "pre"):
                hit = (tag, r)
                if tag == "pre":
                    break
        if hit is None:
            missing.append(L["name"])
            continue
        tag, r = hit
        out.append({**r, "_src": tag, "_led": L,
                    "grow": (L["route_km"] / L["chord_km"] - 1) * 100})
    # 台帳の重複排除キーは端点の5桁丸めなので、端点が数十m違うと同じ線が二重に載る。
    # スナップ先の頂点(vA/vB)が一致するものは同一線とみなして印を付ける。
    for i, c in enumerate(out):
        c["_dup"] = False
    for i in range(len(out)):
        for j in range(i + 1, len(out)):
            va, vb = out[i].get("vA"), out[i].get("vB")
            wa, wb = out[j].get("vA"), out[j].get("vB")
            if not (va and vb and wa and wb):
                continue
            if max(hav(va, wa), hav(vb, wb)) < 0.01:
                out[j]["_dup"] = True      # 後に来た方を重複扱い
    return out, led, missing


def region_of(group) -> str:
    """地方名は**クラスタ全体**の周辺ノードの多数決で決める。
    1本だけで見ると誤る（四国東部は kansai/chugoku のノードが重なって拾われる）。"""
    cnt = {}
    for rec in group:
        for n in rec["scene"]["nodes"]:
            w = (n.get("name") or "").split(" ")[0].lower()
            if w in REGION_JA:
                cnt[w] = cnt.get(w, 0) + 1
    if not cnt:
        return "unknown"
    return max(cnt.items(), key=lambda kv: kv[1])[0]


def cluster(cases):
    """端点間 30km 以内で連結する塊にまとめる（単純な union-find）。"""
    par = list(range(len(cases)))

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x

    for i in range(len(cases)):
        for j in range(i + 1, len(cases)):
            pts_i = [cases[i]["a"], cases[i]["b"]]
            pts_j = [cases[j]["a"], cases[j]["b"]]
            if min(hav(p, q) for p in pts_i for q in pts_j) <= CLUSTER_KM:
                par[find(i)] = find(j)
    groups = {}
    for i, c in enumerate(cases):
        groups.setdefault(find(i), []).append(c)
    out = sorted(groups.values(), key=lambda g: -len(g))
    for g in out:
        reg = region_of(g)
        lead = max(g, key=lambda c: c["_led"]["chord_km"])["name"]
        lead = re.split(r"[（(]", lead)[0][:8]
        for c in g:
            c["_region"] = reg
            c["_cluster"] = f"{REGION_JA.get(reg, reg)}・{lead}周辺"
    return out


def safe(name):
    return re.sub(r"[^0-9A-Za-zぁ-んァ-ヶ一-龠]+", "_", name)[:22]


def fig_all(cases):
    n = len(cases)
    cols = 4
    rows = math.ceil(n / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(3.4 * cols, 3.5 * rows),
                             facecolor=BG)
    axes = axes.ravel()
    for ax, c in zip(axes, cases):
        draw_scene(ax, c, after=True, mode="both", lw_scale=.8)
        L = c["_led"]
        note = "" if c["_src"] == "pre" else " ※後発"
        if c["_dup"]:
            note += " ※二重登録"
        ax.set_title(f"{c['name'][:17]}{note}\n"
                     f"{L['chord_km']:.1f} → {L['route_km']:.1f} km "
                     f"(+{c['grow']:.0f}%) · {c['_cluster']}",
                     fontsize=8.5, color="#cf4f5f" if c["_dup"] else "#1a1a17", pad=5)
    for ax in axes[n:]:
        ax.axis("off")
    handles = [Line2D([], [], color=C_MAIN, lw=2, label="実線形（採用された経路）"),
               Line2D([], [], color=C_OFF, lw=2, label="周辺の未接続断片"),
               Line2D([], [], color=C_CHORD, lw=2, ls=(0, (5, 3)), label="直線コード chord"),
               Line2D([], [], color=C_STUB, lw=2, label="取付スタブ")]
    fig.legend(handles=handles, loc="lower center", ncol=4, frameon=False, fontsize=10,
               bbox_to_anchor=(.5, .008))
    uniq = sum(1 for c in cases if not c["_dup"])
    fig.suptitle(f"EGGC で直線が実線形に置き換わった線 — 台帳の全 {n} 件"
                 + (f"（実線数 {uniq} 本・赤字は二重登録）" if uniq != n else "")
                 + "　破線＝置換前の直線、太線＝採用された実線形",
                 fontsize=13.5, x=.5, y=.985, color="#1a1a17")
    fig.tight_layout(rect=[0, .045, 1, .965])
    out = FIGS / "eggc_gallery_all.png"
    fig.savefig(out, dpi=170, facecolor=BG)
    plt.close(fig)
    print(f"  {out.name}  ({n} 本)")


def fig_area(gi, group):
    """同じエリアの線をまとめて1枚に（周辺系統ごと）。"""
    lat0 = sum(c["a"][0] for c in group) / len(group)
    fig, ax = plt.subplots(figsize=(9.4, 7.4), facecolor=BG)
    ax.set_facecolor("#fffdf6")
    drawn = set()
    for c in group:                     # 背景（同じ線を二度描かない）
        sc, on = c["scene"], route_edge_idx(c)
        for i, e in enumerate(sc["edges"]):
            key = (round(e["path"][0][0], 5), round(e["path"][0][1], 5),
                   round(e["path"][-1][0], 5), round(e["path"][-1][1], 5))
            if key in drawn:
                continue
            drawn.add(key)
            x, y = xy(e["path"], lat0)
            if i in on:
                continue                # 経路は後段で最前面に
            ax.plot(x, y, color=C_MAIN if e["main"] else C_OFF,
                    lw=1.4 if e["main"] else 1.2, alpha=.45, zorder=2,
                    solid_capstyle="round")
    for c in group:                     # 経路・コード・スタブ
        sc, on = c["scene"], route_edge_idx(c)
        for i in on:
            x, y = xy(sc["edges"][i]["path"], lat0)
            ax.plot(x, y, color=C_MAIN, lw=3.0, zorder=4, solid_capstyle="round")
        x, y = xy([c["a"], c["b"]], lat0)
        ax.plot(x, y, color=C_CHORD, lw=2.0, ls=(0, (5, 3)), zorder=5)
        for p, v, km in ((c["a"], c.get("vA"), c.get("stub_a_km", 0)),
                         (c["b"], c.get("vB"), c.get("stub_b_km", 0))):
            if v and km and km > 0.001:
                x, y = xy([p, v], lat0)
                ax.plot(x, y, color=C_STUB, lw=2.6, zorder=6)
        for p in (c["a"], c["b"]):
            x, y = xy([p], lat0)
            ax.plot(x, y, "o", color=C_CHORD, ms=5.5, mec="white", mew=1.1, zorder=7)
    # ラベルは経路上に等間隔で置く（全部を中点に置くと重なって読めない）
    for i, c in enumerate(sorted(group, key=lambda c: c["a"][0])):
        pts = c.get("path") or [c["a"], c["b"]]
        f = 0.28 + 0.44 * (i / max(1, len(group) - 1))
        mx = pts[int(len(pts) * f)]
        x, y = xy([mx], lat0)
        ax.annotate(re.split(r"[（(]", c["name"])[0][:14], (x[0], y[0]),
                    fontsize=8, color="#1a1a17", ha="center", va="center", zorder=8,
                    bbox=dict(boxstyle="round,pad=.22", fc="white", ec="#dcd8cc",
                              alpha=.88, lw=.7))
    # 置換線が主役なので、そこに寄せてクロップする（周辺線の余白で絵が小さくなる）
    fp = [p for c in group for p in ((c.get("path") or []) + [c["a"], c["b"]])]
    mlat, mlon = 0.02, 0.02
    ax.set_ylim(min(p[0] for p in fp) - mlat, max(p[0] for p in fp) + mlat)
    k = math.cos(math.radians(lat0))
    ax.set_xlim((min(p[1] for p in fp) - mlon) * k, (max(p[1] for p in fp) + mlon) * k)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color("#dcd8cc")
    tot_c = sum(c["_led"]["chord_km"] for c in group)
    tot_r = sum(c["_led"]["route_km"] for c in group)
    name = group[0]["_cluster"]
    ax.set_title(f"{name} — この塊で {len(group)} 本が実線形に置換\n"
                 f"合計 {tot_c:.1f} → {tot_r:.1f} km (+{(tot_r/tot_c-1)*100:.0f}%)",
                 fontsize=13, loc="left", color="#1a1a17", pad=10)
    handles = [Line2D([], [], color=C_MAIN, lw=2.6, label="採用された実線形"),
               Line2D([], [], color=C_OFF, lw=2, label="周辺の未接続断片"),
               Line2D([], [], color=C_CHORD, lw=2, ls=(0, (5, 3)), label="置換前の直線コード"),
               Line2D([], [], color=C_STUB, lw=2, label="取付スタブ")]
    ax.legend(handles=handles, loc="lower right", fontsize=9, frameon=False)
    fig.tight_layout()
    out = FIGS / f"eggc_area_{gi+1}_{safe(name)}.png"
    fig.savefig(out, dpi=175, facecolor=BG)
    plt.close(fig)
    print(f"  {out.name}  ({len(group)} 本)")


def pick_featured(cases, k=10):
    """特徴的な k 本。選定理由も返す（図のキャプションに出す）。"""
    picked, why = [], {}
    pool = [c for c in cases if not c["_dup"]]     # 二重登録の片割れは除く

    def add(c, reason):
        if c["name"] not in {p["name"] for p in picked} and len(picked) < k:
            picked.append(c)
            why[id(c)] = reason

    cases = pool
    add(max(cases, key=lambda c: c["_led"]["chord_km"]), "最長の直線コード")
    add(min(cases, key=lambda c: c["_led"]["chord_km"]), "最短の直線コード")
    add(max(cases, key=lambda c: c["grow"]), "伸び率が最大（直線が最も嘘だった）")
    add(min(cases, key=lambda c: c["grow"]), "伸び率が最小（直線でもほぼ正しかった）")
    for c in cases:
        if c["_src"] != "pre":
            add(c, "後発（regen 時に自動適用された）")
    seen = set()
    for c in sorted(cases, key=lambda c: -c["_led"]["chord_km"]):
        if c["_cluster"] not in seen:
            seen.add(c["_cluster"])
            add(c, f"{c['_cluster']} の代表")
    for c in sorted(cases, key=lambda c: -c["_led"]["chord_km"]):
        add(c, "長い順に補充")
    return picked, why


def fig_case(idx, c, reason):
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 5.2), facecolor=BG)
    for ax, after in zip(axes, (False, True)):
        draw_scene(ax, c, after)
    L = c["_led"]
    axes[0].set_title(f"before — 直線コード {L['chord_km']:.1f} km",
                      fontsize=11, color="#1a1a17", loc="left", pad=8)
    axes[1].set_title(f"after — 実線形 {L['route_km']:.1f} km "
                      f"(+{c['grow']:.0f}%) ＋ スタブ "
                      f"{c.get('stub_a_km',0)+c.get('stub_b_km',0):.2f} km",
                      fontsize=11, color="#1a1a17", loc="left", pad=8)
    src = ("適用前スナップショットで再走" if c["_src"] == "pre"
           else "※後発ケース。現行正典からの復元のため、断片は既に本系統に合流している")
    fig.suptitle(f"{idx:02d}. {c['name']}（{c.get('kv') or L.get('kv') or '?'} kV・"
                 f"{c['_cluster']}） — {reason}",
                 fontsize=12.5, x=.045, ha="left", y=.975, color="#1a1a17")
    fig.text(.045, .028, src, fontsize=9, color="#928f84")
    handles = [Line2D([], [], color=C_MAIN, lw=2, label="本系統 main"),
               Line2D([], [], color=C_OFF, lw=2, label="浮いた断片 off-main"),
               Line2D([], [], color=C_CHORD, lw=2, ls=(0, (5, 3)), label="直線コード"),
               Line2D([], [], color=C_STUB, lw=2, label="取付スタブ")]
    fig.legend(handles=handles, loc="lower center", ncol=4, frameon=False,
               fontsize=9.5, bbox_to_anchor=(.55, .003))
    fig.tight_layout(rect=[0, .06, 1, .93])
    out = FIGS / f"eggc_case_{idx:02d}_{safe(c['name'])}.png"
    fig.savefig(out, dpi=170, facecolor=BG)
    plt.close(fig)
    print(f"  {out.name}  — {reason}")


def main() -> int:
    FIGS.mkdir(parents=True, exist_ok=True)
    cases, led, missing = load_cases()
    print(f"台帳の置換 {len(led)} 本 / 図にできた {len(cases)} 本"
          + (f" / 経路を復元できず {missing}" if missing else ""))
    groups = cluster(cases)
    print(f"エリア（{CLUSTER_KM:.0f}km で連結）: "
          + " ・".join(f"{g[0]['_cluster']}={len(g)}本" for g in groups))
    print("一覧:")
    fig_all(cases)
    print("エリア別:")
    for gi, g in enumerate(groups):
        fig_area(gi, g)
    print("特徴的な10本:")
    featured, why = pick_featured(cases, 10)
    for i, c in enumerate(featured, 1):
        fig_case(i, c, why[id(c)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
