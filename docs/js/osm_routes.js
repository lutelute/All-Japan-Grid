/* 系統図マップの「路線」「鉄塔」(2026-11-07)。
 *
 * OSM の送電線は細切れの way で描かれている。scripts/export_osm_routes.py が way を路線にまとめて
 * docs/data/osm_routes/ に書き、ここで次のことをする。
 *   - 正典の線(地図の線)をクリックしたら、その枝が通る OSM の路線を引いて全体を光らせる(A1)
 *   - 路線を選ぶと、その線の鉄塔を出して選べる(A2)。寄ったときは見えている範囲の鉄塔も出す
 *   - 選んだ路線の名前と電圧を線の上に出す(A4)。地中・海底・ケーブルは破線で描き分ける(A7)
 *   - 路線・鉄塔の詳細(OSM のタグ・Wikidata・OpenStreetMap へのリンク)をカードに出す(A6)
 *   - 変電所のカードに、同じ敷地の電圧ごとの母線を並べる(A5)
 *   - 横断検索(grid_search.js)に一覧を渡す(A3)
 *
 * OSM の線と鉄塔は観測から作った derived の層で、正典(docs/data/built)とは別。既定は出さず、
 * 路線を選んだときだけその線と鉄塔を出す(2026-11-07 オーナー判断)。左の「OSM の線と鉄塔」で全部出せる。
 * 選んだ状態は ?route=地域番号.路線番号 / ?tower=地域番号.node id で共有できる(# はタブが使う)。
 *
 * grid_map.js のグローバル(map, lineLayer, substationLayer, voltageColor, fmtKv)を使う。
 */
