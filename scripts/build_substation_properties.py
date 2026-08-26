#!/usr/bin/env python3
"""変電所プロパティ層 — 電圧階級・回線数・導体数の全国集約(オーナー指示 2026-08-26).

オーナー方針(2026-07-02)「線は変電所に入り、変電所で電圧階級・タップ・回線・導体を
接続する」の機械化。構造DB(data/structures/{region}.json = node-breaker、
build_structures_batch.py が生成)の terminal は line_key で OSM 線 feature に
束縛済みだが、線の circuits(回線数)/wires(導体数)/cables(条数) タグは未集約
(par=1 既定・par_source=null)。本スクリプトがそのギャップを埋める:

  一次ソース data/{region}_lines.geojson の OSM 生タグ
    × 構造DBの terminal(line_key で join)
    → 変電所ごと・電圧階級ごとの接続プロパティに集約

集約値(捏造ゼロ: タグが無い線は unknown として数え、推測で埋めない):
  - n_lines: その電圧階級に束縛された線 feature 数(ユニーク)
  - circuits_sum: OSM 証拠(circuits タグ / cables÷3)がある線の回線数合計
  - circuits_est: 証拠なし線を1回線と数えた推計合計(snapped_topology と同じ既定)
  - wires: 導体数タグの分布(single/double/triple/quad → 1/2/3/4)
  - cables_sum: cables タグ合計
  - lines[]: 線ごとの明細(name/circuits/circuits_src/wires/cables)

出力: docs/data/substation_properties.json(全国・commit対象)。
--attach で built(docs/data/built/all.json)の sub ノードに compact 版
(node["sub_props"])を付与する(冪等・regen(STEPS)組込前提)。

構造DBが無い地域は build_structures_batch を自動実行して生成する(全国約4秒)。

usage:
  PYTHONPATH=. python3 scripts/build_substation_properties.py            # 集約のみ
  PYTHONPATH=. python3 scripts/build_substation_properties.py --attach   # built付与も
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import unicodedata
import re
import math
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_substation_structure import prepare_ways   # noqa: E402
from scripts.substation_scope import load                     # noqa: E402
from src.powerflow.snapped_topology import _parse_circuits    # noqa: E402
from src.regions import REGIONS                               # noqa: E402

_WIRES = {"single": 1, "double": 2, "triple": 3, "quad": 4}


def _parse_wires(props):
    """OSM wires タグ → 1相あたり導体数(1..8)。無タグ/解釈不能は None."""
    raw = str(props.get("wires") or "").strip().lower()
    if not raw:
        return None
    if raw in _WIRES:
        return _WIRES[raw]
    try:
        n = int(raw.split(";")[0])
        return n if 1 <= n <= 8 else None
    except ValueError:
        return None


def _parse_cables(props):
    raw = str(props.get("cables") or "").strip()
    if not raw:
        return None
    try:
        n = int(raw.replace(";", "/").split("/")[0])
        return n if 1 <= n <= 64 else None
    except ValueError:
        return None


def norm_base(s):
    s = unicodedata.normalize("NFKC", str(s or "")).replace(" ", "")
    s = re.sub(r"(_\d+|\s*\d+kV)$", "", s)
    return s


def hav_m(a, b):
    la1, lo1 = a
    la2, lo2 = b
    dla = math.radians(la2 - la1)
    dlo = math.radians(lo2 - lo1)
    x = (math.sin(dla / 2) ** 2 + math.cos(math.radians(la1))
         * math.cos(math.radians(la2)) * math.sin(dlo / 2) ** 2)
    return 6371000.0 * 2 * math.asin(math.sqrt(x))


def ensure_structures(region):
    p = ROOT / "data/structures" / f"{region}.json"
    if not p.exists():
        print(f"  structures/{region}.json 不在 → build_structures_batch 実行")
        subprocess.run([sys.executable, "scripts/build_structures_batch.py",
                        "--region", region], cwd=ROOT, check=True)
    return json.loads(p.read_text())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--attach", action="store_true",
                    help="built(all.json)の sub ノードに sub_props を付与")
    args = ap.parse_args()

    sites_out = []
    seen_geom = {}          # site_id の幾何ハッシュ → 出力index(跨region重複統合)
    coverage = {}
    for region in REGIONS:
        _subs, lines = load(region, data_dir=str(ROOT / "data"))
        ways = prepare_ways(lines)
        props_of = {}
        for w in ways:
            props_of.setdefault(w["key"], w["props"])
        st = ensure_structures(region)

        n_lines_reg = len(lines["features"])
        n_circ = sum(1 for f in lines["features"]
                     if _parse_circuits(f.get("properties") or {})[1])
        n_wire = sum(1 for f in lines["features"]
                     if _parse_wires(f.get("properties") or {}) is not None)
        coverage[region] = {"lines": n_lines_reg,
                            "circuits_evidence": n_circ,
                            "wires_tag": n_wire}

        for s in st["structures"]:
            site = s["site"]
            vls = {vl["vl_id"]: vl for vl in s["voltage_levels"]}
            term_by_vl = defaultdict(set)     # vl_id → line_key集合
            for t in s["terminals"]:
                if t.get("line_key"):
                    term_by_vl[t["vl_id"]].add(t["line_key"])
            vl_recs = []
            for vl_id, keys in sorted(term_by_vl.items()):
                kv = (vls.get(vl_id) or {}).get("nominal_kv")
                line_recs, csum, cest, cables, wdist = [], 0, 0, 0, Counter()
                n_ctag = 0
                for k in sorted(keys):
                    p = props_of.get(k)
                    if p is None:
                        cest += 1
                        line_recs.append({"key": k, "name": None})
                        continue
                    cn, csrc = _parse_circuits(p)
                    wn = _parse_wires(p)
                    cb = _parse_cables(p)
                    if csrc:
                        csum += cn
                        n_ctag += 1
                    cest += cn if csrc else 1
                    if wn:
                        wdist[wn] += 1
                    if cb:
                        cables += cb
                    line_recs.append({
                        "key": k, "name": p.get("name"),
                        "circuits": cn if csrc else None,
                        "circuits_src": csrc, "wires": wn, "cables": cb})
                vl_recs.append({
                    "kv": kv, "n_lines": len(keys),
                    "circuits_sum": csum, "circuits_known_lines": n_ctag,
                    "circuits_est": cest,
                    "wires": {str(k): v for k, v in sorted(wdist.items())},
                    "wires_max": max(wdist) if wdist else None,
                    "cables_sum": cables or None,
                    "lines": line_recs})
            rec = {
                "site_id": site["site_id"], "name": site["name"],
                "region": region, "lat": site["lat"], "lon": site["lon"],
                "operator": site.get("operator"),
                "substation_type": site.get("substation_type"),
                "n_transformers": len(s.get("transformers") or []),
                "kv_levels": sorted({v["kv"] for v in vl_recs
                                     if v["kv"]}, reverse=True),
                "voltage_levels": vl_recs,
            }
            gkey = site["site_id"].split("site_")[-1]
            if gkey in seen_geom:      # 跨region重複(aliases)は region を追記
                sites_out[seen_geom[gkey]].setdefault(
                    "also_regions", []).append(region)
                continue
            seen_geom[gkey] = len(sites_out)
            sites_out.append(rec)

    n_l = sum(c["lines"] for c in coverage.values())
    n_c = sum(c["circuits_evidence"] for c in coverage.values())
    n_w = sum(c["wires_tag"] for c in coverage.values())
    out = {
        "note": ("変電所プロパティ層(オーナー指示 2026-08-26): 構造DB terminal × "
                 "OSM線タグの集約。circuits_sum=OSM証拠(circuitsタグ/cables÷3)の"
                 "ある線のみの合計・circuits_est=証拠なし線を1回線と数えた推計。"
                 "wires=導体数タグ分布。捏造ゼロ: 無タグは埋めない"),
        "coverage": coverage,
        "n_sites": len(sites_out),
        "sites": sites_out,
    }
    dst = ROOT / "docs/data/substation_properties.json"
    dst.write_text(json.dumps(out, ensure_ascii=False))
    print(f"サイト{len(sites_out)}件(跨region統合後) / 線タグ被覆: "
          f"circuits系 {n_c}/{n_l} ({n_c/n_l:.0%}) wires {n_w}/{n_l} "
          f"({n_w/n_l:.0%})")
    print(f"-> {dst.relative_to(ROOT)} ({dst.stat().st_size/1e6:.1f}MB)")

    if not args.attach:
        return 0

    # built の sub ノードへ compact 付与(名前一致優先・300m 近傍フォールバック)
    built_p = ROOT / "docs/data/built/all.json"
    built = json.loads(built_p.read_text())
    by_name = defaultdict(list)
    grid = defaultdict(list)
    for s in sites_out:
        by_name[norm_base(s["name"])].append(s)
        grid[(round(s["lat"], 2), round(s["lon"], 2))].append(s)

    def compact(s):
        return {"kv": s["kv_levels"],
                "lines": sum(v["n_lines"] for v in s["voltage_levels"]),
                "circuits": sum(v["circuits_est"]
                                for v in s["voltage_levels"]),
                "circuits_src": sum(v["circuits_known_lines"]
                                    for v in s["voltage_levels"]),
                "wires_max": max((v["wires_max"] or 0
                                  for v in s["voltage_levels"]), default=0)
                or None,
                "trafo": s["n_transformers"]}

    n_att = n_name = 0
    for n in built["nodes"]:
        if not n.get("sub"):
            continue
        cand = None
        nb = norm_base(n.get("name"))
        for s in by_name.get(nb, []):
            d = hav_m((n["lat"], n["lon"]), (s["lat"], s["lon"]))
            if d <= 500 and (cand is None or d < cand[0]):
                cand = (d, s, "name")
        if cand is None:
            g = (round(n["lat"], 2), round(n["lon"], 2))
            for dla in (-1, 0, 1):
                for dlo in (-1, 0, 1):
                    for s in grid.get((round(g[0] + dla / 100, 2),
                                       round(g[1] + dlo / 100, 2)), []):
                        d = hav_m((n["lat"], n["lon"]), (s["lat"], s["lon"]))
                        if d <= 300 and (cand is None or d < cand[0]):
                            cand = (d, s, "near")
        if cand:
            n["sub_props"] = compact(cand[1])
            n_att += 1
            n_name += cand[2] == "name"
    n_sub = sum(1 for n in built["nodes"] if n.get("sub"))
    built_p.write_text(json.dumps(built, ensure_ascii=False))
    print(f"★built付与: subノード{n_sub}中 {n_att}件に sub_props "
          f"(名前一致{n_name}/近傍{n_att - n_name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
