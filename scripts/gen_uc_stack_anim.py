#!/usr/bin/env python3
"""UC 24時間ディスパッチ積み上げGIF — 燃料別発電の一日(2026-08-30).

オーナー要望「UC関連ももっとやってほしい」。fy2023r2シナリオの全国UC解
(757機・9連系線・求解約10秒)を、50Hz系(北海道+東日本)と60Hz系(西日本+沖縄)の
上下2段で燃料別積み上げ×24時間にする。時刻カーソルが掃引し、HUDに内訳GW。

数値は全てUC解由来: 発電=uc_snapshot(スピルは燃料比例で控除・正典と同じ)、
白線=純需要+揚水等充電(uc_to_pf_built と同じ収支式)。積み上げと白線の差=
FC/連系線経由の純輸出入と解釈できる(その旨キャプション明記)。

出力: docs/slides/ajg/assets/uc_dispatch_stack.gif
"""
import os, sys
import numpy as np
os.chdir("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid")
sys.path.insert(0, os.getcwd())
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

from scripts.run_full_powerflow_from_db import ISLAND_OF
from src.uc.scenario import build_national_scenario
from src.uc.solver import solve_uc
from src.uc.pf_injection import uc_snapshot

scn = build_national_scenario(scenario="fy2023r2")
uc = solve_uc(scn.to_uc_parameters())
assert uc.is_optimal

# 揚水等の充電(負出力)を地域別に集計 — uc_to_pf_built と同一の収支式
_gmap = {g.id: g for g in scn.generators}
charge_r = {}
for s in uc.schedules:
    g = _gmap.get(s.generator_id)
    if g is None:
        continue
    arr = charge_r.setdefault(g.region, [0.0] * len(s.power_output_mw))
    for i, pv in enumerate(s.power_output_mw):
        if pv < 0:
            arr[i] += -float(pv)

GROUPS = {
    "50Hz系(北海道+東日本)": [r for r, (isl, _f) in ISLAND_OF.items()
                             if isl in ("hokkaido", "east")],
    "60Hz系(西日本+沖縄)": [r for r, (isl, _f) in ISLAND_OF.items()
                           if isl in ("west", "okinawa")],
}
T = 24

def snap_scaled(r, t):
    """正典(uc_to_pf_built)と同じ: スピルを燃料比例で控除した燃料別MW。"""
    fu = uc_snapshot(uc, scn.generators, t, region=r)
    sp = (uc.regional_spill_mw.get(r) or [])
    v = float(sp[t]) if t < len(sp) else 0.0
    if v > 1e-6:
        tot = sum(fu.values())
        fu = ({k: mw * (tot - v) / tot for k, mw in fu.items()}
              if tot > v else {k: 0.0 for k in fu})
    return fu

# 集計: group -> fuel -> 24h配列 / 需要+充電
data, demand = {}, {}
fuels_seen = set()
for gname, regions in GROUPS.items():
    acc = {}
    dem = np.zeros(T)
    for t in range(T):
        for r in regions:
            for f, mw in snap_scaled(r, t).items():
                acc.setdefault(f, np.zeros(T))[t] += mw
            ch = charge_r.get(r) or []
            dem[t] += float(scn.net_demand_r[r][t]) + \
                (float(ch[t]) if t < len(ch) else 0.0)
    data[gname], demand[gname] = acc, dem
    fuels_seen |= set(acc)

ORDER = ["nuclear", "geothermal", "biomass", "coal", "lng", "oil",
         "hydro", "pumped_hydro", "battery", "solar", "wind", "unknown"]
COL = {"nuclear": "#8E6BC7", "geothermal": "#2E8B57", "biomass": "#7CB342",
       "coal": "#4A4A55", "lng": "#E8833A", "oil": "#8B5A2B",
       "hydro": "#3D7EDB", "pumped_hydro": "#7FB3E8", "battery": "#B39DDB",
       "solar": "#E8C36A", "wind": "#4EC9C9", "unknown": "#9E9E9E"}
JP = {"nuclear": "原子力", "geothermal": "地熱", "biomass": "バイオマス",
      "coal": "石炭", "lng": "LNG", "oil": "石油", "hydro": "水力",
      "pumped_hydro": "揚水", "battery": "蓄電池", "solar": "太陽光",
      "wind": "風力", "unknown": "不明"}
fuels = [f for f in ORDER if f in fuels_seen] + \
        sorted(fuels_seen - set(ORDER))
for f in fuels_seen - set(ORDER):
    COL.setdefault(f, "#9E9E9E"); JP.setdefault(f, f)
