#!/usr/bin/env python3
"""継続ワークフローの入力一式を構築する(1-C GEM充填・復旧).

前提: gem_japan_pages.jsonl(再収穫済み)・cached_verdicts.json・cached_spots.json が S に存在。
手順: match(決定的) → light版 → wf入力3系統 → 分割
  - wf_adj_rem/  : 曖昧のうちキャッシュ裁定に無い plant のみ(25件/バッチ)
  - wf_spot/     : キャッシュacceptのうち未スポット分(3件/バッチ・context付き)
  - wf_ver/      : AUTO major全+solar決定的標本30(単票)
  - wf_srch/     : 未マッチmajor(10件/バッチ)
最後にドリフト(前回結果との突合差)を報告する。
"""
import hashlib
import json
import os
import subprocess
import sys

S = os.path.dirname(os.path.abspath(__file__))
REPO = "/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid"


def load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8")]


# ---- 1. 突合(決定的) ----
r = subprocess.run(
    [sys.executable, f"{S}/match_gem_placeholders.py",
     f"{S}/gem_japan_pages.jsonl", REPO, f"{S}/match"],
    capture_output=True, text=True, cwd=S)
print(r.stdout, r.stderr)
assert r.returncode == 0, "match failed"

# ---- 2. light版(loc抽出・wikitext除去) ----
import re
LOC_RE = re.compile(r"\|\s*([^|\n]*?(?:City|Prefecture|County|Town|Village|District)[^|\n]*?, Japan)")
out = []
for line in open(f"{S}/gem_japan_pages.jsonl", encoding="utf-8"):
    rec = json.loads(line)
    m = LOC_RE.search(rec.get("wikitext") or "")
    rec["loc"] = m.group(1).strip() if m else None
    rec.pop("wikitext", None)
    out.append(rec)
with open(f"{S}/gem_japan_light.jsonl", "w", encoding="utf-8") as f:
    for rec in out:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
print("loc抽出:", sum(1 for rec in out if rec["loc"]), "/", len(out))

# ---- 3. wf入力3系統(前回と同一ロジック) ----
gem = {}
for line in open(f"{S}/gem_japan_light.jsonl", encoding="utf-8"):
    rec = json.loads(line)
    gem[rec["title"]] = rec


def gem_view(title):
    g = gem[title]
    ops = [u for u in g["units"] if str(u.get("status", "")).lower() == "operating" and u.get("cap_mw")]
    return {"title": g["title"], "ja_name": g.get("ja_name"), "loc": g.get("loc"),
            "category": g["category"], "lat": g["lat"], "lon": g["lon"],
            "url": "https://www.gem.wiki/" + g["title"].replace(" ", "_"),
            "operating_units": [{"name": u["name"], "cap_raw": u["cap_raw"]} for u in ops],
            "operating_total_mw": round(sum(u["cap_mw"] for u in ops), 2),
            "other_status": sorted({str(u.get("status")) for u in g["units"]
                                    if str(u.get("status", "")).lower() != "operating"})}


amb = load_jsonl(f"{S}/match_ambig.jsonl")
adj = []
for a in amb:
    pl = a["plant"]
    adj.append({
        "plant": {"key": f"{pl['region']}:{pl['idx']}", "name": pl["name"],
                  "fuel": pl["fuel"], "lat": round(pl["lat"], 5), "lon": round(pl["lon"], 5)},
        "note": a.get("note"),
        "candidates": [dict(gem_view(c["title"]), distance_m=c["d"], name_eq=c["name_eq"])
                       for c in a["cands"]],
    })
json.dump(adj, open(f"{S}/wf_adjudicate.json", "w"), ensure_ascii=False)

auto = load_jsonl(f"{S}/match_auto.jsonl")
ver = []
for a in auto:
    pl = a["plant"]
    ver.append({
        "plant": {"key": f"{pl['region']}:{pl['idx']}", "name": pl["name"],
                  "fuel": pl["fuel"], "lat": round(pl["lat"], 5), "lon": round(pl["lon"], 5)},
        "match": dict(gem_view(a["match"]["title"]), distance_m=a["match"]["d"],
                      name_eq=a["match"]["name_eq"]),
    })
json.dump(ver, open(f"{S}/wf_verify_auto.json", "w"), ensure_ascii=False)

unm = load_jsonl(f"{S}/match_unmatched_major.jsonl")
json.dump([{"key": f"{p['region']}:{p['idx']}", "name": p["name"], "fuel": p["fuel"],
            "lat": round(p["lat"], 5), "lon": round(p["lon"], 5)} for p in unm],
          open(f"{S}/wf_search.json", "w"), ensure_ascii=False)
