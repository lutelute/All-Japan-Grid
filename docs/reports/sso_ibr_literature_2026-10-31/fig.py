"""lit.json からインバータ起因の SSO の系譜の図(年表 × 筋、引用の辺)を描く。python fig.py → lineage_ibr.png"""
import json, math
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch

HERE = Path(__file__).resolve().parent
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
LANES = [("M", "機構(GFL・PLL・弱い系統)"), ("I", "インピーダンス法と判定"), ("G", "系統形成型(GFM)との比較"),
         ("H", "直流・洋上(VSC・MMC)"), ("R", "実事故と再現"), ("T", "分類・教科書・公開の道具"), ("J", "日本(電気学会ほか)")]
COL = {"M": "#c06014", "I": "#1f4e8c", "G": "#2a7f62", "H": "#7a3b8f", "R": "#b8325a", "T": "#4d5560", "J": "#a8761f"}
SHORT = {"HAMI2017": "Hami(PMSG)", "WEAK4HZ2018": "4 Hz か 30 Hz か", "GSCR2018": "一般化 SCR", "PLLLOOP2019": "PLL の同期",
         "PV2018": "太陽光と弱い系統", "SUN2011": "Sun 2011", "CESPEDES2014": "Cespedes・Sun", "DQIMP2015": "dq インピーダンス",
         "UNIFIED2017": "統一モデル", "RYGG2016": "正逆相 = dq", "ADMIT2020": "固有値か Nyquist か",
         "VSG2018": "VSG と従来型", "GFMSSR2023": "GFM と SSR", "GU2022": "Gu・Green",
         "WFHVDC2016": "風力と VSC 直流", "DDWF2020": "直結風力と VSC 直流", "MMCSEQ2017": "MMC",
         "ERCOT2012": "ERCOT 2009", "GUYUAN2017": "現地 58 事象", "CHENG2022": "実事故の総説", "REAL20HZ2022": "太陽光の 20 Hz",
         "HORNSEA2021": "Hornsea 2019", "KAUAI2023": "カウアイ 2021", "HATZI2021": "分類の改訂", "PSID2023": "PSID.jl",
         "FANBOOK2023": "Fan・Miao(本)", "PARAEMT2024": "並列 EMT", "JP2004": "変換器とケーブルの共振",
         "JP2014": "自励式と軸ねじれ", "JP2022": "制御機能の不安定", "JP2024": "PLL と受動性", "JP2025S": "洋上の SCR",
         "JP2025C": "電気学会の委員会", "JP2021K": "新北本(自励式)"}

# 込み合う所の札の置き場(dx, dy[pt], ha)。ほかは同じ筋で上下に交互
LABEL_OFF = {"HAMI2017": (-6, -3, "right"), "GSCR2018": (-7, -3, "right"), "WEAK4HZ2018": (3, -14, "left"),
             "PV2018": (3, 8, "left"), "PLLLOOP2019": (6, -3, "left"), "DQIMP2015": (-4, 9, "right"),
             "RYGG2016": (3, 9, "left"), "UNIFIED2017": (3, -14, "left"), "WFHVDC2016": (-4, 8, "right"),
             "MMCSEQ2017": (6, -3, "left"), "HORNSEA2021": (-4, 8, "right"), "REAL20HZ2022": (3, 8, "left"),
             "CHENG2022": (-4, -14, "right"), "KAUAI2023": (4, -14, "left"), "FANBOOK2023": (-4, -14, "right"),
             "PSID2023": (3, 8, "left"), "PARAEMT2024": (4, -14, "left"), "JP2021K": (3, 8, "left"),
             "JP2024": (3, -14, "left"), "JP2025S": (3, 8, "left"), "JP2025C": (5, -2, "left")}

lit = json.loads((HERE / "lit.json").read_text(encoding="utf-8"))
lane_y = {k: len(LANES) - 1 - i for i, (k, _) in enumerate(LANES)}
pos, jitter = {}, {}
for x in sorted(lit, key=lambda x: (x["lane"], x["year"])):
    n = jitter.get((x["lane"], x["year"]), 0); jitter[(x["lane"], x["year"])] = n + 1
    pos[x["key"]] = (x["year"] + 0.0, lane_y[x["lane"]] + (n % 3 - 1) * 0.24)
fig, ax = plt.subplots(figsize=(15, 7.6), dpi=90)
for k, name in LANES:
    y = lane_y[k]
    ax.axhspan(y - 0.45, y + 0.45, color=COL[k], alpha=0.05, lw=0)
    ax.text(2002.15, y + 0.33, name, va="center", ha="left", fontsize=9.5, color=COL[k], fontweight="bold")
for x in lit:
    for t in x["cites_in_set"]:
        ax.add_patch(FancyArrowPatch(pos[t], pos[x["key"]], arrowstyle="-", connectionstyle="arc3,rad=0.18",
                                     color="#8a9099", alpha=0.28, lw=0.7, zorder=1))
flip = {}
for x in sorted(lit, key=lambda x: (pos[x["key"]][0], x["key"])):
    p = pos[x["key"]]
    s = 18 + 9 * math.log10(1 + (x["cites"] or 0)) ** 2
    prev = x["role"] == "前回"                           # 前回の 59 本にもあるものは白抜き
    ax.scatter([p[0]], [p[1]], s=s, color="white" if prev else COL[x["lane"]], edgecolor=COL[x["lane"]],
               linewidth=1.4 if prev else 0.8, zorder=3)
    if x["key"] in SHORT:
        k = flip.get(x["lane"], 0); flip[x["lane"]] = k + 1
        dx, dy, ha = LABEL_OFF.get(x["key"], (3, 9 if k % 2 == 0 else -15, "left"))
        ax.annotate(SHORT[x["key"]], p, xytext=(dx, dy), textcoords="offset points", ha=ha,
                    fontsize=8.2, color="#1d2226", zorder=4,
                    bbox=dict(boxstyle="square,pad=0.1", fc="white", ec="none", alpha=0.75))
ax.set_xlim(2002, 2027.5); ax.set_ylim(-0.6, len(LANES) - 0.4)
ax.set_yticks([]); ax.set_xticks(range(2004, 2028, 2))
for s in ("left", "right", "top"):
    ax.spines[s].set_visible(False)
ax.tick_params(axis="x", colors="#59616a", labelsize=9)
ax.set_title("インバータ起因の SSO の系譜: 年 × 筋(点の大きさ = 被引用数・白抜き = 前回の 59 本にもある・灰色の線 = この 50 本の中の引用)",
             fontsize=11.5, loc="left", color="#1d2226")
fig.text(0.01, 0.01, "出典: OpenAlex(書誌・引用)・J-STAGE。日本の文献の参考文献は OpenAlex では一部しか結べていない", fontsize=8, color="#59616a")
fig.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig(HERE / "lineage_ibr.png")
print("lineage_ibr.png")
