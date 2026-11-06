#!/usr/bin/env python3
"""MapLibre 版の系統図(docs/map_gl.html)が読むベクタータイルと英語名の表を作る (2026-11-07 試作).

    python scripts/build_map_gl_tiles.py            # tippecanoe が要る(brew install tippecanoe)

入力(読むだけ。正典 docs/data/built は触らない)
------------------------------------------------
docs/data/map/lines_all.geojson   正典から書いた線(scripts/export_map_tiers_from_built.py)
docs/data/map/subs_all.geojson    同じく変電所
docs/data/map/regions.json        地域の名前(name_ja・name_en)と範囲
docs/data/plants_utility.geojson  発電所(電力会社)
data/*_{substations,lines,plants}*.geojson  基底 OSM の抽出。英語名(name:en)を引くためだけに読む

出力
----
docs/data/map/grid.pmtiles   3 層(lines・subs・plants)のベクタータイル。z3〜z11(z11 の 1 目盛り≒5 m で、元の座標の桁 0.0001°≒11 m より細かい)。全部の線と点を全ズームに載せる
                             (電圧の下限はページで絞るので、低いズームで間引かない)
docs/data/map/names_en.json  表示名 → OSM の name:en。地図に出てくる名前だけ。無い名前はページでそのまま出す
docs/data/map/grid_gl.json   上の 2 つを作った元ファイルの sha256、地域×電圧の下限ごとの件数(状態表示用)

tests/test_map_gl_tiles.py が、元ファイルの sha256 が今のファイルと合うか(正典が進んだのに作り直していないか)を見る。

各 feature には _id(元ファイルでの順番 0,1,2…)を付ける。GeoJSON をそのまま読む場合も MapLibre の
generateId が同じ順番を振るので、どちらの読み方でも選んだ線の目立たせ方と探し方が同じになる。
"""
import argparse
import collections
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
MAP_DIR = os.path.join(DOCS, "data", "map")

SOURCES = {
    "lines": os.path.join(MAP_DIR, "lines_all.geojson"),
    "subs": os.path.join(MAP_DIR, "subs_all.geojson"),
    "plants": os.path.join(DOCS, "data", "plants_utility.geojson"),
}
REGIONS = os.path.join(MAP_DIR, "regions.json")
OUT_PMTILES = os.path.join(MAP_DIR, "grid.pmtiles")
OUT_NAMES = os.path.join(MAP_DIR, "names_en.json")
OUT_MANIFEST = os.path.join(MAP_DIR, "grid_gl.json")

# タイルに残す属性(詳細カードと色分けに使うものだけ。_region_ja は地域の表から引く)
KEEP = {
    "lines": ["_voltage_kv", "_display_name", "_region", "_main", "_par"],
    "subs": ["_voltage_kv", "_display_name", "_region", "_main", "name", "voltage_kv",
             "category_ja", "operator", "operator_en", "frequency_hz"],
    "plants": ["_display_name", "_region", "fuel_type", "capacity_mw", "capacity_mw_sourced",
               "capacity_source_url", "capacity_source_note"],
}
# 電圧の下限の切り替え(ページの 500 / 275+ / 154+ / 66+ / すべて と同じ)
MIN_KV = [500, 275, 154, 66, 0]
MIN_ZOOM, MAX_ZOOM = 3, 11

KV_SUFFIX = re.compile(r"\s*\d+(?:\.\d+)?\s*kV$", re.I)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def clean_name(n):
    """grid_map.js の cleanName と同じ(末尾の「 66kV」を落とす)。"""
    return KV_SUFFIX.sub("", str(n or "")).strip()


def osm_name_en():
    """基底 OSM の name / name:ja → name:en。食い違う名前は数の多い方、同数なら辞書順で先の方。"""
    votes = collections.defaultdict(collections.Counter)
    files = []
    for kind in ("substations", "lines", "plants"):
        files += sorted(glob.glob(os.path.join(ROOT, "data", f"*_{kind}*.geojson")))
    for fn in files:
        with open(fn, encoding="utf-8") as f:
            feats = json.load(f)["features"]
        for feat in feats:
            p = feat.get("properties") or {}
            en = str(p.get("name:en") or "").strip()
            if not en:
                continue
            for key in ("name", "name:ja"):
                ja = str(p.get(key) or "").strip()
                if ja and ja != en:
                    votes[ja][en] += 1
    table, conflicts = {}, 0
    for ja, c in votes.items():
        best = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        table[ja] = best
        conflicts += len(c) > 1
    return table, conflicts, [rel(f) for f in files]



