/* 系統図マップの「つながりの点検」の層(2026-11-07)。
 *
 * scripts/audit_route_connectivity.py が書いた候補(docs/data/route_audit/audit.json)に印を出す。
 * 観測(OSM の線の端・途切れ)と正典(電圧の違う枝がつながる点・行き止まり)を分けて出し、
 * クリックすると根拠を確かめるための手がかり(近くの線・変電所・正典の枝・航空写真・OSM)をカードに出す。
 * **候補であって誤りの判定ではない。** 直しは介入台帳(docs/MODEL_INTERVENTIONS.md)で行う。
 */
(function (global) {
    "use strict";

    var URL_AUDIT = "./data/route_audit/audit.json";
    // 種類ごとの色と、何を見ればよいかの説明
    var KIND = {
        obs_near_line: { color: "#f2b134", r: 4, label: "つなぎ忘れの候補", group: "obs",
                         how: "線の端がどこにも続かず、すぐ近くに別の線があります。航空写真で鉄塔が続いているかを見ます。並んで走る別の線のこともあります。" },
        obs_near_sub: { color: "#3cc6c0", r: 4, label: "引込みの描き残し", group: "obs",
                        how: "線の端がどこにも続かず、300 m 以内に変電所があります。引込みの区間が OSM に描かれていない可能性があります。" },
        obs_nothing: { color: "#ff6b5e", r: 4, label: "何もない所で終わる", group: "obs",
                       how: "線の端の近くに線も変電所もありません。描きかけの線か、変電所が OSM に無い可能性があります。" },
        obs_outside: { color: "#8b949e", r: 3.5, label: "取得範囲の外", group: "obs",
                       how: "OSM を取った範囲（地域の外接矩形）の外で終わっています。取り直せば続く可能性があります。" },
        obs_split: { color: "#b48cff", r: 5, label: "同じ名前の線の途切れ", group: "obs",
                     how: "同じ名前・同じ電圧の路線が、両側とも行き止まりのまま 2 km 以内で途切れています。つなぎ忘れの有力な候補です。" },
        canon_mixed_kv: { color: "#ff4fa3", r: 6, label: "電圧の違う枝がつながる", group: "canon",
                          how: "正典で、変電所でない接続点に電圧の違う枝がつながっています。変圧器なしで電圧は変わらないので、併架の鉄塔で別の線をつないだ誤りの有力な候補です。変電所が OSM に無いだけの場合もあります。" },
        canon_dead_end: { color: "#ff9d3c", r: 3.5, label: "正典の行き止まり", group: "canon",
                          how: "正典で、変電所でない接続点に枝が 1 本しかありません（変電所に届かずに終わる）。" },
    };
    var REGION_JA = { hokkaido: "北海道", tohoku: "東北", tokyo: "東京", chubu: "中部", hokuriku: "北陸",
                      kansai: "関西", chugoku: "中国", shikoku: "四国", kyushu: "九州", okinawa: "沖縄" };

    var data = null, loading = null;
    var st = { on: false, minKv: 154, groups: { obs: true, canon: true }, layer: null, extra: null, photo: null };

    function esc(s) { return AGJMap.esc(s); }
    function load() {
        if (data) return Promise.resolve(data);
        if (!loading) loading = fetch(URL_AUDIT).then(function (r) { if (!r.ok) throw new Error("audit " + r.status); return r.json(); })
            .then(function (d) { data = d; return d; }).catch(function (e) { loading = null; throw e; });
        return loading;
    }

    function rowsShown() {
        return data.rows.filter(function (r) {
            var k = KIND[data.classes[r[0]]];
            if (!k || !st.groups[k.group]) return false;
            return st.minKv <= 0 ? true : r[3] >= st.minKv;
        });
    }

    function render() {
        if (!st.layer) st.layer = L.layerGroup().addTo(map);
        st.layer.clearLayers();
        if (st.extra) st.extra.clearLayers();
        var hint = document.getElementById("audit-hint");
        if (!st.on) { if (hint) hint.textContent = ""; return; }
        load().then(function () {
            if (!st.on) return;
            var rows = rowsShown(), cnt = {};
            rows.forEach(function (r) {
                var cls = data.classes[r[0]], k = KIND[cls];
                cnt[cls] = (cnt[cls] || 0) + 1;
                var m = L.circleMarker([r[1] / 1e5, r[2] / 1e5], {
                    radius: k.r, color: "#0d1117", weight: 1.2, fillColor: k.color, fillOpacity: 0.95,
                    renderer: AGJMap.renderer(map),
                });
                m.bindTooltip("点検 ・ " + esc(k.label) + (r[3] ? " ・ " + r[3] + " kV" : ""), { sticky: true, className: "agj-tip" });
                m.on("click", function (e) { L.DomEvent.stopPropagation(e); openCard(r, m); });
                m.addTo(st.layer);
            });
            if (hint) hint.textContent = "印 " + rows.length.toLocaleString("ja-JP") + " か所（" +
                Object.keys(cnt).map(function (c) { return KIND[c].label + " " + cnt[c]; }).join("・") + "）";
        }).catch(function (e) { if (hint) hint.textContent = "読み込めませんでした"; console.warn("[route_audit]", e); });
    }

    function togglePhoto(ll) {
        if (st.photo && map.hasLayer(st.photo)) { map.removeLayer(st.photo); return false; }
        if (!st.photo) {
            st.photo = L.tileLayer("https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg", {
                attribution: '航空写真 &copy; <a href="https://maps.gsi.go.jp/development/ichiran.html">国土地理院</a>',
                maxZoom: 19, maxNativeZoom: 18, pane: "terrainPane", opacity: 1,
            });
        }
        st.photo.addTo(map);
        if (ll) map.setView(ll, Math.max(map.getZoom(), 17));
        return true;
    }

    function m(x) { return x == null ? "—" : x.toLocaleString("ja-JP") + " m"; }

    function openCard(r, marker) {
        var cls = data.classes[r[0]], k = KIND[cls], d = r[6] || {}, ll = L.latLng(r[1] / 1e5, r[2] / 1e5);
        var reg = data.regions[r[4]];
        var rows = [["電圧", r[3] ? esc(r[3] + " kV") : "不明"], ["地域", esc(REGION_JA[reg] || reg || "—")]];
        if (k.group === "obs") {
            rows.push(["線", (d.name ? esc(d.name) : "名前なし") + (r[5] ? ' <button type="button" class="osm-inline-btn" data-act="route">路線を選ぶ</button>' : "")]);
            if (cls === "obs_split") {
                rows.push(["隙間", m(d.gap_m) + "（同じ名前の続きまで）"]);
            } else {
                if (d.near_line_m != null) rows.push(["近くの線", m(d.near_line_m) + " 先に " + esc(d.near_line_name || "名前なしの線")]);
                rows.push(["近くの変電所", m(d.sub_m) + (d.sub_name ? " 先に " + esc(d.sub_name) : "")]);
            }
            rows.push(["正典では", d.canon_line_m != null && d.canon_line_m <= 60
                ? "正典の枝が " + m(d.canon_line_m) + " の所を通る（正典では線が続いている）"
                : "正典の枝は " + m(d.canon_line_m) + " 先（正典でもここで線が切れている）"]);
            if (d.way) rows.push(["OSM", '<a href="https://www.openstreetmap.org/way/' + d.way + '" target="_blank" rel="noopener">way ' + d.way + "</a>" +
                (d.node ? '・<a href="https://www.openstreetmap.org/node/' + d.node + '" target="_blank" rel="noopener">端の点</a>' : "")]);
        } else {
            rows.push(["つながる枝", esc((d.names || []).filter(Boolean).join("・") || "—")]);
            if (d.kvs) rows.push(["枝の電圧", esc(d.kvs.join(" / ") + " kV")]);
            rows.push(["枝の数", String(d.deg)]);
            rows.push(["本系統", d.main ? "はい" : "いいえ（本系統から切れている）"]);
            rows.push(["最寄りの変電所", m(d.sub_m) + (d.sub_name ? " 先に " + esc(d.sub_name) : "")]);
        }
        rows.push(["位置", ll.lat.toFixed(5) + ", " + ll.lng.toFixed(5)]);
        var spec = {
            kind: "つながりの点検（" + (k.group === "obs" ? "観測・OSM" : "正典") + "）", color: k.color,
            title: k.label,
            sub: esc(k.how),
            rows: rows,
            actions: [
                { text: "航空写真を重ねる・外す", onClick: function () { togglePhoto(ll); } },
                { text: "OpenStreetMap で見る", href: "https://www.openstreetmap.org/#map=18/" + ll.lat.toFixed(5) + "/" + ll.lng.toFixed(5), blank: true },
                { text: "地理院地図で見る", href: "https://maps.gsi.go.jp/#18/" + ll.lat.toFixed(5) + "/" + ll.lng.toFixed(5) + "/&base=std&ls=std%7Cseamlessphoto&disp=01", blank: true },
            ],
            note: "候補であって誤りの判定ではありません。直すのは航空写真・OSM・公表値の根拠があるものだけで、直しは介入台帳（docs/MODEL_INTERVENTIONS.md）に記録します。" +
                  (k.group === "obs" ? "地図データ © OpenStreetMap contributors（ODbL）。" : ""),
            _after: function (el) {
                var b = el.querySelector('button[data-act="route"]');
                if (b && global.OSMRoutes) b.addEventListener("click", function () { OSMRoutes.selectRoute(r[5], reg, { card: true, fit: true }); });
            },
        };
        AGJMap.showCard(map, spec, marker);
        if (!st.extra) st.extra = L.layerGroup().addTo(map);
        st.extra.clearLayers();
        if (cls === "obs_split" && d.a && d.b) {
            L.polyline([[d.a[0] / 1e5, d.a[1] / 1e5], [d.b[0] / 1e5, d.b[1] / 1e5]],
                { color: k.color, weight: 3, dashArray: "4 5", renderer: AGJMap.renderer(map), interactive: false }).addTo(st.extra);
        }
    }

    function setMinKv(v) {
        st.minKv = +v;
        document.querySelectorAll("#audit-kv button").forEach(function (b) { b.classList.toggle("active", +b.dataset.v === st.minKv); });
        render();
    }

    function init() {
        if (typeof map === "undefined" || !map) return;
        var cb = document.getElementById("chk-audit");
        if (cb) cb.addEventListener("change", function () { st.on = cb.checked; render(); });
        document.querySelectorAll("#audit-kv button").forEach(function (b) {
            b.addEventListener("click", function () { setMinKv(b.dataset.v); });
        });
        ["obs", "canon"].forEach(function (g) {
            var c = document.getElementById("chk-audit-" + g);
            if (c) c.addEventListener("change", function () { st.groups[g] = c.checked; render(); });
        });
        map.on("agjcardclose", function () { if (st.extra) st.extra.clearLayers(); });
        var leg = document.getElementById("audit-legend");
        if (leg) leg.innerHTML = Object.keys(KIND).map(function (c) {
            return '<span class="audit-key"><i style="background:' + KIND[c].color + '"></i>' + esc(KIND[c].label) + "</span>";
        }).join("");
    }

    // 画面の点(地図の入れ物の座標)に点検の印があるか(js/tower_dots.js が、鉄塔より印を先にするのに使う)
    function hitAt(cp) {
        if (!st.on || !st.layer) return false;
        var hit = false;
        st.layer.eachLayer(function (m) {
            if (hit) return;
            var p = map.latLngToContainerPoint(m.getLatLng());
            var r = (m.options.radius || 4) + 4;
            if ((p.x - cp.x) * (p.x - cp.x) + (p.y - cp.y) * (p.y - cp.y) <= r * r) hit = true;
        });
        return hit;
    }

    global.RouteAudit = { init: init, render: render, load: load, hitAt: hitAt, _st: st };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();
})(window);
