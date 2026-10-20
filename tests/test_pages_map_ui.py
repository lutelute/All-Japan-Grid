"""Pages の地図を実際のブラウザで開き、ホバーとクリックで説明が出るかを確かめる。

2026-04-02(3e014ab7)から半年、map.html の送電線と変電所はホバーもクリックも効かなかった。
発電所用の canvas が上に重なってマウスを全部取っていたためで、構文検査
(test_flow_map_integrity の node --check)では見つからなかった。ここでは
  - 地図の上の描画面(canvas)が 1 枚だけであること
  - 送電線・変電所・発電所の上にマウスを置くと、それぞれの説明が出ること
  - 送電線をクリックすると詳しい説明が出ること
  - 直リンク map.html#tab-ybus / #tab-sld で中身が起動すること
を確かめる(docs/PAGES_INVENTORY.md §3)。

Playwright と Chromium が無い環境では飛ばす(CI では .github/workflows/pages-ui.yml が入れて回す)。
公開サイトに向けるときは AGJ_SITE_URL を渡す(既定は手元の docs/ を配信して確かめる)。
Leaflet は unpkg から読むので、ネットワークも要る。
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


@pytest.fixture(scope="module")
def site():
    # 公開サイトで確かめるとき: AGJ_SITE_URL=https://lutelute.github.io/All-Japan-Grid
    remote = os.environ.get("AGJ_SITE_URL")
    if remote:
        yield remote.rstrip("/")
        return
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(Quiet, directory=str(DOCS))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
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


def _open_map(browser, url):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url)
    try:
        page.wait_for_function("() => window.L && window.map && window.lineLayer && window.substationLayer"
                               " && window.plantLayer && window.substationLayer.getLayers().length > 0",
                               timeout=60_000)
    except sync_api.Error:
        page.close()
        pytest.skip("地図のデータか Leaflet(unpkg)を読み込めない")
    return page, errors


# 点の層の上下関係を崩さずに、まわりに他の点が無い位置を探す(画面座標)
_PICK = """
([kind]) => {
  const rect = map.getContainer().getBoundingClientRect();
  const size = map.getSize();
  const pts = [];
  for (const lyr of [substationLayer, plantLayer]) {
    lyr.eachLayer(m => pts.push(map.latLngToContainerPoint(m.getLatLng())));
  }
  const clear = (p, r) => pts.every(q => q.distanceTo(p) > r);
  const inside = p => p.x > 420 && p.x < size.x - 260 && p.y > 60 && p.y < size.y - 60;
  const out = p => ({x: rect.left + p.x, y: rect.top + p.y});
  if (kind === "line") {
    for (const ln of lineLayer.getLayers()) {
      // 線は必ず自分の頂点を通る(OSM の線は頂点が細かく、区間の中点は使いにくい)
      for (const ll of ln.getLatLngs().flat(2)) {
        const m = map.latLngToContainerPoint(ll);
        if (inside(m) && clear(m, 14)) return out(m);
      }
    }
    return null;
  }
  const lyr = kind === "sub" ? substationLayer : plantLayer;
  for (const m of lyr.getLayers()) {
    const p = map.latLngToContainerPoint(m.getLatLng());
    const others = pts.filter(q => q.distanceTo(p) > 0.5);
    if (inside(p) && others.every(q => q.distanceTo(p) > 20)) return out(p);
  }
  return null;
}
"""


def _tooltip_at(page, xy):
    page.mouse.move(xy["x"] - 40, xy["y"] - 40)
    page.mouse.move(xy["x"], xy["y"], steps=4)
    # Leaflet の canvas はホバーの判定を 32ms に 1 回に間引くので、止まった位置でもう一度動かす
    page.wait_for_timeout(80)
    page.mouse.move(xy["x"] + 1, xy["y"])
    page.wait_for_timeout(250)
    return page.evaluate("() => [...document.querySelectorAll('.leaflet-tooltip')].map(e => e.textContent)")


def test_one_vector_canvas(browser, site):
    page, errors = _open_map(browser, f"{site}/map.html")
    n = page.evaluate("() => map.getContainer().querySelectorAll('.leaflet-pane canvas').length")
    assert n == 1, f"地図の描画面が {n} 枚ある(重なると下の層にイベントが届かない)"
    assert not errors, errors
    page.close()


@pytest.mark.parametrize("kind,label", [("line", "送電線"), ("sub", "変電所"), ("plant", "発電所")])
def test_hover_shows_tooltip(browser, site, kind, label):
    page, _ = _open_map(browser, f"{site}/map.html")
    xy = None
    # 点が密な所では周りに空きが無いので、見つかるまで拡大して探す
    for zoom in (9, 11, 13):
        page.evaluate(f"() => {{ map.setView([35.6, 139.6], {zoom}); }}")
        page.wait_for_timeout(500)
        xy = page.evaluate(_PICK, [kind])
        if xy:
            break
    assert xy, f"{label}の確かめに使える位置が画面内に無い"
    tips = _tooltip_at(page, xy)
    assert any(t.startswith(label) for t in tips), f"{label}の上で説明が出ない: {tips}"
    page.close()


def _card(page):
    page.wait_for_selector(".agj-card:not([hidden])", timeout=3_000)
    return page.inner_text(".agj-card")


def test_click_line_opens_card(browser, site):
    page, _ = _open_map(browser, f"{site}/map.html")
    page.evaluate("() => { map.setView([35.6, 139.6], 9); }")
    page.wait_for_timeout(500)
    xy = page.evaluate(_PICK, ["line"])
    page.mouse.click(xy["x"], xy["y"])
    text = _card(page)
    assert "送電線" in text and "電圧" in text, text
    # Esc で閉じる
    page.keyboard.press("Escape")
    assert page.evaluate("() => document.querySelector('.agj-card').hidden")
    page.close()


def test_click_substation_card_links_to_subsld(browser, site):
    page, _ = _open_map(browser, f"{site}/map.html")
    page.evaluate("() => { map.setView([35.6, 139.6], 9); }")
    page.wait_for_timeout(500)
    xy = page.evaluate(_PICK, ["sub"])
    page.mouse.click(xy["x"], xy["y"])
    text = _card(page)
    assert "変電所" in text, text
    href = page.get_attribute(".agj-card a[href*='subsld.html?q=']", "href")
    assert href, "SubSLD への入口が無い"
    page.close()


def test_deep_link_starts_ybus(browser, site):
    page, errors = _open_map(browser, f"{site}/map.html#tab-ybus")
    page.wait_for_function("() => window.YbusSim && window.YbusSim.stats()", timeout=30_000)
    assert page.evaluate("() => document.getElementById('tab-ybus').classList.contains('active')")
    # 全画面のタブの上に、地図の部品(一覧パネル・拡大ボタン)が被らない
    assert page.evaluate("() => getComputedStyle(document.getElementById('sublist')).visibility") == "hidden"
    assert not errors, errors
    page.close()


def test_deep_link_starts_structure_view(browser, site):
    page, errors = _open_map(browser, f"{site}/map.html#tab-sld")
    page.wait_for_function(
        "() => getComputedStyle(document.getElementById('sld-canvas')).display !== 'none'", timeout=30_000)
    assert not errors, errors
    page.close()
