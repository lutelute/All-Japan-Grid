"""SubSLD(構造 DB)と node-breaker 観測層を、同じ変電所ごとに突き合わせる。

    PYTHONPATH=. .venv/bin/python scripts/compare_station_layers.py [--out docs/reports/station_layers_<日付>]

対応は OSM の (type, id)(``data/stations/japan_rows.json.gz`` の crosswalk)。比べるのは次の 3 つ。

1. 変圧器の電圧の組。構造 DB と潮流モデル(run_full_powerflow_from_db の変電所内の変圧器)は、
   変電所にある電圧階級を高い順に隣どうしで結ぶ「梯子」を仮定している。OSM が両側の巻線電圧
   付きで描いた実機の組と比べ、変電所ごとに判定する。
     same               実機の組の集合 = 梯子の組の集合
     osm_partial        実機の組は梯子の一部(OSM が描き切っていない)
     ladder_skips       梯子が段を飛ばす実機(275/77 の直結など)。構造 DB にある 2 階級の間を
                        梯子は中間の階級経由でつなぐ → 潮流の経路が変わりうる。確認の最優先
     level_not_in_db    構造 DB に無い階級(6 kV など)への実機
2. 電圧階級: 構造 DB の階級と観測層の階級(kV の切り捨て整数で揃える)。
3. 線路の端の根拠: SubSLD の binding と観測層の binding の件数。

梯子の置き換えはしない(モデルの介入はオーナー判断。docs/MODEL_INTERVENTIONS.md の手順)。
ここでは確認の順番を付けた一覧を出すだけ。
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.regions import REGIONS  # noqa: E402

OSM = "https://www.openstreetmap.org/{}/{}"
TYPE = {"n": "node", "w": "way", "r": "relation"}


def kvi(kv) -> int:
    """構造 DB と同じ kV の切り捨て整数(6.6 kV → 6)。"""
    return int(float(kv) + 1e-9)


def load_structures(sdir: Path) -> dict:
    out = {}
    for region in REGIONS:
        p = sdir / f"{region}.json"
        if not p.exists():
            continue
        for s in json.loads(p.read_text())["structures"]:
            out[s["site"]["site_id"]] = (region, s)
    return out


def ladder_pairs(s: dict) -> set:
    out = set()
    for t in s["transformers"]:
        hv, lv = t["hv_vl_id"].rsplit("@", 1)[1], t["lv_vl_id"].rsplit("@", 1)[1]
        if hv != "u" and lv != "u":
            out.add((int(hv), int(lv)))
    return out


def verdict(obs: set, ladder: set, levels: set) -> str:
    extra = obs - ladder
    if not extra:
        return "same" if obs == ladder else "osm_partial"
    if any(hv in levels and lv in levels for hv, lv in extra):
        return "ladder_skips"
    return "level_not_in_db"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rows", type=Path, default=ROOT / "data/stations/japan_rows.json.gz")
    ap.add_argument("--structures", type=Path, default=ROOT / "data/structures")
    ap.add_argument("--out", type=Path, default=ROOT / f"docs/reports/station_layers_{date.today().isoformat()}")
    a = ap.parse_args(argv)

    rows = json.load(gzip.open(a.rows, "rt", encoding="utf-8"))
    data, views = rows["data"], rows["views"]
    structures = load_structures(a.structures)
    nameplate_sites = {sid for sid, (_, s) in structures.items()
                       if any(t.get("source") == "nameplate" for t in s["transformers"])}

    # 観測層: 敷地 → 実機の組・実機 ID・階級
    obs_pairs, obs_eq = defaultdict(set), defaultdict(set)
    for p in views["pairs"]:
        obs_pairs[p["site"]].add((kvi(p["hv_kv"]), kvi(p["lv_kv"])))
        obs_eq[p["site"]].add(p["equipment_id"])
    obs_levels = defaultdict(set)
    for lv in data["levels"]:
        if lv["kv"] is not None and lv["system"] == "ac":
            obs_levels[lv["site"]].add(kvi(lv["kv"]))
    nb_binding = defaultdict(Counter)
    eq_by_id = {e["equipment_id"]: e for e in data["equipment"]}
    for t in data["terminals"]:
        e = eq_by_id[t["equipment_id"]]
        if e["kind"] == "line" and t["terminal_id"] in views["binding"] and t["level_id"]:
            nb_binding[t["level_id"].split("@")[0]][views["binding"][t["terminal_id"]]["binding"]] += 1

    review, verdicts, level_cmp = [], Counter(), Counter()
    jp_binding, nb_binding_sum = Counter(), Counter()
    seen = set()
    for key, sids in sorted(rows["crosswalk"].items()):
        # 1 つの OSM 敷地に構造 DB のサイトが複数あるのは地域境界の重複(aliases)。代表を 1 つ選ぶ
        sids = [sid for sid in sids if sid in structures]
        if not sids:
            continue
        seen.update(sids)
        for sid in sids[:1]:
            region, s = structures[sid]
            db_levels = {kvi(v["nominal_kv"]) for v in s["voltage_levels"] if v["nominal_kv"]}
            ob = obs_levels.get(key, set())
            if ob:
                level_cmp["same" if ob == db_levels else "obs_subset" if ob < db_levels
                          else "obs_superset" if ob > db_levels else "differ"] += 1
            jp_binding.update(t["binding"] for t in s["terminals"])
            nb_binding_sum.update(nb_binding.get(key, {}))
            obs = obs_pairs.get(key)
            if not obs:
                continue
            lad = ladder_pairs(s)
            v = verdict(obs, lad, db_levels)
            verdicts[v] += 1
            if v == "same":
                continue
            skips = sorted(p for p in obs - lad if p[0] in db_levels and p[1] in db_levels)
            review.append({
                "verdict": v, "region": region, "site_id": sid, "aliases": " ".join(sids[1:]),
                "name": s["site"]["name"],
                "osm": OSM.format(TYPE[key[0]], key[1:]),
                "db_levels": "/".join(map(str, sorted(db_levels, reverse=True))),
                "ladder_pairs": " ".join(f"{h}/{l}" for h, l in sorted(lad, reverse=True)),
                "observed_pairs": " ".join(f"{h}/{l}" for h, l in sorted(obs, reverse=True)),
                "skipped_pairs": " ".join(f"{h}/{l}" for h, l in skips),
                "observed_transformers": " ".join(sorted(obs_eq[key])),
                "nameplate_site": sid in nameplate_sites,
            })
    order = {"ladder_skips": 0, "level_not_in_db": 1, "osm_partial": 2}
    review.sort(key=lambda r: (order[r["verdict"]], not r["nameplate_site"], r["region"], r["name"]))

    a.out.mkdir(parents=True, exist_ok=True)
    with open(a.out / "transformer_pair_review.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(review[0]) if review else ["verdict"])
        w.writeheader()
        w.writerows(review)
    skip_pairs = Counter(p for r in review if r["verdict"] == "ladder_skips" for p in r["skipped_pairs"].split())
    manifest = a.rows.parent / "MANIFEST.json"
    osm_time = json.loads(manifest.read_text())["input"].get("osm_timestamp") if manifest.exists() else None
    summary = {
        "generated": date.today().isoformat(),
        "inputs": {"rows": str(a.rows.relative_to(ROOT)), "structures": str(a.structures.relative_to(ROOT)),
                   "osm_timestamp_node_breaker": osm_time,
                   "note": "構造 DB は data/*_substations.geojson(Overpass、2026-08 取得)由来。観測の時点が違う"},
        "structure_sites_compared": len(seen),
        "osm_sites_compared": sum(1 for sids in rows["crosswalk"].values() if any(x in structures for x in sids)),
        "transformer_pairs": {"sites_with_observed_pairs": sum(verdicts.values()), "verdict": dict(verdicts),
                              "skipped_pairs_top": dict(skip_pairs.most_common(15)),
                              "nameplate_sites_in_review": sum(r["nameplate_site"] for r in review)},
        "voltage_levels": dict(level_cmp),
        "line_end_binding": {"subsld": dict(jp_binding), "node_breaker": dict(nb_binding_sum)},
    }
    (a.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
