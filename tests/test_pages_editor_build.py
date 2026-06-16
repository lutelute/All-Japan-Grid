"""全面改修Phase5フル統合の不変条件を固定するテスト。

「正は1つ = src/server/templates/editor.html(:8088フルエディタ)。Pagesは派生」を構造保証する:
  1. build_pages_editor が shim を inject し絶対アセットパスを Pages相対へ rewrite する。
  2. 公開中の docs/editor.html は **テンプレからの派生と一致**(手編集ドリフトの禁止)。
     → テンプレを変えたら必ず再生成する規律を CI/テストで強制(二度と分岐させない)。
  3. regions_bbox.json(shim の /api/regions = regionAt 用)が全地域 + island_class マニフェストを持つ。
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "scripts", "build_pages_editor.py")
DOCS_EDITOR = os.path.join(ROOT, "docs", "editor.html")
TEMPLATE = os.path.join(ROOT, "src", "server", "templates", "editor.html")
SHIM = os.path.join(ROOT, "docs", "js", "editor_static_shim.js")


def _build(out_path, skip_bbox=True):
    argv = [sys.executable, BUILD, "--out", out_path]
    if skip_bbox:
        argv.append("--skip-bbox")
    subprocess.run(argv, cwd=ROOT, check=True)
    with open(out_path, encoding="utf-8") as fh:
        return fh.read()


def test_shim_injected_and_asset_paths_relative(tmp_path):
    html = _build(str(tmp_path / "editor.test.html"))
    # 静的shim が本体inline script の直前に inject されている
    assert '<script src="js/editor_static_shim.js"></script>' in html
    # editor_core.js は Pages相対へ rewrite(絶対 /js/ は残さない)
    assert 'src="js/editor_core.js"' in html
    assert 'src="/js/' not in html
    # フルエディタの証跡(:8088 由来の /api 呼び出し・編集機能)が保たれている
    assert "/api/built/" in html and "/api/edits" in html
    assert "verifyEdits" in html and "toggleCandidates" in html


def test_committed_pages_editor_has_no_drift(tmp_path):
    """docs/editor.html は templates/editor.html からの派生と完全一致でなければならない。

    不一致 = テンプレを変えたのに Pages を再生成していない(ドリフト)。
    `PYTHONPATH=. python scripts/build_pages_editor.py --out docs/editor.html` で解消する。
    """
    fresh = _build(str(tmp_path / "editor.fresh.html"))
    with open(DOCS_EDITOR, encoding="utf-8") as fh:
        committed = fh.read()
    assert fresh == committed, (
        "docs/editor.html がテンプレ派生と不一致(ドリフト)。"
        "`python scripts/build_pages_editor.py --out docs/editor.html` で再生成せよ。"
    )


def test_template_is_the_single_source(tmp_path):
    """テンプレ(:8088の正)が存在し、shim も配置済みであること(派生の前提)。"""
    assert os.path.isfile(TEMPLATE), "テンプレ(単一の正)が無い"
    assert os.path.isfile(SHIM), "editor_static_shim.js(Pages派生の核)が無い"
    # テンプレ自身は shim を読まない(:8088 は backend を使う=無改修)
    with open(TEMPLATE, encoding="utf-8") as fh:
        tmpl = fh.read()
    assert "editor_static_shim.js" not in tmpl, ":8088テンプレに shim が混入している(無改修原則の違反)"


def test_regions_bbox_manifest(tmp_path):
    out = str(tmp_path / "bbox_editor.html")
    # bbox 生成を含めて実行(--skip-bbox を付けない)。出力先は docs/data/built/regions_bbox.json 固定。
    subprocess.run([sys.executable, BUILD, "--out", out], cwd=ROOT, check=True)
    bbox_path = os.path.join(ROOT, "docs", "data", "built", "regions_bbox.json")
    with open(bbox_path, encoding="utf-8") as fh:
        meta = json.load(fh)
    assert "regions" in meta and "island_class" in meta
    # 4周波数島の代表地域が揃っている(regionAt が全国編集を正しく振り分けられる)
    for r in ("hokkaido", "tohoku", "tokyo", "kansai", "kyushu", "okinawa"):
        b = meta["regions"].get(r)
        assert b and all(k in b for k in ("lat_min", "lat_max", "lon_min", "lon_max"))
    assert isinstance(meta["island_class"], list)
