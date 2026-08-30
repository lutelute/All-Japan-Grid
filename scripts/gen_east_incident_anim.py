#!/usr/bin/env python3
"""東全域の大擾乱アニメGIF — N-2同時脱落→UFLS、負荷と発電機を明確に描き分け.

オーナー指示(2026-08-30)「北海道でやっている負荷遮断を東全体で」「発電機全台の
周波数も同じgifで」「負荷と発電機が明確にわかるように」。

素材: mm_traces_east_n3pk.npz (run_multimachine_national --islands east
      --trip-top 3 --tag n3pk — ピーク断面59.4GW・上位3プラント10.9GW
      同時脱落=設計外N-3デモ・ラッチUFLS第1段発火)
描法: 左=地図(●発電機: 色=ローカル周波数・大きさ=定格 / ■負荷: 大きさ=MW・
      UFLS段で縮小+フラッシュ / ×=脱落) 右=全機周波数+COI+現在時刻カーソル

出力: docs/slides/ajg/assets/east_incident.gif
"""
import json, math, os, sys
import numpy as np
os.chdir("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

z = np.load("docs/data/agc/mm_traces_east_n3pk.npz", allow_pickle=True)
t, w, f0 = z["t"], z["w"], float(z["f0"])
lon, lat, S, M, live = z["lon"], z["lat"], z["S"], z["M"], z["live"]
trips = [int(x) for x in z["trips"]]
llon, llat, lmw = z["load_lon"], z["load_lat"], z["load_mw"]
ev_t, ev_s = z["ev_t"], z["ev_s"]
n = w.shape[0]
fm = f0 + w * f0
finite = np.isfinite(w)
coi = np.full(len(t), np.nan)
for i in range(len(t)):
    m = finite[:, i]
    if m.any():
        coi[i] = f0 + (M[m] * w[m, i]).sum() / M[m].sum() * f0

def stage_at(ts):
    return sum(1 for te, sname in zip(ev_t, ev_s)
               if "UFLS" in str(sname) and te <= ts)
def drop_at(k, ts):
    """機kが時刻tsまでに切離されたか(トレースNaN化で判定)。"""
    i = np.searchsorted(t, ts)
    i = min(i, len(t) - 1)
    return not np.isfinite(w[k, i])

# 背景線形(east)
b = json.load(open("docs/data/built/all.json"))
X0, X1, Y0, Y1 = 136.3, 142.9, 34.2, 42.0
segs = [[(p[1], p[0]) for p in e["path"]] for e in b["edges"]
        if e.get("path") and len(e["path"]) >= 2
        and Y0 <= e["path"][0][0] <= Y1 and X0 <= e["path"][0][1] <= X1]

def fcmap(df, span=0.8):
    x = min(max(-df / span, 0.0), 1.0)
    if x < 0.5:
        u = x / 0.5
        c0, c1 = np.array([0.55, 0.75, 1.0]), np.array([1.0, 0.97, 0.85])
    else:
        u = (x - 0.5) / 0.5
        c0, c1 = np.array([1.0, 0.97, 0.85]), np.array([0.88, 0.10, 0.10])
    return c0 + (c1 - c0) * u

BG = "#0A0D1A"
tot_mw = float(lmw.sum())
ms = 20.0 * np.sqrt(np.maximum(S, 5.0) / 500.0)
lsz0 = 3.2 * np.sqrt(lmw / max(lmw.mean(), 1.0))

def render(ts, flash=False):
    k = min(len(t) - 1, int(np.searchsorted(t, ts)))
    st = stage_at(ts)
    fig = plt.figure(figsize=(12.8, 7.2), dpi=110)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.0, 0.0, 0.66, 1.0]); ax.set_facecolor(BG)
    ax.set_xlim(X0, X1); ax.set_ylim(Y0, Y1)
    ax.set_aspect(1.0 / math.cos(math.radians(38.0))); ax.axis("off")
    ax.add_collection(LineCollection(segs, colors="#232A45", linewidths=0.45,
                                     alpha=0.8, zorder=1))
    # 負荷=■(UFLS段で縮小・フラッシュ)
    sc = 1.0 - 0.1 * st
    ax.scatter(llon, llat, s=lsz0 * sc, marker="s",
               c=("#FF5252" if flash else "#C9A227"),
               alpha=0.75 if flash else 0.38, zorder=3, linewidths=0)
    # 発電機=●(色=ローカル周波数) / 切離し済み=×
    for i in range(n):
        if not np.isfinite(lon[i]):
            continue
        if drop_at(i, ts):
            big = i in trips
            ax.scatter([lon[i]], [lat[i]], marker="X",
                       s=330 if big else 90,
                       c="#D62728" if big else "#7A7F99",
                       edgecolors="#FFFFFF", linewidths=0.9 if big else 0.4,
                       zorder=8 if big else 6)
            continue
        fi = fm[i, k]
        if not np.isfinite(fi):
            continue
        ax.scatter([lon[i]], [lat[i]], s=ms[i], color=fcmap(fi - f0),
                   edgecolors="#FFFFFF", linewidths=0.3, alpha=0.95, zorder=5)
    # HUD
    tt = ts - 1.0
    lbl = ("事故前" if tt < 0 else
           f"事故から {tt:5.1f} 秒")
    ax.text(0.03, 0.965, "東日本全域 N-3実験 — 富津+東新潟+千葉 10.9GW同時脱落(設計外デモ)",
            transform=ax.transAxes, color="#C8CDD8", fontsize=13.5,
            fontweight="bold", va="top")
    ax.text(0.03, 0.915, lbl, transform=ax.transAxes, color="#FFFFFF",
            fontsize=18, fontweight="bold", va="top")
    cv = coi[k]
    ax.text(0.03, 0.862, f"系統平均 {cv:6.2f} Hz",
            transform=ax.transAxes, color=fcmap(cv - f0), fontsize=14,
            fontweight="bold", va="top")
    shed = tot_mw * 0.1 * st
    ax.text(0.03, 0.815, f"UFLS 第{st}段 / 遮断 {shed:,.0f} MW" if st else
            "UFLS 未発動", transform=ax.transAxes,
            color="#FF8A80" if st else "#5A648F", fontsize=12.5, va="top")
    # 凡例(負荷と発電機を明確に)
    ax.text(0.025, 0.44,
            "● 発電機(色=その機の周波数・大きさ=定格)\n"
            "■ 負荷(大きさ=MW — UFLSの段ごとに1割ずつ縮む)\n"
            "× 脱落(赤=今回落とした3プラント / 灰=脱調保護)",
            transform=ax.transAxes, color="#C8CDD8", fontsize=10.5,
            va="top", bbox=dict(facecolor="#11152A", edgecolor="#3A4266",
                                boxstyle="round,pad=0.45", alpha=0.92))
    ax.text(0.03, 0.03, "AGC-N 多機共シミュレーション(AGC30定数・実網Kron縮約"
            "・UCピーク断面59.4GW)", transform=ax.transAxes,
            color="#5A648F", fontsize=8.5, va="bottom")
    # 右: 全機周波数パネル
    axw = fig.add_axes([0.70, 0.10, 0.28, 0.80])
    axw.set_facecolor("#11152A")
    for i in range(n):
        if i in trips:
            continue
        axw.plot(t, fm[i], lw=0.35, color="#5A78B8", alpha=0.30)
    axw.plot(t, coi, lw=1.8, color="#FFFFFF")
    for s_hz, lb in ((-1.5, "第1段"), (-2.0, "第2段"), (-2.5, "第3段")):
        axw.axhline(f0 + s_hz, color="#C62828", lw=0.8, ls="--", alpha=0.6)
        axw.text(float(t[-1]) * 0.99, f0 + s_hz + 0.03, f"UFLS{lb}",
                 ha="right", color="#C62828", fontsize=7.5)
    for te in ev_t:
        axw.axvline(te, color="#C62828", lw=0.7, ls=":", alpha=0.7)
    axw.axvline(ts, color="#FFD60A", lw=1.5)
    axw.set_xlim(0, float(t[-1]))
    lo = np.nanmin(coi) - 0.5
    axw.set_ylim(lo, f0 + 0.3)
    axw.tick_params(colors="#8E96B8", labelsize=8)
    for sp in axw.spines.values():
        sp.set_color("#3A4266")
    axw.set_title(f"全{int(np.isfinite(w[:,0]).sum())}機の周波数(細線)+COI(白)",
                  color="#C8CDD8", fontsize=10.5)
    axw.set_xlabel("時間 [s]", color="#8E96B8", fontsize=9)
    fig.canvas.draw()
    img = np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()
    plt.close(fig)
    return img

# タイムライン(可変速): 事故直前→UFLSの数秒は細かく→回復はまばら
TL = [(0.0, 1200)]
TL += [(1.0 + 0.5 * i, 600) for i in range(10)]      # 1〜6s
TL += [(6.0 + 1.0 * i, 450) for i in range(9)]       # 〜15s
TL += [(15.0 + 3.0 * i, 450) for i in range(int((float(t[-1]) - 15) / 3))]
frames, durs = [], []
ev_ufls = [te for te, sname in zip(ev_t, ev_s) if "UFLS" in str(sname)]
for ts, du in TL:
    if ts > float(t[-1]):
        break
    flash = any(0 <= ts - te < 0.6 for te in ev_ufls)
    frames.append(render(ts, flash=flash)); durs.append(du)
frames.append(render(float(t[-1]) - 0.02)); durs.append(3200)
from PIL import Image
ims = [Image.fromarray(f) for f in frames]
out = "docs/slides/ajg/assets/east_incident.gif"
ims[0].save(out, save_all=True, append_images=ims[1:], duration=durs, loop=0,
            optimize=True)
print(f"-> {out} ({len(ims)}フレーム, {os.path.getsize(out)/1e6:.1f}MB)")
