#!/usr/bin/env python3
"""OSM→系統モデルの組み上げアニメGIF — 「手順が見える」デッキ素材(2026-08-30).

実データ(docs/data/built/all.json + data/*_plants.geojson)のレイヤーを、
パイプラインが作る順に出現させる。各フレームは実データのみ(捏造なし)。

出力: docs/slides/ajg/assets/pipeline_buildup.gif
"""
import glob, json, os, sys
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
lon0 = [s[0][0] for s in segs]
order = np.argsort(lon0)                      # 西→東の決定的スイープ
subs = [(n["lon"], n["lat"], n.get("deg", 1)) for n in b["nodes"] if n.get("sub") == 1]
jcts = [(n["lon"], n["lat"]) for n in b["nodes"] if n.get("sub") != 1]
plants = []
for f in glob.glob("data/*_plants.geojson"):
    for ft in json.load(open(f))["features"]:
        g = ft.get("geometry") or {}
        if g.get("type") == "Point":
            lo, la = g["coordinates"][:2]
        else:
            cs = g.get("coordinates")
            try:
                arr = np.array(cs[0] if g.get("type") == "Polygon" else cs,
                               dtype=float).reshape(-1, 2)
                lo, la = float(arr[:, 0].mean()), float(arr[:, 1].mean())
            except Exception:
                continue
        cap = ft["properties"].get("capacity_mw") or 0
        try: cap = float(cap)
        except Exception: cap = 0.0
        if cap >= 100:
            plants.append((lo, la, cap))
print(f"edges={len(segs)} subs={len(subs)} jcts={len(jcts)} plants≥100MW={len(plants)}")

BG = "#0A0D1A"
X0, X1, Y0, Y1 = 128.6, 146.2, 30.2, 45.9

def frame(step_no, title, sub, *, edge_frac=1.0, colored=False, show_jct=False,
          show_sub=False, show_plant=False, endcard=False):
    fig = plt.figure(figsize=(12.8, 7.2), dpi=110); fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_facecolor(BG)
    ax.set_xlim(X0, X1); ax.set_ylim(Y0, Y1)
    ax.set_aspect(1.0 / np.cos(np.radians(37.0))); ax.axis("off")
    n_show = int(len(order) * edge_frac)
    idx = order[:n_show]
    if colored:
        by = {}
        for i in idx:
            by.setdefault(kv_color(kvs[i]), []).append(segs[i])
        for c, ss in by.items():
            ax.add_collection(LineCollection(ss, colors=c, linewidths=0.55,
                                             alpha=0.75, zorder=2))
    else:
        ax.add_collection(LineCollection([segs[i] for i in idx],
                                         colors="#9AA3B8", linewidths=0.45,
                                         alpha=0.55, zorder=2))
    if show_jct:
        ax.scatter([p[0] for p in jcts], [p[1] for p in jcts], s=1.2,
                   c="#FFD60A", alpha=0.6, zorder=4, linewidths=0)
    if show_sub:
        ax.scatter([p[0] for p in subs], [p[1] for p in subs],
                   s=[2.0 + 1.1 * min(d, 8) for _, _, d in subs],
                   c="#FFFFFF", alpha=0.85, zorder=5, linewidths=0)
    if show_plant:
        ax.scatter([p[0] for p in plants], [p[1] for p in plants],
                   s=[14 + cap / 60 for _, _, cap in plants], marker="*",
                   c="#FFB300", edgecolors="#7A4E00", linewidths=0.3,
                   alpha=0.95, zorder=6)
    ax.text(0.025, 0.955, title, transform=ax.transAxes, color="#FFFFFF",
            fontsize=21, fontweight="bold", va="top")
    ax.text(0.025, 0.885, sub, transform=ax.transAxes, color="#A7B0CB",
            fontsize=13, va="top")
    if colored and not endcard:
        for i, (mn, c) in enumerate(KV_STYLE[:-1]):
            lbl = {400: "500 kV級", 250: "275 kV級", 140: "154/187 kV",
                   90: "110 kV", 40: "66/77 kV"}[mn]
            ax.text(0.855, 0.30 - i * 0.045, "━ " + lbl,
                    transform=ax.transAxes, color=c, fontsize=11,
                    fontweight="bold")
    if endcard:
        ax.text(0.025, 0.115, "ここまでが「ベースモデル」— この上で UC(起動停止計画) → AC潮流 → AGC(周波数制御) が動く",
                transform=ax.transAxes, color="#69F0AE", fontsize=13.5,
                fontweight="bold")
    ax.text(0.025, 0.03,
            "全レイヤー実データ(docs/data/built/all.json + plants geojson・発電所は≥100MW表示・沖縄は枠外)",
            transform=ax.transAxes, color="#5A648F", fontsize=9)
    fig.canvas.draw()
    img = np.asarray(fig.canvas.buffer_rgba())[..., :3].copy(); plt.close(fig)
    return img

F = []; D = []
def hold(img, n): F.append(img); D.append(200 * n)

# 総題「OSMから、日本全体の系統モデルを組む」はスライド側のテキストボックスへ
# 移した(GIFに焼き込むとPowerPointで直せない — オーナー指摘)。①〜⑥の段階名は
# アニメの内容そのものなのでGIF内に残し、先頭カードは行程表に置き換える。
hold(frame(0, "これから6段階で組み上げる", "① 送電線 → ② 電圧 → ③ 結線 → ④ 変電所 → ⑤ 発電所 → ⑥ 需要配分", edge_frac=0.0), 8)
for fr in (0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1.0):
    hold(frame(1, "① 送電線をOSMから拾う", "40,077本の送電線ジオメトリ(西→東へ描画中)", edge_frac=fr), 2)
hold(frame(1, "① 送電線をOSMから拾う", "40,077本の送電線ジオメトリ", edge_frac=1.0), 6)
hold(frame(2, "② 電圧階級を決める", "タグ欠測は7段の補完で87%減 — 線の色=電圧", colored=True), 12)
hold(frame(3, "③ 端点を結ぶ", "端点マッチング(Haversine)で線同士を接続 — 黄点=生成されたジャンクション", colored=True, show_jct=True), 10)
hold(frame(4, "④ 変電所を立てる", "白丸=変電所(大きさ=接続本数)。同一地点の異電圧間には変圧器", colored=True, show_jct=True, show_sub=True), 10)
hold(frame(5, "⑤ 発電所を最寄り変電所に接続", "★=発電所(≥100 MW表示・大きさ=容量)。燃料別パラメータを付与", colored=True, show_jct=True, show_sub=True, show_plant=True), 10)
hold(frame(6, "⑥ 需要を配って、モデル完成", "県別実需要×電圧クラス重みで各変電所へ配分", colored=True, show_jct=True, show_sub=True, show_plant=True, endcard=True), 16)
from PIL import Image
ims = [Image.fromarray(f) for f in F]
out = "docs/slides/ajg/assets/pipeline_buildup.gif"
ims[0].save(out, save_all=True, append_images=ims[1:], duration=D, loop=0,
            optimize=True)
print(f"-> {out} ({len(ims)}フレーム, {os.path.getsize(out)/1e6:.1f}MB)")
