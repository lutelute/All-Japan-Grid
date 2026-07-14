#!/usr/bin/env python3
"""キャッシュ済み結果(前回ラン)と継続ワークフロー結果を合算し wf_result.json を作る.

使い方: python3 merge_results.py continuation_result.json wf_result.json
継続結果 = {verdicts, spots, autoVer, searches, searchSpots}(新規分のみ)
"""
import json
import os
import sys

S = os.path.dirname(os.path.abspath(__file__))

cont = json.load(open(sys.argv[1], encoding="utf-8"))
cached_verdicts = json.load(open(f"{S}/cached_verdicts.json", encoding="utf-8"))
cached_spots = json.load(open(f"{S}/cached_spots.json", encoding="utf-8"))

# 裁定: キャッシュ優先(重複keyは継続分を捨てる=キャッシュが正)
seen = {v["plant"] for v in cached_verdicts}
new_v = [v for v in cont.get("verdicts", []) if v["plant"] not in seen]
dup_v = len(cont.get("verdicts", [])) - len(new_v)
verdicts = cached_verdicts + new_v

# スポット: 単純合算(重複plantは refuted=true を優先=保守側)
by_plant = {}
for s in cached_spots + list(cont.get("spots", [])):
    k = s["plant"]
    if k not in by_plant or (s.get("refuted") and not by_plant[k].get("refuted")):
        by_plant[k] = s
spots = list(by_plant.values())

result = {
    "verdicts": verdicts,
    "spots": spots,
    "autoVer": cont.get("autoVer", []),
    "searches": cont.get("searches", []),
    "searchSpots": cont.get("searchSpots", []),
}
json.dump(result, open(sys.argv[2], "w"), ensure_ascii=False)
acc = [v for v in verdicts if v.get("match_title")]
print(json.dumps({
    "verdicts": len(verdicts), "accepts": len(acc),
    "dup_verdicts_dropped": dup_v,
    "spots": len(spots), "spot_refuted": sum(1 for s in spots if s.get("refuted")),
    "autoVer": len(result["autoVer"]),
    "autoVer_refuted": sum(1 for v in result["autoVer"] if v.get("refuted")),
    "searches": len(result["searches"]),
    "search_hits": sum(1 for s in result["searches"] if s.get("gem_title")),
    "searchSpots": len(result["searchSpots"]),
}, ensure_ascii=False))
