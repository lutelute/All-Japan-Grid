#!/usr/bin/env python3
"""#168 の N-1 で、東の「新たな過負荷を生む開放」が 125 → 145 に増えた内訳(先生の問い 2026-11-09)。

n1_east_dump.py の出力(前・後)を突き合わせ、増えた開放・減った開放・新たに過負荷になる線・
基準の負荷率と、275 kV 以上の線の流れの変わり方をまとめる。

    python3 n1_east.py <前.json> <後.json>
→ n1_east.json(まとめ)・fig_n1_east.png
"""
import collections
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#b9b8b1"
BLUE, RED, MID = "#2a78d6", "#e34948", "#e4e3de"


def key(r):
    return (r["table"], r["name"], tuple(sorted([r["from"], r["to"]])), r["kv"])


def main(bp, ap):
    B, A = json.load(open(bp, encoding="utf-8")), json.load(open(ap, encoding="utf-8"))
    bc = {key(r): r for r in B["causing"]}
    ac = {key(r): r for r in A["causing"]}
    bm = {key(r): r for r in B["monitored"]}
    am = {key(r): r for r in A["monitored"]}
    only_a = sorted(ac.keys() - bc.keys(), key=lambda k: -ac[k]["post_max_new"])
    only_b = sorted(bc.keys() - ac.keys())

    def row(r, other=None):
        return {"name": r["name"], "from": r["from"], "to": r["to"], "table": r["table"], "kv": r["kv"],
                "class": r["cls"], "f0_mw": r["f0"], "f0_other_mw": (other or {}).get("f0"),
                "post_max_new_pct": r["post_max_new"],
                "new_over": [{"name": j["name"], "from": j["from"], "to": j["to"],
                              "base_pct": j["base_pct"], "post_pct": j["post_pct"]} for j in r["new_over"]]}

    base_over_b = {key(r) for r in B["base_over"]}
    base_over_a = {key(r) for r in A["base_over"]}
    # 新たに過負荷になる線(増えた開放の側)ごとの、前と後の基準の負荷率
    tgt = collections.Counter()
    for k in only_a:
        for j in ac[k]["new_over"]:
            tgt[key(j)] += 1
    targets = []
    for k, c in tgt.most_common():
        b, a = bm.get(k), am.get(k)
        targets.append({"name": k[1], "from": k[2][0], "to": k[2][1], "n_outages": c,
                        "par_before": b and b["par"], "par_after": a and a["par"],
                        "cap_before_mw": b and b["cap"], "cap_after_mw": a and a["cap"],
                        "base_pct_before": b and b["base_pct"], "base_pct_after": a and a["base_pct"],
                        "base_over_before": k in base_over_b, "base_over_after": k in base_over_a})
    # 275 kV 以上の流れの変わり方(前と後で 1 本ずつ対応の付く線)
    ball, aall = collections.defaultdict(list), collections.defaultdict(list)
    for r in B["all"]:
        ball[key(r)].append(r)
    for r in A["all"]:
        aall[key(r)].append(r)
    flows = []
    for k in ball.keys() & aall.keys():
        if k[3] >= 275 and len(ball[k]) == 1 and len(aall[k]) == 1:
            b, a = ball[k][0], aall[k][0]
            flows.append({"name": k[1], "from": k[2][0], "to": k[2][1], "kv": k[3], "table": k[0],
                          "f0_before": b["f0"], "f0_after": a["f0"],
                          "d_abs": round(abs(a["f0"]) - abs(b["f0"]), 1), "a": a["a"], "b": a["b"]})
    flows.sort(key=lambda r: r["d_abs"])
    tie = {t: [(r["from"], r["to"], r["f0"]) for r in S["all"] if r["cls"] == "synthetic_tie"]
           for t, S in (("before", B), ("after", A))}
    # 同じ枝の数(並行の写しが 1 本になったか)
    cb = collections.Counter(key(r) for r in B["monitored"])
    ca = collections.Counter(key(r) for r in A["monitored"])
    lost = [k for k in cb if ca.get(k, 0) < cb[k]]
    lost_touch = [k for k in lost if k in tgt or k in set(only_a)]
    marginal = [k for k in only_a if ac[k]["post_max_new"] <= 103.0]
    out = {
        "what": "#168 の N-1(実在の線を見張る数え方)で東の新たな過負荷を生む開放が 125 → 145 に増えた内訳",
        "n_causing": [B["n_causing"], A["n_causing"]], "n_base_over": [B["n_base_over"], A["n_base_over"]],
        "n_only_after": len(only_a), "n_only_before": len(only_b), "n_both": len(ac.keys() & bc.keys()),
        "n_only_after_marginal_le_103pct": len(marginal),
        "n_monitored": [len(B["monitored"]), len(A["monitored"])],
        "n_monitored_lost": len(lost), "n_monitored_lost_touching_new": len(lost_touch),
        "targets": targets,
        "only_after": [row(ac[k], bm.get(k)) for k in only_a],
        "only_before": [row(bc[k], am.get(k)) for k in only_b],
        "synthetic_tie": tie,
        "flow_275kv_decrease": [{k: v for k, v in r.items() if k not in ("a", "b")} for r in flows[:12]],
        "flow_275kv_increase": [{k: v for k, v in r.items() if k not in ("a", "b")} for r in flows[-12:][::-1]],
    }
    json.dump(out, open(os.path.join(HERE, "n1_east.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"開放 {B['n_causing']} → {A['n_causing']}: 後だけ {len(only_a)}(うち 103% 以下 {len(marginal)})・"
          f"前だけ {len(only_b)}・見張る線の消えた写し {len(lost)}(増えた開放に関わるもの {len(lost_touch)})")
    fig_(B, A, flows, only_a, ac, tgt, tie)


def fig_(B, A, flows, only_a, ac, tgt, tie):
    fig = plt.figure(figsize=(17, 8.6))
    fig.patch.set_facecolor("#fcfcfb")
    gs = fig.add_gridspec(1, 3, width_ratios=[1, 1, 1.05], wspace=0.08)
    box = (138.95, 141.25, 35.7, 37.95)
    am = {key(r): r for r in A["monitored"]}
    # 図に名前を出す線: 名前 → (後の網での区間をまとめた流れの最大を出す)
    # 図に数字を出す区間: (見出し, 線の名前の組, 端の名前に含む語, もう片方の端は北か, 文字の位置(経度, 緯度), 寄せ)
    LAB = [("南いわき幹線\n（新今市→東群馬）", ("南いわき幹線",), "東群馬", False, (139.0, 36.98), "left"),
           ("川内線\n（南いわき→新いわき）", ("川内線",), "南いわき開閉所", False, (141.2, 37.62), "right"),
           ("福島幹線＋福島東幹線\n（北から新茂木へ）", ("福島幹線", "福島東幹線"), "新茂木", True, (141.2, 37.0), "right"),
           ("新茂木線", ("新茂木線",), "", False, (139.55, 36.22), "center"),
           ("那珂線", ("那珂線",), "", False, (140.85, 36.25), "center")]
    for pi, (S, title) in enumerate(((B, "前（#167 の先頭）"), (A, "後（#168）"))):
        ax = fig.add_subplot(gs[0, pi])
        allS = [r for r in S["all"] if r["kv"] >= 154 and r["a"][0] and r["b"][0]]
        segs = [[(r["a"][1], r["a"][0]), (r["b"][1], r["b"][0])] for r in allS if r["kv"] < 275]
        ax.add_collection(LineCollection(segs, colors=MUTED, linewidths=0.45, zorder=1))
        big = [r for r in allS if r["kv"] >= 275 and r["table"] == "line" and r["cls"] != "synthetic_tie"]
        segs = [[(r["a"][1], r["a"][0]), (r["b"][1], r["b"][0])] for r in big]
        wid = [0.5 + 5.0 * min(1.0, abs(r["f0"]) / 3000) for r in big]
        ax.add_collection(LineCollection(segs, colors=BLUE, linewidths=wid, zorder=3, capstyle="round", alpha=0.9))
        for r in S["all"]:
            if r["cls"] == "synthetic_tie" and r["a"][0]:
                ax.plot([r["a"][1], r["b"][1]], [r["a"][0], r["b"][0]], color=RED,
                        lw=0.8 + 5.0 * min(1.0, abs(r["f0"]) / 3000), zorder=4, solid_capstyle="round")
                ax.annotate(f"合成のタイ 東北東京間連系線 {abs(r['f0']):,.0f} MW",
                            ((r["a"][1] + r["b"][1]) / 2, (r["a"][0] + r["b"][0]) / 2),
                            xytext=(140.2, 37.86), textcoords="data", fontsize=8, color=INK, ha="center",
                            va="center", zorder=8,
                            bbox=dict(boxstyle="round,pad=0.2", fc="#fcfcfb", ec=RED, lw=0.6, alpha=0.95),
                            arrowprops=dict(arrowstyle="-", color=RED, lw=0.6, shrinkA=0, shrinkB=2))
        # 区間ごとの流れ(同じ見出しで線が 2 本あれば大きさを足す。区切りが前と後で違っても比べられるように)
        for lab, names, endw, north, txy, ha in LAB:
            pick = []
            for n in names:
                rs = [r for r in big if r["name"] == n and (not endw or endw in r["from"] or endw in r["to"])]
                if north:
                    def other_north(r):
                        own, oth = (r["a"], r["b"]) if endw in r["from"] else (r["b"], r["a"])
                        return oth[0] > own[0]
                    rs = [r for r in rs if other_north(r)]
                if rs:
                    pick.append(max(rs, key=lambda r: abs(r["f0"])))
            if not pick:
                continue
            val = sum(abs(r["f0"]) for r in pick)
            for r in pick:
                x, y = (r["a"][1] + r["b"][1]) / 2, (r["a"][0] + r["b"][0]) / 2
                ax.annotate("", (x, y), xytext=txy, textcoords="data",
                            arrowprops=dict(arrowstyle="-", color=INK2, lw=0.6, shrinkA=0, shrinkB=2))
            ax.text(txy[0], txy[1], f"{lab} {val:,.0f}", fontsize=8, color=INK, ha=ha, va="center",
                    bbox=dict(boxstyle="round,pad=0.2", fc="#fcfcfb", ec=MUTED, lw=0.5, alpha=0.95), zorder=8)
        if S is A:
            for k in tgt:
                r = am.get(k)
                if r and r["a"][0]:
                    ax.plot([r["a"][1], r["b"][1]], [r["a"][0], r["b"][0]], color=INK, lw=3.2, zorder=5)
            for k in only_a:
                r = ac[k]
                if r["a"][0]:
                    ax.plot((r["a"][1] + r["b"][1]) / 2, (r["a"][0] + r["b"][0]) / 2, marker="x", color=INK2,
                            ms=7, mew=1.6, zorder=6)
        ax.set_xlim(box[0], box[1])
        ax.set_ylim(box[2], box[3])
        ax.set_aspect(1.24)
        ax.set_xticks([])
        ax.set_yticks([])
        for s_ in ax.spines.values():
            s_.set_color(MUTED)
        sub = ("太さ = 基準の流れの大きさ（275 kV 以上）\n赤 = 合成のタイ・数字 = その区間の流れ [MW]" if pi == 0 else
               "黒 = 新たに過負荷になる 154 kV の線\n× = 増えた開放（21 件）の場所")
        ax.set_title(f"{title}\n{sub}", fontsize=9.5, color=INK, loc="left")
    # 右: 新たに過負荷になる線の、基準の負荷率(前 → 後)と、その線を過負荷にする増えた開放の数
    ax2 = fig.add_subplot(gs[0, 2])
    bm = {key(r): r for r in B["monitored"]}
    rows = []
    for k, c in tgt.most_common():
        b, a = bm.get(k), am.get(k)
        if b and a:
            rows.append((k[1], b["base_pct"], a["base_pct"], c))
    rows = rows[::-1]
    for i, (nm, b0, a0, c) in enumerate(rows):
        ax2.plot([b0, a0], [i, i], color=MUTED, lw=2, zorder=1)
        ax2.plot(b0, i, "o", color="#fcfcfb", mec=INK2, ms=8, mew=1.6, zorder=2)
        ax2.plot(a0, i, "o", color=INK, ms=8, zorder=3)
        ax2.annotate(f"{b0:.1f} → {a0:.1f}%（{c} 件）", (min(a0, b0), i), xytext=(-10, 9),
                     textcoords="offset points", fontsize=8.5, color=INK)
    ax2.axvline(100, color=RED, lw=1, ls=":")
    ax2.set_yticks(range(len(rows)))
    ax2.set_yticklabels([r[0] for r in rows], fontsize=9, color=INK)
    ax2.set_xlim(40, 108)
    ax2.set_ylim(-0.6, len(rows) - 0.3)
    ax2.set_xlabel("基準（開放の前）の負荷率 [%]　白丸 = 前・黒丸 = 後・点線 = 100%", fontsize=9, color=INK2)
    ax2.grid(axis="x", color="#ecebe7", lw=0.6)
    for s_ in ("top", "right"):
        ax2.spines[s_].set_visible(False)
    ax2.set_title("新たに過負荷になる線（かっこ = その線を過負荷にする増えた開放の数）\n"
                  "本数と容量は前と同じ。基準の流れが増えて 100% に近づいた。\n"
                  "西水戸線は前は基準で 100% を超えていて「新たな」過負荷に数えなかった",
                  fontsize=9.5, color=INK, loc="left")
    fig.subplots_adjust(left=0.01, right=0.99, top=0.88, bottom=0.07)
    fig.savefig(os.path.join(HERE, "fig_n1_east.png"), dpi=130, facecolor=fig.get_facecolor())
    print("→ fig_n1_east.png")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
