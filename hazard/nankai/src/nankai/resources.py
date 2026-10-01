"""復旧の資源勘定: 人・日(作業班×人数×日数)、資材(ジョブ種別×件数)、電源車(孤立需要÷1台容量)を時系列で積む。"""
from __future__ import annotations
import os
import numpy as np
import pandas as pd
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.abspath(os.path.join(HERE, "..", "..", "config"))


def load_resource_params() -> dict:
    return yaml.safe_load(open(os.path.join(CONFIG, "resources_default.yaml"), encoding="utf-8"))


def job_kind(job: dict, site_ds, site_cause, line_cause) -> str:
    kind, i = job["id"]
    if kind == "s":
        return "substation:tsunami" if site_cause[i] == 2 else ("substation:ds4" if site_ds[i] >= 4 else "substation:ds3")
    c = int(line_cause[i]); return "line:" + {1: "collapse", 2: "tsunami", 3: "short"}.get(c, "collapse")


def ledger(sim, assign: list, site_ds, site_cause, line_cause, isolated_load_by_t: dict, days=None, params: dict | None = None) -> dict:
    """assign: _schedule_logged の記録 [{id, zone, crew, start, dur, end, aid}]。isolated_load_by_t: {t: {zone: MW}}。"""
    P = params or load_resource_params(); days = np.array(days if days is not None else [0, 1, 2, 3, 4, 5, 7, 10, 14, 21, 30, 45, 60, 90], float)
    ppc = float(P["crew"]["persons_per_crew"])
    zones = sorted(set(a["zone"] for a in assign)) or ["all"]
    # 人・日: 各日に稼働している班数 × 人数(その日に進行中のジョブ数)
    persons = {z: np.zeros(len(days)) for z in zones}; cum = {z: np.zeros(len(days)) for z in zones}
    for a in assign:
        for k, t in enumerate(days):
            if a["start"] <= t < a["end"]:
                persons[a["zone"]][k] += ppc
            cum[a["zone"]][k] += ppc * max(0.0, min(t, a["end"]) - a["start"])
    # 資材
    mat = {}
    for a in assign:
        jk = job_kind(a, site_ds, site_cause, line_cause); grp, sub = jk.split(":")
        for m, q in P["materials"][grp][sub].items():
            mat[m] = mat.get(m, 0.0) + float(q)
    # 主変圧器: 予備在庫との比較
    tf = mat.get("主変圧器(台)", 0.0); stock = sum(P["stock"]["主変圧器(台)"].get(z, 0) for z in zones)
    # 電源車
    gt = P["generator_trucks"]; cap = float(gt["capacity_mw"]); fleet = {z: gt["fleet"].get(z, 0) for z in zones}
    trucks_need = {}; trucks_avail = {}
    for k, t in enumerate(days):
        iso = isolated_load_by_t.get(float(t), {})
        for z in zones:
            trucks_need.setdefault(z, np.zeros(len(days)))[k] = iso.get(z, 0.0) / cap
            trucks_avail.setdefault(z, np.zeros(len(days)))[k] = fleet[z] * (float(gt["mutual_aid_factor"]) if t >= float(gt["mutual_aid_start_d"]) else 1.0)
    return {"days": days, "zones": zones, "persons": persons, "person_days_cum": cum, "materials": mat, "transformer_need": tf, "transformer_stock": stock,
            "trucks_need": trucks_need, "trucks_avail": trucks_avail, "n_jobs": len(assign), "person_days_total": float(sum(ppc * a["dur"] for a in assign))}


def plot_ledger(L: dict, out_png: str, title="復旧の資源勘定(1 サンプル)"):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    from . import maps  # フォント設定
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2), dpi=120)
    d = L["days"]; ax = axes[0]; bottom = np.zeros(len(d))
    for z in L["zones"]:
        ax.bar(range(len(d)), L["persons"][z], bottom=bottom, label=z); bottom += L["persons"][z]
    ax.set_xticks(range(len(d))); ax.set_xticklabels([f"{x:g}" for x in d], fontsize=8); ax.set_xlabel("経過日数"); ax.set_ylabel("稼働人数 [人/日]"); ax.set_title(f"作業員(変電所・送電) 計 {L['person_days_total']:,.0f} 人・日", fontsize=10); ax.legend(fontsize=7); ax.grid(axis="y", alpha=0.3)
    ax = axes[1]
    for z in L["zones"]:
        ax.plot(d, L["trucks_need"][z], marker="o", ms=3, label=f"{z} 必要")
        ax.plot(d, L["trucks_avail"][z], ls="--", lw=1, color=ax.lines[-1].get_color())
    ax.set_xscale("symlog", linthresh=1); ax.set_xlabel("経過日数"); ax.set_ylabel("台"); ax.set_title("電源車: 上流孤立の需要÷0.5MW(実線) vs 保有+応援(破線)", fontsize=10); ax.legend(fontsize=7); ax.grid(alpha=0.3)
    ax = axes[2]; items = sorted(L["materials"].items(), key=lambda kv: -kv[1])[:8]
    ax.barh([k for k, _ in items][::-1], [v for _, v in items][::-1], color="#8172b2"); ax.set_title(f"資材(件数×単位当たり; 主変圧器 {L['transformer_need']:.0f} 台 / 予備 {L['transformer_stock']} 台)", fontsize=10); ax.grid(axis="x", alpha=0.3)
    for i, (k, v) in enumerate(items[::-1]):
        ax.text(v, i, f" {v:,.0f}", va="center", fontsize=8)
    fig.suptitle(title, fontsize=11); fig.tight_layout(); fig.savefig(out_png); plt.close(fig)
