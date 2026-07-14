#!/usr/bin/env python3
"""ワークフロー結果(裁定+検証+捜索)から確定マッチ集合を組み立てる.

採用規則(捏造防止側に倒す):
  - AUTO: 敵対的検証で refuted のものを除外。検証標本に系統的問題があれば全体を止める
    (この判断は呼び出し側=レポートで開示)。
  - 裁定: match_title あり かつ confidence∈{high,medium}。スポット反証で refuted の
    plant は除外。low は不採用(裁定者には「不確実ならnull」と指示済みのため)。
  - 捜索: gem_title あり かつ スポット反証で refuted でない。
  - GEM側一意性: 1ページ=1プラント。競合は (name_eq, -distance) 最強のみ。

使い方: python3 assemble_confirmed.py wf_result.json out_confirmed.jsonl
"""
import json
import os
import sys

S = os.path.dirname(os.path.abspath(__file__))  # 作業dir(データ併置)にコピーして実行する設計


def load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8")]


def main():
    wf = json.load(open(sys.argv[1], encoding="utf-8"))
    out_path = sys.argv[2]

    auto = load_jsonl(f"{S}/match_auto.jsonl")
    adj_in = json.load(open(f"{S}/wf_adjudicate.json", encoding="utf-8"))
    srch_in = json.load(open(f"{S}/wf_search.json", encoding="utf-8"))
    gem = {}
    for line in open(f"{S}/gem_japan_light.jsonl", encoding="utf-8"):
        g = json.loads(line)
        gem[g["title"]] = g

    plant_by_key = {}
    for a in auto:
        pl = a["plant"]
        plant_by_key[f"{pl['region']}:{pl['idx']}"] = pl
    for a in adj_in:
        plant_by_key[a["plant"]["key"]] = dict(
            a["plant"], region=a["plant"]["key"].split(":")[0],
            idx=int(a["plant"]["key"].split(":")[1]))
    for p in srch_in:
        plant_by_key.setdefault(p["key"], dict(
            p, region=p["key"].split(":")[0], idx=int(p["key"].split(":")[1])))

    cand_by_key = {a["plant"]["key"]: {c["title"]: c for c in a["candidates"]}
                   for a in adj_in}

    # --- AUTO(検証反証を除外) ---
    refuted_auto = {v["plant"] for v in wf.get("autoVer", []) if v.get("refuted")}
    n_ver = len(wf.get("autoVer", []))
    n_ref = len(refuted_auto)
    confirmed, dropped = [], []
    for a in auto:
        pl = a["plant"]
        key = f"{pl['region']}:{pl['idx']}"
        if key in refuted_auto:
            dropped.append({"key": key, "why": "auto-refuted"})
            continue
        confirmed.append({"plant": pl, "match": a["match"],
                          "lane": "auto",
                          "verdict_note": None})

    # --- 裁定 ---
    spot_refuted = {s["plant"] for s in wf.get("spots", []) if s.get("refuted")}
    n_adj_acc = n_adj_low = 0
    for v in wf.get("verdicts", []):
        if not v.get("match_title"):
            continue
        if v["match_title"] not in gem:
            dropped.append({"key": v["plant"], "why": "title-not-in-harvest"})
            continue
        if v["plant"] in spot_refuted:
            dropped.append({"key": v["plant"], "why": "spot-refuted"})
            continue
        if v.get("confidence") == "low":
            n_adj_low += 1
            dropped.append({"key": v["plant"], "why": "low-confidence"})
            continue
        pl = plant_by_key.get(v["plant"])
        if not pl:
            continue
        c = cand_by_key.get(v["plant"], {}).get(v["match_title"], {})
        confirmed.append({
            "plant": pl,
            "match": {"title": v["match_title"], "d": c.get("distance_m", "?"),
                      "name_eq": c.get("name_eq", False)},
            "lane": "adjudicated",
            "verdict_note": f"{v.get('confidence')}: {v.get('reason','')[:90]}",
        })
        n_adj_acc += 1

    # --- 捜索 ---
    srch_spot_ref = {s["plant"] for s in wf.get("searchSpots", []) if s.get("refuted")}
    n_srch = 0
    for r in wf.get("searches", []):
        if not r.get("gem_title"):
            continue
        if r["gem_title"] not in gem:
            dropped.append({"key": r["plant"], "why": "searched-title-not-in-harvest"})
            continue
        if r["plant"] in srch_spot_ref:
            dropped.append({"key": r["plant"], "why": "search-spot-refuted"})
            continue
        pl = plant_by_key.get(r["plant"])
        if not pl:
            continue
        confirmed.append({
            "plant": pl,
            "match": {"title": r["gem_title"], "d": "?", "name_eq": False},
            "lane": "searched",
            "verdict_note": f"search: {r.get('note','')[:90]}",
        })
        n_srch += 1

    # --- GEM側一意性 ---
    by_title = {}
    for c in confirmed:
        by_title.setdefault(c["match"]["title"], []).append(c)
    final = []
    for title, lst in by_title.items():
        if len(lst) == 1:
            final.append(lst[0])
            continue
        def rank(c):
            d = c["match"].get("d")
            return (not c["match"].get("name_eq"),
                    c["lane"] != "auto",
                    d if isinstance(d, (int, float)) else 9e9)
        lst.sort(key=rank)
        final.append(lst[0])
        for c in lst[1:]:
            dropped.append({"key": f"{c['plant']['region']}:{c['plant']['idx']}",
                            "why": f"gem-page-conflict:{title}"})

    with open(out_path, "w", encoding="utf-8") as f:
        for c in final:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    lanes = {}
    for c in final:
        lanes[c["lane"]] = lanes.get(c["lane"], 0) + 1
    print(json.dumps({
        "confirmed": len(final), "lanes": lanes,
        "auto_verified": n_ver, "auto_refuted": n_ref,
        "adjudicated_accept": n_adj_acc, "adjudicated_low_dropped": n_adj_low,
        "searched_accept": n_srch, "dropped": len(dropped),
    }, ensure_ascii=False))
    with open(f"{S}/dropped.jsonl", "w", encoding="utf-8") as f:
        for d in dropped:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
