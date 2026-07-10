#!/usr/bin/env python3
"""east電圧精緻化の before/after 要約図(LINE送付用)。"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False
HERE = os.path.dirname(os.path.abspath(__file__))

v0 = json.load(open(os.path.join(HERE, "outliers_east.json")))
v3 = json.load(open(os.path.join(HERE, "outliers_east_V3_both.json")))

fig, axes = plt.subplots(1, 3, figsize=(12, 4.6), facecolor="white")
fig.suptitle("east 電圧外れ値の精緻化 — 大間ポケット解消(#23)・24h軽負荷過補償解消(#20精緻化)",
             fontsize=12, fontweight="bold")

# ① 外れ値バス数
ax = axes[0]
x = [0, 1]
ax.bar([i - 0.18 for i in x], [v0["n_over"], v3["n_over"]], 0.36,
       label="過電圧(>1.1pu)", color="#c0392b")
ax.bar([i + 0.18 for i in x], [v0["n_under"], v3["n_under"]], 0.36,
       label="低電圧(<0.85pu)", color="#2980b9")
ax.set_xticks(x, ["before(現行既定)", "after(+#23/#22)"])
for i, (o, u) in enumerate([(v0["n_over"], v0["n_under"]),
                            (v3["n_over"], v3["n_under"])]):
    ax.text(i - 0.18, o, str(o), ha="center", va="bottom")
    ax.text(i + 0.18, u, str(u), ha="center", va="bottom")
ax.set_title("外れ値バス数(静的正典断面)")
ax.legend(fontsize=9)

# ② vm_max
ax = axes[1]
vals = [v0["meta"]["vm_max"], v3["meta"]["vm_max"], 2.987, 1.768]
labels = ["静的\nbefore", "静的\nafter(#23)", "t=3\nシャント固定", "t=3\n時刻別(#20精緻)"]
colors = ["#c0392b", "#27ae60", "#c0392b", "#27ae60"]
ax.bar(range(4), vals, color=colors)
ax.axhline(1.1, ls="--", c="#7f8c8d", lw=1)
ax.text(3.4, 1.12, "1.1pu", fontsize=8, color="#7f8c8d")
for i, v in enumerate(vals):
    ax.text(i, v, f"{v:.2f}", ha="center", va="bottom")
ax.set_xticks(range(4), labels, fontsize=8)
ax.set_title("vm_max [pu]")

# ③ クラスタの位置(外れ値の地理)
ax = axes[2]
built = json.load(open(os.path.join(HERE, "..", "..", "..", "data", "built",
                                    "all.json")))
name_pos = {}
for n in built["nodes"]:
    nm = n.get("name")
    if nm and nm not in name_pos:
        name_pos[nm] = (n["lon"], n["lat"])
for r in v0["outliers"]:
    p = name_pos.get(r["name"])
    if not p:
        continue
    c = "#c0392b" if r["kind"] == "over" else "#2980b9"
    ax.scatter(*p, c=c, s=26, alpha=0.85)
ax.annotate("大間ポケット\n(過電圧12→0)", xy=(140.9, 41.4), fontsize=9,
            ha="center", color="#c0392b")
ax.annotate("城南チェーン\n(低電圧23=根因確定・出典待ち)", xy=(139.65, 35.3),
            fontsize=9, ha="center", color="#2980b9")
ax.set_xlim(138.2, 142.3)
ax.set_ylim(34.6, 42.2)
ax.set_title("外れ値の地理(2クラスタに完全分解)")
ax.set_aspect(1.2)

fig.tight_layout(rect=(0, 0, 1, 0.93))
out = os.path.join(HERE, "east_refinement_beforeafter.png")
fig.savefig(out, dpi=150)
print(out)
