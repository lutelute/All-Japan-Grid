/**
 * Grid Map 統合検索 (grid_search.js)
 *
 * 系統図サイドバー上部の検索ボックスから 2 系統を統合:
 *   (A) DB名検索 — ロード済みの変電所/送電線/発電所 (_display_name) を
 *       部分一致でオフライン即時検索 → 候補クリックで map.flyTo + 一時マーカー強調。
 *   (B) 地名ジオコーディング — Enter / 明示ボタン時のみ OSM Nominatim を叩いて
 *       地名→座標。利用規約配慮でデバウンス(>=350ms)・最小2文字・タイプ毎には叩かない。
 *       失敗/ヒット無しは静かにフォールバック(捏造しない=「該当なし」表示)。
 *
 * grid_map.js のグローバル(rawSubData / rawLineData / rawPlantData / map /
 * voltageColor / fmtKv / FUEL_COLORS / REGION_NAMES_JA)を参照する。
 * 既存の一覧/zoom は壊さない(独立した DOM とハンドラ)。
 */
(function () {
    "use strict";

    var DB_MAX_RESULTS = 10;        // DB候補の最大表示件数
    var GEO_LIMIT = 5;              // Nominatim limit
    var MIN_CHARS = 2;              // ジオコーディング最小文字数
    var GEO_DEBOUNCE_MS = 400;      // ジオコーディング・デバウンス(>=350ms)
    var FLY_ZOOM = 14;
    var FLY_ZOOM_LINE = 12;
    var NOMINATIM_URL = "https://nominatim.openstreetmap.org/search";

    var els = {};                   // DOM 参照キャッシュ
    var highlightMarker = null;     // 一時強調マーカー
    var highlightTimer = null;
    var geoDebounceTimer = null;
    var geoSeq = 0;                 // 競合する非同期応答の破棄用
    var lastGeoQuery = "";          // 同一クエリの二重発火抑止

    // ── 小ユーティリティ ──────────────────────────────────────────

    // grid_map.js の escHtml があれば使い、無ければ自前(独立稼働の保険)
    function esc(s) {
        if (typeof escHtml === "function") return escHtml(s);
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;")
            .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    function kvLabel(kv) {
        if (!(kv > 0)) return "";
        if (typeof fmtKv === "function") {
            var f = fmtKv(kv);
            return /異常/.test(f) ? "" : f;   // 異常電圧タグは候補メタに出さない
        }
        return kv + " kV";
    }

    function colorForKv(kv) {
        if (typeof voltageColor === "function") return voltageColor(kv);
        return "#888";
    }

    function regionJa(code) {
        if (typeof REGION_NAMES_JA !== "undefined" && REGION_NAMES_JA[code]) {
            return REGION_NAMES_JA[code];
        }
        return code || "";
    }

    // ── (A) DB名検索 ──────────────────────────────────────────────

    // Point の座標(lon,lat 配列)から [lat,lon] を返す。線は中点を採用。
    function pointFromGeometry(geom) {
        if (!geom) return null;
        if (geom.type === "Point") {
            var c = geom.coordinates;
            if (!c || c.length < 2) return null;
            return [c[1], c[0]];
        }
        if (geom.type === "LineString") {
            var cs = geom.coordinates;
            if (!cs || !cs.length) return null;
            var mid = cs[Math.floor(cs.length / 2)];
            if (!mid || mid.length < 2) return null;
            return [mid[1], mid[0]];
        }
        if (geom.type === "MultiLineString") {
            var seg = geom.coordinates && geom.coordinates[0];
            if (!seg || !seg.length) return null;
            var m = seg[Math.floor(seg.length / 2)];
            if (!m || m.length < 2) return null;
            return [m[1], m[0]];
        }
        if (geom.type === "Polygon") {
            var ring = geom.coordinates && geom.coordinates[0];
            if (!ring || !ring.length) return null;
            var p0 = ring[0];
            if (!p0 || p0.length < 2) return null;
            return [p0[1], p0[0]];
        }
        return null;
    }

    function collectFromFeatures(data, kind, ql, seen, out) {
        if (!data || !data.features) return;
        for (var i = 0; i < data.features.length && out.length < DB_MAX_RESULTS; i++) {
            var f = data.features[i];
            var p = f.properties || {};
            var name = (p._display_name || p.name || "").trim();
            if (!name) continue;
            if (name.toLowerCase().indexOf(ql) === -1) continue;
            var ll = pointFromGeometry(f.geometry);
            if (!ll) continue;
            var kv = p._voltage_kv || 0;
            // 名前+種別+リージョンで重複排除(同名の複数セグメント等を1件に集約)
            var dedupeKey = kind + "\x00" + name + "\x00" + (p._region || "");
            if (seen[dedupeKey]) continue;
            seen[dedupeKey] = true;
            out.push({
                kind: kind,                 // "sub" | "line" | "gen"
                name: name,
                kv: kv,
                fuel: p.fuel_type || "",
                mw: p.capacity_mw || 0,
                region: p._region || "",
                lat: ll[0],
                lon: ll[1],
            });
        }
    }

    function searchDb(q) {
        var ql = q.trim().toLowerCase();
        if (!ql) return [];
        var seen = {};
        var out = [];
        // 変電所優先 → 発電所 → 送電線 の順(同名衝突時に拠点を上位に)
        collectFromFeatures(typeof rawSubData !== "undefined" ? rawSubData : null, "sub", ql, seen, out);
        collectFromFeatures(typeof rawPlantData !== "undefined" ? rawPlantData : null, "gen", ql, seen, out);
        collectFromFeatures(typeof rawLineData !== "undefined" ? rawLineData : null, "line", ql, seen, out);
        return out.slice(0, DB_MAX_RESULTS);
    }

    var KIND_ICON = { sub: "■", line: "─", gen: "▲", geo: "📍" };
    var KIND_LABEL = { sub: "変電所", line: "送電線", gen: "発電所", geo: "地名" };

    // ── ズーム + 一時強調マーカー ────────────────────────────────

    function flyAndMark(lat, lon, zoom, label, accent) {
        if (typeof map === "undefined" || !map) return;
        map.flyTo([lat, lon], zoom || FLY_ZOOM, { duration: 0.8 });
        showHighlight(lat, lon, label, accent);
    }

    function showHighlight(lat, lon, label, accent) {
        if (typeof L === "undefined" || typeof map === "undefined" || !map) return;
        clearHighlight();
        var color = accent || "#e94560";
        var icon = L.divIcon({
            className: "grid-search-pin",
            html: '<div class="gs-pin-dot" style="--gs-pin:' + color + '"></div>',
            iconSize: [22, 22],
            iconAnchor: [11, 11],
        });
        highlightMarker = L.marker([lat, lon], { icon: icon, interactive: false, keyboard: false });
        try {
            highlightMarker.addTo(map);
            if (label) highlightMarker.bindTooltip(label, { permanent: false, direction: "top" });
        } catch (e) { /* 強調は副次機能。失敗しても本処理は継続 */ }
        if (highlightTimer) clearTimeout(highlightTimer);
        highlightTimer = setTimeout(clearHighlight, 6000);
    }

    function clearHighlight() {
        if (highlightTimer) { clearTimeout(highlightTimer); highlightTimer = null; }
        if (highlightMarker && typeof map !== "undefined" && map) {
            try { map.removeLayer(highlightMarker); } catch (e) {}
        }
        highlightMarker = null;
    }

    // ── 結果レンダリング ──────────────────────────────────────────

    function renderResults(html, show) {
        if (!els.results) return;
        els.results.innerHTML = html || "";
        els.results.style.display = show ? "block" : "none";
    }

    function dbResultRowHtml(r, idx) {
        var color = r.kind === "gen"
            ? ((typeof FUEL_COLORS !== "undefined" && FUEL_COLORS[r.fuel]) || "#999")
            : colorForKv(r.kv);
        var meta;
        if (r.kind === "gen") {
            meta = (r.fuel || "") + (r.mw > 0 ? " " + r.mw + "MW" : "");
        } else {
            meta = kvLabel(r.kv);
        }
        var rj = regionJa(r.region);
        if (rj) meta = (meta ? meta + " " : "") + rj;
        return '<div class="gs-result" data-idx="' + idx + '" data-kind="db"' +
            ' style="border-left-color:' + color + '">' +
            '<span class="gs-kind">' + (KIND_ICON[r.kind] || "?") + '</span>' +
            '<span class="gs-text"><b>' + esc(r.name) + '</b>' +
            '<small>' + esc(KIND_LABEL[r.kind] || "") + (meta ? " · " + esc(meta) : "") + "</small></span>" +
            "</div>";
    }

    function geoResultRowHtml(r, idx) {
        return '<div class="gs-result" data-idx="' + idx + '" data-kind="geo"' +
            ' style="border-left-color:#2ea043">' +
            '<span class="gs-kind">' + KIND_ICON.geo + '</span>' +
            '<span class="gs-text"><b>' + esc(r.label) + '</b>' +
            '<small>地名 (OSM)</small></span>' +
            "</div>";
    }

    // 現在表示中の候補(クリック解決用)
    var currentDb = [];
    var currentGeo = [];

    function showDbResults(results, q) {
        currentDb = results;
        currentGeo = [];
        var html = "";
        if (results.length) {
            html += '<div class="gs-section-label">系統データ (' + results.length + ")</div>";
            html += results.map(dbResultRowHtml).join("");
        } else {
            html += '<div class="gs-empty">系統データに該当なし</div>';
        }
        // 地名検索への導線(Enter でも可)
        html += '<div class="gs-geo-cta" id="gs-geo-cta">📍 「' + esc(q) +
            '」を地名で検索 <span class="gs-kbd">Enter</span></div>';
        renderResults(html, true);
    }

    function showGeoResults(results, q) {
        currentGeo = results;
        var html = '<div class="gs-section-label">地名 — OSM Nominatim (' + results.length + ")</div>";
        if (results.length) {
            html += results.map(geoResultRowHtml).join("");
        } else {
            html += '<div class="gs-empty">「' + esc(q) + '」は該当なし</div>';
        }
        // 直前の DB 候補も残す(参照しやすさ)
        if (currentDb.length) {
            html += '<div class="gs-section-label">系統データ (' + currentDb.length + ")</div>";
            html += currentDb.map(dbResultRowHtml).join("");
        }
        renderResults(html, true);
    }

    function showGeoPending(q) {
        var html = '<div class="gs-section-label">地名検索中… <span class="gs-spin"></span></div>';
        if (currentDb.length) {
            html += '<div class="gs-section-label">系統データ (' + currentDb.length + ")</div>";
            html += currentDb.map(dbResultRowHtml).join("");
        }
        renderResults(html, true);
    }

    // ── (B) ジオコーディング (Nominatim) ────────────────────────

    function runGeocode(q) {
        var query = (q || "").trim();
        if (query.length < MIN_CHARS) return;
        // 同一クエリの二重発火抑止(直前と同じなら投げ直さない)
        if (query === lastGeoQuery && currentGeo.length) {
            showGeoResults(currentGeo, query);
            return;
        }
        lastGeoQuery = query;
        var seq = ++geoSeq;
        showGeoPending(query);
        var url = NOMINATIM_URL +
            "?format=json&countrycodes=jp&limit=" + GEO_LIMIT +
            "&q=" + encodeURIComponent(query);
        fetch(url, {
            method: "GET",
            headers: { "Accept": "application/json" },
            // Referer は規約上の識別に資する。ブラウザが自動付与。
        }).then(function (res) {
            if (!res.ok) throw new Error("nominatim http " + res.status);
            return res.json();
        }).then(function (data) {
            if (seq !== geoSeq) return; // 競合する古い応答は破棄
            var results = (Array.isArray(data) ? data : []).map(function (d) {
                return {
                    label: d.display_name || d.name || query,
                    lat: parseFloat(d.lat),
                    lon: parseFloat(d.lon),
                };
            }).filter(function (r) {
                return isFinite(r.lat) && isFinite(r.lon);
            });
            showGeoResults(results, query);
        }).catch(function (err) {
            if (seq !== geoSeq) return;
            // 利用規約配慮: 失敗は静かにフォールバック(捏造しない)
            lastGeoQuery = "";  // 再試行可能にする
            // 既存の DB 候補は残しつつ、地名は静かに「取得失敗」を出す
            var html = '<div class="gs-empty">地名検索に失敗しました(時間をおいて再試行)</div>';
            if (currentDb.length) {
                html += '<div class="gs-section-label">系統データ (' + currentDb.length + ")</div>";
                html += currentDb.map(dbResultRowHtml).join("");
            }
            renderResults(html, true);
            if (typeof console !== "undefined" && console.warn) {
                console.warn("[grid_search] geocode failed (handled):", err && err.message);
            }
        });
    }

    // ── イベント処理 ──────────────────────────────────────────────

    function onInput() {
        var q = els.input.value || "";
        els.clear.style.display = q ? "block" : "none";
        if (geoDebounceTimer) { clearTimeout(geoDebounceTimer); geoDebounceTimer = null; }
        if (!q.trim()) {
            currentDb = []; currentGeo = [];
            renderResults("", false);
            return;
        }
        // (A) DB は即時。タイプ毎に Nominatim は叩かない(規約配慮)。
        var dbResults = searchDb(q);
        showDbResults(dbResults, q.trim());
    }

    function onKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            var q = (els.input.value || "").trim();
            if (q.length < MIN_CHARS) return;
            // Enter は明示操作 → デバウンス無しで即ジオコーディング
            if (geoDebounceTimer) { clearTimeout(geoDebounceTimer); geoDebounceTimer = null; }
            runGeocode(q);
        } else if (ev.key === "Escape") {
            clearSearch();
        }
    }

    function onResultsClick(ev) {
        var row = ev.target.closest ? ev.target.closest(".gs-result") : null;
        // 「地名で検索」CTA
        var cta = ev.target.closest ? ev.target.closest("#gs-geo-cta") : null;
        if (cta) {
            var q = (els.input.value || "").trim();
            if (q.length >= MIN_CHARS) runGeocode(q);
            return;
        }
        if (!row) return;
        var idx = parseInt(row.getAttribute("data-idx"), 10);
        var kind = row.getAttribute("data-kind");
        if (kind === "geo") {
            var g = currentGeo[idx];
            if (!g) return;
            flyAndMark(g.lat, g.lon, FLY_ZOOM, g.label.split(",")[0], "#2ea043");
        } else {
            var r = currentDb[idx];
            if (!r) return;
            var z = r.kind === "line" ? FLY_ZOOM_LINE : FLY_ZOOM;
            var accent = r.kind === "gen"
                ? ((typeof FUEL_COLORS !== "undefined" && FUEL_COLORS[r.fuel]) || "#e94560")
                : colorForKv(r.kv);
            flyAndMark(r.lat, r.lon, z, r.name, accent);
        }
    }

    function clearSearch() {
        els.input.value = "";
        els.clear.style.display = "none";
        currentDb = []; currentGeo = []; lastGeoQuery = "";
        if (geoDebounceTimer) { clearTimeout(geoDebounceTimer); geoDebounceTimer = null; }
        renderResults("", false);
        clearHighlight();
        els.input.focus();
    }

    // ── DOM 構築 + 初期化 ─────────────────────────────────────────

    function buildSearchBox() {
        var host = document.getElementById("tab-map");
        if (!host) return false;
        if (document.getElementById("grid-search-box")) return true; // 二重初期化防止

        var wrap = document.createElement("div");
        wrap.id = "grid-search-box";
        wrap.className = "section gs-section";
        wrap.innerHTML =
            '<h2>検索 Search <span class="gs-hint">地名・変電所・送電線</span></h2>' +
            '<div class="gs-input-row">' +
            '  <span class="gs-search-ico">🔍</span>' +
            '  <input id="gs-input" class="gs-input" type="text" autocomplete="off" ' +
            '         spellcheck="false" placeholder="嶺南 / 福井市 / 送電線名…">' +
            '  <button id="gs-clear" class="gs-clear" type="button" title="クリア" ' +
            '          style="display:none">✕</button>' +
            '</div>' +
            '<div id="gs-results" class="gs-results" style="display:none"></div>';

        // 「電圧階級」セクションの直前(=サイドバー最上部)に差し込む
        var firstSection = host.querySelector(".section");
        if (firstSection) host.insertBefore(wrap, firstSection);
        else host.insertBefore(wrap, host.firstChild);

        els.input = document.getElementById("gs-input");
        els.clear = document.getElementById("gs-clear");
        els.results = document.getElementById("gs-results");

        els.input.addEventListener("input", onInput);
        els.input.addEventListener("keydown", onKeydown);
        els.results.addEventListener("click", onResultsClick);
        els.clear.addEventListener("click", clearSearch);

        // フォーカスが外れたら結果を閉じる(クリックは mousedown を拾うので維持)
        document.addEventListener("click", function (ev) {
            if (!wrap.contains(ev.target)) renderResults("", false);
        });
        els.input.addEventListener("focus", function () {
            if ((els.input.value || "").trim()) onInput();
        });
        return true;
    }

    function init() {
        // grid_map.js の DOM(#tab-map)が存在する前提。無ければ静かに諦める。
        if (!buildSearchBox()) {
            // タブ生成が遅延する構成への保険(現状は静的だが念のため)
            var tries = 0;
            var t = setInterval(function () {
                tries++;
                if (buildSearchBox() || tries > 20) clearInterval(t);
            }, 200);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    // デバッグ/テスト用に最小限を公開(window 汚染は最小)
    window.gridSearch = {
        searchDb: searchDb,
        runGeocode: runGeocode,
        _state: function () { return { db: currentDb, geo: currentGeo }; },
    };
})();
