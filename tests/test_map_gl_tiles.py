"""MapLibre 版の系統図(docs/map_gl.html・試作 2026-11-07)が、Leaflet 版と同じ正典の層を同じ色で出すことを固定する.

- タイル(docs/data/map/grid.pmtiles)と英語名の表は scripts/build_map_gl_tiles.py が正典の層から作る。
  正典が進んだのに作り直していないと、タイルだけ古い線を出す(2026-10-21 に地図が基底 OSM を出していたのと同じ形)。
  元ファイルの sha256 を grid_gl.json に書いておき、今のファイルと比べる
- 色は js/grid_map.js と同じ(2 つのページで同じ電圧が違う色に見えないように)
- 足すファイルは合計 15 MB 以内(Pages の上限 1 GB が近い)
"""
import gzip
import hashlib
import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
MAP = DOCS / "data" / "map"
MANIFEST = json.loads((MAP / "grid_gl.json").read_text(encoding="utf-8"))


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_tiles_are_built_from_the_current_canon_layers():
    stale = [p for p, h in MANIFEST["sources"].items() if _sha(ROOT / p) != h]
    assert not stale, f"{stale} が変わった。python scripts/build_map_gl_tiles.py で作り直す"


def test_counts_cover_every_feature():
    for layer, path in (("lines", MAP / "lines_all.geojson"), ("subs", MAP / "subs_all.geojson"),
                        ("plants", DOCS / "data" / "plants_utility.geojson")):
        n = len(json.loads(path.read_text(encoding="utf-8"))["features"])
        assert MANIFEST["features"][layer] == n
        assert MANIFEST["counts"]["all"]["0"][layer] == n
    # 275 kV 以上は Leaflet 版が読む lines_275kv・subs_275kv と同じ件数
    for layer in ("lines", "subs"):
        n275 = len(json.loads((MAP / f"{layer}_275kv.geojson").read_text(encoding="utf-8"))["features"])
        assert MANIFEST["counts"]["all"]["275"][layer] == n275


def _pmtiles_header(path):
    raw = path.read_bytes()
    assert raw[:7] == b"PMTiles" and raw[7] == 3, "PMTiles v3 ではない"
    meta_off, meta_len = struct.unpack_from("<QQ", raw, 24)
    internal_comp, tile_comp, tile_type, min_z, max_z = raw[97], raw[98], raw[99], raw[100], raw[101]
    meta = raw[meta_off:meta_off + meta_len]
    if internal_comp == 2:
        meta = gzip.decompress(meta)
    return {"tile_type": tile_type, "min_z": min_z, "max_z": max_z, "meta": json.loads(meta)}


def test_pmtiles_has_three_layers_at_the_declared_zooms():
    h = _pmtiles_header(MAP / "grid.pmtiles")
    assert h["tile_type"] == 1, "ベクタータイル(MVT)ではない"
    assert [h["min_z"], h["max_z"]] == MANIFEST["zoom"]
    assert {v["id"] for v in h["meta"]["vector_layers"]} == {"lines", "subs", "plants"}


def test_added_files_stay_small():
    names = ["grid.pmtiles", "names_en.json", "grid_gl.json"]
    total = sum((MAP / n).stat().st_size for n in names)
    total += (DOCS / "map_gl.html").stat().st_size + (DOCS / "js" / "map_gl.js").stat().st_size
    assert total < 15e6, f"{total / 1e6:.1f} MB"


def test_names_en_come_from_osm():
    names = json.loads((MAP / "names_en.json").read_text(encoding="utf-8"))
    assert names and all(isinstance(v, str) and v.strip() and v != k for k, v in names.items())


def _colors(js, const):
    block = re.search(r"\b" + const + r"\s*=\s*\{(.*?)\};", js, re.S).group(1)
    return dict(re.findall(r"(\w+)\s*:\s*\"(#[0-9a-fA-F]{6})\"", block))


def test_colors_match_the_leaflet_map():
    gl = (DOCS / "js" / "map_gl.js").read_text(encoding="utf-8")
    lf = (DOCS / "js" / "grid_map.js").read_text(encoding="utf-8")
    for const in ("VOLTAGE_COLORS", "FUEL_COLORS"):
        assert _colors(gl, const) == _colors(lf, const), const
        assert _colors(gl, const)


def test_page_reads_canon_layers_and_pins_libraries():
    js = (DOCS / "js" / "map_gl.js").read_text(encoding="utf-8")
    assert "./data/map/lines_all.geojson" in js and "./data/map/grid.pmtiles" in js
    assert '"./data/lines_' not in js, "基底 OSM の層を読んでいる"
    html = (DOCS / "map_gl.html").read_text(encoding="utf-8")
    libs = re.findall(r'(?:src|href)="(https://[^"]+)"', html)
    assert libs and all(re.search(r"@\d+\.\d+\.\d+/", u) for u in libs), libs
