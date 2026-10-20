#!/usr/bin/env python3
"""「2 導体と仮定すると鉄塔に 42 m が要る」を、段を追って読める図にする。

「導体数」は 1 相あたりの素導体の数（単導体／2 導体＝複導体）。
より線の素線数や回線数とは別。

impedance_calibration デッキの 9 枚目（42 m）の補足。要点は 1 つだけ:

    x = 2πf · 2×10⁻⁷ · ln(D / GMR)

なので、実測 x が決めるのは **D ÷ GMR という比** だけ。
2 導体（複導体）で GMR が約 7 倍になれば、同じ x を出すには D も約 7 倍が要る。

出力（docs/reports/figs/）:
  why42m_parts.png    部品図（線間距離 D と、電気的な太さ GMR）
  why42m_ratio.png    比 750 のものさし（単導体: 8 mm→6 m / 2 導体: 57 mm→42 m）
  why42m_curve.png    x–D 曲線（実測 x の水平線との交点が 6 m と 42 m）
  why42m_perline.png  線ごとの必要な D（単導体仮定と 2 導体仮定を線で結ぶ）

線ごとの図は data/external/system_disclosure/normalized（.gitignore・再配布不可）を読む。
**線名は出さない**（点と集計のみ）。無ければその図だけ飛ばす。
"""
from __future__ import annotations

import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
FIGS = ROOT / "docs/reports/figs"
NORM = ROOT / "data/external/system_disclosure/normalized"
if not NORM.exists() and ROOT.parent.name == "worktrees":   # worktree からは本体の data を読む
    NORM = ROOT.parents[2] / "data/external/system_disclosure/normalized"
for _f in ("Hiragino Sans", "Hiragino Kaku Gothic ProN", "YuGothic"):
    plt.rcParams["font.family"] = _f
    break
plt.rcParams["axes.unicode_minus"] = False

BG, PANEL = "#faf8f1", "#fffdf6"
INK, INK2, MUTED, RULE = "#1a1a17", "#52504a", "#8a877d", "#dcd8cc"
C1, C2 = "#2a78d6", "#eb6834"          # 単導体仮定 / 2 導体仮定（validate_palette.js で PASS）
BAND = "#cfe9df"                        # 187 kV 鉄塔の線間距離の目安

AREA = 330.0                            # ACSR 330 mm²（line_types.yaml の 187 kV）
SPACING = 400.0                         # 素導体間隔 [mm]
X_OBS = 0.416                           # 187 kV 実効 x [Ω/km]（介入 #46・n=31・50 Hz 扱い）
D_LO, D_HI = 4.5, 6.5                   # 187 kV の線間距離の目安 [m]（本検討の想定値）
FREQ = {"hokkaido": 50, "shikoku": 60}


def k_per_km(f_hz: float) -> float:
    """ln(D/GMR) 1 あたりのリアクタンス [Ω/km]。"""
    return 2 * math.pi * f_hz * 2e-7 * 1000


def gmr_single(area_mm2: float) -> float:
    """断面積から等価円の半径を出し、0.78 倍を GMR とする [mm]。"""
    return 0.78 * math.sqrt(area_mm2 / math.pi)


G1 = gmr_single(AREA)                   # ≈ 8.0 mm
G2 = math.sqrt(G1 * SPACING)            # ≈ 57 mm（2 導体）
RATIO = math.exp(X_OBS / k_per_km(50))  # ≈ 750


def _clean(ax):
    ax.set_facecolor(PANEL)
    for s in ax.spines.values():
        s.set_color(RULE)
    ax.tick_params(colors=INK2, labelsize=10)


