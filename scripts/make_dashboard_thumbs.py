#!/usr/bin/env python3
"""ダッシュボードのツールカードに載せる静止画を作る.

- 今も更新しているページ(SHOTS)は、手元で docs/ を配信して今の画面を撮る(Playwright)。
  README の GIF は旧 UI のままのものがあるため
- 更新を止めたページ(FRAMES)は、README の GIF(docs/assets/gif、0.1〜3.7 MB)から 1 コマ切り出す
どちらも 16:10 に切り抜き、幅 640 の JPEG にする。元の GIF は変えない(書き出すのは
docs/assets/thumbs/ の新しいファイルだけ)。

    python3 scripts/make_dashboard_thumbs.py            # 全部
    python3 scripts/make_dashboard_thumbs.py --no-shots # GIF のコマだけ(Playwright 無しで動く)

どのカードにどの画像を出すかは docs/data/tools_catalog.json の各ツールの "image"。
"""
from __future__ import annotations

import argparse
import functools
import http.server
import io
import threading
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "assets" / "gif"
OUT = ROOT / "docs" / "assets" / "thumbs"
W, H = 640, 400

# 出力名: (GIF, 何割の位置のコマか)。割合は、絵がいちばん伝わるコマを目で見て決めた
FRAMES = {
    "flow_map": ("flow.gif", 0.45),          # 関東の潮流を細かく(潮流マップの中の画面)
    "compare": ("compare.gif", 0.7),
    "review": ("review.gif", 0.5),
    "dynamics": ("dynamics_swing.gif", 0.5),
}

# 出力名: 毎時作られる静止画(docs/ からの相対)。「日本の送電網、いま」は光る潮流の
# pulse.png(scripts/export_pulse.py)から切り出す
# (ファイル, 切り出す範囲 = 左・上・右・下 を幅と高さの割合で)
STILLS = {
    "pulse": ("data/flow_map/pulse.png", (0.10, 0.36, 0.98, 0.91)),   # 九州〜東北の南
}

# 出力名: (ページ, 開いたあとに走らせる JS, 待つ ms)。画面は 1280×800 で撮る
SHOTS = {
    # 地図だけを見せる(サイドバー・一覧・凡例を閉じる)
    "map": ("map.html", "toggleSidebar(); toggleListPanel(false); toggleLegend(); map.invalidateSize();"
            " map.setView([35.4, 136.6], 7);", 3500),
    "subsld": ("subsld.html", "", 4000),
    "ybus_sim": ("map.html#tab-ybus", "", 6000),
}


def frame(path: Path, at: float) -> Image.Image:
    im = Image.open(path)
    n = getattr(im, "n_frames", 1)
    im.seek(min(n - 1, int(round(at * (n - 1)))))
    return im.convert("RGB")


def cover(im: Image.Image, w: int, h: int) -> Image.Image:
    """縦横比を保って w×h を覆うように縮め、中央を切り抜く。"""
    s = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def save(im: Image.Image, name: str) -> None:
    out = OUT / f"{name}.jpg"
    cover(im, W, H).save(out, "JPEG", quality=82, optimize=True, progressive=True)
    print(f"{out.relative_to(ROOT)}  {out.stat().st_size / 1024:.0f} KB")


def shots() -> None:
    from playwright.sync_api import sync_playwright

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    httpd = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Quiet, directory=str(ROOT / "docs")))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}/"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for name, (page_path, js, wait) in SHOTS.items():
                page = browser.new_page(viewport={"width": 1280, "height": 800})
                page.goto(base + page_path, wait_until="networkidle", timeout=90_000)
                page.wait_for_timeout(1500)
                if js:
                    page.evaluate(f"() => {{ {js} }}")
                page.wait_for_timeout(wait)
                save(Image.open(io.BytesIO(page.screenshot())).convert("RGB"), name)
                page.close()
            browser.close()
    finally:
        httpd.shutdown()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-shots", action="store_true", help="今のページは撮らない(GIF のコマだけ)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (gif, at) in FRAMES.items():
        save(frame(SRC / gif, at), name)
    for name, (rel, (l, t, r, b)) in STILLS.items():
        im = Image.open(ROOT / "docs" / rel).convert("RGB")
        save(im.crop((round(l * im.width), round(t * im.height), round(r * im.width), round(b * im.height))), name)
    if not args.no_shots:
        shots()


if __name__ == "__main__":
    main()
