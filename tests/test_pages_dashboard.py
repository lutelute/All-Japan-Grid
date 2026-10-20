"""Pages ダッシュボード(docs/index.html)が腐らないことを固定する.

2026-09 の棚卸しで、戻り導線の無いページ8枚・どこからも辿れないページ2枚・
HTMLに直書きされた古い版番号やバス数が見つかった。原因は「ページを足しても入口に
載せる仕組みが無い」「数字を手で書く」の2点だったので、その2点をテストで塞ぐ。
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
CATALOG = json.loads((DOCS / "data" / "tools_catalog.json").read_text(encoding="utf-8"))
TOOLS = CATALOG["tools"]
KINDS = {"pages", "local", "cli", "report"}


def _id(tool):
    return tool["id"]


def test_catalog_ids_unique_and_categories_known():
    ids = [t["id"] for t in TOOLS]
    assert len(ids) == len(set(ids))
    cats = {c["id"] for c in CATALOG["categories"]}
    for t in TOOLS:
        assert t["category"] in cats, t["id"]
        assert t["kind"] in KINDS, t["id"]
        assert t["title"] and t["summary"], t["id"]


def test_every_category_has_a_tool():
    used = {t["category"] for t in TOOLS}
    assert used == {c["id"] for c in CATALOG["categories"]}


@pytest.mark.parametrize("tool", [t for t in TOOLS if t.get("href")], ids=_id)
def test_pages_href_exists(tool):
    """カードのリンク先(docs/ 相対)が実在する。#tab-… は map.html のタブ名と一致する。"""
    path, _, frag = tool["href"].partition("#")
    assert (DOCS / path).is_file(), tool["href"]
    if frag:
        assert f'data-tab="{frag}"' in (DOCS / path).read_text(encoding="utf-8"), tool["href"]


@pytest.mark.parametrize("tool", [t for t in TOOLS if t.get("doc") or t.get("source")], ids=_id)
def test_doc_and_source_exist(tool):
    for key in ("doc", "source"):
        if tool.get(key):
            assert (ROOT / tool[key]).exists(), f"{tool['id']}.{key} = {tool[key]}"


@pytest.mark.parametrize("tool", [t for t in TOOLS if t["kind"] == "cli"], ids=_id)
def test_cli_command_points_at_real_script(tool):
    """コピーさせるコマンドが存在しないスクリプトを指さない。"""
    cmd = tool["command"]
    scripts = re.findall(r"(?:scripts|examples)/[\w/.-]+\.(?:py|sh|mjs)", cmd)
    assert scripts or cmd.startswith("ajgrid "), cmd
    for s in scripts:
        assert (ROOT / s).is_file(), f"{tool['id']}: {s}"


def test_local_tools_have_local_href():
    for t in TOOLS:
        if t["kind"] == "local":
            assert t.get("local_href", "").startswith("/"), t["id"]


def test_no_orphan_pages():
    """docs/ 直下の HTML は、カタログに載せるか、載せない理由を明記するかのどちらか。"""
    listed = {t["href"].partition("#")[0] for t in TOOLS if t.get("href")}
    excused = set(CATALOG["legacy_pages"]) | set(CATALOG["embedded_pages"]) | {"index.html"}
    pages = {p.name for p in DOCS.glob("*.html")}
    assert pages - listed - excused == set()
    assert excused - pages == set(), "存在しないページが除外リストに残っている"


def test_standalone_pages_link_back_to_dashboard():
    """単独で開くページには必ずダッシュボードへの戻り口がある(生成物の editor.html は親タブが持つ)。"""
    for name in {t["href"].partition("#")[0] for t in TOOLS if t.get("href")}:
        if "/" in name:            # slides/ 配下は自己完結の発表資料
            continue
        html = (DOCS / name).read_text(encoding="utf-8")
        assert re.search(r'href="(\./)?index\.html"', html), name


