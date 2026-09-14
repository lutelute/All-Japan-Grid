#!/usr/bin/env python3
"""動的カスケード 1 サンプルの可視化(MP4 + GIF + 静止画): 揺れの到達 → 発電機停止 → 周波数 → リレー → 系統分離 → 停電。

    PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/make_dynamic_cascade_viz.py --run hazard/nankai/output/run_v2_dyn --island west \
        --out docs/reports/nankai_hazard_2026-09-13/dynamics/cascade_west

代表サンプルは dyn_samples.csv から「180 秒後の受電 MW が中央値に最も近いサンプル」を選び、同じ乱数で再計算して時系列を記録する。
左: 母線の地図(受電中は島ごとに色、赤 = 周波数崩壊、灰 = 電源から切り離された孤立、橙の × = 設備損傷)と S 波の波面
右上: エリアごとの周波数(エリアの負荷が最も多く属する島の周波数)と UFLS の段
右中: 受電を続ける独立系統(島)の数(平常時の幹線から分かれたもの、負荷 10 MW 以上 / 100 MW 以上)
右下: 需要 MW の内訳(受電 / UFLS 遮断 / 周波数崩壊 / 孤立 / 設備損傷)
"""
from __future__ import annotations
import argparse, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import numpy as np, pandas as pd, yaml, json
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

NANKAI = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.abspath(os.path.join(NANKAI, "..", ".."))
plt.rcParams["font.family"] = ["Hiragino Sans"]
BG = "#070b14"; PANEL = "#0d1422"; GRID = "#1f2a3d"; TXT = "#e8e4d8"; MUTED = "#8e98ab"
ZC = {"chubu": "#ffb347", "kansai": "#ff6b6b", "hokuriku": "#6fd3ff", "chugoku": "#9be37a", "shikoku": "#c79bff", "kyushu": "#ffd86b", "tokyo": "#ffb347", "tohoku": "#6fd3ff"}
ZJ = {"chubu": "中部", "kansai": "関西", "hokuriku": "北陸", "chugoku": "中国", "shikoku": "四国", "kyushu": "九州", "tokyo": "東京", "tohoku": "東北"}
ISL = ["#f4efe2", "#5ad1ff", "#9be37a", "#c79bff", "#ffd86b", "#ff9ecb", "#7ff0d2", "#b0b8ff"]


