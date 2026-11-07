/* 系統図マップの MapLibre GL 版(試作・2026-11-07).
 *
 * map.html(Leaflet・js/grid_map.js)と同じ正典の層(data/map/lines_all・subs_all、data/plants_utility)を
 * WebGL で描く。読み方は 2 通りで、?src= で切り替える(既定は pmtiles):
 *   pmtiles: data/map/grid.pmtiles(scripts/build_map_gl_tiles.py)。見えている範囲のタイルだけ HTTP Range で読む
 *   geojson: GeoJSON を全部読む(Leaflet 版と同じファイル)。MapLibre が worker の中でタイルに切る
 * どちらも全部の電圧が入っていて、電圧の下限は filter で絞る(読み直さない)。
 *
 * 色と線の太さ・点の大きさ・詳細カードの項目は grid_map.js と同じにしてある(色は tests/test_map_gl_tiles.py が見る)。
 * 言葉は日本語と英語(?lang=ja|en)。設備の名前は OSM の name:en(data/map/names_en.json)、無ければそのまま。
 * 位置は URL の #z/lat/lon(MapLibre の hash。z は 512 px タイルの数え方なので Leaflet の z より 1 小さい)。
 */
(function () {
    "use strict";

    // ── 色(grid_map.js と同じ) ──
    var VOLTAGE_COLORS = {
        500: "#d62728",
        275: "#ff7f0e",
        220: "#e377c2",
        187: "#9467bd",
        154: "#2ca02c",
        132: "#17becf",
        110: "#1f77b4",
        77:  "#bcbd22",
        66:  "#8c564b",
        0:   "#cccccc",
    };
    var FUEL_COLORS = {
        nuclear: "#ff0000", coal: "#444444", gas: "#ff8800",
        oil: "#884400", hydro: "#0088ff", pumped_hydro: "#0044aa",
        wind: "#00cc88", solar: "#ffdd00", geothermal: "#cc4488",
        biomass: "#668833", waste: "#996633", tidal: "#006688",
        battery: "#aa00ff", unknown: "#999999",
    };
    var FUEL_ENTRIES = [
        ["nuclear", "原子力", "Nuclear"], ["coal", "石炭", "Coal"], ["gas", "ガス", "Gas"],
        ["oil", "石油", "Oil"], ["hydro", "水力", "Hydro"], ["pumped_hydro", "揚水", "Pumped hydro"],
        ["wind", "風力", "Wind"], ["solar", "太陽光", "Solar"], ["geothermal", "地熱", "Geothermal"],
        ["biomass", "バイオマス", "Biomass"], ["waste", "廃棄物", "Waste"], ["battery", "蓄電池", "Battery"],
        ["unknown", "その他", "Other"],
    ];
    var LEGEND_FUELS = ["nuclear", "coal", "gas", "oil", "hydro", "wind", "solar", "geothermal", "biomass"];
    var LEGEND_KV = [500, 275, 220, 187, 154, 132, 110, 77, 66];
    var KV_STEPS = [500, 275, 154, 66, 0];   // 電圧の下限の切り替え(Leaflet 版の区切りボタンと同じ)
    var KV_MAX_REAL = 1100;                  // これを超える電圧は OSM の多値タグの読み違い(grid_map.js と同じ)
    var TOLERANCE = 6;                       // 当たり判定の余白 px(js/agj_map.js と同じ)
    var CENTER = [137.0, 36.5], ZOOM = 5;    // Leaflet 版の setView([36.5, 137], 6) と同じ範囲

    // 変電所の種別(正典の category_ja は日本語だけ)
    var CATEGORY_EN = {
        "不明": "Unknown", "配電用変電所": "Distribution substation", "送電用変電所": "Transmission substation",
        "鉄道用変電所": "Railway substation", "需要家変電所": "Customer substation",
        "架空/地中切替所": "Overhead/underground transition", "発電所構内変電所": "Power plant substation",
        "配電塔": "Distribution kiosk", "周波数変換所/直流変換所": "Frequency / HVDC converter",
        "調相所": "Reactive power station", "開閉所": "Switching station",
    };

    var T = {
        ja: {
            title: "系統図マップ（MapLibre 試作） — All-Japan-Grid",
            subtitle: "系統図・MapLibre 試作",
            link_home: "← ダッシュボード", link_leaflet: "Leaflet 版",
            h_lang: "言語", h_kv: "電圧", h_layers: "表示", h_region: "地域", h_legend: "凡例", h_source: "読み方",
            kv_all: "すべて", lines: "送電線", subs: "変電所", plants: "発電所", all_japan: "全国",
            k_lines: "送電線", k_subs: "変電所", k_plants: "発電所",
            legend_kv: "電圧", legend_plants: "発電所", kv_unknown_short: "不明",
            src_pmtiles: "タイル", src_geojson: "GeoJSON",
            src_note_pmtiles: "見えている範囲のタイル（PMTiles）だけ読みます。",
            src_note_geojson: "GeoJSON を全部読みます（Leaflet 版と同じファイル）。",
            kv_label: function (mk) { return mk >= 500 ? "500 kV" : mk > 0 ? mk + " kV 以上" : "すべての電圧"; },
            status: function (r, kv, c) { return r + " ・ " + kv + "：変電所 " + c.subs + " ・ 送電線 " + c.lines + " ・ 発電所 " + c.plants; },
            drawn: function (s) { return "読み込みから描き終わりまで " + s + " 秒"; },
            loading: "読み込み中…", panel: "操作",
            noname: "名称なし", close: "閉じる", sep: " ・ ",
            r_kv: "電圧", r_region: "地域", r_par: "回線数", r_conn: "つながり", r_shape: "線形",
            main: "本系統", off_main: "本系統から切れている", shape: "正典（built）の枝・形は OpenStreetMap",
            r_cat: "種別", r_op: "運営", r_freq: "周波数",
            r_fuel: "燃料", r_cap_osm: "容量（OSM）", r_cap_src: "公式の容量", src_link: "出典",
            a_fit: "線の全体を見る", a_osm: "OpenStreetMap で見る", a_zoom: "この場所に寄る", a_subsld: "SubSLD で変電所の中を見る",
            note_line: "線路定数は電圧階級ごとの代表値です（実測ではありません）。",
            kv_unknown: "不明", kv_bad: "不明 (電圧タグ異常)",
            no_webgl: "この端末では WebGL が使えないため地図を描けません。Leaflet 版（map.html）を使ってください。",
            failed: "データを読めませんでした",
            gsi: "国土地理院",
        },
        en: {
            title: "Grid map (MapLibre trial) — All-Japan-Grid",
            subtitle: "Grid map · MapLibre trial",
            link_home: "← Dashboard", link_leaflet: "Leaflet version",
            h_lang: "Language", h_kv: "Voltage", h_layers: "Layers", h_region: "Region", h_legend: "Legend", h_source: "Loading",
            kv_all: "All", lines: "Lines", subs: "Substations", plants: "Power plants", all_japan: "All Japan",
            k_lines: "Transmission line", k_subs: "Substation", k_plants: "Power plant",
            legend_kv: "Voltage", legend_plants: "Power plants", kv_unknown_short: "Unknown",
            src_pmtiles: "Tiles", src_geojson: "GeoJSON",
            src_note_pmtiles: "Reads only the tiles in view (PMTiles).",
            src_note_geojson: "Reads the whole GeoJSON (same files as the Leaflet version).",
            kv_label: function (mk) { return mk >= 500 ? "500 kV" : mk > 0 ? mk + " kV and above" : "all voltages"; },
            status: function (r, kv, c) { return r + " · " + kv + ": " + c.subs + " substations · " + c.lines + " lines · " + c.plants + " plants"; },
            drawn: function (s) { return "Loaded and drawn in " + s + " s"; },
            loading: "Loading…", panel: "Controls",
            noname: "Unnamed", close: "Close", sep: " · ",
            r_kv: "Voltage", r_region: "Region", r_par: "Circuits", r_conn: "Connection", r_shape: "Geometry",
            main: "Main grid", off_main: "Cut off from the main grid", shape: "Canonical model (built) branch; shape from OpenStreetMap",
            r_cat: "Type", r_op: "Operator", r_freq: "Frequency",
            r_fuel: "Fuel", r_cap_osm: "Capacity (OSM)", r_cap_src: "Official capacity", src_link: "source",
            a_fit: "Show the whole line", a_osm: "Open in OpenStreetMap", a_zoom: "Zoom in here", a_subsld: "Inside this substation (SubSLD)",
            note_line: "Line constants are typical values per voltage class, not measurements.",
            kv_unknown: "Unknown", kv_bad: "Unknown (bad voltage tag)",
            no_webgl: "WebGL is not available on this device, so the map cannot be drawn. Use the Leaflet version (map.html).",
            failed: "Could not load the data",
            gsi: "GSI Japan",
        },
    };

    // ── 状態 ──
    var params = new URLSearchParams(location.search);
    var MODE = params.get("src") === "geojson" ? "geojson" : "pmtiles";
    var state = {
        lang: pickLang(),
        minKv: 275,
        region: "all",
        layers: { lines: true, subs: true, plants: true },
        card: null,           // { kind, props, geometry, lngLat }
    };
    var REGIONS = {}, REGION_ORDER = [], NAMES_EN = {}, MANIFEST = null;
    var map = null, sel = null, attribution = null, drawnSec = null;
    var FUEL = {};
    FUEL_ENTRIES.forEach(function (e) { FUEL[e[0]] = { ja: e[1], en: e[2] }; });

    function pickLang() {
        var q = params.get("lang");
        if (q === "ja" || q === "en") return q;
        try { var s = localStorage.getItem("agj_gl_lang"); if (s === "ja" || s === "en") return s; } catch (e) { /* 保存できない環境 */ }
        return /^ja\b/i.test(navigator.language || "ja") ? "ja" : "en";
    }
    function t(key) { return T[state.lang][key]; }

    function esc(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }
    function $(id) { return document.getElementById(id); }
    function nf(n) { return Number(n).toLocaleString(state.lang === "en" ? "en-US" : "ja-JP"); }

    // ── 値の書き方(grid_map.js の fmtKv・cleanName と同じ) ──
    function isCorruptKv(kv) { return !(kv > 0) || kv > KV_MAX_REAL; }
    function fmtKv(kv) {
        if (kv == null || kv === "") return t("kv_unknown");
        var n = +kv;
        return isCorruptKv(n) ? t("kv_bad") : n + " kV";
    }
    function bracket(kv) {
        if (isCorruptKv(kv)) return 0;
        for (var i = 0; i < LEGEND_KV.length; i++) if (kv >= LEGEND_KV[i]) return LEGEND_KV[i];
        return 0;
    }
    function voltageColor(kv) { return VOLTAGE_COLORS[bracket(kv)] || "#cccccc"; }
    function cleanName(n) { return String(n || "").replace(/\s*\d+(?:\.\d+)?\s*kV$/i, ""); }
    function mwOf(p) { return p.capacity_mw > 0 ? p.capacity_mw : null; }   // -1 などは容量不明の印
    function fmtNum(n) { return n == null ? "-" : (typeof n === "number" && n >= 1000 ? nf(n) : String(n)); }

    function nameOf(p, kind) {
        var ja = kind === "subs" ? cleanName(p.name || p._display_name) : (p._display_name || "");
        if (state.lang === "en") return NAMES_EN[ja] || NAMES_EN[p._display_name] || ja;
        return ja;
    }
    function regionName(p) {
        var r = REGIONS[p._region];
        if (state.lang === "en") return r ? r.name_en : (p._region || "—");
        return p._region_ja || p.region_ja || (r ? r.name_ja : "—");
    }
    function fuelName(f) { return (FUEL[f] || FUEL.unknown)[state.lang]; }

    // ── MapLibre の式 ──
    var KV = ["coalesce", ["get", "_voltage_kv"], 0];
    var KVc = ["case", [">", KV, KV_MAX_REAL], 0, KV];
    var SEL = ["boolean", ["feature-state", "sel"], false];
    function kvColorExpr() {
        var e = ["step", KVc, VOLTAGE_COLORS[0]];
        LEGEND_KV.slice().reverse().forEach(function (kv) { e.push(kv, VOLTAGE_COLORS[kv]); });
        return e;
    }
    var LINE_W = ["step", KVc, 1.5, 154, 2, 275, 2.5, 500, 3];          // voltageLineWeight
    var SUB_R = ["step", KVc, 3, 275, 4, 500, 5];                        // 変電所の半径
    var MW = ["coalesce", ["get", "capacity_mw"], 0];
    var PLANT_R = ["step", MW, 2.5, 1e-9, 3.5, 100, 5, 1000, 7];         // plantMarker の半径
    function fuelColorExpr() {
        var e = ["match", ["get", "fuel_type"]];
        Object.keys(FUEL_COLORS).forEach(function (k) { if (k !== "unknown") e.push(k, FUEL_COLORS[k]); });
        e.push(FUEL_COLORS.unknown);
        return e;
    }

    function src(layer) {
        return MODE === "pmtiles" ? { source: "grid", "source-layer": layer } : { source: layer };
    }

    function buildStyle() {
        var sources = {
            gsi: {
                type: "raster", tileSize: 256, maxzoom: 18,
                tiles: ["https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png"],
            },
        };
        if (MODE === "pmtiles") {
            sources.grid = {
                type: "vector",
                url: "pmtiles://" + new URL("./data/map/grid.pmtiles", location.href).href,
                promoteId: { lines: "_id", subs: "_id", plants: "_id" },
            };
        } else {
            sources.lines = { type: "geojson", data: "./data/map/lines_all.geojson", generateId: true };
            sources.subs = { type: "geojson", data: "./data/map/subs_all.geojson", generateId: true };
            sources.plants = { type: "geojson", data: "./data/plants_utility.geojson", generateId: true };
        }
        // 最初の絞り込み(275 kV 以上)は style に入れておく。読み終わってから setFilter すると、タイルを切り直す
        var lay = function (id, base, o) {
            var l = Object.assign({ id: id }, base, o), f = filterFor(id.replace("agj-", ""));
            if (f) l.filter = f;
            return l;
        };
        return {
            version: 8,
            sources: sources,
            layers: [
                { id: "bg", type: "background", paint: { "background-color": "#1c1f25" } },
                // css/style.css の .agj-dark-tiles(invert(1) hue-rotate(180deg) brightness(.78) contrast(.95) saturate(.35))
                // と同じ見え方。brightness の min>max で明暗を反転する
                { id: "gsi", type: "raster", source: "gsi", paint: {
                    "raster-hue-rotate": 180, "raster-saturation": -0.65, "raster-contrast": -0.05,
                    "raster-brightness-min": 0.78, "raster-brightness-max": 0, "raster-fade-duration": 0 } },
                lay("agj-lines", src("lines"), {
                    type: "line",
                    layout: { "line-cap": "round", "line-join": "round", "line-sort-key": KVc },
                    paint: {
                        "line-color": kvColorExpr(),
                        "line-width": ["case", SEL, ["+", LINE_W, 4], LINE_W],
                        "line-opacity": ["case", SEL, 1, 0.7],
                    },
                }),
                lay("agj-subs", src("subs"), {
                    type: "circle",
                    layout: { "circle-sort-key": KVc },
                    paint: {
                        "circle-radius": ["case", SEL, ["+", SUB_R, 3], SUB_R],
                        "circle-color": kvColorExpr(),
                        "circle-opacity": 0.9,
                        "circle-stroke-color": "#ffffff",
                        "circle-stroke-width": ["case", SEL, 2.5, 0.8],
                    },
                }),
                lay("agj-plants", src("plants"), {
                    type: "circle",
                    layout: { "circle-sort-key": ["-", 0, MW] },
                    paint: {
                        "circle-radius": ["case", SEL, ["+", PLANT_R, 3], PLANT_R],
                        "circle-color": fuelColorExpr(),
                        "circle-opacity": 0.85,
                        "circle-stroke-color": ["case", SEL, "#ffffff", "#000000"],
                        "circle-stroke-opacity": 0.9,
                        "circle-stroke-width": ["case", SEL, 2.5, 1],
                    },
                }),
            ],
        };
    }

    // ── 絞り込み(電圧の下限は線と変電所だけ。地域は 3 層とも) ──
    function filterFor(layer) {
        var f = ["all"];
        if (layer !== "plants" && state.minKv > 0) f.push([">=", KVc, state.minKv]);
        if (state.region !== "all") f.push(["==", ["get", "_region"], state.region]);
        return f.length > 1 ? f : null;
    }
    function applyFilters() {
        ["lines", "subs", "plants"].forEach(function (l) {
            map.setFilter("agj-" + l, filterFor(l));
            map.setLayoutProperty("agj-" + l, "visibility", state.layers[l] ? "visible" : "none");
        });
        renderStatus();
    }

    // ── 当たり判定・ホバー ──
    function pick(point) {
        var layers = ["plants", "subs", "lines"].filter(function (l) { return state.layers[l]; })
            .map(function (l) { return "agj-" + l; });
        if (!layers.length) return null;
        var r = TOLERANCE;
        var fs = map.queryRenderedFeatures([[point.x - r, point.y - r], [point.x + r, point.y + r]], { layers: layers });
        if (!fs.length) return null;
        // 点を線より先に(上に描いているので、重なったら点を取る)
        for (var i = 0; i < layers.length; i++) {
            for (var j = 0; j < fs.length; j++) if (fs[j].layer.id === layers[i]) return fs[j];
        }
        return fs[0];
    }
    function kindOf(f) { return f.layer.id.replace("agj-", ""); }

    function tipText(f) {
        var p = f.properties, k = kindOf(f), sep = " | ";
        if (k === "plants") {
            return t("k_plants") + " " + (nameOf(p, k) || t("noname")) + sep + fuelName(p.fuel_type || "unknown") +
                (mwOf(p) ? sep + fmtNum(mwOf(p)) + " MW" : "");
        }
        return t("k_" + k) + " " + (nameOf(p, k) || t("noname")) + sep + fmtKv(p._voltage_kv) + sep + regionName(p);
    }

    var hoverRaf = 0, hoverPt = null;
    function onMove(e) {
        hoverPt = e.point;
        if (!hoverRaf) hoverRaf = requestAnimationFrame(doHover);
    }
    function doHover() {
        hoverRaf = 0;
        var tip = $("tip");
        var f = hoverPt ? pick(hoverPt) : null;
        map.getCanvas().style.cursor = f ? "pointer" : "";
        if (!f) { tip.hidden = true; return; }
        tip.textContent = tipText(f);
        tip.hidden = false;
        var box = map.getContainer().getBoundingClientRect();
        var x = hoverPt.x + 14, y = hoverPt.y + 14;
        if (x + tip.offsetWidth > box.width - 8) x = hoverPt.x - tip.offsetWidth - 14;
        if (y + tip.offsetHeight > box.height - 8) y = hoverPt.y - tip.offsetHeight - 14;
        tip.style.transform = "translate(" + Math.max(4, x) + "px," + Math.max(4, y) + "px)";
    }

    // ── 選んだ設備を目立たせる(feature-state。タイルで切れた線も同じ id で全部光る) ──
    function select(f) {
        unselect();
        if (f.id == null) return;
        sel = { source: f.source, id: f.id };
        if (f.sourceLayer) sel.sourceLayer = f.sourceLayer;
        map.setFeatureState(sel, { sel: true });
    }
    function unselect() {
        if (sel) { map.setFeatureState(sel, { sel: false }); sel = null; }
    }

    // 線の全体: 読んである範囲の切れ端を集めて寄せ、新しく読んだタイルで広がったらもう一度(最大 4 回)
    function eachCoord(g, fn) {
        if (!g) return;
        if (g.type === "Point") fn(g.coordinates);
        else if (g.type === "LineString" || g.type === "MultiPoint") g.coordinates.forEach(fn);
        else if (g.type === "MultiLineString") g.coordinates.forEach(function (l) { l.forEach(fn); });
    }
    function boundsOf(selRef) {
        var parts = map.querySourceFeatures(selRef.source, { sourceLayer: selRef.sourceLayer, filter: ["==", ["id"], selRef.id] });
        var b = null;
        parts.forEach(function (p) {
            eachCoord(p.geometry, function (c) { b = b ? b.extend(c) : new maplibregl.LngLatBounds(c, c); });
        });
        return b;
    }
    function fitWhole(selRef, iter, prev) {
        var b = boundsOf(selRef);
        if (!b) return;
        var grew = !prev || b.getWest() < prev.getWest() - 1e-4 || b.getEast() > prev.getEast() + 1e-4 ||
            b.getSouth() < prev.getSouth() - 1e-4 || b.getNorth() > prev.getNorth() + 1e-4;
        if (!grew) return;
        map.fitBounds(b, { padding: 60, maxZoom: 13 });
        if (iter < 4) map.once("idle", function () { fitWhole(selRef, iter + 1, b); });
    }

    // ── 詳細カード(grid_map.js の lineCard・subCard・plantCard と同じ項目) ──
    function osmLink(ll) {
        return "https://www.openstreetmap.org/#map=16/" + ll.lat.toFixed(5) + "/" + ll.lng.toFixed(5);
    }
    function zoomAction(ll, z) {
        return { text: t("a_zoom"), onClick: function () { map.flyTo({ center: ll, zoom: Math.max(map.getZoom(), z) }); } };
    }
    function pointLL(g) { return { lng: g.coordinates[0], lat: g.coordinates[1] }; }

    function lineCard(c) {
        var p = c.props;
        var selRef = c.sel;
        return {
            kind: t("k_lines"), color: voltageColor(p._voltage_kv || 0),
            title: nameOf(p, "lines") || t("noname"),
            sub: esc([fmtKv(p._voltage_kv), regionName(p)].filter(Boolean).join(t("sep"))),
            rows: [[t("r_kv"), esc(fmtKv(p._voltage_kv))], [t("r_region"), esc(regionName(p))],
                   [t("r_par"), p._par ? esc(String(p._par)) : "—"],
                   [t("r_conn"), p._main === false ? t("off_main") : t("main")],
                   [t("r_shape"), t("shape")]],
            actions: [{ text: t("a_fit"), onClick: function () { if (selRef) fitWhole(selRef, 0, null); } },
                      { text: t("a_osm"), href: osmLink(c.lngLat), blank: true }],
            note: t("note_line"),
        };
    }
    function subCard(c) {
        var p = c.props, ll = pointLL(c.geometry), ja = cleanName(p.name || p._display_name);
        var rows = [[t("r_kv"), esc(fmtKv(p._voltage_kv != null ? p._voltage_kv : p.voltage_kv))],
                    [t("r_region"), esc(regionName(p))]];
        if (p.category_ja) rows.push([t("r_cat"), esc(state.lang === "en" ? (CATEGORY_EN[p.category_ja] || p.category_ja) : p.category_ja)]);
        if (p.operator) rows.push([t("r_op"), esc(state.lang === "en" && p.operator_en ? p.operator_en : p.operator)]);
        if (p.frequency_hz) rows.push([t("r_freq"), esc(p.frequency_hz + " Hz")]);
        if (p._main != null) rows.push([t("r_conn"), p._main ? t("main") : t("off_main")]);
        return {
            kind: t("k_subs"), color: voltageColor(p._voltage_kv || 0),
            title: nameOf(p, "subs") || t("noname"),
            sub: esc(ll.lat.toFixed(4) + ", " + ll.lng.toFixed(4)),
            rows: rows,
            actions: [ja ? { text: t("a_subsld"), href: "./subsld.html?q=" + encodeURIComponent(ja.replace(/変電所$/, "")) } : null,
                      zoomAction(ll, 13),   // Leaflet の 14 と同じ縮尺
                      { text: t("a_osm"), href: osmLink(ll), blank: true }].filter(Boolean),
        };
    }
    function plantCard(c) {
        var p = c.props, ll = pointLL(c.geometry), fuel = p.fuel_type || "unknown";
        var rows = [[t("r_fuel"), esc(fuelName(fuel))],
                    [t("r_cap_osm"), mwOf(p) ? esc(fmtNum(mwOf(p)) + " MW") : "—"]];
        if (p.capacity_mw_sourced != null) {
            rows.push([t("r_cap_src"), "<b>" + esc(fmtNum(p.capacity_mw_sourced) + " MW") + "</b>" +
                (p.capacity_source_url ? ' <a href="' + esc(p.capacity_source_url) + '" target="_blank" rel="noopener">' + t("src_link") + "</a>" : "")]);
        }
        rows.push([t("r_region"), esc(regionName(p))]);
        return {
            kind: t("k_plants"), color: FUEL_COLORS[fuel] || FUEL_COLORS.unknown,
            title: nameOf(p, "plants") || t("noname"),
            sub: esc([fuelName(fuel), mwOf(p) ? fmtNum(mwOf(p)) + " MW" : ""].filter(Boolean).join(t("sep"))),
            rows: rows,
            html: p.capacity_source_note ? '<p class="card-src">' + esc(p.capacity_source_note) + "</p>" : "",
            actions: [zoomAction(ll, 12), { text: t("a_osm"), href: osmLink(ll), blank: true }],
        };
    }

    function openCard(f, lngLat) {
        var kind = kindOf(f);
        state.card = { kind: kind, props: f.properties, geometry: f.geometry, lngLat: lngLat,
                       sel: f.id != null ? { source: f.source, sourceLayer: f.sourceLayer, id: f.id } : null };
        renderCard();
        select(f);
    }
    function renderCard() {
        var el = $("card"), c = state.card;
        if (!c) { el.hidden = true; return; }
        var spec = c.kind === "lines" ? lineCard(c) : c.kind === "subs" ? subCard(c) : plantCard(c);
        var h = '<button type="button" class="card-x" aria-label="' + esc(t("close")) + '">&times;</button>' +
            '<div class="card-kind"><i style="background:' + esc(spec.color) + '"></i>' + esc(spec.kind) + "</div>" +
            '<h3 class="card-title">' + esc(spec.title) + "</h3>" +
            (spec.sub ? '<div class="card-sub">' + spec.sub + "</div>" : "");
        if (spec.rows.length) {
            h += '<dl class="card-rows">' + spec.rows.map(function (r) {
                return "<dt>" + esc(r[0]) + "</dt><dd>" + r[1] + "</dd>";
            }).join("") + "</dl>";
        }
        if (spec.html) h += spec.html;
        h += '<div class="card-actions">' + spec.actions.map(function (a, i) {
            return a.href
                ? '<a class="card-btn" href="' + esc(a.href) + '"' + (a.blank ? ' target="_blank" rel="noopener"' : "") + ">" + esc(a.text) + "</a>"
                : '<button type="button" class="card-btn" data-i="' + i + '">' + esc(a.text) + "</button>";
        }).join("") + "</div>";
        if (spec.note) h += '<p class="card-note">' + esc(spec.note) + "</p>";
        el.innerHTML = h;
        el.setAttribute("aria-label", spec.kind);
        el.querySelector(".card-x").addEventListener("click", closeCard);
        el.querySelectorAll("button[data-i]").forEach(function (b) {
            b.addEventListener("click", function () { spec.actions[+b.dataset.i].onClick(); });
        });
        el.hidden = false;
    }
    function closeCard() {
        state.card = null;
        $("card").hidden = true;
        unselect();
    }

    // ── 左の操作 ──
    function setSeg(id, value) {
        $(id).querySelectorAll("button").forEach(function (b) {
            var on = b.dataset.v === String(value);
            b.classList.toggle("on", on);
            b.setAttribute("aria-pressed", on ? "true" : "false");
        });
    }

    function renderTexts() {
        document.documentElement.lang = state.lang;
        document.title = t("title");
        document.querySelectorAll("[data-t]").forEach(function (el) { el.textContent = t(el.dataset.t); });
        $("seg-kv").querySelector('[data-v="0"]').textContent = t("kv_all");
        $("src-note").textContent = t(MODE === "pmtiles" ? "src_note_pmtiles" : "src_note_geojson");
        setSeg("seg-lang", state.lang);
        setSeg("seg-kv", state.minKv);
        setSeg("seg-src", MODE);
        renderRegions();
        renderLegend();
        renderStatus();
        renderCard();
        renderAttribution();
    }

    function renderRegions() {
        var box = $("regions");
        var ids = ["all"].concat(REGION_ORDER);
        box.innerHTML = ids.map(function (id) {
            var label = id === "all" ? t("all_japan") : (state.lang === "en" ? REGIONS[id].name_en : REGIONS[id].name_ja);
            return '<button type="button" data-v="' + id + '" class="' + (state.region === id ? "on" : "") +
                '" aria-pressed="' + (state.region === id) + '">' + esc(label) + "</button>";
        }).join("");
    }

    function renderLegend() {
        var h = '<div class="lg-h">' + esc(t("legend_kv")) + '</div><div class="lg-grid">';
        LEGEND_KV.forEach(function (kv) {
            h += '<span><i class="sw-line" style="background:' + VOLTAGE_COLORS[kv] + '"></i>' + kv + " kV</span>";
        });
        h += '<span><i class="sw-line" style="background:' + VOLTAGE_COLORS[0] + '"></i>' + esc(t("kv_unknown_short")) + "</span>";
        h += '</div><div class="lg-h">' + esc(t("legend_plants")) + '</div><div class="lg-grid">';
        LEGEND_FUELS.forEach(function (k) {
            h += '<span><i class="sw-dot" style="background:' + FUEL_COLORS[k] + '"></i>' + esc(fuelName(k)) + "</span>";
        });
        $("legend").innerHTML = h + "</div>";
    }

    function renderStatus() {
        var el = $("status");
        if (!MANIFEST) { el.textContent = t("loading"); return; }
        var row = (MANIFEST.counts[state.region] || {})[String(state.minKv)] || {};
        var c = {};
        ["lines", "subs", "plants"].forEach(function (l) { c[l] = nf(state.layers[l] ? (row[l] || 0) : 0); });
        var r = state.region === "all" ? t("all_japan") : (state.lang === "en" ? REGIONS[state.region].name_en : REGIONS[state.region].name_ja);
        el.innerHTML = esc(t("status")(r, t("kv_label")(state.minKv), c)) +
            (drawnSec != null ? '<br><span class="mut">' + esc(t("drawn")(drawnSec)) + "</span>" : "");
    }

    function renderAttribution() {
        if (!map) return;
        if (attribution) map.removeControl(attribution);
        attribution = new maplibregl.AttributionControl({
            compact: true,
            // 背景は地理院、送電網は AGJ(線と点の形は OpenStreetMap、ODbL)
            customAttribution: ['<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank" rel="noopener">' + esc(t("gsi")) + "</a>",
                                '<a href="https://github.com/lutelute/All-Japan-Grid" target="_blank" rel="noopener">All-Japan-Grid</a>',
                                '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>'],
        });
        map.addControl(attribution, "bottom-right");
    }

    function bindPanel() {
        $("seg-lang").addEventListener("click", function (e) {
            var v = e.target.closest("button"); if (!v) return;
            state.lang = v.dataset.v;
            try { localStorage.setItem("agj_gl_lang", state.lang); } catch (err) { /* 同上 */ }
            var u = new URL(location.href); u.searchParams.set("lang", state.lang);
            history.replaceState(null, "", u.pathname + u.search + location.hash);
            renderTexts();
        });
        $("seg-kv").addEventListener("click", function (e) {
            var v = e.target.closest("button"); if (!v || !map) return;
            state.minKv = +v.dataset.v;
            setSeg("seg-kv", state.minKv);
            applyFilters();
        });
        $("seg-src").addEventListener("click", function (e) {
            var v = e.target.closest("button"); if (!v || v.dataset.v === MODE) return;
            var u = new URL(location.href);
            u.searchParams.set("src", v.dataset.v);
            u.searchParams.set("lang", state.lang);
            location.href = u.pathname + u.search + location.hash;
        });
        document.querySelectorAll("input[data-layer]").forEach(function (cb) {
            cb.addEventListener("change", function () {
                state.layers[cb.dataset.layer] = cb.checked;
                if (map) applyFilters();
            });
        });
        $("regions").addEventListener("click", function (e) {
            var v = e.target.closest("button"); if (!v || !map) return;
            state.region = v.dataset.v;
            renderRegions();
            applyFilters();
            if (state.region === "all") {
                map.easeTo({ center: CENTER, zoom: ZOOM });
            } else {
                var bb = REGIONS[state.region].bounding_box;
                map.fitBounds([[bb.lon_min, bb.lat_min], [bb.lon_max, bb.lat_max]], { padding: 30 });
            }
        });
        $("panel-toggle").addEventListener("click", function () {
            var open = document.body.classList.toggle("panel-open");
            $("panel-toggle").setAttribute("aria-expanded", String(open));
        });
        document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeCard(); });
    }

    // ── 起動 ──
    window.AGJ_GL = { mode: MODE, ready: false };

    function fetchJSON(url) {
        return fetch(url).then(function (r) { if (!r.ok) throw new Error(url + " " + r.status); return r.json(); });
    }

    function start() {
        bindPanel();
        renderTexts();
        Promise.all([fetchJSON("./data/map/regions.json"), fetchJSON("./data/map/names_en.json"), fetchJSON("./data/map/grid_gl.json")])
            .then(function (res) {
                res[0].forEach(function (r) { REGIONS[r.id] = r; REGION_ORDER.push(r.id); });
                NAMES_EN = res[1];
                MANIFEST = res[2];
                renderTexts();
            })
            .catch(function (err) { console.error(err); $("status").textContent = t("failed"); });

        if (MODE === "pmtiles") {
            var protocol = new pmtiles.Protocol();
            maplibregl.addProtocol("pmtiles", protocol.tile);
        }
        try {
            map = new maplibregl.Map({
                container: "map",
                style: buildStyle(),
                center: CENTER, zoom: ZOOM, minZoom: 3, maxZoom: 18,
                hash: true,                  // #z/lat/lon
                attributionControl: false,
                dragRotate: false, pitchWithRotate: false, touchPitch: false,
                fadeDuration: 0,
            });
        } catch (err) {
            $("map").innerHTML = '<p class="no-gl">' + esc(t("no_webgl")) + "</p>";
            console.warn(err);
            return;
        }
        window.agjMap = map;
        map.touchZoomRotate.disableRotation();
        map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
        map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
        renderAttribution();
        // 海の上の地理院タイルは高いズームで 404 になる(Leaflet 版も同じで、黙って空白にする)
        map.on("error", function (e) {
            if (e && e.sourceId === "gsi") return;
            console.error(e && e.error ? e.error : e);
        });
        // ページを開いてから(performance.now の原点=読み込み開始)、線と点を全部描き終えるまで。
        // 背景の地理院タイルは数えない(Leaflet 版の測り方とそろえる。地理院の速さは外の事情)
        var gridSources = MODE === "pmtiles" ? ["grid"] : ["lines", "subs", "plants"];
        map.on("render", function onRender() {
            var done = gridSources.every(function (s) { return map.getSource(s) && map.isSourceLoaded(s); });
            if (!done) return;
            map.off("render", onRender);
            var ms = performance.now();
            drawnSec = (ms / 1000).toFixed(2);
            window.AGJ_GL.ready = true;
            window.AGJ_GL.t_drawn_ms = Math.round(ms);
            renderStatus();
        });
        map.on("mousemove", onMove);
        map.on("mouseout", function () { hoverPt = null; $("tip").hidden = true; });
        map.on("click", function (e) {
            var f = pick(e.point);
            if (f) openCard(f, e.lngLat); else closeCard();
        });
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
    else start();
})();
