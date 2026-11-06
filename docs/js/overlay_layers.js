/* 系統図マップ(map.html)の「重ねて見る」に足す層(2026-11-07, B).
 *
 * 2 つのまとまりを足す。どれも見せ方だけの層で、正典(docs/data/built)は変えない。
 *   B-1 系統の容量・潮流 … 連系線の運用容量(OCCTO)と値差の割合(JEPX)・送電線の潮流の実績(各社の公表の年統計)・
 *                         混み具合(AGJ の計算)・エリアの価格(JEPX の年度平均)・エリアの需要(でんき予報)
 *   B-2 災害と土地       … 津波・洪水・高潮・土砂災害(ハザードマップポータルサイト)・赤色立体地図・土地利用(国土地理院)
 *
 * 決まり:
 *   - 公表値(observed)と計算値(derived)を混ぜない(docs/OBSERVED_VS_DERIVED.md)。公表値は実線・「公表」、
 *     計算は破線・「計算」と書き、色も重ねない
 *   - 線と点は 1 枚の canvas(AGJMap.renderer(map))に描く(js/agj_map.js の冒頭)。タイルは別
 *   - 各社の線路別の容量(rating)・空き容量の生の値は載せない(利用条件が公開を許すと確かめられていない)。
 *     公表ページへのリンクだけを置く
 *   - grid_map.js は書き換えない。読むのは map・substationLayer・plantLayer(どれもグローバル)だけ
 *
 * map.html では「重ねて見る」の中の data-ov="…" のチェックと data-ov-opacity="…" のスライダーをこのファイルがつなぐ。
 */
