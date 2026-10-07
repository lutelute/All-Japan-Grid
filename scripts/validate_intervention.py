"""モデルの介入の妥当性を、独立した公表資料と潮流の実績で採点する(介入 #48 を最初の対象に)。

    # 1. 介入なし・ありで潮流を解き、線と変圧器の潮流を書き出す
    PYTHONPATH=. .venv/bin/python scripts/run_full_powerflow_from_db.py --dump-flows --output-dir OFF
    PYTHONPATH=. .venv/bin/python scripts/run_full_powerflow_from_db.py --dump-flows --observed-trafos --output-dir ON
    # 2. 採点
    PYTHONPATH=. .venv/bin/python scripts/validate_intervention.py --off OFF --on ON --out report.json

判断の材料を 3 つに分ける。どれか 1 つだけで採否を決めない。

1. **構造(どの電圧の組に変圧器があるか)を、OSM と独立の公表資料で採点する。**
   正解 = 東北電力ネットワークの系統情報公表の変圧器(``tohoku_tr_registry.csv``、201 組)と、
   出典 DB(``data/transformer_sources.jsonl``)の既設の銘板で、同じ引用文に高圧側と低圧側が書かれた組。
   予測 = 梯子(電圧階級の隣どうし)と、介入 #48(観測した組を先に張り残りを梯子)。
   変電所に両端の階級があって、どちらの予測でも作れる組だけを数える(階級が無い組は別の問題)。
   正解の資料は全台を載せているとは限らないので、予測にあって正解に無い組は「誤り」でなく「裏付け無し」と数える。
2. **潮流を、公表の潮流実績(年統計)と比べる。** 照合は ``scripts/export_obs_compare.py`` と同じ
   (観測の線 → モデルの線の経路)。モデルは 1 断面なので、観測の p95(絶対値)との比を見る。
   全線と、結び直した変電所から 15 km 以内の線に分け、比の対数誤差・×2 以内の割合・向きの一致を前後で並べ、
   線ごとに近づいた/離れたを数える。
3. **物理の健全性**: 収束・電圧・損失・過負荷(100% 超)の線と変圧器の数。

観測と計算は混ぜない(docs/OBSERVED_VS_DERIVED.md)。観測の生の時系列は読まない(年統計だけ)。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REGISTRY = ROOT / "data/external/system_disclosure/normalized/tohoku_tr_registry.csv"
SOURCES = ROOT / "data/transformer_sources.jsonl"
NEAR_KM = 15.0


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKC", str(name or ""))
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"\(.*?\)", "", s)
    return s.replace("九州電力", "")


def hav_km(la1, lo1, la2, lo2) -> float:
    p1, p2, dl, dn = map(math.radians, (la1, la2, la2 - la1, lo2 - lo1))
    a = math.sin(dl / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dn / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(a))


# ------------------------------------------------------------------ 1. 構造
def truth_pairs() -> dict:
    """(region, 正規化した変電所名) → {(hv, lv)}: 公表資料と出典 DB の既設の変圧器の組。"""
    out = defaultdict(set)
    src = defaultdict(set)
    if REGISTRY.exists():
        for r in csv.DictReader(open(REGISTRY, encoding="utf-8")):
            hv, lv = sorted((int(float(r["kv1"])), int(float(r["kv2"]))), reverse=True)
            out[("tohoku", norm(r["name"]))].add((hv, lv))
            src[("tohoku", norm(r["name"]))].add("tohoku_tr_registry")
    by_quote = defaultdict(dict)
    for line in open(SOURCES, encoding="utf-8"):
        r = json.loads(line)
        if r.get("status") != "existing" or r.get("field") not in ("hv_kv", "lv_kv"):
            continue
        by_quote[(r["site_key"], r["quote"])][r["field"]] = r["value"]
    for (site_key, _q), f in by_quote.items():
        if "hv_kv" in f and "lv_kv" in f:
            region, name = site_key.split(":", 1)
            key = (region, norm(name))
            out[key].add((int(float(f["hv_kv"])), int(float(f["lv_kv"]))))
            src[key].add("transformer_sources")
    return {k: {"pairs": v, "sources": sorted(src[k])} for k, v in out.items()}


def score_topology(structures_dir: Path) -> dict:
    from src.model.site_transformers import link_levels
    from src.model.site_transformers import by_structure_site
    observed = by_structure_site()
    truth = truth_pairs()
    sites, seen = [], set()
    for p in sorted(structures_dir.glob("*.json")):
        if p.name == "summary.json" or "_site_" in p.name:
            continue
        d = json.loads(p.read_text())
        for s in d["structures"]:
            key = (d["region"], norm(s["site"]["name"]))
            if key not in truth or key in seen:
                continue
            seen.add(key)
            levels = sorted({int(v["nominal_kv"]) for v in s["voltage_levels"] if v["nominal_kv"]}, reverse=True)
            ladder = set(zip(levels, levels[1:]))
            obs = observed.get(s["site"]["site_id"])
            linked = {(int(h), int(l)) for h, l, _ in link_levels(levels, obs)} if obs else ladder
            gold = {pr for pr in truth[key]["pairs"] if pr[0] in levels and pr[1] in levels}
            if not gold:
                continue
            sites.append({"region": d["region"], "name": s["site"]["name"], "levels": levels,
                          "truth": sorted(gold, reverse=True), "sources": truth[key]["sources"],
                          "ladder": sorted(ladder, reverse=True), "observed_first": sorted(linked, reverse=True),
                          "has_osm_observation": bool(obs),
                          "hit_ladder": len(gold & ladder), "hit_observed_first": len(gold & linked),
                          "unsupported_ladder": len(ladder - truth[key]["pairs"]),
                          "unsupported_observed_first": len(linked - truth[key]["pairs"])})

    def summ(rows):
        n = sum(len(r["truth"]) for r in rows)
        if not n:
            return None
        return {"sites": len(rows), "truth_pairs": n,
                "recall_ladder": round(sum(r["hit_ladder"] for r in rows) / n, 3),
                "recall_observed_first": round(sum(r["hit_observed_first"] for r in rows) / n, 3),
                "unsupported_ladder": sum(r["unsupported_ladder"] for r in rows),
                "unsupported_observed_first": sum(r["unsupported_observed_first"] for r in rows)}
    differ = [r for r in sites if r["ladder"] != r["observed_first"]]
    return {"all": summ(sites), "where_they_differ": summ(differ),
            "with_osm_observation": summ([r for r in sites if r["has_osm_observation"]]),
            "sites_where_they_differ": differ}


# ------------------------------------------------------------------ 2. 潮流と実績
def matched_lines(cache: Path | None) -> list:
    """観測の線 → モデルの線の経路(export_obs_compare と同じ照合)。重いのでキャッシュする。"""
    if cache and cache.exists():
        return json.loads(cache.read_text())
    from scripts.export_obs_compare import load_obs, match_all
    built = json.loads((ROOT / "docs/data/built/all.json").read_text())
    matched, _ = match_all(load_obs(), built)
    out = [{"util": m["util"], "name": m["name"], "kv": m["kv"], "from": m["from"], "to": m["to"],
            "island": m["island"], "conf": m["conf"], "obs": m["obs"], "n_circ_obs": m.get("n_circ_obs"),
            "seg0": [[k, sg, par] for k, sg, par in m["segs"][0]]} for m in matched]
    if cache:
        cache.write_text(json.dumps(out, ensure_ascii=False))
    return out


def model_value(m: dict, lines: dict):
    """観測の向きに揃えた、起点側の最初の区間の潮流(平行線は合算・回線ごとの観測は按分)。"""
    tot_par = sum(par for _, _, par in m["seg0"])
    scale = (m["n_circ_obs"] / tot_par) if m.get("n_circ_obs") and tot_par > m["n_circ_obs"] else 1.0
    v, ok, pos = 0.0, False, None
    for k, sg, _ in m["seg0"]:
        row = lines.get(k)
        if row is None:
            continue
        v += sg * row[0]
        ok = True
        pos = pos or row[2:6]
    return (v * scale if ok else None), pos


def sign_test(k_better: int, k_worse: int) -> float | None:
    """近づいた/離れた本数の両側の符号検定(二項・p=0.5)。変化なしは数えない。"""
    n = k_better + k_worse
    if not n:
        return None
    k = min(k_better, k_worse)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return round(min(1.0, 2 * p), 4)


def score_flows(off: dict, on: dict, matched: list, sites48: list) -> dict:
    rows = []
    for m in matched:
        isl = m["island"]
        if isl not in off or isl not in on or not m["obs"].get("p95"):
            continue
        a, pos = model_value(m, off[isl]["lines"])
        b, _ = model_value(m, on[isl]["lines"])
        if a is None or b is None or pos is None:
            continue
        near = min((hav_km(pos[0], pos[1], s["lat"], s["lon"]) for s in sites48 if s["island"] == isl),
                   default=1e9)
        rows.append({"util": m["util"], "line": m["name"], "kv": m["kv"], "from": m["from"], "to": m["to"],
                     "island": isl, "conf": m["conf"], "obs_p95": m["obs"]["p95"], "obs_mean": m["obs"]["mean"],
                     "off_mw": round(a, 1), "on_mw": round(b, 1), "near_km": round(near, 1)})
    # 同じ線の年度ごとの記録(公表は年度別)は 1 本にまとめ、観測の年統計は平均する
    merged = {}
    for r in rows:
        k = (r["util"], norm(r["line"]), norm(r["from"]), norm(r["to"]), r["kv"])
        if k in merged:
            g = merged[k]
            g["_n"] += 1
            g["obs_p95"] += r["obs_p95"]
            g["obs_mean"] += r["obs_mean"]
        else:
            merged[k] = {**r, "_n": 1}
    rows = []
    for g in merged.values():
        g["obs_p95"] = round(g["obs_p95"] / g["_n"], 1)
        g["obs_mean"] = round(g["obs_mean"] / g["_n"], 1)
        g["n_years"] = g.pop("_n")
        rows.append(g)

    def err(x, obs):
        return abs(math.log2(max(abs(x), 0.5) / obs))

    def summ(rs):
        if not rs:
            return None
        out = {"n": len(rs)}
        for tag in ("off", "on"):
            e = sorted(err(r[f"{tag}_mw"], r["obs_p95"]) for r in rs)
            dd = [(r[f"{tag}_mw"] > 0) == (r["obs_mean"] > 0) for r in rs
                  if r["conf"] != "C" and abs(r["obs_mean"]) >= 0.1 * r["obs_p95"] and abs(r[f"{tag}_mw"]) >= 1]
            out[tag] = {"median_abs_log2_ratio": round(e[len(e) // 2], 3),
                        "within_x2": round(sum(1 for x in e if x <= 1) / len(e), 3),
                        "dir_agree": round(sum(dd) / len(dd), 3) if dd else None, "n_dir": len(dd)}
        d = [err(r["on_mw"], r["obs_p95"]) - err(r["off_mw"], r["obs_p95"]) for r in rs]
        out["closer"] = sum(1 for x in d if x < -0.05)
        out["farther"] = sum(1 for x in d if x > 0.05)
        out["unchanged"] = len(d) - out["closer"] - out["farther"]
        out["sign_test_p"] = sign_test(out["closer"], out["farther"])
        return out
    changed = [r for r in rows if abs(r["on_mw"] - r["off_mw"]) >= 1]
    return {"all": summ(rows), f"within_{NEAR_KM:g}km_of_relinked": summ([r for r in rows if r["near_km"] <= NEAR_KM]),
            "lines_whose_flow_changed_1mw": summ(changed),
            "changed_lines": sorted(changed, key=lambda r: r["near_km"])}


# ------------------------------------------------------------------ 3. 物理
def score_physics(off_dir: Path, on_dir: Path, off: dict, on: dict) -> dict:
    so = json.loads((off_dir / "summary.json").read_text())["islands"]
    sn = json.loads((on_dir / "summary.json").read_text())["islands"]
    out = {}
    for isl in so:
        def over(d, kind):
            if isl not in d:
                return None
            if kind == "lines":
                return sum(1 for v in d[isl]["lines"].values() if v[1] > 100)
            return sum(1 for t in d[isl]["trafos"] if t[2] > 100)
        out[isl] = {k: [so[isl].get(k), sn[isl].get(k)] for k in
                    ("ac_converged", "dc_converged", "ac_vm_min", "ac_total_loss_mw", "ac_max_loading_pct",
                     "dc_max_loading_pct")}
        out[isl]["lines_over_100pct"] = [over(off, "lines"), over(on, "lines")]
        out[isl]["trafos_over_100pct"] = [over(off, "trafos"), over(on, "trafos")]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--off", type=Path, required=True, help="介入なしの出力(--dump-flows つき)")
    ap.add_argument("--on", type=Path, required=True, help="介入ありの出力(--dump-flows つき)")
    ap.add_argument("--structures", type=Path, default=ROOT / "data/structures")
    ap.add_argument("--matched-cache", type=Path, default=None, help="観測の照合結果のキャッシュ(JSON)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    off = json.loads((a.off / "flows.json").read_text())
    on = json.loads((a.on / "flows.json").read_text())
    ledger = json.loads((a.on / "summary.json").read_text())["islands"]
    ledger_off = json.loads((a.off / "summary.json").read_text())["islands"]
    # 介入なしの側ですでに同じ結び方をしている変電所(別の介入で結び直し済み)は、この介入の変化ではない
    same_in_off = {(isl, r["site"], json.dumps(r["linked"])) for isl, v in ledger_off.items()
                   for r in v.get("observed_trafos") or [] if r.get("applied", True)}
    obs_sites = {}
    for src in (ROOT / "data/stations/observed_transformer_pairs.json",
                ROOT / "data/reference/published_transformer_pairs.json"):
        if src.exists():
            obs_sites.update({s["name"]: s for s in json.loads(src.read_text())["sites"]})
    sites48 = []
    for isl, v in ledger.items():
        for r in v.get("observed_trafos") or []:
            if not r.get("applied", True):       # 切っている介入の候補は数えない
                continue
            if (isl, r["site"], json.dumps(r["linked"])) in same_in_off:
                continue
            nm = re.sub(r"\s*\d+(\.\d+)?kV$", "", r["site"])
            s = obs_sites.get(nm) or next((x for k, x in obs_sites.items() if nm.endswith(k) or k.endswith(nm)), None)
            if s:
                sites48.append({"island": isl, "name": nm, "lat": s["lat"], "lon": s["lon"]})
    report = {
        "method": "scripts/validate_intervention.py の docstring",
        "relinked_sites": sites48,
        "topology_vs_published": score_topology(a.structures),
        "flows_vs_observed": score_flows(off, on, matched_lines(a.matched_cache), sites48),
        "physics": score_physics(a.off, a.on, off, on),
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    t, f = report["topology_vs_published"], report["flows_vs_observed"]
    print(json.dumps({"topology": {k: t[k] for k in ("all", "where_they_differ", "with_osm_observation")},
                      "flows": {k: f[k] for k in f if k != "changed_lines"},
                      "physics": report["physics"]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
