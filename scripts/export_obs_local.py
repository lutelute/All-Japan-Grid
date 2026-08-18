#!/usr/bin/env python3
"""線クリック用の観測実績オーバーレイ(年統計=集計値)を生成する.

出力: docs/data/flow_map/obs_local.json — 公開(2026-08-18オーナー判断)。
収録は年統計3値(平均/p95/最大)のみ=集計値。生の時系列(30分値×8760)は
従来どおり非公開。出典=各一般送配電事業者の系統情報公表(潮流実績)。
"""
import csv, json, re, unicodedata
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
OBS = ROOT / "data/external/system_disclosure/normalized/line_observations.csv"
def norm(s):
    s = unicodedata.normalize("NFKC", str(s or ""))
    return re.sub(r"[\s・()（）]", "", s)
out = {}
with OBS.open(encoding="utf-8") as f:
    for r in csv.DictReader(f):
        k = norm(r.get("name"))
        if not k: continue
        try:
            mean = float(r.get("flow_mean_mw") or "nan")
            p95 = float(r.get("flow_p95_abs_mw") or "nan")
            mx = float(r.get("flow_max_abs_mw") or "nan")
        except ValueError:
            continue
        if p95 != p95: continue
        rec = out.get(k)
        if rec is None or p95 > rec["p95"]:
            out[k] = {"util": r.get("utility"), "kv": r.get("voltage_kv"),
                      "mean": None if mean != mean else round(mean, 1),
                      "p95": round(p95, 1),
                      "max": None if mx != mx else round(mx, 1),
                      "n": r.get("n_obs")}
dst = ROOT / "docs/data/flow_map/obs_local.json"
dst.write_text(json.dumps({"note": "観測実績の年統計(集計値)。出典=各一般送配電事業者 系統情報公表(潮流実績・2024年度)。生の時系列は収録しない",
                           "lines": out}, ensure_ascii=False))
print(f"obs_local: {len(out)}線 -> {dst.name} (untracked)")