def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tippecanoe", default=shutil.which("tippecanoe"))
    ap.add_argument("--keep-tmp", action="store_true")
    args = ap.parse_args()
    if not args.tippecanoe:
        sys.exit("tippecanoe が見つからない(macOS: brew install tippecanoe / Linux: felt/tippecanoe をビルド)")

    data = {}
    for layer, path in SOURCES.items():
        with open(path, encoding="utf-8") as f:
            data[layer] = json.load(f)["features"]
    with open(REGIONS, encoding="utf-8") as f:
        regions = json.load(f)

    # ── 英語名 ──
    lut, conflicts, osm_files = osm_name_en()
    names, hits = {}, collections.Counter()
    for layer, feats in data.items():
        for feat in feats:
            p = feat["properties"]
            for n in {str(p.get("_display_name") or "").strip(), clean_name(p.get("name") or p.get("_display_name"))}:
                if n and n in lut:
                    names[n] = lut[n]
            if any(n in lut for n in (str(p.get("_display_name") or "").strip(),
                                      clean_name(p.get("name") or p.get("_display_name")))):
                hits[layer] += 1

    # ── 件数(地域 × 電圧の下限。発電所は電圧で絞らない) ──
    counts = {}
    region_ids = ["all"] + [r["id"] for r in regions]
    for rid in region_ids:
        counts[rid] = {}
        for mk in MIN_KV:
            row = {}
            for layer, feats in data.items():
                n = 0
                for feat in feats:
                    p = feat["properties"]
                    if rid != "all" and p.get("_region") != rid:
                        continue
                    if layer != "plants" and mk > 0:
                        # ページの絞り込み(_voltage_kv だけを見る。grid_map.js の filterByVoltage と同じ)
                        kv = p.get("_voltage_kv")
                        if kv is None or kv < mk:
                            continue
                    n += 1
                row[layer] = n
            counts[rid][str(mk)] = row

    # ── タイル ──
    tmp = tempfile.mkdtemp(prefix="agj_map_gl_")
    try:
        layer_args = []
        for layer, feats in data.items():
            out = []
            for i, feat in enumerate(feats):
                p = feat["properties"]
                q = {k: p[k] for k in KEEP[layer] if p.get(k) not in (None, "")}
                q["_id"] = i
                out.append({"type": "Feature", "properties": q, "geometry": feat["geometry"]})
            fn = os.path.join(tmp, f"{layer}.geojson")
            with open(fn, "w", encoding="utf-8") as f:
                json.dump({"type": "FeatureCollection", "features": out}, f, ensure_ascii=False, separators=(",", ":"))
            layer_args += ["-L", f"{layer}:{fn}"]
        cmd = [args.tippecanoe, "-o", OUT_PMTILES, "--force", "--quiet",
               f"-Z{MIN_ZOOM}", f"-z{MAX_ZOOM}",
               "-r1",                      # 点を間引かない(全ズームに全部の変電所と発電所)
               "--no-feature-limit", "--no-tile-size-limit",
               "--no-tile-stats",          # 属性の統計を metadata に入れない(ページは読まない)
               "-n", "AGJ grid (map_gl)",
               "-A", "All-Japan-Grid / OpenStreetMap contributors"] + layer_args
        subprocess.run(cmd, check=True)
        version = subprocess.run([args.tippecanoe, "--version"], capture_output=True, text=True)
        version = (version.stdout or version.stderr).strip()
    finally:
        if args.keep_tmp:
            print("tmp:", tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    with open(OUT_NAMES, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(names.items())), f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")

    manifest = {
        "_about": "docs/map_gl.html が読む。scripts/build_map_gl_tiles.py が書く。sources の sha256 が今の"
                  "ファイルと違えば作り直す(tests/test_map_gl_tiles.py)。",
        "sources": {rel(p): sha256(p) for p in list(SOURCES.values()) + [REGIONS]},
        "names_en_from": osm_files,
        "outputs": {rel(OUT_PMTILES): os.path.getsize(OUT_PMTILES), rel(OUT_NAMES): os.path.getsize(OUT_NAMES)},
        "zoom": [MIN_ZOOM, MAX_ZOOM],
        "tippecanoe": version,
        "features": {k: len(v) for k, v in data.items()},
        "names_en": {"entries": len(names), "osm_conflicts": conflicts,
                     "features_with_en": dict(hits)},
        "counts": counts,
    }
    with open(OUT_MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
        f.write("\n")

    mb = os.path.getsize(OUT_PMTILES) / 1e6
    print(f"{rel(OUT_PMTILES)}: {mb:.2f} MB  z{MIN_ZOOM}-{MAX_ZOOM}  "
          + "  ".join(f"{k} {len(v):,}" for k, v in data.items()))
    print(f"{rel(OUT_NAMES)}: {len(names):,} 件  英語名が付く feature: "
          + "  ".join(f"{k} {hits[k]:,}/{len(data[k]):,}" for k in data))


if __name__ == "__main__":
    main()
