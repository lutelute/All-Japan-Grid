"""MapLibre 版の系統図(docs/map_gl.html・試作)を実際のブラウザで開き、描画・ホバー・クリック・日英の切り替えを確かめる.

map.html の Leaflet 版は半年ホバーとクリックが効かなかった(tests/test_pages_map_ui.py)。同じことを
こちらで起こさないように、操作して確かめる。WebGL が使えない Chromium では飛ばす。

PMTiles は HTTP の Range で読むので、配信には Range を返す小さなサーバーを使う(python の http.server は返さない)。
MapLibre と pmtiles は unpkg から読むので、ネットワークも要る。背景の地理院タイルは空の画像に差し替える。
"""
from __future__ import annotations

import base64
import functools
import http.server
import os
import re
import threading
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"

sync_api = pytest.importorskip("playwright.sync_api")

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        rng = self.headers.get("Range")
        path = self.translate_path(self.path)
        if not rng or not os.path.isfile(path):
            return super().do_GET()
        size = os.path.getsize(path)
        m = re.match(r"bytes=(\d*)-(\d*)", rng)
        start = int(m.group(1)) if m.group(1) else size - int(m.group(2))
        end = min(int(m.group(2)) if m.group(1) and m.group(2) else size - 1, size - 1)
        with open(path, "rb") as f:
            f.seek(start)
            body = f.read(end - start + 1)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def site():
    remote = os.environ.get("AGJ_SITE_URL")
    if remote:
        yield remote.rstrip("/")
        return
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(RangeHandler, directory=str(DOCS)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            # CI の Chromium は GPU が無いので、WebGL を SwiftShader で描かせる
            b = p.chromium.launch(args=["--enable-unsafe-swiftshader", "--use-angle=swiftshader"])
        except Exception as e:  # noqa: BLE001 — ブラウザ本体が入っていない
            pytest.skip(f"Chromium を起動できない: {e}")
        yield b
        b.close()


def _open(browser, url):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.route(re.compile(r"cyberjapandata\.gsi\.go\.jp"), lambda r: r.fulfill(status=200, content_type="image/png", body=PNG))
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.goto(url)
    if page.evaluate("() => !document.createElement('canvas').getContext('webgl2')"):
        page.close()
        pytest.skip("この Chromium では WebGL2 が使えない")
    try:
        page.wait_for_function("() => window.AGJ_GL && window.AGJ_GL.ready", timeout=90_000)
    except sync_api.Error:
        page.close()
        pytest.skip("地図のデータか MapLibre(unpkg)を読み込めない")
    return page, errors


# 線・変電所の上で、その層がいちばん上に当たる画面上の点を探す
_PICK = """
([layer]) => {
  const m = window.agjMap, rect = m.getCanvas().getBoundingClientRect();
  for (const f of m.queryRenderedFeatures({ layers: [layer] })) {
    // タイルで切れた線は MultiLineString で返ることがある
    const g = f.geometry, cs = g.type === 'Point' ? [g.coordinates] : g.type === 'MultiLineString' ? g.coordinates.flat() : g.coordinates;
    for (const c of cs) {
      const p = m.project(c);
      if (p.x < 60 || p.y < 60 || p.x > rect.width - 420 || p.y > rect.height - 60) continue;
      const hit = m.queryRenderedFeatures([[p.x - 6, p.y - 6], [p.x + 6, p.y + 6]], { layers: ['agj-plants', 'agj-subs', 'agj-lines'] });
      if (hit.length && hit[0].layer.id === layer) return { x: rect.left + p.x, y: rect.top + p.y };
    }
  }
  return null;
}
"""


def _n_features(kind: str, tier: str) -> str:
    """地図のデータ(docs/data/map/<kind>_<tier>.geojson)の件数を、画面と同じ桁区切りで返す。
    正典が変わるたびに数を書き直さなくてよいように、固定の数ではなくデータと比べる(#58 で 19,909 → 17,391)。"""
    import json
    with open(DOCS / "data" / "map" / f"{kind}_{tier}.geojson", encoding="utf-8") as fh:
        return f"{len(json.load(fh)['features']):,}"


def _hover(page, xy):
    page.mouse.move(xy["x"] - 40, xy["y"] - 40)
    page.mouse.move(xy["x"], xy["y"], steps=4)
    page.wait_for_timeout(200)
    return page.evaluate("() => { const t = document.getElementById('tip'); return t.hidden ? null : t.textContent; }")


@pytest.mark.parametrize("src", ["pmtiles", "geojson"])
def test_draws_and_counts(browser, site, src):
    page, errors = _open(browser, f"{site}/map_gl.html?lang=ja&src={src}#6/34.7/135.5")
    n = page.evaluate("() => agjMap.queryRenderedFeatures({ layers: ['agj-lines'] }).length")
    status = page.inner_text("#status")
    page.close()
    assert n > 100, n
    # 275 kV 以上(Leaflet 版と同じ件数 = 地図のデータの件数)
    assert f"変電所 {_n_features('subs', '275kv')}" in status and f"送電線 {_n_features('lines', '275kv')}" in status, status
    assert not errors, errors


def test_hover_click_and_language(browser, site):
    page, errors = _open(browser, f"{site}/map_gl.html?lang=ja#7/34.7/135.5")
    line = page.evaluate(_PICK, ["agj-lines"])
    sub = page.evaluate(_PICK, ["agj-subs"])
    assert line and sub
    assert (_hover(page, line) or "").startswith("送電線 ")
    assert (_hover(page, sub) or "").startswith("変電所 ")

    page.mouse.click(line["x"], line["y"])
    page.wait_for_timeout(200)
    card = page.inner_text("#card")
    assert "送電線" in card and "回線数" in card and "つながり" in card

    page.click('#seg-lang button[data-v="en"]')
    page.wait_for_timeout(100)
    card = page.inner_text("#card")
    assert "Transmission line" in card and "Circuits" in card and "Connection" in card
    assert "?lang=en" in page.url and re.search(r"#7(\.\d+)?/34\.7\d*/135\.5", page.url), page.url

    page.click('#seg-kv button[data-v="0"]')
    page.wait_for_timeout(300)
    assert f"{_n_features('lines', 'all')} lines" in page.inner_text("#status")
    page.close()
    assert not errors, errors
