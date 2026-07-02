"""変電所内部構造(node-breaker)の地域一括生成 — 構造DBの正典生成器.

オーナー指示(2026-07-02): 「構造的に資産になりうるDBになるように改善修正、生成をループ」。
本スクリプトが `data/structures/{region}.json`(正典・D層=OSMから決定的に再生成可能)と
`data/structures/summary.json`(全国集計)を生成する。

資産の品質ゲート(全て機械検証・fail-fast):
  1. 全数生成: 地域の全 substation feature が例外ゼロでレコード化される
  2. 参照整合性: busbar/bay/terminal/transformer の vl_id 参照に dangling ゼロ
  3. ID一意性: site_id が地域内で一意(同名同座標の重複 feature は統合し
     dup_features として記録=OSM品質シグナル)
  4. 決定性: 同一入力から同一出力(構造部のバイト一致。generated 日付は除外)
  5. 接続レコード導出: 両端が別サイトに束縛された線 = サイト間接続
     (どの線が・どの変電所の・どの電圧階級に・どの根拠で)を connections として出力

Usage:
    PYTHONPATH=. .venv/bin/python scripts/build_structures_batch.py --region okinawa
    PYTHONPATH=. .venv/bin/python scripts/build_structures_batch.py --all
    PYTHONPATH=. .venv/bin/python scripts/build_structures_batch.py --all --verify-determinism
"""
import argparse
import json
import os
import time
from collections import Counter, defaultdict
from dataclasses import asdict

from scripts.build_substation_structure import (
    extract_structure,
    load,
    prepare_ways,
)
from src.regions import REGIONS

OUT_DIR = "data/structures"


def check_integrity(s) -> list:
    """vl_id 参照の dangling を列挙(空=健全)。"""
    vlids = {vl.vl_id for vl in s.voltage_levels}
    bad = []
    for bb in s.busbars:
        if bb.vl_id not in vlids:
            bad.append(("busbar", bb.busbar_id))
    for b in s.bays:
        if b.vl_id not in vlids:
            bad.append(("bay", b.bay_id))
    for t in s.terminals:
        if t.vl_id not in vlids:
            bad.append(("terminal", t.terminal_id))
    for tr in s.transformers:
        if tr.hv_vl_id not in vlids or tr.lv_vl_id not in vlids:
            bad.append(("trafo", tr.trafo_id))
    return bad


def derive_connections(structures) -> list:
    """端子 → サイト間接続レコード(線の両端が別サイトに束縛)を導出する。

    これが「接続の第一級データ」の中核: どの線(line_key/名前)が、どの2サイトの
    どの電圧階級に、どの根拠(binding)と信頼度で繋がるかの機械可読レコード。
    """
    by_line = defaultdict(list)
    for s in structures:
        for t in s.terminals:
            by_line[t.line_key].append((s.site.site_id, t))
    conns = []
    for lk in sorted(by_line):
        ends = by_line[lk]
        sites = sorted({sid for sid, _ in ends})
        if len(sites) < 2:
            continue
        # 2サイト以上に触れる線 = 接続。サイト対ごとに1レコード。
        for i, sa in enumerate(sites):
            for sb in sites[i + 1:]:
                ta = next(t for sid, t in ends if sid == sa)
                tb = next(t for sid, t in ends if sid == sb)
                conns.append({
                    "line_key": lk,
                    "line_name": ta.line_name or tb.line_name,
                    "from_site": sa, "from_vl": ta.vl_id,
                    "from_binding": ta.binding,
                    "to_site": sb, "to_vl": tb.vl_id,
                    "to_binding": tb.binding,
                    "par": max(ta.par, tb.par),
                    "confidence": round(min(ta.confidence, tb.confidence), 2),
                })
    return conns


def build_region(region, data_dir="data"):
    """1地域の全変電所を構造化。(structures, report) を返す。"""
    t0 = time.time()
    subs, lines = load(region, data_dir)
    pways = prepare_ways(lines)
    structures = []
    seen_ids = {}
    dup_features = 0
    errors = []
    for i, ft in enumerate(subs["features"]):
        try:
            s, _ways, _poly = extract_structure(region, ft, pways)
        except Exception as exc:   # noqa: BLE001 — 全数生成ゲートで報告
            nm = (ft.get("properties") or {}).get("name")
            errors.append({"index": i, "name": nm,
                           "error": f"{type(exc).__name__}: {exc}"})
            continue
        if s.site.site_id in seen_ids:
            # 同名同座標の重複 feature(OSM品質シグナル)= 1サイトに統合
            dup_features += 1
            continue
        bad = check_integrity(s)
        if bad:
            errors.append({"index": i, "name": s.site.name,
                           "error": f"dangling refs: {bad[:3]}"})
            continue
        seen_ids[s.site.site_id] = True
        structures.append(s)

    conns = derive_connections(structures)
    bind = Counter(t.binding for s in structures for t in s.terminals)
    vl_known = sum(1 for s in structures
                   if any(vl.nominal_kv > 0 for vl in s.voltage_levels))
    report = {
        "region": region,
        "n_features": len(subs["features"]),
        "n_sites": len(structures),
        "dup_features": dup_features,
        "n_errors": len(errors),
        "errors": errors[:10],
        "n_terminals": sum(len(s.terminals) for s in structures),
        "terminal_binding": dict(bind),
        "n_busbars": sum(len(s.busbars) for s in structures),
        "n_busbars_inferred": sum(1 for s in structures for b in s.busbars
                                  if b.kv_inferred),
        "n_bays": sum(len(s.bays) for s in structures),
        "n_transformers": sum(len(s.transformers) for s in structures),
        "sites_with_known_kv": vl_known,
        "n_connections": len(conns),
        "elapsed_s": round(time.time() - t0, 1),
    }
    return structures, conns, report