# 全24時刻・全系で50MW未満の燃料は積み上げにも凡例にも出さない。
# とくに「不明」が凡例だけに居ると『燃料不明の機があるのか』と説明時間を取られる
_MIN_MW = 50.0
_drop = [f for f in fuels
         if max(float(np.max(data[g].get(f, np.zeros(1)))) for g in GROUPS)
         < _MIN_MW]
if _drop:
    print("凡例から除外(全時刻で50MW未満): " + ", ".join(JP.get(f, f)
                                                        for f in _drop))
    fuels = [f for f in fuels if f not in _drop]

# 整合チェック(レンダ前に必ず出す): 発電合計 vs 需要+充電
for gname in GROUPS:
    gen_pk = sum(v[np.argmax(demand[gname])] for v in data[gname].values())
    d_pk = demand[gname].max()
    print(f"[check] {gname}: ピーク需要+充電 {d_pk/1e3:.1f}GW / "
          f"同時刻発電 {gen_pk/1e3:.1f}GW (差=連系線純輸出入)")

BG = "#0D1120"
hrs = np.arange(T)
frames, durs = [], []
for tc in range(T):
    fig = plt.figure(figsize=(12.8, 7.2), dpi=110)
    fig.patch.set_facecolor(BG)
    for gi, (gname, regions) in enumerate(GROUPS.items()):
        ax = fig.add_axes([0.075, 0.525 - 0.445 * gi, 0.63, 0.335])
        ax.set_facecolor("#11152A")
        ys = [data[gname].get(f, np.zeros(T)) / 1e3 for f in fuels]
        ax.stackplot(hrs, *ys, colors=[COL[f] for f in fuels],
                     alpha=0.92, linewidth=0)
        ax.plot(hrs, demand[gname] / 1e3, color="#FFFFFF", lw=2.0)
        ax.axvline(tc, color="#FFD60A", lw=1.6)
        ax.set_xlim(0, 23)
        ax.set_ylim(0, demand[gname].max() / 1e3 * 1.22)
        ax.tick_params(colors="#8E96B8", labelsize=9)
        for sp in ax.spines.values():
            sp.set_color("#3A4266")
        ax.set_title(f"{gname} — 燃料別発電 [GW]・白線=純需要+揚水充電",
                     color="#C8CDD8", fontsize=11.5, loc="left")
        if gi == 1:
            ax.set_xlabel("時刻 [時]", color="#8E96B8", fontsize=10)
        # HUD: カーソル時刻の内訳(上位)
        vals = sorted(((f, data[gname].get(f, np.zeros(T))[tc] / 1e3)
                       for f in fuels), key=lambda kv: -kv[1])
        tot = sum(v for _f, v in vals)
        tx = f"{tc:02d}時  計 {tot:.1f} GW\n" + "\n".join(
            f"{JP[f]:　<4} {v:5.1f}" for f, v in vals[:6] if v > 0.05)
        ax.text(1.025, 0.97, tx, transform=ax.transAxes, va="top",
                color="#C8CDD8", fontsize=9.5, family="Hiragino Sans")
    # 凡例(右下)
    axl = fig.add_axes([0.865, 0.055, 0.125, 0.42]); axl.axis("off")
    for i, f in enumerate(reversed(fuels)):
        y = i / max(len(fuels), 1)
        axl.add_patch(plt.Rectangle((0.0, y), 0.10, 0.055, color=COL[f],
                                    transform=axl.transAxes))
        axl.text(0.14, y + 0.01, JP[f], transform=axl.transAxes,
                 color="#C8CDD8", fontsize=9.5)
    # タイトルはスライド側のテキストボックスへ(PowerPointで編集可能に
    # するため — オーナー指摘「GIFに焼き込むと編集できない」)
    fig.text(0.075, 0.962,
             "全て全国UC最適解(求解約10秒)の数値。スピルは燃料比例で控除(正典と同式)"
             " / 積み上げと白線の差=連系線・FC経由の純輸出入",
             color="#8E96B8", fontsize=9.5, va="top")
    fig.canvas.draw()
    frames.append(np.asarray(fig.canvas.buffer_rgba())[..., :3].copy())
    plt.close(fig)
    durs.append(400)
durs[-1] = 3200          # 最終フレームは長押し(重複フレームはPILが潰すため作らない)

from PIL import Image
ims = [Image.fromarray(f) for f in frames]
out = "docs/slides/ajg/assets/uc_dispatch_stack.gif"
ims[0].save(out, save_all=True, append_images=ims[1:], duration=durs, loop=0,
            optimize=True)
print(f"-> {out} ({len(ims)}フレーム, {os.path.getsize(out)/1e6:.1f}MB)")
