#!/usr/bin/env python3
"""系統の強さの地図 — 全バス短絡容量(SCC)マップ(2026-08-30).

オーナー要望「SCRももっとやってほしい」への応答。UCピーク断面の運転中機
(古典機・Xd'背後電圧)+実網Ybusから各バスのテブナンZを求め、
SCC = S_base·|1/Z_th,ii| [MVA] を全バスで着色する。

定義と近似(正直に開示):
  - 機械は Xd' の背後に V=1.0 の定電圧源(古典近似・IEC非準拠)
  - 負荷アドミタンスは除外(慣行)・変圧器/線路は実網Ybusのまま
  - 運転中機のみ(UCで停止中のプラントは寄与しない)
  - SCR(短絡比)= SCC / 対象設備MVA — 設備を決めれば本図から読める

出力: docs/slides/ajg/assets/scr_map.png
"""
import argparse, json, math, os, re, sys
import numpy as np
os.chdir("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid")
sys.path.insert(0, os.getcwd())
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap, LogNorm
from matplotlib.patches import FancyBboxPatch
import scipy.sparse as sp
from scipy.sparse.linalg import splu
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

from scripts.run_multimachine_national import (build_case, extract_model,
                                               S_BASE_MVA)
from scripts.run_full_powerflow_from_db import BUILT
from src.powerflow.load_estimator import load_demand_config
from src.powerflow.pref_demand import pref_zone_gwh
from src.uc.scenario import build_national_scenario
from src.uc.solver import solve_uc

ap = argparse.ArgumentParser()
ap.add_argument("--cache", default="",
                help="計算結果(座標・SCC・名前・負荷)のnpz。存在すれば再利用し、"
                     "無ければ計算後に保存 — レイアウト調整の反復を高速化(計算は約6分)")
args = ap.parse_args()

pts = []          # (lon, lat, scc_mva, name, vn_kv, load_mw, island)
if args.cache and os.path.exists(args.cache):
    _z = np.load(args.cache, allow_pickle=True)
    pts = [tuple(r) for r in _z["pts"]]
    pts = [(float(a), float(b), float(c), str(d), float(e), float(f), str(g))
           for a, b, c, d, e, f, g in pts]
    print(f"キャッシュ再利用: {args.cache} ({len(pts):,}バス)")

if not pts:
  scn = build_national_scenario(scenario="fy2023r2")
  uc = solve_uc(scn.to_uc_parameters()); assert uc.is_optimal
  built = json.load(open(BUILT)); cfg = load_demand_config()
  pref_gwh, _ = pref_zone_gwh(built["nodes"])

  for island in ("hokkaido", "east", "west", "okinawa"):
    net, mode, f0 = build_case(island, scn, uc, built, cfg, pref_gwh)
    machines, Em, delta0, kron, load0 = extract_model(net, mode, f0)
    Ysp = net._ppc["internal"]["Ybus"].tocsr()
    nb = Ysp.shape[0]
    rows, vals = [], []
    for m in machines:
        rows.append(m["bus"]); vals.append(1.0 / (1j * m["Xdp"]))
    Ysc = (Ysp + sp.csr_matrix((vals, (rows, rows)), shape=(nb, nb),
                               dtype=complex) +
           sp.diags(np.full(nb, 1e-9 + 0j))).tocsc()
    lu = splu(Ysc)
    zdiag = np.zeros(nb, dtype=complex)
    step = 800
    for s0 in range(0, nb, step):
        e = np.zeros((nb, min(step, nb - s0)), dtype=complex)
        for j in range(e.shape[1]):
            e[s0 + j, j] = 1.0
        X = lu.solve(e)
        for j in range(e.shape[1]):
            zdiag[s0 + j] = X[s0 + j, j]
    scc = S_BASE_MVA / np.maximum(np.abs(zdiag), 1e-9)
    # バス→座標・名前・負荷
    lookup = net._pd2ppc_lookups["bus"]
    load_by_bus = {}
    for i in net.load.index:
        if bool(net.load.at[i, "in_service"]):
            b = int(lookup[int(net.load.at[i, "bus"])])
            load_by_bus[b] = load_by_bus.get(b, 0.0) + \
                float(net.load.at[i, "p_mw"])
    for pd_idx in net.bus.index:
        b = int(lookup[int(pd_idx)])
        if b < 0 or b >= nb:
            continue
        try:
            g = json.loads(net.bus.at[pd_idx, "geo"])
            lo, la = g["coordinates"][0], g["coordinates"][1]
        except Exception:  # noqa: BLE001
            continue
        pts.append((lo, la, float(scc[b]), str(net.bus.at[pd_idx, "name"]),
                    float(net.bus.at[pd_idx, "vn_kv"]),
                    load_by_bus.get(b, 0.0), island))
    print(f"[{island}] buses={nb} SCC範囲 {scc.min():,.0f}〜{scc.max():,.0f} MVA")
  if args.cache:
    np.savez_compressed(args.cache, pts=np.array(pts, dtype=object))
    print(f"キャッシュ保存: {args.cache}")

