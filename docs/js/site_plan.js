/* 接続の計画とサイト分析(site_plan.html, 2026-11-07).
 *
 * 地図で候補地を選ぶと、
 *   1. 電圧ごとに最寄りの変電所と最寄りの送電線(線への垂線の足)を直線距離つきで出す
 *   2. 候補地 → 選んだ接続先の直線上の標高の断面を描く(地理院の標高タイル)
 *   3. 前年 1 年の日射・風速・気温を出す(Open-Meteo の Historical Weather API・ERA5)
 *   4. 空き容量は数値を載せず、そのエリアの事業者の公表ページへ案内する
 *   5. 以上を印刷用のレポートにまとめる(ブラウザの印刷で PDF)
 * 状態は URL の #lat=..&lon=..(&sel=..) で共有する。
 *
 * 決まり:
 *   - 系統は正典(docs/data/built)から書いた地図データ data/map/*_all.geojson だけを読む。正典は変えない
 *   - 距離は直線。実際の経路ではないことを、表・カード・レポートのどこでも書く
 *   - 出典の無い数字は出さない。工事費の単価は持たず、利用者が入れたときだけ「仮定」として掛け算する
 *   - 各社の空き容量・線路別の容量は載せない(All Rights Reserved の事業者がある。docs/OBSERVED_VS_DERIVED.md)
 *   - 外部への問い合わせは抑える: 標高はタイル(ブラウザがキャッシュ)、気象は ERA5 の格子ごとに 1 回、
 *     地名は Enter のときだけ・1 秒以上あける(Nominatim の利用方針)
 */
