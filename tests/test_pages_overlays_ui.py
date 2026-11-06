"""系統図マップ(map.html)の「重ねて見る」に足した層(js/overlay_layers.js、2026-11-07)をブラウザで確かめる。

  - 線と点の層を点けても、地図の描画面(canvas)は 1 枚のまま(js/agj_map.js の決まり)
  - 点けると凡例と出典が地図の左下に出て、公表値は「公表」、計算は「計算」と書かれる
  - 全部消すと、層の数が元に戻り、凡例も消える
  - タイルの層(災害・土地)は専用の pane に入り、透過度のスライダーが効く(タイルそのものは外のサイトなので、
    届くかどうかは確かめない)

test_pages_map_ui.py と同じく、Playwright と Chromium が無い環境では飛ばす。
"""
from __future__ import annotations

import functools
import http.server
import os
import threading
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"

sync_api = pytest.importorskip("playwright.sync_api")

VECTOR = {"ic": "連系線の運用容量と値差", "obs": "送電線の潮流の実績", "load": "送電線の混み具合",
          "price": "エリアの価格", "demand": "エリアの需要"}
TILES = ["tsunami", "flood", "hightide", "sediment", "relief", "landuse"]


@pytest.fixture(scope="module")
def site():
    remote = os.environ.get("AGJ_SITE_URL")
    if remote:
        yield remote.rstrip("/")
        return

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(Quiet, directory=str(DOCS))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 — ブラウザ本体が入っていない
            pytest.skip(f"Chromium を起動できない: {e}")
        yield b
        b.close()


def _open(browser, site):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{site}/map.html")
    try:
        page.wait_for_function("() => window.map && window.lineLayer && window.AGJOverlays", timeout=60_000)
    except sync_api.Error:
        page.close()
        pytest.skip("地図のデータか Leaflet(unpkg)を読み込めない")
    return page, errors


def _set(page, key, on):
    page.evaluate("([k, on]) => { const cb = document.querySelector(`input[data-ov=\"${k}\"]`);"
                  " cb.checked = on; cb.dispatchEvent(new Event('change')); }", [key, on])


def _wait_loaded(page):
    page.wait_for_function("() => ![...document.querySelectorAll('[data-ov-status]')]"
                           ".some(e => /読み込み中|読めません/.test(e.textContent))", timeout=60_000)


def _count_layers(page):
    return page.evaluate("() => { let n = 0; map.eachLayer(() => n++); return n; }")


def test_vector_overlays_one_canvas_and_legend(browser, site):
    page, errors = _open(browser, site)
    n0 = _count_layers(page)
    for k in VECTOR:
        _set(page, k, True)
    _wait_loaded(page)
    page.wait_for_timeout(500)
    canv = page.evaluate("() => map.getContainer().querySelectorAll('.leaflet-pane canvas').length")
    assert canv == 1, f"地図の描画面が {canv} 枚ある"
    legend = page.inner_text(".agj-ov-legend")
    for title in VECTOR.values():
        assert title in legend, f"凡例に {title} が無い"
    assert "出典" in legend
    assert _count_layers(page) > n0
    for k in VECTOR:
        _set(page, k, False)
    page.wait_for_timeout(300)
    assert _count_layers(page) == n0, "消したあとに層が残っている"
    assert page.query_selector(".agj-ov-legend") is None, "消したあとに凡例が残っている"
    assert not errors, errors
    page.close()


def test_observed_and_derived_are_labeled_apart(browser, site):
    page, errors = _open(browser, site)
    _set(page, "obs", True)
    _set(page, "load", True)
    _wait_loaded(page)
    tags = page.evaluate("""() => [...document.querySelectorAll('.agj-ov-legend .ov-sec')].map(s => ({
        h: s.querySelector('.ov-h').textContent, calc: !!s.querySelector('.ov-tag-calc')}))""")
    by = {t["h"]: t["calc"] for t in tags}
    obs = [h for h in by if h.startswith("送電線の潮流の実績")]
    calc = [h for h in by if h.startswith("送電線の混み具合")]
    assert obs and "公表" in obs[0] and not by[obs[0]], tags
    assert calc and "計算" in calc[0] and by[calc[0]], tags
    # 公表の実績は実線、計算は破線
    styles = page.evaluate("""() => { const s = {solid: 0, dashed: 0};
        map.eachLayer(l => { if (l instanceof L.Polyline && l.options.interactive !== false) {
            if (l.options.color === '#f0f6fc') s.solid += l.options.dashArray ? 0 : 1;
            if (l.options.color === '#ffe14d') s.dashed += l.options.dashArray ? 1 : 0; } });
        return s; }""")
    assert styles["solid"] > 100 and styles["dashed"] > 100, styles
    assert not errors, errors
    page.close()


def test_tile_overlays_use_own_panes_and_opacity(browser, site):
    page, errors = _open(browser, site)
    for k in TILES:
        _set(page, k, True)
    page.wait_for_timeout(500)
    n_haz = page.evaluate("() => map.getPane('agjOvHazard').querySelectorAll('.leaflet-layer').length")
    n_land = page.evaluate("() => map.getPane('agjOvLand').querySelectorAll('.leaflet-layer').length")
    assert n_haz == 6, n_haz          # 津波・洪水・高潮・土砂(3 枚)
    assert n_land == 2, n_land        # 赤色立体地図・土地利用
    page.evaluate("() => { const s = document.querySelector('input[data-ov-opacity=\"hazard\"]');"
                  " s.value = 30; s.dispatchEvent(new Event('input')); }")
    ops = page.evaluate("() => [...map.getPane('agjOvHazard').querySelectorAll('.leaflet-layer')].map(e => e.style.opacity)")
    assert set(ops) == {"0.3"}, ops
    attrib = page.inner_text(".leaflet-control-attribution")
    assert "ハザードマップポータルサイト" in attrib and "国土地理院" in attrib, attrib
    for k in TILES:
        _set(page, k, False)
    page.wait_for_timeout(300)
    assert page.evaluate("() => map.getPane('agjOvHazard').querySelectorAll('.leaflet-layer').length") == 0
    assert not errors, errors
    page.close()
