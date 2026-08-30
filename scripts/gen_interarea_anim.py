#!/usr/bin/env python3
"""逆位相動揺(inter-areaモード)GIF — 九州側と関西側の綱引き(2026-08-30 v3).

west正典多機トレース(最大機トリップ)に西G(lon<132.5)×東G(lon>134.5)の
逆位相モード(相関-0.999・周期2.4s)が出る。実網から測った連系剛性T_abが
決める固有モードの可視化。

v3(オーナー指摘「矢印が合っていない・位相シフト?」対応):
- 地図の●の色を「速度」から「位相角偏差(対COI・初期値基準)」に変更。
  矢印はΔδ(群間位相角差)駆動なので、色と矢印が完全に同期する。
  旧版は色=速度で、調和振動では位相と速度が90°ずれるため
  「矢印最大の瞬間に色が薄い」— 指摘の"位相シフト"は物理的に正しい観察。
- 右パネル再構成: 上=Δδ(綱の張り・主役)、下=群平均速度+90°先行の注記。
- 綱引きの4拍子(①西Gが前へ②引き戻し③東Gが前へ④引き戻し)の現在地表示。
- 青/赤=位相進み/遅れ専用。群の識別色は橙(西G)/紫(東G)に分離。

出力: docs/slides/ajg/assets/interarea_mode.gif
"""
import json, math, os
import numpy as np
os.chdir("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.patches import FancyBboxPatch
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

z = np.load("docs/data/agc/mm_traces_west.npz", allow_pickle=True)
t, w, f0 = z["t"], z["w"], float(z["f0"])
dlt = z["d"]                            # 各機の位相角δ [rad]
lon, lat, S, M = z["lon"], z["lat"], z["S"], z["M"]
trip = int(z["trip"])
fin = np.isfinite(w)
coi = np.array([(M[m] * w[m, i]).sum() / M[m].sum()
                if (m := fin[:, i]).any() else np.nan for i in range(len(t))])
rel = (w - coi[None, :]) * f0          # COI相対周波数[Hz](下パネル用)
gW = np.where(np.isfinite(lon) & (lon < 132.5))[0]
gE = np.where(np.isfinite(lon) & (lon > 134.5))[0]
def gmean(idx):
    x = rel[idx]
    return np.nansum(M[idx][:, None] * x, axis=0) / np.maximum(
        (M[idx][:, None] * np.isfinite(x)).sum(axis=0), 1e-9)
a, b = gmean(gW), gmean(gE)

# ── 位相角: COI角(M加重平均)からの偏差、初期値基準 [deg] — 地図の色と同じ量
finang = np.isfinite(dlt)
sysang = np.array([(M[m] * dlt[m, i]).sum() / M[m].sum()
                   if (m := finang[:, i]).any() else np.nan
                   for i in range(len(t))])
pang = np.degrees((dlt - dlt[:, [0]]) - (sysang - sysang[0])[None, :])

def gang(idx):
    x = dlt[idx]
    return np.nansum(M[idx][:, None] * x, axis=0) / np.maximum(
        (M[idx][:, None] * np.isfinite(x)).sum(axis=0), 1e-9)
ddeg = np.degrees(gang(gW) - gang(gE))
ddeg = ddeg - ddeg[0]                   # 初期潮流分を除いた角度差の偏差 [deg]
ddot = np.gradient(ddeg, t)             # dΔδ/dt [deg/s] — 4拍子の判定に使う
kwin = int(8.7 / (t[1] - t[0]))
dmax = float(np.nanmax(np.abs(ddeg[:kwin])))
# 色の飽和スパン: 表示窓内の全機|位相偏差|の95パーセンタイル(脱調機の裾を除く)
PSPAN = float(np.nanpercentile(np.abs(pang[:, :kwin]), 95))
cW = (float(np.average(lon[gW], weights=M[gW])),
      float(np.average(lat[gW], weights=M[gW])))
cE = (float(np.average(lon[gE], weights=M[gE])),
      float(np.average(lat[gE], weights=M[gE])))

bjs = json.load(open("docs/data/built/all.json"))
X0, X1, Y0, Y1 = 128.8, 137.8, 30.6, 37.4
segs = [[(p[1], p[0]) for p in e["path"]] for e in bjs["edges"]
        if e.get("path") and len(e["path"]) >= 2
        and Y0 <= e["path"][0][0] <= Y1 and X0 <= e["path"][0][1] <= X1]

BG = "#0A0D1A"
CWG, CEG = "#FFA94D", "#C39BFF"        # 群の識別色: 西G=橙 / 東G=紫
def rcol(v, span):
    """位相偏差[deg]→色。青=位相進み / 赤=位相遅れ(±spanで飽和)。"""
    x = max(-1.0, min(1.0, v / span))
    if x >= 0:
        c0, c1 = np.array([0.16, 0.19, 0.33]), np.array([0.30, 0.62, 1.0])
        return c0 + (c1 - c0) * x
    c0, c1 = np.array([0.16, 0.19, 0.33]), np.array([1.0, 0.32, 0.28])
    return c0 + (c1 - c0) * (-x)

STATES = ["① 西Gが前へ — 綱が張っていく",
          "② 綱が西Gを引き戻す(西G減速)",
          "③ 東Gが前へ — 綱が逆に張る",
          "④ 綱が東Gを引き戻す(東G減速)"]
def state_at(k):
    dd, dv = ddeg[k], ddot[k]
    if dd > 0:
        return 0 if dv > 0 else 1
    return 2 if dv <= 0 else 3

ms = 26.0 * np.sqrt(np.maximum(S, 5.0) / 500.0)
frames, durs = [], []
for ts in np.arange(1.0, 8.62, 0.12):
    k = min(len(t) - 1, int(np.searchsorted(t, ts)))
    fig = plt.figure(figsize=(12.8, 7.2), dpi=110)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.0, 0.0, 0.64, 1.0]); ax.set_facecolor(BG)
    ax.set_xlim(X0, X1); ax.set_ylim(Y0, Y1)
    ax.set_aspect(1.0 / math.cos(math.radians(34.0))); ax.axis("off")
    ax.add_collection(LineCollection(segs, colors="#242B49", linewidths=0.45,
                                     alpha=0.85, zorder=1))
    for i in range(w.shape[0]):
        if not np.isfinite(lon[i]) or not np.isfinite(pang[i, k]):
            continue
        ax.scatter([lon[i]], [lat[i]], s=ms[i], color=rcol(pang[i, k], PSPAN),
                   zorder=5, linewidths=0.3, edgecolors="#FFFFFF", alpha=0.95)
    ax.scatter([lon[trip]], [lat[trip]], marker="X", s=260, c="#D62728",
               edgecolors="#FFFFFF", linewidths=0.9, zorder=8)
    # 綱引き矢印: 位相の進んだ群(Δδ)→遅れた群へ。色は電力=金(群色と独立)
    dv = ddeg[k]
    if abs(dv) > 0.02 * dmax:
        src, dst = (cW, cE) if dv > 0 else (cE, cW)
        ax.annotate("", xy=dst, xytext=src, zorder=9,
                    arrowprops=dict(arrowstyle="-|>", color="#FFC94A",
                                    lw=1.0 + 5.0 * abs(dv) / dmax,
                                    mutation_scale=18 + 26 * abs(dv) / dmax,
                                    alpha=0.9,
                                    connectionstyle="arc3,rad=-0.18"))
        mx, my = (cW[0] + cE[0]) / 2, (cW[1] + cE[1]) / 2 + 1.15
        ax.text(mx, my, "電力 西→東" if dv > 0 else "電力 東→西",
                color="#FFC94A", fontsize=11.5, fontweight="bold",
                ha="center", zorder=9)
    ax.text(0.03, 0.955, "逆位相動揺 — 九州側と関西側の綱引き",
            transform=ax.transAxes, color="#FFFFFF", fontsize=19,
            fontweight="bold", va="top")
    ax.text(0.03, 0.895,
            f"西日本{w.shape[0]}機・最大機トリップ後の位相角の偏差"
            f"(青=位相進み / 赤=位相遅れ、±{PSPAN:.0f}°で飽和)",
            transform=ax.transAxes, color="#A7B0CB", fontsize=12, va="top")
    ax.text(0.03, 0.845, f"事故から {ts-1.0:4.2f} 秒",
            transform=ax.transAxes, color="#FFD60A", fontsize=15,
            fontweight="bold", va="top")
    ax.text(0.03, 0.05,
            "しくみ: 2つの慣性群が長い送電回廊(=ばね)で繋がれた2重り系 — 綱引き。\n"
            f"西G(九州側{len(gW)}機)×東G(関西以東{len(gE)}機) "
            "相関 −0.999 / 周期 2.4 s(実網の連系剛性T_abが決める固有値)",
            transform=ax.transAxes, color="#8E96B8", fontsize=9.5, va="bottom")
    # 綱引きの4拍子 — 現在の局面をハイライト(太平洋上の空き領域)
    st = state_at(k)
    ax.add_patch(FancyBboxPatch((0.535, 0.115), 0.445, 0.205,
                 transform=ax.transAxes, boxstyle="round,pad=0.012",
                 facecolor="#11152A", edgecolor="#3A4266", alpha=0.94,
                 zorder=9))
    ax.text(0.55, 0.303, "綱引きの4拍子(いまの局面)", transform=ax.transAxes,
            color="#C8CDD8", fontsize=9.5, fontweight="bold", va="top",
            zorder=10)
    for si, lbl in enumerate(STATES):
        cur = (si == st)
        ax.text(0.55, 0.262 - 0.042 * si,
                ("▶ " if cur else "   ") + lbl, transform=ax.transAxes,
                color="#FFD60A" if cur else "#5A648F",
                fontsize=9.5, fontweight="bold" if cur else "normal",
                va="top", zorder=10)
    # 右上(主役): 綱の張り=群間位相角差Δδ — 地図の色・矢印と同期
    axg = fig.add_axes([0.68, 0.50, 0.30, 0.40]); axg.set_facecolor("#11152A")
    axg.plot(t, ddeg, lw=1.8, color="#E8C36A")
    axg.axvline(t[k], color="#FFD60A", lw=1.5)
    axg.axhline(0, color="#3A4266", lw=0.8)
    axg.set_xlim(0.8, 8.6); axg.set_ylim(-1.25 * dmax, 1.25 * dmax)
    axg.tick_params(colors="#8E96B8", labelsize=8)
    for sp in axg.spines.values():
        sp.set_color("#3A4266")
    axg.set_title("綱の張り = 群間の位相角差Δδ [deg](初期潮流分を除く)",
                  color="#C8CDD8", fontsize=10.5)
    axg.text(0.03, 0.88, "Δδ>0: 西Gが位相で進み → 電力 西→東(地図の矢印)",
             transform=axg.transAxes, color="#8E96B8", fontsize=8.2)
    axg.text(0.03, 0.06, "Δδ<0: 東Gが位相で進み → 電力 東→西",
             transform=axg.transAxes, color="#8E96B8", fontsize=8.2)
    # 右下: 群平均の速度 — 位相より90°先行する(オーナーの"位相シフト?"への回答)
    axw = fig.add_axes([0.68, 0.09, 0.30, 0.31]); axw.set_facecolor("#11152A")
    axw.plot(t, a, lw=1.7, color=CWG, label=f"西G {len(gW)}機")
    axw.plot(t, b, lw=1.7, color=CEG, label=f"東G {len(gE)}機")
    axw.axvline(t[k], color="#FFD60A", lw=1.5)
    axw.axhline(0, color="#3A4266", lw=0.8)
    axw.set_xlim(0.8, 8.6); axw.set_ylim(-0.14, 0.14)
    axw.tick_params(colors="#8E96B8", labelsize=8)
    for sp in axw.spines.values():
        sp.set_color("#3A4266")
    axw.legend(loc="upper right", fontsize=8.5, facecolor="#11152A",
               labelcolor="#C8CDD8", edgecolor="#3A4266")
    axw.set_title("群平均の速度(COI相対周波数) [Hz] — 位相より90°先行",
                  color="#C8CDD8", fontsize=10)
    axw.text(0.03, 0.06, "振り子と同じ: 綱が最も張った瞬間、速度はゼロ",
             transform=axw.transAxes, color="#8FD3A5", fontsize=8.2)
    axw.set_xlabel("時間 [s]", color="#8E96B8", fontsize=9)
    fig.canvas.draw()
    frames.append(np.asarray(fig.canvas.buffer_rgba())[..., :3].copy())
    plt.close(fig)
    durs.append(170)
durs[-1] = 2500
from PIL import Image
ims = [Image.fromarray(f) for f in frames]
out = "docs/slides/ajg/assets/interarea_mode.gif"
ims[0].save(out, save_all=True, append_images=ims[1:], duration=durs, loop=0,
            optimize=True)
print(f"-> {out} ({len(ims)}フレーム, {os.path.getsize(out)/1e6:.1f}MB)")
