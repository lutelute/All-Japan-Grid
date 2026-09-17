#!/usr/bin/env python3
"""混在県個別化(介入#42)のドライラン監査 — all.json は変更しない(2026-09-02).

現ガード(UNIFORM_FREQ_PREFS)対象の周波数跨ぎ候補ノードに対し、
data/reference/freq_boundary_mixed.geojson(出典つき境界)+
freq_corridor_whitelist.json(越境幹線・FC保護)を適用した場合の
フリップ計画を作り、**島跨ぎ切断が新規に0件**であることを検証する。

拒否の3段構え(実装は本体 `src.powerflow.region_attribution.plan_mixed_pref_flips`
に一本化。本スクリプトは呼ぶだけ — 写しを持たない):
  A) 保護域ポリゴン / 富士川実河道の東西判定と領土判定の不一致 → ガード維持
  B) ホワイトリスト: FC名・越境幹線エッジに接するノードは拒否
  C) 切断ガード(硬い保証): 仮適用で新規の島跨ぎエッジが生じる限り、
     関与したフリップを拒否して反復 — 収束時点で新規切断は構造的に0

出力: docs/reports/mixed_pref_flip_audit_<date>.json と標準出力の要約。
正典適用は scripts/apply_node_hygiene.py --mixed-pref --write(帳簿・バックアップつき)。
Usage: PYTHONPATH=. python3 scripts/audit_mixed_pref_flip.py [--out PATH]
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from src.powerflow.region_attribution import (plan_mixed_pref_flips,   # noqa: E402
                                              prefecture_of)

BUILT = "docs/data/built/all.json"


def build_report(nodes, edges, note=None) -> dict:
    mp = plan_mixed_pref_flips(nodes, edges)
    plan = mp["plan"]

    def row(i):
        n = nodes[i]
        return {"id": n.get("id"), "name": n.get("name"), "sub": n.get("sub"),
                "pref": prefecture_of(n["lat"], n["lon"]),
                "from": n.get("region"), "to": plan.get(i),
                "lat": n["lat"], "lon": n["lon"]}

    rep = {
        "date": str(datetime.date.today()),
        "note": note or "ドライラン監査 — all.json 無変更。適用は apply_node_hygiene --mixed-pref --write",
        "guarded_total": len(mp["guarded"]),
        "flip_planned": len(plan),
        "flip_by_dir": {},
        "veto_whitelist": len(mp["veto_whitelist"]),
        "veto_crossing_guard": len(mp["veto_crossing"]),
        "kept_guarded": len(mp["kept"]),
        "kept_by_reason": {},
        "pre_existing_cross_edges": mp["pre_cross_edges"],
        "new_cross_edges_after_plan": mp["new_cross_edges"],
        "pass": mp["new_cross_edges"] == 0,
        "flips": [row(i) for i in sorted(plan)],
        "vetoed_whitelist": [
            {**row(i), "why": w} for i, w in sorted(mp["veto_whitelist"].items())],
        "vetoed_crossing": [
            {**row(i), "cut_edge": w} for i, w in sorted(mp["veto_crossing"].items())],
    }
    for i in plan:
        n = nodes[i]
        k = f"{prefecture_of(n['lat'], n['lon'])}:{n['region']}->{plan[i]}"
        rep["flip_by_dir"][k] = rep["flip_by_dir"].get(k, 0) + 1
    for r in mp["kept"].values():
        rep["kept_by_reason"][r] = rep["kept_by_reason"].get(r, 0) + 1
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=None,
                    help="出力JSON(既定 docs/reports/mixed_pref_flip_audit_<date>.json)")
    args = ap.parse_args(argv)
    d = json.load(open(BUILT, encoding="utf-8"))
    rep = build_report(d["nodes"], d["edges"])
    out = args.out or f"docs/reports/mixed_pref_flip_audit_{rep['date']}.json"
    json.dump(rep, open(out, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1)
    print(f"ガード対象 {rep['guarded_total']} / フリップ計画 {rep['flip_planned']} "
          f"(WL拒否 {rep['veto_whitelist']}・切断ガード拒否 {rep['veto_crossing_guard']}・"
          f"ガード維持 {rep['kept_guarded']} {json.dumps(rep['kept_by_reason'], ensure_ascii=False)})")
    print("方向別:", json.dumps(rep["flip_by_dir"], ensure_ascii=False))
    print(f"既存跨ぎ {rep['pre_existing_cross_edges']} / 新規切断 "
          f"{rep['new_cross_edges_after_plan']} → {'PASS' if rep['pass'] else 'FAIL'}")
    print("->", out)
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
