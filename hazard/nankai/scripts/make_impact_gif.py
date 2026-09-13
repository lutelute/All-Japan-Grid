#!/usr/bin/env python3
"""プレゼン用インパクト GIF: west+east を 1 枚の地図に載せ、時間とともに停電確率(物理)が変わる。
右に 五地域の停電軒数(本解析 vs 内閣府 2025 基本) と復旧曲線。

    PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/make_impact_gif.py <run_dir> <out.gif> [--fps 0.8]
"""
from __future__ import annotations
import argparse, os, sys, tempfile, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import numpy as np, pandas as pd, yaml
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
import imageio.v2 as imageio
from nankai.grid import GridCase
from nankai.aggregate import bus_prefecture, naikakufu_region_of, customers_per_mw
from nankai import maps

NANKAI = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
W, H, DPI = 1280, 720, 100
EXT = (129.3, 141.2, 30.9, 37.4)
LABELS = {0: "発災直後", 0.25: "6 時間後", 0.5: "12 時間後", 1: "1 日後", 2: "2 日後", 3: "3 日後", 4: "4 日後", 5: "5 日後", 7: "1 週間後", 10: "10 日後", 14: "2 週間後", 21: "3 週間後", 30: "1 か月後", 45: "45 日後", 60: "2 か月後", 90: "3 か月後"}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("run"); ap.add_argument("out"); ap.add_argument("--fps", type=float, default=0.8); a = ap.parse_args()
    rp = yaml.safe_load(open(os.path.join(NANKAI, "config", "restoration_default.yaml"))); T = [float(t) for t in rp["timeline_days"]]
    tg = yaml.safe_load(open(os.path.join(NANKAI, "config", "calibration_targets.yaml")))["naikakufu_2025"]["outage_households"]["①東海_基本"]
    nk = {t: sum(tg[r][i] for r in ("tokai", "kinki", "sanyo", "shikoku", "kyushu")) for i, t in enumerate((0, 1, 4, 7))}
    buses = []; five_out = {t: 0.0 for t in T}; load_tot = 0; served = {t: 0.0 for t in T}; phys = {t: 0.0 for t in T}
    for isl in ("west", "east"):
        b = pd.read_parquet(os.path.join(a.run, isl, "bus_results.parquet")); case = GridCase.load(isl)
        reg = naikakufu_region_of(bus_prefecture(case)); cpm = customers_per_mw(b.groupby("zone").pd_mw.sum().to_dict())
        cust = b.pd_mw.to_numpy() * b.zone.map(cpm).fillna(0).to_numpy(); five = np.isin(reg, ["tokai", "kinki", "sanyo", "shikoku", "kyushu"])
        for t in T:
            five_out[t] += float(((1 - b[f"phys_t{t:g}"].to_numpy()[five]) * cust[five]).sum())
            served[t] += float((b[f"served_t{t:g}"] * b.pd_mw).sum()); phys[t] += float((b[f"phys_t{t:g}"] * b.pd_mw).sum())
        load_tot += float(b.pd_mw.sum()); buses.append(b)
    bus = pd.concat(buses, ignore_index=True)
    s = 3 + 28 * np.sqrt(np.clip(bus.pd_mw.values, 0, 500) / 500)
    tmp = tempfile.mkdtemp(); frames = []; durs = []
    def frame(ti, t, title, first=False):
        fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI); fig.patch.set_facecolor("#f4f3ef")
        ax = fig.add_axes([0.0, 0.0, 0.66, 1.0])
        for p in maps._prefs():
            ax.fill(p[:, 0], p[:, 1], color="#f3f1ea", ec="#9a9a9a", lw=0.5, zorder=0)
        ax.set_xlim(EXT[0], EXT[1]); ax.set_ylim(EXT[2], EXT[3]); ax.set_aspect(1 / np.cos(np.radians((EXT[2] + EXT[3]) / 2))); ax.set_facecolor("#dbe9f4"); ax.set_xticks([]); ax.set_yticks([])
        if first:
            v = bus.intensity_mean.values; o = np.argsort(v)
            from matplotlib.colors import ListedColormap, BoundaryNorm
            cmap = ListedColormap([maps.JMA_COLORS[k] for k in maps.JMA_ORDER]); norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5, 4.5, 5.0, 5.5, 6.0, 6.5, 7.5], cmap.N)
            ax.scatter(bus.lon.values[o], bus.lat.values[o], c=v[o], cmap=cmap, norm=norm, s=6, lw=0, zorder=4)
        else:
            v = bus[f"pout_phys_t{t:g}"].values; o = np.argsort(v)
            ax.scatter(bus.lon.values[o], bus.lat.values[o], c=v[o], cmap="magma_r", vmin=0, vmax=1, s=s[o], lw=0, alpha=0.9, zorder=4)
        ax.text(0.02, 0.97, title, transform=ax.transAxes, fontsize=26, fontweight="bold", va="top", ha="left", color="#1b1f26")
        ax.text(0.02, 0.905, "母線 14,238 点の停電確率（設備損傷・系統崩壊・上流孤立）" if not first else "J-SHIS 南海トラフ最大クラス Mw9.1 の想定震度（母線）", transform=ax.transAxes, fontsize=11, va="top", color="#444")
        # 右パネル
        ax2 = fig.add_axes([0.70, 0.56, 0.28, 0.36])
        x = np.array(T); y = np.array([phys[tt] for tt in T]) / load_tot * 100; y2 = np.array([served[tt] for tt in T]) / load_tot * 100
        ax2.plot(x, y, color="#c2361f", lw=2.5, label="受電可能"); ax2.plot(x, y2, color="#1c5d8c", lw=1.5, ls="--", label="供給率(不足込み)")
        if not first:
            ax2.axvline(t, color="#333", lw=1.2, ls=":"); ax2.plot([t], [phys[t] / load_tot * 100], "o", color="#c2361f", ms=8)
        ax2.set_xscale("symlog", linthresh=1); ax2.set_xlim(0, 90); ax2.set_ylim(0, 100); ax2.set_xticks([0, 1, 7, 30, 90]); ax2.set_xticklabels(["直後", "1日", "1週", "1月", "3月"]); ax2.grid(alpha=0.3); ax2.legend(fontsize=8, loc="lower right"); ax2.set_ylabel("[%]"); ax2.set_title("全国(west+east)の復旧曲線", fontsize=10)
        ax3 = fig.add_axes([0.70, 0.08, 0.28, 0.40]); ax3.axis("off")
        if first:
            ax3.text(0, 0.95, "載せたもの", fontsize=13, fontweight="bold", va="top")
            ax3.text(0, 0.82, "・地震動: J-SHIS 250 m 震度\n・津波: 国土数値情報 A40 浸水想定\n・脆弱性: HAZUS×日本補正、内閣府の火力停止率\n・復旧: 修理時間分布・作業班・優先順\n・系統: All-Japan-Grid 正典 14,238 母線", fontsize=10.5, va="top", linespacing=1.6)
        else:
            ax3.text(0, 0.95, "五地域の停電軒数（物理）", fontsize=13, fontweight="bold", va="top")
            ax3.text(0, 0.80, f"{five_out[t]/1e4:,.0f} 万軒", fontsize=34, fontweight="bold", color="#c2361f", va="top")
            if t in nk:
                ax3.text(0, 0.50, f"内閣府 2025 想定: {nk[t]/1e4:,.0f} 万軒", fontsize=12, va="top", color="#444")
            ax3.text(0, 0.36, f"受電可能 {phys[t]/load_tot:.0%}   供給率 {served[t]/load_tot:.0%}", fontsize=11, va="top")
            ax3.text(0, 0.20, {0: "中部エリアが需給崩壊。沿岸は津波", 1: "崩壊は復電、津波と上流孤立が残る", 4: "内閣府は 36 万。差は津波変電所と上流孤立", 7: "残るのは大阪湾岸・伊勢湾岸・高知・徳島", 30: "津波変電所の復旧が律速(中央値 60 日)", 90: "ほぼ復旧。原単位は仮定、配電は未考慮"}.get(t, ""), fontsize=10, va="top", color="#666", wrap=True)
        fig.text(0.70, 0.02, "All-Japan-Grid hazard/nankai v0 ・ N=200 ・ 2026-09", fontsize=8, color="#888")
        fp = os.path.join(tmp, f"f{ti:02d}.png"); fig.savefig(fp, dpi=DPI); plt.close(fig); return fp
    frames.append(imageio.imread(frame(0, 0, "南海トラフ地震が起きたら", first=True))); durs.append(2.5)
    for i, t in enumerate(T):
        frames.append(imageio.imread(frame(i + 1, t, LABELS.get(t, f"{t:g} 日後")))); durs.append(2.2 if t in (0, 1, 4, 7, 30, 90) else 1.0 / a.fps)
    durs[-1] = 3.5
    imageio.mimsave(a.out, frames, duration=[d * 1000 for d in durs], loop=0)
    mp4 = os.path.splitext(a.out)[0] + ".mp4"
    lst = os.path.join(tmp, "l.txt")
    with open(lst, "w") as f:
        for i, d in enumerate(durs):
            f.write(f"file '{os.path.join(tmp, f'f{i:02d}.png')}'\nduration {d}\n")
        f.write(f"file '{os.path.join(tmp, f'f{len(durs)-1:02d}.png')}'\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-vf", f"scale={W}:{H},format=yuv420p", "-r", "10", "-c:v", "libx264", "-crf", "22", "-movflags", "+faststart", mp4], check=True)
    print("gif", round(os.path.getsize(a.out) / 1e6, 1), "MB", len(frames), "frames", round(sum(durs), 1), "s; mp4", round(os.path.getsize(mp4) / 1e6, 1), "MB")


if __name__ == "__main__":
    main()
