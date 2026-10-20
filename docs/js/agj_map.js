/* AGJ の地図ページが共通で使う地図部品(2026-10-20 io 一新の 1 段目).
 *
 * なぜ要るか: map.html は preferCanvas に変電所用・発電所用の pane を組み合わせていたため、
 * Leaflet が pane ごとに canvas を作り、地図全面に 3 枚重なっていた。canvas は自分の上に
 * 描いたものしか当たり判定をせず、下の canvas にイベントを渡さないので、一番上の発電所の
 * canvas がマウスを全部取り、送電線と変電所のホバー/クリックが半年効かなかった
 * (3e014ab7 から。docs/PAGES_INVENTORY.md §3)。
 *
 * ここでの決まり:
 *   - ベクトルの層はすべて 1 枚の canvas(AGJMap.renderer(map))に描く。pane を分けない
 *   - 当たり判定には余白(既定 6px)を付ける。細い線でも当たる
 *   - 上下は追加の順で決まる。後から足した層が点を隠すときは AGJMap.raise(...) で上げる
 *   - 説明は AGJMap.bindInfo で付ける(ホバーで吹き出し、クリックで詳しい説明)
 */
(function (global) {
    "use strict";

    var TOLERANCE = 6;

    // 背景地図。CARTO dark_all は 2026 年から API キー必須になったので、キー不要の地理院・淡色を
    // CSS で反転して暗くする(css/style.css の .agj-dark-tiles)
    var GSI = '&copy; <a href="https://maps.gsi.go.jp/development/ichiran.html">国土地理院</a>';
    function baseLayers() {
        return {
            "ダーク (地理院 淡色)": L.tileLayer("https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png",
                { attribution: GSI, maxZoom: 18, className: "agj-dark-tiles" }),
            "OSM": L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                { attribution: '&copy; <a href="https://www.openstreetmap.org/">OpenStreetMap</a>', maxZoom: 19 }),
            "地形図 (OpenTopoMap)": L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
                { attribution: 'Map data: &copy; <a href="https://www.openstreetmap.org/">OSM</a> contributors, SRTM | &copy; <a href="https://opentopomap.org">OpenTopoMap</a>', maxZoom: 17 }),
            "衛星 (Google)": L.tileLayer("https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
                { attribution: "Google", maxZoom: 20 }),
            "地図 (国土地理院)": L.tileLayer("https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png",
                { attribution: GSI, maxZoom: 18 }),
            "航空写真 (国土地理院)": L.tileLayer("https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg",
                { attribution: GSI, maxZoom: 18 }),
        };
    }

    /* 地図を作る。el は要素か id。opts: center, zoom, tolerance, defaultBase, storageKey。 */
    function createMap(el, opts) {
        opts = opts || {};
        var renderer = L.canvas({ tolerance: opts.tolerance == null ? TOLERANCE : opts.tolerance, padding: 0.5 });
        var map = L.map(el, {
            center: opts.center || [36.5, 137.0],
            zoom: opts.zoom == null ? 6 : opts.zoom,
            zoomControl: true,
            preferCanvas: true,
            renderer: renderer,
        });
        map._agjRenderer = renderer;

        var layers = baseLayers();
        var key = opts.storageKey || "agj_basemap";
        var saved = null;
        try { saved = localStorage.getItem(key); } catch (e) { /* 保存できない環境 */ }
        (layers[saved] || layers[opts.defaultBase || "ダーク (地理院 淡色)"]).addTo(map);
        L.control.layers(layers, null, { position: "topright", collapsed: true }).addTo(map);
        map.on("baselayerchange", function (e) {
            try { localStorage.setItem(key, e.name); } catch (err) { /* 同上 */ }
        });
        return map;
    }

    /* この地図の共有 canvas。層を作るときに { renderer: AGJMap.renderer(map) } と渡すと、
       pane を指定していても同じ canvas に描かれる。 */
    function renderer(map) {
        return map._agjRenderer;
    }

    /* 後から足した層の上に、点の層を上げる(渡した順に上へ積む)。 */
    function raise() {
        for (var i = 0; i < arguments.length; i++) {
            var layer = arguments[i];
            if (layer && layer.bringToFront) layer.bringToFront();
        }
    }

    /* 説明を付ける。tip はホバーの 1 行(文字列)、popup はクリックで出す HTML(文字列か関数)。 */
    function bindInfo(layer, tip, popup, popupOptions) {
        if (tip) layer.bindTooltip(tip, { sticky: true, className: "agj-tip" });
        if (popup) layer.bindPopup(popup, popupOptions || { maxWidth: 350 });
        return layer;
    }

    // ── クリックで右に出す詳細カード(2026-10-21 オーナー「クリックしてカード的に表示される機能も」) ──
    // spec = { kind: "送電線", color: "#ff9d3c", title, sub, rows: [[見出し, 値の HTML]], html, more: 折りたたむ HTML,
    //          actions: [{ text, href } | { text, onClick }], note }
    // 文字列は esc() を通してから渡す(OSM の名前に < > が入りうる)。

    function esc(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }

    function cardEl(map) {
        if (map._agjCard) return map._agjCard;
        var el = L.DomUtil.create("aside", "agj-card", map.getContainer());
        el.hidden = true;
        el.setAttribute("role", "dialog");
        el.setAttribute("aria-label", "選んだ設備の詳細");
        L.DomEvent.disableClickPropagation(el);
        L.DomEvent.disableScrollPropagation(el);
        map.on("click", function () { hideCard(map); });
        document.addEventListener("keydown", function (e) { if (e.key === "Escape") hideCard(map); });
        map._agjCard = el;
        return el;
    }

    function showCard(map, spec, selected) {
        var el = cardEl(map);
        unselect(map);
        var h = '<button type="button" class="agj-card-x" aria-label="閉じる">&times;</button>' +
            '<div class="agj-card-kind"><i style="background:' + esc(spec.color || "#888") + '"></i>' + esc(spec.kind) + "</div>" +
            '<h3 class="agj-card-title">' + esc(spec.title || "名称なし") + "</h3>" +
            (spec.sub ? '<div class="agj-card-sub">' + spec.sub + "</div>" : "");
        if (spec.rows && spec.rows.length) {
            h += '<dl class="agj-card-rows">' + spec.rows.map(function (r) {
                return "<dt>" + esc(r[0]) + "</dt><dd>" + r[1] + "</dd>";
            }).join("") + "</dl>";
        }
        if (spec.html) h += '<div class="agj-card-html">' + spec.html + "</div>";
        if (spec.more) h += '<details class="agj-card-more"><summary>' + esc(spec.moreTitle || "詳しく") + "</summary>" + spec.more + "</details>";
        if (spec.actions && spec.actions.length) {
            h += '<div class="agj-card-actions">' + spec.actions.map(function (a, i) {
                return a.href
                    ? '<a class="agj-card-btn' + (i === 0 ? " primary" : "") + '" href="' + esc(a.href) + '"' + (a.blank ? ' target="_blank" rel="noopener"' : "") + ">" + esc(a.text) + "</a>"
                    : '<button type="button" class="agj-card-btn' + (i === 0 ? " primary" : "") + '" data-i="' + i + '">' + esc(a.text) + "</button>";
            }).join("") + "</div>";
        }
        if (spec.note) h += '<p class="agj-card-note">' + spec.note + "</p>";
        el.innerHTML = h;
        el.querySelector(".agj-card-x").addEventListener("click", function () { hideCard(map); });
        el.querySelectorAll("button[data-i]").forEach(function (b) {
            b.addEventListener("click", function () { spec.actions[+b.dataset.i].onClick(); });
        });
        el.hidden = false;
        el.scrollTop = 0;
        if (selected) select(map, selected);
        map.fire("agjcardopen");
    }

    function hideCard(map) {
        if (!map._agjCard || map._agjCard.hidden) return;
        map._agjCard.hidden = true;
        unselect(map);
        map.fire("agjcardclose");
    }

    // 選んだ線・点を目立たせ、カードを閉じたら元に戻す
    function select(map, layer) {
        if (!layer.setStyle || !layer.options) return;
        var o = layer.options;
        map._agjSel = { layer: layer, style: { weight: o.weight, color: o.color, opacity: o.opacity, radius: o.radius } };
        if (layer.setRadius) {
            layer.setRadius((o.radius || 4) + 3);
            layer.setStyle({ color: "#ffffff", weight: 2.5 });
        } else {
            layer.setStyle({ weight: (o.weight || 2) + 4, opacity: 1 });
        }
        // 最前面に出すのは点だけ(線を上げると、閉じたあとも点の上に残ってホバーを塞ぐ)
        if (layer.setRadius && layer.bringToFront) layer.bringToFront();
    }

    function unselect(map) {
        var s = map._agjSel;
        if (!s) return;
        if (s.layer.setRadius && s.style.radius != null) s.layer.setRadius(s.style.radius);
        s.layer.setStyle({ weight: s.style.weight, color: s.style.color, opacity: s.style.opacity });
        map._agjSel = null;
    }

    /* クリックで詳細カードを出す。specFn(layer) が spec を返す。 */
    function bindCard(layer, specFn) {
        layer.on("click", function (e) {
            L.DomEvent.stopPropagation(e);
            var map = layer._map || (e.target && e.target._map);
            if (map) showCard(map, specFn(layer), layer);
        });
        return layer;
    }

    global.AGJMap = {
        TOLERANCE: TOLERANCE,
        createMap: createMap,
        renderer: renderer,
        raise: raise,
        bindInfo: bindInfo,
        esc: esc,
        bindCard: bindCard,
        showCard: showCard,
        hideCard: hideCard,
    };
})(window);
