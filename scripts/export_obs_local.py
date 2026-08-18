#!/usr/bin/env python3
"""線クリック用の観測実績オーバーレイ(ローカル限定・非公開)を生成する.

出力: docs/data/flow_map/obs_local.json — **untracked(.gitignore)**。
Pagesにはpushされないため、ローカルで開いたときだけ実績が表示される。
観測生値(All-Rights-Reserved)を公開配信しない方針とクリック表示要望の両立。
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
dst.write_text(json.dumps({"note": "ローカル限定・観測実績(非公開データ)。untracked",
                           "lines": out}, ensure_ascii=False))
print(f"obs_local: {len(out)}線 -> {dst.name} (untracked)")
