"""SSO の第 0 段(文献の系譜)を見せる短い動画(音なし・字幕つき)。
python docs/reports/sso_literature_2026-10-31/video.py docs/reports/sso_literature_2026-10-31 <出力.mp4> [--still 秒,秒,...]
要るもの: matplotlib と ffmpeg。lit.json だけを読む(git の外のデータは使わない)"""
import json, math, sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle
from matplotlib.animation import FFMpegWriter

LIT_DIR, OUT = Path(sys.argv[1]), Path(sys.argv[2])
STILLS = [float(s) for s in sys.argv[4].split(",")] if len(sys.argv) > 4 and sys.argv[3] == "--still" else None
FPS = 30
BG, INK, SUB, RULE, GRAY = "#fbfaf7", "#1d2226", "#59616a", "#c9c6bd", "#8a9099"
SANS, MIN = ["Hiragino Sans", "sans-serif"], ["Hiragino Mincho ProN", "serif"]
plt.rcParams["font.family"] = SANS

# ---- 系譜のデータ(fig.py と同じ置き方) ----
LANES = [("A", "直列補償と軸ねじれ(SSR)"), ("B", "直流・パワエレと軸ねじれ(SSTI)"), ("C", "風力と直列補償(SSCI)"),
         ("D", "インバータとインピーダンス法"), ("E", "super 側・高調波・ケーブル"),
         ("F", "分類・用語・指針"), ("J", "日本(電気学会ほか)")]
COL = {"A": "#1f4e8c", "B": "#7a3b8f", "C": "#2a7f62", "D": "#c06014", "E": "#b8325a", "F": "#4d5560", "J": "#a8761f"}
SHORT = {"MOHAVE1975": "Mohave 試験", "FBM1977": "第 1 ベンチマーク", "SBM1985": "第 2 ベンチマーク",
         "ANDERSON1999": "Anderson ほか(本)", "SQBUTTE1980": "Square Butte", "COALCREEK1981": "Coal Creek",
         "ERCOT2012": "ERCOT 2009", "GUYUAN2017": "現地 58 事象", "SUN2011": "Sun 2011", "BAKHSH2016": "周波数の結合",
         "HAMI2017": "PMSG と弱い系統", "CHENG2022": "実事故の総説", "STATCOM2017": "sub・super の相互作用",
         "WANGBLAA2018": "高調波の安定度", "DUTCH2016": "地中ケーブルの共振", "HATZI2021": "分類の改訂",
         "TB909": "CIGRE TB 909", "KAUAI2023": "カウアイ 2021", "J1976": "直列補償の軸ねじれ", "J1988A": "直流と軸ねじれ",
         "J1997A": "紀伊水道と大型火力", "J2012": "交直の相互作用委員会"}
YEAR_FIX = {"KUNDUR1994": 1994, "TB909": 2023}
# 込み合う所の札の置き場(dx, dy[pt], ha)。ほかは同じ筋で上下に交互
LABEL_OFF = {"SUN2011": (-7, 8, "right"), "HAMI2017": (5, 16, "left"), "BAKHSH2016": (-4, -16, "right"),
             "CHENG2022": (4, -16, "left"), "WANGBLAA2018": (5, 8, "left"), "DUTCH2016": (-5, -15, "right"),
             "STATCOM2017": (4, -15, "left"), "HATZI2021": (-7, -14, "right"), "TB909": (4, -14, "left"),
             "KAUAI2023": (-4, 8, "right"), "J1997A": (4, -15, "left")}
lit = json.loads((LIT_DIR / "lit.json").read_text(encoding="utf-8"))
for x in lit:
    x["yr"] = x["year"] or YEAR_FIX[x["key"]]