lon = np.array([p[0] for p in pts]); lat = np.array([p[1] for p in pts])
scc = np.array([p[2] for p in pts]); lmw = np.array([p[5] for p in pts])

# 背景線形
b = json.load(open("docs/data/built/all.json"))
segs = [[(q[1], q[0]) for q in e["path"]] for e in b["edges"]
        if e.get("path") and len(e["path"]) >= 2]

BG = "#0A0D1A"
cmap = LinearSegmentedColormap.from_list(
    "scr", ["#D62728", "#FF9500", "#FFE28A", "#8FD3A5", "#4E9BFF"])
fig = plt.figure(figsize=(12.8, 7.2), dpi=150)
fig.patch.set_facecolor(BG)
# 下端0.115を注記帯として空ける(旧: 地図が下端まで伸び九州の点群と注記が重なった)
ax = fig.add_axes([0.0, 0.115, 0.78, 0.885]); ax.set_facecolor(BG)
ax.set_xlim(128.6, 146.2); ax.set_ylim(30.2, 45.9)
ax.set_aspect(1.0 / math.cos(math.radians(37.0))); ax.axis("off")
ax.add_collection(LineCollection(segs, colors="#1C2340", linewidths=0.35,
                                 alpha=0.8, zorder=1))
norm = LogNorm(vmin=200, vmax=50000)
conn = scc >= 10.0                 # 電源への電気的経路があるバス
frag = ~conn                       # 孤立断片(定注入扱いの島など) — 灰で開示
ax.scatter(lon[frag], lat[frag], c="#3A4155", s=3.0, zorder=4, linewidths=0)
order = np.argsort(scc[conn])[::-1]
li, la_, sv = lon[conn][order], lat[conn][order], scc[conn][order]
sc = ax.scatter(li, la_, c=sv, s=4.5, cmap=cmap, norm=norm, zorder=5,
                linewidths=0)
# 弱点コールアウト: 接続済みで負荷があるのにSCCが低いバス(全国ワースト)
SYNTH_ID = re.compile(r"^[a-z_]+_\d+$")     # 例 tokyo_sub_1855(合成ID・実名でない)


def disp_name(nm):
    """注記に出してよい実名か判定し、表示用に整える(不可ならNone)。

    姉妹図 gen_loading_map.py と同じ方針: 合成IDと会社名は『変電所名ですか?』
    と聞かれるだけで情報にならないため落とす。長い名前は末尾を…で省略。
    """
    nm = (nm or "").strip()
    if not nm or SYNTH_ID.match(nm):
        return None
    if "株式会社" in nm or "(株)" in nm or "（株）" in nm:
        return None
    return nm if len(nm) <= 16 else nm[:15] + "…"


