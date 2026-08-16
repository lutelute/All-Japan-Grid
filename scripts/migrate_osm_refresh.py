#!/usr/bin/env python3
"""OSM再抽出の移行(大工事フェーズ2): data/osm_refresh/* を data/ へ、名前資産を引き継いで移す。

原則:
  - 新raw(osm_id+全タグ)が幾何の正。**OSM実名 > 旧enrich名 > 無名**
  - 旧ファイルのenrich名(endpoint_matching / geocode promotion の住所合成名)は
    「同じ設備」に限り引き継ぐ。同定は幾何(lines=両端点±約60m / subs=重心±100m)
  - これによりYAML台帳(disclosure_map_connections 等)が参照する合成名
    (天瀬町赤岩変電所・日田市変電所110kV 等)は、OSM側が無名のままなら保存される
  - 旧ファイルは data/osm_refresh/backup_old/ に退避(さらにnas03へコピー可)

実行:
  python3 scripts/migrate_osm_refresh.py --dry-run   # 差分レポートのみ
  python3 scripts/migrate_osm_refresh.py --write     # 移行実行
"""
from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEW = ROOT / "data/osm_refresh"
OLD_BAK = NEW / "backup_old"
REPORT = ROOT / "docs/reports/osm_refresh_migration_2026-08-16.json"

REGIONS = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
           "kansai", "chugoku", "shikoku", "kyushu", "okinawa"]
ENRICH_KEYS = ("name", "_enriched_by", "_name_source", "_src:name",
               "_promoted_name", "_geocode_source")


def r4(x: float) -> float:
    return round(x, 4)          # ≈11m格子。端点一致の同定用


def line_keys(feat) -> list:
    g = feat.get("geometry") or {}
    if g.get("type") != "LineString" or len(g.get("coordinates", [])) < 2:
        return []
    a, b = g["coordinates"][0], g["coordinates"][-1]
    ka, kb = (r4(a[0]), r4(a[1])), (r4(b[0]), r4(b[1]))
    return [tuple(sorted((ka, kb)))]


def centroid(feat):
    g = feat.get("geometry") or {}
    if g.get("type") == "Point":
        return g["coordinates"]
    if g.get("type") == "Polygon" and g.get("coordinates"):
        ring = g["coordinates"][0]
        n = max(len(ring) - 1, 1)
        return [sum(p[0] for p in ring[:n]) / n, sum(p[1] for p in ring[:n]) / n]
    return None


def sub_key(feat):
    c = centroid(feat)
    return (round(c[0], 3), round(c[1], 3)) if c else None   # ≈100m格子


def carry(new_props: dict, old_props: dict) -> bool:
    """旧enrich名を新featureへ引き継ぐ。OSM実名があれば何もしない。"""
    if new_props.get("name"):
        return False
    if not old_props.get("name"):
        return False
    for k in ENRICH_KEYS:
        if old_props.get(k) is not None:
            new_props.setdefault(k, old_props[k])
    new_props.setdefault("_name_carried", "osm_refresh_2026-08")
    return True


def migrate_layer(region: str, layer: str, write: bool) -> dict:
    newp = NEW / f"{region}_{layer}.geojson"
    oldp = ROOT / f"data/{region}_{layer}.geojson"
    if not newp.exists() or not oldp.exists():
        return {"status": "missing", "new": newp.exists(), "old": oldp.exists()}
    new = json.loads(newp.read_text(encoding="utf-8"))
    old = json.loads(oldp.read_text(encoding="utf-8"))

    if layer == "lines":
        old_ix = defaultdict(list)
        for f in old["features"]:
            for k in line_keys(f):
                old_ix[k].append(f)
        keyf = line_keys
    else:
        old_ix = defaultdict(list)
        for f in old["features"]:
            k = sub_key(f)
            if k:
                old_ix[k].append(f)
        keyf = lambda f: [sub_key(f)] if sub_key(f) else []   # noqa: E731

    carried = real_named = unnamed = 0
    for f in new["features"]:
        p = f.setdefault("properties", {})
        if p.get("name"):
            real_named += 1
            continue
        done = False
        for k in keyf(f):
            for of in old_ix.get(k, []):
                if carry(p, of.get("properties") or {}):
                    carried += 1
                    done = True
                    break
            if done:
                break
        if not done:
            unnamed += 1

    old_names = {(f.get("properties") or {}).get("name")
                 for f in old["features"]} - {None, ""}
    new_names = {(f.get("properties") or {}).get("name")
                 for f in new["features"]} - {None, ""}
    lost = sorted(old_names - new_names)

    rep = {
        "n_old": len(old["features"]), "n_new": len(new["features"]),
        "real_named": real_named, "carried": carried, "unnamed": unnamed,
        "lost_names": len(lost), "lost_sample": lost[:12],
    }
    if write:
        OLD_BAK.mkdir(parents=True, exist_ok=True)
        bak = OLD_BAK / oldp.name
        if not bak.exists():
            shutil.copy2(oldp, bak)
        oldp.write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")
        rep["written"] = True
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--write", action="store_true")
    args = ap.parse_args()

    out: dict = {}
    for region in REGIONS:
        for layer in ("lines", "substations"):
            rep = migrate_layer(region, layer, args.write)
            out[f"{region}_{layer}"] = rep
            if rep.get("status") == "missing":
                print(f"! {region}/{layer}: new={rep['new']} old={rep['old']} — skip")
                continue
            print(f"{region:9}/{layer:11}: 旧{rep['n_old']:5} → 新{rep['n_new']:5} "
                  f"(実名{rep['real_named']:5} 引継{rep['carried']:5} 無名{rep['unnamed']:4}"
                  f" 消失名{rep['lost_names']:4})")
    REPORT.write_text(json.dumps(
        {"note": "OSM再抽出の移行レポート。carried=旧enrich名を幾何一致で引継。"
                 "lost=旧にあって新に無い名前(幾何変化で引継不能=enrich再走候補)",
         "mode": "write" if args.write else "dry-run", "layers": out},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