by_key = {x["key"]: x for x in lit}
lane_y = {k: len(LANES) - 1 - i for i, (k, _) in enumerate(LANES)}
pos, jit = {}, {}
for x in sorted(lit, key=lambda x: (x["lane"], x["yr"])):
    n = jit.get((x["lane"], x["yr"]), 0); jit[(x["lane"], x["yr"])] = n + 1
    pos[x["key"]] = (x["yr"], lane_y[x["lane"]] + (n % 3 - 1) * 0.22)
EDGES = [(t, x["key"]) for x in lit for t in x["cites_in_set"] if t in by_key]

# 年ごとの持ち時間: 本の多い年ほど長く(1 年 0.15 秒 + 1 本 0.33 秒)
Y0, Y1, PER_YEAR, PER_PAPER = 1968, 2025, 0.15, 0.33
appear, cur_t, year_start = {}, 0.0, {}
for y in range(Y0, Y1 + 1):
    year_start[y] = cur_t
    papers = sorted([x for x in lit if x["yr"] == y], key=lambda x: "ABCDEFJ".index(x["lane"]))
    for i, x in enumerate(papers):
        appear[x["key"]] = cur_t + PER_YEAR + PER_PAPER * i
    cur_t += PER_YEAR + PER_PAPER * len(papers)
year_start[Y1 + 1] = cur_t
SWEEP = cur_t

def cursor_year(t):
    for y in range(Y0, Y1 + 1):
        if t < year_start[y + 1]:
            return y + (t - year_start[y]) / (year_start[y + 1] - year_start[y])
    return Y1 + 1.0

# ---- 台本(秒) ----
T_TITLE = (0.0, 4.5)
T_BAND = (4.5, 18.0)
T_LIN = (18.0, 18.0 + SWEEP + 4.5 + 11.0)       # 掃引 → 全体 → 日本
T_PLAN = (T_LIN[1], T_LIN[1] + 13.0)
T_END = (T_PLAN[1], T_PLAN[1] + 4.5)
TOTAL = T_END[1]

def clamp(v): return max(0.0, min(1.0, v))
def ease(v): v = clamp(v); return 1 - (1 - v) ** 3
def back(v):
    v = clamp(v); c = 1.70158
    return 1 + (c + 1) * (v - 1) ** 3 + c * (v - 1) ** 2
def window(t, a, b, d=0.35): return clamp((t - a) / d) * clamp((b - t) / d)

def header(fig, text, a=1.0, right=None):
    fig.text(0.05, 0.945, text, fontsize=11, color=SUB, alpha=a)
    if right: fig.text(0.95, 0.945, right, fontsize=15, color=INK, ha="right", family=MIN)
    else: fig.text(0.95, 0.945, "All-Japan-Grid", fontsize=11, color=SUB, ha="right", alpha=a)
    fig.add_artist(plt.Line2D([0.05, 0.95], [0.925, 0.925], color=RULE, lw=0.8, alpha=a))

def caption(fig, t, items):
    """items = [(t0, t1, 文)]。下の帯に 1 つずつ出す"""
    fig.add_artist(plt.Line2D([0.05, 0.95], [0.155, 0.155], color=RULE, lw=0.8))
    for a, b, s in items:
        w = window(t, a, b)
        if w > 0:
            fig.text(0.05, 0.088, s, fontsize=17, color=INK, alpha=w, va="center", linespacing=1.5)

# ---- 1. 表題 ----
def scene_title(fig, t):
    a = ease((t - 0.2) / 0.8)
    fig.text(0.08, 0.60, "SSO の文献の系譜", fontsize=50, family=MIN, color=INK, alpha=a)
    fig.add_artist(plt.Line2D([0.08, 0.08 + 0.84 * ease((t - 0.5) / 1.0)], [0.53, 0.53], color=INK, lw=1.2))
    b = ease((t - 1.0) / 0.8)
    fig.text(0.08, 0.45, "系統周波数の下(sub)と上(super)の振動  ・  59 本  ・  1971〜2023", fontsize=18, color=SUB, alpha=b)
    fig.text(0.08, 0.12, "2026-10-31  ・  第 0 段(文献調査と系譜)  ・  PR #125", fontsize=13, color=SUB, alpha=b)

