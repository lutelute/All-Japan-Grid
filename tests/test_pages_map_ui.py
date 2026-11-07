"""Pages の地図を実際のブラウザで開き、ホバーとクリックで説明が出るかを確かめる。

2026-04-02(3e014ab7)から半年、map.html の送電線と変電所はホバーもクリックも効かなかった。
発電所用の canvas が上に重なってマウスを全部取っていたためで、構文検査
(test_flow_map_integrity の node --check)では見つからなかった。ここでは
  - 地図の上の描画面(canvas)が 1 枚だけであること
  - 送電線・変電所・発電所の上にマウスを置くと、それぞれの説明が出ること
  - 送電線をクリックすると詳しい説明が出ること
  - 直リンク map.html#tab-ybus / #tab-sld で中身が起動すること
  - 送電線をクリックすると OSM の路線が引かれて光ること、路線を選ぶと鉄塔が出て選べること、
    ?route= の共有の URL で路線が開くこと、検索で路線と鉄塔が見つかること(2026-11-07、js/osm_routes.js)
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
import time
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


# マウスを取る描画面(canvas)。鉄塔の点(js/tower_dots.js)の canvas はマウスを取らない(pointer-events: none)ので数えない
_MOUSE_CANVASES = """() => [...map.getContainer().querySelectorAll('.leaflet-pane canvas')]
    .filter(c => getComputedStyle(c).pointerEvents !== 'none'
              && getComputedStyle(c.closest('.leaflet-pane')).pointerEvents !== 'none').length"""


def test_one_vector_canvas(browser, site):
    page, errors = _open_map(browser, f"{site}/map.html")
    n = page.evaluate(_MOUSE_CANVASES)
    assert n == 1, f"マウスを取る描画面が {n} 枚ある(重なると下の層にイベントが届かない)"
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


# ── 路線・鉄塔・検索(js/osm_routes.js・grid_search.js、2026-11-07) ──

def test_click_line_lights_up_osm_route(browser, site):
    page, errors = _open_map(browser, f"{site}/map.html")
    page.evaluate("() => { map.setView([35.6, 139.6], 9); }")
    page.wait_for_timeout(500)
    xy = page.evaluate(_PICK, ["line"])
    page.mouse.click(xy["x"], xy["y"])
    _card(page)
    # カードの「OSM の路線」の欄が埋まる(対応する路線が無い枝ならそう書く)
    page.wait_for_function("() => { const e = document.querySelector('.agj-card .osm-slot-line');"
                           " return e && !/調べています/.test(e.textContent); }", timeout=20_000)
    text = page.inner_text(".agj-card .osm-slot-line")
    assert "OSM の路線" in text or "対応づけられない" in text, text
    # 回線数・導体数・素導体数・導体の種類・事業者の行がある(値が無ければ「不明」)
    full = page.inner_text(".agj-card")
    for label in ("回線数", "導体数", "素導体数", "導体の種類", "事業者", "OSM"):
        assert label in full, f"線のカードに「{label}」が無い: {full}"
    if "OSM の路線" in text:
        assert page.evaluate("() => OSMRoutes._state().sel !== null")
        assert page.evaluate("() => OSMRoutes._st.selGroup.getLayers().length > 0"), "路線が光っていない"
    n = page.evaluate(_MOUSE_CANVASES)
    assert n == 1, f"路線を描いたあとにマウスを取る描画面が {n} 枚になった"
    assert not errors, errors
    page.close()


def _first_route_with_towers(page):
    return page.evaluate("""async () => {
        const S = await OSMRoutes.loadSearch();
        const T = await OSMRoutes.loadSearchTowers();
        const named = new Map(S.routes.map(r => [r[0], r]));
        for (const t of T.towers) {
            if (!t[2]) continue;
            for (const rid of t[6]) { const r = named.get(rid); if (r) return {rid: rid, ri: r[1], name: r[2], ref: String(t[2])}; }
        }
        return null;
    }""")


def test_share_link_opens_route_and_towers_are_clickable(browser, site):
    page, errors = _open_map(browser, f"{site}/map.html")
    hit = _first_route_with_towers(page)
    assert hit, "番号のある鉄塔を持つ名前付きの路線が一覧に無い"
    page.close()
    page, errors = _open_map(browser, f"{site}/map.html?route={hit['ri']}.{hit['rid']}")
    page.wait_for_function("() => OSMRoutes._state().sel !== null", timeout=30_000)
    text = _card(page)
    assert "OSM の路線" in text and hit["name"].split(" ")[0] in text, text
    # 寄ると、その路線の鉄塔が出て、クリックで鉄塔のカードが開く
    page.evaluate("""() => { const b = OSMRoutes._st.sel.rec[5]; map.setView([(b[1]+b[3])/2, (b[0]+b[2])/2], 15, {animate:false}); }""")
    page.wait_for_function("() => OSMRoutes._st.towerSelGroup.getLayers().length > 0", timeout=30_000)
    xy = page.evaluate("""() => {
        const rect = map.getContainer().getBoundingClientRect(), size = map.getSize();
        for (const m of OSMRoutes._st.towerSelGroup.getLayers()) {
            const p = map.latLngToContainerPoint(m.getLatLng());
            if (p.x > 420 && p.x < size.x - 420 && p.y > 80 && p.y < size.y - 80) return {x: rect.left + p.x, y: rect.top + p.y};
        }
        return null;
    }""")
    if xy is None:   # 画面の端にしか無いときは 1 基を真ん中に寄せる
        page.evaluate("() => { map.setView(OSMRoutes._st.towerSelGroup.getLayers()[0].getLatLng(), 16, {animate:false}); }")
        page.wait_for_timeout(800)
        xy = page.evaluate("() => { const r = map.getContainer().getBoundingClientRect(), s = map.getSize(); return {x: r.left + s.x/2, y: r.top + s.y/2}; }")
    page.mouse.click(xy["x"], xy["y"])
    page.wait_for_function("() => /鉄塔/.test(document.querySelector('.agj-card').innerText)", timeout=10_000)
    assert "載っている線" in page.inner_text(".agj-card")
    assert "tower=" in page.url
    assert not errors, errors
    page.close()


def test_search_finds_route_and_tower(browser, site):
    page, errors = _open_map(browser, f"{site}/map.html")
    hit = _first_route_with_towers(page)
    name = hit["name"]
    page.fill("#gs-input", name)
    page.wait_for_function("() => [...document.querySelectorAll('#gs-results .gs-result')]"
                           ".some(e => /OSM の路線/.test(e.innerText))", timeout=20_000)
    page.fill("#gs-input", f"{name} {hit['ref']}")
    page.wait_for_function("() => [...document.querySelectorAll('#gs-results .gs-result')]"
                           ".some(e => /鉄塔/.test(e.innerText))", timeout=20_000)
    page.click("#gs-results .gs-result >> text=鉄塔")
    page.wait_for_function("() => document.querySelector('.agj-card') && !document.querySelector('.agj-card').hidden"
                           " && /鉄塔/.test(document.querySelector('.agj-card').innerText)", timeout=20_000)
    assert ("No." + hit["ref"]) in page.inner_text(".agj-card .agj-card-title")
    assert not errors, errors
    page.close()


def test_all_towers_are_drawn_and_clickable(browser, site):
    """OSM の鉄塔を全部(番号の無いものも)点で描く。全国を見て、地域ごとにデータの数と描いた数が一致する。
    寄って点をマウスでクリックすると、鉄塔のカード(番号・載っている線・回線数)が開く。"""
    page, errors = _open_map(browser, f"{site}/map.html")
    page.wait_for_function("() => window.TowerDots && TowerDots.state().loaded", timeout=60_000)
    page.evaluate("() => { map.fitBounds([[24.0, 122.9], [45.6, 146.0]], {animate: false}); }")
    page.wait_for_timeout(1500)
    s = page.evaluate("() => TowerDots.state()")
    meta_total = page.evaluate("async () => (await OSMRoutes.loadMeta()).counts.towers")
    assert s["total"] == meta_total, (s["total"], meta_total)
    for reg, v in s["perRegion"].items():
        assert v["drawn"] == v["data"], f"{reg}: データ {v['data']} 基のうち {v['drawn']} 基しか描いていない"
    # 寄って、画面の真ん中に近い鉄塔をクリック
    page.evaluate("() => { map.setView([35.42667, 136.66566], 16, {animate: false}); }")
    page.wait_for_timeout(1200)
    xy = page.evaluate("""() => { const p = map.latLngToContainerPoint(map.getCenter()); let k = TowerDots.pickAt(p.x, p.y);
        if (!k) { const s = map.getSize(); for (let dx = -200; dx <= 200 && !k; dx += 4) for (let dy = -150; dy <= 150 && !k; dy += 4) k = TowerDots.pickAt(s.x/2 + dx, s.y/2 + dy); }
        const r = map.getContainer().getBoundingClientRect(); return k ? {x: r.left + k.x, y: r.top + k.y} : null; }""")
    assert xy, "画面の中に鉄塔が無い"
    page.mouse.click(xy["x"], xy["y"])
    page.wait_for_function("() => /鉄塔/.test((document.querySelector('.agj-card') || {}).innerText || '')", timeout=15_000)
    text = page.inner_text(".agj-card")
    assert "番号" in text and "載っている線" in text, text
    if "線に載っていない" not in text:
        assert "回線数" in text and "導体数" in text, text
    assert not errors, errors
    page.close()


def test_select_line_from_tower_card_keeps_the_route_card(browser, site):
    """鉄塔のカードの「この線を選ぶ」で、路線のカードが開いたまま残り、路線が光る(2026-11-07 の不具合:
    押したボタンが中身の差し替えで DOM から外れ、地図が「何も無い所のクリック」と取ってカードを閉じていた)。
    路線のカードには回線数・導体数・素導体数・導体の種類の行がある。"""
    page, errors = _open_map(browser, f"{site}/map.html")
    page.wait_for_function("() => window.TowerDots && TowerDots.state().loaded", timeout=60_000)
    page.evaluate("() => { TowerDots.setMode('tower'); map.setView([35.42667, 136.66566], 16, {animate: false}); }")
    page.wait_for_timeout(1200)
    xy = page.evaluate("""() => { const s = map.getSize(); let k = null;
        for (let dx = 0; dx <= 200 && !k; dx += 4) for (let dy = -150; dy <= 150 && !k; dy += 4) k = TowerDots.pickAt(s.x/2 + dx, s.y/2 + dy);
        const r = map.getContainer().getBoundingClientRect(); return k ? {x: r.left + k.x, y: r.top + k.y} : null; }""")
    assert xy
    page.mouse.click(xy["x"], xy["y"])
    page.wait_for_function("() => /この線を選ぶ/.test((document.querySelector('.agj-card') || {}).innerText || '')", timeout=15_000)
    page.click(".agj-card button.agj-card-btn >> text=この線を選ぶ")
    page.wait_for_timeout(1500)
    assert not page.evaluate("() => document.querySelector('.agj-card').hidden"), "カードが閉じた"
    text = page.inner_text(".agj-card")
    assert "OSM の路線" in text, text
    for label in ("回線数", "導体数", "素導体数", "導体の種類"):
        assert label in text, f"路線のカードに「{label}」が無い"
    assert page.evaluate("() => OSMRoutes._state().sel !== null"), "路線が光っていない"
    assert not errors, errors
    page.close()


def _a_tower(region="tohoku"):
    """docs/data/osm_routes/towers_<地域>.json の鉄塔を 1 基(地域の番号・node id・緯度経度)。"""
    import json as _json
    meta = _json.loads((DOCS / "data" / "osm_routes" / "meta.json").read_text(encoding="utf-8"))
    d = _json.loads((DOCS / "data" / "osm_routes" / f"towers_{region}.json").read_text(encoding="utf-8"))
    i = d["n"] // 2

    def at(key):
        acc = 0
        for k, x in enumerate(d[key]):
            acc += x
            if k == i:
                return acc

    return meta["regions"].index(region), at("id"), at("lat") / 1e5, at("lon") / 1e5


def test_tower_share_link_keeps_the_view_when_lines_load_late(browser, site):
    """?tower= で開くと、送電線のデータが鉄塔より遅く着いても、地図はその鉄塔に寄ったまま(全国へ戻らない)。
    公開サイトでは送電線のデータの方が遅く、最初の読み込みの終わりで全国の表示に引き戻していた(2026-11-07)。"""
    ri, tid, lat, lon = _a_tower()
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    def slow(route):
        time.sleep(3)
        route.continue_()

    page.route("**/data/map/lines_*", slow)
    page.goto(f"{site}/map.html?tower={ri}.{tid}")
    try:
        page.wait_for_function("() => window.map && window.lineLayer && window.lineLayer.getLayers().length > 0",
                               timeout=90_000)
    except sync_api.Error:
        page.close()
        pytest.skip("地図のデータか Leaflet(unpkg)を読み込めない")
    page.wait_for_function("() => /鉄塔/.test((document.querySelector('.agj-card') || {}).innerText || '')",
                           timeout=30_000)
    page.wait_for_timeout(1500)
    z, c = page.evaluate("() => [map.getZoom(), map.getCenter()]")
    assert z >= 15, z
    assert abs(c["lat"] - lat) < 0.01 and abs(c["lng"] - lon) < 0.01, (c, lat, lon)
    assert not errors, errors
    page.close()
