#!/usr/bin/env python3
"""EGGC のスライド用図を、教材と同じトレースデータから描く。

  fig1  before / after  — 直線コードが OSM 実線形になる（代表ケース）
  fig2  証拠ゲート      — 90本の散布（chord × off-main比率）と閾値の効き
  fig3  何が変わって何が変わらないか — 判定内訳と線長の増分

出力: docs/reports/figs/eggc_*.png
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
TRACE = ROOT / "docs/data/eggc_trace.json"
FIGS = ROOT / "docs/reports/figs"

for _fam in ("Hiragino Sans", "Hiragino Kaku Gothic ProN", "YuGothic", "Arial Unicode MS"):
    plt.rcParams["font.family"] = _fam
    break
plt.rcParams["axes.unicode_minus"] = False

C_MAIN = "#3a6ea5"
C_OFF = "#cf4f5f"
C_CHORD = "#6f54c4"
C_STUB = "#1f9e8a"
BG = "#faf8f1"


def xy(pts, lat0):
    k = math.cos(math.radians(lat0))
    return [p[1] * k for p in pts], [p[0] for p in pts]


def route_edge_idx(rec):
    """このケースの経路を構成する scene エッジの添字。"""
    on = set()
    if not rec.get("path"):
        return on
    pk = {(round(p[0], 5), round(p[1], 5)) for p in rec["path"]}
    for i, e in enumerate(rec["scene"]["edges"]):
        hit = sum(1 for q in e["path"] if (round(q[0], 5), round(q[1], 5)) in pk)
        if hit >= max(2, len(e["path"]) * 0.6):
            on.add(i)
    return on


def draw_scene(ax, rec, after: bool, mode: str = "panel", lw_scale: float = 1.0):
    """mode='panel' は before/after の片側だけ。'both' は同じ絵に重ねる（一覧用）。"""
    sc = rec["scene"]
    lat0 = (sc["bbox"][0] + sc["bbox"][2]) / 2
    on = route_edge_idx(rec)
    both = mode == "both"
    for i, e in enumerate(sc["edges"]):
        x, y = xy(e["path"], lat0)
        if (after or both) and i in on:
            ax.plot(x, y, color=C_MAIN, lw=2.4 * lw_scale, zorder=3,
                    solid_capstyle="round")
        else:
            ax.plot(x, y, color=C_MAIN if e["main"] else C_OFF,
                    lw=(1.5 if e["main"] else 1.3) * lw_scale, alpha=.5, zorder=2,
                    solid_capstyle="round")
    A, B = rec["a"], rec["b"]
    if both or not after:
        x, y = xy([A, B], lat0)
        ax.plot(x, y, color=C_CHORD, lw=2.6 * lw_scale, ls=(0, (5, 3)), zorder=5)
    if both or after:
        for p, v, km in ((A, rec.get("vA"), rec.get("stub_a_km", 0)),
                         (B, rec.get("vB"), rec.get("stub_b_km", 0))):
            if v and km and km > 0.001:
                x, y = xy([p, v], lat0)
                ax.plot(x, y, color=C_STUB, lw=2.6 * lw_scale, zorder=6)
    for p in (A, B):
        x, y = xy([p], lat0)
        ax.plot(x, y, "o", color=C_CHORD, ms=6 * lw_scale, mec="white",
                mew=1.2, zorder=7)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color("#dcd8cc")
    ax.set_facecolor("#fffdf6")


def fig1(T):
    # 周辺の系統が写り込むケースを選ぶ（背景が薄いと「浮いた断片」の対比が伝わらない）
    reps = [r for r in T["records"] if r.get("scene") and r["verdict"] == "replaced"]
    rec = max(reps, key=lambda r: (len(r["scene"]["edges"]) >= 20, r["chord_km"]))
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.6), facecolor=BG)
    for ax, after in zip(axes, (False, True)):
        draw_scene(ax, rec, after)
    axes[0].set_title(f"before — 公表資料の論理接続を直線で張る\n"
                      f"chord {rec['chord_km']:.1f} km（実線形は赤い断片として浮いたまま）",
                      fontsize=11.5, color="#1a1a17", loc="left", pad=10)
    axes[1].set_title(f"after — 証拠ゲートを通り、実線形へ置換\n"
                      f"route {rec['route_km']:.1f} km ＋ 取付スタブ "
                      f"{rec['stub_a_km'] + rec['stub_b_km']:.2f} km（断片は本系統に合流）",
                      fontsize=11.5, color="#1a1a17", loc="left", pad=10)
    handles = [Line2D([], [], color=C_MAIN, lw=2, label="本系統 main"),
               Line2D([], [], color=C_OFF, lw=2, label="浮いた断片 off-main"),
               Line2D([], [], color=C_CHORD, lw=2, ls=(0, (5, 3)), label="直線コード chord"),
               Line2D([], [], color=C_STUB, lw=2, label="取付スタブ")]
    fig.legend(handles=handles, loc="lower center", ncol=4, frameon=False,
               fontsize=10, bbox_to_anchor=(.5, .015))
    fig.suptitle(f"EGGC：{rec['name']}（{rec.get('kv', '')} kV）",
                 fontsize=13.5, x=.055, ha="left", y=.975, color="#1a1a17")
    fig.tight_layout(rect=[0, .06, 1, .94])
    out = FIGS / "eggc_before_after.png"
    fig.savefig(out, dpi=190, facecolor=BG)
    plt.close(fig)
    print(f"  {out.name}  ({rec['name']})")


def fig2(T):
    s = T["summary"]
    th = T["params"]["off_share_min"]
    fig, ax = plt.subplots(figsize=(9.6, 5.4), facecolor=BG)
    ax.set_facecolor("#fffdf6")
    rep = [x for x in s if x["verdict"] == "replaced"]
    det = [x for x in s if x["verdict"] == "kept_detour"]
    non = [x for x in s if x["verdict"] == "no_route"]
    ax.scatter([x["chord_km"] for x in det], [x["off"] for x in det],
               s=44, color=C_OFF, alpha=.55, label=f"直線維持・別線迂回 {len(det)} 本", zorder=3)
    ax.scatter([x["chord_km"] for x in rep], [x["off"] for x in rep],
               s=78, color=C_STUB, edgecolor="white", lw=1.1,
               label=f"吸着・実線形に置換 {len(rep)} 本", zorder=4)
    ax.axhline(th, color="#b3812f", lw=1.6, ls="--", zorder=2)
    ax.text(ax.get_xlim()[1], th + .02, f" 証拠ゲート {th}", color="#b3812f",
            fontsize=10, ha="right", va="bottom")
    ax.set_xscale("log")
    ax.set_xlabel("直線コードの長さ chord [km]（対数）", fontsize=10.5)
    ax.set_ylabel("経路のうち off-main が占める比率", fontsize=10.5)
    ax.set_ylim(-.05, 1.12)
    ax.grid(alpha=.25, color="#dcd8cc")
    for sp in ax.spines.values():
        sp.set_color("#dcd8cc")
    ax.legend(loc="center left", fontsize=10, frameon=False)
    ax.set_title("証拠ゲートは、二つに割れる — 中間が無い\n"
                 f"（経路なし {len(non)} 本は判定以前に直線維持。図の外）",
                 fontsize=12.5, loc="left", color="#1a1a17", pad=10)
    fig.tight_layout()
    out = FIGS / "eggc_gate_scatter.png"
    fig.savefig(out, dpi=190, facecolor=BG)
    plt.close(fig)
    print(f"  {out.name}  (replaced={len(rep)} detour={len(det)} none={len(non)})")


def fig3(T):
    s, st = T["summary"], T["stats"]
    rep = [x for x in s if x["verdict"] == "replaced"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.4), facecolor=BG,
                                 gridspec_kw={"width_ratios": [1, 1.25]})
    for ax in (a1, a2):
        ax.set_facecolor("#fffdf6")
        for sp in ax.spines.values():
            sp.set_color("#dcd8cc")
    vals = [st["n_replaced"], st["n_kept_detour"], st["n_no_route"]]
    labs = ["吸着\n(実線形に置換)", "直線維持\n(別線迂回)", "直線維持\n(OSM未収載)"]
    a1.bar(labs, vals, color=[C_STUB, C_OFF, "#928f84"], width=.62)
    for i, v in enumerate(vals):
        a1.text(i, v + 1.2, str(v), ha="center", fontsize=12, fontweight="bold")
    a1.set_ylim(0, max(vals) * 1.22)
    a1.set_title(f"対象 {st['n_targets']} 本の判定内訳", fontsize=12, loc="left", pad=8)
    a1.tick_params(labelsize=9.5)
    a1.grid(axis="y", alpha=.22, color="#dcd8cc")

    rep = sorted(rep, key=lambda x: x["chord_km"])
    idx = range(len(rep))
    a2.barh([i - .2 for i in idx], [x["chord_km"] for x in rep], height=.38,
            color=C_CHORD, alpha=.75, label="before 直線 chord")
    a2.barh([i + .2 for i in idx], [x["route_km"] for x in rep], height=.38,
            color=C_MAIN, label="after 実線形 route")
    a2.set_yticks(list(idx))
    a2.set_yticklabels([x["name"][:16] for x in rep], fontsize=8.5)
    a2.set_xlabel("ブランチ長 [km]", fontsize=10)
    a2.legend(fontsize=9.5, frameon=False, loc="lower right")
    tot_c = sum(x["chord_km"] for x in rep)
    tot_r = sum(x["route_km"] for x in rep)
    a2.set_title(f"変わったのは幾何の質だけ（連結性 KPI は不変）\n"
                 f"吸着 12 本の合計 {tot_c:.0f} → {tot_r:.0f} km "
                 f"(+{(tot_r / tot_c - 1) * 100:.0f}%)",
                 fontsize=11.5, loc="left", pad=8)
    a2.grid(axis="x", alpha=.22, color="#dcd8cc")
    fig.tight_layout()
    out = FIGS / "eggc_summary.png"
    fig.savefig(out, dpi=190, facecolor=BG)
    plt.close(fig)
    print(f"  {out.name}")


def main() -> int:
    T = json.loads(TRACE.read_text(encoding="utf-8"))
    FIGS.mkdir(parents=True, exist_ok=True)
    print("EGGC 図を生成:")
    fig1(T); fig2(T); fig3(T)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
