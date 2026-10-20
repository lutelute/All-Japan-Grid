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


# ── Ybus / N-1 タブと潮流の出力も正典から(2026-10-21・D3) ─────────────────────
# N-1 の表は旧系譜(地域別のスナップ済みの網・06-03)、潮流の出力 powerflow_full は 08-28 の正典
# (17,745 ノード・19,895 枝)のままだった。正典が進んだら作り直す。

ISLANDS = {"hokkaido", "east", "west", "okinawa"}


def test_powerflow_full_is_from_the_current_canon(built):
    meta = json.loads((DOCS / "data" / "powerflow_full" / "summary.json").read_text(encoding="utf-8"))["_meta"]
    assert (meta["n_nodes"], meta["n_edges"]) == (len(built["nodes"]), len(built["edges"])), \
        f"powerflow_full は {meta['generated']} の正典から計算したまま(scripts/run_full_powerflow_from_db.py で作り直す)"


def test_n1_tab_reads_the_canonical_screening():
    html = (DOCS / "map.html").read_text(encoding="utf-8")
    assert "./data/n1_canon/summary.json" in html
    legacy = html.index('<details id="n1-legacy"')
    assert legacy < html.index("./data/n1/n1_summary.csv"), "旧系譜の N-1 の表は「記録」の折りたたみの中に置く"


def test_n1_summary_is_from_the_latest_report():
    reports = sorted((DOCS / "reports").glob("n1_screening_????-??-??.json"))
    s = json.loads((DOCS / "data" / "n1_canon" / "summary.json").read_text(encoding="utf-8"))
    assert s["source"] == f"docs/reports/{reports[-1].name}", "scripts/export_n1_pages.py で書き直す"
    assert {i["island"] for i in s["islands"]} == ISLANDS
    for i in s["islands"]:
        for row in i["top"] + i["ac_verify"]:
            assert not row["label"].startswith("trafo_") and row["label"] != "namebind", row["label"]
