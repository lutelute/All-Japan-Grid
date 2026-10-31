"""lit.json から SSO の系譜の図(年表 × 筋、引用の辺)を描く。python fig.py → lineage.png"""
import json, math
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch

HERE = Path(__file__).resolve().parent
plt.rcParams["font.family"] = ["Hiragino Sans", "Noto Sans CJK JP", "sans-serif"]
LANES = [("A", "直列補償と軸ねじれ(SSR)"), ("B", "直流・パワエレと軸ねじれ(SSTI)"), ("C", "風力と直列補償(SSCI)"),
         ("D", "インバータとインピーダンス法(弱い系統)"), ("E", "super 側・高調波・ケーブルの共振"),
         ("F", "分類・用語・指針"), ("J", "日本(電気学会ほか)")]
COL = {"A": "#1f4e8c", "B": "#7a3b8f", "C": "#2a7f62", "D": "#c06014", "E": "#b8325a", "F": "#4d5560", "J": "#a8761f"}
SHORT = {"MOHAVE1975": "Mohave 試験", "FBM1977": "第 1 ベンチマーク", "SBM1985": "第 2 ベンチマーク", "FSCAN1979": "周波数走査",
         "ANDERSON1999": "Anderson ほか(本)", "SQBUTTE1980": "Square Butte", "COALCREEK1981": "Coal Creek",
         "DDSO2015": "周波数走査のふるい分け", "ERCOT2012": "ERCOT 2009",
         "GUYUAN2017": "現地 58 事象", "SUN2011": "Sun 2011", "BAKHSH2016": "周波数の結合", "HAMI2017": "PMSG と弱い系統",
         "CHENG2022": "実事故の総説", "STATCOM2017": "sub・super の相互作用", "WANGBLAA2018": "高調波の安定度",
         "DUTCH2016": "地中ケーブルの共振", "TERMS1985": "用語と定義", "KUNDUR1994": "Kundur(本)", "HATZI2021": "分類の改訂",
         "TB909": "CIGRE TB 909", "KAUAI2023": "カウアイ 2021", "J1976": "直列補償の軸ねじれ", "J1988A": "直流と軸ねじれ",
         "J1997A": "紀伊水道と大型火力", "J2012": "交直の相互作用委員会", "J1985": "直流の低周波不安定"}
YEAR_FIX = {"KUNDUR1994": 1994, "TB909": 2023}

lit = json.loads((HERE / "lit.json").read_text(encoding="utf-8"))
lane_y = {k: len(LANES) - 1 - i for i, (k, _) in enumerate(LANES)}
pos, jitter = {}, {}
for x in sorted(lit, key=lambda x: (x["lane"], x["year"] or YEAR_FIX.get(x["key"], 2000))):
    yr = x["year"] or YEAR_FIX.get(x["key"])
    n = jitter.get((x["lane"], yr), 0); jitter[(x["lane"], yr)] = n + 1
    pos[x["key"]] = (yr + 0.0, lane_y[x["lane"]] + (n % 3 - 1) * 0.22)
fig, ax = plt.subplots(figsize=(15, 7.6), dpi=90)
for i, (k, name) in enumerate(LANES):
    y = lane_y[k]
    ax.axhspan(y - 0.45, y + 0.45, color=COL[k], alpha=0.05, lw=0)
    ax.text(1966.2, y + 0.33, name, va="center", ha="left", fontsize=9.5, color=COL[k], fontweight="bold")
for x in lit:
    for t in x["cites_in_set"]:
        if t in pos and x["key"] in pos:
            a, b = pos[t], pos[x["key"]]
            ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-", connectionstyle="arc3,rad=0.18",
                                         color="#8a9099", alpha=0.28, lw=0.7, zorder=1))
flip = {}
for x in sorted(lit, key=lambda x: pos[x["key"]][0]):
    p = pos[x["key"]]
    s = 18 + 9 * math.log10(1 + (x["cites"] or 0)) ** 2
    ax.scatter([p[0]], [p[1]], s=s, color=COL[x["lane"]], edgecolor="white", linewidth=0.8, zorder=3)
    if x["key"] in SHORT:
        k = flip.get(x["lane"], 0); flip[x["lane"]] = k + 1     # 同じ筋の札は上下に交互に置く
        ax.annotate(SHORT[x["key"]], p, xytext=(3, 9 if k % 2 == 0 else -15), textcoords="offset points",
                    fontsize=8.2, color="#1d2226", zorder=4,
                    bbox=dict(boxstyle="square,pad=0.1", fc="white", ec="none", alpha=0.75))
ax.set_xlim(1966, 2026); ax.set_ylim(-0.6, len(LANES) - 0.4)
ax.set_yticks([]); ax.set_xticks(range(1970, 2030, 5))
for s in ("left", "right", "top"):
    ax.spines[s].set_visible(False)
ax.tick_params(axis="x", colors="#59616a", labelsize=9)
ax.set_title("SSO の系譜: 年 × 筋(点の大きさ = 被引用数・灰色の線 = この 59 本の中の引用)", fontsize=12, loc="left", color="#1d2226")
fig.text(0.01, 0.01, "出典: OpenAlex(書誌・引用)・J-STAGE。DOI の無い 2 本(Kundur・CIGRE TB 909)は引用の線なし。"
         "日本の文献の参考文献は OpenAlex では一部しか結べていない", fontsize=8, color="#59616a")
fig.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig(HERE / "lineage.png")
print("lineage.png")