def test_dashboard_reads_numbers_from_data():
    """ダッシュボードに版番号やノード数を直書きしない(data/*.json から読む)。"""
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    assert "data/dashboard.json" in html and "data/tools_catalog.json" in html
    assert not re.search(r"v\d+\.\d+\.\d+", html)
    assert not re.search(r"\d{1,2},\d{3}\s*(ノード|バス|母線)", html)


def test_map_page_has_no_hardcoded_model_size():
    html = (DOCS / "map.html").read_text(encoding="utf-8")
    assert not re.search(r"\d{1,2},\d{3}\s*(ノード|バス)", html)
    assert not re.search(r"releases/tag/v\d", html)


def test_dashboard_data_generator():
    from scripts import build_dashboard_data as gen

    data = gen.build()
    assert data["version"] and data["dataset_version"]
    assert data["model"]["n_nodes"] > 10_000
    assert data["interventions"] >= 30
    recent = data["reports"]["recent"]
    assert recent and recent == sorted(recent, key=lambda r: r["date"], reverse=True)
    for r in recent:
        assert (ROOT / r["path"]).is_file()
    for b in data["bundles"]:
        assert (DOCS / b["href"]).is_file()


@pytest.mark.parametrize("tool", [t for t in TOOLS if t.get("image")], ids=_id)
def test_card_image_exists(tool):
    """カードの画像(docs/ 相対・scripts/make_dashboard_thumbs.py が作る)が実在する。"""
    assert (DOCS / tool["image"]).is_file(), tool["image"]


# ── カードが読むデータの系譜(2026-10-21) ─────────────────────────────
# 全体構造の分析(docs/reports/project_structure_2026-10-21.md)で、地図が基底 OSM を出していた(D1)、
# 「MATPOWER ケースを書き出す」が比較用の旧系譜を指していた(B1)ことが分かった。どちらも
# 「正典を読んでいるはず」と思われていたのが原因なので、系譜をカタログに書かせて検査する。
LINEAGES = {"built", "stations", "snapped", "base_osm", "frozen", "mixed", "text"}
NEEDS_NOTE = LINEAGES - {"built", "stations", "text"}
LEGACY_IMPORT = re.compile(
    r"^\s*(?:from\s+\S+\s+)?import\s+.*\b(build_network_snapped|build_and_solve|ReconstructionConfig)\b", re.M)


@pytest.mark.parametrize("tool", TOOLS, ids=_id)
def test_lineage_is_declared(tool):
    assert tool.get("lineage") in LINEAGES, f"{tool['id']}: lineage を {sorted(LINEAGES)} から書く"
    if tool["lineage"] in NEEDS_NOTE:
        assert tool.get("lineage_note"), f"{tool['id']}: 正典と何が違うかを lineage_note に書く"


@pytest.mark.parametrize("tool", [t for t in TOOLS if (t.get("source") or "").endswith(".py")], ids=_id)
def test_lineage_matches_source_imports(tool):
    """旧系譜の網を組む関数を import するソースは、built と名乗れない(逆も)。"""
    legacy = LEGACY_IMPORT.findall((ROOT / tool["source"]).read_text(encoding="utf-8"))
    if tool["lineage"] == "built":
        assert not legacy, f"{tool['id']}: built なのに {legacy} を import している"
    if legacy:
        assert tool["lineage"] in {"snapped", "mixed", "frozen"}, f"{tool['id']}: {legacy} → lineage={tool['lineage']}"


def test_matpower_card_points_at_the_distributed_case():
    """配布物(dist/matpower_national)を作る正本を指す。配布物に gencost は無い(dataset/01 の README)。"""
    t = next(t for t in TOOLS if t["id"] == "matpower")
    assert t["source"] == "scripts/export_matpower_canonical.py"
    assert "export_matpower_canonical.py" in t["command"]
    assert "runopf にそのまま" not in t["summary"] and "GENCOST つき" not in t["summary"]


def test_lineage_badge_is_rendered():
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    assert "LINEAGE_LABEL[t.lineage]" in html and "t.lineage_note" in html
