"""変電所の構内結線(node-breaker)の観測層を、電力だけに絞った日本の PBF から作る。

    PYTHONPATH=. .venv/bin/python scripts/build_station_db.py \
        [--pbf data/osm_pbf/japan-power.osm.pbf] [--out data/stations]

入力の取り方(data/stations/MANIFEST.json に記録する):

    curl -O https://download.geofabrik.de/asia/japan-latest.osm.pbf      # md5 を照合
    osmium tags-filter japan-latest.osm.pbf nwr/power r/route=power \
        -o data/osm_pbf/japan-power.osm.pbf

敷地は PBF の power=substation|converter|plant(同じ観測時点)。構造 DB(SubSLD、
data/structures)の変電所とは OSM の (type, id) で対応付け、構造 DB の site_id を
``crosswalk`` に残す。ID は置き換えない。

出力:
    data/stations/japan_rows.json.gz   行(設備・端子・接続点・巻線・回線・課題)と派生の読み方
    data/stations/summary.json         件数・状態・課題・根拠の分布(追跡)
    data/stations/MANIFEST.json        入力の時点・ハッシュ・取得手順・コードの版(追跡)
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shapely.geometry import Point, mapping, shape  # noqa: E402

from scripts.build_substation_structure import _geom_key  # noqa: E402
from src.regions import REGIONS  # noqa: E402
from src.stations.core import VERSION, key_of, model  # noqa: E402
from src.stations.tags import split_list  # noqa: E402
from src.stations.views import analyse, coverage, gaps  # noqa: E402


# 柵の外へはみ出して描かれたベイ・母線を敷地に含める上限(m)。2026-10-06 の日本の抽出で、
# 1 つの敷地からはみ出す構内配線 901 本の 89% が 100 m 以内(中央値 47 m)だった。
EXTENSION_M = 100.0


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def pbf_header(path: Path) -> dict:
    """osmium fileinfo の時点(replication timestamp)。osmium CLI が無ければ空。"""
    try:
        out = subprocess.run(["osmium", "fileinfo", "-g", "header.option.timestamp", str(path)],
                             capture_output=True, text=True, check=True).stdout.strip()
        return {"osm_timestamp": out}
    except (OSError, subprocess.CalledProcessError):
        return {}


def structure_crosswalk(data_dir: Path) -> dict:
    """OSM キー(w123 等) → 構造 DB の site_id(build_substation_structure と同じ導出)。"""
    out = {}
    for region in REGIONS:
        p = data_dir / f"{region}_substations.geojson"
        if not p.exists():
            continue
        for ft in json.loads(p.read_text())["features"]:
            props = ft.get("properties") or {}
            if props.get("osm_type") not in ("node", "way", "relation") or not ft.get("geometry"):
                continue
            g = shape(ft["geometry"])
            name = props.get("name") or ""
            sid = f"{region}_site_{_geom_key([[g.centroid.x, g.centroid.y]], name)[2:]}"
            out.setdefault(key_of(props["osm_type"], props["osm_id"]), []).append(sid)
    return out


def frequency_mix(data: dict) -> list:
    """同じ敷地の同じ電圧階級に 50 Hz と 60 Hz のタグの導体が両方ある所(周波数変換所の候補)。

    日本では 50/60 Hz を同じ系統 ``ac`` として扱うので(src/stations/tags.py)、ここで別に拾う。
    """
    freqs = defaultdict(set)
    for e in data["equipment"]:
        if e["kind"] in ("busbar", "bay", "internal", "line") and e.get("lvl") and e["lvl"][0] is not None:
            for f in split_list(e["tags"].get("frequency")):
                if f in ("50", "60"):
                    sites = [e["site"]] if e["site"] else [s for s in e.get("end_sites") or () if s]
                    for s in sites:
                        freqs[(s, e["lvl"][0])].add(f)
    return [{"site": s, "kv": kv, "frequencies": sorted(fs)}
            for (s, kv), fs in sorted(freqs.items()) if len(fs) > 1]


def escape_distances(data: dict, sites: list, lines: list) -> dict:
    """敷地を一意に決められなかった構内配線(internal_way_without_unique_site のうち候補の敷地が
    1 つのもの)が、その敷地の柵から最も離れる距離(m)の分布。柵外 25 m の緩衝の妥当性を見る。"""
    import numpy as np
    import shapely

    geom = {key_of(f["properties"]["osm_type"], f["properties"]["osm_id"]): f["geometry"] for f in sites}
    coords = {key_of("way", f["properties"]["osm_id"]): f["geometry"]["coordinates"] for f in lines}
    bins, metres = Counter(), []
    for i in data["issues"]:
        if i["code"] != "internal_way_without_unique_site" or len(i["detail"].get("sites", [])) != 1:
            continue
        g, cs = geom.get(i["detail"]["sites"][0]), coords.get(i["entity_id"])
        if g is None or not cs:
            bins["unknown"] += 1
            continue
        k = np.array([max(math.cos(math.radians(g.representative_point().y)), 0.05), 1.0])
        local = shapely.transform(g, lambda xy: xy * k)
        m = max(local.distance(Point(*(np.array(c) * k))) for c in cs) * 111320
        metres.append(m)
        bins["<=25m" if m <= 25 else "<=40m" if m <= 40 else "<=60m" if m <= 60
             else "<=100m" if m <= 100 else ">100m"] += 1
    return {"bins": dict(bins), "median_m": round(float(np.median(metres)), 1) if metres else None,
            "n": len(metres)}


def gap_bins(gap: dict) -> dict:
    """全閉でもつながらない階級の、いちばん近い部分どうしの距離の分布。数 cm は描き手が結ぶつもりだった所
    (SubSLD の座標丸め 0.1 m なら接続になる)、数十 m 以上は描き漏れか別の構内。"""
    bins = Counter()
    for g in gap.values():
        m = g["gap_m"]
        bins["<0.1m" if m < 0.1 else "<1m" if m < 1 else "<10m" if m < 10 else "<50m" if m < 50 else ">=50m"] += 1
    return {"levels": len(gap), "bins": dict(bins),
            "between": dict(Counter(g["between"] for g in gap.values()).most_common())}


def _jsonable(o):
    return mapping(o) if hasattr(o, "geom_type") else str(o)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pbf", type=Path, default=ROOT / "data/osm_pbf/japan-power.osm.pbf")
    ap.add_argument("--source-md5", help="元の japan-latest.osm.pbf の md5(Geofabrik の .md5 と照合した値)")
    ap.add_argument("--out", type=Path, default=ROOT / "data/stations")
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data")
    ap.add_argument("--extension-m", type=float, default=EXTENSION_M,
                    help="柵の外へはみ出して描かれたベイ・母線を敷地に含める上限 m(0 で AU/EU の厳密な読み方)")
    a = ap.parse_args(argv)
    from src.stations.extract_pbf import read_cached, read_sites   # pyosmium(任意の依存 [stations])

    t0 = time.time()

    sites = read_sites(a.pbf)
    got = read_cached(a.pbf, sites, a.out / "read_cache.pkl")
    data = model(sites, got["lines"], got["elements"], extension_m=a.extension_m)
    views = analyse(data)
    cov = coverage(data, views)
    gap = gaps(data, views)
    xwalk = structure_crosswalk(a.data_dir)
    elapsed = round(time.time() - t0)

    site_props = {key_of(f["properties"]["osm_type"], f["properties"]["osm_id"]): f["properties"] for f in sites}
    matched = {k: v for k, v in xwalk.items() if k in site_props}
    eq_kind = Counter(e["kind"] for e in data["equipment"])
    winding_method = Counter(w["voltage_method"] for w in data["ends"])
    line_binding = Counter(b["binding"] for b in views["binding"].values())
    reaches = sum(1 for b in views["binding"].values() if b["reaches_busbar"])
    split_levels = sum(1 for v in views["levels"].values() if v["tn_mapped"] > 1)
    mixed = frequency_mix(data)
    summary = {
        "generated": date.today().isoformat(),
        "version": VERSION,
        "rules": {"buffer_m": 25.0, "extension_m": a.extension_m},
        "sites": {"total": len(sites), "by_power": dict(Counter(p.get("power") for p in site_props.values())),
                  "with_station_record": len(cov)},
        "status": dict(Counter(c["status"] for c in cov.values())),
        "rows": {k: len(v) for k, v in data.items() if isinstance(v, list) and k != "sites"},
        "equipment": dict(sorted(eq_kind.items())),
        "winding_voltage_method": dict(winding_method),
        "line_terminal_binding": dict(line_binding),
        "line_terminals_reaching_busbar_all_closed": reaches,
        "bays": dict(Counter(b["function"] for b in views["bays"])),
        "levels_split_with_all_switches_closed": split_levels,
        "split_level_gap_m": gap_bins(gap),
        "issues": dict(Counter(i["code"] for i in data["issues"]).most_common()),
        "internal_way_escape_distance": escape_distances(data, sites, got["lines"]),
        "frequency_mixed_levels": mixed,
        "crosswalk": {"structure_sites_total": sum(len(v) for v in xwalk.values()),
                      "osm_keys_total": len(xwalk), "osm_keys_found_in_pbf": len(matched)},
        "read": got["stats"],
        "elapsed_s": elapsed,
    }
    a.out.mkdir(parents=True, exist_ok=True)
    rows = {"summary": summary, "data": {k: v for k, v in data.items() if k != "sites"},
            "views": {k: v for k, v in views.items() if k not in ("attachments", "tn_of")},
            "coverage": cov, "gaps": gap, "crosswalk": matched,
            "site_names": {k: p.get("name") for k, p in site_props.items() if p.get("name")}}
    with gzip.open(a.out / "japan_rows.json.gz", "wt", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, default=_jsonable)
    (a.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n")
    manifest = {
        "generated": summary["generated"],
        "input": {"path": str(a.pbf.relative_to(ROOT)) if a.pbf.is_relative_to(ROOT) else str(a.pbf),
                  "sha256": sha256(a.pbf), "bytes": a.pbf.stat().st_size, **pbf_header(a.pbf),
                  "source": "https://download.geofabrik.de/asia/japan-latest.osm.pbf",
                  "source_md5": a.source_md5,
                  "filter": "osmium tags-filter japan-latest.osm.pbf nwr/power r/route=power",
                  "license": "ODbL 1.0 (© OpenStreetMap contributors)"},
        "code": {"version": VERSION, "rules": "docs/STATION_NODE_BREAKER.md",
                 "buffer_m": 25.0, "extension_m": a.extension_m},
        "output": {"rows": "data/stations/japan_rows.json.gz (untracked, D layer)"},
    }
    (a.out / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({k: summary[k] for k in ("sites", "status", "equipment", "issues", "elapsed_s")},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
