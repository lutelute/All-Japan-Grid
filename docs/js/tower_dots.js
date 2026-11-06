/* 系統図マップに、OSM の鉄塔(power=tower)を全部、点で描く(2026-11-07 オーナー「全ての鉄塔もプロットして」)。
 *
 * 鉄塔は全国で約 24.6 万基あり、Leaflet の部品(circleMarker)を 1 基ずつ作ると重すぎる。そこで
 *   - 位置は Web メルカトルの 0〜1 の値にして型付き配列に持ち、
 *   - 地図の動きが止まるたびに、見えている範囲の点を 1 枚の canvas に直接描く(全国でも数十ミリ秒)。
 *   - 読み込みは地域ごとに少しずつ(1 地域を処理したら一度手を離して描く)。開いた直後に画面が固まらないように
 * この canvas はマウスを取らない(pointer-events: none)。クリックは地図の入れ物で先に受け、
 * 「クリックで開くもの」(自動・線・鉄塔)に従って、鉄塔のカードか線のカードを開く。
 *   自動: 地図の線(正典の枝)の上なら線を開く。線が無い所(下の電圧の線など)の点や、
 *         よく寄っていて(ズーム 14 以上)点の真上を押したときは鉄塔を開く
 * 番号や名前の無い鉄塔も含めて全部描く。データは docs/data/osm_routes/towers_{地域}.json(js/osm_routes.js が読む)。
 */
