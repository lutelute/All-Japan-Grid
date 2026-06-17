/* AGJ 接続編集プラットフォーム — GitHub Pages 静的shim(全面改修Phase5フル統合)
 *
 * 設計(docs/OVERHAUL_PLAN.md「Phase 5 フル統合の確定設計 — 静的shim方式」):
 *   正は1つ = src/server/templates/editor.html(フル機能の:8088エディタ)。:8088は無改修。
 *   Pages版は scripts/build_pages_editor.py が同テンプレを copy + 本shimを inject して派生する。
 *   本shimは backend(:8088)が無いPages上で window.fetch を上書きし、/api/* を
 *   静的JSON(docs/data/**)+ localStorage(下書き)へ振替える。:8088では本ファイルは
 *   読み込まれない(buildで生成されるdocs/editor.htmlにのみ inject される)ので影響ゼロ。
 *
 * 不変条件: 物理接続=真・捏造禁止。Pagesは「閲覧 + 接続の下書き(ブラウザ保存) + issue下書き」。
 *   検証(潮流)/反映(supplement永続)はバックエンド固有のためローカル:8088でのみ可能 → 非表示。
 *
 * レスポンス形状の正規化(肝):
 *   事前生成 data/built/{region}.json は counts を `stats` に内包するが、フロントは
 *   built.n_island_nodes / main_size / n_components / n_edges を **トップレベル** で読む
 *   (templates/editor.html L274/L358)。→ shimが stats をトップレベルへ spread する。
 */