# ---- 2. 帯 ----
F0 = 60.0
def scene_band(fig, t):
    t -= T_BAND[0]
    header(fig, "SSO はどの帯か")
    ax = fig.add_axes([0.07, 0.25, 0.86, 0.62]); ax.set_facecolor(BG)
    ax.set_xscale("log"); ax.set_xlim(0.08, 230); ax.set_ylim(0, 4.5)
    ax.set_yticks([]); [ax.spines[s].set_visible(False) for s in ("left", "right", "top")]
    ax.spines["bottom"].set_color(SUB)
    ticks = [0.1, 1, 2.5, 10, 60, 120]
    ax.set_xticks(ticks); ax.set_xticklabels(["0.1", "1", "2.5", "10", "60", "120 Hz"])
    ax.xaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    ax.tick_params(axis="x", colors=SUB, labelsize=12)

    def bar(a, b, y, col, p):
        if p <= 0: return
        bb = a * (b / a) ** ease(p)
        ax.add_patch(Rectangle((a, y - 0.2), bb - a, 0.4, color=col, lw=0, alpha=0.85))

    p1 = (t - 0.3) / 1.0
    bar(0.1, 2.5, 3.8, GRAY, p1)
    ax.text(0.1, 4.15, "いまの多機動揺モデル: 電気機械モード 0.1〜2.5 Hz", fontsize=13, color=SUB, alpha=ease(p1))
    p2 = (t - 4.3) / 1.2
    bar(3.0, F0, 2.3, COL["A"], p2)
    ax.text(3.0, 1.98, "sub(数 Hz〜f0)", fontsize=14, color=COL["A"], fontweight="bold", va="top", alpha=ease(p2))
    ax.text(3.0, 1.52, "軸ねじれと直列補償(SSR)\n直流の制御と軸ねじれ(SSTI)\nインバータの制御(SSCI)",
            fontsize=12, color=INK, va="top", linespacing=1.6, alpha=ease(p2 - 0.4))
    p3 = (t - 6.0) / 1.0
    bar(F0, 2 * F0, 2.3, COL["E"], p3)
    ax.text(F0 * 1.04, 1.98, "super(f0〜2f0 前後)", fontsize=14, color=COL["E"], fontweight="bold", va="top", alpha=ease(p3))
    ax.text(F0 * 1.04, 1.52, "インバータの制御\nケーブルの並列共振", fontsize=12, color=INK, va="top",
            linespacing=1.6, alpha=ease(p3 - 0.4))
    pf = ease((t - 4.0) / 0.6)
    ax.plot([F0, F0], [0.0, 3.45], color=INK, lw=1.0, ls=(0, (3, 3)), alpha=pf)
    ax.text(F0, 3.55, "f0 = 60 Hz(西。東は 50 Hz)", fontsize=12, color=INK, ha="center", alpha=pf)
    # インバータの鏡像の組: f と 2f0 − f
    for k, (fa, d0) in enumerate([(20.0, 8.6), (38.0, 9.6)]):
        fb = 2 * F0 - fa
        p = ease((t - d0) / 1.1)
        if p <= 0: continue
        s = np.linspace(0, p, 80)
        xs = np.exp(np.log(fa) + (np.log(fb) - np.log(fa)) * s)
        ax.plot(xs, 2.52 + (0.42 + 0.25 * k) * np.sin(np.pi * s), color=COL["D"], lw=1.8)
        ax.scatter([fa], [2.3], s=36, color=COL["D"], zorder=5, edgecolor="white")
        if p >= 1: ax.scatter([fb], [2.3], s=36, color=COL["D"], zorder=5, edgecolor="white")
        if k == 0:
            ax.text(fa / 1.07, 2.58, f"{fa:.0f} Hz", fontsize=10.5, color=COL["D"], ha="right", alpha=p)
            ax.text(fb * 1.06, 2.58, f"{fb:.0f} Hz", fontsize=10.5, color=COL["D"], ha="left", alpha=clamp(p * 3 - 2))
    caption(fig, t, [(0.0, 4.2, "いまの動揺の道具が見ているのは、0.1〜2.5 Hz の電気機械モードだけ"),
                     (4.2, 8.4, "SSO は、系統周波数 f0 の下(sub)と上(super)の両方で起きる"),
                     (8.4, 13.6, "インバータでは f と 2f0 − f が組で出る(60 Hz なら 20 Hz と 100 Hz)。\nsub と super は分けずに見る")])