(function (global) {
    "use strict";

    var PICK_ZOOM = 8;        // これより寄っているときだけ、クリックで鉄塔を選ぶ
    var PICK_PX = 7;          // クリックした位置からこの距離(画面の px)以内の鉄塔を選ぶ
    var LINE_PX = 10;         // 線の当たり判定(grid_map.js の地図の tolerance と同じ)
    var st = {
        on: true, loaded: false, loading: null, sets: [], nLoaded: 0, nRegions: 0,
        canvas: null, ctx: null, pane: null, mode: "auto",
        drawnX: new Float32Array(0), drawnY: new Float32Array(0), drawnSet: new Uint8Array(0), drawnIdx: new Uint32Array(0), nDrawn: 0,
        perRegion: {}, tip: null, lastHover: -1, t0: 0, tLoad: null,
    };

    function merc(lat, lon) {
        var s = Math.sin(lat * Math.PI / 180);
        return [(lon + 180) / 360, 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)];
    }

    function grow(total) {
        if (st.drawnX.length >= total) return;
        st.drawnX = new Float32Array(total); st.drawnY = new Float32Array(total);
        st.drawnSet = new Uint8Array(total); st.drawnIdx = new Uint32Array(total);
    }

    // 地域ごとに読み、1 地域ずつ手を離して描く(全部まとめて処理すると、そのあいだ画面が止まる)
    function load() {
        if (st.loading) return st.loading;
        st.t0 = performance.now();
        st.loading = OSMRoutes.loadMeta().then(function (meta) {
            st.nRegions = meta.regions.length;
            var chain = Promise.resolve();
            var fetches = meta.regions.map(function (reg) { return OSMRoutes.loadTowers(reg); });
            meta.regions.forEach(function (reg, k) {
                chain = chain.then(function () { return fetches[k]; }).then(function (T) {
                    return new Promise(function (res) {
                        setTimeout(function () {
                            var mx = new Float64Array(T.n), my = new Float64Array(T.n);
                            for (var i = 0; i < T.n; i++) {
                                var p = merc(T.la[i] / 1e5, T.lo[i] / 1e5);
                                mx[i] = p[0]; my[i] = p[1];
                            }
                            st.sets.push({ reg: reg, T: T, mx: mx, my: my });
                            st.nLoaded++;
                            grow(st.sets.reduce(function (a, s) { return a + s.T.n; }, 0));
                            st.loaded = true;
                            draw();
                            res();
                        }, 0);
                    });
                });
            });
            return chain;
        }).then(function () {
            st.tLoad = Math.round(performance.now() - st.t0);
            report();
            return st.sets;
        }).catch(function (e) { st.loading = null; throw e; });
        return st.loading;
    }

    function ensureCanvas() {
        if (st.canvas) return;
        st.pane = map.createPane("towerPane");
        st.pane.style.zIndex = 390;
        st.pane.style.pointerEvents = "none";
        st.canvas = L.DomUtil.create("canvas", "tower-dots", st.pane);
        st.canvas.style.pointerEvents = "none";
        st.ctx = st.canvas.getContext("2d");
    }

    function dotSize(z) { return z <= 6 ? 1 : z <= 8 ? 1.4 : z <= 10 ? 2 : z <= 12 ? 2.6 : z <= 14 ? 3.6 : 5; }

    function draw() {
        if (!st.canvas) return;
        var size = map.getSize(), dpr = window.devicePixelRatio || 1;
        var c = st.canvas, ctx = st.ctx;
        if (c.width !== Math.round(size.x * dpr) || c.height !== Math.round(size.y * dpr)) {
            c.width = Math.round(size.x * dpr); c.height = Math.round(size.y * dpr);
            c.style.width = size.x + "px"; c.style.height = size.y + "px";
        }
        var topLeft = map.containerPointToLayerPoint([0, 0]);
        L.DomUtil.setPosition(c, topLeft);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, size.x, size.y);
        st.nDrawn = 0;
        st.perRegion = {};
        if (!st.on || !st.loaded) { report(); return; }
        var z = map.getZoom(), scale = 256 * Math.pow(2, z);
        // 遠くからは線の下(線を隠さない)、寄ったら線の上(鉄塔が線に重なって見える)。マウスは取らないので上でも線は選べる
        st.pane.style.zIndex = z >= 12 ? 450 : 390;
        var po = map.getPixelOrigin(), ox = po.x + topLeft.x, oy = po.y + topLeft.y;
        var r = dotSize(z), h = r / 2, w = size.x, hh = size.y;
        // 遠くからは薄く小さく(線と変電所を隠さない)、寄ると白く縁取りして目立たせる
        ctx.fillStyle = z >= 13 ? "#f0f3f6" : z >= 10 ? "rgba(220,226,232,0.85)" : "rgba(200,208,216,0.5)";
        var stroke = z >= 13;
        if (stroke) { ctx.strokeStyle = "#0d1117"; ctx.lineWidth = 1; }
        for (var s = 0; s < st.sets.length; s++) {
            var S = st.sets[s], mx = S.mx, my = S.my, n = S.T.n, cnt = 0;
            for (var i = 0; i < n; i++) {
                var x = mx[i] * scale - ox, y = my[i] * scale - oy;
                if (x < -r || y < -r || x > w + r || y > hh + r) continue;
                ctx.fillRect(x - h, y - h, r, r);
                if (stroke) ctx.strokeRect(x - h, y - h, r, r);
                var k = st.nDrawn++;
                st.drawnX[k] = x; st.drawnY[k] = y; st.drawnSet[k] = s; st.drawnIdx[k] = i;
                cnt++;
            }
            st.perRegion[S.reg] = { data: n, drawn: cnt };
        }
        report();
    }

    var REGION_JA = { hokkaido: "北海道", tohoku: "東北", tokyo: "東京", chubu: "中部", hokuriku: "北陸",
                      kansai: "関西", chugoku: "中国", shikoku: "四国", kyushu: "九州", okinawa: "沖縄" };

    function report() {
        var el = document.getElementById("tower-count");
        if (!el) return;
        if (!st.on) { el.innerHTML = ""; return; }
        if (!st.loaded) { el.textContent = "鉄塔を読み込んでいます…"; return; }
        var tot = 0, drawn = 0, rows = "";
        st.sets.forEach(function (S) {
            var pr = st.perRegion[S.reg] || { data: S.T.n, drawn: 0 };
            tot += pr.data; drawn += pr.drawn;
            rows += "<tr><td>" + (REGION_JA[S.reg] || S.reg) + '</td><td class="n">' + pr.data.toLocaleString("ja-JP") +
                    '</td><td class="n">' + pr.drawn.toLocaleString("ja-JP") + "</td></tr>";
        });
        var loading = st.nLoaded < st.nRegions ? '<p class="ui-note">鉄塔を読み込んでいます（' + st.nLoaded + " / " + st.nRegions + " 地域）</p>" : "";
        el.innerHTML = loading + '<table class="tower-count"><thead><tr><th>地域</th><th class="n">データ</th><th class="n">いま見えている</th></tr></thead><tbody>' +
            rows + '</tbody><tfoot><tr><td>計</td><td class="n">' + tot.toLocaleString("ja-JP") + '</td><td class="n">' +
            drawn.toLocaleString("ja-JP") + "</td></tr></tfoot></table>" +
            '<p class="ui-note">' + (map.getZoom() >= PICK_ZOOM ? "点をクリックすると鉄塔の番号・載っている線・回線数・導体数が出ます。"
                : "もう少し寄ると（ズーム " + PICK_ZOOM + " 以上）、点をクリックして鉄塔を選べます。") +
            (st.tLoad != null ? " 読み込み " + (st.tLoad / 1000).toFixed(1) + " 秒。" : "") + "</p>";
    }

    // 画面の点(地図の入れ物の座標)に一番近い鉄塔
    function pick(cp, px) {
        var best = -1, bd = (px || PICK_PX) * (px || PICK_PX);
        for (var k = 0; k < st.nDrawn; k++) {
            var dx = st.drawnX[k] - cp.x, dy = st.drawnY[k] - cp.y, d = dx * dx + dy * dy;
            if (d <= bd) { bd = d; best = k; }
        }
        return best;
    }

    // 画面の点の近く(px 以内)にある地図の線(正典の枝)。近い順
    function linesNear(cp, px) {
        var layers = [];
        if (typeof lineLayer !== "undefined" && lineLayer) lineLayer.eachLayer(function (l) { layers.push(l); });
        if (typeof unroutedLayer !== "undefined" && unroutedLayer) unroutedLayer.eachLayer(function (l) { layers.push(l); });
        var a = map.containerPointToLatLng([cp.x - px, cp.y + px]), b = map.containerPointToLatLng([cp.x + px, cp.y - px]);
        var box = L.latLngBounds(a, b), out = [];
        layers.forEach(function (l) {
            if (!l.getBounds || !l.getBounds().intersects(box)) return;
            var parts = l.getLatLngs();
            if (parts.length && !Array.isArray(parts[0])) parts = [parts];
            var bd = Infinity;
            parts.forEach(function (pts) {
                for (var j = 0; j + 1 < pts.length; j++) {
                    var p = map.latLngToContainerPoint(pts[j]), q = map.latLngToContainerPoint(pts[j + 1]);
                    var vx = q.x - p.x, vy = q.y - p.y, wx = cp.x - p.x, wy = cp.y - p.y;
                    var t = (vx * vx + vy * vy) ? Math.max(0, Math.min(1, (wx * vx + wy * vy) / (vx * vx + vy * vy))) : 0;
                    var dx = p.x + t * vx - cp.x, dy = p.y + t * vy - cp.y, d = dx * dx + dy * dy;
                    if (d < bd) bd = d;
                }
            });
            if (bd <= px * px) {
                var f = (l.feature && l.feature.properties) || l._agjProps || {};
                out.push({ layer: l, d: Math.sqrt(bd), name: f._display_name || "", kv: f._voltage_kv || null });
            }
        });
        out.sort(function (x, y) { return x.d - y.d; });
        var seen = {}, uniq = [];
        out.forEach(function (x) { var k = x.name + "|" + x.kv; if (!seen[k]) { seen[k] = 1; uniq.push(x); } });
        return uniq.slice(0, 4);
    }

    function onClickCapture(e) {
        if (!st.on || !st.loaded || map.getZoom() < PICK_ZOOM || st.mode === "line") return;
        if (e.target.closest && e.target.closest(".leaflet-control, .agj-card, .leaflet-popup, .leaflet-tooltip")) return;
        var cp = map.mouseEventToContainerPoint(e);
        var k = pick(cp);
        if (k < 0) return;
        var near = linesNear(cp, LINE_PX);
        if (st.mode === "auto" && near.length) {
            // 線の上: よく寄っていて点の真上を押したときだけ鉄塔、それ以外は線(地図がそのまま線のカードを開く)
            var dx = st.drawnX[k] - cp.x, dy = st.drawnY[k] - cp.y;
            if (!(map.getZoom() >= 14 && dx * dx + dy * dy <= 9)) return;
        }
        e.stopPropagation();
        e.preventDefault();
        hideTip();
        var S = st.sets[st.drawnSet[k]];
        var tp = { x: st.drawnX[k], y: st.drawnY[k] };
        OSMRoutes.openTowerCard(S.T, st.drawnIdx[k], { lines: near.length ? near : linesNear(tp, 14) });
    }

    var hoverTimer = null;
    function onMove(e) {
        if (hoverTimer) return;
        hoverTimer = setTimeout(function () { hoverTimer = null; }, 50);
        if (!st.on || !st.loaded || map.getZoom() < 11 || st.mode === "line") { hideTip(); return; }
        var cp = map.mouseEventToContainerPoint(e);
        var k = pick(cp, st.mode === "auto" ? 3 : PICK_PX);
        if (k < 0) { hideTip(); return; }
        if (k === st.lastHover) return;
        st.lastHover = k;
        var S = st.sets[st.drawnSet[k]], i = st.drawnIdx[k], T = S.T;
        var ref = T.ref[i], nm = T.name[i];
        if (!st.tip) st.tip = L.tooltip({ direction: "top", offset: [0, -6], className: "agj-tip" });
        st.tip.setLatLng([T.la[i] / 1e5, T.lo[i] / 1e5])
            .setContent("鉄塔 " + AGJMap.esc(ref ? "No." + ref : (nm || "番号なし")) + "（クリックで詳しく）");
        if (!map.hasLayer(st.tip)) st.tip.addTo(map);
    }
    function hideTip() {
        st.lastHover = -1;
        if (st.tip && map.hasLayer(st.tip)) map.removeLayer(st.tip);
    }

    function setOn(on) {
        st.on = !!on;
        if (st.on) load().then(draw); else draw();
        if (!st.on) hideTip();
    }

    function setMode(m) {
        st.mode = m === "line" || m === "tower" ? m : "auto";
        document.querySelectorAll("#click-mode button").forEach(function (b) { b.classList.toggle("active", b.dataset.v === st.mode); });
        hideTip();
    }

    function init() {
        if (typeof map === "undefined" || !map || !global.OSMRoutes) return;
        ensureCanvas();
        map.on("moveend zoomend resize viewreset", draw);
        map.on("zoomstart", function () { if (st.canvas) st.canvas.style.visibility = "hidden"; });
        map.on("zoomend", function () { if (st.canvas) st.canvas.style.visibility = ""; });
        var box = map.getContainer();
        box.addEventListener("click", onClickCapture, true);
        box.addEventListener("mousemove", onMove);
        box.addEventListener("mouseleave", hideTip);
        var cb = document.getElementById("chk-towers");
        if (cb) { st.on = cb.checked; cb.addEventListener("change", function () { setOn(cb.checked); }); }
        document.querySelectorAll("#click-mode button").forEach(function (b) {
            b.addEventListener("click", function () { setMode(b.dataset.v); });
        });
        // 線と変電所を先に出し、鉄塔はそのあとで(読み込みを重ねない)
        if (st.on) {
            report();
            setTimeout(function () { load().catch(function (e) { console.warn("[tower_dots]", e); }); }, 300);
        }
    }

    global.TowerDots = {
        setOn: setOn, setMode: setMode, draw: draw, load: load,
        state: function () {
            var tot = 0, drawn = 0;
            Object.keys(st.perRegion).forEach(function (r) { tot += st.perRegion[r].data; drawn += st.perRegion[r].drawn; });
            return { on: st.on, loaded: st.loaded && st.nLoaded === st.nRegions, regionsLoaded: st.nLoaded, total: tot, drawn: drawn,
                     perRegion: st.perRegion, zoom: map.getZoom(), mode: st.mode, loadMs: st.tLoad };
        },
        // 確かめ用: 画面の点(地図の入れ物の座標)にある鉄塔
        pickAt: function (x, y) {
            var k = pick({ x: x, y: y });
            if (k < 0) return null;
            var S = st.sets[st.drawnSet[k]], i = st.drawnIdx[k];
            return { reg: S.reg, i: i, id: S.T.id[i], x: st.drawnX[k], y: st.drawnY[k] };
        },
        linesNear: function (x, y, px) { return linesNear({ x: x, y: y }, px || LINE_PX).map(function (o) { return { name: o.name, kv: o.kv, d: o.d }; }); },
    };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();
})(window);
