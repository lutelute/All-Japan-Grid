/**
 * Japan Power Grid — Ybus interactive simulation tool (DB4)
 *
 * Builds the bus admittance (Ybus) adjacency for one region *in the browser*
 * from the canonical built model (docs/data/built/{region}.json) and lets the
 * user inspect and edit it:
 *
 *   - Region selector  -> construct Ybus adjacency (bus x bus) client-side.
 *   - Canvas spy plot  -> dark theme (#0f1419 / #5dade2), diagonal=orange,
 *                         off-diagonal=cyan. Zoom (wheel) + pan (drag).
 *   - Hover            -> bus info (name / kv / substation?).
 *   - Click a bus      -> highlight its row & column (its connections).
 *   - Toggle a branch  -> enable/disable a bus-bus coupling; Ybus + live stats
 *                         (nnz / density / deg avg+max / #connected components)
 *                         recompute immediately. Reset restores all.
 *
 * Model fidelity (matches gen_ybus_from_db.py + index.json component counts):
 *   - Line edges: endpoints matched to nodes site-aware (same lat/lon may host
 *     several buses at different kV = a transformer site; prefer the kV-matching
 *     bus, never collapse them into a self-loop).
 *   - Transformer edges: co-located buses (different kV, same site) are joined
 *     by an explicit transformer branch (NOT a self-loop) so components match.
 *
 * No video. Interactive is the primary view; the static PNG gallery is a
 * secondary "details" fallback (handled by the inline script in index.html).
 */