# ---- 3. 系譜 ----
ERAS = [(1968, 1980, "1970 年代: 直列補償の線と、発電機の軸ねじれの共振(SSR)。\nMohave の試験、IEEE 第 1 ベンチマーク(1977)"),
        (1980, 1990, "1980 年代: 直流の制御と軸ねじれ(Square Butte・Coal Creek)。\n用語の整理と第 2 ベンチマーク。日本でも直流と軸ねじれの研究"),
        (1990, 2007, "1990 年代: 教科書がまとまる。\n日本では、紀伊水道の直流と大型火力の相互作用を検討(1997)"),
        (2007, 2014, "2009 年 ERCOT: 風力と直列補償の SSCI。\nインピーダンスでインバータの安定を判定する手法(Sun 2011)"),
        (2014, 2020, "2010 年代後半: 弱い系統の風力の振動、sub と super の相互作用、\n高調波の安定度"),
        (2020, 2027, "2020 年代: 安定度の分類の改訂(2021)、CIGRE TB 909(2023)、\n実事故の総説")]

def scene_lineage(fig, t):
    t -= T_LIN[0]
    t_sweep_end, t_jp = SWEEP, SWEEP + 4.5
    ax = fig.add_axes([0.04, 0.19, 0.93, 0.71]); ax.set_facecolor(BG)
    ax.set_xlim(1966, 2026.5); ax.set_ylim(-0.6, len(LANES) - 0.35)
    ax.set_yticks([]); ax.set_xticks(range(1970, 2030, 10))
    [ax.spines[s].set_visible(False) for s in ("left", "right", "top")]
    ax.spines["bottom"].set_color(SUB); ax.tick_params(axis="x", colors=SUB, labelsize=11)
    jp = ease((t - t_jp) / 0.9)                      # 日本の筋だけを残す度合い
    def dim(lane): return 1.0 - 0.85 * jp if lane != "J" else 1.0
    for k, name in LANES:
        y = lane_y[k]
        ax.axhspan(y - 0.45, y + 0.45, color=COL[k], alpha=0.05 * dim(k) + (0.07 * jp if k == "J" else 0), lw=0)
        ax.text(1966.3, y + 0.30, name, va="center", fontsize=11, color=COL[k], fontweight="bold", alpha=dim(k))
    cy = cursor_year(min(t, t_sweep_end))
    if t < t_sweep_end + 0.6:
        ca = 1 - clamp((t - t_sweep_end) / 0.6)
        ax.axvline(cy, color=INK, lw=0.8, alpha=0.5 * ca)
    n_seen = sum(1 for k in appear if appear[k] <= t)
    yr_txt = f"{min(int(cy), Y1)} 年" if t < t_sweep_end else "1971〜2023"
    header(fig, "SSO の系譜  ・  年 × 筋(点の大きさ = 被引用数、線 = この 59 本の中の引用)", right=f"{yr_txt}  ・  {n_seen} 本")
    for a, b in EDGES:
        ta = appear[b]
        if t < ta: continue
        age = t - ta
        touch_j = by_key[a]["lane"] == "J" or by_key[b]["lane"] == "J"
        fresh = clamp(1 - age / 1.3)
        col = COL[by_key[b]["lane"]] if fresh > 0 else GRAY
        alpha = (0.28 + 0.5 * fresh) * ease(age / 0.3)
        lw = 0.8 + 0.7 * fresh
        if jp > 0:
            if touch_j: col, alpha, lw = COL["J"], alpha + (0.85 - alpha) * jp, lw + 1.0 * jp
            else: alpha *= 1 - 0.8 * jp
        ax.add_patch(FancyArrowPatch(pos[a], pos[b], arrowstyle="-", connectionstyle="arc3,rad=0.18",
                                     color=col, alpha=alpha, lw=lw, zorder=1))
    flip = {}
    for x in sorted(lit, key=lambda x: (pos[x["key"]][0], x["key"])):
        k = x["key"]
        if x["key"] in SHORT:
            f = flip.get(x["lane"], 0); flip[x["lane"]] = f + 1
        if t < appear[k]: continue
        age = t - appear[k]
        p = pos[k]
        s = (22 + 11 * math.log10(1 + (x["cites"] or 0)) ** 2) * back(age / 0.35)
        d = dim(x["lane"])
        ax.scatter([p[0]], [p[1]], s=s, color=COL[x["lane"]], edgecolor="white", linewidth=0.8, zorder=3, alpha=d)
        if k in SHORT:
            dx, dy, ha = LABEL_OFF.get(k, (4, 9 if f % 2 == 0 else -16, "left"))
            ax.annotate(SHORT[k], p, xytext=(dx, dy), textcoords="offset points", ha=ha,
                        fontsize=9.5, color=INK, zorder=4, alpha=ease(age / 0.3) * d,
                        bbox=dict(boxstyle="square,pad=0.1", fc=BG, ec="none", alpha=0.8 * d))
    if jp > 0:                                        # 紀伊水道の論文を枠で囲む
        p = pos["J1997A"]
        ax.add_patch(Rectangle((p[0] - 0.7, p[1] - 0.15), 1.4, 0.30, fill=False, ec=COL["J"], lw=1.6, alpha=jp, zorder=6))
    items = []
    for y0, y1, s in ERAS:
        a, b = year_start[max(y0, Y0)], year_start[min(y1, Y1 + 1)]
        if y1 >= 2027: b = t_sweep_end + 1.8
        items.append((a, b, s))
    items.append((t_sweep_end + 1.8, t_jp, "59 本(DOI のある 57 本は DOI で確かめた)。引用の線は 145 本"))
    items.append((t_jp, t_jp + 5.6, "日本: 紀伊水道の直流 1,400 MW と、直結する大型火力の相互作用と対策\n(1997・山路ほか)。AGJ が最初に照らす相手"))
    items.append((t_jp + 5.6, t_jp + 11.2, "国内の直流の論文は Square Butte を引いている。\nインバータの側の国内の文献は、続く調査で見つかった(2014・2022・2024・2025)"))
    caption(fig, t, items)