(function () {
    "use strict";

    // ── 定数 ────────────────────────────────────────────────
    const DATA = {
        subs: "./data/map/subs_all.geojson",
        lines: "./data/map/lines_all.geojson",
        obs: "./data/flow_map/obs_local.json",
        dash: "./data/dashboard.json",
    };
    const NEAR_KM = 100;            // 表に出す電圧の目安(これより遠い電圧は名前だけ)
    const R_KM = 6371.0088;
    const DEG = Math.PI / 180;
    const KV_CLASSES = [500, 275, 220, 187, 154, 132, 110, 77, 66, 0];   // 0 = 電圧不明
    // grid_map.js と同じ色(系統図と見比べられるように)
    const VOLTAGE_COLORS = {
        500: "#d62728", 275: "#ff7f0e", 220: "#e377c2", 187: "#9467bd", 154: "#2ca02c",
        132: "#17becf", 110: "#1f77b4", 77: "#bcbd22", 66: "#8c564b", 0: "#9aa4ae",
    };
    const KV_MAX_REAL = 1100;       // grid_map.js と同じ。超える値は OSM の多値タグの読み違い
    const DETOUR_DEFAULT = 1.12;    // docs/reports/impedance_validation_2026-08-19.md §10(経路/弦の中央値)

    // 空き容量の入口。AGJ の取得台帳 config/system_disclosure.yaml の index_url(中部だけは空容量の地図のページ)
    const UTILS = {
        hokkaido: ["北海道電力ネットワーク", "https://www.hepco.co.jp/network/con_service/public_document/bid_info.html"],
        tohoku: ["東北電力ネットワーク", "https://nw.tohoku-epco.co.jp/consignment/system/announcement/index.html"],
        tokyo: ["東京電力パワーグリッド", "https://www.tepco.co.jp/pg/consignment/system/"],
        chubu: ["中部電力パワーグリッド", "https://powergrid.chuden.co.jp/goannai/hatsuden_kouri/takuso_kyokyu/rule/map/index.html"],
        hokuriku: ["北陸電力送配電", "https://www.rikuden.co.jp/nw_notification/U_154seiyaku.html"],
        kansai: ["関西電力送配電", "https://www.kansai-td.co.jp/consignment/disclosure/distribution-equipment/index.html"],
        chugoku: ["中国電力ネットワーク", "https://www.energia.co.jp/nw/service/retailer/keitou/access/"],
        shikoku: ["四国電力送配電", "https://www.yonden.co.jp/nw/line_access/data.html"],
        kyushu: ["九州電力送配電", "https://www.kyuden.co.jp/td_service_wheeling_rule-document_disclosure"],
        okinawa: ["沖縄電力", "https://www.okiden.co.jp/business-support/service/rule/plan/index.html"],
    };
    const REGION_JA = { hokkaido: "北海道", tohoku: "東北", tokyo: "東京", chubu: "中部", hokuriku: "北陸", kansai: "関西",
                        chugoku: "中国", shikoku: "四国", kyushu: "九州", okinawa: "沖縄" };
    // OSM の operator タグ(変電所の運営者)から事業者のエリアを引く
    const OPERATOR_RX = [[/北海道電力/, "hokkaido"], [/東北電力/, "tohoku"], [/東京電力/, "tokyo"], [/中部電力/, "chubu"],
                         [/北陸電力/, "hokuriku"], [/関西電力/, "kansai"], [/中国電力/, "chugoku"], [/四国電力/, "shikoku"],
                         [/九州電力/, "kyushu"], [/沖縄電力/, "okinawa"]];
    const REGION_ORDER = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku", "kansai", "chugoku", "shikoku", "kyushu", "okinawa"];

    // 地理院の標高タイル(https://maps.gsi.go.jp/development/ichiran.html・仕様 demtile.html)
    const GSI = "https://cyberjapandata.gsi.go.jp/xyz/";
    const DEM = {
        dem5a: { path: "dem5a_png", z: 15, label: "DEM5A（5 m メッシュ）" },
        dem5b: { path: "dem5b_png", z: 15, label: "DEM5B（5 m メッシュ）" },
        dem10b: { path: "dem_png", z: 14, label: "DEM10B（10 m メッシュ）" },
    };
    const PROFILE_N = 161;          // 断面の点の数

    const NOMINATIM = "https://nominatim.openstreetmap.org/search";
    const GEO_GAP_MS = 1100;        // Nominatim の利用方針: 1 秒に 1 回まで
    const OPEN_METEO = "https://archive-api.open-meteo.com/v1/archive";
    const WX_DEBOUNCE_MS = 700;

    const $ = (id) => document.getElementById(id);
    const esc = (s) => AGJMap.esc(s);

    // ── 状態 ────────────────────────────────────────────────
    let map = null, candLayer = null, siteMarker = null, hoverMarker = null, distTip = null;
    let SUB = null, SEG = null;           // 最寄り探索用の配列
    let subMeta = [], lineMeta = [];      // 表示用の属性
    let obsLines = null, dashInfo = null;
    let site = null;                      // { lat, lon, elev: {h, src} | null | undefined }
    let cands = [], far = [], selKey = null, region = null;
    let profileState = null;              // { key, dist, z, pts }
    let weather = null;                   // 集計済みの気象(renderWeather が読む)
    let seq = 0;                          // 候補地を選び直したら古い非同期の結果を捨てる
    let lastHash = "";
    const lineByKey = {}, markerByKey = {};

    // ── 小道具 ──────────────────────────────────────────────
    function kvClass(kv) {
        if (!(kv > 0) || kv > KV_MAX_REAL) return 0;
        for (const c of KV_CLASSES) if (c > 0 && kv >= c) return c;
        return 0;
    }
    const kvText = (c) => (c > 0 ? c + " kV" : "電圧不明");
    const colorOf = (c) => VOLTAGE_COLORS[c] || VOLTAGE_COLORS[0];
    const kvGlyph = (c) => '<span class="sp-kvg" style="color:' + colorOf(c) + '" aria-hidden="true">━</span>';

    function hav(lat1, lon1, lat2, lon2) {
        const dl = (lat2 - lat1) * DEG, dn = (lon2 - lon1) * DEG;
        const a = Math.sin(dl / 2) ** 2 + Math.cos(lat1 * DEG) * Math.cos(lat2 * DEG) * Math.sin(dn / 2) ** 2;
        return 2 * R_KM * Math.asin(Math.min(1, Math.sqrt(a)));
    }
    function fmtKm(d) {
        if (d == null || !isFinite(d)) return "—";
        return (d < 1 ? d.toFixed(2) : d < 100 ? d.toFixed(1) : Math.round(d).toLocaleString("ja-JP")) + " km";
    }
    const fmtNum = (x, n) => (x == null || !isFinite(x) ? "—" : x.toLocaleString("ja-JP", { minimumFractionDigits: n || 0, maximumFractionDigits: n || 0 }));
    const fmtTick = (v) => (Math.abs(v) >= 1000 ? fmtNum(v) : String(+v.toFixed(2)));
    const fmtLL = (lat, lon) => lat.toFixed(5) + ", " + lon.toFixed(5);
    const cleanName = (n) => String(n || "").replace(/\s*\d+(?:\.\d+)?\s*kV$/i, "");
    const normName = (s) => String(s || "").normalize("NFKC").replace(/[\s・()（）]/g, "");
    const inJapan = (lat, lon) => lat >= 20 && lat <= 46.5 && lon >= 122 && lon <= 154.5;

    function status(msg) { const el = $("status-text"); if (el) el.textContent = msg; }

    function getJSON(url) {
        return fetch(url).then((r) => {
            if (!r.ok) throw new Error(url + " " + r.status);
            return r.json();
        });
    }

    // ── 系統データ ──────────────────────────────────────────
    function buildIndex(subs, lines) {
        const sf = subs.features.filter((f) => f.geometry && f.geometry.type === "Point");
        SUB = { n: sf.length, lat: new Float64Array(sf.length), lon: new Float64Array(sf.length), cls: new Int16Array(sf.length) };
        subMeta = sf.map((f, i) => {
            const p = f.properties || {}, c = f.geometry.coordinates, cls = kvClass(p._voltage_kv);
            SUB.lat[i] = c[1]; SUB.lon[i] = c[0]; SUB.cls[i] = KV_CLASSES.indexOf(cls);
            let op = null;
            for (const [rx, code] of OPERATOR_RX) if (rx.test(p.operator || "")) { op = code; break; }
            return { name: p._display_name || p.name || "名称なし", kv: p._voltage_kv, cls, main: p._main !== false, op,
                     region: p._region, region_ja: p._region_ja, lat: c[1], lon: c[0], p };
        });

        let nseg = 0;
        const lf = lines.features.filter((f) => f.geometry && f.geometry.type === "LineString" && f.geometry.coordinates.length >= 2);
        lf.forEach((f) => { nseg += f.geometry.coordinates.length - 1; });
        SEG = { n: nseg, lon1: new Float64Array(nseg), lat1: new Float64Array(nseg), lon2: new Float64Array(nseg),
                lat2: new Float64Array(nseg), cls: new Int16Array(nseg), f: new Int32Array(nseg) };
        let k = 0;
        lineMeta = lf.map((f, i) => {
            const p = f.properties || {}, cs = f.geometry.coordinates, cls = kvClass(p._voltage_kv), ci = KV_CLASSES.indexOf(cls);
            let w = 180, e = -180, s = 90, n = -90;
            for (let j = 0; j < cs.length; j++) {
                const x = cs[j][0], y = cs[j][1];
                if (x < w) w = x; if (x > e) e = x; if (y < s) s = y; if (y > n) n = y;
                if (j > 0) {
                    SEG.lon1[k] = cs[j - 1][0]; SEG.lat1[k] = cs[j - 1][1]; SEG.lon2[k] = x; SEG.lat2[k] = y;
                    SEG.cls[k] = ci; SEG.f[k] = i; k++;
                }
            }
            return { name: p._display_name || "名称なし", kv: p._voltage_kv, cls, main: p._main !== false, region: p._region,
                     region_ja: p._region_ja, par: p._par, coords: cs, bbox: [w, s, e, n] };
        });
    }

    function renderNetwork(subs, lines) {
        const r = AGJMap.renderer(map);
        // 系統は背景として描くだけ(クリックはすべて候補地の指定に使う)。調べるのは候補の印から
        L.geoJSON(lines, {
            renderer: r, interactive: false,
            style: (f) => {
                const c = kvClass(f.properties._voltage_kv);
                return { color: colorOf(c), weight: c >= 500 ? 2.6 : c >= 275 ? 2.1 : c >= 154 ? 1.6 : 1.1, opacity: f.properties._main === false ? 0.35 : 0.62 };
            },
        }).addTo(map);
        L.geoJSON(subs, {
            renderer: r, interactive: false,
            filter: (f) => f.geometry && f.geometry.type === "Point",
            pointToLayer: (f, ll) => {
                const c = kvClass(f.properties._voltage_kv);
                return L.circleMarker(ll, { renderer: r, interactive: false, radius: c >= 275 ? 3 : 2.2, stroke: false,
                    fillColor: colorOf(c), fillOpacity: 0.85 });
            },
        }).addTo(map);
    }

    function addLegend() {
        const ctl = L.control({ position: "bottomright" });
        ctl.onAdd = function () {
            const el = L.DomUtil.create("div", "sp-legend");
            el.innerHTML = '<div class="sp-legend-h">線と変電所の色（電圧）</div><div class="sp-legend-g">' +
                KV_CLASSES.map((c) => "<span>" + kvGlyph(c) + " " + (c > 0 ? c : "不明") + "</span>").join("") + "</div>" +
                '<div class="sp-legend-m"><span><i class="sp-lg-sub"></i>最寄りの変電所</span><span><i class="sp-lg-foot"></i>線上のいちばん近い点</span>' +
                '<span><i class="sp-lg-dash"></i>直線（経路ではない）</span></div>';
            L.DomEvent.disableClickPropagation(el);
            return el;
        };
        ctl.addTo(map);
    }

    // ── 最寄り探索 ──────────────────────────────────────────
    // 候補地のまわりを正距円筒で平面にみなして探す(どの候補が一番近いかを決めるだけ)。表に出す距離は大円距離で測り直す
    function nearest(lat0, lon0) {
        const kx = R_KM * Math.cos(lat0 * DEG) * DEG, ky = R_KM * DEG, C = KV_CLASSES.length;
        const bs = new Float64Array(C).fill(Infinity), bi = new Int32Array(C).fill(-1);
        for (let i = 0; i < SUB.n; i++) {
            const dx = (SUB.lon[i] - lon0) * kx, dy = (SUB.lat[i] - lat0) * ky, d2 = dx * dx + dy * dy, c = SUB.cls[i];
            if (d2 < bs[c]) { bs[c] = d2; bi[c] = i; }
        }
        const bl = new Float64Array(C).fill(Infinity), li = new Int32Array(C).fill(-1), lt = new Float64Array(C);
        for (let j = 0; j < SEG.n; j++) {
            const c = SEG.cls[j];
            const x1 = (SEG.lon1[j] - lon0) * kx, y1 = (SEG.lat1[j] - lat0) * ky;
            const ex = (SEG.lon2[j] - lon0) * kx - x1, ey = (SEG.lat2[j] - lat0) * ky - y1;
            const L2 = ex * ex + ey * ey;
            let t = L2 > 0 ? -(x1 * ex + y1 * ey) / L2 : 0;
            t = t < 0 ? 0 : t > 1 ? 1 : t;
            const fx = x1 + t * ex, fy = y1 + t * ey, d2 = fx * fx + fy * fy;
            if (d2 < bl[c]) { bl[c] = d2; li[c] = j; lt[c] = t; }
        }
        const out = [];
        KV_CLASSES.forEach((cls, ci) => {
            if (bi[ci] >= 0) {
                const m = subMeta[bi[ci]];
                out.push({ key: "sub-" + cls, type: "sub", cls, name: m.name, lat: m.lat, lon: m.lon, main: m.main,
                           region: m.region, region_ja: m.region_ja, dist: hav(lat0, lon0, m.lat, m.lon), meta: m });
            }
            if (li[ci] >= 0) {
                const j = li[ci], t = lt[ci], m = lineMeta[SEG.f[j]];
                const lat = SEG.lat1[j] + t * (SEG.lat2[j] - SEG.lat1[j]), lon = SEG.lon1[j] + t * (SEG.lon2[j] - SEG.lon1[j]);
                out.push({ key: "line-" + cls, type: "line", cls, name: m.name, lat, lon, main: m.main, region: m.region,
                           region_ja: m.region_ja, dist: hav(lat0, lon0, lat, lon), meta: m });
            }
        });
        return out;
    }

    // 線名だけで公表の潮流実績(年統計)を引く(flow_map.html と同じ正規化)。公表の線名は回線の印つき
    // (例 東京東線12L)なので、末尾の「12L」「1号線」を外した名前でも引く。同じ事業者で、公表の電圧が
    // 分かるときはモデルの電圧階級と同じものに限る(同名の別の電圧の線を拾わないため)
    function indexObs(lines) {
        const idx = {};
        Object.keys(lines).forEach((k) => {
            const base = normName(k).replace(/(\d+L|\d+号線?)$/i, "");
            (idx[base] = idx[base] || []).push(Object.assign({ key: k }, lines[k]));
            if (base !== normName(k)) (idx[normName(k)] = idx[normName(k)] || []).push(Object.assign({ key: k }, lines[k]));
        });
        return idx;
    }
    function obsFor(c) {
        if (!obsLines || c.type !== "line") return null;
        const k = normName(String(c.name).split(" ")[0]);
        if (k.length < 2 || k === "送電線" || /kV線$/i.test(k)) return null;
        const hit = (obsLines[k] || []).filter((o) => o.util === c.region && (!o.kv || kvClass(+o.kv) === c.cls));
        return hit.length ? hit.sort((a, b) => (b.p95 || 0) - (a.p95 || 0))[0] : null;
    }
    function obsHtml(o) {
        return '<p class="sp-obs">公表の潮流実績（2024 年度の年統計・線名だけで引いた値で区間は未確認・公表の線名「' + esc(o.key) + '」）: 平均 ' +
            (o.mean != null ? fmtNum(Math.abs(o.mean)) : "—") + " / p95 " + fmtNum(o.p95) + " / 最大 " +
            (o.max != null ? fmtNum(o.max) : "—") + " MW。出典: " + esc(UTILS[o.util] ? UTILS[o.util][0] : o.util) +
            " の系統情報の公表（AGJ が集計）。</p>";
    }

    // エリアの目安(空き容量の公表ページを選ぶため)。
    // 1. 40 km 以内に運営者タグ(OSM の operator)のある変電所が 3 か所以上あれば、近い 15 か所を距離で重みづけした多数決
    // 2. 足りなければ、近い変電所 30 か所(30 km 以内)の AGJ の地域ラベルの多数決
    // 地域ラベル(_region)だけだと北陸の変電所の半分ほどが「中部」になっているため、運営者タグを先に見る。
    // 2026-11-07 に 27 地点(各社の中心都市と、富士川の東・敦賀・小浜・熊野など境界の近く)で 1 位が供給区域と一致。
    // 2 位が 1 位の 6 割以上なら決めきれないとして両方を出す
    function areaGuess(lat0, lon0) {
        const kx = Math.cos(lat0 * DEG), near = [];
        for (let i = 0; i < SUB.n; i++) {
            const dx = (SUB.lon[i] - lon0) * kx, dy = SUB.lat[i] - lat0;
            near.push([dx * dx + dy * dy, i]);
        }
        near.sort((a, b) => a[0] - b[0]);
        const score = {}, add = (k, w) => { score[k] = (score[k] || 0) + w; };
        const ops = [];
        for (const [, i] of near) {
            const m = subMeta[i], d = hav(lat0, lon0, m.lat, m.lon);
            if (d > 40 || ops.length >= 15) break;
            if (m.op) ops.push([d, m.op]);
        }
        let basis, n = 0;
        if (ops.length >= 3) {
            ops.forEach(([d, op]) => add(op, 1 / (1 + d / 10)));
            basis = "op"; n = ops.length;
        } else {
            for (const [, i] of near.slice(0, 30)) {
                const m = subMeta[i];
                if (n > 0 && hav(lat0, lon0, m.lat, m.lon) > 30) break;
                n++;
                if (m.region) add(m.region, 1);
            }
            basis = "region";
        }
        const rank = Object.keys(score).sort((a, b) => score[b] - score[a]);
        if (!rank.length) return { codes: [], n: 0, basis };
        const codes = [rank[0]];
        if (rank[1] && score[rank[1]] >= 0.6 * score[rank[0]]) codes.push(rank[1]);
        return { codes, n, basis };
    }
    const areaText = (a) => (a && a.codes.length ? a.codes.map((c) => REGION_JA[c] || c).join(" か ") : "—");

    // ── 費用(利用者の仮定) ──────────────────────────────────
    function costAssume() {
        const u = parseFloat($("sp-unit").value), f = parseFloat($("sp-detour").value);
        if (!(u > 0)) return null;
        return { unit: u, factor: f >= 1 ? f : 1 };
    }
    const costOf = (c, a) => (a ? c.dist * a.factor * a.unit : null);
    const costText = (x) => "仮定 " + fmtNum(x, x < 10 ? 1 : 0) + " 億円";

    // ── 候補地を決める ──────────────────────────────────────
    function setSite(lat, lon, opts) {
        opts = opts || {};
        if (!SUB) { pending = { lat, lon, opts }; return; }
        if (!inJapan(lat, lon)) { status("日本の範囲（北緯 20〜46 度・東経 122〜154 度）の外です"); return; }
        const my = ++seq;
        site = { lat, lon, elev: undefined };
        const all = nearest(lat, lon);
        const byCls = {};
        all.forEach((c) => { (byCls[c.cls] = byCls[c.cls] || []).push(c); });
        cands = []; far = [];
        KV_CLASSES.forEach((cls) => {
            const g = byCls[cls] || [];
            if (!g.length) return;
            if (Math.min.apply(null, g.map((c) => c.dist)) <= NEAR_KM) cands.push.apply(cands, g);
            else far.push(cls);
        });
        region = areaGuess(lat, lon);

        const want = opts.sel && cands.some((c) => c.key === opts.sel) ? opts.sel : defaultSel();
        placeSiteMarker();
        drawCands();
        renderSite();
        renderCapacity();
        $("sp-open-report").disabled = false;
        $("sp-copy-link").disabled = false;
        select(want, { silent: true });
        if (opts.fly) {
            const pts = [[lat, lon]].concat(cands.slice().sort((a, b) => a.dist - b.dist).slice(0, 4).map((c) => [c.lat, c.lon]));
            // 共有リンクで開いたとき(jump)は動きなしで寄る。読み込み直後の重い再描画で飛ぶ動きが止まることがあった
            if (opts.fly === "jump") map.fitBounds(L.latLngBounds(pts), { padding: [70, 70], maxZoom: 14, animate: false });
            else map.flyToBounds(L.latLngBounds(pts), { padding: [70, 70], maxZoom: 14, duration: 0.8 });
        }
        writeHash();
        status(fmtLL(lat, lon) + " ・ 近い系統 " + cands.length + " 件");

        pointElevation(lat, lon).then((e) => {
            if (my !== seq) return;
            site.elev = e;
            renderSite();
        });
        scheduleWeather();
    }
    let pending = null;

    function defaultSel() {
        let b = null;
        cands.forEach((c) => { if (c.type === "sub" && c.cls > 0 && (!b || c.dist < b.dist)) b = c; });
        if (!b) cands.forEach((c) => { if (!b || c.dist < b.dist) b = c; });
        return b ? b.key : null;
    }

    function placeSiteMarker() {
        const ll = [site.lat, site.lon];
        if (!siteMarker) {
            siteMarker = L.marker(ll, {
                draggable: true, keyboard: true, title: "候補地（引っぱって動かせます）", zIndexOffset: 1000,
                icon: L.divIcon({ className: "sp-site-pin", html: "<i></i>", iconSize: [18, 18], iconAnchor: [9, 9] }),
            }).addTo(map);
            siteMarker.on("dragend", () => { const p = siteMarker.getLatLng(); setSite(p.lat, p.lng); });
        } else {
            siteMarker.setLatLng(ll);
        }
    }

    function drawCands() {
        const r = AGJMap.renderer(map);
        candLayer.clearLayers();
        Object.keys(lineByKey).forEach((k) => { delete lineByKey[k]; delete markerByKey[k]; });
        cands.forEach((c) => {
            const col = colorOf(c.cls);
            const ln = L.polyline([[site.lat, site.lon], [c.lat, c.lon]], { renderer: r, interactive: false, color: col,
                weight: 1.4, opacity: 0.8, dashArray: "4 5" });
            const mk = L.circleMarker([c.lat, c.lon], c.type === "sub"
                ? { renderer: r, radius: 5.5, color: "#ffffff", weight: 1.2, fillColor: col, fillOpacity: 1 }
                : { renderer: r, radius: 4.5, color: col, weight: 2.2, fillColor: "#0d1117", fillOpacity: 1 });
            AGJMap.bindInfo(mk, (c.type === "sub" ? "変電所 " : "送電線 ") + c.name + " ・ " + kvText(c.cls) + " ・ 直線 " + fmtKm(c.dist));
            mk.on("click", (e) => {
                L.DomEvent.stopPropagation(e);
                select(c.key);
                AGJMap.showCard(map, candCard(c), mk);
            });
            candLayer.addLayer(ln);
            candLayer.addLayer(mk);
            lineByKey[c.key] = ln;
            markerByKey[c.key] = mk;
        });
    }

    function candCard(c) {
        const rows = [["電圧", esc(kvText(c.cls))], ["直線距離", "<b>" + esc(fmtKm(c.dist)) + "</b>"],
                      ["つながり", c.main ? "本系統" : "本系統から切れている（AGJ のモデルの中で）"],
                      ["地域", esc(c.region_ja || "—")]];
        if (c.type === "line") {
            rows.push(["回線数", c.meta.par ? esc(String(c.meta.par)) : "—"]);
            rows.push(["接続点", "線への垂線の足 " + esc(fmtLL(c.lat, c.lon))]);
        } else {
            rows.push(["位置", esc(fmtLL(c.lat, c.lon))]);
        }
        const a = costAssume();
        if (a) rows.push(["費用（仮定）", esc(costText(costOf(c, a))) + "<br><small>直線 × " + a.factor + " × " + a.unit + " 億円/km</small>"]);
        const o = obsFor(c);
        const nm = cleanName(c.name).replace(/変電所$/, "");
        const osm = "https://www.openstreetmap.org/#map=16/" + c.lat.toFixed(5) + "/" + c.lon.toFixed(5);
        return {
            kind: c.type === "sub" ? "変電所（最寄り）" : "送電線（線上のいちばん近い点）", color: colorOf(c.cls),
            title: c.type === "sub" ? cleanName(c.name) : c.name,
            sub: esc(kvText(c.cls) + " ・ 候補地から直線 " + fmtKm(c.dist)),
            rows,
            html: o ? obsHtml(o) : "",
            actions: [c.type === "sub" && nm ? { text: "SubSLD で変電所の中を見る", href: "./subsld.html?q=" + encodeURIComponent(nm) } : null,
                      { text: "OpenStreetMap で見る", href: osm, blank: true }].filter(Boolean),
            note: "距離は直線で、実際の経路ではありません。線の途中につなげるか、空きがあるかはここでは分かりません。",
        };
    }

    function select(key, opts) {
        opts = opts || {};
        selKey = key;
        cands.forEach((c) => {
            const ln = lineByKey[c.key], on = c.key === key;
            if (ln) ln.setStyle({ weight: on ? 3.2 : 1.4, opacity: on ? 1 : 0.75, dashArray: on ? null : "4 5" });
        });
        const c = cands.find((x) => x.key === key);
        if (distTip) { map.removeLayer(distTip); distTip = null; }
        if (c) {
            const mid = [(site.lat + c.lat) / 2, (site.lon + c.lon) / 2];
            distTip = L.tooltip({ permanent: true, direction: "center", className: "sp-dist-tip", interactive: false })
                .setLatLng(mid).setContent("直線 " + fmtKm(c.dist)).addTo(map);
            if (markerByKey[key] && markerByKey[key].bringToFront) markerByKey[key].bringToFront();
        }
        renderCands();
        renderSelected();
        if (!opts.silent) writeHash();
    }

    // ── サイドバーの描画 ────────────────────────────────────
    function renderSite() {
        if (!site) return;
        const e = site.elev;
        const elev = e === undefined ? '<span class="sp-muted">読み込み中…</span>'
            : e ? fmtNum(e.h, 1) + ' m <small class="sp-muted">' + esc(DEM[e.src].label) + "</small>"
            : '<span class="sp-muted">データなし（海・湖など）</span>';
        const gsi = "https://maps.gsi.go.jp/#15/" + site.lat.toFixed(6) + "/" + site.lon.toFixed(6) + "/";
        const osm = "https://www.openstreetmap.org/#map=15/" + site.lat.toFixed(5) + "/" + site.lon.toFixed(5);
        $("sp-site").innerHTML = '<dl class="sp-dl">' +
            "<dt>緯度・経度</dt><dd>" + esc(fmtLL(site.lat, site.lon)) + "</dd>" +
            "<dt>標高</dt><dd>" + elev + "</dd>" +
            "<dt>エリアの目安</dt><dd>" + esc(areaText(region)) + ' <small class="sp-muted">' + esc(areaBasis(region)) + "</small></dd></dl>" +
            '<p class="sp-links"><a href="' + gsi + '" target="_blank" rel="noopener">地理院地図で見る</a>' +
            '<a href="' + osm + '" target="_blank" rel="noopener">OpenStreetMap で見る</a></p>';
    }

    function areaBasis(a) {
        if (!a || !a.n) return "";
        return (a.codes.length > 1 ? "手がかりが割れていて決めきれない。" : "") + (a.basis === "op"
            ? "近くの変電所 " + a.n + " か所の運営者（OpenStreetMap）から推定"
            : "近くに運営者の分かる変電所が少ないため、AGJ の地域ラベル " + a.n + " か所から推定");
    }

    function cell(c, a) {
        if (!c) return '<td class="sp-none">—</td>';
        const flag = c.main ? "" : ' <span class="sp-flag" title="AGJ のモデルの中で本系統（最大の連結成分）につながっていない">本系統外</span>';
        const cost = a ? '<span class="sp-cost">' + esc(costText(costOf(c, a))) + "</span>" : "";
        return '<td><button type="button" class="sp-cell' + (c.key === selKey ? " on" : "") + '" data-key="' + c.key + '"' +
            (c.key === selKey ? ' aria-pressed="true"' : ' aria-pressed="false"') + ">" +
            '<span class="sp-cname">' + esc(c.type === "sub" ? cleanName(c.name) : c.name) + "</span>" +
            '<span class="sp-cdist">' + esc(fmtKm(c.dist)) + flag + "</span>" + cost + "</button></td>";
    }

    function renderCands() {
        if (!site) return;
        const a = costAssume();
        const rows = [];
        KV_CLASSES.forEach((cls) => {
            const s = cands.find((c) => c.cls === cls && c.type === "sub"), l = cands.find((c) => c.cls === cls && c.type === "line");
            if (!s && !l) return;
            rows.push("<tr><th>" + kvGlyph(cls) + " " + esc(kvText(cls)) + "</th>" + cell(s, a) + cell(l, a) + "</tr>");
        });
        let h = rows.length
            ? '<table class="sp-table"><thead><tr><th>電圧</th><th>変電所</th><th>送電線（線上の点）</th></tr></thead><tbody>' +
              rows.join("") + "</tbody></table>"
            : '<p class="sp-muted">' + NEAR_KM + " km 以内に系統がありません。</p>";
        if (far.length) h += '<p class="sp-note">' + NEAR_KM + " km より遠い電圧: " + far.map(kvText).join("・") + "</p>";
        if (a) h += '<p class="sp-assume-inline">費用は仮定: 直線 × ' + a.factor + " × " + a.unit + " 億円/km</p>";
        $("sp-cands").innerHTML = h;
    }

    function renderSelected() {
        const c = cands.find((x) => x.key === selKey);
        $("sp-sel-sec").hidden = !c;
        if (!c) return;
        const a = costAssume(), o = obsFor(c);
        $("sp-sel").innerHTML = '<p class="sp-sel-h">' + kvGlyph(c.cls) + " <b>" + esc(c.type === "sub" ? cleanName(c.name) : c.name) + "</b> " +
            '<span class="sp-muted">' + esc((c.type === "sub" ? "変電所" : "送電線の線上の点") + " ・ " + kvText(c.cls)) + "</span></p>" +
            '<dl class="sp-dl"><dt>直線距離</dt><dd>' + esc(fmtKm(c.dist)) + "</dd>" +
            "<dt>つながり</dt><dd>" + (c.main ? "本系統" : "本系統から切れている（AGJ のモデルの中で）") + "</dd>" +
            (a ? "<dt>費用（仮定）</dt><dd>" + esc(costText(costOf(c, a))) + "</dd>" : "") + "</dl>" +
            (o ? obsHtml(o) : "") +
            '<p class="sp-links"><button type="button" class="sp-linkbtn" id="sp-sel-card">詳しく（カード）</button></p>';
        $("sp-sel-card").addEventListener("click", () => AGJMap.showCard(map, candCard(c), markerByKey[c.key]));
        updateProfile(c);
    }

    // ── 標高(地理院の標高タイル) ────────────────────────────
    const tileCache = new Map();
    function getTile(name, z, x, y) {
        const k = name + "/" + z + "/" + x + "/" + y;
        if (tileCache.has(k)) return tileCache.get(k);
        const url = GSI + DEM[name].path + "/" + z + "/" + x + "/" + y + ".png";
        const p = fetch(url).then((r) => (r.ok ? r.blob() : null))   // 404 = その範囲にデータが無い(海など)
            .then((b) => (b ? decodePng(b) : null))
            .catch(() => null);
        tileCache.set(k, p);
        return p;
    }
    function decodePng(blob) {
        // 色の変換をさせない(標高は RGB の値そのものに入っている)
        return createImageBitmap(blob, { premultiplyAlpha: "none", colorSpaceConversion: "none" }).then((bmp) => {
            const cv = document.createElement("canvas");
            cv.width = 256; cv.height = 256;
            const ctx = cv.getContext("2d", { willReadFrequently: true });
            ctx.drawImage(bmp, 0, 0);
            if (bmp.close) bmp.close();
            return ctx.getImageData(0, 0, 256, 256).data;
        });
    }
    // 仕様(demtile.html): x = 2^16 R + 2^8 G + B。x < 2^23 なら h = x u、x = 2^23 は無効、x > 2^23 なら h = (x − 2^24) u、u = 0.01 m
    function demValue(d, ix, iy) {
        const i = (iy * 256 + ix) * 4;
        if (d[i + 3] === 0) return null;
        const x = d[i] * 65536 + d[i + 1] * 256 + d[i + 2];
        if (x === 8388608) return null;
        return (x < 8388608 ? x : x - 16777216) * 0.01;
    }
    function worldPx(lat, lon, z) {
        const n = 256 * Math.pow(2, z), s = Math.sin(lat * DEG);
        return [(lon + 180) / 360 * n, (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * n];
    }
    function elevAt(name, z, lat, lon) {
        const p = worldPx(lat, lon, z), tx = Math.floor(p[0] / 256), ty = Math.floor(p[1] / 256);
        return getTile(name, z, tx, ty).then((d) => (d ? demValue(d, Math.min(255, Math.floor(p[0] - tx * 256)), Math.min(255, Math.floor(p[1] - ty * 256))) : null));
    }
    // 点の標高: 細かい順に DEM5A → DEM5B → DEM10B(地理院地図と同じ考え方)
    function pointElevation(lat, lon) {
        const order = ["dem5a", "dem5b", "dem10b"];
        let i = 0;
        const next = () => {
            if (i >= order.length) return Promise.resolve(null);
            const name = order[i++];
            return elevAt(name, DEM[name].z, lat, lon).then((h) => (h == null ? next() : { h, src: name }));
        };
        return next();
    }
    // 断面: DEM10B を、点の間隔に見合うズームで読む(長い線ほど粗いズーム = 読むタイルの数を抑える)
    function computeProfile(a, b) {
        const dist = hav(a[0], a[1], b[0], b[1]);
        const n = dist < 0.02 ? 2 : PROFILE_N;
        const spacing = Math.max(1, dist * 1000 / (n - 1));
        let z = Math.ceil(Math.log2(156543.03 * Math.cos(a[0] * DEG) / spacing));
        z = Math.max(8, Math.min(14, z));
        const pts = [];
        for (let i = 0; i < n; i++) {
            const t = i / (n - 1);
            pts.push({ t, d: dist * t, lat: a[0] + (b[0] - a[0]) * t, lon: a[1] + (b[1] - a[1]) * t, h: null });
        }
        return Promise.all(pts.map((p) => elevAt("dem10b", z, p.lat, p.lon).then((h) => { p.h = h; })))
            .then(() => ({ dist, z, pts }));
    }

    const profKey = (c) => c.key + "@" + site.lat.toFixed(6) + "," + site.lon.toFixed(6);
    function updateProfile(c) {
        const key = profKey(c);
        if (profileState && profileState.key === key) { drawProfileSidebar(c); return; }
        const my = seq;
        $("sp-profile").innerHTML = '<p class="sp-muted">標高タイルを読み込み中…</p>';
        $("sp-profile-note").textContent = "";
        computeProfile([site.lat, site.lon], [c.lat, c.lon]).then((pr) => {
            if (my !== seq || selKey !== c.key) return;
            profileState = Object.assign({ key, target: c }, pr);
            drawProfileSidebar(c);
        });
    }

    function profileStats(pr) {
        const v = pr.pts.filter((p) => p.h != null);
        if (!v.length) return null;
        let hi = v[0], lo = v[0];
        v.forEach((p) => { if (p.h > hi.h) hi = p; if (p.h < lo.h) lo = p; });
        return { hi, lo, start: pr.pts[0].h, end: pr.pts[pr.pts.length - 1].h, na: pr.pts.length - v.length, n: pr.pts.length };
    }

    function profileNote(pr, c) {
        const s = profileStats(pr);
        if (!s) return "この直線の上には標高データがありません（海の上など）。";
        return "候補地 " + (s.start != null ? fmtNum(s.start) + " m" : "—") + " ・ 接続先 " + (s.end != null ? fmtNum(s.end) + " m" : "—") +
            " ・ 最高 " + fmtNum(s.hi.h) + " m（候補地から " + fmtKm(s.hi.d) + "）。" +
            "地理院の標高タイル DEM10B をズーム " + pr.z + " で " + s.n + " 点読んだ値" +
            (s.na ? "（うち " + s.na + " 点は海・湖などで標高なし）" : "") + "。直線の上の地形で、線を引く経路の地形ではありません。";
    }

    function drawProfileSidebar(c) {
        const pr = profileState;
        const host = $("sp-profile");
        const w = Math.max(280, host.clientWidth || 360);
        host.innerHTML = profileSvg(pr, w, 170, { target: c.type === "sub" ? cleanName(c.name) : c.name, hover: true });
        $("sp-profile-note").textContent = profileNote(pr, c);
        bindProfileHover(host.querySelector("svg"), pr);
    }

    // ── グラフ(SVG。系列は 1 本ずつなので凡例は付けず、見出しで名乗る) ─────────
    function niceStep(range, n) {
        const raw = range / n, p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
        return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p;
    }
    function ticks(lo, hi, n) {
        const st = niceStep(Math.max(hi - lo, 1e-9), n), out = [];
        for (let v = Math.ceil(lo / st) * st; v <= hi + 1e-9; v += st) out.push(+v.toFixed(6));
        return out;
    }

    function profileSvg(pr, W, H, opt) {
        const m = { l: 44, r: 12, t: 16, b: 30 };
        const pw = W - m.l - m.r, ph = H - m.t - m.b;
        const s = profileStats(pr);
        if (!s) return '<p class="sp-muted">この直線の上には標高データがありません。</p>';
        let lo = Math.min(0, s.lo.h), hi = s.hi.h;
        if (hi - lo < 20) hi = lo + 20;
        hi += (hi - lo) * 0.14;   // 最高点の注記の置き場
        const yt = ticks(lo, hi, 4);
        lo = Math.min(lo, yt[0]); hi = Math.max(hi, yt[yt.length - 1]);
        const X = (d) => m.l + (pr.dist > 0 ? d / pr.dist : 0) * pw, Y = (h) => m.t + (1 - (h - lo) / (hi - lo)) * ph;
        let line = "", area = "", seg = [];
        const flush = () => {
            if (seg.length > 1) {
                line += "M" + seg.map((p) => X(p.d).toFixed(1) + "," + Y(p.h).toFixed(1)).join("L");
                area += "M" + X(seg[0].d).toFixed(1) + "," + Y(lo).toFixed(1) + "L" + seg.map((p) => X(p.d).toFixed(1) + "," + Y(p.h).toFixed(1)).join("L") +
                    "L" + X(seg[seg.length - 1].d).toFixed(1) + "," + Y(lo).toFixed(1) + "Z";
            }
            seg = [];
        };
        pr.pts.forEach((p) => { if (p.h == null) flush(); else seg.push(p); });
        flush();
        const xt = ticks(0, pr.dist, 4);
        let g = "";
        yt.forEach((v) => {
            g += '<line class="grid" x1="' + m.l + '" x2="' + (W - m.r) + '" y1="' + Y(v).toFixed(1) + '" y2="' + Y(v).toFixed(1) + '"/>' +
                 '<text class="tick" x="' + (m.l - 6) + '" y="' + (Y(v) + 3.5).toFixed(1) + '" text-anchor="end">' + fmtTick(v) + "</text>";
        });
        xt.forEach((v) => {
            g += '<text class="tick" x="' + X(v).toFixed(1) + '" y="' + (H - m.b + 14) + '" text-anchor="middle">' + fmtTick(v) + "</text>";
        });
        const unitY = '<text class="unit" x="' + (m.l - 6) + '" y="' + (m.t - 2) + '" text-anchor="end">m</text>';
        const unitX = '<text class="unit" x="' + (W - m.r) + '" y="' + (H - 3) + '" text-anchor="end">km</text>';
        const ends = '<text class="end" x="' + m.l + '" y="' + (H - 3) + '">候補地</text>' +
            '<text class="end" x="' + (m.l + pw / 2) + '" y="' + (H - 3) + '" text-anchor="middle">' + esc(String(opt.target || "").slice(0, 18)) + " まで</text>";
        const hiMark = '<circle class="hi" cx="' + X(s.hi.d).toFixed(1) + '" cy="' + Y(s.hi.h).toFixed(1) + '" r="3"/>' +
            '<text class="lab" x="' + Math.min(W - m.r - 2, Math.max(m.l + 2, X(s.hi.d))).toFixed(1) + '" y="' + (Y(s.hi.h) - 6).toFixed(1) +
            '" text-anchor="' + (X(s.hi.d) > W - 60 ? "end" : X(s.hi.d) < m.l + 40 ? "start" : "middle") + '">最高 ' + fmtNum(s.hi.h) + " m</text>";
        const hover = opt.hover ? '<line class="xh" x1="0" x2="0" y1="' + m.t + '" y2="' + (m.t + ph) + '" visibility="hidden"/>' +
            '<circle class="xd" r="3.5" cx="0" cy="0" visibility="hidden"/>' +
            '<rect class="hit" x="' + m.l + '" y="' + m.t + '" width="' + pw + '" height="' + ph + '"/>' : "";
        return '<svg class="sp-svg sp-prof" viewBox="0 0 ' + W + " " + H + '" width="' + W + '" height="' + H + '" role="img" aria-label="候補地から接続先までの直線上の標高の断面"' +
            ' data-ml="' + m.l + '" data-pw="' + pw + '" data-mt="' + m.t + '" data-ph="' + ph + '" data-lo="' + lo + '" data-hi="' + hi + '">' +
            g + '<line class="axis" x1="' + m.l + '" x2="' + (W - m.r) + '" y1="' + (m.t + ph) + '" y2="' + (m.t + ph) + '"/>' +
            '<path class="area" d="' + area + '"/><path class="line" d="' + line + '"/>' + hiMark + unitY + unitX + ends + hover + "</svg>";
    }

    function bindProfileHover(svg, pr) {
        if (!svg) return;
        const hit = svg.querySelector(".hit"), xh = svg.querySelector(".xh"), xd = svg.querySelector(".xd");
        const ml = +svg.dataset.ml, pw = +svg.dataset.pw, mt = +svg.dataset.mt, ph = +svg.dataset.ph, lo = +svg.dataset.lo, hi = +svg.dataset.hi;
        const tip = $("sp-tip");
        const hide = () => {
            xh.setAttribute("visibility", "hidden"); xd.setAttribute("visibility", "hidden"); tip.hidden = true;
            if (hoverMarker) { map.removeLayer(hoverMarker); hoverMarker = null; }
        };
        hit.addEventListener("mousemove", (ev) => {
            const r = svg.getBoundingClientRect(), sx = (ev.clientX - r.left) * (svg.viewBox.baseVal.width / r.width);
            const t = Math.max(0, Math.min(1, (sx - ml) / pw)), i = Math.round(t * (pr.pts.length - 1)), p = pr.pts[i];
            const x = ml + (i / (pr.pts.length - 1)) * pw;
            xh.setAttribute("x1", x); xh.setAttribute("x2", x); xh.setAttribute("visibility", "visible");
            if (p.h != null) {
                xd.setAttribute("cx", x); xd.setAttribute("cy", mt + (1 - (p.h - lo) / (hi - lo)) * ph); xd.setAttribute("visibility", "visible");
            } else xd.setAttribute("visibility", "hidden");
            tip.innerHTML = "候補地から " + esc(fmtKm(p.d)) + "<br><b>" + (p.h != null ? fmtNum(p.h, 1) + " m" : "標高なし") + "</b>";
            tip.hidden = false;
            tip.style.left = Math.min(window.innerWidth - 150, ev.clientX + 12) + "px";
            tip.style.top = (ev.clientY - 44) + "px";
            const ll = [p.lat, p.lon];
            if (!hoverMarker) hoverMarker = L.circleMarker(ll, { renderer: AGJMap.renderer(map), interactive: false, radius: 5, color: "#ffffff", weight: 2, fillColor: "#0d1117", fillOpacity: 1 }).addTo(map);
            else hoverMarker.setLatLng(ll);
        });
        hit.addEventListener("mouseleave", hide);
    }

    function barSvg(vals, W, H, opt) {
        const m = { l: 36, r: 6, t: 8, b: 20 };
        const pw = W - m.l - m.r, ph = H - m.t - m.b;
        const mx = Math.max.apply(null, vals.map((v) => (v == null ? 0 : v)).concat([1e-9]));
        const yt = ticks(0, mx, 3), top = Math.max(mx, yt[yt.length - 1]);
        const bw = pw / vals.length, gap = Math.max(2, bw * 0.22);
        let g = "";
        yt.forEach((v) => {
            const y = m.t + (1 - v / top) * ph;
            g += '<line class="grid" x1="' + m.l + '" x2="' + (W - m.r) + '" y1="' + y.toFixed(1) + '" y2="' + y.toFixed(1) + '"/>' +
                 '<text class="tick" x="' + (m.l - 5) + '" y="' + (y + 3.5).toFixed(1) + '" text-anchor="end">' + fmtTick(v) + "</text>";
        });
        vals.forEach((v, i) => {
            const x = m.l + i * bw + gap / 2, h = v == null ? 0 : (v / top) * ph;
            g += '<rect class="bar" data-i="' + i + '" x="' + x.toFixed(1) + '" y="' + (m.t + ph - h).toFixed(1) + '" width="' + (bw - gap).toFixed(1) + '" height="' + h.toFixed(1) + '"/>' +
                 '<rect class="bhit" data-i="' + i + '" x="' + (m.l + i * bw).toFixed(1) + '" y="' + m.t + '" width="' + bw.toFixed(1) + '" height="' + ph + '"/>' +
                 '<text class="tick" x="' + (m.l + i * bw + bw / 2).toFixed(1) + '" y="' + (H - 6) + '" text-anchor="middle">' + (i + 1) + "</text>";
        });
        return '<svg class="sp-svg sp-bars" viewBox="0 0 ' + W + " " + H + '" width="' + W + '" height="' + H + '" role="img" aria-label="' + esc(opt.title + "（" + opt.unit + "）") + '">' + g +
            '<line class="axis" x1="' + m.l + '" x2="' + (W - m.r) + '" y1="' + (m.t + ph) + '" y2="' + (m.t + ph) + '"/></svg>';
    }

    function bindBarHover(host, vals, opt) {
        const tip = $("sp-tip");
        host.querySelectorAll(".bhit").forEach((b) => {
            b.addEventListener("mousemove", (ev) => {
                const i = +b.dataset.i, v = vals[i];
                tip.innerHTML = (i + 1) + "月<br><b>" + (v == null ? "—" : fmtNum(v, opt.digits) + " " + esc(opt.unit)) + "</b>";
                tip.hidden = false;
                tip.style.left = Math.min(window.innerWidth - 150, ev.clientX + 12) + "px";
                tip.style.top = (ev.clientY - 44) + "px";
            });
            b.addEventListener("mouseenter", () => { const r = host.querySelector('.bar[data-i="' + b.dataset.i + '"]'); if (r) r.classList.add("on"); });
            b.addEventListener("mouseleave", () => { tip.hidden = true; host.querySelectorAll(".bar.on").forEach((x) => x.classList.remove("on")); });
        });
    }

    // ── 気象(Open-Meteo・ERA5) ─────────────────────────────
    const wxMem = {};
    let wxTimer = null, wxLast = 0;
    function wxYear() {
        const d = new Date();   // ERA5 は 5 日遅れで入る。年明けすぐは前々年にする
        return d.getMonth() === 0 && d.getDate() < 15 ? d.getFullYear() - 2 : d.getFullYear() - 1;
    }
    function scheduleWeather() {
        $("sp-wx-sec").hidden = false;
        clearTimeout(wxTimer);
        wxTimer = setTimeout(loadWeather, WX_DEBOUNCE_MS);
    }
    function loadWeather() {
        if (!site) return;
        // ERA5 の格子(0.25°)に丸めて問い合わせる。同じ格子なら問い合わせ直さない
        const glat = Math.round(site.lat * 4) / 4, glon = Math.round(site.lon * 4) / 4, year = wxYear();
        const key = "agj_sp_wx_" + glat.toFixed(2) + "_" + glon.toFixed(2) + "_" + year;
        let hit = wxMem[key];
        if (!hit) { try { hit = JSON.parse(sessionStorage.getItem(key) || "null"); } catch (e) { hit = null; } }
        if (hit) { wxMem[key] = hit; weather = hit; renderWeather(); return; }
        const wait = Math.max(0, wxLast + 1000 - Date.now());
        if (wait) { wxTimer = setTimeout(loadWeather, wait); return; }
        wxLast = Date.now();
        weather = null;
        $("sp-wx-year").textContent = year + " 年・ERA5 再解析";
        $("sp-wx").innerHTML = '<p class="sp-muted">Open-Meteo から取得中…</p>';
        const url = OPEN_METEO + "?latitude=" + glat + "&longitude=" + glon + "&start_date=" + year + "-01-01&end_date=" + year + "-12-31" +
            "&daily=shortwave_radiation_sum,temperature_2m_mean&hourly=wind_speed_10m,wind_speed_100m&models=era5" +
            "&timezone=Asia%2FTokyo&wind_speed_unit=ms";
        const my = seq;
        getJSON(url).then((d) => {
            const s = summarizeWeather(d, year, glat, glon);
            wxMem[key] = s;
            try { sessionStorage.setItem(key, JSON.stringify(s)); } catch (e) { /* 保存できない環境 */ }
            if (my !== seq) return;
            weather = s;
            renderWeather();
        }).catch((err) => {
            if (my !== seq) return;
            $("sp-wx").innerHTML = '<p class="sp-muted">気象データを取得できませんでした（時間をおいて選び直してください）。</p>';
            console.warn("[site_plan] Open-Meteo:", err && err.message);
        });
    }
    function summarizeWeather(d, year, glat, glon) {
        const dl = d.daily || {}, hr = d.hourly || {};
        const sw = new Array(12).fill(0), swN = new Array(12).fill(0), w10 = new Array(12).fill(0), w100 = new Array(12).fill(0), wN = new Array(12).fill(0);
        let swSum = 0, swDays = 0, tSum = 0, tN = 0, a10 = 0, a100 = 0, aN = 0;
        (dl.time || []).forEach((t, i) => {
            const mo = +t.slice(5, 7) - 1, v = dl.shortwave_radiation_sum ? dl.shortwave_radiation_sum[i] : null;
            if (v != null) { sw[mo] += v / 3.6; swN[mo]++; swSum += v / 3.6; swDays++; }   // MJ/m² → kWh/m²
            const tv = dl.temperature_2m_mean ? dl.temperature_2m_mean[i] : null;
            if (tv != null) { tSum += tv; tN++; }
        });
        (hr.time || []).forEach((t, i) => {
            const mo = +t.slice(5, 7) - 1, u = hr.wind_speed_10m[i], v = hr.wind_speed_100m[i];
            if (u != null && v != null) { w10[mo] += u; w100[mo] += v; wN[mo]++; a10 += u; a100 += v; aN++; }
        });
        return {
            year, glat, glon, lat: d.latitude, lon: d.longitude, elevation: d.elevation,
            swYear: swDays ? swSum * (365 / swDays) : null, swDaily: swDays ? swSum / swDays : null, swDays,
            swMonth: sw.map((v, i) => (swN[i] ? v : null)),
            w10: aN ? a10 / aN : null, w100: aN ? a100 / aN : null, hours: aN,
            w100Month: w100.map((v, i) => (wN[i] ? v / wN[i] : null)),
            t: tN ? tSum / tN : null,
        };
    }
    function weatherTable(s) {
        return '<table class="sp-kvt"><tbody>' +
            "<tr><th>日射量（水平面全天）</th><td><b>" + fmtNum(s.swYear) + "</b> kWh/m²・年<br><small>1 日平均 " + fmtNum(s.swDaily, 2) + " kWh/m²</small></td></tr>" +
            "<tr><th>風速の年平均</th><td>高さ 10 m <b>" + fmtNum(s.w10, 1) + "</b> m/s ・ 100 m <b>" + fmtNum(s.w100, 1) + "</b> m/s</td></tr>" +
            "<tr><th>気温の年平均</th><td>" + fmtNum(s.t, 1) + " °C</td></tr></tbody></table>";
    }
    function weatherNote(s) {
        return "ERA5 の格子（0.25°・約 25 km）の値で、この地点の観測ではありません。格子点 " + s.lat.toFixed(2) + ", " + s.lon.toFixed(2) +
            "・期間 " + s.year + " 年 1〜12 月（" + s.swDays + " 日・" + s.hours + " 時間）。日射は日合計（MJ/m²）を kWh/m² に直して足し、風速は 1 時間値を平均しました。";
    }
    function renderWeather() {
        const s = weather;
        if (!s) return;
        $("sp-wx-year").textContent = s.year + " 年・ERA5 再解析";
        const W = Math.max(280, ($("sp-wx").clientWidth || 360));
        $("sp-wx").innerHTML = weatherTable(s) +
            '<div class="sp-sub">月ごとの日射量 <span class="ov-hint">kWh/m²</span></div><div class="sp-chart" id="sp-wx-sw">' +
            barSvg(s.swMonth, W, 120, { unit: "kWh/m²", digits: 0, title: "月ごとの日射量" }) + "</div>" +
            '<div class="sp-sub">月ごとの風速（高さ 100 m） <span class="ov-hint">m/s</span></div><div class="sp-chart" id="sp-wx-w">' +
            barSvg(s.w100Month, W, 120, { unit: "m/s", digits: 1, title: "月ごとの風速（高さ 100 m）" }) + "</div>" +
            '<p class="sp-note">' + esc(weatherNote(s)) + ' 設計には現地の観測や NEDO の<a href="https://www.nedo.go.jp/library/nissharyou.html" target="_blank" rel="noopener">日射に関するデータベース</a>・風況マップを使ってください。</p>' +
            '<p class="sp-note"><a href="https://open-meteo.com/" target="_blank" rel="noopener">Weather data by Open-Meteo.com</a>（CC BY 4.0）。Contains modified Copernicus Climate Change Service information ' + s.year + ".</p>";
        bindBarHover($("sp-wx-sw"), s.swMonth, { unit: "kWh/m²", digits: 0 });
        bindBarHover($("sp-wx-w"), s.w100Month, { unit: "m/s", digits: 1 });
    }

    // ── 空き容量(各社の公表ページへ) ──────────────────────
    function renderCapacity() {
        $("sp-cap-sec").hidden = false;
        const us = (region ? region.codes : []).filter((k) => UTILS[k]);
        $("sp-cap").innerHTML =
            "<p>空き容量は各社が公表しています。AGJ は数値を載せません（転載を認めていない事業者があるため）。</p>" +
            us.map((k) => '<p class="sp-cap-main">' + esc(REGION_JA[k]) + "エリア: <b>" + esc(UTILS[k][0]) + '</b><br><a href="' + UTILS[k][1] +
                '" target="_blank" rel="noopener">系統情報の公表のページ ↗</a></p>').join("") +
            '<details class="sp-details"><summary>10 社の公表ページ</summary><ul class="sp-list">' +
            REGION_ORDER.map((k) => '<li><a href="' + UTILS[k][1] + '" target="_blank" rel="noopener">' + esc(UTILS[k][0]) + "</a></li>").join("") +
            '</ul></details><p class="sp-note">入口は AGJ の取得台帳（config/system_disclosure.yaml）から。エリアは近くの変電所の運営者（OpenStreetMap の operator タグ）から推した目安で（足りなければ AGJ の地域ラベル）、供給区域の境界の近くでは違うことがあります。</p>';
    }

    // ── 地名・緯度経度の入力 ────────────────────────────────
    function parseLatLon(raw) {
        const s = String(raw || "").normalize("NFKC").replace(/[、]/g, ",").trim();
        const m = s.match(/^(?:北緯|N)?\s*(-?\d+(?:\.\d+)?)\s*°?\s*[,\s/]\s*(?:東経|E)?\s*(-?\d+(?:\.\d+)?)\s*°?$/i);
        if (!m) return null;
        const a = +m[1], b = +m[2];
        if (inJapan(a, b)) return { lat: a, lon: b };
        if (inJapan(b, a)) return { lat: b, lon: a };
        return { error: true };
    }
    const geoCache = {};
    let geoLast = 0, geoTimer = null, geoSeq = 0;
    function onSearch(ev) {
        ev.preventDefault();
        const q = $("sp-q").value.trim();
        if (!q) return;
        const ll = parseLatLon(q);
        if (ll && ll.error) { showGeo('<p class="sp-muted">日本の範囲（北緯 20〜46 度・東経 122〜154 度）の外です。</p>'); return; }
        if (ll) { showGeo(""); setSite(ll.lat, ll.lon, { fly: true }); return; }
        if (q.length < 2) return;
        geocode(q);
    }
    function showGeo(h) { const el = $("sp-geo"); el.innerHTML = h; el.hidden = !h; }
    function geocode(q) {
        if (geoCache[q]) { geoResults(q, geoCache[q]); return; }
        const my = ++geoSeq;
        showGeo('<p class="sp-muted">地名を検索中…（OpenStreetMap Nominatim）</p>');
        clearTimeout(geoTimer);
        // 押し続けても 1 秒に 1 回まで(Nominatim の利用方針)
        geoTimer = setTimeout(() => {
            geoLast = Date.now();
            getJSON(NOMINATIM + "?format=jsonv2&countrycodes=jp&limit=5&accept-language=ja&q=" + encodeURIComponent(q)).then((d) => {
                const rs = (Array.isArray(d) ? d : []).map((x) => ({ label: x.display_name || q, lat: parseFloat(x.lat), lon: parseFloat(x.lon) }))
                    .filter((r) => isFinite(r.lat) && isFinite(r.lon));
                geoCache[q] = rs;
                if (my === geoSeq) geoResults(q, rs);
            }).catch(() => { if (my === geoSeq) showGeo('<p class="sp-muted">地名を検索できませんでした（時間をおいて Enter）。</p>'); });
        }, Math.max(0, geoLast + GEO_GAP_MS - Date.now()));
    }
    function geoResults(q, rs) {
        if (!rs.length) { showGeo('<p class="sp-muted">「' + esc(q) + "」は見つかりませんでした。</p>"); return; }
        showGeo('<div class="sp-geo-h">地名の候補（OpenStreetMap Nominatim）</div>' + rs.map((r, i) =>
            '<button type="button" class="sp-geo-r' + (i === 0 ? " on" : "") + '" data-i="' + i + '">' + esc(r.label.split(",").slice(0, 3).join(",")) + "</button>").join(""));
        $("sp-geo").querySelectorAll(".sp-geo-r").forEach((b) => b.addEventListener("click", () => {
            $("sp-geo").querySelectorAll(".sp-geo-r").forEach((x) => x.classList.toggle("on", x === b));
            const r = rs[+b.dataset.i];
            setSite(r.lat, r.lon, { fly: true });
        }));
        setSite(rs[0].lat, rs[0].lon, { fly: true });
    }

    // ── URL の状態 ──────────────────────────────────────────
    function readHash() {
        const q = new URLSearchParams(location.hash.replace(/^#/, ""));
        const lat = parseFloat(q.get("lat")), lon = parseFloat(q.get("lon"));
        return isFinite(lat) && isFinite(lon) ? { lat, lon, sel: q.get("sel") } : null;
    }
    function writeHash() {
        if (!site) return;
        const h = "#lat=" + site.lat.toFixed(5) + "&lon=" + site.lon.toFixed(5) + (selKey ? "&sel=" + selKey : "");
        if (h !== location.hash) history.replaceState(null, "", h);
        lastHash = location.hash;
    }

    // ── レポート(印刷用) ────────────────────────────────────
    function reportCands() {
        const out = [];
        KV_CLASSES.forEach((cls) => ["sub", "line"].forEach((t) => {
            const c = cands.find((x) => x.cls === cls && x.type === t);
            if (c) out.push(c);
        }));
        return out;
    }

    // 地図の図: 地理院タイル(淡色)を <img> で並べ、系統と候補を SVG で重ねる(印刷でも崩れない)
    function reportMap(rc, W, H) {
        const sel = rc.find((c) => c.key === selKey);
        const near = rc.slice().sort((a, b) => a.dist - b.dist).slice(0, 5);
        if (sel && near.indexOf(sel) < 0) near.push(sel);
        const pts = [[site.lat, site.lon]].concat(near.map((c) => [c.lat, c.lon]));
        // 全部が入るいちばん細かいズーム(16〜5)
        let z = 16, px = null;
        for (; z > 5; z--) {
            px = pts.map((p) => worldPx(p[0], p[1], z));
            const xs = px.map((p) => p[0]), ys = px.map((p) => p[1]);
            if (Math.max.apply(null, xs) - Math.min.apply(null, xs) <= W - 90 && Math.max.apply(null, ys) - Math.min.apply(null, ys) <= H - 90) break;
        }
        if (z === 5) px = pts.map((p) => worldPx(p[0], p[1], z));
        const xs = px.map((p) => p[0]), ys = px.map((p) => p[1]);
        const ox = (Math.max.apply(null, xs) + Math.min.apply(null, xs)) / 2 - W / 2, oy = (Math.max.apply(null, ys) + Math.min.apply(null, ys)) / 2 - H / 2;
        const P = (lat, lon) => { const p = worldPx(lat, lon, z); return [p[0] - ox, p[1] - oy]; };
        let imgs = "";
        for (let tx = Math.floor(ox / 256); tx <= Math.floor((ox + W) / 256); tx++) {
            for (let ty = Math.floor(oy / 256); ty <= Math.floor((oy + H) / 256); ty++) {
                imgs += '<img alt="" src="' + GSI + "pale/" + z + "/" + tx + "/" + ty + '.png" style="left:' + (tx * 256 - ox).toFixed(0) + "px;top:" + (ty * 256 - oy).toFixed(0) + 'px">';
            }
        }
        // 画面の範囲(経緯度)
        const n = 256 * Math.pow(2, z), toLon = (x) => x / n * 360 - 180, toLat = (y) => Math.atan(Math.sinh(Math.PI * (1 - 2 * y / n))) / DEG;
        const w = toLon(ox), e = toLon(ox + W), nlat = toLat(oy), slat = toLat(oy + H);
        let net = "";
        lineMeta.forEach((m) => {
            const b = m.bbox;
            if (b[2] < w || b[0] > e || b[3] < slat || b[1] > nlat) return;
            const d = m.coords.map((c) => { const p = P(c[1], c[0]); return p[0].toFixed(1) + "," + p[1].toFixed(1); }).join(" ");
            net += '<polyline points="' + d + '" stroke="' + colorOf(m.cls) + '" stroke-width="' + (m.cls >= 275 ? 2.2 : m.cls >= 154 ? 1.6 : 1.1) + '"' + (m.main ? "" : ' stroke-dasharray="3 2"') + "/>";
        });
        let subs = "";
        subMeta.forEach((m) => {
            if (m.lon < w || m.lon > e || m.lat < slat || m.lat > nlat) return;
            const p = P(m.lat, m.lon);
            subs += '<circle cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="2.2" fill="' + colorOf(m.cls) + '"/>';
        });
        const sp = P(site.lat, site.lon);
        let conn = "", marks = "";
        const labels = [];   // 近い場所(1 つの変電所の別の電圧など)の番号は 1 つの注記にまとめる
        rc.forEach((c, i) => {
            const p = P(c.lat, c.lon), on = c.key === selKey;
            conn += '<line x1="' + sp[0].toFixed(1) + '" y1="' + sp[1].toFixed(1) + '" x2="' + p[0].toFixed(1) + '" y2="' + p[1].toFixed(1) + '" stroke="' + colorOf(c.cls) +
                '" stroke-width="' + (on ? 2.6 : 1.3) + '"' + (on ? "" : ' stroke-dasharray="4 4"') + "/>";
            marks += c.type === "sub"
                ? '<circle cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="4.5" fill="' + colorOf(c.cls) + '" stroke="#fff" stroke-width="1.2"/>'
                : '<circle cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="4" fill="#fff" stroke="' + colorOf(c.cls) + '" stroke-width="2"/>';
            const near = labels.find((g) => Math.hypot(g.p[0] - p[0], g.p[1] - p[1]) < 14);
            if (near) near.n.push(i + 1); else labels.push({ p, n: [i + 1] });
        });
        labels.forEach((g) => {
            marks += '<text class="num" x="' + (g.p[0] + 7).toFixed(1) + '" y="' + (g.p[1] - 6).toFixed(1) + '">' + g.n.join("・") + "</text>";
        });
        marks += '<circle cx="' + sp[0].toFixed(1) + '" cy="' + sp[1].toFixed(1) + '" r="7" fill="#111" stroke="#fff" stroke-width="2.5"/>' +
            '<text class="site" x="' + (sp[0] + 10).toFixed(1) + '" y="' + (sp[1] + 4).toFixed(1) + '">候補地</text>';
        // 縮尺
        const mpp = 156543.03 * Math.cos(site.lat * DEG) / Math.pow(2, z);
        let len = niceStep(mpp * 120, 1);
        const bar = len / mpp;
        const scale = '<g class="scale"><rect x="10" y="' + (H - 26) + '" width="' + (bar + 16) + '" height="20" fill="#fff" opacity=".85"/>' +
            '<line x1="18" x2="' + (18 + bar).toFixed(1) + '" y1="' + (H - 12) + '" y2="' + (H - 12) + '" stroke="#111" stroke-width="2"/>' +
            '<text x="18" y="' + (H - 15) + '">' + (len >= 1000 ? fmtNum(len / 1000) + " km" : fmtNum(len) + " m") + "</text></g>";
        const svg = '<svg class="sp-rep-svg" viewBox="0 0 ' + W + " " + H + '" width="' + W + '" height="' + H + '">' +
            '<g fill="none" stroke-linecap="round" opacity=".9">' + net + "</g>" + '<g opacity=".9">' + subs + "</g>" + conn + marks + scale + "</svg>";
        return '<div class="sp-rep-map" style="width:' + W + "px;height:" + H + 'px">' + imgs + svg + "</div>";
    }

    function buildReport() {
        if (!site) return Promise.resolve();
        const rc = reportCands(), a = costAssume(), sel = rc.find((c) => c.key === selKey);
        const now = new Date();
        const stamp = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-" + String(now.getDate()).padStart(2, "0") +
            " " + String(now.getHours()).padStart(2, "0") + ":" + String(now.getMinutes()).padStart(2, "0");
        const ver = dashInfo ? "All-Japan-Grid v" + dashInfo.version + (dashInfo.model && dashInfo.model.model_version ? "・正典 " + dashInfo.model.model_version : "") : "All-Japan-Grid";
        const e = site.elev;
        const W = 680;
        const rows = rc.map((c, i) => {
            const o = obsFor(c);
            return "<tr" + (c.key === selKey ? ' class="on"' : "") + "><td>" + (i + 1) + "</td><td>" + (c.type === "sub" ? "変電所" : "送電線（線上の点）") + "</td><td>" +
                esc(kvText(c.cls)) + "</td><td>" + esc(c.type === "sub" ? cleanName(c.name) : c.name) + (o ? "<br><small>潮流実績 p95 " + fmtNum(o.p95) + " MW（2024 年度・公表の線名「" + esc(o.key) + "」と名前で照合）</small>" : "") +
                '</td><td class="r">' + esc(fmtKm(c.dist)) + "</td><td>" + (c.main ? "本系統" : "本系統外") + "</td>" +
                (a ? '<td class="r">' + esc(fmtNum(costOf(c, a), 1)) + "</td>" : "") + "</tr>";
        }).join("");
        const wx = weather;
        const us = (region ? region.codes : []).filter((k) => UTILS[k]);
        let h = '<header class="sp-rep-head"><h1>接続の計画とサイト分析</h1>' +
            "<p>" + esc(stamp) + " 作成 ・ " + esc(ver) + "</p>" +
            '<p class="sp-rep-url">' + esc(location.href) + "</p></header>" +
            '<p class="sp-rep-warn">AGJ は OpenStreetMap を機械処理したモデルで、電力会社の公式情報ではありません。距離はすべて直線で、実際の経路ではありません。接続の可否・空き容量・工事費は分かりません。</p>' +
            '<section class="sp-rep-sec"><h2>1. 候補地</h2><table class="sp-rep-kv"><tbody>' +
            "<tr><th>緯度・経度</th><td>" + esc(fmtLL(site.lat, site.lon)) + "</td></tr>" +
            "<tr><th>標高</th><td>" + (e ? fmtNum(e.h, 1) + " m（地理院の標高タイル " + esc(DEM[e.src].label) + "）" : "データなし") + "</td></tr>" +
            "<tr><th>エリアの目安</th><td>" + esc(areaText(region)) + "（" + esc(areaBasis(region)) + "）</td></tr></tbody></table></section>" +
            '<section class="sp-rep-sec sp-rep-split"><h2>2. 近い系統</h2><figure class="sp-rep-fig">' + reportMap(rc, W, 400) +
            '<figcaption class="sp-rep-cap">図 1. 候補地と、電圧ごとに最寄りの変電所（塗りの丸）・送電線の線上のいちばん近い点（白抜きの丸）。番号は表 1。太い線が選んだ接続先。点線の送電線は AGJ のモデルで本系統から切れているもの。背景: 地理院タイル（淡色地図・国土地理院）。系統: All-Japan-Grid（&copy; OpenStreetMap contributors）。</figcaption></figure>' +
            '<table class="sp-rep-t"><thead><tr><th>#</th><th>種類</th><th>電圧</th><th>名称</th><th class="r">直線距離</th><th>つながり</th>' + (a ? '<th class="r">費用（仮定・億円）</th>' : "") + "</tr></thead><tbody>" +
            rows + "</tbody></table>" +
            '<p class="sp-rep-cap">表 1. 候補地から ' + NEAR_KM + " km 以内に最寄りがある電圧ごとの、最寄りの変電所と送電線。距離は大円距離（直線）。" +
            (far.length ? NEAR_KM + " km より遠い電圧: " + esc(far.map(kvText).join("・")) + "。" : "") + "「本系統外」は AGJ のモデルの中で最大の連結成分につながっていないもの（実際の設備の状態ではありません）。</p>" +
            (a ? '<p class="sp-rep-assume">仮定: 費用 ＝ 直線距離 × 倍率 ' + a.factor + " × 単価 " + a.unit + " 億円/km。単価は利用者が入れた値で、AGJ の値ではありません。倍率の既定 1.12 は AGJ の正典の線 246 本の「線形の長さ ÷ 端点間の直線距離」の中央値（docs/reports/impedance_validation_2026-08-19.md §10）。</p>" : "") +
            "</section>";
        if (sel && profileState && profileState.key === profKey(sel)) {
            h += '<section class="sp-rep-sec"><h2>3. 標高の断面（' + esc(sel.type === "sub" ? cleanName(sel.name) : sel.name) + " まで）</h2>" +
                profileSvg(profileState, W, 200, { target: sel.type === "sub" ? cleanName(sel.name) : sel.name }) +
                '<p class="sp-rep-cap">図 2. ' + esc(profileNote(profileState, sel)) + "</p></section>";
        }
        if (wx) {
            h += '<section class="sp-rep-sec sp-rep-split"><h2>4. 気象（' + wx.year + " 年・ERA5 再解析）</h2>" + weatherTable(wx) +
                '<div class="sp-rep-two"><div><div class="sp-rep-sub">月ごとの日射量（kWh/m²）</div>' + barSvg(wx.swMonth, 330, 130, { unit: "kWh/m²", digits: 0, title: "月ごとの日射量" }) + "</div>" +
                '<div><div class="sp-rep-sub">月ごとの風速・高さ 100 m（m/s）</div>' + barSvg(wx.w100Month, 330, 130, { unit: "m/s", digits: 1, title: "月ごとの風速" }) + "</div></div>" +
                '<table class="sp-rep-t sp-rep-month"><thead><tr><th>月</th>' + wx.swMonth.map((v, i) => "<th>" + (i + 1) + "</th>").join("") + "</tr></thead><tbody>" +
                "<tr><th>日射 kWh/m²</th>" + wx.swMonth.map((v) => '<td class="r">' + fmtNum(v) + "</td>").join("") + "</tr>" +
                "<tr><th>風速 100 m</th>" + wx.w100Month.map((v) => '<td class="r">' + fmtNum(v, 1) + "</td>").join("") + "</tr></tbody></table>" +
                '<p class="sp-rep-cap">' + esc(weatherNote(wx)) + " Weather data by Open-Meteo.com（CC BY 4.0, https://open-meteo.com/）。Contains modified Copernicus Climate Change Service information " + wx.year + ". 欧州委員会と ECMWF はこの情報の利用に責任を負いません。</p></section>";
        }
        h += '<section class="sp-rep-sec"><h2>5. 空き容量</h2><p>AGJ は各社の空き容量の数値を載せません（転載を認めていない事業者があるため）。' +
            us.map((k) => esc(REGION_JA[k]) + "エリアは " + esc(UTILS[k][0]) + " の系統情報の公表を見てください: " + esc(UTILS[k][1]) + "。").join("") + "</p></section>" +
            '<section class="sp-rep-sec sp-rep-split"><h2>出典</h2><ul class="sp-rep-src">' +
            "<li>系統: All-Japan-Grid の正典（docs/data/built）から書いた地図データ data/map/subs_all.geojson・lines_all.geojson。元は OpenStreetMap（ODbL, &copy; OpenStreetMap contributors）。</li>" +
            "<li>標高: 国土地理院 地理院タイル（標高タイル DEM5A・DEM5B・DEM10B）https://maps.gsi.go.jp/development/ichiran.html</li>" +
            "<li>背景地図: 国土地理院 地理院タイル（淡色地図）</li>" +
            (wx ? "<li>気象: Open-Meteo Historical Weather API（ERA5）。年・月の集計はこのページで行った。</li>" : "") +
            (rc.some(obsFor) ? "<li>潮流実績: 各一般送配電事業者の系統情報の公表（2024 年度）の年統計を AGJ が集計した値（data/flow_map/obs_local.json）。線名だけで照合。</li>" : "") +
            "</ul><p class=\"sp-rep-cap\">このレポートは接続の可否・運用の可否の判定には使えません。検討は各社の系統情報の公表と事前相談・接続検討で行ってください。</p></section>";
        $("sp-rep-page").innerHTML = h;
        const imgs = Array.from($("sp-rep-page").querySelectorAll("img"));
        return Promise.all(imgs.map((im) => (im.decode ? im.decode().catch(() => {}) : Promise.resolve())));
    }

    function openReport() {
        $("sp-report").hidden = false;
        document.body.classList.add("sp-report-open");
        $("sp-rep-page").innerHTML = '<p class="sp-muted">レポートを組み立て中…</p>';
        return buildReport();
    }
    function closeReport() {
        $("sp-report").hidden = true;
        document.body.classList.remove("sp-report-open");
    }

    // ── 起動 ────────────────────────────────────────────────
    function init() {
        map = AGJMap.createMap("map", { center: [36.2, 137.6], zoom: 6 });
        candLayer = L.layerGroup().addTo(map);
        addLegend();
        map.on("click", (e) => setSite(e.latlng.lat, e.latlng.lng));
        map.on("agjcardopen", () => document.body.classList.add("agj-card-open"));
        map.on("agjcardclose", () => document.body.classList.remove("agj-card-open"));

        $("sp-form").addEventListener("submit", onSearch);
        $("sp-cands").addEventListener("click", (ev) => {
            const b = ev.target.closest(".sp-cell");
            if (!b) return;
            select(b.dataset.key);
            const c = cands.find((x) => x.key === b.dataset.key);
            if (c) map.panInside([c.lat, c.lon], { padding: [80, 80] });
        });
        ["sp-unit", "sp-detour"].forEach((id) => $(id).addEventListener("input", () => { if (site) { renderCands(); renderSelected(); } }));
        $("sp-open-report").addEventListener("click", openReport);
        $("sp-close-report").addEventListener("click", closeReport);
        $("sp-print").addEventListener("click", () => buildReport().then(() => window.print()));
        $("sp-copy-link").addEventListener("click", () => {
            const b = $("sp-copy-link");
            navigator.clipboard.writeText(location.href).then(() => {
                b.textContent = "コピーしました"; setTimeout(() => { b.textContent = "この地点のリンクをコピー"; }, 1400);
            }).catch(() => { b.textContent = "コピーできません"; });
        });
        document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("sp-report").hidden) closeReport(); });
        // Ctrl+P でもレポートを刷る(ボタンからでないと背景の地図が間に合わないことがある)
        let openedByPrint = false;
        window.addEventListener("beforeprint", () => {
            if (site && $("sp-report").hidden) { openedByPrint = true; $("sp-report").hidden = false; buildReport(); }
        });
        window.addEventListener("afterprint", () => { if (openedByPrint) { openedByPrint = false; closeReport(); } });
        window.addEventListener("hashchange", () => {
            if (location.hash === lastHash) return;
            const h = readHash();
            if (h) setSite(h.lat, h.lon, { sel: h.sel, fly: true });
        });

        status("地図データを読み込み中…（約 13 MB）");
        Promise.all([getJSON(DATA.subs), getJSON(DATA.lines)]).then((res) => {
            buildIndex(res[0], res[1]);
            renderNetwork(res[0], res[1]);
            status("変電所 " + fmtNum(subMeta.length) + " ・ 送電線 " + fmtNum(lineMeta.length) + " 本。地図をクリックして候補地を選んでください。");
            const h = readHash();
            if (pending) { const p = pending; pending = null; setSite(p.lat, p.lon, p.opts); }
            else if (h) setSite(h.lat, h.lon, { sel: h.sel, fly: "jump" });
        }).catch((err) => {
            status("地図データを読めませんでした: " + (err && err.message));
            console.error("[site_plan]", err);
        });
        getJSON(DATA.obs).then((d) => { obsLines = d && d.lines ? indexObs(d.lines) : null; if (site) { renderCands(); renderSelected(); } }).catch(() => {});
        getJSON(DATA.dash).then((d) => { dashInfo = d; }).catch(() => {});
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();

    // テスト・デバッグ用
    window.sitePlan = {
        setSite: (lat, lon, sel) => setSite(lat, lon, { sel, fly: true }),
        state: () => ({ site, cands: cands.map((c) => ({ key: c.key, name: c.name, dist: c.dist, main: c.main })), selKey, region, weather, profile: profileState && { dist: profileState.dist, z: profileState.z, stats: profileStats(profileState) } }),
        openReport, closeReport, map: () => map,
    };
})();
