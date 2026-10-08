#!/usr/bin/env python3
"""解析の流れを 1 本の動画にする(地震動 → 津波 → 損傷 → 直後の系統状態 → 復旧 → 確率化 → 原因分解)。

    PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/make_video.py <run_dir> <out.mp4> [--island west] [--seed 7]

1 サンプルの損傷と復旧を実際に計算して描き、最後にモンテカルロ平均(run_dir の結果)を重ねる。
"""
from __future__ import annotations
import argparse, os, sys, subprocess, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import numpy as np, pandas as pd, yaml
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from nankai.grid import GridCase
from nankai.montecarlo import Simulator
from nankai.hazard_field import jma_class
from nankai import maps

W, H, DPI = 1280, 720, 100
FPS = 12


class Deck:
    def __init__(self, tmp):
        self.tmp = tmp; self.i = 0; self.files = []

    def hold(self, fig, seconds):
        fp = os.path.join(self.tmp, f"f{self.i:05d}.png"); fig.savefig(fp, dpi=DPI); plt.close(fig); self.i += 1
        self.files += [fp] * max(1, int(round(seconds * FPS)))


def base(title, sub=None, extent=maps.EXTENT_WEST, curve=False):
    fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI); fig.patch.set_facecolor("#f4f3ef")
    if curve:
        ax = fig.add_axes([0.02, 0.05, 0.62, 0.84]); ax2 = fig.add_axes([0.70, 0.10, 0.27, 0.56])
    else:
        ax = fig.add_axes([0.02, 0.05, 0.96, 0.84]); ax2 = None
    for p in maps._prefs():
        ax.fill(p[:, 0], p[:, 1], color="#f3f1ea", ec="#9a9a9a", lw=0.5, zorder=0)
    ax.set_xlim(extent[0], extent[1]); ax.set_ylim(extent[2], extent[3])
    ax.set_aspect(1 / np.cos(np.radians((extent[2] + extent[3]) / 2))); ax.set_facecolor("#dbe9f4"); ax.set_xticks([]); ax.set_yticks([])
    fig.text(0.02, 0.945, title, fontsize=17, fontweight="bold", va="center")
    if sub:
        fig.text(0.02, 0.905, sub, fontsize=11.5, color="#444", va="center")
    return fig, ax, ax2