def fig_parts():
    fig = plt.figure(figsize=(12.0, 5.6), facecolor=BG)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.0, 1.15], wspace=.08)

    # 左: 鉄塔の断面（相どうしの間隔 D）
    ax = fig.add_subplot(gs[0]); ax.set_facecolor(PANEL)
    ax.set_xlim(-6, 6); ax.set_ylim(-1.2, 11); ax.set_aspect("equal"); ax.axis("off")
    ax.plot([0, 0], [0, 10], color=INK2, lw=4, solid_capstyle="round")
    for y in (7.0,):
        ax.plot([-3, 3], [y, y], color=INK2, lw=3)
    phases = [(0, 9.4), (-3, 7.0), (3, 7.0)]
    for px, py in phases:
        ax.add_patch(Circle((px, py), .32, color=INK, zorder=4))
    ax.add_patch(FancyArrowPatch((-3, 6.1), (3, 6.1), arrowstyle="<->",
                                 mutation_scale=16, color=INK, lw=1.6))
    box = dict(boxstyle="round,pad=.25", fc=PANEL, ec="none")
    ax.text(0, 5.35, "線間距離  D", ha="center", fontsize=15, color=INK, fontweight="bold",
            bbox=box, zorder=5)
    ax.text(0, 4.55, "隣の相（電線）との間隔\n187 kV の鉄塔でおよそ 6 m",
            ha="center", va="top", fontsize=11, color=INK2, bbox=box, zorder=5)
    ax.text(0, -.9, "① 鉄塔の腕の幅で決まる量（メートル）", ha="center",
            fontsize=12, color=INK, fontweight="bold")

    # 右: 1 相ぶんの電線の拡大（電気的な太さ GMR）
    ax = fig.add_subplot(gs[1]); ax.set_facecolor(PANEL)
    ax.set_xlim(0, 12); ax.set_ylim(-1.2, 11); ax.set_aspect("equal"); ax.axis("off")
    ax.text(6, 10.3, "1 相ぶんを拡大（縮尺は模式）", ha="center", fontsize=11, color=MUTED)
    # 単導体
    cx, cy = 2.8, 6.0
    ax.add_patch(Circle((cx, cy), .45, color=C1, zorder=3))
    ax.add_patch(Circle((cx, cy), .75, fill=False, ec=INK, lw=1.5, ls=(0, (4, 3)), zorder=4))
    ax.text(cx, 8.0, "単導体", ha="center", fontsize=14, color=INK, fontweight="bold")
    ax.text(cx, 3.9, f"GMR 約 {G1:.0f} mm", ha="center", fontsize=14, color=C1, fontweight="bold")
    # 2 導体（複導体）
    cx, cy = 8.6, 6.0
    for dx in (-1.1, 1.1):
        ax.add_patch(Circle((cx + dx, cy), .45, color=C2, zorder=3))
    ax.add_patch(Circle((cx, cy), 2.05, fill=False, ec=INK, lw=1.5, ls=(0, (4, 3)), zorder=4))
    ax.add_patch(FancyArrowPatch((cx - 1.1, cy + .75), (cx + 1.1, cy + .75), arrowstyle="<->",
                                 mutation_scale=11, color=INK2, lw=1.1))
    ax.text(cx, cy + 1.0, "40 cm", ha="center", fontsize=10, color=INK2)
    ax.text(cx, 8.6, "2 導体（複導体）", ha="center", fontsize=14, color=INK, fontweight="bold")
    ax.text(cx, 3.1, f"GMR 約 {G2:.0f} mm", ha="center", fontsize=14, color=C2, fontweight="bold")
    ax.text(cx, 2.45, "素導体間隔 40 cm", ha="center", fontsize=10, color=INK2)
    ax.text(6, 1.3, f"点線の円 ＝「電気的な太さ」。束ねると約 {G2/G1:.0f} 倍に太く見える",
            ha="center", fontsize=11, color=INK2)
    ax.text(6, -.9, "② 電線の構成で決まる量（ミリメートル）", ha="center",
            fontsize=12, color=INK, fontweight="bold")
    out = FIGS / "why42m_parts.png"
    fig.savefig(out, dpi=180, facecolor=BG, bbox_inches="tight"); plt.close(fig)
    return out


def fig_ratio():
    fig, ax = plt.subplots(figsize=(12.0, 4.8), facecolor=BG)
    _clean(ax)
    ax.set_xscale("log")
    ax.set_xlim(3, 2e5)
    ax.set_ylim(-.2, 2.2)
    ax.axvspan(D_LO * 1000, D_HI * 1000, color=BAND, zorder=0)
    ax.text(math.sqrt(D_LO * D_HI) * 1000, 2.08, "187 kV 鉄塔の\n線間距離の目安", ha="center",
            va="top", fontsize=10, color="#2f6b57")
    rows = [(1.45, G1, C1, "単導体"), (.45, G2, C2, "2 導体")]
    for y, g, c, lab in rows:
        D = g * RATIO
        ax.plot([g, D], [y, y], color=c, lw=2.2, zorder=3)
        ax.plot([g], [y], "o", ms=11, color=c, mec="white", mew=2, zorder=4)
        ax.plot([D], [y], "o", ms=11, color=c, mec="white", mew=2, zorder=4)
        ax.text(g, y + .22, f"GMR {g:.0f} mm", ha="center", fontsize=12, color=INK, fontweight="bold")
        ax.text(D, y + .22, f"D = {D/1000:.1f} m", ha="center", fontsize=12, color=INK, fontweight="bold")
        ax.text(math.sqrt(g * D), y - .28, "× 約 750", ha="center", fontsize=12, color=INK2)
        ax.text(3.6, y, lab, ha="left", va="center", fontsize=14, color=c, fontweight="bold")
    ticks = [10, 100, 1e3, 1e4, 1e5]
    ax.set_xticks(ticks)
    ax.set_xticklabels(["1 cm", "10 cm", "1 m", "10 m", "100 m"])
    ax.set_yticks([])
    ax.grid(axis="x", color=RULE, lw=.8, which="major")
    ax.set_xlabel("長さ（対数目盛。同じ「× 750」はどこでも同じ長さになる）", fontsize=11, color=INK2)
    out = FIGS / "why42m_ratio.png"
    fig.savefig(out, dpi=180, facecolor=BG, bbox_inches="tight"); plt.close(fig)
    return out