def payload_dict(region, structures, conns):
    """出力ペイロード(決定性検証は 'generated' を除いた本体で行う)。"""
    return {
        "region": region,
        "n_sites": len(structures),
        "structures": [asdict(s) for s in structures],
        "connections": conns,
    }


def cross_region_aliases(all_payloads):
    """地域重複(同名・近接~200m)の同一実体を aliases として相互記録する。"""
    index = defaultdict(list)   # name -> [(region, site_dict)]
    for pl in all_payloads.values():
        for sd in pl["structures"]:
            nm = sd["site"]["name"]
            if nm:
                index[nm].append((pl["region"], sd))
    n_alias = 0
    for nm, entries in index.items():
        if len(entries) < 2:
            continue
        for i, (ra, sa) in enumerate(entries):
            for rb, sb in entries[i + 1:]:
                if ra == rb:
                    continue
                da = abs(sa["site"]["lat"] - sb["site"]["lat"]) \
                    + abs(sa["site"]["lon"] - sb["site"]["lon"])
                if da > 0.004:      # ~200-400m: 同名でも別サイトは除外
                    continue
                if sb["site"]["site_id"] not in sa["site"]["aliases"]:
                    sa["site"]["aliases"].append(sb["site"]["site_id"])
                if sa["site"]["site_id"] not in sb["site"]["aliases"]:
                    sb["site"]["aliases"].append(sa["site"]["site_id"])
                n_alias += 1
    return n_alias


def generate(regions, out_dir=OUT_DIR, data_dir="data",
             verify_determinism=False, log=print):
    """地域群を生成して書き出す(CLI とダッシュボードの共通実体)。

    Returns:
        (reports, gate_fail): 地域別レポート dict と品質ゲート失敗フラグ。
    """
    os.makedirs(out_dir, exist_ok=True)
    all_payloads = {}
    reports = {}
    gate_fail = False
    for region in regions:
        structures, conns, rep = build_region(region, data_dir)
        reports[region] = rep
        all_payloads[region] = payload_dict(region, structures, conns)
        status = "OK " if rep["n_errors"] == 0 else "FAIL"
        if rep["n_errors"]:
            gate_fail = True
        log(f"[{status}] {region}: features={rep['n_features']} "
            f"sites={rep['n_sites']} dup={rep['dup_features']} "
            f"err={rep['n_errors']} terminals={rep['n_terminals']} "
            f"conn={rep['n_connections']} ({rep['elapsed_s']}s)")
        if rep["errors"]:
            for e in rep["errors"][:3]:
                log(f"    ERR: {e}")

    if verify_determinism:
        for region in regions:
            structures2, conns2, _ = build_region(region, data_dir)
            a = json.dumps(all_payloads[region], ensure_ascii=False,
                           sort_keys=True)
            b = json.dumps(payload_dict(region, structures2, conns2),
                           ensure_ascii=False, sort_keys=True)
            det = "identical" if a == b else "MISMATCH"
            log(f"[determinism] {region}: {det}")
            if det != "identical":
                gate_fail = True

    n_alias = cross_region_aliases(all_payloads) if len(regions) > 1 else 0

    from datetime import date
    for region, pl in all_payloads.items():
        pl["generated"] = date.today().isoformat()
        path = os.path.join(out_dir, f"{region}.json")
        with open(path, "w") as f:
            json.dump(pl, f, ensure_ascii=False, separators=(",", ":"))
    if set(regions) == set(REGIONS):
        summary = {
            "generated": date.today().isoformat(),
            "regions": reports,
            "totals": {
                "sites": sum(r["n_sites"] for r in reports.values()),
                "terminals": sum(r["n_terminals"] for r in reports.values()),
                "busbars": sum(r["n_busbars"] for r in reports.values()),
                "bays": sum(r["n_bays"] for r in reports.values()),
                "transformers": sum(r["n_transformers"]
                                    for r in reports.values()),
                "connections": sum(r["n_connections"]
                                   for r in reports.values()),
                "cross_region_alias_pairs": n_alias,
            },
        }
        with open(os.path.join(out_dir, "summary.json"), "w") as f:
            json.dump(summary, f, ensure_ascii=False, indent=1)
        log("summary: " + json.dumps(summary["totals"], ensure_ascii=False))
    return reports, gate_fail


def main():
    ap = argparse.ArgumentParser(description="変電所構造DBの一括生成(正典)")
    ap.add_argument("--region", help="単一地域")
    ap.add_argument("--all", action="store_true", help="全10地域")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--verify-determinism", action="store_true",
                    help="2回生成して構造部のバイト一致を検証")
    args = ap.parse_args()

    regions = REGIONS if args.all else [args.region]
    if not regions or regions == [None]:
        ap.error("--region か --all を指定")
    _reports, gate_fail = generate(regions, args.out, args.data_dir,
                                   args.verify_determinism)
    if gate_fail:
        raise SystemExit("QUALITY GATE FAILED (errors above)")


if __name__ == "__main__":
    main()