(function (global) {
    "use strict";

    var DATA = "./data/";
    var esc = function (s) { return global.AGJMap ? AGJMap.esc(s) : String(s == null ? "" : s); };
    var fmt = function (x, d) {
        if (x == null || isNaN(x)) return "—";
        return Number(x).toLocaleString("ja-JP", { maximumFractionDigits: d == null ? 0 : d, minimumFractionDigits: d || 0 });
    };

    // ── 出典 ──
    var SRC = {
        haz: '出典: <a href="https://disaportal.gsi.go.jp/hazardmap/copyright/opendata.html" target="_blank" rel="noopener">ハザードマップポータルサイト</a>（タイルをそのまま表示）',
        gsi: '出典: <a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank" rel="noopener">国土地理院（地理院タイル）</a>',
        occto: '出典: <a href="https://web-kohyo.occto.or.jp/kks-web-public/" target="_blank" rel="noopener">電力広域的運営推進機関（OCCTO）系統情報公表</a>の 30 分値を AGJ が中央値・最大に集計（加工）',
        jepx: '出典: <a href="https://www.jepx.jp/" target="_blank" rel="noopener">日本卸電力取引所（JEPX）</a>スポット市場の取引結果を AGJ が年度で集計（加工）',
        tso: '出典: 各一般送配電事業者の系統情報の公表（潮流実績）。AGJ が年の統計 3 つ（平均・p95・最大）にまとめたもの',
        yoho: '出典: 各一般送配電事業者のでんき予報（1 時間値）',
        agj: '計算: AGJ のモデル（正典 built）で、でんき予報の需要に合わせて解いた潮流',
    };
    var HAZ_NOTE = "最新・詳しい情報は各市町村のハザードマップで確かめてください。";

    // ── B-2 タイル ──
    var D = "https://disaportaldata.gsi.go.jp/raster/";
    var G = "https://cyberjapandata.gsi.go.jp/xyz/";
    var HAZ_ATTR = '<a href="https://disaportal.gsi.go.jp/hazardmap/copyright/opendata.html">ハザードマップポータルサイト</a>';
    var GSI_ATTR = '&copy; <a href="https://maps.gsi.go.jp/development/ichiran.html">国土地理院</a>';

    // 浸水深の凡例(ハザードマップポータルサイトの凡例画像 img/shinsui_legend3.png の色)
    var SHINSUI = [
        ["#dc7adc", "20 m 以上"], ["#f285c9", "10〜20 m"], ["#ff9191", "5〜10 m"], ["#ffb7b7", "3〜5 m"],
        ["#ffd8c0", "0.5〜3 m"], ["#f8e1a6", "0.5〜1 m"], ["#f7f5a9", "0.5 m 未満"], ["#ffffb3", "0.3 m 未満"],
    ];

    var TILES = {
        tsunami: { group: "hazard", title: "津波浸水想定", urls: [D + "04_tsunami_newlegend_data/{z}/{x}/{y}.png"],
                   minNative: 2, maxNative: 17, attr: HAZ_ATTR, src: SRC.haz, swatches: SHINSUI, note: "浸水する深さ。" + HAZ_NOTE },
        flood:   { group: "hazard", title: "洪水浸水想定（想定最大規模）", urls: [D + "01_flood_l2_shinsuishin_data/{z}/{x}/{y}.png"],
                   minNative: 2, maxNative: 17, attr: HAZ_ATTR, src: SRC.haz, swatches: SHINSUI, note: "浸水する深さ。" + HAZ_NOTE },
        hightide:{ group: "hazard", title: "高潮浸水想定", urls: [D + "03_hightide_l2_shinsuishin_data/{z}/{x}/{y}.png"],
                   minNative: 2, maxNative: 17, attr: HAZ_ATTR, src: SRC.haz, swatches: SHINSUI, note: "浸水する深さ。" + HAZ_NOTE },
        sediment:{ group: "hazard", title: "土砂災害警戒区域", urls: [
                       D + "05_dosekiryukeikaikuiki/{z}/{x}/{y}.png",
                       D + "05_kyukeishakeikaikuiki/{z}/{x}/{y}.png",
                       D + "05_jisuberikeikaikuiki/{z}/{x}/{y}.png"],
                   minNative: 2, maxNative: 17, attr: HAZ_ATTR, src: SRC.haz,
                   swatches: [["#e6c832", "警戒区域"], ["#a50021", "特別警戒区域"]],
                   note: "土石流・急傾斜地の崩壊・地すべりの 3 つを重ねて表示。色合いは種類や地域で少し違う。広い範囲では区域が点に見える。" + HAZ_NOTE },
        relief:  { group: "land", title: "赤色立体地図", urls: [G + "sekishoku/{z}/{x}/{y}.png"],
                   minNative: 2, maxNative: 14, attr: GSI_ATTR, src: SRC.gsi,
                   note: "地形の起伏を赤色の濃淡で表した地図（地理院の説明）。細かい起伏が見やすい。" },
        landuse: { group: "land", title: "土地利用（1982〜83 年）", urls: [G + "lum200k/{z}/{x}/{y}.png"],
                   minZoom: 11, minNative: 11, maxNative: 14, attr: GSI_ATTR, src: SRC.gsi,
                   legendImg: "https://maps.gsi.go.jp/legend/lum200k_legend.jpg",
                   note: "20 万分の 1 土地利用図。森林・田・畑・市街地など。40 年前の図で、いまの土地利用とは違う所がある。ズーム 11 以上で出る。" },
    };

    // ── B-1 の色 ──
    // 値差の割合(公表の価格から集計)は紫の濃淡、計算の混み具合は黄〜赤の破線。エリアの価格は青緑〜黄(viridis)
    var SPLIT_BINS = [[0.10, "#5b4a86", "10% 未満"], [0.25, "#7c5cc4", "10〜25%"], [0.40, "#a77bf3", "25〜40%"], [Infinity, "#d7b8ff", "40% 以上"]];
    // 計算の混み具合は 1 色(明るい黄)の破線で、太さで段階を分ける。送電線の電圧の色(橙・赤・緑…)と重ねないため
    var LOAD_COLOR = "#ffe14d";
    var LOAD_BINS = [[80, 2.2, "50〜80%"], [100, 3.4, "80〜100%"], [Infinity, 5, "100% 超"]];
    var PRICE_BINS = [[9.5, "#3b528b", "9.5 円未満"], [10.5, "#21918c", "9.5〜10.5 円"], [11.5, "#5ec962", "10.5〜11.5 円"], [Infinity, "#fde725", "11.5 円以上"]];
    var OBS_COLOR = "#f0f6fc";
    var CASING = "#0d1117";

    function bin(bins, v) {
        for (var i = 0; i < bins.length; i++) if (v < bins[i][0]) return bins[i];
        return bins[bins.length - 1];
    }

    var UTIL_JA = {
        hokkaido: "北海道電力ネットワーク", tohoku: "東北電力ネットワーク", tokyo: "東京電力パワーグリッド",
        chubu: "中部電力パワーグリッド", hokuriku: "北陸電力送配電", kansai: "関西電力送配電",
        chugoku: "中国電力ネットワーク", shikoku: "四国電力送配電", kyushu: "九州電力送配電", okinawa: "沖縄電力",
    };
    // エリアの目印の位置(各エリアの代表都市)。境界ではない
    var AREA_POINTS = {
        "北海道": [43.06, 141.35, "hokkaido"], "東北": [38.27, 140.87, "tohoku"], "東京": [35.68, 139.77, "tokyo"],
        "中部": [35.18, 136.91, "chubu"], "北陸": [36.70, 137.21, "hokuriku"], "関西": [34.69, 135.50, "kansai"],
        "中国": [34.39, 132.46, "chugoku"], "四国": [34.34, 134.05, "shikoku"], "九州": [33.59, 130.40, "kyushu"],
        "沖縄": [26.21, 127.68, "okinawa"],
    };
    // 連系線の数字の置き場所(重ならないように向きを変える。見せ方だけ)
    var IC_LABEL_DIR = {
        "hokkaido-tohoku": "right", "tohoku-tokyo": "right", "tokyo-chubu": "right", "chubu-kansai": "bottom",
        "chubu-hokuriku": "top", "hokuriku-kansai": "left", "kansai-chugoku": "top", "kansai-shikoku": "bottom",
        "chugoku-shikoku": "bottom", "chugoku-kyushu": "left",
    };

    // ── 状態 ──
    var on = {};                         // key → true
    var opacity = { hazard: 0.7, land: 0.6 };
    var tileLayers = {};                 // key → [L.TileLayer]
    var vecLayers = {};                  // key → L.LayerGroup
    var cache = {};                      // url → Promise<json>
    var legendCtl = null;
    var meta = {};                       // 層ごとの凡例に出す追加の文(取得時刻など)

    function getMap() {
        var m = global.map;
        return (m && typeof m.addLayer === "function") ? m : null;
    }

    function fetchJSON(url) {
        if (!cache[url]) {
            cache[url] = fetch(url).then(function (r) {
                if (!r.ok) throw new Error(url + " → " + r.status);
                return r.json();
            });
            cache[url].catch(function () { delete cache[url]; });
        }
        return cache[url];
    }

    function panes(map) {
        if (map.getPane("agjOvLand")) return;
        var p1 = map.createPane("agjOvLand");     // 地形(280)の下
        p1.style.zIndex = 270; p1.style.pointerEvents = "none";
        var p2 = map.createPane("agjOvHazard");   // 地形(280)と適地スコア(300)のあいだ
        p2.style.zIndex = 290; p2.style.pointerEvents = "none";
    }

    // ── タイル(B-2) ──
    function setTile(key, show) {
        var map = getMap(), def = TILES[key];
        if (!map || !def) return;
        panes(map);
        if (show) {
            if (!tileLayers[key]) {
                tileLayers[key] = def.urls.map(function (u) {
                    return L.tileLayer(u, {
                        pane: def.group === "hazard" ? "agjOvHazard" : "agjOvLand",
                        opacity: opacity[def.group],
                        minZoom: def.minZoom || 0,
                        minNativeZoom: def.minNative,
                        maxNativeZoom: def.maxNative,
                        maxZoom: 19,
                        attribution: def.attr,
                    });
                });
            }
            tileLayers[key].forEach(function (t) { t.addTo(map); });
        } else if (tileLayers[key]) {
            tileLayers[key].forEach(function (t) { map.removeLayer(t); });
        }
    }

    function setOpacity(group, val) {
        opacity[group] = val / 100;
        Object.keys(tileLayers).forEach(function (k) {
            if (TILES[k].group === group) tileLayers[k].forEach(function (t) { t.setOpacity(opacity[group]); });
        });
    }

    // ── 線と点(B-1) ──
    function group(attribution) {
        return L.layerGroup([], { attribution: attribution });
    }

    // 上下の順: 元の送電線 → 重ねた線(実績・計算) → 変電所 → 発電所 → 重ねた点(連系線・エリア)
    var LINE_KEYS = ["obs", "load"], POINT_KEYS = ["ic"];
    function front(keys) {
        keys.forEach(function (k) {
            if (on[k] && vecLayers[k]) vecLayers[k].eachLayer(function (l) { if (l.bringToFront) l.bringToFront(); });
        });
    }
    function raisePoints() {
        front(LINE_KEYS);
        if (global.AGJMap) AGJMap.raise(global.substationLayer, global.plantLayer);
        if (areaGroup) areaGroup.eachLayer(function (l) { if (l.bringToFront) l.bringToFront(); });
        front(POINT_KEYS);
    }
    // grid_map.js が電圧や地域を変えて線を描き直すと、重ねた層が下に回る。少し待ってから順を戻す
    var raiseTimer = null, watching = false;
    function watchRedraw(map) {
        if (watching) return;
        watching = true;
        map.on("layeradd", function () {
            if (!Object.keys(vecLayers).some(function (k) { return on[k]; }) && !areaGroup) return;
            clearTimeout(raiseTimer);
            raiseTimer = setTimeout(raisePoints, 120);
        });
    }

    // 下に暗い縁を敷いて、元の送電線(電圧の色)と見分けやすくする
    function casedLine(latlngs, style, g, map) {
        L.polyline(latlngs, { renderer: AGJMap.renderer(map), color: CASING, weight: style.weight + 3,
                               opacity: 0.85, interactive: false, lineCap: "round" }).addTo(g);
        var ln = L.polyline(latlngs, Object.assign({ renderer: AGJMap.renderer(map), lineCap: "round" }, style));
        ln.addTo(g);
        return ln;
    }

    // 潮流の線の形(docs/data/flow_map/flows_now_*.geojson。毎時の処理が更新する)。実績と計算の両方で使う
    var ISLANDS = ["hokkaido", "east", "west", "okinawa"];
    function loadFlowsNow() {
        return Promise.all(ISLANDS.map(function (isl) {
            return fetchJSON(DATA + "flow_map/flows_now_" + isl + ".geojson").catch(function () { return { features: [] }; });
        })).then(function (parts) {
            var byKey = {};
            parts.forEach(function (fc) {
                (fc.features || []).forEach(function (f) { byKey[f.properties.k] = f; });
            });
            return byKey;
        });
    }
    function toLatLngs(f) {
        return f.geometry.coordinates.map(function (c) { return [c[1], c[0]]; });
    }

    // 連系線: 運用容量(OCCTO)と値差の割合(JEPX)。どちらも公表値とその集計
    function buildIC(map) {
        return fetchJSON(DATA + "overlays/interconnectors.json").then(function (d) {
            var g = group("連系線: OCCTO 系統情報公表・JEPX");
            var m = d._meta || {};
            meta.ic = m.jepx ? (m.jepx.fiscal_year + " 年度（" + m.jepx.from + "〜" + m.jepx.to + "）") : "";
            d.links.forEach(function (L0) {
                var o = L0.occto[0];
                var medFwd = o.fwd.median_mw, medRev = o.rev.median_mw;
                var big = Math.max(o.fwd.max_mw, o.rev.max_mw);
                var r = 5 + 2.2 * Math.sqrt(big / 300);
                var sp = L0.jepx_split;
                var col = sp ? bin(SPLIT_BINS, sp.split_share)[1] : "#8b949e";
                var mk = L.circleMarker([L0.lat, L0.lon], {
                    renderer: AGJMap.renderer(map), radius: r, color: "#f0f6fc", weight: 1.5,
                    fillColor: col, fillOpacity: 0.95,
                }).addTo(g);
                var lab = "→" + esc(L0.fwd[1]) + " " + fmt(medFwd) + "<br>→" + esc(L0.rev[1]) + " " + fmt(medRev);
                var dir = IC_LABEL_DIR[L0.id] || "right", gap = r + 3;
                var off = { right: [gap, 0], left: [-gap, 0], top: [0, -gap], bottom: [0, gap] }[dir];
                mk.bindTooltip(lab, { permanent: true, direction: dir, offset: off, className: "agj-ov-label", interactive: false });
                AGJMap.bindCard(mk, function () { return icCard(L0, m); });
            });
            return g;
        });
    }

    function icCard(L0, m) {
        var rows = [];
        L0.occto.forEach(function (o) {
            rows.push([o.name + "（" + L0.fwd[0] + "→" + L0.fwd[1] + "）",
                       "<b>" + fmt(o.fwd.median_mw) + " MW</b>（最大 " + fmt(o.fwd.max_mw) + "）"]);
            rows.push([o.name + "（" + L0.rev[0] + "→" + L0.rev[1] + "）",
                       "<b>" + fmt(o.rev.median_mw) + " MW</b>（最大 " + fmt(o.rev.max_mw) + "）"]);
        });
        var html = '<p class="agj-card-src">運用容量＝その時に流してよい上限。季節や系統の状態で変わるので、' +
            "ふだんの値として中央値、ほかに期間の最大を出しています（OCCTO の 30 分値、2025 年 4 月から・取得 " + esc(L0.occto[0].retrieved_at) + "）。" +
            (L0.cap_note ? esc(L0.cap_note) + "。" : "") + "<br>" + SRC.occto + "</p>";
        var sp = L0.jepx_split;
        if (sp) {
            var a = sp.areas[0], b = sp.areas[1];
            html += '<p class="agj-card-src" style="margin-top:8px">JEPX のスポット市場で' + esc(a) + "と" + esc(b) +
                "のエリアプライスが違った 30 分は <b>" + fmt(100 * sp.split_share, 1) + "%</b>（" +
                esc(b) + "が高い " + fmt(100 * sp.share_b_higher, 1) + "%・" + esc(a) + "が高い " + fmt(100 * sp.share_a_higher, 1) + "%）。" +
                "値差が出るのは、市場でこの連系線が上限まで使われたとき（安い側から高い側への向き）。" +
                (meta.ic ? esc(meta.ic) + "。" : "") + "<br>" + SRC.jepx + "</p>";
        }
        return {
            kind: "連系線（公表値）", color: sp ? bin(SPLIT_BINS, sp.split_share)[1] : "#8b949e",
            title: L0.name, sub: esc(L0.kind + "・" + L0.fwd[0] + "⇄" + L0.fwd[1]),
            rows: rows.map(function (r) { return [r[0], r[1]]; }), html: html,
            note: esc(L0.site_note) + "。地図の印は目印で、線の経路ではありません。",
        };
    }

    // 送電線の潮流の実績: 各社公表の年統計(obs_compare.json。flow_map と同じもの)をモデルの線に重ねる
    function obsWidth(p95) { return p95 < 50 ? 1.4 : p95 < 200 ? 2.2 : p95 < 500 ? 3.2 : p95 < 1000 ? 4.4 : 6; }
    var CONF_JA = { A: "線名と両端で照合", B: "両端で照合（線名なし）", C: "片端と線名で照合（区間は不確か）" };

    function buildObs(map) {
        return Promise.all([fetchJSON(DATA + "flow_map/obs_compare.json"), loadFlowsNow()]).then(function (res) {
            var obs = res[0], byKey = res[1];
            var g = group("潮流の実績: 各社の系統情報の公表（年統計）");
            var drawn = 0, missing = 0;
            // 細い線を先に、太い線を後に(太い線が上)
            var lines = (obs.lines || []).slice().sort(function (a, b) { return (a.obs.p95 || 0) - (b.obs.p95 || 0); });
            lines.forEach(function (r) {
                var p95 = r.obs && r.obs.p95;
                if (p95 == null) return;
                var segs = [];
                r.keys.forEach(function (kk) {
                    var f = byKey[kk[0]];
                    if (f) segs.push(toLatLngs(f)); else missing++;
                });
                if (!segs.length) return;
                drawn++;
                var style = { color: OBS_COLOR, weight: obsWidth(p95), opacity: r.conf === "C" ? 0.5 : 0.95 };
                segs.forEach(function (ll) {
                    var ln = casedLine(ll, style, g, map);
                    ln.bindTooltip(esc(r.name) + "｜p95 " + fmt(p95) + " MW（公表の実績）", { sticky: true, className: "agj-tip" });
                    AGJMap.bindCard(ln, function () { return obsCard(r); });
                });
            });
            meta.obs = "照合できた " + fmt(drawn) + " 本" + (missing ? "（線の形が見つからない区間 " + missing + "）" : "");
            return g;
        });
    }

    function obsCard(r) {
        var o = r.obs;
        return {
            kind: "送電線の潮流（公表の実績）", color: OBS_COLOR, title: r.name,
            sub: esc((r.kv ? fmt(r.kv) + " kV・" : "") + (UTIL_JA[r.util] || r.util)),
            rows: [["平均", fmt(Math.abs(o.mean)) + " MW"], ["上位 5%（p95）", "<b>" + fmt(o.p95) + " MW</b>"],
                   ["最大", fmt(o.max) + " MW"], ["区間", esc((r.from || "?") + " → " + (r.to || "（片端）"))],
                   ["照合", esc(r.conf + ": " + (CONF_JA[r.conf] || ""))]],
            html: '<p class="agj-card-src">' + SRC.tso + "（2024 年度・ファイル " + esc(r.src || "—") + "）。" +
                  "生の時系列は載せていません。モデルの線への照合は scripts/export_obs_compare.py。</p>",
            note: "公表の値です（AGJ の計算ではありません）。平均は年の平均から正負を外した値。",
        };
    }

    // 混み具合(計算): モデルの潮流 ÷ モデルの容量。公表値ではない
    function buildLoad(map) {
        return Promise.all([loadFlowsNow(), fetchJSON(DATA + "flow_map/now_meta.json").catch(function () { return {}; })]).then(function (res) {
            var byKey = res[0], nm = res[1] || {};
            var g = group("混み具合: AGJ の計算");
            var feats = Object.keys(byKey).map(function (k) { return byKey[k]; }).filter(function (f) {
                return Math.abs(f.properties.loading_pct || 0) >= 50;
            }).sort(function (a, b) { return Math.abs(a.properties.loading_pct) - Math.abs(b.properties.loading_pct); });
            feats.forEach(function (f) {
                var p = f.properties, ld = Math.abs(p.loading_pct);
                var b = bin(LOAD_BINS, ld);
                var style = { color: LOAD_COLOR, weight: b[1], opacity: 0.95, dashArray: "7 6", lineCap: "butt" };
                var ln = casedLine(toLatLngs(f), style, g, map);
                ln.bindTooltip(esc(p.name || "名称なし") + "｜計算の負荷率 " + fmt(ld) + "%", { sticky: true, className: "agj-tip" });
                AGJMap.bindCard(ln, function () {
                    return {
                        kind: "送電線の混み具合（計算）", color: LOAD_COLOR, title: p.name || "名称なし",
                        sub: esc((p.kv ? fmt(p.kv) + " kV" : "")),
                        rows: [["計算の負荷率", "<b>" + fmt(ld) + "%</b>"], ["計算の潮流", fmt(Math.abs(p.p_mw)) + " MW"],
                               ["断面", esc(nm.fetched_at ? "でんき予報 " + nm.fetched_at.replace("T", " ").slice(0, 16) + " 取得" : "—")]],
                        html: '<p class="agj-card-src">' + SRC.agj + "。容量は導体から推定したモデルの値で、各社が公表する運用容量ではありません。" +
                              "実際の系統は 100% を超えないように運用されるので、100% 超はモデルの側のずれ（網の欠けなど）を表します。</p>",
                        note: "AGJ の計算値（推定）です。公表の値ではありません。",
                    };
                });
            });
            meta.load = "負荷率 50% 以上の " + fmt(feats.length) + " 本" +
                (nm.fetched_at ? "・でんき予報 " + nm.fetched_at.replace("T", " ").slice(0, 16) + " 取得の断面" : "");
            return g;
        });
    }

    // エリアの価格(JEPX 年度平均)とエリアの需要(でんき予報)。同じ目印(代表都市)に 1 つの札でまとめて出す。
    // 位置はエリアの目印で、境界ではない
    var areaGroup = null, areaSeq = 0;
    function loadArea() {
        return Promise.all([
            on.price ? fetchJSON(DATA + "overlays/area_prices.json") : Promise.resolve(null),
            on.demand ? fetchJSON(DATA + "realtime/latest.json") : Promise.resolve(null),
            on.demand ? fetchJSON(DATA + "flow_map/now_meta.json").catch(function () { return {}; }) : Promise.resolve(null),
        ]);
    }

    function renderArea() {
        var map = getMap();
        if (!map) return;
        var seq = ++areaSeq;
        if (areaGroup) { map.removeLayer(areaGroup); areaGroup = null; }
        if (!on.price && !on.demand) return;
        watchRedraw(map);
        ["price", "demand"].forEach(function (k) { if (on[k]) setStatus(k, "読み込み中…"); });
        loadArea().then(function (res) {
            if (seq !== areaSeq) return;              // 途中で切り替えられた
            var pd = res[0], dd = res[1], nm = res[2] || {};
            var prices = {}, zh = nm.zone_hour || {};
            if (pd) {
                var m = pd._meta || {};
                meta.price = m.jepx ? m.jepx.fiscal_year + " 年度の平均（システムプライス " + fmt(m.system_price_mean_yen, 2) + " 円）" : "";
                pd.areas.forEach(function (a) { prices[a.area] = a; });
            }
            if (dd) meta.demand = dd.fetched_at ? "取得 " + dd.fetched_at.replace("T", " ").slice(0, 16) : "";
            var g = group([pd ? "エリアの価格: JEPX" : null, dd ? "エリアの需要: 各社のでんき予報" : null].filter(Boolean).join(", "));
            Object.keys(AREA_POINTS).forEach(function (area) {
                var pt = AREA_POINTS[area], zid = pt[2];
                var a = prices[area];
                var z = dd && (dd.zones || {})[zid], h = dd && zh[zid];
                if (!z || !h) { z = null; h = null; }
                if (!a && !h) return;
                var ll = [pt[0], pt[1]], R = AGJMap.renderer(map), top = 9;
                if (h) {
                    top = 6 + Math.sqrt(h.mw) / 9;
                    L.circleMarker(ll, { renderer: R, radius: top, color: "#c9d1d9", weight: 1.6,
                                         fillColor: "#c9d1d9", fillOpacity: 0.08, interactive: false }).addTo(g);
                }
                var col = a ? bin(PRICE_BINS, a.mean_yen)[1] : "#c9d1d9";
                var mk = L.circleMarker(ll, { renderer: R, radius: a ? 8 : 4, color: "#f0f6fc", weight: 1.2,
                                              fillColor: col, fillOpacity: 0.95 }).addTo(g);
                var parts = [];
                if (a) parts.push(fmt(a.mean_yen, 2) + " 円");
                if (h) parts.push(fmt(h.mw) + " MW（" + h.hour + " 時）");
                mk.bindTooltip(esc(area) + " " + parts.join("・"), { permanent: true, direction: "top",
                               offset: [0, -(top + 2)], className: "agj-ov-label", interactive: false });
                AGJMap.bindCard(mk, function () { return areaCard(area, a, z, h, col); });
            });
            areaGroup = g;
            ["price", "demand"].forEach(function (k) { setStatus(k, ""); });
            g.addTo(map);
            raisePoints();
            updateLegend();
        }).catch(function (e) {
            ["price", "demand"].forEach(function (k) { if (on[k]) setStatus(k, "読めませんでした"); });
            console.error("overlay area:", e);
        });
    }

    function areaCard(area, a, z, h, col) {
        var rows = [], html = "";
        if (a) {
            rows.push(["エリアプライスの平均", "<b>" + fmt(a.mean_yen, 2) + " 円/kWh</b>"]);
            rows.push(["同 中央値", fmt(a.median_yen, 2) + " 円/kWh"]);
            html += '<p class="agj-card-src">価格は ' + esc(meta.price) + "。30 分ごとの値の単純平均。<br>" + SRC.jepx + "</p>";
        }
        if (h) {
            rows.push(["需要の実績", "<b>" + fmt(h.mw) + " MW</b>（" + esc(String(h.date)) + " " + h.hour + " 時）"]);
            html += '<p class="agj-card-src" style="margin-top:8px">' + SRC.yoho +
                '（<a href="' + esc(z.source) + '" target="_blank" rel="noopener">この社の CSV</a>、更新 ' + esc(z.updated || "—") + "）。" +
                "万 kW を 10 倍して MW にしたもの。毎時の処理が取り込みます。</p>";
        }
        return { kind: "エリア（公表値）", color: col, title: area + "エリア", rows: rows, html: html,
                 note: "地図の円はエリアの目印（代表都市）の位置で、境界ではありません。" +
                       (h ? "外側の輪の大きさは需要の大きさ。" : "") };
    }

    var BUILDERS = { ic: buildIC, obs: buildObs, load: buildLoad };
    var building = {};

    function setVec(key, show) {
        var map = getMap();
        if (!map) return;
        if (!show) {
            if (vecLayers[key]) map.removeLayer(vecLayers[key]);
            return;
        }
        watchRedraw(map);
        if (vecLayers[key]) { vecLayers[key].addTo(map); raisePoints(); return; }
        if (building[key]) return;
        building[key] = true;
        setStatus(key, "読み込み中…");
        BUILDERS[key](map).then(function (g) {
            building[key] = false;
            vecLayers[key] = g;
            setStatus(key, "");
            if (on[key]) { g.addTo(map); raisePoints(); }
            updateLegend();
        }).catch(function (e) {
            building[key] = false;
            setStatus(key, "読めませんでした");
            console.error("overlay " + key + ":", e);
        });
    }

    function setStatus(key, text) {
        var el = document.querySelector('[data-ov-status="' + key + '"]');
        if (el) el.textContent = text;
    }

    function toggle(key, show) {
        on[key] = !!show;
        if (TILES[key]) setTile(key, show);
        else if (key === "price" || key === "demand") renderArea();
        else setVec(key, show);
        updateLegend();
    }

    // ── 凡例(地図の左下)。点けている層だけ、見本と出典を出す ──
    var VEC_LEGEND = {
        ic: function () {
            return section("連系線の運用容量と値差", "公表",
                '<div class="ov-row">数字＝運用容量の中央値（MW、→ は向き）。円の大きさ＝期間の最大</div>' +
                '<div class="ov-row">円の色＝JEPX で両側の価格が違った 30 分の割合</div>' +
                '<div class="ov-row ov-wrap">' + SPLIT_BINS.map(function (b) { return '<span><i class="ov-dot" style="background:' + b[1] + '"></i>' + b[2] + "</span>"; }).join("") + "</div>",
                SRC.occto + "<br>" + SRC.jepx + (meta.ic ? "（" + esc(meta.ic) + "）" : ""),
                "印は目印で経路ではない。");
        },
        obs: function () {
            return section("送電線の潮流の実績", "公表",
                '<div class="ov-row">白い線。太さ＝年間の上位 5% の潮流（p95）</div>' +
                '<div class="ov-row ov-wrap">' + [[50, "〜50"], [200, "〜200"], [500, "〜500"], [1000, "〜1,000"], [2000, "1,000 MW〜"]].map(function (s) {
                    return '<span><i class="ov-line" style="height:' + obsWidth(s[0] - 1) + 'px;background:' + OBS_COLOR + '"></i>' + s[1] + "</span>";
                }).join("") + "</div>" +
                '<div class="ov-row"><i class="ov-line" style="height:3px;background:' + OBS_COLOR + ';opacity:.5"></i>薄い線＝区間が不確か</div>',
                SRC.tso + "（2024 年度）",
                esc(meta.obs || ""));
        },
        load: function () {
            return section("送電線の混み具合", "計算",
                LOAD_BINS.map(function (b) { return '<div class="ov-row"><i class="ov-dash" style="border-color:' + LOAD_COLOR + ";border-top-width:" + b[1] + 'px"></i>計算の負荷率 ' + b[2] + "</div>"; }).join(""),
                SRC.agj + "。" + esc(meta.load || ""),
                "公表値ではない。容量はモデルの推定。100% 超はモデルのずれ。");
        },
        price: function () {
            return section("エリアの価格", "公表値の集計",
                '<div class="ov-row">エリアプライスの年度平均（円/kWh）</div>' +
                '<div class="ov-row ov-wrap ov-2col">' + PRICE_BINS.map(function (b) { return '<span><i class="ov-dot" style="background:' + b[1] + '"></i>' + b[2] + "</span>"; }).join("") + "</div>",
                SRC.jepx + (meta.price ? "（" + esc(meta.price) + "）" : ""),
                "円の位置はエリアの目印（代表都市）。沖縄は JEPX のエリアに無い。");
        },
        demand: function () {
            return section("エリアの需要", "公表",
                '<div class="ov-row"><i class="ov-ring"></i>円が大きいほど需要が大きい（MW、いまの時刻）</div>',
                SRC.yoho + (meta.demand ? "（" + esc(meta.demand) + "）" : ""),
                "関西は取り込み元が未設定で出ない。四国は前日までの値。");
        },
    };

    function section(title, tag, body, src, note) {
        var cls = tag === "計算" ? "ov-tag ov-tag-calc" : "ov-tag";
        return '<div class="ov-sec"><div class="ov-h">' + esc(title) + ' <span class="' + cls + '">' + esc(tag) + "</span></div>" +
            body + '<div class="ov-src">' + src + "</div>" + (note ? '<div class="ov-src">' + note + "</div>" : "") + "</div>";
    }

    // 色の見本を 2 列に並べる
    function swatches(list) {
        if (!list || !list.length) return "";
        return '<div class="ov-row ov-wrap ov-2col">' + list.map(function (s) {
            return '<span><i class="ov-sq" style="background:' + s[0] + '"></i>' + esc(s[1]) + "</span>";
        }).join("") + "</div>";
    }

    function tileLegend(key) {
        var def = TILES[key];
        var body = swatches(def.swatches);
        if (def.legendImg) body += '<div class="ov-row"><a href="' + def.legendImg + '" target="_blank" rel="noopener">凡例（地理院の画像）を開く</a></div>';
        return section(def.title, "公表", body, def.src, esc(def.note || ""));
    }

    function updateLegend() {
        var map = getMap();
        if (!map) return;
        var keys = Object.keys(on).filter(function (k) { return on[k]; });
        if (!keys.length) {
            if (legendCtl) { map.removeControl(legendCtl); legendCtl = null; }
            return;
        }
        if (!legendCtl) {
            legendCtl = L.control({ position: "bottomleft" });
            legendCtl.onAdd = function () {
                var div = L.DomUtil.create("div", "agj-ov-legend");
                L.DomEvent.disableClickPropagation(div);
                L.DomEvent.disableScrollPropagation(div);
                div.addEventListener("click", function (e) {
                    if (!e.target.closest(".ov-fold")) return;
                    legendFolded = !legendFolded;
                    div.classList.toggle("folded", legendFolded);
                    e.target.closest(".ov-fold").setAttribute("aria-expanded", String(!legendFolded));
                    e.target.closest(".ov-fold").textContent = legendFolded ? "開く" : "たたむ";
                });
                return div;
            };
            legendCtl.addTo(map);
        }
        var order = ["ic", "obs", "load", "price", "demand", "tsunami", "flood", "hightide", "sediment", "relief", "landuse"];
        var shown = {};
        var html = '<div class="ov-title">重ねた層の凡例と出典<button type="button" class="ov-fold" aria-expanded="' + !legendFolded + '">' +
            (legendFolded ? "開く" : "たたむ") + "</button></div>";
        order.forEach(function (k) {
            if (!on[k]) return;
            if (TILES[k]) {
                // 浸水の 3 つは凡例が同じなので 1 つにまとめる
                if (TILES[k].swatches === SHINSUI) {
                    if (shown.shinsui) return;
                    shown.shinsui = true;
                    var names = ["tsunami", "flood", "hightide"].filter(function (x) { return on[x]; }).map(function (x) { return TILES[x].title; });
                    html += section(names.join("・"), "公表", swatches(SHINSUI), SRC.haz, "浸水する深さ。" + HAZ_NOTE);
                    return;
                }
                html += tileLegend(k);
            } else if (VEC_LEGEND[k]) {
                html += VEC_LEGEND[k]();
            }
        });
        var box = legendCtl.getContainer();
        box.innerHTML = html;
        box.classList.toggle("folded", legendFolded);
    }
    // 狭い画面では地図を隠さないよう、たたんだ状態で始める
    var legendFolded = !!(global.matchMedia && global.matchMedia("(max-width: 768px)").matches);

    // ── 見た目(罫線だけ・角は立てる。map_ui.css は触らない) ──
    function injectCss() {
        if (document.getElementById("agj-ov-css")) return;
        var css =
            ".agj-ov-legend{background:rgba(13,17,23,.94);color:#e6edf3;border:1px solid #30363d;border-radius:0;padding:7px 9px;" +
            "font-size:10.5px;line-height:1.45;width:268px;max-height:40vh;overflow-y:auto}" +
            ".agj-ov-legend.folded{max-height:none;overflow:visible}" +
            ".agj-ov-legend.folded .ov-sec{display:none}" +
            ".agj-ov-legend .ov-title{display:flex;align-items:center;gap:8px;font-weight:700;color:#8b949e;font-size:10.5px;letter-spacing:.04em}" +
            ".agj-ov-legend .ov-fold{margin-left:auto;background:none;border:1px solid #30363d;border-radius:0;color:#c9d1d9;" +
            "font:600 10.5px/1.4 inherit;font-family:inherit;padding:1px 6px;cursor:pointer}" +
            ".agj-ov-legend .ov-fold:hover{border-color:#6e7681}" +
            ".agj-ov-legend .ov-sec{border-top:1px solid #30363d;padding-top:6px;margin-top:6px}" +
            ".agj-ov-legend .ov-h{font-weight:700;margin-bottom:3px}" +
            ".agj-ov-legend .ov-tag{font-weight:600;font-size:10px;color:#c9d1d9;border:1px solid #6e7681;padding:0 4px;margin-left:4px}" +
            ".agj-ov-legend .ov-tag-calc{color:#f0883e;border-color:#f0883e;border-style:dashed}" +
            ".agj-ov-legend .ov-row{display:flex;align-items:center;gap:7px;margin:1px 0}" +
            ".agj-ov-legend .ov-wrap{flex-wrap:wrap;gap:3px 10px}" +
            ".agj-ov-legend .ov-wrap span{display:inline-flex;align-items:center;gap:5px}" +
            ".agj-ov-legend .ov-2col span{width:calc(50% - 5px)}" +
            ".agj-ov-legend .ov-sq{width:14px;height:10px;border:1px solid rgba(255,255,255,.25);flex:none}" +
            ".agj-ov-legend .ov-dot{width:10px;height:10px;border-radius:50%;border:1px solid #f0f6fc;flex:none}" +
            ".agj-ov-legend .ov-ring{width:12px;height:12px;border-radius:50%;border:1.6px solid #c9d1d9;flex:none}" +
            ".agj-ov-legend .ov-line{width:20px;flex:none;box-shadow:0 0 0 1.5px #0d1117}" +
            ".agj-ov-legend .ov-dash{width:20px;height:0;border-top:3px dashed;flex:none}" +
            ".agj-ov-legend .ov-src{color:#8b949e;font-size:10.5px;margin-top:3px}" +
            ".agj-ov-legend a{color:#4493f8}" +
            ".leaflet-tooltip.agj-ov-label{background:rgba(13,17,23,.88);color:#e6edf3;border:1px solid #30363d;border-radius:0;" +
            "box-shadow:none;font-size:10.5px;line-height:1.35;padding:2px 5px;font-variant-numeric:tabular-nums;white-space:nowrap}" +
            ".ov-links{margin:6px 0 0;padding:0;list-style:none;font-size:11px;line-height:1.7;color:#8b949e}" +
            ".ov-links a{color:#4493f8}" +
            "[data-ov-status]{font-size:10.5px;color:#8b949e;margin-left:6px}" +
            "@media (max-width:768px){.agj-ov-legend{max-width:62vw;max-height:34vh}}";
        var st = document.createElement("style");
        st.id = "agj-ov-css";
        st.textContent = css;
        document.head.appendChild(st);
    }

    // ── 左バーのチェック・スライダーをつなぐ ──
    function bindUi() {
        document.querySelectorAll("input[data-ov]").forEach(function (cb) {
            cb.addEventListener("change", function () { toggle(cb.dataset.ov, cb.checked); });
            if (cb.checked) toggle(cb.dataset.ov, true);
        });
        document.querySelectorAll("input[data-ov-opacity]").forEach(function (sl) {
            sl.addEventListener("input", function () { setOpacity(sl.dataset.ovOpacity, +sl.value); });
            opacity[sl.dataset.ovOpacity] = +sl.value / 100;
        });
    }

    function init() {
        injectCss();
        // 地図は grid_map.js が DOMContentLoaded で作る。できるまで待つ(長くても数秒)
        var tries = 0;
        (function wait() {
            if (getMap() && global.AGJMap) { bindUi(); return; }
            if (++tries > 200) { console.error("overlay_layers: 地図が見つからない"); return; }
            setTimeout(wait, 50);
        })();
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();

    global.AGJOverlays = { toggle: toggle, setOpacity: setOpacity, _on: on };
})(window);
