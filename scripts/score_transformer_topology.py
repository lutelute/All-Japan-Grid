"""変電所内の変圧器の結び方(梯子 / 介入 #48)が正しいかを、各社の公表一覧(全国の変圧器台帳)で採点する。

    PYTHONPATH=. .venv/bin/python scripts/score_transformer_topology.py \
        [--registry data/external/system_disclosure/transformer_lists/transformer_registry.csv] \
        [--out docs/reports/<日付>/transformer_topology_score.json]

判断の根拠は「正しいか」(docs/INTERVENTION_VALIDATION.md)。正解は各社の空容量・予想潮流一覧の変圧器の行
(一次・二次[・三次]電圧)。構造 DB の変電所と、地域 + 正規化した名前で対応を取る。

数えるもの(変電所ごと、構造 DB に両端の電圧階級がある組だけ):
    recall    = 公表の組のうち、予測が作れた割合
    precision = 予測の組のうち、公表にある割合(公表一覧がその変電所の変圧器を全部載せている前提)
    exact     = 予測の組の集合が公表と一致した変電所の割合
予測は 梯子(電圧階級の隣どうし)と 観測優先(介入 #48、OSM で観測した組を先に張り残りを梯子)。

公表一覧の値(台数・容量)は All-Rights-Reserved の社があるので、追跡するレポートには件数と割合だけを書く。
変電所ごとの詳細は --detail(非追跡の場所)に書く。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REGISTRY = ROOT / "data/external/system_disclosure/transformer_lists/transformer_registry.csv"
SUFFIX = re.compile(r"(変電所|開閉所|変換所|発電所|開閉站|S/S|SS)$")


def site_norm(name: str) -> str:
    """変電所名の照合用の正規化(公表一覧と構造 DB の両方に同じものを当てる)。"""
    s = unicodedata.normalize("NFKC", str(name or ""))
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"\(.*?\)", "", s)
    for prefix in ("九州電力送配電", "九州電力", "東北電力ネットワーク(株)", "東北電力ネットワーク",
                   "北海道電力", "中国電力", "関西電力", "中部電力", "東京電力"):
        if s.startswith(prefix) and len(s) > len(prefix) + 1:
            s = s[len(prefix):]
    s = re.sub(r"_\d+$", "", s)
    return SUFFIX.sub("", s)


def kvc(v) -> int | None:
    try:
        return int(float(v) + 1e-9)
    except (TypeError, ValueError):
        return None


def load_registry(path: Path) -> dict:
    """(region, 正規化名) → 公表の組の集合(三巻線は 3 組に展開)。"""
    out = defaultdict(set)
    for r in csv.DictReader(open(path, encoding="utf-8")):
        vs = sorted({v for v in (kvc(r.get("hv_kv")), kvc(r.get("lv_kv")), kvc(r.get("tv_kv"))) if v},
                    reverse=True)
        key = (r["agj_region"], site_norm(r.get("substation_norm") or r["substation_raw"]))
        for i, a in enumerate(vs):
            for b in vs[i + 1:]:
                out[key].add((a, b))
    return out


def score(registry: dict, structures_dir: Path) -> tuple[dict, list]:
    from src.model.site_transformers import by_structure_site, link_levels
    observed = by_structure_site()
    rows, seen = [], set()
    for p in sorted(structures_dir.glob("*.json")):
        if p.name == "summary.json" or "_site_" in p.name:
            continue
        d = json.loads(p.read_text())
        for s in d["structures"]:
            key = (d["region"], site_norm(s["site"]["name"]))
            if key not in registry or key in seen:
                continue
            seen.add(key)
            levels = sorted({int(v["nominal_kv"]) for v in s["voltage_levels"] if v["nominal_kv"]}, reverse=True)
            truth_all = registry[key]
            truth = {pr for pr in truth_all if pr[0] in levels and pr[1] in levels}
            ladder = set(zip(levels, levels[1:]))
            obs = observed.get(s["site"]["site_id"])
            linked = {(int(h), int(l)) for h, l, _ in link_levels(levels, obs)} if obs else ladder
            rows.append({"region": d["region"], "name": s["site"]["name"], "levels": levels,
                         "truth": sorted(truth, reverse=True),
                         "truth_level_missing": sorted(truth_all - truth, reverse=True),
                         "ladder": sorted(ladder, reverse=True), "observed_first": sorted(linked, reverse=True),
                         "has_osm_observation": bool(obs)})

    def summ(rs):
        rs = [r for r in rs if r["truth"]]
        if not rs:
            return None
        out = {"sites": len(rs), "truth_pairs": sum(len(r["truth"]) for r in rs)}
        for tag in ("ladder", "observed_first"):
            hit = sum(len(set(map(tuple, r["truth"])) & set(map(tuple, r[tag]))) for r in rs)
            pred = sum(len(r[tag]) for r in rs)
            out[tag] = {"recall": round(hit / out["truth_pairs"], 3),
                        "precision": round(hit / pred, 3) if pred else None,
                        "exact_sites": round(sum(set(map(tuple, r["truth"])) == set(map(tuple, r[tag]))
                                                 for r in rs) / len(rs), 3)}
        return out
    differ = [r for r in rows if r["ladder"] != r["observed_first"]]
    agg = {"matched_sites": len(rows),
           "sites_with_truth_inside_levels": sum(1 for r in rows if r["truth"]),
           "sites_with_truth_level_missing_in_db": sum(1 for r in rows if r["truth_level_missing"]),
           "all": summ(rows), "with_osm_observation": summ([r for r in rows if r["has_osm_observation"]]),
           "without_osm_observation": summ([r for r in rows if not r["has_osm_observation"]]),
           "where_ladder_and_observed_differ": summ(differ)}
    return agg, rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--registry", type=Path, default=REGISTRY)
    ap.add_argument("--structures", type=Path, default=ROOT / "data/structures")
    ap.add_argument("--out", type=Path, default=ROOT / f"docs/reports/transformer_topology_{date.today().isoformat()}.json")
    ap.add_argument("--detail", type=Path, default=REGISTRY.parent / "topology_score_detail.json",
                    help="変電所ごとの詳細(非追跡の場所に書く)")
    a = ap.parse_args(argv)
    if not a.registry.exists():
        sys.exit(f"{a.registry} が無い(非公開。scripts/fetch_transformer_lists.py で作る)")
    registry = load_registry(a.registry)
    agg, rows = score(registry, a.structures)
    agg = {"generated": date.today().isoformat(), "registry_sites": len(registry),
           "note": "正解=各社の空容量・予想潮流一覧の変圧器の行。件数と割合だけ(値は非公開)", **agg}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(agg, ensure_ascii=False, indent=1) + "\n")
    a.detail.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(agg, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
