"""デモの一覧(docs/demos.json)と、1 枚で完結するデモのページ(docs/demos/*.html)が腐らないことを固定する。

desk(手元のアプリ)は docs/demos.json を読み、path のページを sandbox="allow-scripts" の枠と、外へ何も読ませない
CSP で開く。そのため、ページはデータを埋め込み、fetch・XHR・外のスクリプトや書体を使わない。
url のページは io(GitHub Pages)の公開のページで、docs/ に実在するものだけを載せる。
ページの作り直しは `PYTHONPATH=. python scripts/build_desk_demos.py`。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEMOS = json.loads((ROOT / "docs" / "demos.json").read_text(encoding="utf-8"))
PAGES = [p for s in DEMOS["series"] for p in s["pages"]]
IO = "https://lutelute.github.io/All-Japan-Grid/"


def test_shape():
    ids = [(s["id"], p["id"]) for s in DEMOS["series"] for p in s["pages"]]
    assert len(ids) == len(set(ids))
    for p in PAGES:
        assert isinstance(p["estimated"], bool), p["id"]
        assert p["variants"] and all({"id", "label", "query"} <= set(v) for v in p["variants"]), p["id"]
        assert ("path" in p) != ("url" in p), p["id"]
        assert len(p.get("badge", "")) <= 12 and len(p.get("headline", "")) <= 60 and len(p.get("caveat", "")) <= 300, p["id"]
        for v in p["variants"]:
            assert v["query"] == "" or re.fullmatch(r"\?[\w=&.-]+", v["query"]), v


@pytest.mark.parametrize("page", [p for p in PAGES if "url" in p], ids=lambda p: p["id"])
def test_io_pages_exist(page):
    assert page["url"].startswith(IO)
    rel = page["url"][len(IO):].split("?")[0].split("#")[0]
    assert (ROOT / "docs" / rel).is_file(), rel


@pytest.mark.parametrize("page", [p for p in PAGES if "path" in p], ids=lambda p: p["id"])
def test_embedded_pages_are_self_contained(page):
    path = ROOT / page["path"]
    assert page["path"].startswith("docs/demos/") and path.suffix == ".html" and path.is_file()
    html = path.read_text(encoding="utf-8")
    assert "/*__" not in html, "テンプレートの差し込み口が残っている"
    assert "const D = {" in html, "データが埋め込まれていない"
    for bad in ("fetch(", "XMLHttpRequest", "WebSocket", "<script src", "<link ", "@import", "http://", "https://", "window.open", "localStorage"):
        assert bad not in html, bad
    assert not page.get("script_hosts") and not page.get("tile_hosts") and not page.get("font_hosts")
    for need in page.get("needs", []):
        if "/" in need and "{" not in need and not need.startswith("git"):
            assert (ROOT / need).exists(), need
