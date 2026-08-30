#!/usr/bin/env python3
"""東全域の大擾乱アニメGIF — N-3→UFLS→回復、2幕構成(2026-08-30 v3).

オーナー指摘の変遷:
  v1「負荷と発電機が明確に」→ v2 900sアーク対応(停滞の開示)
  → v3「わかりにくい」— 情報の同時表示過多を整理:
     第1幕(0-20s・ほぼ実速): 事故→急落→UFLS底打ち→登坂開始。凡例は序盤のみ。
     幕間: フルフレームバナー「ここから早送り — 回復には15分かかる」
     第2幕(20-900s・×30/×120): 局面を上部の大きな帯バナーで1つずつ。
       HUDは時刻+系統平均に絞り、右のCOIパネルに局面シェードを重ねて主役化。

素材: mm_traces_east_n3pk.npz (--islands east --trip-top 3 --tag n3pk
      --t-end 900 — ピーク断面・上位3プラント同時脱落=設計外N-3デモ)
出力: docs/slides/ajg/assets/east_incident.gif
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

z = np.load("docs/data/agc/mm_traces_east_n3pk.npz", allow_pickle=True)
t, w, f0 = z["t"], z["w"], float(z["f0"])
lon, lat, S, M = z["lon"], z["lat"], z["S"], z["M"]
trips = [int(x) for x in z["trips"]]
llon, llat, lmw = z["load_lon"], z["load_lat"], z["load_mw"]
ev_t, ev_s = z["ev_t"], z["ev_s"]
names = z["names"]
n = w.shape[0]
fm = f0 + w * f0
finite = np.isfinite(w)
coi = np.full(len(t), np.nan)
for i in range(len(t)):
    m = finite[:, i]
    if m.any():
        coi[i] = f0 + (M[m] * w[m, i]).sum() / M[m].sum() * f0

# 数値衛生: 表示値は全てデータから
trip_mw = float(sum(S[i] for i in trips))  # 参考(定格) — 脱落量は台帳値でなくP
tot_mw = float(lmw.sum())
floor_hz = float(np.nanmin(coi))
k60 = min(len(t) - 1, int(np.searchsorted(t, 60.0)))
f60 = float(coi[k60])
f_end = float(coi[np.isfinite(coi)][-1])
T_LAST = float(t[-1])
end_min = (T_LAST - 1.0) / 60.0

def stage_at(ts):
    return sum(1 for te, sname in zip(ev_t, ev_s)
               if "UFLS" in str(sname) and te <= ts)
def drop_at(kk, ts):
    i = min(np.searchsorted(t, ts), len(t) - 1)
    return not np.isfinite(w[kk, i])

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
ms = 20.0 * np.sqrt(np.maximum(S, 5.0) / 500.0)
lsz0 = 3.2 * np.sqrt(lmw / max(lmw.mean(), 1.0))
# 第2幕の局面(帯バナー): (開始s, 終了s, ラベル, 色)
PHASES = [(5.3, 60.0, "高速登坂 — ガバナ+水力LFC(速い余力)", "#8FD3A5"),
          (60.0, 180.0, "停滞 — 速い余力が尽き、遅い火力だけが登る", "#FFD60A"),
          (180.0, T_LAST, "緩やかな回復 — 遅い火力が仕上げる", "#9EC1FF")]

def phase_of(tt):
    for x0, x1, lb, c in PHASES:
        if x0 <= tt + 1.0 < x1:
            return lb, c
    return PHASES[-1][2], PHASES[-1][3]

def render(ts, flash=False, speed=1, act=1):
    k = min(len(t) - 1, int(np.searchsorted(t, ts)))
    st = stage_at(ts)
    fig = plt.figure(figsize=(12.8, 7.2), dpi=110)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.0, 0.0, 0.66, 1.0]); ax.set_facecolor(BG)
    ax.set_xlim(X0, X1); ax.set_ylim(Y0, Y1)
    ax.set_aspect(1.0 / math.cos(math.radians(38.0))); ax.axis("off")
    ax.add_collection(LineCollection(segs, colors="#232A45", linewidths=0.45,
                                     alpha=0.8, zorder=1))
    sc = 1.0 - 0.1 * st
    ax.scatter(llon, llat, s=lsz0 * sc, marker="s",
               c=("#FF5252" if flash else "#C9A227"),
               alpha=0.75 if flash else 0.38, zorder=3, linewidths=0)
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
    tt = ts - 1.0
    lbl = ("事故前" if tt < 0 else
           f"事故から {tt:5.1f} 秒" if tt < 90 else
           f"事故から {int(tt)//60}分{int(tt)%60:02d}秒")
    if act == 2:
        # ── 第2幕: 上部の局面帯バナー(1つだけ大きく)
        ph, pc = phase_of(tt)
        axb = fig.add_axes([0.0, 0.925, 1.0, 0.075], zorder=11)
        axb.set_facecolor("#11152A"); axb.set_xticks([]); axb.set_yticks([])
        for sp in axb.spines.values():
            sp.set_visible(False)
        axb.text(0.02, 0.5, "▸ " + ph, color=pc, fontsize=17,
                 fontweight="bold", va="center", transform=axb.transAxes)
        axb.text(0.985, 0.5, f"×{speed} 早送り", color="#FFD60A",
                 fontsize=11.5, fontweight="bold", va="center", ha="right",
                 transform=axb.transAxes)
        ax.text(0.03, 0.875, lbl, transform=ax.transAxes, color="#FFFFFF",
                fontsize=17, fontweight="bold", va="top")
        cv = coi[k]
        ax.text(0.03, 0.822, f"系統平均 {cv:6.2f} Hz",
                transform=ax.transAxes, color=fcmap(cv - f0), fontsize=14,
                fontweight="bold", va="top")
        shed = tot_mw * 0.1 * st
        if st:
            ax.text(0.03, 0.775, f"UFLS 第{st}段 遮断 {shed:,.0f} MW(継続中)",
                    transform=ax.transAxes, color="#8E96B8", fontsize=10,
                    va="top")
    else:
        # ── 第1幕: 事故の数十秒(ほぼ実速)
        ax.text(0.03, 0.965, "東日本全域 N-3実験 — 富津+東新潟+千葉 "
                "10.9GW同時脱落(設計外デモ)",
                transform=ax.transAxes, color="#C8CDD8", fontsize=13.5,
                fontweight="bold", va="top")
        ax.text(0.03, 0.915, lbl, transform=ax.transAxes, color="#FFFFFF",
                fontsize=18, fontweight="bold", va="top")
        cv = coi[k]
        ax.text(0.03, 0.862, f"系統平均 {cv:6.2f} Hz",
                transform=ax.transAxes, color=fcmap(cv - f0), fontsize=14,
                fontweight="bold", va="top")
        shed = tot_mw * 0.1 * st
        ax.text(0.03, 0.815,
                f"UFLS 第{st}段 / 遮断 {shed:,.0f} MW" if st else "UFLS 未発動",
                transform=ax.transAxes,
                color="#FF8A80" if st else "#5A648F", fontsize=12.5, va="top")
        if tt < 3.0:   # 凡例は序盤のみ(情報を減らす)
            ax.add_patch(FancyBboxPatch((0.018, 0.295), 0.40, 0.135,
                         transform=ax.transAxes, boxstyle="round,pad=0.012",
                         facecolor="#11152A", edgecolor="#3A4266", alpha=0.94,
                         zorder=9))
            ax.text(0.03, 0.415,
                    "● 発電機 — 色=その機の周波数(青=50Hz↔赤=低下)",
                    transform=ax.transAxes, color="#9EC1FF", fontsize=10.5,
                    va="top", zorder=10)
            ax.text(0.03, 0.375, "■ 負荷(黄) — UFLSの段ごとに1割ずつ縮む",
                    transform=ax.transAxes, color="#E0B93C", fontsize=10.5,
                    va="top", zorder=10)
            ax.text(0.03, 0.335, "× 脱落 — 赤=落とした3プラント / 灰=脱調保護",
                    transform=ax.transAxes, color="#FF8A80", fontsize=10.5,
                    va="top", zorder=10)
    ax.text(0.03, 0.03, "AGC-N 多機共シミュレーション(AGC30定数・実網Kron縮約"
            "・UCピーク断面59.4GW)", transform=ax.transAxes,
            color="#5A648F", fontsize=8.5, va="bottom")
    # 右: 全機周波数+COI
    axw = fig.add_axes([0.70, 0.10, 0.28, 0.80])
    axw.set_facecolor("#11152A")
    if act == 2:   # 第2幕はCOIパネルが主役 — 局面シェードを重ねる
        for x0, x1, _lb, c in PHASES:
            axw.axvspan(x0 + 1.0, min(x1 + 1.0, T_LAST), color=c, alpha=0.06)
    stride = max(1, len(t) // 2500)
    for i in range(n):
        if i in trips:
            continue
        axw.plot(t[::stride], fm[i, ::stride], lw=0.35, color="#5A78B8",
                 alpha=0.30)
    axw.plot(t[::stride], coi[::stride], lw=2.0 if act == 2 else 1.8,
             color="#FFFFFF")
    for s_hz, lb2 in ((-1.5, "第1段"), (-2.0, "第2段"), (-2.5, "第3段")):
        axw.axhline(f0 + s_hz, color="#C62828", lw=0.8, ls="--", alpha=0.6)
        axw.text(T_LAST * 0.99, f0 + s_hz + 0.03, f"UFLS{lb2}",
                 ha="right", color="#C62828", fontsize=7.5)
    for te in ev_t:
        axw.axvline(te, color="#C62828", lw=0.7, ls=":", alpha=0.7)
    axw.axvline(ts, color="#FFD60A", lw=1.5)
    # 第1幕は最初の20秒にズーム(事故が見える)、第2幕は全景
    if act == 1:
        axw.set_xlim(0, 20.0)
    else:
        axw.set_xlim(0, T_LAST)
    lo = np.nanmin(coi) - 0.5
    axw.set_ylim(lo, f0 + 0.3)
    axw.tick_params(colors="#8E96B8", labelsize=8)
    for sp in axw.spines.values():
        sp.set_color("#3A4266")
    axw.set_title(f"全{int(np.isfinite(w[:,0]).sum())}機の周波数(細線)+COI(白)"
                  + ("" if act == 2 else " — 最初の20秒"),
                  color="#C8CDD8", fontsize=10.5)
    axw.set_xlabel("時間 [s]", color="#8E96B8", fontsize=9)
    fig.canvas.draw()
    img = np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()
    plt.close(fig)
    return img

def interlude():
    fig = plt.figure(figsize=(12.8, 7.2), dpi=110)
    fig.patch.set_facecolor(BG)
    fig.text(0.5, 0.56, "ここから早送り", color="#FFFFFF", fontsize=34,
             fontweight="bold", ha="center")
    fig.text(0.5, 0.455,
             f"回復には{end_min:.0f}分かかる — その戻り方に、系統の余力が現れる",
             color="#C8CDD8", fontsize=15.5, ha="center")
    fig.text(0.5, 0.385,
             f"底 {floor_hz:.2f} Hz → 60秒で {f60:.2f} Hz → "
             f"{end_min:.0f}分で {f_end:.2f} Hz(50.00復帰はさらに数十分先)",
             color="#8E96B8", fontsize=12, ha="center")
    fig.canvas.draw()
    img = np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()
    plt.close(fig)
    return img

# ── タイムライン ──
frames, durs = [], []
ev_ufls = [te for te, sname in zip(ev_t, ev_s) if "UFLS" in str(sname)]
# 第1幕 0-20s
ACT1 = ([(0.0, 1400)] + [(1.0 + 0.5 * i, 550) for i in range(10)]
        + [(6.0 + 1.0 * i, 420) for i in range(9)] + [(17.5, 420), (20.0, 500)])
for ts, du in ACT1:
    flash = any(0 <= ts - te < 0.6 for te in ev_ufls)
    frames.append(render(ts, flash=flash, act=1)); durs.append(du)
# 幕間バナー
frames.append(interlude()); durs.append(1900)
# 第2幕 20-900s
ACT2 = ([(20.0 + 10.0 * i, 420, 30) for i in range(4)]       # 〜60s
        + [(60.0 + 20.0 * i, 420, 30) for i in range(6)]     # 〜180s 停滞
        + [(180.0 + 60.0 * i, 420, 120)
           for i in range(int((T_LAST - 180) / 60))])        # 〜900s
for ts, du, spd in ACT2:
    if ts > T_LAST:
        break
    frames.append(render(ts, speed=spd, act=2)); durs.append(du)
frames.append(render(T_LAST - 0.02, speed=120, act=2)); durs.append(3200)

from PIL import Image
ims = [Image.fromarray(f) for f in frames]
out = "docs/slides/ajg/assets/east_incident.gif"
ims[0].save(out, save_all=True, append_images=ims[1:], duration=durs, loop=0,
            optimize=True)
print(f"-> {out} ({len(ims)}フレーム, {os.path.getsize(out)/1e6:.1f}MB)")