def card(lines, big=None, color="#1b1f26", bg="#f4f3ef"):
    fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI); fig.patch.set_facecolor(bg)
    y = 0.62 if big else 0.55
    if big:
        fig.text(0.5, 0.60, big, ha="center", va="center", fontsize=34, fontweight="bold", color=color)
        y = 0.40
    for k, ln in enumerate(lines):
        fig.text(0.5, y - k * 0.075, ln, ha="center", va="center", fontsize=15, color=color)
    return fig


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("run"); ap.add_argument("out"); ap.add_argument("--island", default="west"); ap.add_argument("--seed", type=int, default=7); a = ap.parse_args()
    case = GridCase.load(a.island); sim = Simulator(case)
    bus = pd.read_parquet(os.path.join(a.run, a.island, "bus_results.parquet")); summ = pd.read_csv(os.path.join(a.run, a.island, "timeline_summary.csv"))
    ext = maps.EXTENT_WEST
    rng = np.random.default_rng(a.seed); d = sim.damage(rng); d.blackout_until = sim._blackout(d, rng)
    out, phys, info = sim.evaluate_timeline(d)
    lat, lon = sim.lat, sim.lon; load = sim.cm.load; s = 3 + 30 * np.sqrt(np.clip(load, 0, 500) / 500)
    tmp = tempfile.mkdtemp(); deck = Deck(tmp)
    # 0 title
    deck.hold(card(["All-Japan-Grid の系統モデルの上で、地震動 → 損傷 → 系統 → 復旧 を計算する", "西日本 60Hz 系統 7,985 母線 ・ J-SHIS Mw9.1 ・ A40 津波 ・ モンテカルロ N=200"], big="南海トラフ地震 電力ハザードマップ v0"), 3.0)
    # 1 hazard
    fig, ax, _ = base("① 地震動: J-SHIS 南海トラフ最大クラス(Mw9.1)の 250m 計測震度を母線に引く", "空間相関ノイズを乗せた 1 サンプル。色は気象庁震度階級", ext)
    cmap = ListedColormap([maps.JMA_COLORS[k] for k in maps.JMA_ORDER]); norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5, 4.5, 5.0, 5.5, 6.0, 6.5, 7.5], cmap.N)
    o = np.argsort(d.intensity); ax.scatter(lon[o], lat[o], c=d.intensity[o], cmap=cmap, norm=norm, s=6, lw=0, zorder=4)
    deck.hold(fig, 3.0)
    # 2 tsunami
    fig, ax, _ = base("② 津波: 国土数値情報 A40 の最大クラス浸水想定に入る母線", f"浸水域内の母線 {int((sim.bus_ts>0).sum())} 点(青)。浸水深ランクで変電所・発電所の停止確率が決まる", ext)
    ax.scatter(lon, lat, c="#d9d5c8", s=4, lw=0, zorder=3)
    m = sim.bus_ts > 0; ax.scatter(lon[m], lat[m], c=sim.bus_ts[m], cmap="Blues", vmin=0, vmax=7, s=28, ec="#123", lw=0.4, zorder=5)
    deck.hold(fig, 2.5)
    # 3 damage
    fig, ax, _ = base("③ 損傷のサンプル: 変電所(揺れ=橙・津波=青)、停止した発電所(黒・大きさ=出力)、落ちた線路(赤)", "脆弱性曲線(HAZUS×日本補正)と内閣府方式の火力停止率で 1 回サンプル", ext)
    ax.scatter(lon, lat, c="#d9d5c8", s=3, lw=0, zorder=2)
    sc = d.site_cause[sim.bus_site]; ff = int(sim.fm.p["substation"]["functional_failure_ds"]); sd = d.site_ds[sim.bus_site]
    fs = (sd >= ff) & (sc == 1); ft = (sd >= ff) & (sc == 2)
    ax.scatter(lon[fs], lat[fs], c="#f39c12", s=26, marker="x", lw=1.2, zorder=6, label=f"変電所 揺れ停止 {int(fs.sum())}")
    ax.scatter(lon[ft], lat[ft], c="#1f77b4", s=26, marker="x", lw=1.2, zorder=6, label=f"変電所 津波停止 {int(ft.sum())}")
    br = case.branch; lf = d.line_fail
    for k in np.where(lf)[0]:
        ax.plot([lon[sim.bf[k]], lon[sim.bt[k]]], [lat[sim.bf[k]], lat[sim.bt[k]]], color="#d62728", lw=1.6, zorder=5)
    ax.plot([], [], color="#d62728", lw=1.6, label=f"線路停止 {int(lf.sum())}")
    g = case.gen; gstop = (d.done_gen > 0) & ~sim.gslack & (g.p_mw.to_numpy() > 50)
    ax.scatter(lon[sim.gb[gstop]], lat[sim.gb[gstop]], s=10 + g.p_mw.to_numpy()[gstop] / 15, c="#111", alpha=0.65, zorder=7, label=f"発電所 停止(>50MW) {int(gstop.sum())} 基 {g.p_mw.to_numpy()[gstop].sum()/1000:.1f} GW")
    ax.legend(loc="lower right", fontsize=9); deck.hold(fig, 3.5)
    # 4 t=0 state
    T = sim.timeline; bo = d.blackout_until
    def state_fig(ti, label):
        t = T[ti]
        fig, ax, ax2 = base(f"④ 系統評価: {label}", "色 = 供給率(緑=供給、赤=停電)。エリアの供給不足が 25% を超えると系統崩壊(全停)、以後は需給・DC潮流・過負荷連鎖を解く", ext, curve=True)
        v = out[ti]; o = np.argsort(-v)
        ax.scatter(lon[o], lat[o], c=v[o], cmap="RdYlGn", vmin=0, vmax=1, s=s[o], lw=0, alpha=0.9, zorder=4)
        x = np.array([r["t_days"] for r in info]); y = np.array([r["served_mw"] for r in info]) / load.sum() * 100; yp = np.array([r["phys_mw"] for r in info]) / load.sum() * 100
        ax2.plot(x, yp, color="#c2361f", lw=2, label="受電可能(物理)"); ax2.plot(x, y, color="#1c5d8c", lw=2, label="供給率")
        ax2.axvline(t, color="#333", ls="--", lw=1); ax2.set_xscale("symlog", linthresh=1); ax2.set_xlim(0, 90); ax2.set_ylim(0, 100); ax2.grid(alpha=0.3)
        ax2.set_xlabel("経過日数"); ax2.set_ylabel("[%]"); ax2.legend(fontsize=8, loc="lower right"); ax2.set_title("このサンプルの復旧曲線", fontsize=10)
        fig.text(0.70, 0.86, f"t = {label}", fontsize=15, fontweight="bold", va="top")
        fig.text(0.70, 0.815, f"供給率 {y[ti]:.0f}%  受電可能 {yp[ti]:.0f}%\n停止中: 変電所 {info[ti]['sites_out']} ・ 線路 {info[ti]['lines_out']} ・ 発電機 {info[ti]['gens_out']}\n系統崩壊中の需要 {info[ti]['blackout_mw']/1000:.1f} GW", fontsize=10.5, va="top", linespacing=1.5)
        return fig
    labels = ["直後", "6時間", "12時間", "1日", "2日", "3日", "4日", "5日", "7日", "10日", "14日", "21日", "30日", "45日", "60日", "90日"]
    deck.hold(state_fig(0, "直後"), 3.0)
    for ti in range(1, len(T)):
        deck.hold(state_fig(ti, labels[ti]), 0.8 if ti < 9 else 0.6)
    deck.hold(state_fig(len(T) - 1, "90日"), 1.5)
    # 5 MC mean
    fig, ax, _ = base("⑤ 確率化: 200 サンプルの平均 — 7 日後に停電している確率(物理)", "サンプルごとに違う損傷の組合せを重ねると、沿岸の津波浸水域と上流孤立が残る", ext)
    v = bus.pout_phys_t7.values; o = np.argsort(v); ax.scatter(bus.lon.values[o], bus.lat.values[o], c=v[o], cmap="magma_r", vmin=0, vmax=1, s=s[o] if len(s) == len(bus) else 6, lw=0, alpha=0.9, zorder=4)
    deck.hold(fig, 3.0)
    fig, ax, _ = base("⑤ 確率化: 期待停電日数(0〜90 日の積分・物理停電)", "どこが「長く」止まるか。津波浸水域の変電所(復旧中央値 60 日)が支配する", ext)
    v = bus.expected_outage_days_phys.values; o = np.argsort(v); ax.scatter(bus.lon.values[o], bus.lat.values[o], c=v[o], cmap="viridis_r", vmin=0, vmax=float(np.quantile(v, 0.98)), s=s[o] if len(s) == len(bus) else 6, lw=0, alpha=0.9, zorder=4)
    deck.hold(fig, 3.0)
    # 6 figures
    for png, sec in ((os.path.join(a.run, "cause_decomposition.png"), 3.5), (os.path.join(a.run, "naikakufu_compare.png"), 4.0), (os.path.join(a.run, a.island, "potential.png"), 2.5)):
        if os.path.exists(png):
            img = plt.imread(png); fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI); fig.patch.set_facecolor("#f4f3ef")
            ax = fig.add_axes([0.03, 0.03, 0.94, 0.90]); ax.imshow(img); ax.axis("off")
            ttl = {"cause_decomposition.png": "⑥ 原因分解: 系統崩壊は 2 日で消え、津波変電所と上流孤立が残る", "naikakufu_compare.png": "⑦ 内閣府想定との比較: 直後〜1日は同じ桁、4日後以降は 1 桁多い(=負の結果として記録)", "potential.png": "⑧ ポテンシャル法: 潮流を解かずに 0.8 秒で出す指標(需要加重相関 0.55)"}[os.path.basename(png)]
            fig.text(0.02, 0.965, ttl, fontsize=16, fontweight="bold", va="center"); deck.hold(fig, sec)
    deck.hold(card(["配電(6.6kV 以下)は未考慮 ・ 津波変電所の停止確率と復旧日数は仮定 ・ 需要家数は概数", "内閣府の数字は結果に入れていない(較正目標と比較対象のみ)", "コード: All-Japan-Grid feature/nankai-hazard / hazard/nankai/"], big="言えること・言えないこと"), 4.0)
    # encode
    lst = os.path.join(tmp, "list.txt")
    with open(lst, "w") as f:
        for fp in deck.files:
            f.write(f"file '{fp}'\nduration {1/FPS:.5f}\n")
        f.write(f"file '{deck.files[-1]}'\n")
    try:
        import imageio_ffmpeg; ff = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ff = "ffmpeg"
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-vf", f"scale={W}:{H},format=yuv420p", "-r", str(FPS), "-c:v", "libx264", "-crf", "23", "-movflags", "+faststart", a.out], check=True)
    print("frames", len(deck.files), "sec", len(deck.files) / FPS, "->", a.out, round(os.path.getsize(a.out) / 1e6, 1), "MB")


if __name__ == "__main__":
    main()
