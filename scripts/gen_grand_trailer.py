#!/usr/bin/env python3
"""All-Japan-Grid 全史トレーラーGIF — 組み上げ→UC→AC点灯→西の夜→擾乱→24/24 (2026-08-30).

「もっと全体を通してすごいgif」(オーナー)。約45秒・全レイヤー実データ。
状態演出(島の点灯/減光)は模式であることをフレーム内に明記。

出力: docs/slides/ajg/assets/grand_trailer.gif
"""
import glob, json, math, os
import numpy as np
os.chdir("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

KV_STYLE = [(400, "#FF3B30"), (250, "#FF9500"), (140, "#BF5AF2"),
            (90, "#34C759"), (40, "#32ADE6"), (0, "#5A6270")]
def kv_color(kv):
    for mn, c in KV_STYLE:
        if kv >= mn: return c
    return KV_STYLE[-1][1]

b = json.load(open("docs/data/built/all.json"))
edges = [e for e in b["edges"] if e.get("path") and len(e["path"]) >= 2]
segs = [[(p[1], p[0]) for p in e["path"]] for e in edges]
kvs = [float(e.get("kv") or 0) for e in edges]
lon0 = np.array([s[0][0] for s in segs]); lat0 = np.array([s[0][1] for s in segs])
order = np.argsort(lon0)
subs = [(n["lon"], n["lat"], n.get("deg", 1)) for n in b["nodes"] if n.get("sub") == 1]
plants = []
for f in glob.glob("data/*_plants.geojson"):
    for ft in json.load(open(f))["features"]:
        g = ft.get("geometry") or {}
        if g.get("type") == "Point":
            lo, la = g["coordinates"][:2]
        else:
            try:
                arr = np.array(g["coordinates"][0] if g.get("type") == "Polygon"
                               else g["coordinates"], dtype=float).reshape(-1, 2)
                lo, la = float(arr[:, 0].mean()), float(arr[:, 1].mean())
            except Exception:
                continue
        try: cap = float(ft["properties"].get("capacity_mw") or 0)
        except Exception: cap = 0.0
        if cap >= 100:
            plants.append((lo, la, cap))

# east擾乱データ(実シミュ)
z = np.load("docs/data/agc/mm_traces_east_n3pk.npz", allow_pickle=True)
mt, mw, mf0 = z["t"], z["w"], float(z["f0"])
mlon, mlat, mS, mM = z["lon"], z["lat"], z["S"], z["M"]
mtrips = [int(x) for x in z["trips"]]
mev_t, mev_s = z["ev_t"], z["ev_s"]
mfin = np.isfinite(mw)
mcoi = np.array([mf0 + (mM[m] * mw[m, i]).sum() / mM[m].sum() * mf0
                 if (m := mfin[:, i]).any() else np.nan for i in range(len(mt))])

def island_of(lo, la):
    if la > 41.3: return "hokkaido"
    if lo < 129.0 and la < 28.0: return "okinawa"
    if lo >= 137.0 and la >= 34.5 or lo >= 139.0: return "east"
    return "west"
seg_isl = [island_of(x, y) for x, y in zip(lon0, lat0)]

BG = "#0A0D1A"
X0, X1, Y0, Y1 = 128.6, 146.2, 30.2, 45.9
def canvas():
    fig = plt.figure(figsize=(12.8, 7.2), dpi=110); fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_facecolor(BG)
    ax.set_xlim(X0, X1); ax.set_ylim(Y0, Y1)
    ax.set_aspect(1.0 / np.cos(np.radians(37.0))); ax.axis("off")
    return fig, ax

def draw_grid(ax, frac=1.0, colored=True, dim_isl=None, bright_isl=None):
    n_show = int(len(order) * frac)
    idx = order[:n_show]
    by = {}
    for i in idx:
        isl = seg_isl[i]
        c = kv_color(kvs[i]) if colored else "#9AA3B8"
        a, lw = 0.72, 0.5
        if dim_isl and isl in dim_isl: a, lw = 0.16, 0.4
        if bright_isl and isl in bright_isl: a, lw = 0.95, 0.7
        by.setdefault((c, a, lw), []).append(segs[i])
    for (c, a, lw), ss in by.items():
        ax.add_collection(LineCollection(ss, colors=c, linewidths=lw,
                                         alpha=a, zorder=2))

def hud(ax, act, title, sub, note=None, col="#FFFFFF"):
    ax.text(0.025, 0.955, act, transform=ax.transAxes, color="#69F0AE",
            fontsize=12.5, fontweight="bold", va="top")
    ax.text(0.025, 0.905, title, transform=ax.transAxes, color=col,
            fontsize=22, fontweight="bold", va="top")
    ax.text(0.025, 0.835, sub, transform=ax.transAxes, color="#A7B0CB",
            fontsize=12.5, va="top")
    if note:
        ax.text(0.025, 0.03, note, transform=ax.transAxes, color="#5A648F",
                fontsize=9, va="bottom")

def snap(fig):
    fig.canvas.draw()
    img = np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()
    plt.close(fig)
    return img

F, D = [], []
def add(img, ms): F.append(img); D.append(ms)

# ── 幕0: タイトル
fig, ax = canvas()
draw_grid(ax, colored=True)
ax.text(0.5, 0.56, "All-Japan-Grid", transform=ax.transAxes, color="#FFFFFF",
        fontsize=44, fontweight="bold", ha="center")
ax.text(0.5, 0.46, "公開データだけで、日本全体の系統モデルを作り、動かす",
        transform=ax.transAxes, color="#C8CDD8", fontsize=16, ha="center")
ax.text(0.5, 0.40, "— 6ヶ月の全記録、45秒 —", transform=ax.transAxes,
        color="#69F0AE", fontsize=12.5, ha="center")
add(snap(fig), 3000)

# ── 幕1: 組み上げ
for fr in (0.25, 0.55, 1.0):
    fig, ax = canvas(); draw_grid(ax, frac=fr, colored=False)
    hud(ax, "第1幕 — 組み上げ", "OSMから送電線を拾う",
        "40,077本のジオメトリ(西→東)", "全レイヤー実データ")
    add(snap(fig), 700)
fig, ax = canvas(); draw_grid(ax, colored=True)
hud(ax, "第1幕 — 組み上げ", "電圧を決め、端点を結ぶ",
    "7段補完でタグ欠測87%減 — 色=電圧階級")
add(snap(fig), 1600)
fig, ax = canvas(); draw_grid(ax, colored=True)
ax.scatter([p[0] for p in subs], [p[1] for p in subs],
           s=[1.6 + 0.9 * min(d, 8) for _, _, d in subs], c="#FFFFFF",
           alpha=0.8, zorder=5, linewidths=0)
ax.scatter([p[0] for p in plants], [p[1] for p in plants],
           s=[12 + c / 70 for _, _, c in plants], marker="*", c="#FFB300",
           edgecolors="#7A4E00", linewidths=0.3, zorder=6)
hud(ax, "第1幕 — 組み上げ", "変電所6,962・発電所を接続",
    "白丸=変電所 / ★=発電所(≥100MW表示) — 需要は県別実需要で配分")
add(snap(fig), 2200)

# ── 幕2: UC
fig, ax = canvas(); draw_grid(ax, colored=True, dim_isl=set())
ax.scatter([p[0] for p in plants], [p[1] for p in plants],
           s=[20 + c / 40 for _, _, c in plants], marker="*", c="#FFD60A",
           edgecolors="#7A4E00", linewidths=0.3, zorder=6, alpha=0.95)
hud(ax, "第2幕 — 計画", "757機・9連系線の起動停止計画(UC)を10秒で最適化",
    "混雑費用+1.4%を検出 — この解が以降の全実験の土台")
add(snap(fig), 2600)

# ── 幕3: AC点灯(模式) — 東側は解けたが西だけ解けない
fig, ax = canvas()
draw_grid(ax, colored=True, dim_isl={"west"}, bright_isl={"hokkaido", "east", "okinawa"})
hud(ax, "第3幕 — 潮流", "3島はACで解けた。西日本だけが、解けない",
    "北海道・東日本・沖縄=AC成立 / 西=何をしてもdc_fallback",
    "点灯/減光は状態の模式表現", col="#FFB74D")
ax.text(133.5, 33.0, "?", fontsize=60, color="#FF5252", fontweight="bold",
        ha="center")
add(snap(fig), 2800)
# 探偵編ワンカット
fig, ax = canvas()
draw_grid(ax, colored=True, dim_isl={"hokkaido", "east", "okinawa"})
ax.annotate("軽井沢・嬬恋\n(誤帰属の50Hz設備)", xy=(138.45, 36.35),
            xytext=(140.5, 38.6), color="#FF8A80", fontsize=12,
            fontweight="bold",
            arrowprops=dict(arrowstyle="->", color="#FF8A80", lw=1.4))
ax.annotate("大阪都心\n(上位接続の欠測)", xy=(135.5, 34.75),
            xytext=(130.3, 32.3), color="#FFB74D", fontsize=12,
            fontweight="bold",
            arrowprops=dict(arrowstyle="->", color="#FFB74D", lw=1.4))
hud(ax, "第4幕 — 探偵編", "犯人は2人いた",
    "①都心給電の欠測(OSMに地中網が無い) ②50Hz設備の誤帰属(抽出bboxこぼれ)",
    "介入#37(仮)都心給電・#38跨ぎ是正・#39帳簿修復 — 全件台帳・可逆")
add(snap(fig), 3200)
# 西点灯
fig, ax = canvas()
draw_grid(ax, colored=True, bright_isl={"hokkaido", "east", "okinawa", "west"})
hud(ax, "第4幕 — 点灯", "西日本 7,928バス、史上初のAC解",
    "4島すべてAC — 西は24時間全時刻で成立(served 100%)",
    "点灯は模式・数値は正典ラン(docs/reports/west_ac_wave6-8)", col="#69F0AE")
add(snap(fig), 3000)

# ── 幕5: 東N-3擾乱(実シミュ)
ms_m = 16.0 * np.sqrt(np.maximum(mS, 5.0) / 500.0)
def fcol(df, span=0.8):
    x = min(max(-df / span, 0.0), 1.0)
    if x < 0.5:
        u = x / 0.5; c0, c1 = np.array([0.56, 0.72, 1.0]), np.array([1.0, 0.97, 0.85])
    else:
        u = (x - 0.5) / 0.5; c0, c1 = np.array([1.0, 0.97, 0.85]), np.array([0.88, 0.1, 0.1])
    return c0 + (c1 - c0) * u
for ts, du in ((0.9, 900), (1.6, 900), (3.0, 900), (5.3, 1300), (12.0, 900),
               (59.5, 1800)):
    k = min(len(mt) - 1, int(np.searchsorted(mt, ts)))
    st = sum(1 for te, sn in zip(mev_t, mev_s) if "UFLS" in str(sn) and te <= ts)
    fig, ax = canvas()
    draw_grid(ax, colored=True, dim_isl={"west", "okinawa", "hokkaido"})
    for i in range(mw.shape[0]):
        if not np.isfinite(mlon[i]): continue
        if not np.isfinite(mw[i, k]):
            big = i in mtrips
            ax.scatter([mlon[i]], [mlat[i]], marker="X", s=200 if big else 60,
                       c="#D62728" if big else "#7A7F99",
                       edgecolors="#FFFFFF", linewidths=0.7 if big else 0.3,
                       zorder=8)
            continue
        ax.scatter([mlon[i]], [mlat[i]], s=ms_m[i],
                   color=fcol(mf0 + mw[i, k] * mf0 - mf0), zorder=6,
                   edgecolors="#FFFFFF", linewidths=0.25)
    cv = mcoi[k]
    flash = st and any(0 <= ts - te < 0.7 for te in mev_t if True)
    hud(ax, "第5幕 — 擾乱実験(東・実シミュ)",
        f"事故から{ts-1.0:5.1f}秒 — 系統平均 {cv:.2f} Hz",
        "N-3設計外デモ: 富津+東新潟+千葉 10.9GW同時脱落 → "
        + (f"UFLS第{st}段が発動(遮断5,935MW)" if st else "183機が一斉に沈む"),
        "●=発電機(色=各機の周波数) ×=脱落 — AGC30定数・実網Kron縮約",
        col=("#FF8A80" if cv < 49 else "#FFFFFF"))
    add(snap(fig), du)

# ── フィナーレ
fig, ax = canvas()
draw_grid(ax, colored=True)
ax.scatter([p[0] for p in subs], [p[1] for p in subs],
           s=[1.6 + 0.9 * min(d, 8) for _, _, d in subs], c="#FFFFFF",
           alpha=0.75, zorder=5, linewidths=0)
ax.text(0.5, 0.60, "地図はあった。モデルが無かった。", transform=ax.transAxes,
        color="#C8CDD8", fontsize=17, ha="center")
ax.text(0.5, 0.52, "いまは、ある。", transform=ax.transAxes, color="#FFFFFF",
        fontsize=27, fontweight="bold", ha="center")
ax.text(0.5, 0.42,
        "UC → AC潮流(4島・西24/24) → AGC/多機動揺 → 変電所の中(SubSLD)まで",
        transform=ax.transAxes, color="#69F0AE", fontsize=13, ha="center")
ax.text(0.5, 0.36, "github.com/lutelute/All-Japan-Grid — 介入は全件台帳・捏造ゼロ",
        transform=ax.transAxes, color="#8E96B8", fontsize=11, ha="center")
add(snap(fig), 4200)

from PIL import Image
ims = [Image.fromarray(f) for f in F]
out = "docs/slides/ajg/assets/grand_trailer.gif"
ims[0].save(out, save_all=True, append_images=ims[1:], duration=D, loop=0,
            optimize=True)
print(f"-> {out} ({len(ims)}フレーム, {sum(D)/1000:.0f}s, "
      f"{os.path.getsize(out)/1e6:.1f}MB)")
