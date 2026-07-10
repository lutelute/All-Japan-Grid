#!/usr/bin/env python3
"""GitHub Pages 用エディタ(docs/editor.html)を **単一の正** から派生生成する。

全面改修Phase5フル統合の確定設計(docs/OVERHAUL_PLAN.md「静的shim方式」):
  正は1つ = src/server/templates/editor.html(フル機能の :8088 エディタ)。:8088 は無改修。
  本スクリプトは同テンプレを読み、
    (a) 絶対アセットパス(/js/, /static/)を Pages 相対へ rewrite、
    (b) 静的shim(docs/js/editor_static_shim.js)を本体inline <script> の **直前** に inject、
  して docs/editor.new.html を書く。shim が backend(:8088)無しのPages上で /api/* を
  静的JSON(docs/data/**)+ localStorage に振替えるため、**:8088 と同一のエディタ** が動く。

  本スクリプトは docs/ にのみ書き込み、テンプレートは一切変更しない(=:8088 を壊さない)。
  既定の出力は docs/editor.new.html。headless 検証で OK を確認してから docs/editor.html へ
  置換する(手順厳守=壊れた版を配信しない)。--out docs/editor.html で直接生成も可。

  併せて docs/data/built/regions_bbox.json(shim の /api/regions = regionAt 用)を生成する。

使い方:
    PYTHONPATH=. python scripts/build_pages_editor.py            # → docs/editor.new.html + bbox
    PYTHONPATH=. python scripts/build_pages_editor.py --out docs/editor.html
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "server", "templates", "editor.html")
DOCS = os.path.join(ROOT, "docs")
OUT_DEFAULT = os.path.join(DOCS, "editor.new.html")
BBOX_OUT = os.path.join(DOCS, "data", "built", "regions_bbox.json")
REGIONS_YAML = os.path.join(ROOT, "config", "regions.yaml")

# 本体inline <script>(アプリ起動)の直前に shim を差し込むためのアンカー。
# テンプレートが変わってここが見つからなければ fail-fast(暗黙に壊れた版を出さない)。
ANCHOR = "<script>\nconst qp = new URLSearchParams"
SHIM_TAG = ('<script src="js/editor_static_shim.js"></script>'
            '<!-- 全面改修Phase5: Pages静的shim(/api/*→静的JSON+localStorage・:8088は無改修) -->\n')


def build_html(out_path: str, template: str = SRC) -> None:
    with open(template, encoding="utf-8") as fh:
        html = fh.read()

    # (a) 絶対アセットパス → Pages 相対(project site 配下でも正しく解決)。
    html = html.replace('src="/js/editor_core.js"', 'src="js/editor_core.js"')
    html = html.replace('href="/static/', 'href="static/').replace('src="/static/', 'src="static/')

    # (b) 本体inline <script> の直前に shim を inject。
    if ANCHOR not in html:
        sys.exit("[build_pages_editor] ERROR: inline script アンカー未検出 — "
                 "templates/editor.html が変わった。ANCHOR を更新せよ(壊れた版は出さない)。")
    html = html.replace(ANCHOR, SHIM_TAG + ANCHOR, 1)

    # タイトルに下書きモードを明示(:8088 と取り違えない)。
    html = html.replace("<title>AGJ 接続編集プラットフォーム</title>",
                        "<title>AGJ 接続編集プラットフォーム(Pages 下書き)</title>")

    # (c) :8088 専用のツールダッシュボード導線を剥がす(Pages に /tools は無い=死にリンク)。
    tools_link = ' <a href="/tools"'
    if tools_link in html:
        import re
        html = re.sub(r' <a href="/tools".*?</a>', '', html, count=1)

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"[build_pages_editor] wrote {os.path.relpath(out_path, ROOT)} ({len(html):,} bytes)")


def build_bbox() -> None:
    import glob
    import yaml
    cfg = yaml.safe_load(open(REGIONS_YAML, encoding="utf-8"))
    out = {}
    for r, d in (cfg.get("regions") or {}).items():
        bb = d.get("bounding_box") or {}
        if all(k in bb for k in ("lat_min", "lat_max", "lon_min", "lon_max")):
            out[r] = {k: bb[k] for k in ("lat_min", "lat_max", "lon_min", "lon_max")}
    # island_class マニフェスト: docs/data/island_class/{region}.json が公開されている地域のみ。
    #   shim はこのリストに無い地域には fetch せず即404(存在しないファイルへの404コンソール汚染を回避)。
    ic_dir = os.path.join(DOCS, "data", "island_class")
    ic_list = sorted(os.path.splitext(os.path.basename(p))[0]
                     for p in glob.glob(os.path.join(ic_dir, "*.json")))
    os.makedirs(os.path.dirname(BBOX_OUT), exist_ok=True)
    with open(BBOX_OUT, "w", encoding="utf-8") as fh:
        json.dump({"regions": out, "island_class": ic_list}, fh, ensure_ascii=False)
    print(f"[build_pages_editor] wrote {os.path.relpath(BBOX_OUT, ROOT)} "
          f"({len(out)} regions, island_class={ic_list or 'none'})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT_DEFAULT, help="出力HTML(既定 docs/editor.new.html)")
    ap.add_argument("--template", default=SRC, help="入力テンプレ(既定=本番 editor.html・提案検証時のみ別指定)")
    ap.add_argument("--skip-bbox", action="store_true", help="regions_bbox.json 生成を省略")
    args = ap.parse_args()

    if not os.path.isfile(os.path.join(DOCS, "js", "editor_static_shim.js")):
        sys.exit("[build_pages_editor] ERROR: docs/js/editor_static_shim.js が無い(shim未配置)")
    if not os.path.isfile(args.template):
        sys.exit(f"[build_pages_editor] ERROR: テンプレが無い: {args.template}")
    build_html(args.out, template=args.template)
    if not args.skip_bbox:
        build_bbox()