(function (global) {
    "use strict";

    var BASE = "./data/osm_routes/";
    var C = { ID: 0, NAME: 1, UNNAMED: 2, KV: 3, LEN: 4, BBOX: 5, TW: 6, TWREF: 7, JOIN: 8, ENDS: 9, TAGS: 10, W: 11 };
    var STYLE_DASH = { u: "6 4", c: "6 4", s: "2 5" };
    var STYLE_JA = { "": "架空", air: "架空", u: "地中", c: "ケーブル", s: "海底" };
    var END_JA = { sub: "変電所", plant: "発電所", line: "ほかの線へ続く", portal: "引留め鉄構", terminal: "終端",
                   transition: "架空と地中の切替", none: "何もない所で終わる" };
    var TOWER_TAG_JA = { design: "形", structure: "構造", height: "高さ", material: "材料", line_attachment: "線の付け方",
                         line_management: "線の分かれ方", colour: "色", start_date: "建った年", "name:en": "英語の名前", note: "メモ" };
    // OSM の鉄塔の形(design)・構造(structure)の値を日本語に。知らない値はそのまま出す
    var DESIGN_JA = { "one-level": "1 段", "two-level": "2 段", "three-level": "3 段", "four-level": "4 段", "five-level": "5 段",
                      "six-level": "6 段", "nine-level": "9 段", "twelve-level": "12 段", barrel: "たる形", donau: "ドナウ形",
                      flag: "片側に腕（旗形）", asymmetric: "左右が非対称", delta: "三角形", "h-frame": "H 形（門形の柱）",
                      monopole: "1 本柱", monopolar: "1 本柱", portal: "門形" };
    var STRUCTURE_JA = { lattice: "鉄骨を組んだ塔", tubular: "鋼管の柱", solid: "中の詰まった柱" };
    function tagValueJa(k, v) {
        var dict = k === "design" ? DESIGN_JA : k === "structure" ? STRUCTURE_JA : null;
        if (!dict) return v;
        var parts = String(v).replace(/_level/g, "-level").split("_").map(function (x) { return dict[x] || x; });
        return parts.join("・") + (parts.join("") !== String(v) ? "（" + v + "）" : "");
    }
    var MIN_ZOOM_OSM = 9, MIN_ZOOM_TOWERS = 13, MIN_ZOOM_ROUTE_TOWERS = 10, MAX_TOWERS_DRAWN = 5000;

    var P = {};
    var meta = null;
    var routes = {};   // 地域 → { list, byId }
    var towers = {};   // 地域 → 解いた鉄塔
    var st = {
        sel: null,          // { rid, reg, rec }
        selGroup: null,     // 選んだ路線の線・ラベル
        towerSelGroup: null,// 選んだ路線の鉄塔
        osmOn: false,
        osmGroups: {},      // "地域|最低kV" → layerGroup
        viewTowers: null,   // 見えている範囲の鉄塔
        canonHi: [],        // 光らせた正典の線 [layer, 元のstyle]
        opening: false,     // 自分でカードを開くあいだは選択を消さない
        selTower: null,
    };

    function esc(s) { return AGJMap.esc(s); }
    function nfmt(x) { return Number(x).toLocaleString("ja-JP"); }

    function getJSON(name) {
        if (!P[name]) {
            P[name] = fetch(BASE + name).then(function (r) {
                if (!r.ok) throw new Error(name + " " + r.status);
                return r.json();
            }).catch(function (e) { delete P[name]; throw e; });
        }
        return P[name];
    }

    function loadMeta() {
        return getJSON("meta.json").then(function (m) { meta = m; return m; });
    }

    // ── Google polyline(小数 5 桁)を解く ──
    function decode(s) {
        var out = [], i = 0, lat = 0, lon = 0;
        while (i < s.length) {
            var v = [0, 0];
            for (var k = 0; k < 2; k++) {
                var shift = 0, res = 0, b;
                do { b = s.charCodeAt(i++) - 63; res |= (b & 31) << shift; shift += 5; } while (b >= 32);
                v[k] = (res & 1) ? ~(res >> 1) : (res >> 1);
            }
            lat += v[0]; lon += v[1];
            out.push([lat / 1e5, lon / 1e5]);
        }
        return out;
    }
    function wayLL(w) { if (!w._ll) w._ll = decode(w[3]); return w._ll; }

    function loadRoutes(reg) {
        if (routes[reg]) return Promise.resolve(routes[reg]);
        return getJSON("routes_" + reg + ".json").then(function (d) {
            if (routes[reg]) return routes[reg];
            var byId = {};
            d.routes.forEach(function (r) { byId[r[C.ID]] = r; });
            routes[reg] = { list: d.routes, byId: byId, reg: reg };
            return routes[reg];
        });
    }

    // 鉄塔は列ごと・差で書いてある(export_osm_routes.py)。足し戻して配列にする
    function loadTowers(reg) {
        if (towers[reg]) return Promise.resolve(towers[reg]);
        return getJSON("towers_" + reg + ".json").then(function (d) {
            if (towers[reg]) return towers[reg];
            var n = d.n, id = new Float64Array(n), la = new Int32Array(n), lo = new Int32Array(n);
            var a = 0, b = 0, c = 0, byCoord = new Map(), byRoute = new Map(), byId = new Map();
            for (var i = 0; i < n; i++) {
                a += d.id[i]; b += d.lat[i]; c += d.lon[i];
                id[i] = a; la[i] = b; lo[i] = c;
                byCoord.set(b + "," + c, i);
                byId.set(a, i);
                var r = d.r[i];
                var rs = r === -1 ? [] : (typeof r === "number" ? [d.rl[r]] : r.map(function (x) { return d.rl[x]; }));
                for (var k = 0; k < rs.length; k++) {
                    var l = byRoute.get(rs[k]);
                    if (!l) byRoute.set(rs[k], l = []);
                    l.push(i);
                }
            }
            var T = { reg: reg, n: n, id: id, la: la, lo: lo, rl: d.rl, r: d.r, ref: d.ref, name: d.name, tags: d.tags,
                      byCoord: byCoord, byRoute: byRoute, byId: byId };
            towers[reg] = T;
            return T;
        });
    }

    function towerRoutes(T, i) {
        var r = T.r[i];
        return r === -1 ? [] : (typeof r === "number" ? [T.rl[r]] : r.map(function (x) { return T.rl[x]; }));
    }
    function tower(T, i) {
        return { reg: T.reg, i: i, id: T.id[i], lat: T.la[i] / 1e5, lon: T.lo[i] / 1e5,
                 ref: T.ref[i] || null, name: T.name[i] || null, tags: T.tags[i] || null, rids: towerRoutes(T, i) };
    }

    function regIndex(reg) { return meta ? meta.regions.indexOf(reg) : -1; }
    function bboxHit(a, b) { return a && b && a[0] <= b[2] && a[2] >= b[0] && a[1] <= b[3] && a[3] >= b[1]; }
    function viewBox() {
        var b = map.getBounds();
        return [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
    }
    function regionsFor(box) {
        return meta.regions.filter(function (r) { return bboxHit(meta.region_bbox[r], box); });
    }

    // 1 本の路線を、地域を決め打ちせずに引く(地域の境では隣のファイルにあることがある)
    function findRoute(rid, regHint) {
        return loadMeta().then(function () {
            var order = [regHint].concat(meta.regions.filter(function (r) { return r !== regHint; }));
            function next(k) {
                if (k >= order.length) return null;
                if (!order[k]) return next(k + 1);
                return loadRoutes(order[k]).then(function (R) {
                    return R.byId[rid] ? { rec: R.byId[rid], reg: order[k] } : next(k + 1);
                });
            }
            return next(0);
        });
    }

    function kvMax(rec) { var k = rec[C.KV]; return k.length ? Math.max.apply(null, k) : 0; }
    function kvText(rec) { var k = rec[C.KV]; return k.length ? k.slice().sort(function (a, b) { return b - a; }).join(" / ") + " kV" : "電圧不明"; }
    function color(kv) { return typeof voltageColor === "function" ? voltageColor(kv) : "#e6edf3"; }
    function title(rec) { return rec[C.NAME] || "名前なし（OSM way " + rec[C.ID] + "）"; }
    function mid(rec) {
        var best = null, n = 0;
        rec[C.W].forEach(function (w) { var ll = wayLL(w); if (ll.length > n) { n = ll.length; best = ll; } });
        return best ? best[Math.floor(best.length / 2)] : null;
    }

    // ── 正典の線(地図の線)を引く鍵。scripts/export_osm_routes.py の R.edge_key と同じ書き方 ──
    function edgeKey(coords) {
        var a = coords[0], b = coords[coords.length - 1];
        function q(x) { return String(Math.round(x * 1e4)); }
        return [q(a[0]), q(a[1]), q(b[0]), q(b[1]), String(coords.length)].join(",");
    }
    function edgeRoutes(feature) {
        return getJSON("edge_routes.json").then(function (d) {
            var v = d.map[edgeKey(feature.geometry.coordinates)] || [];
            var out = [];
            for (var i = 0; i < v.length; i += 2) out.push({ rid: v[i], reg: meta.regions[v[i + 1]] });
            return out;
        });
    }

    // ── 選択 ──
    function ensureGroups() {
        if (!st.selGroup) st.selGroup = L.layerGroup().addTo(map);
        if (!st.towerSelGroup) st.towerSelGroup = L.layerGroup().addTo(map);
    }

    function clearSelection() {
        if (st.selGroup) st.selGroup.clearLayers();
        if (st.towerSelGroup) st.towerSelGroup.clearLayers();
        st.canonHi.forEach(function (x) { try { x[0].setStyle(x[1]); } catch (e) { /* 消えた層 */ } });
        st.canonHi = [];
        st.sel = null;
        st.selTower = null;
        setURL(null);
    }

    function lineStyle(kv, sty, sel) {
        return { color: color(kv), weight: sel ? 5 : 1.8, opacity: sel ? 1 : 0.85,
                 dashArray: STYLE_DASH[sty] || null, renderer: AGJMap.renderer(map), interactive: true };
    }

    function drawSelected(rec, reg) {
        ensureGroups();
        st.selGroup.clearLayers();
        var kv = kvMax(rec);
        rec[C.W].forEach(function (w) {
            var ll = wayLL(w);
            if (ll.length < 2) return;
            L.polyline(ll, { color: "#ffffff", weight: 11, opacity: 0.28, renderer: AGJMap.renderer(map), interactive: false }).addTo(st.selGroup);
            var pl = L.polyline(ll, lineStyle(w[1] || kv, w[2], true)).addTo(st.selGroup);
            pl.bindTooltip(esc(title(rec)) + " ・ " + esc(kvText(rec)), { sticky: true, className: "agj-tip" });
            pl.on("click", function (e) { L.DomEvent.stopPropagation(e); openRouteCard(rec, reg); });
        });
        var m = mid(rec);
        if (m) {
            L.tooltip({ permanent: true, direction: "center", className: "osm-route-label", interactive: false })
                .setLatLng(m).setContent(esc(title(rec)) + " " + esc(kvText(rec))).addTo(st.selGroup);
        }
    }

    function highlightCanon(rid) {
        if (typeof lineLayer === "undefined" || !lineLayer) return Promise.resolve(0);
        return getJSON("edge_routes.json").then(function (d) {
            if (!st.sel || st.sel.rid !== rid) return 0;
            var n = 0, sel = map._agjSel && map._agjSel.layer;
            lineLayer.eachLayer(function (layer) {
                var v = d.map[edgeKey(layer.feature.geometry.coordinates)];
                if (!v) return;
                for (var i = 0; i < v.length; i += 2) {
                    if (v[i] === rid) {
                        n++;
                        if (layer !== sel) {
                            var o = layer.options;
                            st.canonHi.push([layer, { weight: o.weight, opacity: o.opacity, color: o.color }]);
                            layer.setStyle({ weight: (o.weight || 2) + 3, opacity: 1 });
                        }
                        break;
                    }
                }
            });
            return n;
        });
    }

    function drawRouteTowers(rid, rec) {
        ensureGroups();
        st.towerSelGroup.clearLayers();
        if (map.getZoom() < MIN_ZOOM_ROUTE_TOWERS) return Promise.resolve(0);
        var regs = regionsFor(rec[C.BBOX]);
        return Promise.all(regs.map(loadTowers)).then(function (Ts) {
            if (!st.sel || st.sel.rid !== rid) return 0;
            var n = 0;
            Ts.forEach(function (T) {
                (T.byRoute.get(rid) || []).forEach(function (i) { towerMarker(T, i, true).addTo(st.towerSelGroup); n++; });
            });
            return n;
        });
    }

    function selectRoute(rid, regHint, opts) {
        opts = opts || {};
        return findRoute(rid, regHint).then(function (hit) {
            if (!hit) return null;
            if (!opts.keepCanon) clearSelection();
            st.sel = { rid: rid, reg: hit.reg, rec: hit.rec };
            drawSelected(hit.rec, hit.reg);
            highlightCanon(rid);
            drawRouteTowers(rid, hit.rec);
            if (opts.fit && hit.rec[C.BBOX]) {
                var b = hit.rec[C.BBOX];
                map.flyToBounds([[b[1], b[0]], [b[3], b[2]]], { padding: [70, 70], maxZoom: 14, duration: 0.8 });
            }
            if (opts.card) openRouteCard(hit.rec, hit.reg);
            setURL("route", regIndex(hit.reg) + "." + rid);
            return hit;
        });
    }

    function withOwnCard(fn) {
        st.opening = true;
        try { fn(); } finally { st.opening = false; }
    }

    // ── 路線のカード ──
    function endsText(rec) {
        var ends = rec[C.ENDS];
        if (!ends.length) return "端なし（輪になっている）";
        var parts = ends.slice(0, 6).map(function (e) {
            var k = END_JA[e[0]] || e[0];
            return e[1] ? esc(e[1]) : (e[0] === "none" ? '<span class="osm-warn">' + k + "</span>" : esc(k));
        });
        return parts.join(" ／ ") + (ends.length > 6 ? " ほか " + (ends.length - 6) : "");
    }

    function styleText(rec) {
        var c = {};
        rec[C.W].forEach(function (w) { var k = STYLE_JA[w[2]] || "架空"; c[k] = (c[k] || 0) + 1; });
        return Object.keys(c).map(function (k) { return k + " " + c[k]; }).join("・");
    }

    function tagRows(tags) {
        if (!tags) return "";
        var ja = { ref: "番号(ref)", circuits: "回線数", cables: "電線の数", wires: "導体", frequency: "周波数", operator: "事業者",
                   "operator:wikidata": "事業者の Wikidata", wikidata: "Wikidata", wikipedia: "Wikipedia", location: "場所",
                   line: "線の種類", start_date: "使い始め", "name:en": "英語の名前" };
        return '<table class="osm-tags">' + Object.keys(tags).map(function (k) {
            return "<tr><td>" + esc(ja[k] || k) + "</td><td>" + tags[k].map(esc).join("; ") + "</td></tr>";
        }).join("") + "</table>";
    }

    function wikiLinks(tags) {
        if (!tags) return [];
        var out = [];
        (tags.wikidata || []).slice(0, 2).forEach(function (q) {
            if (/^Q\d+$/.test(q)) out.push('<a href="https://www.wikidata.org/wiki/' + q + '" target="_blank" rel="noopener">Wikidata ' + q + "</a>");
        });
        (tags.wikipedia || []).slice(0, 2).forEach(function (w) {
            var m = /^([a-z\-]+):(.+)$/.exec(w);
            if (m) out.push('<a href="https://' + m[1] + ".wikipedia.org/wiki/" + encodeURIComponent(m[2]) + '" target="_blank" rel="noopener">Wikipedia（' + esc(m[1]) + "）</a>");
        });
        (tags["operator:wikidata"] || []).slice(0, 1).forEach(function (q) {
            if (/^Q\d+$/.test(q)) out.push('<a href="https://www.wikidata.org/wiki/' + q + '" target="_blank" rel="noopener">事業者の Wikidata</a>');
        });
        return out;
    }

    function routeCard(rec, reg) {
        var tags = rec[C.TAGS] || null, j = rec[C.JOIN];
        var rows = [
            ["電圧", esc(kvText(rec))],
            ["区間", rec[C.W].length + " 本（" + esc(styleText(rec)) + "）・ " + rec[C.LEN].toFixed(1) + " km"],
            ["両端", endsText(rec)],
            ["鉄塔", nfmt(rec[C.TW]) + " 基" + (rec[C.TW] ? "（番号のあるもの " + nfmt(rec[C.TWREF]) + "）" : "")],
        ];
        if (tags && tags.circuits) rows.splice(1, 0, ["回線数", esc(tags.circuits.join(" / "))]);
        if (tags && tags.operator) rows.push(["事業者", esc(tags.operator.join(" / "))]);
        if (rec[C.NAME] && rec[C.UNNAMED]) rows.push(["名前", "名前の無い区間 " + rec[C.UNNAMED] + " 本は、隣の区間の名前を当てています（推定）"]);
        rows.push(["つなぎ方", "同じ名前 " + j[0] + "・名前なしの続き " + j[1] + "・片方だけ名前 " + j[2]]);
        var links = wikiLinks(tags);
        if (links.length) rows.push(["リンク", links.join("<br>")]);
        rows.push(["正典の枝", '<span class="osm-slot-canon">数えています…</span>']);
        if (rec[C.NAME]) rows.push(["同じ名前", '<span class="osm-slot-same">調べています…</span>']);
        var b = rec[C.BBOX];
        var ways = rec[C.W].slice(0, 40).map(function (w) {
            return '<a href="https://www.openstreetmap.org/way/' + w[0] + '" target="_blank" rel="noopener">' + w[0] + "</a>";
        }).join(" ") + (rec[C.W].length > 40 ? " ほか " + (rec[C.W].length - 40) : "");
        return {
            kind: "送電線（OSM の路線）", color: color(kvMax(rec)),
            title: title(rec),
            sub: esc(kvText(rec)) + " ・ " + esc(regionJa(reg)),
            rows: rows,
            moreTitle: "OSM のタグと way の一覧",
            more: tagRows(tags) + '<p class="osm-ways">way: ' + ways + "</p>",
            actions: [
                b ? { text: "路線の全体を見る", onClick: function () { map.flyToBounds([[b[1], b[0]], [b[3], b[2]]], { padding: [70, 70], maxZoom: 14 }); } } : null,
                { text: "OpenStreetMap で見る", href: "https://www.openstreetmap.org/way/" + rec[C.ID], blank: true },
            ].filter(Boolean),
            note: "OSM の way を、同じ名前か端点の続きでまとめた路線です（観測から作った derived・正典の枝とは別）。" +
                  "1 列の鉄塔に別の線が載っていても（併架）つなぎません。地図データ © OpenStreetMap contributors（ODbL）。",
        };
    }

    function regionJa(reg) {
        return (typeof REGION_NAMES_JA !== "undefined" && REGION_NAMES_JA[reg]) || reg || "";
    }

    function openRouteCard(rec, reg) {
        withOwnCard(function () { AGJMap.showCard(map, routeCard(rec, reg), null); });
        fillRouteSlots(rec, reg);
    }

    function cardEl() { return map._agjCard; }

    function fillRouteSlots(rec, reg) {
        var rid = rec[C.ID];
        highlightCount(rid).then(function (n) {
            var el = cardEl() && cardEl().querySelector(".osm-slot-canon");
            if (el) el.textContent = n ? n + " 本（地図で太く表示）" : "対応する枝なし（いま出している電圧の範囲で）";
        });
        if (!rec[C.NAME]) return;
        loadSearch().then(function (S) {
            var el = cardEl() && cardEl().querySelector(".osm-slot-same");
            if (!el) return;
            var mine = nameParts(rec[C.NAME]), kv = kvMax(rec);
            var others = S.routes.filter(function (r) {
                return r[0] !== rid && Math.abs((r[3] || 0) - kv) < 0.6 && r[6].some(function (p) { return mine.indexOf(p) >= 0; });
            });
            if (!others.length) { el.textContent = "ほかに同じ名前の区間はありません"; return; }
            el.innerHTML = "つながっていない別の区間が " + others.length + " か所 " +
                '<button type="button" class="osm-inline-btn">まとめて光らせる</button>';
            el.querySelector("button").addEventListener("click", function () { showNameGroup(rec, reg, others); });
        });
    }

    function highlightCount(rid) {
        if (typeof lineLayer === "undefined" || !lineLayer) return Promise.resolve(0);
        return getJSON("edge_routes.json").then(function (d) {
            var n = 0;
            lineLayer.eachLayer(function (layer) {
                var v = d.map[edgeKey(layer.feature.geometry.coordinates)];
                if (!v) return;
                for (var i = 0; i < v.length; i += 2) if (v[i] === rid) { n++; break; }
            });
            return n;
        });
    }

    function nameParts(name) {
        // src/topology/osm_routes.py の name_set と同じ比べ方(; / で分け、空白と末尾のローマ字の読みを除く)
        return String(name || "").split(/[;\/]/).map(function (p) {
            return p.trim().replace(/\s*[(（][\x20-\x7eÀ-ɏḀ-ỿ]+[)）]\s*$/, "").replace(/\s+/g, "");
        }).filter(Boolean);
    }

    // 同じ名前でつながっていない区間も一緒に光らせる(つながっていないことは線を細く・破線にして見せる)
    function showNameGroup(rec, reg, others) {
        var box = rec[C.BBOX].slice();
        Promise.all(others.map(function (o) { return findRoute(o[0], meta.regions[o[1]]); })).then(function (hits) {
            hits.forEach(function (h) {
                if (!h) return;
                var r = h.rec, kv = kvMax(r), b = r[C.BBOX];
                r[C.W].forEach(function (w) {
                    var ll = wayLL(w);
                    if (ll.length < 2) return;
                    L.polyline(ll, { color: "#ffffff", weight: 9, opacity: 0.18, renderer: AGJMap.renderer(map), interactive: false }).addTo(st.selGroup);
                    var pl = L.polyline(ll, { color: color(w[1] || kv), weight: 3.5, opacity: 0.95, dashArray: "8 5",
                                               renderer: AGJMap.renderer(map) }).addTo(st.selGroup);
                    pl.bindTooltip("同じ名前の別の区間 ・ " + esc(title(r)), { sticky: true, className: "agj-tip" });
                    pl.on("click", function (e) { L.DomEvent.stopPropagation(e); selectRoute(r[C.ID], h.reg, { card: true }); });
                });
                if (b) box = [Math.min(box[0], b[0]), Math.min(box[1], b[1]), Math.max(box[2], b[2]), Math.max(box[3], b[3])];
            });
            map.flyToBounds([[box[1], box[0]], [box[3], box[2]]], { padding: [60, 60], maxZoom: 13 });
        });
    }

    // ── 鉄塔 ──
    function towerMarker(T, i, onRoute) {
        var rids = towerRoutes(T, i);
        var z = map.getZoom();
        var m = L.circleMarker([T.la[i] / 1e5, T.lo[i] / 1e5], {
            radius: z >= 15 ? 4.5 : z >= 13 ? 3.5 : 2.5,
            color: "#0d1117", weight: 1.2, fillColor: onRoute ? "#ffffff" : "#d0d7de", fillOpacity: 1,
            renderer: AGJMap.renderer(map),
        });
        var ref = T.ref[i], nm = T.name[i];
        m.bindTooltip("鉄塔 " + esc(ref ? "No." + ref : (nm || "番号なし")) + (rids.length > 1 ? " ・ 併架 " + rids.length + " 路線" : ""),
                      { sticky: true, className: "agj-tip" });
        m.on("click", function (e) { L.DomEvent.stopPropagation(e); openTowerCard(T, i, m); });
        return m;
    }

    function openTowerCard(T, i, marker) {
        var t = tower(T, i);
        Promise.all(t.rids.map(function (rid) { return findRoute(rid, T.reg); })).then(function (hits) {
            hits = hits.filter(Boolean);
            var rows = [
                ["番号", t.ref ? esc(t.ref) : "OSM に番号なし"],
            ];
            if (t.name) rows.push(["名前", esc(t.name)]);
            rows.push(["載っている線", hits.length ? hits.map(function (h, k) {
                return '<button type="button" class="osm-inline-btn" data-k="' + k + '">' + esc(title(h.rec)) + " " + esc(kvText(h.rec)) + "</button>";
            }).join("<br>") + (hits.length > 1 ? '<br><span class="osm-dim">併架（1 列の鉄塔に別の線）</span>' : "") : "線に載っていない（OSM の線とつながっていない鉄塔）"]);
            if (t.tags) Object.keys(t.tags).forEach(function (k) { rows.push([TOWER_TAG_JA[k] || k, esc(tagValueJa(k, t.tags[k]))]); });
            rows.push(["位置", t.lat.toFixed(5) + ", " + t.lon.toFixed(5)]);
            var first = hits[0];
            var spec = {
                kind: "鉄塔（OSM）", color: first ? color(kvMax(first.rec)) : "#aab4c0",
                title: t.ref ? "No." + t.ref : (t.name || "番号なし"),
                sub: first ? esc(title(first.rec)) : "線に載っていない",
                rows: rows,
                actions: [
                    first ? { text: "この線を選ぶ", onClick: function () { selectRoute(first.rec[C.ID], first.reg, { card: true }); } } : null,
                    first ? { text: "前の鉄塔へ", onClick: function () { stepTower(t, first, -1); } } : null,
                    first ? { text: "次の鉄塔へ", onClick: function () { stepTower(t, first, +1); } } : null,
                    { text: "OpenStreetMap で見る", href: "https://www.openstreetmap.org/node/" + t.id, blank: true },
                ].filter(Boolean),
                note: "番号は OSM の ref タグです。番号の無い鉄塔に番号は付けていません。地図データ © OpenStreetMap contributors（ODbL）。",
            };
            withOwnCard(function () { AGJMap.showCard(map, spec, marker || null); });
            var el = cardEl();
            if (el) el.querySelectorAll("button.osm-inline-btn[data-k]").forEach(function (b) {
                b.addEventListener("click", function () { var h = hits[+b.dataset.k]; selectRoute(h.rec[C.ID], h.reg, { card: true }); });
            });
            st.selTower = { reg: T.reg, id: t.id };
            setURL("tower", regIndex(T.reg) + "." + t.id);
            if (first && (!st.sel || st.sel.rid !== first.rec[C.ID])) {
                st.sel = { rid: first.rec[C.ID], reg: first.reg, rec: first.rec };
                drawSelected(first.rec, first.reg);
                drawRouteTowers(first.rec[C.ID], first.rec);
            }
        });
    }

    // 線の上で隣の鉄塔へ(way の頂点の並びをたどる。鉄塔でない頂点は飛ばす)
    function stepTower(t, hit, dir) {
        var key = Math.round(t.lat * 1e5) + "," + Math.round(t.lon * 1e5);
        var ws = hit.rec[C.W];
        for (var a = 0; a < ws.length; a++) {
            var ll = wayLL(ws[a]);
            for (var k = 0; k < ll.length; k++) {
                if (Math.round(ll[k][0] * 1e5) + "," + Math.round(ll[k][1] * 1e5) !== key) continue;
                return walk(ll, k, dir, hit);
            }
        }
    }
    function walk(ll, k, dir, hit) {
        var regs = regionsFor(hit.rec[C.BBOX]);
        return Promise.all(regs.map(loadTowers)).then(function (Ts) {
            for (var j = k + dir; j >= 0 && j < ll.length; j += dir) {
                var key = Math.round(ll[j][0] * 1e5) + "," + Math.round(ll[j][1] * 1e5);
                for (var q = 0; q < Ts.length; q++) {
                    var i = Ts[q].byCoord.get(key);
                    if (i != null) {
                        map.panTo([Ts[q].la[i] / 1e5, Ts[q].lo[i] / 1e5]);
                        openTowerCard(Ts[q], i, null);
                        return;
                    }
                }
            }
            var el = cardEl() && cardEl().querySelector(".agj-card-note");
            if (el) el.textContent = "この way の端です。続きはほかの way にあります（路線の線をクリックして選び直してください）。";
        });
    }

    function selectTowerById(regHint, id, opts) {
        opts = opts || {};
        return loadMeta().then(function () {
            var order = [regHint].concat(meta.regions.filter(function (r) { return r !== regHint; })).filter(Boolean);
            function next(k) {
                if (k >= order.length) return null;
                return loadTowers(order[k]).then(function (T) {
                    var i = T.byId.get(id);
                    if (i == null) return next(k + 1);
                    if (opts.fly) map.setView([T.la[i] / 1e5, T.lo[i] / 1e5], Math.max(map.getZoom(), 16));
                    openTowerCard(T, i, null);
                    return true;
                });
            }
            return next(0);
        });
    }

    // ── OSM の線と鉄塔を全部出す層(既定はオフ) ──
    function minKv() {
        var sel = document.getElementById(typeof colorMode !== "undefined" && colorMode === "region" ? "area-min-kv" : "min-kv");
        return sel ? parseFloat(sel.value) || 0 : 0;
    }

    function osmGroup(reg, mk) {
        var key = reg + "|" + mk;
        if (st.osmGroups[key]) return st.osmGroups[key];
        var g = L.layerGroup();
        routes[reg].list.forEach(function (rec) {
            var kv = kvMax(rec);
            if (mk > 0 && !(kv >= mk)) return;
            rec[C.W].forEach(function (w) {
                var ll = wayLL(w);
                if (ll.length < 2) return;
                var pl = L.polyline(ll, lineStyle(w[1] || kv, w[2], false));
                pl.bindTooltip("OSM の線 " + esc(title(rec)) + " ・ " + esc(kvText(rec)), { sticky: true, className: "agj-tip" });
                pl.on("click", function (e) { L.DomEvent.stopPropagation(e); selectRoute(rec[C.ID], reg, { card: true }); });
                pl.addTo(g);
            });
        });
        st.osmGroups[key] = g;
        return g;
    }

    var renderTimer = null;
    function scheduleRender() {
        if (renderTimer) clearTimeout(renderTimer);
        renderTimer = setTimeout(renderOsm, 160);
    }

    function setHint(text) {
        var el = document.getElementById("osm-layer-hint");
        if (el) el.textContent = text || "";
    }

    function renderOsm() {
        if (!meta) return;
        var z = map.getZoom(), mk = minKv();
        Object.keys(st.osmGroups).forEach(function (k) {
            var g = st.osmGroups[k];
            var reg = k.split("|")[0];
            var want = st.osmOn && z >= MIN_ZOOM_OSM && +k.split("|")[1] === mk && bboxHit(meta.region_bbox[reg], viewBox());
            if (want && !map.hasLayer(g)) g.addTo(map);
            if (!want && map.hasLayer(g)) map.removeLayer(g);
        });
        if (st.viewTowers) st.viewTowers.clearLayers();
        if (!st.osmOn) { setHint(""); return; }
        if (z < MIN_ZOOM_OSM) { setHint("寄ると出ます（もう " + (MIN_ZOOM_OSM - z) + " 段）"); return; }
        var regs = regionsFor(viewBox());
        Promise.all(regs.map(loadRoutes)).then(function () {
            if (!st.osmOn) return;
            regs.forEach(function (reg) {
                var g = osmGroup(reg, mk);
                if (!map.hasLayer(g)) g.addTo(map);
            });
            if (st.selGroup) { st.selGroup.eachLayer(function (l) { if (l.bringToFront) l.bringToFront(); }); }
            if (map.getZoom() < MIN_ZOOM_TOWERS) { setHint("鉄塔はもっと寄ると出ます"); return; }
            return Promise.all(regs.map(loadTowers)).then(function (Ts) {
                if (!st.osmOn) return;
                if (!st.viewTowers) st.viewTowers = L.layerGroup().addTo(map);
                st.viewTowers.clearLayers();
                var b = map.getBounds().pad(0.1), s = b.getSouth() * 1e5, n = b.getNorth() * 1e5, w = b.getWest() * 1e5, e = b.getEast() * 1e5;
                var cnt = 0;
                for (var q = 0; q < Ts.length && cnt < MAX_TOWERS_DRAWN; q++) {
                    var T = Ts[q];
                    for (var i = 0; i < T.n && cnt < MAX_TOWERS_DRAWN; i++) {
                        if (T.la[i] < s || T.la[i] > n || T.lo[i] < w || T.lo[i] > e) continue;
                        towerMarker(T, i, st.sel && towerRoutes(T, i).indexOf(st.sel.rid) >= 0).addTo(st.viewTowers);
                        cnt++;
                    }
                }
                setHint("鉄塔 " + nfmt(cnt) + " 基" + (cnt >= MAX_TOWERS_DRAWN ? "（多いので一部だけ）" : ""));
            });
        }).catch(function (e) { setHint("読み込めませんでした"); console.warn("[osm_routes]", e); });
    }

    function setOsmLayer(on) {
        st.osmOn = !!on;
        loadMeta().then(renderOsm);
    }

    // ── 正典の線のカードに路線を足す(grid_map.js の lineCard から呼ぶ) ──
    function fillCanonSlot(feature) {
        loadMeta().then(function () { return edgeRoutes(feature); }).then(function (list) {
            var el = cardEl() && cardEl().querySelector(".osm-slot-line");
            if (!el) return;
            if (!list.length) {
                el.innerHTML = '<span class="osm-dim">OSM の線と対応づけられない枝です（形の無い枝・引込み・同じ敷地のつなぎなど）。</span>';
                return;
            }
            return Promise.all(list.map(function (x) { return findRoute(x.rid, x.reg); })).then(function (hits) {
                hits = hits.filter(Boolean);
                if (!hits.length) return;
                var h0 = hits[0];
                el.innerHTML = '<div class="osm-slot-head">OSM の路線</div>' + hits.map(function (h, k) {
                    return '<div class="osm-slot-row"><button type="button" class="osm-inline-btn" data-k="' + k + '">' + esc(title(h.rec)) + "</button> " +
                        '<span class="osm-dim">' + esc(kvText(h.rec)) + " ・ " + h.rec[C.W].length + " 区間 ・ " + h.rec[C.LEN].toFixed(1) + " km</span></div>";
                }).join("") + (hits.length > 1 ? '<div class="osm-dim">同じ鉄塔を通る線が複数あります（併架）。上が電圧の合う線です。</div>' : "");
                el.querySelectorAll("button[data-k]").forEach(function (b) {
                    b.addEventListener("click", function () { var h = hits[+b.dataset.k]; selectRoute(h.rec[C.ID], h.reg, { card: true, fit: true }); });
                });
                // カードはそのまま、路線を光らせる
                st.sel = { rid: h0.rec[C.ID], reg: h0.reg, rec: h0.rec };
                drawSelected(h0.rec, h0.reg);
                highlightCanon(h0.rec[C.ID]);
                drawRouteTowers(h0.rec[C.ID], h0.rec);
            });
        }).catch(function (e) { console.warn("[osm_routes] canon slot", e); });
    }

    // ── 変電所の電圧ごとの母線(A5)。grid_map.js の subCard から呼ぶ ──
    function fillSiteSlot(name, lat, lon) {
        loadSearch().then(function (S) {
            var el = cardEl() && cardEl().querySelector(".osm-slot-site");
            if (!el) return;
            var base = String(name || "").replace(/\s*\d+(?:\.\d+)?\s*kV$/i, "");
            var same = S.subs.filter(function (s) {
                return s[0] === base && Math.abs(s[2] / 1e5 - lat) < 0.015 && Math.abs(s[3] / 1e5 - lon) < 0.018;
            });
            var kvs = [];
            same.forEach(function (s) { if (kvs.indexOf(s[1]) < 0) kvs.push(s[1]); });
            kvs.sort(function (a, b) { return b - a; });
            if (kvs.length < 2) {           // 電圧が 1 つだけの敷地はこの行を出さない
                var dd = el.closest("dd");
                if (dd) { var dt = dd.previousElementSibling; dd.remove(); if (dt) dt.remove(); }
                return;
            }
            el.innerHTML = kvs.map(function (kv, k) { return "（" + (k + 1) + "）" + esc(fmtKvLocal(kv)); }).join("　");
        });
    }
    function fmtKvLocal(kv) { return kv > 0 ? kv + " kV" : "電圧不明"; }

    // ── 横断検索の一覧(grid_search.js から) ──
    function loadSearch() { return loadMeta().then(function () { return getJSON("search.json"); }); }
    function loadSearchTowers() { return loadMeta().then(function () { return getJSON("search_towers.json"); }); }

    // ── URL ──
    function setURL(kind, val) {
        try {
            var u = new URL(location.href);
            u.searchParams.delete("route"); u.searchParams.delete("tower");
            if (kind) u.searchParams.set(kind, val);
            history.replaceState(null, "", u.pathname + u.search + u.hash);
        } catch (e) { /* 古いブラウザ */ }
    }

    function fromURL() {
        var q = new URLSearchParams(location.search);
        var r = q.get("route"), t = q.get("tower");
        if (!r && !t) return;
        loadMeta().then(function () {
            var v = (r || t).split(".");
            var reg = meta.regions[+v[0]], id = +v[1];
            if (!isFinite(id)) return;
            if (r) selectRoute(id, reg, { card: true, fit: true });
            else selectTowerById(reg, id, { fly: true });
        });
    }

    function init() {
        if (typeof map === "undefined" || !map) return;
        ensureGroups();
        map.on("agjcardopen", function () { if (!st.opening && !st.keepOnOpen) clearSelection(); });
        map.on("agjcardclose", function () { clearSelection(); });
        map.on("moveend", scheduleRender);
        map.on("zoomend", function () {
            if (st.sel) drawRouteTowers(st.sel.rid, st.sel.rec);
        });
        var cb = document.getElementById("chk-osm");
        if (cb) cb.addEventListener("change", function () { setOsmLayer(cb.checked); });
        ["min-kv", "area-min-kv"].forEach(function (id) {
            var s = document.getElementById(id);
            if (s) s.addEventListener("change", scheduleRender);
        });
        loadMeta().then(function () { fromURL(); }).catch(function (e) { console.warn("[osm_routes] meta", e); });
    }

    // 正典の線のクリックでカードを開いたあと(grid_map.js の lineCard → showCard のあと)に光らせる。
    // カードが開いた時点で前の選択は消えるので、ここで新しく描く
    function afterCanonCard(feature) {
        setTimeout(function () { fillCanonSlot(feature); }, 0);
    }
    function afterSubCard(name, lat, lon) {
        setTimeout(function () { fillSiteSlot(name, lat, lon); }, 0);
    }

    global.OSMRoutes = {
        init: init,
        selectRoute: selectRoute,
        selectTowerById: selectTowerById,
        setOsmLayer: setOsmLayer,
        afterCanonCard: afterCanonCard,
        afterSubCard: afterSubCard,
        loadSearch: loadSearch,
        loadSearchTowers: loadSearchTowers,
        nameParts: nameParts,
        edgeKey: edgeKey,
        _st: st,
        _state: function () { return { sel: st.sel && { rid: st.sel.rid, reg: st.sel.reg }, osmOn: st.osmOn, canonHi: st.canonHi.length,
                                        routesLoaded: Object.keys(routes), towersLoaded: Object.keys(towers) }; },
    };
    // grid_map.js の DOMContentLoaded(地図を作る)のあとに動く(script の順)
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();
})(window);
