#!/usr/bin/env python3
"""west断片化の主因図: サイズ分布 / 根本原因分類 / 介入効果."""
import json, os
REPO = "/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid"
os.chdir(REPO)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

P = "docs/reports/probes/west_fragmentation_2026-07-09"
F = json.load(open(f"{P}/west.json"))
L = json.load(open(f"{P}/west_lever.json"))
D = json.load(open(f"{P}/west_dedup.json"))

fig, axes = plt.subplots(1, 3, figsize=(16.5, 5), constrained_layout=True)

# ① サイズ分布
ax = axes[0]
sb = F["size_buckets"]
keys = ["1", "2", "3-5", "6-20", "21-100", ">100"]
vals = [sb[k] for k in keys]
ax.bar(keys, vals, color=["#e57373", "#f5b041", "#f5b041", "#af7ac5", "#888", "#69f0ae"])
ax.set_yscale("symlog")
for i, v in enumerate(vals):
    ax.text(i, v+0.5, str(v), ha="center", fontsize=9)
ax.set_title("① 断片のサイズ分布\n87%が単一バス島・中規模分断網は皆無(21-100=0)",
             fontsize=10)
ax.set_ylabel("成分数(symlog)")
ax.set_xlabel("成分のバス数")

# ② 根本原因分類(≥154kV単一バス変電所島 260件)
ax = axes[1]
cats = L["categories"]
labels = ["T:変圧器/重複\nギャップ", "S:スナップ\nギャップ", "M:OSM欠落"]
vv = [cats.get("T", 0), cats.get("S", 0), cats.get("M", 0)]
cols = ["#5dade2", "#af7ac5", "#e57373"]
w, _t, auto = ax.pie(vv, labels=labels, colors=cols, autopct=lambda p: f"{p*260/100:.0f}件\n({p:.0f}%)",
                     startangle=90, textprops={"fontsize": 9})
ax.set_title("② ≥154kV単一バス変電所島の根本原因\n"
             "99%はデータ欠落でなくbuild接続漏れ", fontsize=10)

# ③ 介入効果
ax = axes[2]
names = ["ベース", "D:重複\ndedup", "Sn:スナップ\n150m", "D+Tr+Sn"]
ncomp = [D["base_n_comp"], D["D_dedup"]["n_comp"],
         D["Sn_snap150m"]["n_comp"], D["D+Tr+Sn"]["n_comp"]]
cols2 = ["#888", "#69f0ae", "#5dade2", "#3a9d6a"]
bars = ax.bar(names, ncomp, color=cols2)
for b, v in zip(bars, ncomp):
    ax.text(b.get_x()+b.get_width()/2, v+40, str(v), ha="center", fontsize=10,
            fontweight="bold")
ax.set_ylabel("成分数")
ax.axhline(D["base_n_comp"], ls="--", color="#888", lw=0.7)
ax.set_title("③ 介入の成分削減効果\nD(重複dedup)単独で2531→544(−78%)・"
             f"D+Tr+Snで主成分{D['D+Tr+Sn']['main_frac']*100:.0f}%",
             fontsize=10)

fig.suptitle("west 断片化の主因 — bbox重なりの重複ノード(B案未実装が残した最後のアーティファクト)",
             fontsize=13)
out = "docs/reports/figs/west_fragmentation_2026-07-09.png"
fig.savefig(out, dpi=140)
print(f"wrote {out}")