(function () {
    "use strict";

    var RJA = {
        hokkaido: "北海道", tohoku: "東北", tokyo: "東京", chubu: "中部",
        hokuriku: "北陸", kansai: "関西", chugoku: "中国", shikoku: "四国",
        kyushu: "九州", okinawa: "沖縄"
    };

    // Dark palette (matches #ybus-panel)
    var COL = {
        fig: "#0f1419", ax: "#0c1014", dot: "#5dade2", diag: "#f5b041",
        xfmr: "#69f0ae", hl: "#ff3b6b", off: "#34495e", grid: "#16212c",
        sub: "#9fb3c8", title: "#e6e6e6"
    };

    var state = {
        inited: false,
        region: "tokyo",
        model: null,         // { buses, links } for current region
        // view transform (data px -> screen): screen = data*scale + off
        scale: 1, offX: 0, offY: 0,
        hoverBus: -1,        // bus index under cursor (matrix row/col)
        selBus: -1,          // clicked/locked bus
        dragging: false, dragMoved: false, lastX: 0, lastY: 0,
        canvas: null, ctx: null, dpr: 1,
        cache: {}            // region -> raw json
    };

    // ── small DOM helper ──
    function el(tag, attrs, html) {
        var e = document.createElement(tag);
        if (attrs) for (var k in attrs) {
            if (k === "style") e.style.cssText = attrs[k];
            else if (k === "class") e.className = attrs[k];
            else e.setAttribute(k, attrs[k]);
        }
        if (html != null) e.innerHTML = html;
        return e;
    }
    function $(id) { return document.getElementById(id); }

    function rkey(lat, lon) { return lat.toFixed(5) + "," + lon.toFixed(5); }

    // ──────────────────────────────────────────────────────────────
    //  Model construction (site-aware, with transformer branches)
    // ──────────────────────────────────────────────────────────────
    function buildModel(raw) {
        var nodes = raw.nodes || [];
        var edges = raw.edges || [];
        // site index: (lat,lon) -> [bus indices]
        var loc = {};
        for (var i = 0; i < nodes.length; i++) {
            var n = nodes[i];
            var key = rkey(n.lat, n.lon);
            (loc[key] || (loc[key] = [])).push(i);
        }
        function pick(latlon, kv) {
            var cands = loc[rkey(latlon[0], latlon[1])];
            if (!cands) return -1;
            if (cands.length === 1) return cands[0];
            if (kv != null) {
                for (var c = 0; c < cands.length; c++) {
                    var nkv = nodes[cands[c]].kv;
                    if (nkv != null && Math.abs(nkv - kv) < 0.5) return cands[c];
                }
            }
            return cands[0];
        }

        // undirected pair -> link object (dedup), keep names/kv/kind
        var byPair = {};            // "i:j" -> link
        function addLink(a, b, kind, kv, name) {
            if (a < 0 || b < 0 || a === b) return;
            var lo = Math.min(a, b), hi = Math.max(a, b);
            var k = lo + ":" + hi;
            var L = byPair[k];
            if (!L) {
                L = { i: lo, j: hi, kind: kind, kv: kv, name: name || "",
                      enabled: true, id: 0 };
                byPair[k] = L;
            } else {
                // merge: prefer line over xfmr label; accumulate names
                if (name && L.name.indexOf(name) < 0) {
                    L.name = L.name ? (L.name + "; " + name) : name;
                }
                if (kv != null && (L.kv == null || kv > L.kv)) L.kv = kv;
                if (kind === "line") L.kind = "line";
            }
        }

        // line branches
        for (var e = 0; e < edges.length; e++) {
            var ed = edges[e];
            var ia = pick(ed.a, ed.kv), ib = pick(ed.b, ed.kv);
            addLink(ia, ib, "line", ed.kv, ed.name);
        }
        // transformer branches: chain co-located buses (different kV at a site)
        for (var key in loc) {
            var cs = loc[key];
            if (cs.length > 1) {
                cs = cs.slice().sort(function (x, y) { return x - y; });
                for (var t = 0; t < cs.length - 1; t++) {
                    addLink(cs[t], cs[t + 1], "xfmr", null, "変圧器");
                }
            }
        }

        var links = [];
        var lid = 0;
        for (var pk in byPair) { var lk = byPair[pk]; lk.id = lid++; links.push(lk); }
        // stable order: by i then j (gives clean banded spy)
        links.sort(function (p, q) { return p.i - q.i || p.j - q.j; });
        for (var z = 0; z < links.length; z++) links[z].id = z;

        return { region: raw.region, buses: nodes, links: links };
    }

    // ──────────────────────────────────────────────────────────────
    //  Stats (recomputed on every toggle) — union-find components
    // ──────────────────────────────────────────────────────────────
    function computeStats(model) {
        var N = model.buses.length;
        var deg = new Int32Array(N);
        var parent = new Int32Array(N);
        for (var p = 0; p < N; p++) parent[p] = p;
        function find(x) { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; }

        var nnz = 0, nLine = 0, nXfmr = 0;
        var links = model.links;
        for (var i = 0; i < links.length; i++) {
            var L = links[i];
            if (!L.enabled) continue;
            nnz++;
            if (L.kind === "xfmr") nXfmr++; else nLine++;
            deg[L.i]++; deg[L.j]++;
            var ra = find(L.i), rb = find(L.j);
            if (ra !== rb) parent[ra] = rb;
        }
        // components over ALL buses (isolated buses count)
        var comps = 0, mainSize = 0;
        var sizeOf = {};
        for (var b = 0; b < N; b++) {
            var r = find(b);
            sizeOf[r] = (sizeOf[r] || 0) + 1;
        }
        for (var rk in sizeOf) { comps++; if (sizeOf[rk] > mainSize) mainSize = sizeOf[rk]; }

        var degMax = 0, degSum = 0, degCnt = 0;
        for (var d = 0; d < N; d++) {
            if (deg[d] > degMax) degMax = deg[d];
            if (deg[d] > 0) { degSum += deg[d]; degCnt++; }
        }
        var nSub = 0;
        for (var s = 0; s < N; s++) if (model.buses[s].sub === 1) nSub++;

        return {
            N: N, nSub: nSub, nnz: nnz, nLine: nLine, nXfmr: nXfmr,
            density: N ? (nnz / (N * N) * 100) : 0,
            degAvg: degCnt ? (degSum / degCnt) : 0,
            degMax: degMax, comps: comps, mainSize: mainSize, deg: deg
        };
    }

    // adjacency of a single bus (its enabled neighbours) for highlight
    function neighbours(model, bus) {
        var out = [];
        if (bus < 0) return out;
        var links = model.links;
        for (var i = 0; i < links.length; i++) {
            var L = links[i];
            if (!L.enabled) continue;
            if (L.i === bus) out.push(L.j);
            else if (L.j === bus) out.push(L.i);
        }
        return out;
    }

    // ──────────────────────────────────────────────────────────────
    //  Canvas spy plot — zoom/pan, hover, selection highlight
    // ──────────────────────────────────────────────────────────────
    function fitView() {
        // fit N x N matrix into canvas with small margin
        var c = state.canvas;
        var N = state.model ? state.model.buses.length : 1;
        var w = c.clientWidth, h = c.clientHeight;
        var m = 18;
        var s = Math.min((w - 2 * m) / N, (h - 2 * m) / N);
        state.scale = s;
        state.offX = m + (w - 2 * m - s * N) / 2;
        state.offY = m + (h - 2 * m - s * N) / 2;
    }

    function draw() {
        var c = state.canvas, ctx = state.ctx;
        if (!c || !state.model) return;
        var dpr = state.dpr;
        var w = c.clientWidth, h = c.clientHeight;
        var N = state.model.buses.length;
        var sc = state.scale, ox = state.offX, oy = state.offY;

        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, w, h);
        ctx.fillStyle = COL.ax;
        ctx.fillRect(0, 0, w, h);

        // matrix frame
        ctx.strokeStyle = COL.off;
        ctx.lineWidth = 1;
        ctx.strokeRect(ox, oy, sc * N, sc * N);

        // point size scales with zoom but stays visible
        var ps = Math.max(0.7, Math.min(6, sc * 0.9));
        var half = ps / 2;

        var links = state.model.links;
        var deg = state._stats ? state._stats.deg : null;

        // 1) off-diagonal couplings (cyan), disabled = dim ghost
        for (var i = 0; i < links.length; i++) {
            var L = links[i];
            var xi = ox + (L.j + 0.5) * sc, yi = oy + (L.i + 0.5) * sc;
            var xj = ox + (L.i + 0.5) * sc, yj = oy + (L.j + 0.5) * sc;
            if (L.enabled) {
                ctx.fillStyle = (L.kind === "xfmr") ? COL.xfmr : COL.dot;
                ctx.globalAlpha = 0.9;
            } else {
                ctx.fillStyle = "#2a3744";
                ctx.globalAlpha = 0.55;
            }
            ctx.fillRect(xi - half, yi - half, ps, ps);   // (i,j)
            ctx.fillRect(xj - half, yj - half, ps, ps);   // (j,i) symmetric
        }
        ctx.globalAlpha = 1;

        // 2) diagonal (orange) for buses with degree >= 1
        if (deg) {
            ctx.fillStyle = COL.diag;
            for (var d = 0; d < N; d++) {
                if (deg[d] >= 1) {
                    var xd = ox + (d + 0.5) * sc, yd = oy + (d + 0.5) * sc;
                    ctx.fillRect(xd - half, yd - half, ps, ps);
                }
            }
        }

        // 3) selection highlight: row + column band of selected bus
        var hb = state.selBus >= 0 ? state.selBus : -1;
        if (hb >= 0) {
            var bx = ox + hb * sc, by = oy + hb * sc;
            ctx.fillStyle = "rgba(255,59,107,0.16)";
            ctx.fillRect(ox, by, sc * N, sc);        // row
            ctx.fillRect(bx, oy, sc, sc * N);        // column
            // highlight its neighbour cells brightly
            var nb = neighbours(state.model, hb);
            ctx.fillStyle = COL.hl;
            var hs = Math.max(2, ps + 1.5), hh = hs / 2;
            for (var k = 0; k < nb.length; k++) {
                var nx = ox + (nb[k] + 0.5) * sc, ny = oy + (hb + 0.5) * sc;
                ctx.fillRect(nx - hh, ny - hh, hs, hs);            // row entry
                var nx2 = ox + (hb + 0.5) * sc, ny2 = oy + (nb[k] + 0.5) * sc;
                ctx.fillRect(nx2 - hh, ny2 - hh, hs, hs);          // column entry
            }
            // diagonal marker of selected bus
            var sx = ox + (hb + 0.5) * sc, sy = oy + (hb + 0.5) * sc;
            ctx.fillStyle = "#fff";
            ctx.fillRect(sx - hh, sy - hh, hs, hs);
        }

        // 4) hover crosshair
        var ho = state.hoverBus;
        if (ho >= 0 && ho !== hb) {
            ctx.strokeStyle = "rgba(93,173,226,0.5)";
            ctx.lineWidth = 1;
            var hx = ox + (ho + 0.5) * sc, hy = oy + (ho + 0.5) * sc;
            ctx.beginPath();
            ctx.moveTo(ox, hy); ctx.lineTo(ox + sc * N, hy);
            ctx.moveTo(hx, oy); ctx.lineTo(hx, oy + sc * N);
            ctx.stroke();
        }
    }

    // pixel -> bus index (matrix col == bus, we report the column under cursor)
    function busAt(px, py) {
        var sc = state.scale, ox = state.offX, oy = state.offY;
        var N = state.model.buses.length;
        var col = Math.floor((px - ox) / sc);
        var row = Math.floor((py - oy) / sc);
        if (col < 0 || col >= N || row < 0 || row >= N) return { bus: -1, row: -1, col: -1 };
        return { bus: col, row: row, col: col };
    }

    // ──────────────────────────────────────────────────────────────
    //  UI panels (stats + tooltip + branch list)
    // ──────────────────────────────────────────────────────────────
    function statRow(label, val, color) {
        return '<div style="display:flex;justify-content:space-between;border-bottom:1px dashed #1f3a4a;padding:5px 0">' +
            '<span style="color:#9fb3c8">' + label + '</span>' +
            '<span style="font-family:ui-monospace,monospace;color:' + (color || "#fff") + ';font-weight:600">' + val + '</span></div>';
    }

    function renderStats() {
        var st = computeStats(state.model);
        state._stats = st;
        var box = $("ybus-sim-stats");
        if (!box) return;
        box.innerHTML =
            statRow("地域", RJA[state.region] || state.region) +
            statRow("バス数 N", st.N.toLocaleString()) +
            statRow("うち変電所", st.nSub.toLocaleString()) +
            statRow("非零 nnz (有効枝)", st.nnz.toLocaleString(), COL.dot) +
            statRow("　└ 送電線 / 変圧器", st.nLine.toLocaleString() + " / " + st.nXfmr.toLocaleString()) +
            statRow("疎度 density", st.density.toFixed(4) + " %") +
            statRow("平均次数", st.degAvg.toFixed(2)) +
            statRow("最大次数", String(st.degMax)) +
            statRow("連結成分数", st.comps.toLocaleString(), st.comps > 1 ? "#ffd43b" : "#69f0ae") +
            statRow("最大成分サイズ", st.mainSize.toLocaleString()) +
            statRow("行列形状", st.N + " × " + st.N);

        var nDis = 0;
        for (var i = 0; i < state.model.links.length; i++) if (!state.model.links[i].enabled) nDis++;
        var mini = $("ybus-sim-mini");
        if (mini) {
            mini.innerHTML = "<b>" + st.N.toLocaleString() + "</b> バス · 非零 <b>" +
                st.nnz.toLocaleString() + "</b> · 成分 <b style=\"color:" +
                (st.comps > 1 ? "#ffd43b" : "#69f0ae") + "\">" + st.comps + "</b>" +
                (nDis ? (" · <b style=\"color:#ff3b6b\">無効枝 " + nDis + "</b>") : "");
        }
    }

    function setTooltip(info) {
        var tt = $("ybus-sim-tip");
        if (!tt) return;
        if (!info || info.bus < 0) { tt.style.display = "none"; return; }
        var b = state.model.buses[info.bus];
        var nb = neighbours(state.model, info.bus);
        tt.style.display = "block";
        tt.innerHTML =
            '<div style="font-weight:700;color:#fff;margin-bottom:3px">#' + info.bus +
            (b.sub === 1 ? ' <span style="color:#69f0ae">変電所</span>' : ' <span style="color:#9fb3c8">接続点</span>') + '</div>' +
            '<div style="color:#cfd8e3">' + (b.name || "(名称なし)") + '</div>' +
            '<div style="color:#9fb3c8;margin-top:2px">' + (b.kv != null ? b.kv + " kV" : "kV不明") +
            ' · 次数 ' + nb.length + '</div>' +
            (info.row >= 0 && info.row !== info.col
                ? '<div style="color:#5dade2;margin-top:2px;font-size:10px">行 #' + info.row + ' × 列 #' + info.col + '</div>'
                : '');
    }

    function renderBranchList() {
        var wrap = $("ybus-sim-branchlist");
        if (!wrap) return;
        var links = state.model.links;
        var buses = state.model.buses;
        // limit DOM rows for huge regions; provide a filter
        var filt = ($("ybus-sim-filter") && $("ybus-sim-filter").value || "").trim().toLowerCase();
        var rows = [];
        var shown = 0, MAXROWS = 400;
        for (var i = 0; i < links.length; i++) {
            var L = links[i];
            var na = buses[L.i].name || ("#" + L.i);
            var nb = buses[L.j].name || ("#" + L.j);
            var lbl = (L.name || (L.kind === "xfmr" ? "変圧器" : "送電線"));
            if (filt) {
                var hay = (lbl + " " + na + " " + nb + " " + (L.kv || "")).toLowerCase();
                if (hay.indexOf(filt) < 0) continue;
            }
            shown++;
            if (shown > MAXROWS) continue;
            var kvtxt = L.kv != null ? (L.kv + "kV") : (L.kind === "xfmr" ? "T" : "—");
            rows.push(
                '<label style="display:flex;align-items:center;gap:6px;padding:3px 4px;border-bottom:1px solid #14202a;cursor:pointer;' +
                (L.enabled ? "" : "opacity:0.5;") + '" data-lid="' + L.id + '" class="ybus-sim-brow">' +
                '<input type="checkbox" ' + (L.enabled ? "checked" : "") + ' data-lid="' + L.id + '" style="accent-color:#5dade2">' +
                '<span style="color:' + (L.kind === "xfmr" ? COL.xfmr : COL.dot) + ';font-size:10px;width:34px;flex:0 0 auto">' + kvtxt + '</span>' +
                '<span style="color:#cfd8e3;font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' +
                '#' + L.i + '–#' + L.j + ' ' + lbl + '</span></label>'
            );
        }
        var head = '<div style="font-size:10px;color:#7d8aa0;padding:3px 0">枝 ' + links.length.toLocaleString() +
            (shown > MAXROWS ? (' · 表示 ' + MAXROWS + '/' + shown + '（絞り込み推奨）') :
                (filt ? (' · 一致 ' + shown) : '')) + '</div>';
        wrap.innerHTML = head + rows.join("");
        // wire checkboxes
        wrap.querySelectorAll("input[type=checkbox]").forEach(function (cb) {
            cb.addEventListener("change", function () {
                var lid = +this.dataset.lid;
                var L = state.model.links[lid];
                if (L) { L.enabled = this.checked; onModelChanged(); }
            });
        });
        // click row label (not checkbox) selects the i-bus to highlight
        wrap.querySelectorAll(".ybus-sim-brow").forEach(function (lab) {
            lab.addEventListener("click", function (ev) {
                if (ev.target && ev.target.tagName === "INPUT") return;
                var lid = +this.dataset.lid;
                var L = state.model.links[lid];
                if (L) { state.selBus = L.i; draw(); }
            });
        });
    }

    function onModelChanged() {
        renderStats();
        draw();
    }

    // ──────────────────────────────────────────────────────────────
    //  Region load
    // ──────────────────────────────────────────────────────────────
    function setBusy(on, msg) {
        var b = $("ybus-sim-busy");
        if (b) { b.style.display = on ? "flex" : "none"; if (msg) b.textContent = msg; }
    }

    async function loadRegion(region) {
        state.region = region;
        setBusy(true, "build/" + region + ".json を読み込み中…");
        try {
            var raw = state.cache[region];
            if (!raw) {
                var r = await fetch("./data/built/" + region + ".json?cb=" + Date.now());
                if (!r.ok) throw new Error("HTTP " + r.status);
                raw = await r.json();
                state.cache[region] = raw;
            }
            state.model = buildModel(raw);
            state.selBus = -1; state.hoverBus = -1;
            renderStats();
            fitView();
            renderBranchList();
            draw();
        } catch (e) {
            console.error("[ybus_sim] load failed", e);
            var box = $("ybus-sim-stats");
            if (box) box.innerHTML = '<div style="color:#ff6b6b">読み込み失敗: ' + e.message + '</div>';
        } finally {
            setBusy(false);
        }
    }

    // ──────────────────────────────────────────────────────────────
    //  Canvas events
    // ──────────────────────────────────────────────────────────────
    function setupCanvas() {
        var c = state.canvas;
        var dpr = window.devicePixelRatio || 1;
        state.dpr = dpr;

        function resize() {
            var w = c.clientWidth, h = c.clientHeight;
            c.width = Math.round(w * dpr);
            c.height = Math.round(h * dpr);
            if (state.model) { /* keep transform; just redraw */ draw(); }
        }
        // initial sizing
        requestAnimationFrame(function () { resize(); if (state.model) { fitView(); draw(); } });
        window.addEventListener("resize", function () { resize(); });

        // wheel zoom (about cursor)
        c.addEventListener("wheel", function (ev) {
            ev.preventDefault();
            if (!state.model) return;
            var rect = c.getBoundingClientRect();
            var mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
            var f = ev.deltaY < 0 ? 1.15 : 1 / 1.15;
            var ns = state.scale * f;
            ns = Math.max(0.05, Math.min(40, ns));
            f = ns / state.scale;
            // keep cursor point fixed
            state.offX = mx - (mx - state.offX) * f;
            state.offY = my - (my - state.offY) * f;
            state.scale = ns;
            draw();
        }, { passive: false });

        // drag = pan
        c.addEventListener("mousedown", function (ev) {
            state.dragging = true; state.dragMoved = false;
            state.lastX = ev.clientX; state.lastY = ev.clientY;
        });
        window.addEventListener("mouseup", function () { state.dragging = false; });
        c.addEventListener("mousemove", function (ev) {
            var rect = c.getBoundingClientRect();
            var mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
            if (state.dragging) {
                var dx = ev.clientX - state.lastX, dy = ev.clientY - state.lastY;
                if (Math.abs(dx) + Math.abs(dy) > 2) state.dragMoved = true;
                state.offX += dx; state.offY += dy;
                state.lastX = ev.clientX; state.lastY = ev.clientY;
                draw();
                return;
            }
            var info = busAt(mx, my);
            if (info.bus !== state.hoverBus) {
                state.hoverBus = info.bus;
                draw();
            }
            setTooltip(info);
            var tt = $("ybus-sim-tip");
            if (tt && info.bus >= 0) {
                tt.style.left = Math.min(mx + 14, c.clientWidth - 220) + "px";
                tt.style.top = Math.min(my + 14, c.clientHeight - 90) + "px";
            }
        });
        c.addEventListener("mouseleave", function () {
            state.hoverBus = -1;
            setTooltip(null);
            draw();
        });
        // click selects a bus (row+column highlight); ignore if it was a drag
        c.addEventListener("click", function (ev) {
            if (state.dragMoved) return;
            var rect = c.getBoundingClientRect();
            var info = busAt(ev.clientX - rect.left, ev.clientY - rect.top);
            state.selBus = (info.bus === state.selBus) ? -1 : info.bus;
            draw();
            // reflect selection in info line
            var sb = $("ybus-sim-selinfo");
            if (sb) {
                if (state.selBus < 0) sb.innerHTML = "";
                else {
                    var b = state.model.buses[state.selBus];
                    var nb = neighbours(state.model, state.selBus);
                    sb.innerHTML = '選択: <b style="color:#fff">#' + state.selBus + '</b> ' +
                        (b.name || "") + ' — 接続 <b style="color:#ff3b6b">' + nb.length + '</b> バス' +
                        ' <span style="color:#7d8aa0">(行/列ハイライト)</span>';
                }
            }
        });
    }

    // ──────────────────────────────────────────────────────────────
    //  Build the simulator DOM inside #ybus-sim-root (created in HTML)
    // ──────────────────────────────────────────────────────────────
    function mount() {
        var root = $("ybus-sim-root");
        if (!root) return false;

        // region options
        var regs = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
                    "kansai", "chugoku", "shikoku", "kyushu", "okinawa"];
        var opts = regs.map(function (r) {
            return '<option value="' + r + '"' + (r === state.region ? " selected" : "") + '>' + RJA[r] + '</option>';
        }).join("");

        root.innerHTML =
        '<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 10px">' +
            '<label style="font-size:12px;color:#9fb3c8">地域:</label>' +
            '<select id="ybus-sim-region" style="background:#1b2631;color:#fff;border:1px solid #34495e;border-radius:4px;padding:5px 8px;font-size:13px">' + opts + '</select>' +
            '<button id="ybus-sim-reset" style="background:#16213e;color:#9fb3c8;border:1px solid #34495e;border-radius:4px;padding:5px 12px;font-size:12px;cursor:pointer">↺ 全枝リセット</button>' +
            '<button id="ybus-sim-fit" style="background:#16213e;color:#9fb3c8;border:1px solid #34495e;border-radius:4px;padding:5px 12px;font-size:12px;cursor:pointer">⤢ 全体表示</button>' +
            '<span id="ybus-sim-mini" style="font-size:12px;color:#5dade2;margin-left:4px"></span>' +
        '</div>' +
        '<div style="display:grid;grid-template-columns:minmax(0,2.1fr) minmax(280px,1fr);gap:14px;align-items:start">' +
            // left: canvas
            '<div style="position:relative">' +
                '<div id="ybus-sim-canvas-wrap" style="position:relative;width:100%;aspect-ratio:1/1;max-height:78vh;border:1px solid #2c3e50;border-radius:4px;background:' + COL.ax + ';overflow:hidden">' +
                    '<canvas id="ybus-sim-canvas" style="width:100%;height:100%;display:block;cursor:crosshair"></canvas>' +
                    '<div id="ybus-sim-tip" style="display:none;position:absolute;pointer-events:none;background:rgba(8,14,20,0.96);border:1px solid #2c3e50;border-radius:4px;padding:6px 9px;font-size:11px;color:#cfd8e3;max-width:210px;z-index:5;box-shadow:0 2px 8px rgba(0,0,0,0.5)"></div>' +
                    '<div id="ybus-sim-busy" style="display:none;position:absolute;inset:0;align-items:center;justify-content:center;background:rgba(15,20,25,0.82);color:#9fb3c8;font-size:13px;z-index:6">読み込み中…</div>' +
                    '<div style="position:absolute;left:8px;bottom:6px;font-size:10px;color:#5b6b7c;pointer-events:none">ホイール=ズーム / ドラッグ=パン / クリック=行・列ハイライト</div>' +
                '</div>' +
                '<div id="ybus-sim-selinfo" style="margin-top:6px;font-size:11px;color:#9fb3c8;min-height:14px"></div>' +
                '<div style="margin-top:4px;font-size:10px;color:#7d8aa0">' +
                    '<span style="color:' + COL.diag + '">■</span> 対角(自己) ' +
                    '<span style="color:' + COL.dot + '">■</span> 送電線結合 ' +
                    '<span style="color:' + COL.xfmr + '">■</span> 変圧器 ' +
                    '<span style="color:' + COL.hl + '">■</span> 選択バスの接続' +
                '</div>' +
            '</div>' +
            // right: stats + branch editor
            '<div style="min-width:0">' +
                '<div style="background:#0c1014;border:1px solid #2c3e50;border-radius:4px;padding:12px">' +
                    '<div style="font-size:13px;color:#9fb3c8;font-weight:600;margin:0 0 8px">ライブ統計（操作に追従）</div>' +
                    '<div id="ybus-sim-stats"></div>' +
                '</div>' +
                '<div style="background:#0c1014;border:1px solid #2c3e50;border-radius:4px;padding:12px;margin-top:10px">' +
                    '<div style="font-size:13px;color:#9fb3c8;font-weight:600;margin:0 0 6px">枝のトグル（on/off で Ybus を編集）</div>' +
                    '<input id="ybus-sim-filter" placeholder="線名 / バス番号で絞り込み…" style="width:100%;box-sizing:border-box;background:#1b2631;color:#fff;border:1px solid #34495e;border-radius:4px;padding:5px 8px;font-size:11px;margin:0 0 6px">' +
                    '<div id="ybus-sim-branchlist" style="max-height:340px;overflow-y:auto;border:1px solid #14202a;border-radius:3px"></div>' +
                    '<div style="font-size:10px;color:#7d8aa0;margin-top:6px">枝をオフにすると非零パターン・密度・次数・連結成分数が即時に再計算されます。クリックで両端バスをハイライト。</div>' +
                '</div>' +
            '</div>' +
        '</div>';

        state.canvas = $("ybus-sim-canvas");
        state.ctx = state.canvas.getContext("2d");

        $("ybus-sim-region").addEventListener("change", function () { loadRegion(this.value); });
        $("ybus-sim-reset").addEventListener("click", function () {
            if (!state.model) return;
            for (var i = 0; i < state.model.links.length; i++) state.model.links[i].enabled = true;
            renderBranchList(); onModelChanged();
        });
        $("ybus-sim-fit").addEventListener("click", function () { fitView(); draw(); });
        $("ybus-sim-filter").addEventListener("input", function () { renderBranchList(); });

        setupCanvas();
        return true;
    }

    // ──────────────────────────────────────────────────────────────
    //  Init (lazy, on first Ybus tab activation)
    // ──────────────────────────────────────────────────────────────
    function init() {
        if (state.inited) return;
        if (!mount()) return;
        state.inited = true;
        loadRegion(state.region);
    }

    function setupTabHook() {
        document.querySelectorAll('.tab-btn[data-tab="tab-ybus"]').forEach(function (btn) {
            btn.addEventListener("click", function () {
                // defer so the panel is visible & sized before canvas math
                setTimeout(function () {
                    init();
                    if (state.inited && state.model) { fitView(); draw(); }
                }, 30);
            });
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", setupTabHook);
    } else {
        setupTabHook();
    }

    // expose for debugging / verification
    window.YbusSim = {
        init: init,
        load: loadRegion,
        stats: function () { return state.model ? computeStats(state.model) : null; },
        toggle: function (lid, on) {
            if (!state.model) return;
            var L = state.model.links[lid];
            if (L) { L.enabled = (on != null) ? on : !L.enabled; renderBranchList(); onModelChanged(); }
        },
        state: state
    };
})();
