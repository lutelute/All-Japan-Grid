#!/usr/bin/env python3
"""線種標準値の較正（介入#31）が系統全体に与える影響を before/after で示す。

較正値は「公表 X ÷ モデルの実線形長」の階級中央値なので、較正後は
**公表値との比が定義上 1 に寄る**。それ自体は自明なので、ここで問うのは
「系統全体のリアクタンス総量がどれだけ動くか」＝潮流に効く量。

before: 標準 x × 実線形長 ÷ par   after: 較正 x × 実線形長 ÷ par
（較正値を持たない階級は before=after。地中線は線名で除外）

出力: docs/reports/figs/calibration_before_after.png
"""
from __future__ import annotations
import json, math
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
FIGS = ROOT / "docs/reports/figs"
for _f in ("Hiragino Sans", "Hiragino Kaku Gothic ProN", "YuGothic"):
    plt.rcParams["font.family"] = _f
    break
plt.rcParams["axes.unicode_minus"] = False
BG, C_BEF, C_AFT = "#faf8f1", "#b3812f", "#1f9e8a"


def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    return 6371*2*math.asin(math.sqrt(math.sin((la2-la1)/2)**2 +
        math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2))


def path_km(e):
    p = e.get("path") or [e["a"], e["b"]]
    return sum(hav(p[i], p[i+1]) for i in range(len(p)-1))


def nearest_kv(kv, classes):
    return min(classes, key=lambda c: abs(c - kv)) if kv else None


def main():
    lt = yaml.safe_load((ROOT/"config/line_types.yaml").read_text(encoding="utf-8"))
    classes = sorted(int(k) for k in lt if str(k).isdigit())
    ci = json.loads((ROOT/"docs/reports/line_type_calibration_ci.json").read_text(encoding="utf-8"))
    sig = {r["voltage_kv"]: r["significant"] for r in ci["by_voltage"]}
    built = json.loads((ROOT/"docs/data/built/all.json").read_text(encoding="utf-8"))

    agg = {}
    for e in built["edges"]:
        kv = e.get("kv") or 0
        c = nearest_kv(kv, classes)
        if not c:
            continue
        if "地中" in str(e.get("name") or ""):
            continue
        L = path_km(e)
        if L <= 0:
            continue
        par = max(int(e.get("par") or 1), 1)
        std = lt[c]["x_ohm_per_km"]
        cal = (lt[c].get("calibrated") or {}).get("x_ohm_per_km", std)
        # 較正は「x が有意に過小」と判定された階級のみ適用する（CIが1を含む階級は据え置き）
        if "x" not in sig.get(c, []):
            cal = std
        d = agg.setdefault(c, {"km": 0.0, "bef": 0.0, "aft": 0.0, "n": 0})
        d["km"] += L; d["n"] += 1
        d["bef"] += std * L / par
        d["aft"] += cal * L / par

    ks = sorted(agg)
    bef = np.array([agg[k]["bef"] for k in ks])
    aft = np.array([agg[k]["aft"] for k in ks])
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12.8, 5.6), facecolor=BG,
                                 gridspec_kw={"width_ratios": [1.15, 1]})
    for a in (a1, a2):
        a.set_facecolor("#fffdf6")
        for s in a.spines.values():
            s.set_color("#dcd8cc")
    y = np.arange(len(ks))
    a1.barh(y - .2, bef, height=.38, color=C_BEF, label="before（標準値）")
    a1.barh(y + .2, aft, height=.38, color=C_AFT, label="after（較正値・有意な階級のみ）")
    a1.set_yticks(y)
    a1.set_yticklabels([f"{k} kV\n({agg[k]['n']:,}本 / {agg[k]['km']:,.0f}km)" for k in ks],
                       fontsize=9)
    for i, (b, af) in enumerate(zip(bef, aft)):
        if af > b * 1.001:
            a1.text(af * 1.01, i + .2, f"+{(af/b-1)*100:.0f}%", va="center",
                    fontsize=9.5, color="#126b5c", fontweight="bold")
    a1.set_xlabel("系統全体のリアクタンス総和 Σ x·ℓ/par [Ω]", fontsize=10.5)
    a1.legend(fontsize=9.5, frameon=False, loc="lower right")
    a1.grid(axis="x", alpha=.22, color="#dcd8cc")
    tb, ta = bef.sum(), aft.sum()
    a1.set_title(f"before / after — 較正で系統全体の X は {(ta/tb-1)*100:+.1f}%\n"
                 f"（{tb:,.0f} → {ta:,.0f} Ω・地中線は除外）",
                 fontsize=12, loc="left", color="#1a1a17", pad=10)

    labs, mids, los, his, cols = [], [], [], [], []
    for r in ci["by_voltage"]:
        for kind, key in (("x", "x_ratio"), ("r", "r_ratio")):
            labs.append(f"{r['voltage_kv']}kV {kind} (n={r['n']})")
            mids.append(r[f"{key}_median"])
            los.append(r[f"{key}_ci95"][0]); his.append(r[f"{key}_ci95"][1])
            cols.append("#cf4f5f" if kind in r["significant"] else "#9aa5ae")
    yy = np.arange(len(labs))
    a2.errorbar(mids, yy, xerr=[np.array(mids)-np.array(los), np.array(his)-np.array(mids)],
                fmt="o", ms=5, lw=1.4, ecolor="#c8d3dd", mfc="white", mec="none", zorder=2)
    a2.scatter(mids, yy, s=44, c=cols, zorder=3, edgecolor="white", lw=.7)
    a2.axvline(1.0, color="#52504a", ls="--", lw=1.4, zorder=1)
    a2.set_yticks(yy); a2.set_yticklabels(labs, fontsize=8)
    a2.invert_yaxis()
    a2.set_xlabel("実効値 / 標準値（点＝中央値、線＝ブートストラップ95%CI）", fontsize=10)
    a2.grid(axis="x", alpha=.22, color="#dcd8cc")
    a2.set_title("赤＝CI が 1 を含まない（有意に過小）\n"
                 "灰＝1 を含む（標準値と差があるとは言えない）",
                 fontsize=12, loc="left", color="#1a1a17", pad=10)
    fig.tight_layout()
    out = FIGS/"calibration_before_after.png"
    fig.savefig(out, dpi=180, facecolor=BG); plt.close(fig)
    print(f"  {out.name}  総和 {tb:,.0f} → {ta:,.0f} Ω ({(ta/tb-1)*100:+.2f}%)")
    for k in ks:
        d = agg[k]
        if d["aft"] > d["bef"] * 1.001:
            print(f"    {k}kV: {d['n']:,}本 {d['km']:,.0f}km  {d['bef']:,.0f} → {d['aft']:,.0f} Ω "
                  f"({(d['aft']/d['bef']-1)*100:+.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