print("adjudicate:", len(adj), "verify_auto:", len(ver), "search:", len(unm))

# ---- 4. 分割 ----
cached_verdicts = json.load(open(f"{S}/cached_verdicts.json", encoding="utf-8"))
cached_spots = json.load(open(f"{S}/cached_spots.json", encoding="utf-8"))
cached_keys = {v["plant"] for v in cached_verdicts}
spotted_keys = {s["plant"] for s in cached_spots}

# 4a. 残り裁定バッチ
rem = [a for a in adj if a["plant"]["key"] not in cached_keys]
os.makedirs(f"{S}/wf_adj_rem", exist_ok=True)
B = 25
n_rem = 0
for i in range(0, len(rem), B):
    with open(f"{S}/wf_adj_rem/batch_{i//B:03d}.json", "w", encoding="utf-8") as f:
        json.dump(rem[i:i + B], f, ensure_ascii=False, indent=1)
    n_rem += 1

# 4b. 未スポットaccept(キャッシュ裁定のうち match_title あり・high/medium・未スポット)
adj_by_key = {a["plant"]["key"]: a for a in adj}
unspotted = [v for v in cached_verdicts
             if v.get("match_title") and v.get("confidence") in ("high", "medium")
             and v["plant"] not in spotted_keys]
os.makedirs(f"{S}/wf_spot", exist_ok=True)
SB = 3
n_spot = 0
no_ctx = 0
for i in range(0, len(unspotted), SB):
    grp = unspotted[i:i + SB]
    ctx = []
    for v in grp:
        a = adj_by_key.get(v["plant"])
        if a:
            ctx.append(a)
        else:
            no_ctx += 1
            pl_key = v["plant"]
            ctx.append({"plant": {"key": pl_key},
                        "note": "regenerated-ambig-drift: 候補文脈なし(前回裁定時の曖昧集合にのみ存在)",
                        "candidates": []})
    with open(f"{S}/wf_spot/batch_{n_spot:03d}.json", "w", encoding="utf-8") as f:
        json.dump({"targets": grp, "context": ctx}, f, ensure_ascii=False, indent=1)
    n_spot += 1

# 4c. AUTO検証単票(前回と同一の決定的標本)
majors = [i for i, v in enumerate(ver) if v["plant"]["fuel"] != "solar"]
solar = [i for i, v in enumerate(ver) if v["plant"]["fuel"] == "solar"]
solar_sample = sorted(solar, key=lambda i: hashlib.sha1(str(i).encode()).hexdigest())[:30]
idx = majors + solar_sample
os.makedirs(f"{S}/wf_ver", exist_ok=True)
for k, i in enumerate(idx):
    with open(f"{S}/wf_ver/item_{k:03d}.json", "w", encoding="utf-8") as f:
        json.dump(ver[i], f, ensure_ascii=False, indent=1)
json.dump(idx, open(f"{S}/wf_ver/index_map.json", "w"))

# 4d. 捜索バッチ
srch = json.load(open(f"{S}/wf_search.json", encoding="utf-8"))
os.makedirs(f"{S}/wf_srch", exist_ok=True)
SRB = 10
n_srch = 0
for i in range(0, len(srch), SRB):
    with open(f"{S}/wf_srch/batch_{i//SRB:03d}.json", "w", encoding="utf-8") as f:
        json.dump(srch[i:i + SRB], f, ensure_ascii=False, indent=1)
    n_srch += 1

# ---- 5. ドリフト報告 ----
adj_keys = {a["plant"]["key"] for a in adj}
stale = cached_keys - adj_keys          # キャッシュにあるが今回の曖昧集合に無い
report = {
    "ambig_now": len(adj), "cached_verdicts": len(cached_verdicts),
    "rem_plants": len(rem), "n_rem_batches": n_rem,
    "unspotted_accepts": len(unspotted), "n_spot_batches": n_spot,
    "spot_context_missing": no_ctx,
    "auto_now": len(ver), "n_ver_items": len(idx),
    "search_now": len(srch), "n_srch_batches": n_srch,
    "drift_stale_cached": len(stale),
}
print(json.dumps(report, ensure_ascii=False, indent=1))
json.dump(report, open(f"{S}/continuation_meta.json", "w"))
json.dump(sorted(stale), open(f"{S}/drift_stale_cached.json", "w"))