def fig_curve():
    fig, ax = plt.subplots(figsize=(12.0, 6.2), facecolor=BG)
    _clean(ax)
    ax.tick_params(labelsize=12)
    K = k_per_km(50)
    D = np.logspace(0, 2, 200)
    ax.axvspan(D_LO, D_HI, color=BAND, zorder=0)
    ax.text(math.sqrt(D_LO * D_HI), .158, "187 kV 鉄塔\nの目安", ha="center", va="bottom",
            fontsize=12, color="#2f6b57")
    for g, c, lab in ((G1, C1, "単導体（GMR 8 mm）"), (G2, C2, "2 導体（GMR 57 mm）")):
        ax.plot(D, K * np.log(D * 1000 / g), color=c, lw=2.4, zorder=3)
        xl = 40 if g < 20 else 80
        ax.text(xl, K * math.log(xl * 1e3 / g) + .018, lab, ha="right", fontsize=14, color=c,
                fontweight="bold")
    ax.axhline(X_OBS, color=INK, lw=1.4, ls=(0, (5, 3)), zorder=2)
    ax.text(1.05, X_OBS + .008, f"実測 x = {X_OBS} Ω/km", fontsize=14, color=INK)
    for g, c in ((G1, C1), (G2, C2)):
        Dx = g * RATIO / 1000
        ax.plot([Dx], [X_OBS], "o", ms=12, color=c, mec="white", mew=2, zorder=5)
        ax.annotate(f"{Dx:.1f} m", (Dx, X_OBS), xytext=(0, -30), textcoords="offset points",
                    ha="center", fontsize=16, color=INK, fontweight="bold")
    x2 = K * math.log(6000 / G2)
    ax.plot([6], [x2], "o", ms=10, color=C2, mec="white", mew=2, zorder=5)
    ax.annotate(f"腕 6 m なら 2 導体は x = {x2:.3f}\n（実測の {x2/X_OBS:.2f} 倍）", (6, x2),
                xytext=(12, -8), textcoords="offset points", fontsize=13, color=INK2, va="top")
    ax.set_xscale("log")
    ax.set_xlim(1, 100); ax.set_ylim(.15, .56)
    ax.set_xticks([1, 2, 5, 10, 20, 50, 100])
    ax.set_xticklabels(["1", "2", "5", "10", "20", "50", "100"])
    ax.set_xlabel("線間距離 D [m]（対数目盛）", fontsize=13, color=INK2)
    ax.set_ylabel("リアクタンス x [Ω/km]（50 Hz）", fontsize=13, color=INK2)
    ax.grid(color=RULE, lw=.7)
    out = FIGS / "why42m_curve.png"
    fig.savefig(out, dpi=180, facecolor=BG, bbox_inches="tight"); plt.close(fig)
    return out


def per_line():
    """187 kV の線ごとに、単導体仮定と 2 導体仮定で必要な D [m] を返す（線名は返さない）。"""
    import pandas as pd
    cm_p = NORM / "compare_observed_derived_impedance.csv"
    rl_p = ROOT / "docs/reports/route_len.csv"
    if not cm_p.exists() or not rl_p.exists():
        return None
    cm = pd.read_csv(cm_p)
    rl = pd.read_csv(rl_p)
    key = ["utility", "line_name", "voltage_kv"]
    d = cm.merge(rl[key + ["route_km"]], on=key)
    d = d[~d.line_name.astype(str).str.contains("地中|ケーブル|洞道")]
    d = d[d.route_km > 0].copy()
    d["x_eff"] = d.X_ohm_obs / d.route_km
    d = d[(d.x_eff >= .15) & (d.x_eff <= .8)].drop_duplicates(key)
    s = d[(d.voltage_kv == 187) & d.utility.isin(FREQ)]
    rows = []
    for x, u in zip(s.x_eff, s.utility):
        r = math.exp(x / k_per_km(FREQ[u]))
        rows.append({"utility": u, "x": x, "D1": G1 * r / 1000, "D2": G2 * r / 1000})
    return pd.DataFrame(rows)