(function () {
  "use strict";
  window.__AGJ_STATIC__ = true;
  var ORIG = window.fetch.bind(window);
  var DATA = "data/"; // docs/editor.html から見た docs/data/(相対=Pagesのproject site配下でも正しく解決)

  var ALL_REGIONS = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
    "kansai", "chugoku", "shikoku", "kyushu", "okinawa"];

  // ── キャッシュ ────────────────────────────────────────────────
  var _tier = {};   // ファイル名 -> 解析済みFeatureCollection(全国tier)
  var _built = {};  // region -> 解析済み built doc(geojson合成 と /api/built で共有=1回DL)
  var _meta = null; // regions_bbox.json 全体({regions, island_class})

  function J(obj, status) {
    return new Response(JSON.stringify(obj),
      { status: status || 200, headers: { "Content-Type": "application/json" } });
  }
  async function tier(name) {
    if (_tier[name]) return _tier[name];
    var r = await ORIG(DATA + name);
    if (!r.ok) throw new Error("tier missing: " + name);
    _tier[name] = await r.json();
    return _tier[name];
  }
  async function builtDoc(region) {
    if (_built[region]) return _built[region];
    var r = await ORIG(DATA + "built/" + region + ".json");
    if (!r.ok) return null;
    _built[region] = await r.json();
    return _built[region];
  }
  async function meta() {
    if (_meta) return _meta;
    var r = await ORIG(DATA + "built/regions_bbox.json");
    _meta = r.ok ? await r.json() : { regions: {}, island_class: [] };
    return _meta;
  }
  async function bbox() { return (await meta()).regions || {}; }

  // ── built doc の正規化: stats をトップレベルへ展開(フロントが読む形に) ──
  function flattenBuilt(doc) {
    if (!doc) return null;
    var out = {};
    for (var k in doc) if (k !== "stats") out[k] = doc[k];
    var s = doc.stats || {};
    for (var k2 in s) out[k2] = s[k2];
    return out;
  }

  // ── per-region 生OSM層を built/{region}.json から軽量合成 ──
  //   基底extract(66k features)を静的化せず、既に公開済の built モデルから
  //   変電所リング(snap点)と回廊線(fitBounds用)を作る。fit復活+snap確保。
  //   生OSMの“モデル未接続線”は全国概観(tier)側で確認できる。
  function synthSubs(doc) {
    var feats = [];
    (doc.nodes || []).forEach(function (n) {
      if (!n.sub) return;
      if (!isFinite(n.lat) || !isFinite(n.lon)) return;
      feats.push({
        type: "Feature",
        geometry: { type: "Point", coordinates: [n.lon, n.lat] },
        properties: { id: n.id, name: n.name || null, voltage: n.kv || 0, _voltage_kv: n.kv || null },
      });
    });
    return { type: "FeatureCollection", features: feats };
  }
  function synthLines(doc) {
    var feats = [];
    (doc.edges || []).forEach(function (e) {
      var path = e.path || (e.a && e.b ? [e.a, e.b] : null);
      if (!path || path.length < 2) return;
      // built path は [lat,lon] 配列 → GeoJSON は [lon,lat]
      var coords = path.map(function (p) { return [p[1], p[0]]; });
      feats.push({
        type: "Feature",
        geometry: { type: "LineString", coordinates: coords },
        properties: { name: e.name || null, voltage: e.kv || null, _voltage_kv: e.kv || null },
      });
    });
    return { type: "FeatureCollection", features: feats };
  }

  // ── 全国tier の min_kv フィルタ(/api/geojson/all/{layer} 等価) ──
  function filterByKv(fc, minKv) {
    var feats = (fc.features || []).filter(function (f) {
      var k = (f.properties || {})._voltage_kv;
      return k != null && k >= minKv;
    });
    return { type: "FeatureCollection", features: feats };
  }

  // ── localStorage 下書きCRUD(/api/edits 等価) ──
  function ek(r) { return "agj_edits_" + r; }
  function getEdits(r) { try { return JSON.parse(localStorage.getItem(ek(r)) || "[]"); } catch (e) { return []; } }
  function setEdits(r, a) { localStorage.setItem(ek(r), JSON.stringify(a)); }
  function tally(a) { var c = {}; a.forEach(function (e) { c[e.status] = (c[e.status] || 0) + 1; }); return c; }
  function newId() { return "d" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }

  // ── issue 下書き → GitHub プレフィルURL(サーバ捏造せず人間がGitHubで作成) ──
  function fmtPt(p) { return p ? "(" + (+p.lat).toFixed(4) + "," + (+p.lon).toFixed(4) + ")" : "?"; }
  function buildIssue(region, body) {
    var regs = region === "all" ? ALL_REGIONS : [region];
    var eds = [];
    regs.forEach(function (r) {
      getEdits(r).forEach(function (e) { if (e.status === "pending") eds.push(e); });
    });
    var n = eds.length;
    var title = "[接続提案] " + region + " 下書き " + n + "件 (AGJ Pages)";
    var L = ["# 接続編集提案 (" + region + ")", "", "下書き件数: " + n, ""];
    if (body && body.memo) { L.push("## メモ", body.memo, ""); }
    L.push("## 編集一覧");
    eds.slice(0, 80).forEach(function (e) {
      if (e.action === "connect") L.push("- connect " + fmtPt(e.a) + " ↔ " + fmtPt(e.b) + (e.kv ? " (" + (e.kv / 1000) + "kV)" : ""));
      else if (e.action === "disconnect") L.push("- ✂cut " + fmtPt(e.a) + " ↔ " + fmtPt(e.b));
      else if (e.action === "add_point") L.push("- add_point " + fmtPt(e.pt) + " " + ((e.attrs && e.attrs.name) || ""));
      else L.push("- " + e.action);
    });
    if (n > 80) L.push("- …他 " + (n - 80) + "件");
    L.push("", "> AGJ GitHub Pages の下書きモードで作成。物理接続=真・捏造禁止のもとレビューしてください。");
    var bodyMd = L.join("\n");
    if (body && body.dry_run) return { ok: true, n: n, title: title, body: bodyMd };
    var url = "https://github.com/lutelute/All-Japan-Grid/issues/new?labels="
      + encodeURIComponent("connection,data-quality")
      + "&title=" + encodeURIComponent(title)
      + "&body=" + encodeURIComponent(bodyMd.slice(0, 6000));
    return { ok: true, n: n, issue_number: "draft", issue_url: url, title: title, body: bodyMd };
  }

  // ── fetch 上書き本体 ──
  window.fetch = async function (input, init) {
    var url = (typeof input === "string") ? input : (input && input.url) || "";
    var method = ((init && init.method) || (input && input.method) || "GET").toUpperCase();
    var i = url.indexOf("/api/");
    if (i < 0) return ORIG(input, init); // /api 以外(タイル等)は素通し
    var api = url.slice(i).split("#")[0];
    var path = api.split("?")[0];
    try {
      // GET /api/regions
      if (path === "/api/regions") { return J({ regions: await bbox() }); }

      // GET /api/built/{region|all}
      var mB = path.match(/^\/api\/built\/([^/]+)$/);
      if (mB && method === "GET") {
        var doc = await builtDoc(mB[1]);
        if (!doc) return J({ detail: "no built for " + mB[1] }, 404);
        return J(flattenBuilt(doc));
      }

      // GET /api/geojson/all/{layer}?min_kv=
      var mA = path.match(/^\/api\/geojson\/all\/([^/]+)$/);
      if (mA) {
        var layerA = mA[1];
        var mk = 0;
        try { mk = parseFloat(new URL(url, location.href).searchParams.get("min_kv") || "0") || 0; } catch (e) {}
        var fileA = layerA === "substations" ? "subs_all.geojson" : "lines_all.geojson";
        return J(filterByKv(await tier(fileA), mk));
      }

      // GET /api/geojson/{region}/{layer} → built/{region}.json から軽量合成
      var mG = path.match(/^\/api\/geojson\/([^/]+)\/([^/]+)$/);
      if (mG) {
        var reg = mG[1], layer = mG[2];
        var bdoc = await builtDoc(reg);
        if (!bdoc) return J({ type: "FeatureCollection", features: [] });
        return J(layer === "substations" ? synthSubs(bdoc) : synthLines(bdoc));
      }

      // GET /api/island_class/{region} → 公開リストに在る時のみ配信(無ければ即404=
      //   存在しないファイルへ fetch せず、ブラウザの404コンソール汚染を避ける)。フロントはnull扱い。
      var mI = path.match(/^\/api\/island_class\/([^/]+)$/);
      if (mI && method === "GET") {
        var icList = (await meta()).island_class || [];
        if (icList.indexOf(mI[1]) < 0) return J({ detail: "island_class未公開(下書きモード)" }, 404);
        var ric = await ORIG(DATA + "island_class/" + mI[1] + ".json");
        return ric.ok ? ric : J({ detail: "island_class未公開" }, 404);
      }

      // POST /api/edits(下書き追加)
      if (path === "/api/edits" && method === "POST") {
        var body = {};
        try { body = JSON.parse((init && init.body) || "{}"); } catch (e) {}
        var r = body.region || "tokyo";
        var arr = getEdits(r);
        var rec = Object.assign({}, body, { id: newId(), status: "pending", ts: Date.now() });
        arr.push(rec); setEdits(r, arr);
        return J({ ok: true, id: rec.id, status: "pending" });
      }
      // DELETE /api/edits/{region}/{id}
      var mDel = path.match(/^\/api\/edits\/([^/]+)\/([^/]+)$/);
      if (mDel && method === "DELETE") {
        var dr = mDel[1], did = mDel[2], da = getEdits(dr);
        var idx = da.findIndex(function (e) { return e.id === did; });
        if (idx < 0) return J({ detail: "該当する下書きがありません" }, 404);
        var removed = da.splice(idx, 1)[0]; setEdits(dr, da);
        return J({ ok: true, removed: removed });
      }
      // GET /api/edits/{region}
      var mGe = path.match(/^\/api\/edits\/([^/]+)$/);
      if (mGe && method === "GET") {
        var gr = mGe[1], ga = getEdits(gr);
        return J({ region: gr, edits: ga, counts: tally(ga), submitted: [] });
      }

      // POST /api/verify|/api/adopt → バックエンド専用(下書きモードでは非対応)
      if (/^\/api\/verify\//.test(path)) return J({ detail: "検証(潮流)はローカル :8088 でのみ可能(下書きモード)" }, 501);
      if (/^\/api\/adopt\//.test(path)) return J({ detail: "反映(supplement永続)はローカル :8088 でのみ可能(下書きモード)" }, 501);

      // POST /api/issue/{region} → GitHub プレフィルURL
      var mIss = path.match(/^\/api\/issue\/([^/]+)$/);
      if (mIss && method === "POST") {
        var ibody = {};
        try { ibody = JSON.parse((init && init.body) || "{}"); } catch (e) {}
        return J(buildIssue(mIss[1], ibody));
      }

      return J({ detail: "下書きモードでは未対応: " + api }, 501);
    } catch (err) {
      return J({ detail: "static shim error: " + err }, 500);
    }
  };

  // ── UI 微調整(Pagesのみ・:8088には無い): 下書きモードの明示と backend専用ボタンの整理 ──
  function tweakUI() {
    var panel = document.getElementById("panel");
    var host = panel ? (panel.querySelector(".body") || panel) : null;
    if (host && !document.getElementById("agj-static-banner")) {
      var b = document.createElement("div");
      b.id = "agj-static-banner";
      b.style.cssText = "background:#161b22;border:1px solid #30363d;border-left:3px solid #a371f7;"
        + "border-radius:9px;padding:7px 10px;margin:12px 0 0;font-size:11px;color:#9cc4f0;line-height:1.45";
      b.innerHTML = "📝 <b>下書きモード</b> — 閲覧+下書き+issue(ブラウザ保存)。検証/反映/属性永続は <code>:8088</code> で。";
      host.insertBefore(b, host.firstChild);
    }
    // backend専用ボタンを非表示(verify/adopt)
    var hide = ["verifyEdits()", "adoptEdits()"];
    Array.prototype.forEach.call(document.querySelectorAll("button"), function (btn) {
      var oc = btn.getAttribute("onclick") || "";
      if (hide.indexOf(oc) >= 0) btn.style.display = "none";
      if (oc === "submitIssue()") btn.textContent = "🐙 GitHubでissue作成(プレフィル)";
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", tweakUI);
  else tweakUI();
})();