# ---- 4. 次の段 ----
STEPS = [("前提を確かめる", "基幹系統に直列補償があるか。直流の変換所は他励式か自励式か"),
         ("ベンチマークを再現する", "IEEE 第 1 ベンチマーク。通らなければ全国には進まない"),
         ("周波数走査", "選んだバスから見た網のインピーダンス Z(f)、1 Hz〜2f0 超"),
         ("UIF で一次判定", "変換所の近くの機ごとに。紀伊水道・橘湾を 1997 年の論文と照らす"),
         ("ねじれの帯と突き合わせる", "f0 − 網の共振 が、典型のねじれの帯に入る機を挙げる"),
         ("報告", "西・東・北海道で回す。出すのは詳しく調べる候補の順位まで")]
def scene_plan(fig, t):
    t -= T_PLAN[0]
    header(fig, "次の段の計画(第 1 段: 同期機と直流)")
    top, step = 0.84, 0.105
    for i, (h, d) in enumerate(STEPS):
        a = ease((t - 0.4 - 0.75 * i) / 0.5)
        y = top - step * i
        fig.text(0.07, y - 0.035, f"{i + 1}", fontsize=26, family=MIN, color=INK, alpha=a, va="center")
        fig.text(0.12, y - 0.035, h, fontsize=17, color=INK, fontweight="bold", alpha=a, va="center")
        fig.text(0.40, y - 0.035, d, fontsize=14, color=SUB, alpha=a, va="center")
        fig.add_artist(plt.Line2D([0.05, 0.95], [y - step + 0.017, y - step + 0.017], color=RULE, lw=0.6, alpha=a))
    if t > 7.6:                                       # 最初の一手を強調
        a = ease((t - 7.6) / 0.6)
        fig.add_artist(Rectangle((0.05, top - 0.07), 0.9, 0.07, transform=fig.transFigure, fill=False,
                                 ec=COL["A"], lw=1.6, alpha=a))
    caption(fig, t, [(0.0, 7.4, "段の組み方は CIGRE TB 909 の「ふるい分け → 詳しい検討 → 対策 → 監視」。\nAGJ がやるのは、ふるい分けだけ"),
                     (7.4, 10.4, "UIF は直列補償の無い網でしか成り立たない。\nだから、最初に直列補償の有無を確かめる"),
                     (10.4, 13.0, "第 1 段は、指示を受けてから始める")])