def classify(df):
    def near(D):  # 目安の帯の前後 ±50% を「鉄塔の寸法と同じ桁」とみなす
        return D_LO / 1.5 <= D <= D_HI * 1.5
    one = df.D1.between(D_LO, D_HI * 1.05) & ~df.D2.apply(near)
    two = df.D2.apply(near) & ~df.D1.apply(near)
    return one, two


def fig_perline(df):
    one, two = classify(df)
    df = df.assign(grp=np.where(one, 0, np.where(two, 1, 2)))
    df = df.sort_values(["grp", "D1"]).reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(11.5, 6.4), facecolor=BG)
    _clean(ax)
    ax.axvspan(D_LO, D_HI, color=BAND, zorder=0)
    y = np.arange(len(df))[::-1]
    for yi, (_, r) in zip(y, df.iterrows()):
        ax.plot([r.D1, r.D2], [yi, yi], color=RULE, lw=2.2, zorder=1)
        mk = "o" if r.utility == "hokkaido" else "s"
        ax.plot([r.D1], [yi], mk, ms=9, color=C1, mec="white", mew=1.5, zorder=3)
        ax.plot([r.D2], [yi], mk, ms=9, color=C2, mec="white", mew=1.5, zorder=3)
    n1, n2 = int(one.sum()), int(two.sum())
    n0 = len(df) - n1 - n2
    r1 = df[df.grp == 0].D1
    r2 = df[df.grp == 1].D2
    bounds = [(0, n1, f"{n1} 線路: 単導体なら {r1.min():.1f}〜{r1.max():.1f} m\n＝鉄塔の寸法に合う"),
              (n1, n1 + n2, f"{n2} 線路: 2 導体なら {r2.min():.1f}〜{r2.max():.1f} m\n＝鉄塔の寸法に近い"),
              (n1 + n2, len(df), f"{n0} 線路: どちらの仮定でも\n鉄塔の寸法から外れる")]
    for a, b, lab in bounds:
        if b <= a:
            continue
        ytop, ybot = y[a], y[b - 1]
        if a:
            ax.axhline(ytop + .5, color=MUTED, lw=.8, ls=":")
        ax.text(160, (ytop + ybot) / 2, lab, ha="left", va="center", fontsize=14,
                color=INK, fontweight="bold")
    ax.set_xscale("log")
    ax.set_xlim(.7, 150)
    ax.set_xticks([1, 2, 5, 10, 20, 50, 100])
    ax.set_xticklabels(["1", "2", "5", "10", "20", "50", "100"])
    ax.set_yticks([])
    ax.set_ylim(-.8, len(df) - .2)
    ax.set_xlabel("実測 x を説明するのに必要な線間距離 D [m]（対数目盛）", fontsize=13, color=INK2)
    ax.tick_params(labelsize=12)
    ax.grid(axis="x", color=RULE, lw=.7)
    h = [plt.Line2D([], [], ls="", marker="o", ms=9, color=C1, label="単導体と仮定"),
         plt.Line2D([], [], ls="", marker="o", ms=9, color=C2, label="2 導体と仮定"),
         plt.Line2D([], [], ls="", marker="o", ms=8, color=MUTED, label="北海道 50 Hz"),
         plt.Line2D([], [], ls="", marker="s", ms=8, color=MUTED, label="四国 60 Hz")]
    ax.legend(handles=h, loc="upper center", bbox_to_anchor=(.5, 1.09), ncol=4,
              frameon=False, fontsize=13)
    out = FIGS / "why42m_perline.png"
    fig.savefig(out, dpi=180, facecolor=BG, bbox_inches="tight"); plt.close(fig)
    return out, n1, n2, n0


def main():
    print(f"  GMR 単導体={G1:.2f} mm / 2導体={G2:.2f} mm（{G2/G1:.2f} 倍） 比 D/GMR={RATIO:.0f}")
    print(f"  必要な D: 単導体={G1*RATIO/1000:.2f} m / 2導体={G2*RATIO/1000:.2f} m")
    for f in (fig_parts, fig_ratio, fig_curve):
        print("  ", f().name)
    df = per_line()
    if df is None:
        print("  (data/external が無いので why42m_perline.png は作らない)")
        return 0
    out, n1, n2, n0 = fig_perline(df)
    print("  ", out.name, f"n={len(df)} 単導体={n1} 2導体={n2} どちらでもない={n0}")
    for u, g in df.groupby("utility"):
        r = math.exp(g.x.median() / k_per_km(FREQ[u]))
        print(f"    {u:9s} {FREQ[u]}Hz n={len(g)} x中央値={g.x.median():.3f}"
              f" → D 単導体={G1*r/1000:.1f} m / 2導体={G2*r/1000:.1f} m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
