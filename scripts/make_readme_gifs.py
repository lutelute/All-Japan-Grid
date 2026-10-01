#!/usr/bin/env python3
"""README のデモ GIF を、Pages のページをブラウザで操作して撮り直す。

    python scripts/make_readme_gifs.py              # 全シーン(撮影 → 南海トラフ・動態 → 予告編)
    python scripts/make_readme_gifs.py map flow     # 指定したシーンだけ
    python scripts/make_readme_gifs.py --list       # シーン一覧

docs/ をローカルで配信し、Playwright(Chromium) で台本どおりに操作しながら、CDP の
screencast でフレームを時刻つきで受け取る。それを一定 fps に並べ直して gifski で GIF にする。
カメラの移動(flyTo)も潮流の流れるアニメーションも、実際の速さのまま撮れる。
画面の左上には、いま何を見せているかの字幕を重ねる(ページの DOM に一時的に差し込むだけ)。

出力: docs/assets/gif/<scene>.gif
要るもの: playwright + chromium(`playwright install chromium`)、gifski(`brew install gifski`)
任意: gifsicle(あれば最後に -O3 --lossy で軽くする)
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import functools
import http.server
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from PIL import Image
from playwright.async_api import Page, async_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.readme_numbers import numbers  # noqa: E402  字幕の数字もデータから(手書きすると古くなる)

DOCS = ROOT / "docs"
OUT = DOCS / "assets" / "gif"
VIEW = {"width": 1280, "height": 760}

# ---------------------------------------------------------------- 配信・録画の道具


def serve_docs() -> tuple[http.server.ThreadingHTTPServer, str]:
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a, **k) -> None:
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(DOCS)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class Recorder:
    """CDP screencast でフレームを集め、一定 fps の PNG 列に並べ直す。

    pause()〜resume() の間(データの読み込み待ちなど)は切り落とす(ジャンプカット)。
    """

    def __init__(self, page: Page):
        self.page = page
        self.frames: list[tuple[float, bytes]] = []
        self.segments: list[list[float]] = []
        self.cdp = None

    async def _now(self) -> float:
        return await self.page.evaluate("Date.now()/1000")

    async def start(self) -> None:
        if self.cdp is None:
            self.cdp = await self.page.context.new_cdp_session(self.page)

            def on_frame(e: dict) -> None:
                self.frames.append((e["metadata"]["timestamp"], base64.b64decode(e["data"])))
                asyncio.ensure_future(self.cdp.send("Page.screencastFrameAck", {"sessionId": e["sessionId"]}))

            self.cdp.on("Page.screencastFrame", on_frame)
            await self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 95,
                                                          "maxWidth": VIEW["width"], "maxHeight": VIEW["height"]})
        await self.page.wait_for_timeout(250)  # 直前の字幕などの書き換えが描画に乗るのを待つ
        self.segments.append([await self._now(), 0.0])

    resume = start

    async def pause(self) -> None:
        self.segments[-1][1] = await self._now()
        # フレームの時刻は描画の確定時刻なので、止めた直後の操作が前の区間に混ざることがある。少し空ける
        await self.page.wait_for_timeout(350)

    async def stop(self) -> None:
        await self.pause()
        await self.cdp.send("Page.stopScreencast")

    async def snap(self) -> None:
        """いまの画面をちょうど 1 コマだけ足す(録画は止めたまま)。"""
        t = await self._now()
        self.segments.append([t, None])

    def resample(self, fps: float, outdir: Path) -> int:
        """各区間を 1/fps 刻みで切り、各時刻で最後に届いたフレームを使う(静止区間は前のコマを繰り返す)。"""
        fr = sorted(self.frames)
        if not fr:
            raise RuntimeError("フレームが 1 枚も届いていない")
        n = 0
        for t0, t1 in self.segments:
            j = 0
            times = [t0] if t1 is None else [t0 + i / fps for i in range(int((t1 - t0) * fps))]
            for t in times:
                while j + 1 < len(fr) and fr[j + 1][0] <= t:
                    j += 1
                Image.open(io.BytesIO(fr[j][1])).convert("RGB").save(outdir / f"f{n:05d}.png")
                n += 1
        return n


async def wait_js(page: Page, cond: str, timeout: int = 60000) -> None:
    """条件式が真になるまで待つ(受動的に 400ms 間隔・JS 側でループしない)。"""
    for _ in range(timeout // 400):
        if await page.evaluate(f"(() => {{ try {{ return !!({cond}); }} catch (e) {{ return false; }} }})()"):
            return
        await page.wait_for_timeout(400)
    raise TimeoutError(cond)


async def caption(page: Page, title: str, sub: str = "", pos: str = "bottom") -> None:
    """画面の下(または上)中央に字幕を出す(同じ id を使い回す)。title が空なら消す。"""
    await page.evaluate(
        """([t, s, pos]) => {
          let el = document.getElementById('__readme_cap');
          if (!t) { if (el) el.remove(); return; }
          if (!el) {
            el = document.createElement('div'); el.id = '__readme_cap';
            el.style.cssText = 'position:fixed;left:50%;transform:translateX(-50%);z-index:99999;' +
              'background:rgba(10,14,22,.86);color:#fff;padding:10px 18px;border-radius:10px;' +
              'font:600 19px/1.35 "Hiragino Sans","Noto Sans JP",sans-serif;box-shadow:0 4px 18px rgba(0,0,0,.35);' +
              'border:1px solid rgba(255,255,255,.14);text-align:center;max-width:78%;pointer-events:none;' +
              'transition:opacity .25s';
            document.body.appendChild(el);
          }
          el.style.top = pos === 'top' ? '14px' : ''; el.style.bottom = pos === 'top' ? '' : '22px';
          el.innerHTML = t + (s ? '<div style="font-weight:400;font-size:14px;color:#b8c4d6;margin-top:2px">' + s + '</div>' : '');
        }""",
        [title, sub, pos],
    )


async def fly(page: Page, lat: float, lon: float, zoom: float, sec: float, var: str = "map") -> None:
    await page.evaluate(f"{var}.flyTo([{lat},{lon}],{zoom},{{duration:{sec}}})")
    await page.wait_for_timeout(int(sec * 1000) + 150)


async def prewarm(page: Page, views: list[tuple[float, float, float]], var: str = "map", wait: int = 2500) -> None:
    """撮る前に行き先のタイルを読ませておく(撮影中に灰色の穴が出ないように)。"""
    for lat, lon, z in views:
        await page.evaluate(f"{var}.setView([{lat},{lon}],{z},{{animate:false}})")
        await page.wait_for_timeout(wait)


async def glide(page: Page, rec: Recorder, lat: float, lon: float, zoom: float, sec: float,
                fps: float = 10, var: str = "map", settle: int = 90) -> None:
    """カメラを小刻みに動かし、毎回描き直しを待ってから 1 コマずつ撮る。

    Leaflet の flyTo は拡大の途中で canvas の画像を引き伸ばすので、点や線がぼやけた塊に写る。
    ここでは 1 コマごとに setView → 描画を待つ → snap を繰り返す(録画は止めたまま)。
    中心は「目的地へ向かってズームしていく」ように動かす。
    """
    await page.evaluate(f"{var}.options.zoomSnap = 0")
    la0, lo0, z0 = await page.evaluate(f"(() => {{ const c = {var}.getCenter(); return [c.lat, c.lng, {var}.getZoom()]; }})()")
    await rec.pause()
    n, dz = max(2, int(sec * fps)), zoom - z0
    for i in range(1, n + 1):
        u = i / n
        e = u * u * (3 - 2 * u)
        z = z0 + dz * e
        f = e if abs(dz) < 1e-6 else (1 - 2 ** (-(z - z0))) / (1 - 2 ** (-dz))
        await page.evaluate(f"{var}.setView([{la0 + (lat - la0) * f},{lo0 + (lon - lo0) * f}],{z},{{animate:false}})")
        for _ in range(10):  # タイルが届くまで最大 2.5 秒
            if await page.evaluate(TILES_DONE):
                break
            await page.wait_for_timeout(250)
        await page.evaluate("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
        await page.wait_for_timeout(settle)  # moveend で描き直すページはその分待つ
        await rec.snap()
    await page.evaluate(f"{var}.options.zoomSnap = 1")
    await rec.resume()


async def wait_stable(page: Page, expr: str, hold: int = 1500, timeout: int = 60000) -> None:
    """式の値が hold ミリ秒変わらなくなるまで待つ(読み込みが 2 段階で走るページ向け)。"""
    last, since = None, 0
    for _ in range(timeout // 250):
        v = await page.evaluate(expr)
        since = since + 250 if v == last else 0
        last = v
        if since >= hold:
            return
        await page.wait_for_timeout(250)


TILES_DONE = "document.querySelectorAll('img.leaflet-tile:not(.leaflet-tile-loaded)').length === 0"


# ---------------------------------------------------------------- シーン(台本)
# 各シーンは (page, base_url, rec) を受け取り、準備 → rec.start() → 操作 → rec.stop() の順に進める。


MAP_READY = "document.getElementById('status-text').textContent.includes(' lines')"


async def set_kv(page: Page, kv: str) -> None:
    """電圧の絞り込みを変え、描き直しが終わるまで待つ(状態表示を目印に書き換えてから新しい表記を待つ)。"""
    await page.evaluate("document.getElementById('status-text').textContent = '__wait__'")
    await page.select_option("#min-kv", kv)
    await wait_js(page, f"document.getElementById('status-text').textContent.includes('[{kv} kV+]') && {MAP_READY}")
    await wait_stable(page, "document.getElementById('status-text').textContent")


async def scene_map(page: Page, base: str, rec: Recorder) -> None:
    """全国系統マップ: 電圧を下げて線が増えていく → 首都圏へ寄って変電所を出す → 関西へ。"""
    await page.goto(f"{base}/map.html?readme", wait_until="domcontentloaded")
    await wait_js(page, MAP_READY)
    await page.evaluate("toggleListPanel(false)")
    await page.locator('.layer-cb[data-layer="plants"]').first.uncheck()
    subs = page.locator('.layer-cb[data-layer="subs"]').first
    await set_kv(page, "66")
    await prewarm(page, [(35.62, 139.75, 9), (34.75, 135.55, 9)])
    await page.evaluate("map.setView([36.4,137.4],6,{animate:false})")
    await set_kv(page, "275")
    await subs.uncheck()
    await page.wait_for_timeout(1500)

    await caption(page, "日本全国の送電網を地図で", "OpenStreetMap から組み立て、公表資料で突き合わせた全国モデル(275 kV 以上)")
    await page.wait_for_timeout(600)
    await rec.start()
    await page.wait_for_timeout(2800)
    await rec.pause()
    await set_kv(page, "154")
    await caption(page, "154 kV 以上", "電圧を下げるほど細かい網が見えてくる")
    await rec.resume()
    await page.wait_for_timeout(1800)
    await rec.pause()
    await set_kv(page, "66")
    await caption(page, "66 kV 以上", f"送電線 {numbers()['lines']:,} 本")
    await rec.resume()
    await page.wait_for_timeout(2000)
    await caption(page, "首都圏へ", "")
    await glide(page, rec, 35.62, 139.75, 9, 2.4)
    await rec.pause()
    await subs.check()
    await page.wait_for_timeout(1500)
    await caption(page, "変電所も", f"{numbers()['substations']:,} か所。クリックで構内図・単線結線図へ")
    await rec.resume()
    await page.wait_for_timeout(2200)
    # 首都圏→関西へ直接動かすと描画が追いつかないので、全国表示に戻して(カット)から寄る
    await rec.pause()
    await subs.uncheck()
    await page.evaluate("map.setView([36.4,137.4],6,{animate:false})")
    await page.wait_for_timeout(1800)
    await caption(page, "関西へ", "")
    await rec.resume()
    await page.wait_for_timeout(400)
    await glide(page, rec, 34.75, 135.55, 9, 2.4)
    await rec.pause()
    await subs.check()
    await page.wait_for_timeout(1500)
    await rec.resume()
    await page.wait_for_timeout(1800)
    await rec.stop()


async def scene_flow(page: Page, base: str, rec: Recorder) -> None:
    """潮流: UC の発電計画で解いた全国の流れ → 首都圏へ寄る → 1 日を再生 → ⚡NOW(実績需要の断面)。"""
    await page.goto(f"{base}/flow_map.html?readme", wait_until="domcontentloaded")
    await page.wait_for_timeout(14000)
    await prewarm(page, [(36.2, 138.6, 7), (35.75, 139.6, 8)])
    await page.evaluate("map.setView([36.6,137.8],6,{animate:false})")
    await page.wait_for_timeout(3500)

    await caption(page, "電気の流れを地図の上で", "UC(fy2023)の時刻別の発電計画で全国の潮流を解き、流れとして描く", pos="top")
    await page.wait_for_timeout(600)
    await rec.start()
    await page.wait_for_timeout(3000)
    await caption(page, "首都圏へ寄る", "線の太さ = 潮流の大きさ、色 = 線路の負荷率、光の粒 = 流れる向き", pos="top")
    await glide(page, rec, 35.75, 139.6, 8, 2.2, settle=380)
    await page.wait_for_timeout(2200)
    await caption(page, "1 日の変化を再生", "時刻ごとに需要と発電が変わり、流れも変わる", pos="top")
    await page.click("#btnPlay")
    await page.wait_for_timeout(5500)
    await page.click("#btnPlay")
    await rec.pause()
    await page.click('#tabs .tab[data-k="now"]')
    await page.wait_for_timeout(5000)
    await page.evaluate("map.setView([35.75,139.6],8,{animate:false})")  # NOW は全国表示に戻るので寄り直す
    await page.wait_for_timeout(2500)
    await caption(page, "⚡NOW — いまの断面", "各社でんき予報の実績需要(毎時取得)に合わせて解き直した潮流", pos="top")
    await rec.resume()
    await page.wait_for_timeout(3200)
    await rec.stop()


async def scene_subsld(page: Page, base: str, rec: Recorder) -> None:
    """変電所の中: 航空写真の上の構内図 × 単線結線図 → 名前で探す → 開閉器を開けて母線が落ちる。"""
    await page.goto(f"{base}/subsld.html?readme", wait_until="domcontentloaded")
    await page.wait_for_timeout(8000)
    names = ["新信濃", "新京葉", "南福光"]
    for nm in names:  # 写真タイルを先読み
        await page.fill("#q", nm)
        await page.wait_for_timeout(600)
        if await page.locator("#list .row").count():
            await page.locator("#list .row").first.click()
            await page.wait_for_timeout(2000)
    await page.fill("#q", "")
    await page.wait_for_timeout(600)
    await page.locator("#list .row").first.click()
    await page.wait_for_timeout(2500)

    await caption(page, f"{numbers()['subsld_sites']:,} か所の変電所それぞれに「中の図」", "左 = 航空写真に OSM の構内幾何、右 = 単線結線図(推定は推定と明記)")
    await page.wait_for_timeout(600)
    await rec.start()
    await page.wait_for_timeout(3200)
    for nm in names:
        await caption(page, f"「{nm}」を探す", "名前で絞り込み、選ぶとその場で図を描き直す")
        await page.fill("#q", "")
        await page.type("#q", nm, delay=140)
        await page.wait_for_timeout(500)
        if not await page.locator("#list .row").count():
            continue
        await page.locator("#list .row").first.click()
        await page.wait_for_timeout(2400)
    n_sw = await page.evaluate("document.querySelectorAll('#sld g.sw').length")
    if n_sw:
        await caption(page, "開閉器をクリックして開ける", "母線の明暗 = 充電されているかどうか(制御所ビュー)")
        await page.wait_for_timeout(1000)
        for k in range(min(2, n_sw)):
            await page.evaluate(f"document.querySelectorAll('#sld g.sw')[{k}].onclick()")
            await page.wait_for_timeout(1500)
        await page.wait_for_timeout(1000)
    await rec.stop()


async def scene_compare(page: Page, base: str, rec: Recorder) -> None:
    """Before/After: 旧(断片化) と 新(OSM の実線形でつなぐ) を地域ごとに見比べる。"""
    await page.goto(f"{base}/compare.html?readme", wait_until="domcontentloaded")
    await page.wait_for_timeout(9000)
    for r in ("kansai", "kyushu", "tokyo"):
        await page.select_option("#region", r)
        await page.wait_for_timeout(5000)

    await caption(page, "左 = 旧モデル、右 = 今のモデル", "旧: 端点を最寄りの変電所に吸着 → 網がばらばら / 今: OSM の実線形でつなぐ")
    await page.wait_for_timeout(600)
    await rec.start()
    await page.wait_for_timeout(3600)
    for r, ja in (("kansai", "関西"), ("kyushu", "九州")):
        await caption(page, f"{ja}でも", "下の帯: 連結成分の数・AC 潮流が収束したか")
        await page.select_option("#region", r)
        await page.wait_for_timeout(3400)
    await rec.stop()


async def scene_review(page: Page, base: str, rec: Recorder) -> None:
    """候補レビュー: 機械が出した接続候補を、地図の上で 1 件ずつ人が判断する。"""
    await page.goto(f"{base}/review.html?readme", wait_until="domcontentloaded")
    await page.wait_for_timeout(9000)

    await caption(page, "つなぐかどうかは人が決める", "機械が出した接続候補を 1 件ずつ地図で確かめる")
    await page.wait_for_timeout(600)
    await rec.start()
    await page.wait_for_timeout(3000)
    for fn, msg in (("revSkip", "保留して次へ"), ("revApprove", "承認(下書きとして記録)"), ("revSkip", "次の候補")):
        await rec.pause()
        await caption(page, msg, "承認・却下はブラウザ内の下書き。正典への反映は別の手順で")
        await page.evaluate(f"{fn}()")
        await page.wait_for_timeout(600)
        await wait_js(page, TILES_DONE, timeout=8000)
        await page.wait_for_timeout(500)
        await rec.resume()
        await page.wait_for_timeout(2300)
    await rec.stop()


async def scene_dashboard(page: Page, base: str, rec: Recorder) -> None:
    """入口のダッシュボード: 状態タイル → ツールを検索で絞る。"""
    await page.goto(f"{base}/index.html?readme", wait_until="domcontentloaded")
    await page.wait_for_timeout(4000)

    await caption(page, "入口はダッシュボード", "モデルの規模・リアルタイムの鮮度・介入の件数をデータから読む")
    await page.wait_for_timeout(600)
    await rec.start()
    await page.wait_for_timeout(3000)
    await page.mouse.wheel(0, 380)
    await page.wait_for_timeout(900)
    await caption(page, "ツールを探す", "ブラウザで開く / ローカルで起動 / コマンド")
    for word in ("潮流", "N-1"):
        await page.fill("#q", "")
        await page.type("#q", word, delay=160)
        await page.wait_for_timeout(1900)
    await page.fill("#q", "")
    await page.wait_for_timeout(1200)
    await rec.stop()


# ---------------------------------------------------------------- 撮影しない素材(既存の成果物から作る)

# 南海トラフの計算結果(git 管理外)。別の作業ツリーで撮るときは AGJ_NANKAI_ROOT で結果のあるチェックアウトを指す
NANKAI_ROOT = Path(os.environ.get("AGJ_NANKAI_ROOT", ROOT))
NANKAI_RUN = NANKAI_ROOT / "hazard" / "nankai" / "output" / "run_v10"  # 正典(併架線の回線数を是正後)


def shrink(src: Path, out: Path, width: int, lossy: int = 70) -> None:
    subprocess.run(["gifsicle", "--resize-width", str(width), "-O3", f"--lossy={lossy}", "--colors", "256",
                    "--no-warnings", str(src), "-o", str(out)], check=True)


def make_nankai() -> Path:
    """南海トラフ: 夜の灯りが消えて戻る映像を run_v10 で作り直して縮める(hazard/nankai/scripts/make_cinematic.py)。"""
    if not NANKAI_RUN.exists():
        raise FileNotFoundError(f"{NANKAI_RUN} が無い(hazard の計算結果はリポジトリに入っていない)")
    out = OUT / "nankai_cinematic.gif"
    with tempfile.TemporaryDirectory() as td:
        env = {**os.environ, "PYTHONPATH": str(NANKAI_ROOT / "hazard" / "nankai" / "src")}
        subprocess.run([sys.executable, str(NANKAI_ROOT / "hazard/nankai/scripts/make_cinematic.py"), str(NANKAI_RUN),
                        f"{td}/cinematic"], check=True, env=env, cwd=NANKAI_ROOT)
        shrink(Path(td) / "cinematic.gif", out, 800, lossy=80)
    return out


def make_dynamics() -> Path:
    """動態: 全系統の動揺(4 島 542 機)。動態解析スライドの素材を縮める。"""
    out = OUT / "dynamics_swing.gif"
    shrink(ROOT / "docs/slides/ajg/assets/national_swing.gif", out, 960, lossy=60)
    return out


def gif_frames(path: Path, fps: float) -> list[Image.Image]:
    """GIF を一定 fps のコマ列に展開する(各コマの表示時間を考慮)。"""
    im, out, acc, t = Image.open(path), [], 0.0, 0.0
    for i in range(im.n_frames):
        im.seek(i)
        acc += im.info.get("duration", 100) / 1000
        fr = im.convert("RGB")
        while t < acc:
            out.append(fr)
            t += 1 / fps
    return out


# 予告編: 各 GIF のどこを何秒使うか(秒)。GIF を撮り直したら見直す
HERO_CUTS = [("map.gif", 4.6, 8.6), ("flow.gif", 5.2, 8.6), ("subsld.gif", 5.4, 8.6), ("nankai_cinematic.gif", 10.6, 14.6)]


def make_hero(fps: float = 10, size: tuple[int, int] = (800, 475)) -> Path:
    """README の冒頭: 地図 → 潮流 → 変電所の中 → 南海トラフ を数秒ずつつなぐ。"""
    out = OUT / "hero.gif"
    with tempfile.TemporaryDirectory() as td:
        n = 0
        for name, a, b in HERO_CUTS:
            frames = gif_frames(OUT / name, fps)[int(a * fps):int(b * fps)]
            for fr in frames:
                canvas = Image.new("RGB", size, (6, 9, 15))
                fr = fr.copy()
                fr.thumbnail(size, Image.LANCZOS)
                canvas.paste(fr, ((size[0] - fr.width) // 2, (size[1] - fr.height) // 2))
                canvas.save(Path(td) / f"f{n:05d}.png")
                n += 1
        encode(Path(td), out, fps, size[0], 70)
    return out


POST = {
    "nankai": (make_nankai, "南海トラフ: 夜の灯りが消えて戻る(run_v10 で作り直す・ローカルのみ)"),
    "dynamics": (make_dynamics, "全系統の動揺(動態解析スライドの素材を縮める)"),
    "hero": (make_hero, "冒頭の予告編(撮った GIF から切り出してつなぐ・最後に作る)"),
}


SCENES = {
    "map": (scene_map, "全国系統マップ(電圧の絞り込みとズーム)"),
    "flow": (scene_flow, "いまの潮流と 24 時間の再生"),
    "subsld": (scene_subsld, "変電所の構内図×単線結線図、開閉器の操作"),
    "compare": (scene_compare, "旧モデルと今のモデルの見比べ"),
    "review": (scene_review, "接続候補のレビュー"),
    "dashboard": (scene_dashboard, "入口のダッシュボード"),
}

# ---------------------------------------------------------------- 書き出し


def encode(frames_dir: Path, out: Path, fps: float, width: int, quality: int) -> None:
    pngs = sorted(frames_dir.glob("f*.png"))
    subprocess.run(["gifski", "--fps", str(fps), "--width", str(width), "--quality", str(quality),
                    "--quiet", "-o", str(out), *map(str, pngs)], check=True)
    if shutil.which("gifsicle"):
        subprocess.run(["gifsicle", "-O3", "--lossy=35", "--colors", "256", "--no-warnings", "--batch", str(out)], check=True)


async def run(names: list[str], fps: float, width: int, quality: int) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    post = [n for n in names if n in POST]
    names = [n for n in names if n in SCENES]
    if names:
        await capture(names, fps, width, quality)
    for n in post:
        out = POST[n][0]()
        print(f"[{n}] → {out.relative_to(ROOT)} ({out.stat().st_size / 1e6:.1f} MB)")


async def capture(names: list[str], fps: float, width: int, quality: int) -> None:
    srv, base = serve_docs()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
            for name in names:
                fn, desc = SCENES[name]
                ctx = await browser.new_context(viewport=VIEW, device_scale_factor=1, locale="ja-JP")
                page = await ctx.new_page()
                rec = Recorder(page)
                print(f"[{name}] {desc} …", flush=True)
                await fn(page, base, rec)
                with tempfile.TemporaryDirectory() as td:
                    n = rec.resample(fps, Path(td))
                    out = OUT / f"{name}.gif"
                    encode(Path(td), out, fps, width, quality)
                print(f"[{name}] {n} コマ・{n / fps:.1f} 秒 → {out.relative_to(ROOT)} ({out.stat().st_size / 1e6:.1f} MB)")
                await ctx.close()
            await browser.close()
    finally:
        srv.shutdown()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("scenes", nargs="*", help="撮るシーン(省略で全部)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--fps", type=float, default=10)
    ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--quality", type=int, default=70, help="gifski の画質 1-100")
    a = ap.parse_args()
    if a.list:
        for k, (_, d) in {**SCENES, **POST}.items():
            print(f"  {k:10s} {d}")
        return
    names = a.scenes or [*SCENES, *POST]
    bad = [n for n in names if n not in SCENES and n not in POST]
    if bad:
        sys.exit(f"知らないシーン: {bad}(--list で一覧)")
    if not shutil.which("gifski"):
        sys.exit("gifski が見つからない(brew install gifski)")
    asyncio.run(run(names, a.fps, a.width, a.quality))


if __name__ == "__main__":
    main()