def main():
    a = argparse.ArgumentParser(); a.add_argument("--run", required=True); a.add_argument("--island", default="west"); a.add_argument("--out", required=True)
    a.add_argument("--sample", type=int, default=None); a.add_argument("--seed", type=int, default=0); args = a.parse_args()
    import arrival_physics as ap
    from nankai.grid import GridCase
    from nankai.montecarlo import Simulator
    from nankai.dyn_cascade import DynCascade
    od = os.path.join(args.run, args.island)
    ds = pd.read_csv(os.path.join(od, "dyn_samples.csv"))
    if args.sample is None:
        x = ds[ds.t_s == 180.0].set_index("sample").energized_mw
        s = int((x - x.median()).abs().idxmin())
    else:
        s = args.sample
    import run_dynamic as RD                                   # モンテカルロと同じ初期化(台帳による容量の置き換え・感度の上書きを含む)
    meta = json.load(open(os.path.join(od, "meta.json")))
    RD.init(args.island, args.seed, meta.get("overrides") or {})
    sim, cfg, dc = RD.G["sim"], RD.G["cfg"], RD.G["dc"]; case = sim.case
    ts = dc.t_s
    rng = np.random.default_rng([args.seed, s]); d = sim.damage(rng)
    r = dc.run(d, rng, trace=True)
    tr = r["trace"]; T = np.array(tr["t"])
    zone = case.bus.zone.to_numpy(); zones = [z for z in ZC if z in set(zone)]
    lat, lon = case.bus.lat.to_numpy(), case.bus.lon.to_numpy(); load = sim.cm.load
    f0 = dc.f0
    L = float(load.sum())
    # ログから主な事象(文字で出す)
    log = [(float(e[0]), e[1], float(e[2])) for e in r["log"]]
    # フレームの時刻: 0〜300 秒は 1 秒ごと、その後 3 時間まで 5 分ごと
    frames = list(np.arange(0, 301, 1.0)) + list(np.arange(600, 10801, 300.0))
    tmp = tempfile.mkdtemp()
    lon0, lon1, lat0, lat1 = lon.min() - 0.3, lon.max() + 0.3, lat.min() - 0.3, lat.max() + 0.3
    kx = np.cos(np.radians(35))
    size = np.clip(np.sqrt(load) * 1.6, 1.5, 40)
    gj = json.load(open(os.path.join(ROOT, "data", "reference", "japan_prefectures_simplified.geojson"), encoding="utf-8"))
    polys = []
    for f in gj["features"]:
        geo = f["geometry"]; rings = geo["coordinates"][:1] if geo["type"] == "Polygon" else [p[0] for p in geo["coordinates"]]
        for rr in rings:
            rr = np.array(rr)
            if rr[:, 0].max() > lon0 - 1 and rr[:, 0].min() < lon1 + 1 and rr[:, 1].max() > lat0 - 1 and rr[:, 1].min() < lat1 + 1:
                polys.append(rr)
    ufls = [st["ratio"] * f0 for st in cfg["ufls"]["stages"]]
    Tn = T; zf = pd.DataFrame(tr["zone_f"]); mw = pd.DataFrame(tr["mw"]); nis = np.array(tr["n_islands"]); n100 = np.array(tr["n_100mw"])
    xt = lambda t: np.where(np.asarray(t) <= 300, np.asarray(t), 300 + (np.log10(np.maximum(np.asarray(t), 300)) - np.log10(300)) / (np.log10(10800) - np.log10(300)) * 120)
    events_txt = []
    for i, tf in enumerate(frames):
        k = int(np.searchsorted(Tn, tf, side="right") - 1); k = max(k, 0)
        fig = plt.figure(figsize=(19.2, 10.8), dpi=100, facecolor=BG)
        axm = fig.add_axes([0.01, 0.05, 0.50, 0.90]); axm.set_facecolor(BG); axm.axis("off")
        for p in polys:
            axm.fill(p[:, 0] * kx, p[:, 1], color="#111a2b", ec="#1e2a40", lw=0.5, zorder=0)
        e = tr["energized"][k].astype(float); lab = tr["island"][k]; col = tr["collapsed"][k]; iso = tr["isolated"][k]; so = tr["site_out"][k]
        # 受電中の島に色(負荷の大きい順)
        live = e > 0
        Li = pd.Series(load[live]).groupby(lab[live]).sum().sort_values(ascending=False)
        rank = {int(isl): j for j, isl in enumerate(Li.index)}
        c_live = np.array([ISL[min(rank.get(int(x), 7), 7)] for x in lab[live]]) if live.any() else np.array([])
        axm.scatter(lon[iso] * kx, lat[iso], s=size[iso] * 0.6, c="#3a4458", lw=0, zorder=1)
        axm.scatter(lon[col] * kx, lat[col], s=size[col], c="#ff3b2f", alpha=0.85, lw=0, zorder=2)
        if live.any():
            axm.scatter(lon[live] * kx, lat[live], s=size[live] * (0.35 + 0.65 * e[live]), c=c_live, alpha=0.9, lw=0, zorder=3)
        axm.scatter(lon[so] * kx, lat[so], s=26, marker="x", c="#ff9f40", lw=1.2, zorder=4)
        if tf <= 400:
            front = np.abs(ts - tf) < 2.5
            axm.scatter(lon[front] * kx, lat[front], s=18, c="#ffd9a0", alpha=0.35, lw=0, zorder=5)
        axm.set_xlim(lon0 * kx, lon1 * kx); axm.set_ylim(lat0, lat1); axm.set_aspect("equal")
        clock = f"{int(tf//3600)}:{int(tf%3600//60):02d}:{int(tf%60):02d}"
        fig.text(0.02, 0.93, clock, fontsize=46, color="#ffd696", family="Menlo")
        fig.text(0.02, 0.885, "揺れの到達 → 発電機停止 → 周波数 → リレー → 系統分離", fontsize=19, color=TXT)
        leg = [Line2D([], [], ls="", marker="o", color=ISL[0], label="受電中(最大の島)"), Line2D([], [], ls="", marker="o", color=ISL[1], label="受電中(分かれた島)"),
               Line2D([], [], ls="", marker="o", color="#ff3b2f", label="周波数崩壊"), Line2D([], [], ls="", marker="o", color="#3a4458", label="電源から孤立"),
               Line2D([], [], ls="", marker="x", color="#ff9f40", label="設備損傷"), Line2D([], [], ls="", marker="o", color="#ffd9a0", alpha=0.5, label="S 波の波面")]
        axm.legend(handles=leg, loc=("center left" if args.island == "east" else "lower left"), fontsize=12, frameon=False, labelcolor=TXT)
        # 右上: 周波数
        ax1 = fig.add_axes([0.56, 0.63, 0.42, 0.30], facecolor=PANEL)
        m = Tn <= tf
        for z in zones:
            if z in zf:
                ax1.plot(xt(Tn[m]), zf[z].values[m], color=ZC[z], lw=2, label=ZJ[z])
        for u in ufls:
            ax1.axhline(u, color="#ff6b6b", lw=0.8, ls="--"); ax1.text(2, u + 0.03, f"UFLS {u:.1f} Hz", color="#ff9b9b", fontsize=10)
        ax1.set_ylim(f0 * 0.945, f0 * 1.02); ax1.set_xlim(0, 420)
        ax1.set_xticks([0, 60, 120, 180, 240, 300, xt(1800), xt(10800)]); ax1.set_xticklabels(["0", "1分", "2分", "3分", "4分", "5分", "30分", "3時間"], color=MUTED)
        ax1.tick_params(colors=MUTED); [sp.set_color(GRID) for sp in ax1.spines.values()]; ax1.grid(color=GRID, lw=0.6)
        ax1.set_title("エリアの周波数 [Hz](そのエリアの負荷が最も多く属する島)", color=TXT, fontsize=14, loc="left")
        ax1.legend(loc="lower left", ncol=6, fontsize=10, frameon=False, labelcolor=TXT)
        # 右中: 島の数
        ax2 = fig.add_axes([0.56, 0.37, 0.42, 0.18], facecolor=PANEL)
        ax2.step(xt(Tn[m]), nis[m], where="post", color="#5ad1ff", lw=2.2, label="負荷 10 MW 以上")
        ax2.step(xt(Tn[m]), n100[m], where="post", color="#f4efe2", lw=1.6, label="100 MW 以上")
        ax2.set_xlim(0, 420); ax2.set_ylim(0, max(4, int(nis.max()) + 1)); ax2.set_xticks([0, 60, 120, 180, 240, 300, xt(1800), xt(10800)]); ax2.set_xticklabels(["0", "1分", "2分", "3分", "4分", "5分", "30分", "3時間"], color=MUTED)
        ax2.tick_params(colors=MUTED); [sp.set_color(GRID) for sp in ax2.spines.values()]; ax2.grid(color=GRID, lw=0.6)
        ax2.set_title(f"受電を続ける独立系統の数  いま {int(nis[k])} 個(100 MW 以上 {int(n100[k])} 個)", color=TXT, fontsize=14, loc="left")
        ax2.legend(loc="upper left", fontsize=10, frameon=False, labelcolor=TXT)
        # 右下: MW 内訳
        ax3 = fig.add_axes([0.56, 0.08, 0.42, 0.21], facecolor=PANEL)
        cols = [("site_out", "#ff9f40", "設備損傷"), ("isolated", "#7d8aa3", "電源から孤立"), ("collapsed", "#ff3b2f", "周波数崩壊"), ("shed", "#ffd86b", "UFLS 遮断")]
        ys = [mw[c].values[m] / L * 100 for c, _, _ in cols]
        if m.sum() > 1:
            ax3.stackplot(xt(Tn[m]), *ys, colors=[c for _, c, _ in cols], labels=[l for _, _, l in cols], alpha=0.95)
        ymax = float(sum(mw[c].values for c, _, _ in cols).max() / L * 100) * 1.25 + 1
        ax3.set_xlim(0, 420); ax3.set_ylim(0, ymax); ax3.set_xticks([0, 60, 120, 180, 240, 300, xt(1800), xt(10800)]); ax3.set_xticklabels(["0", "1分", "2分", "3分", "4分", "5分", "30分", "3時間"], color=MUTED)
        ax3.tick_params(colors=MUTED); [sp.set_color(GRID) for sp in ax3.spines.values()]
        cur = mw.iloc[k]
        ax3.set_title(f"停電の原因 [需要の %]  停電 {1-cur.energized/L:.0%}(UFLS {cur.shed/1e3:.1f}・崩壊 {cur.collapsed/1e3:.1f}・孤立 {cur.isolated/1e3:.1f}・損傷 {cur.site_out/1e3:.1f} GW)", color=TXT, fontsize=13, loc="left")
        ax3.legend(loc="upper left", ncol=4, fontsize=10, frameon=False, labelcolor=TXT)
        # 事象(直近)
        recent = [e_ for e_ in log if e_[0] <= tf and e_[1] in ("COLLAPSE", "overload_trip", "UFLS") and (e_[1] == "overload_trip" or e_[2] >= 50)]
        lines = []
        for t_, kind, v in recent[-4:]:
            if kind == "COLLAPSE":
                lines.append(f"{t_:6.1f} 秒  島(負荷 {v:,.0f} MW)が周波数崩壊")
            elif kind == "overload_trip":
                lines.append(f"{t_:6.1f} 秒  過負荷リレーが動作(過負荷 {int(v)} 本、上位から切る)")
            else:
                lines.append(f"{t_:6.1f} 秒  UFLS が負荷 {v:,.0f} MW を遮断")
        for j, ln in enumerate(lines):
            fig.text(0.02, 0.835 - j * 0.03, ln, fontsize=14, color="#ffcf9e")
        fig.text(0.56, 0.02, f"All-Japan-Grid {'西 60 Hz' if f0 == 60 else '東 50 Hz'}・代表サンプル #{s}(3 分後の受電が中央値に最も近い)・同じ島のエリアは周波数の線が重なる",
                 fontsize=10, color=MUTED)
        fig.savefig(os.path.join(tmp, f"f{i:04d}.png"), facecolor=BG); plt.close(fig)
        if tf == 180:
            import shutil; shutil.copy(os.path.join(tmp, f"f{i:04d}.png"), args.out + "_still.png")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "15", "-i", os.path.join(tmp, "f%04d.png"), "-vf", "format=yuv420p", "-c:v", "libx264", "-crf", "22", "-movflags", "+faststart", args.out + ".mp4"], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", args.out + ".mp4", "-vf", "fps=6,scale=960:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128:stats_mode=diff[p];[s1][p]paletteuse=dither=none:diff_mode=rectangle", "-loop", "0", args.out + ".gif"], check=True)
    json.dump({"island": args.island, "sample": s, "n_frames": len(frames), "log_counts": pd.Series([e_[1] for e_ in log]).value_counts().to_dict()}, open(args.out + "_meta.json", "w"), ensure_ascii=False, indent=1)
    print("sample", s, "frames", len(frames), "mp4 MB", round(os.path.getsize(args.out + ".mp4") / 1e6, 1), "gif MB", round(os.path.getsize(args.out + ".gif") / 1e6, 1))


if __name__ == "__main__":
    main()
