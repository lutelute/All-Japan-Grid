"""報告の図 2 枚: エリア間の潮流(前・後・試算 と OCCTO)/ 線ごとの潮流の変わり方の地図。

    python docs/reports/west_slack_surplus_2026-10-26/fig.py <前の powerflow_full のフォルダ>

後 = docs/data/powerflow_full(この版)、前 = 引数のフォルダ(`git show <前の版>:docs/data/powerflow_full/...` で取り出したもの)。
"""
import json
import logging
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BEFORE_DIR = Path(sys.argv[1])
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)   # 無い字体の候補を毎字警告しない
plt.rcParams["font.family"] = ["Hiragino Sans", "Noto Sans CJK JP", "DejaVu Sans"]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
C_AFTER, C_BEFORE, C_TRIAL = "#2a78d6", "#eb6834", "#1baf7a"   # 分類色の 1〜3 番(この順で固定)

S = json.loads((HERE / "stats.json").read_text(encoding="utf-8"))
R = json.loads((HERE / "occto_reference.json").read_text(encoding="utf-8"))
JA = {"chubu": "中部", "hokuriku": "北陸", "kansai": "関西", "chugoku": "中国", "shikoku": "四国",
      "kyushu": "九州", "tohoku": "東北", "tokyo": "東京"}
ROWS = [  # (島, モデルの組, 表示名, OCCTO の組)
    ("west", "500kv", "三重東近江線 500 kV\n(中部→関西)", "chubu->kansai"),
    ("west", "chubu->kansai", "中部→関西 の計", "chubu->kansai"),
    ("west", "chugoku->kansai", "中国→関西", "chugoku->kansai"),
    ("west", "chugoku->kyushu", "中国→九州", "chugoku->kyushu"),
    ("west", "chugoku->shikoku", "中国→四国", "chugoku->shikoku"),
    ("west", "kansai->shikoku", "関西→四国(直流)", "kansai->shikoku"),
    ("east", "tohoku->tokyo", "東北→東京", "tohoku->tokyo"),
]


def model_val(rec, pair):
    if pair == "500kv":
        return sum(rec["chubu_kansai_500kv"].values())
    return rec["zone_pairs"].get(pair, 0.0)


def fig_pairs():
    fig, ax = plt.subplots(figsize=(9.6, 5.6), dpi=150)
    ys = list(range(len(ROWS)))[::-1]
    for y, (isl, pair, label, opair) in zip(ys, ROWS):
        ref = R["islands"][isl]["pairs"][opair]
        ax.plot([ref["p10"], ref["p90"]], [y, y], color="#c3c2b7", lw=7, solid_capstyle="round", zorder=1)
        ax.plot([ref["median"]] * 2, [y - 0.28, y + 0.28], color=INK, lw=2, zorder=2)
        st = S["islands"][isl]
        ax.scatter(model_val(st["before"], pair), y, s=70, color=C_BEFORE, edgecolor="white", lw=1.5, zorder=4)
        ax.scatter(model_val(st["after"], pair), y, s=70, color=C_AFTER, edgecolor="white", lw=1.5, zorder=5)
        if st.get("trial_exchange", {}).get("ac"):          # 東の試算は AC で解けない(DC のみ)ので描かない
            ax.scatter(model_val(st["trial_exchange"], pair), y, s=60, marker="D", facecolor="white",
                       edgecolor=C_TRIAL, lw=2, zorder=3)
    ax.axvline(0, color=INK2, lw=0.8)
    ax.set_yticks(ys, [r[2] for r in ROWS], color=INK)
    ax.set_xlabel("潮流 MW(左のエリアから右のエリアへを正)", color=INK2)
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    h = [plt.Line2D([], [], color="#c3c2b7", lw=7, label="OCCTO 計画潮流 10〜90%(同じ需要水準のコマ)"),
         plt.Line2D([], [], color=INK, lw=2, label="OCCTO 中央値"),
         plt.Line2D([], [], ls="", marker="o", ms=8, color=C_BEFORE, label="前(〜10-26 の正典)"),
         plt.Line2D([], [], ls="", marker="o", ms=8, color=C_AFTER, label="後(介入#54)"),
         plt.Line2D([], [], ls="", marker="D", ms=7, mfc="white", mec=C_TRIAL, mew=2, label="試算: 取引を入れる(案3・未採用)")]
    ax.legend(handles=h, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, frameon=False, fontsize=8.5)
    ax.set_title("エリアをまたぐ潮流: モデルと OCCTO の連系線", loc="left", color=INK, fontsize=12, pad=46)
    fig.tight_layout()
    fig.savefig(HERE / "interzonal_flows.png", facecolor="white")
    plt.close(fig)


def lines(folder, regions):
    out = {}
    for r in regions:
        p = folder / f"{r}_ac_lines.geojson"
        for f in json.loads(p.read_text(encoding="utf-8"))["features"]:
            c = f["geometry"]["coordinates"]
            k = (f["properties"].get("name"), tuple(round(x, 5) for x in c[0]), tuple(round(x, 5) for x in c[-1]))
            out[k] = (c, float(f["properties"].get("p_mw") or 0.0))
    return out


BINS = [(0, 50, "#e4e3df", 0.5, "50 MW 未満"), (50, 200, "#9cc2ee", 1.0, "50〜200"),
        (200, 1000, "#2a78d6", 1.6, "200〜1,000"), (1000, 1e9, "#0b3d82", 2.4, "1,000 MW 以上")]


def fig_map():
    panels = [("west", ["chubu", "hokuriku", "kansai", "chugoku", "shikoku", "kyushu"], "西の島"),
              ("east", ["tohoku", "tokyo"], "東の島")]
    fig, axes = plt.subplots(1, 2, figsize=(12, 6.4), dpi=150, gridspec_kw={"width_ratios": [1.35, 1]})
    for ax, (isl, regions, title) in zip(axes, panels):
        a, b = lines(BEFORE_DIR, regions), lines(ROOT / "docs/data/powerflow_full", regions)
        common = a.keys() & b.keys()
        counts = []
        for lo, hi, col, lw, _lab in BINS:
            segs = [b[k][0] for k in common if lo <= abs(b[k][1] - a[k][1]) < hi]
            counts.append(len(segs))
            ax.add_collection(LineCollection(segs, colors=col, linewidths=lw, capstyle="round"))
        st = S["islands"][isl]["before"]
        x, y = st["main_slack_lonlat"]
        ax.scatter([x], [y], s=120, marker="*", color=C_BEFORE, edgecolor="white", lw=1.2, zorder=5)
        ax.annotate(f"前の主成分のスラック {st['main_slack']}\n({JA.get(st['main_slack_zone'], '')}・{st['main_slack_mw']:,.0f} MW)",
                    (x, y), xytext=(10, -30), textcoords="offset points", fontsize=8, color=INK,
                    bbox={"boxstyle": "round,pad=0.25", "fc": "white", "ec": "none", "alpha": 0.85})
        ax.autoscale()
        ax.set_aspect(1.2)
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        ax.text(0, 1.02, f"{title}: 線ごとの潮流の変わり方 |後 − 前|(比べた {len(common):,} 本)",
                transform=ax.transAxes, color=INK, fontsize=10.5, va="bottom")
        ax.legend(handles=[plt.Line2D([], [], color=c, lw=max(lw, 1.5), label=f"{lab}({n:,} 本)")
                           for (_lo, _hi, c, lw, lab), n in zip(BINS, counts)],
                  loc="upper left", frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(HERE / "line_change_map.png", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    fig_pairs()
    fig_map()
