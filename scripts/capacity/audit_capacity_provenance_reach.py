#!/usr/bin/env python3
"""発電容量の出典が「どこまで届いているか」を監査する。

出典必須DB（`data/generator_capacity_sources.jsonl`）は値と出典をセットで持つが、
**その値が実際に下流のどの成果物に届いているか**は別問題。2026-08-09 の調査で
二つの穴が見つかったので、常時検出できるようにする。

1. **出典がCGMESに届いていない** — `src/cim/exporter.py` は `capacity_mw_sourced` を
   優先して `GeneratingUnit.ratedP` に載せ、`capacity_source_url` を
   `IdentifiedObject.description` に刻む実装になっている（Phase 1-B 出典伝播）。
   しかし出典を書き込む `apply_capacity_sources.py` の対象は `docs/data/*.geojson` の
   4ファイルだけで、**CIM が読む `data/<region>_plants.geojson` は対象外**。
   結果、CIM 内の出典URLは変圧器由来のみで、発電容量由来は 0 件。

2. **出典値を単純合計すると多重計上** — `capacity_mw_sourced` は発電所全体の値
   （例: 柏崎刈羽 8,212MW = 7号機合計）だが、レコードは号機単位なので同じ値が
   7 レコードに載る。レコード単位で合計すると 73% 過大になる。
   現時点でそれを合計している消費者は無いが、罠として残っている。

usage: python3 scripts/capacity/audit_capacity_provenance_reach.py
出力: docs/reports/capacity_provenance_reach_<date>.{md,json}
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

REPORTS = ROOT / "docs" / "reports"
GEN_DB = ROOT / "data" / "generator_capacity_sources.jsonl"
TRAFO_DB = ROOT / "data" / "transformer_sources.jsonl"
APPLIED = ROOT / "docs" / "data" / "generators.geojson"
CIM_INPUT_GLOB = str(ROOT / "data" / "*_plants.geojson")
CIM_OUT_GLOB = str(ROOT / "dist" / "cim" / "*_EQ.xml")


def load_urls(path: Path) -> set[str]:
    if not path.exists():
        return set()
    out = set()
    for line in open(path, encoding="utf-8"):
        if line.strip():
            u = json.loads(line).get("source_url")
            if u:
                out.add(u)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                                       text=True).stdout.strip()

    gen_urls, trafo_urls = load_urls(GEN_DB), load_urls(TRAFO_DB)

    # ── ① 出典が適用されている成果物 ─────────────────────────────
    applied_n = applied_sourced = 0
    by_name: dict[str, list[tuple[float, float]]] = defaultdict(list)
    if APPLIED.exists():
        for ft in json.load(open(APPLIED))["features"]:
            p = ft["properties"]
            applied_n += 1
            s = p.get("capacity_mw_sourced")
            if s not in (None, "", 0):
                applied_sourced += 1
                by_name[str(p.get("name") or "?")].append(
                    (float(p.get("capacity_mw") or 0), float(s)))

    multi = {k: v for k, v in by_name.items() if len(v) > 1}
    naive = sum(x[1] for v in by_name.values() for x in v)      # レコード単位合計
    per_plant = sum(v[0][1] for v in by_name.values())          # 発電所ごとに1回
    unit_sum = sum(x[0] for v in by_name.values() for x in v)   # 号機容量の合計
    overcount = naive - per_plant

    # ── ② CIM の入力に出典欄があるか ─────────────────────────────
    cim_in_n = cim_in_sourced = 0
    for f in sorted(glob.glob(CIM_INPUT_GLOB)):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        for ft in d.get("features", []):
            cim_in_n += 1
            if ft["properties"].get("capacity_mw_sourced") not in (None, "", 0):
                cim_in_sourced += 1

    # ── ③ CIM の出力に届いた出典URL ─────────────────────────────
    cim_urls: list[str] = []
    for f in sorted(glob.glob(CIM_OUT_GLOB)):
        s = open(f, encoding="utf-8", errors="replace").read()
        cim_urls += re.findall(r"IdentifiedObject\.description>(https?://[^<]+)", s)
    uniq = set(cim_urls)
    from_gen = uniq & gen_urls
    from_trafo = uniq & trafo_urls

    payload = {
        "date": date,
        "generator_source_db": {"n_urls": len(gen_urls)},
        "transformer_source_db": {"n_urls": len(trafo_urls)},
        "applied_geojson": {
            "file": str(APPLIED.relative_to(ROOT)), "n_features": applied_n,
            "n_sourced": applied_sourced, "n_plants": len(by_name),
            "n_plants_multi_record": len(multi),
            "sum_per_record_mw": round(naive, 1),
            "sum_per_plant_mw": round(per_plant, 1),
            "sum_unit_capacity_mw": round(unit_sum, 1),
            "overcount_mw": round(overcount, 1),
            "overcount_share": round(overcount / naive, 4) if naive else 0,
        },
        "cim_input": {"glob": "data/*_plants.geojson", "n_features": cim_in_n,
                      "n_sourced": cim_in_sourced},
        "cim_output": {"n_description_urls": len(cim_urls), "n_unique": len(uniq),
                       "n_from_generator_db": len(from_gen),
                       "n_from_transformer_db": len(from_trafo)},
        "findings": {
            "capacity_provenance_reaches_cim": bool(from_gen),
            "sourced_sum_is_safe": len(multi) == 0,
        },
    }
    json.dump(payload, open(REPORTS / f"capacity_provenance_reach_{date}.json", "w"),
              ensure_ascii=False, indent=1)

    L = [
        f"# 発電容量の出典はどこまで届いているか（{date}）",
        "",
        "出典必須DB は値と出典をセットで持つが、**その値が下流のどの成果物に届いているか**は",
        "別問題。監査したところ二つの穴が見つかった。",
        "",
        "## ① 発電容量の出典が CGMES に届いていない",
        "",
        "| | |",
        "|---|---:|",
        f"| 発電容量 出典DB の URL 種類 | {len(gen_urls)} |",
        f"| 変圧器 出典DB の URL 種類 | {len(trafo_urls)} |",
        f"| CGMES 内の出典URL（延べ / 種類） | {len(cim_urls)} / {len(uniq)} |",
        f"| うち **発電容量DB** 由来 | **{len(from_gen)}** |",
        f"| うち 変圧器DB 由来 | {len(from_trafo)} |",
        "",
        f"CIM が読む `data/*_plants.geojson` は {cim_in_n:,} レコードあるが、",
        f"`capacity_mw_sourced` を持つのは **{cim_in_sourced} 件**。",
        "",
        "`src/cim/exporter.py` は出典値を優先し出典URLを `IdentifiedObject.description` に",
        "刻む実装になっている（Phase 1-B 出典伝播）。しかし出典を書き込む",
        "`apply_capacity_sources.py` の対象は `docs/data/` の 4 ファイルだけで、",
        "**CIM の入力は対象外**。つまり伝播の経路が繋がっていない。",
        "変圧器の出典は別経路で届いているため、CGMES に出典URLは存在する — ",
        "そのせいで「届いている」ように見えてしまう点が厄介だった。",
        "",
        "**影響**: CGMES の `GeneratingUnit.ratedP` は出典付きの値ではなく OSM/P03 由来の",
        "生値のまま。捏造防止の規約が CGMES まで貫通していない。",
        "",
        "## ② 出典値を単純合計すると多重計上になる",
        "",
        f"`{APPLIED.relative_to(ROOT)}` の {applied_sourced} 件が出典付きで、",
        f"実体は **{len(by_name)} 発電所**（うち {len(multi)} 発電所が複数レコード＝号機単位）。",
        "",
        "| 数え方 | 合計 |",
        "|---|---:|",
        f"| 号機容量 `capacity_mw` の合計 | {unit_sum:,.0f} MW |",
        f"| 発電所ごとに 1 回だけ数えた出典値 | {per_plant:,.0f} MW |",
        f"| **レコード単位で出典値を合計** | **{naive:,.0f} MW** |",
        f"| 多重計上ぶん | {overcount:,.0f} MW（{overcount / naive:.0%}） |",
        "",
        "`capacity_mw_sourced` は**発電所全体の値**（柏崎刈羽 8,212MW = 7 号機合計）だが、",
        "レコードは号機単位なので同じ値が 7 レコードに載る。**現時点でこれを合計している",
        "消費者は無い**ので実害は出ていないが、集計を書いた瞬間に踏む罠として残っている。",
        "",
        "## 直し方の提案（未適用）",
        "",
        "- ①: `apply_capacity_sources.py` の対象に `data/*_plants.geojson` を加えるか、",
        "  CIM 側が `docs/data/` の適用済みファイルを読むようにする。どちらが正かは",
        "  データフローの設計判断なので人間が決める",
        "- ②: 号機単位レコードには**号機容量**を、発電所全体の値は別欄",
        "  （`plant_total_mw` 等）に分ける。あるいは出典値を号機数で按分する。",
        "  当面は本監査を回して「合計してはいけない」ことを機械的に思い出せるようにする",
        "",
        "---",
        "生成: `scripts/capacity/audit_capacity_provenance_reach.py`",
        "",
    ]
    (REPORTS / f"capacity_provenance_reach_{date}.md").write_text("\n".join(L), encoding="utf-8")

    print(f"① 出典のCGMES到達: 発電容量DB由来 {len(from_gen)} 種 / 変圧器DB由来 {len(from_trafo)} 種")
    print(f"   CIM入力 {cim_in_n:,} レコード中、出典付きは {cim_in_sourced} 件")
    print(f"② 出典値の合計: レコード単位 {naive:,.0f} MW vs 発電所単位 {per_plant:,.0f} MW "
          f"→ 多重計上 {overcount:,.0f} MW ({overcount/naive:.0%})")
    print(f"   複数レコードを持つ発電所 {len(multi)} 件")
    print(f"→ docs/reports/capacity_provenance_reach_{date}.md")


if __name__ == "__main__":
    main()
