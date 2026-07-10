#!/usr/bin/env python3
"""既定ON化(#19/#20/#21)の before/after 要約図 — compare.json から生成。

左: 島別の連結成分数(log)  右: 島別バス数。下段: AC/DC成立と損失の表。
before=従来既定(全OFF) / after=新既定。LINE送付用の1枚。
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

HERE = os.path.dirname(os.path.abspath(__file__))
cmp_ = json.load(open(os.path.join(HERE, "compare.json")))
ISLANDS = ["hokkaido", "east", "west", "okinawa"]

fig = plt.figure(figsize=(11, 7.5), facecolor="white")
fig.suptitle("介入 #19/#20/#21 既定ON化 — before/after(4島・run_full_powerflow)",
             fontsize=13, fontweight="bold")

ax1 = fig.add_subplot(2, 2, 1)
ax2 = fig.add_subplot(2, 2, 2)
x = range(len(ISLANDS))
w = 0.38
comp_o = [cmp_[i]["old"]["n_components"] for i in ISLANDS]
comp_n = [cmp_[i]["new"]["n_components"] for i in ISLANDS]
bus_o = [cmp_[i]["old"]["n_bus"] for i in ISLANDS]
bus_n = [cmp_[i]["new"]["n_bus"] for i in ISLANDS]

ax1.bar([i - w / 2 for i in x], comp_o, w, label="before(従来既定)", color="#c0392b")
ax1.bar([i + w / 2 for i in x], comp_n, w, label="after(新既定)", color="#27ae60")
ax1.set_yscale("log")
ax1.set_xticks(list(x), ISLANDS)
ax1.set_title("連結成分数(log) — 少ないほど良い")
for i, (o, n) in enumerate(zip(comp_o, comp_n)):
    ax1.text(i - w / 2, o, f"{o:,}", ha="center", va="bottom", fontsize=8)
    ax1.text(i + w / 2, n, f"{n:,}", ha="center", va="bottom", fontsize=8)
ax1.legend(fontsize=9)

ax2.bar([i - w / 2 for i in x], bus_o, w, label="before", color="#7f8c8d")
ax2.bar([i + w / 2 for i in x], bus_n, w, label="after", color="#2980b9")
ax2.set_xticks(list(x), ISLANDS)
ax2.set_title("バス数 — 差=bbox二重抽出の除去分(実バス無損失)")
for i, (o, n) in enumerate(zip(bus_o, bus_n)):
    ax2.text(i + w / 2, n, f"−{o - n:,}", ha="center", va="bottom", fontsize=8,
             color="#2c3e50")
ax2.legend(fontsize=9)

ax3 = fig.add_subplot(2, 1, 2)
ax3.axis("off")
rows = []
for i in ISLANDS:
    o, n = cmp_[i]["old"], cmp_[i]["new"]
    sol_o = "AC" if o["ac_converged"] else ("DC" if o["dc_converged"] else "×")
    sol_n = "AC" if n["ac_converged"] else ("DC" if n["dc_converged"] else "×")
    lo = f"{o['ac_total_loss_mw']:,.0f}" if o["ac_total_loss_mw"] else "—"
    ln = f"{n['ac_total_loss_mw']:,.0f}" if n["ac_total_loss_mw"] else "—"
    rows.append([i, sol_o, sol_n, lo, ln,
                 f"{n['n_dedup_merged']:,}", f"{n['n_edge_dup_removed']:,}"])
tbl = ax3.table(cellText=rows,
                colLabels=["島", "解(before)", "解(after)", "AC損失before[MW]",
                           "AC損失after[MW]", "重複ノード併合", "重複エッジ除去"],
                loc="center", cellLoc="center")
tbl.auto_set_font_size(False)
tbl.set_fontsize(10)
tbl.scale(1, 1.6)
ax3.set_title("解成立の退行なし(4/4) / east損失増=二重計上是正の方向 / west=設計どおりDC",
              fontsize=10, pad=18)

fig.tight_layout(rect=(0, 0, 1, 0.96))
out = os.path.join(HERE, "beforeafter_default_on.png")
fig.savefig(out, dpi=150)
print(out)