# ---- 5. 終わり ----
def scene_end(fig, t):
    t -= T_END[0]
    a = ease((t - 0.2) / 0.6)
    fig.text(0.08, 0.66, "報告と計画", fontsize=30, family=MIN, color=INK, alpha=a)
    fig.add_artist(plt.Line2D([0.08, 0.92], [0.61, 0.61], color=INK, lw=1.0, alpha=a))
    for i, s in enumerate(["docs/reports/sso_literature_2026-10-31.md     文献 59 本・系譜・日本の文脈",
                           "docs/reports/sso_plan_2026-10-31.md     計画 案 3",
                           "docs/reports/sso_literature_2026-10-31/     表・図・BibTeX・再現のスクリプト"]):
        fig.text(0.08, 0.52 - 0.075 * i, s, fontsize=14, color=INK, family=["Menlo"] + SANS, alpha=ease((t - 0.5 - 0.3 * i) / 0.5))
    fig.text(0.08, 0.14, "github.com/lutelute/All-Japan-Grid", fontsize=13, color=SUB, alpha=a)

SCENES = [(T_TITLE, scene_title), (T_BAND, scene_band), (T_LIN, scene_lineage), (T_PLAN, scene_plan), (T_END, scene_end)]

def render(fig, t):
    fig.clf(); fig.set_facecolor(BG)
    for (a, b), fn in SCENES:
        if a <= t < b or (fn is scene_end and t >= b):
            fn(fig, t)
            w = window(t, a, b, 0.4) if fn is not scene_end else clamp((t - a) / 0.4) * clamp((TOTAL - t) / 0.6)
            if w < 1:
                fig.add_artist(Rectangle((0, 0), 1, 1, transform=fig.transFigure, color=BG, alpha=1 - w, zorder=100))
            break

fig = plt.figure(figsize=(12.8, 7.2), dpi=100)
if STILLS:
    for s in STILLS:
        render(fig, s); fig.savefig(OUT.with_name(f"{OUT.stem}_{s:05.1f}.png"), facecolor=BG)
    print("stills", STILLS, "total", round(TOTAL, 1)); sys.exit()
writer = FFMpegWriter(fps=FPS, codec="libx264", bitrate=-1,
                      extra_args=["-pix_fmt", "yuv420p", "-crf", "22", "-preset", "medium"])
n = int(TOTAL * FPS)
with writer.saving(fig, str(OUT), dpi=100):
    for i in range(n):
        render(fig, i / FPS); writer.grab_frame(facecolor=BG)
        if i % 300 == 0: print(f"{i}/{n}", flush=True)
print("done", OUT, round(TOTAL, 1), "s")
