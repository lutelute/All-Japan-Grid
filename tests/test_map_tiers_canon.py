"""系統図マップの線と変電所は、正典(docs/data/built/all.json)から書いた層を出す。

2026-10-21 まで、地図は介入を当てる前の基底 OSM を出していた。正典から書く
scripts/export_map_tiers_from_built.py と、基底 OSM から書く build_static_site.py が同じ名前
(docs/data/lines_*・subs_*)に書き、deploy でも regenerate_all でも後者が後に走っていたため。
正典の層は docs/data/map/ に分けた(docs/PAGES_INVENTORY.md・docs/reports/project_structure_2026-10-21.md)。
"""
import json
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"
MAP = DOCS / "data" / "map"


@pytest.fixture(scope="module")
def built():
    return json.loads((DOCS / "data" / "built" / "all.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def lines_all():
    return json.loads((MAP / "lines_all.geojson").read_text(encoding="utf-8"))["features"]


def test_map_page_reads_canon_tiers():
    js = (DOCS / "js" / "grid_map.js").read_text(encoding="utf-8")
    assert '"./data/map/lines_"' in js and '"./data/map/subs_"' in js
    assert '"./data/lines_"' not in js, "基底 OSM の層を読んでいる"


def test_lines_match_canon_edges(built, lines_all):
    # 形の無い枝(点 1 つ)は書かないので、正典の枝の数をわずかに下回るだけ
    edges = built["edges"]
    assert 0.97 * len(edges) <= len(lines_all) <= len(edges)


def test_canon_corrections_show_on_the_map(lines_all):
    # 介入#51: 西島根の 275 kV は一次資料で誤り → 220 kV。地図にも 275 kV で出さない
    bad = [f["properties"] for f in lines_all
           if "西島根" in (f["properties"].get("_display_name") or "")
           and f["properties"].get("_voltage_kv") == 275.0]
    assert not bad, bad