mask = conn & (lmw > 5.0)
worst = np.argsort(np.where(mask, scc, np.inf))[:400]
shown = []
for i in worst:
    if len(shown) >= 5:
        break
    if not np.isfinite(scc[i]) or not mask[i]:
        continue
    if disp_name(pts[i][3]) is None:
        continue
    if any(abs(lon[i] - lon[j]) < 1.1 and abs(lat[i] - lat[j]) < 1.1
           for j in shown):
        continue
    shown.append(i)
# ラベルは地図の左余白に固定スロットで並べる(姉妹図 gen_loading_map.py と同方式)。
# 旧: 点の近くに交互配置 → 3枚が中央下部で重なり点群にも埋もれて読めなかった
shown.sort(key=lambda i: -lat[i])          # 北の点ほど上のスロット(引出線の交差を減らす)
for rank, i in enumerate(shown):
    nm = disp_name(pts[i][3])
    ax.annotate(f"{nm}\nSCC {scc[i]:,.0f} MVA / 負荷{lmw[i]:.0f} MW",
                xy=(lon[i], lat[i]), xycoords="data",
                xytext=(0.022, 0.70 - 0.10 * rank),
                textcoords="figure fraction",
                color="#FF8A80", fontsize=8, va="center", ha="left",
                linespacing=1.5,
                arrowprops=dict(arrowstyle="->", color="#FF8A80", lw=0.7,
                                alpha=0.8,
                                connectionstyle="arc3,rad=0.12"))
# 見出しの背後にも同じ暗色帯(北海道の点群がサブタイトルに薄くかぶるため)
fig.patches.append(FancyBboxPatch(
    (0.160, 0.893), 0.615, 0.098, transform=fig.transFigure,
    boxstyle="round,pad=0.004", facecolor="#0A0D1A", edgecolor="none",
    alpha=0.72, zorder=20))
# 見出しも図座標に置く(fig.patchesはaxesより前面に描かれるため、帯を使うなら
# 文字も図レベルに揃える必要がある — ax.textのままだと帯に隠れる)
# タイトルはスライド側のテキストボックスへ(PowerPointで編集可能にするため
# — オーナー指摘「GIFに焼き込むと編集できない」)
fig.text(0.175, 0.970,
         f"UCピーク断面・全4島 {int(conn.sum()):,}バス — 青=強い / 赤=弱い"
         f"(対数) / 灰={int(frag.sum()):,}孤立断片(電源経路なし)",
         color="#A7B0CB", fontsize=11.5, va="top", zorder=21)
# 近似の前提=技術報告の核心。地図の外(図下端の帯)に置き、暗色ボックスで確実に読ませる
fig.patches.append(FancyBboxPatch(
    (0.020, 0.008), 0.755, 0.098, transform=fig.transFigure,
    boxstyle="round,pad=0.004", facecolor="#0A0D1A", edgecolor="#2A3050",
    linewidth=0.8, alpha=0.82, zorder=20))
fig.text(0.030, 0.018,
         "SCC = S_base·|1/Z_th|(古典近似: 運転中機のXd'背後V=1.0・負荷除外・実網Ybus)\n"
         "SCR(短絡比) = SCC ÷ 連系する設備の容量 — 赤い場所ほどインバータ電源の連系が難しい\n"
         "注記のバスは『接続済みで負荷があるのに弱い』全国ワースト5(近接は代表1点・断片除外)",
         color="#9AA3C0", fontsize=9, va="bottom", zorder=21, linespacing=1.5)
cax = fig.add_axes([0.80, 0.15, 0.018, 0.62])
cb = fig.colorbar(sc, cax=cax)
cb.set_label("短絡容量 SCC [MVA]", color="#C8CDD8", fontsize=10, labelpad=14)
cb.ax.tick_params(colors="#8E96B8", labelsize=8)
cb.outline.set_edgecolor("#3A4266")
out = "docs/slides/ajg/assets/scr_map.png"
fig.savefig(out, facecolor=BG)
print(f"-> {out}")
