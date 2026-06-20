/**
 * Japan Power Grid - Power Flow Visualization (static, pre-computed)
 *
 * Loads pre-computed DC/AC power flow results and renders:
 *  - Loading heatmap (line color by loading %)
 *  - Flow direction (arrows showing power flow, width by MW)
 *  - Thermal heatmap (line width + color emphasis by loading %)
 *  - Voltage heatmap (bus voltage or angle)
 *  - Base grid background (all voltage classes from grid_map.js)
 */

(function () {
    "use strict";

    var pfState = {
        region: null,
        mode: "ac",
        viz: "loading",
        summary: null,
        busLayer: null,
        lineLayer: null,
        arrowLayer: null,
        gridLayer: null,   // base grid background
        routeLayers: [],   // per-kV real-route layers (eager 500+275 kV)
        tierLayers: {},    // kv -> L.GeoJSON (on-demand lower tiers)
        ringLayer: null,   // backbone ring highlight layer
        active: false,
        busData: null,
        lineData: null,
        showGrid: true,
        showLines: true,
        showBuses: true,
        otherFreqLayer: null,   // other-frequency reference overlay (not solved)
        showOtherFreq: false,
    };

    // ── Real-route tier config ──
    // 500/275/154 kV load eagerly (154 is the sub-transmission backbone the
    // 66 kV programme targets — PLAN_66KV); 110/77/66 stay on-demand for
    // payload, but user toggles now PERSIST across mode switches instead of
    // being force-unchecked (the "66 kV disappeared" report, 2026-06-11).
    // DB②(2026-06-19): 全国基幹のデータソースを旧縮約(powerflow/routes_*・2189バス)→
    // 正典(powerflow_full/national_overview_*)へ。gen_national_overview_from_full.py が
    // 全規模AC結果(17,333バス)から電圧帯別に生成(再solveなし・kv付与=端点99%+名前100%)。
    // tier UI(下位電圧の on-demand 表示)はそのまま温存。プロパティは loading_pct。
    var ROUTE_TIERS = [
        { kv: 500, file: "national_overview_500kv.geojson", zIdx: 444, col: "#cc0000", wt: 3.5, eager: true  },
        { kv: 275, file: "national_overview_275kv.geojson", zIdx: 443, col: "#0044cc", wt: 2.5, eager: true  },
        { kv: 154, file: "national_overview_154kv.geojson", zIdx: 442, col: "#007733", wt: 1.6, eager: true  },
        { kv: 110, file: "national_overview_110kv.geojson", zIdx: 441, col: "#885500", wt: 1.2, eager: false },
        { kv: 77,  file: "national_overview_77kv.geojson",  zIdx: 440, col: "#660077", wt: 1.0, eager: false },
        { kv: 66,  file: "national_overview_66kv.geojson",  zIdx: 439, col: "#334455", wt: 0.8, eager: false },
    ];

    function routeWeight(loading, kv) {
        var base = kv >= 500 ? 3.5 : kv >= 275 ? 2.5 : kv >= 154 ? 1.6 : 1.0;
        if (loading >= 100) return base * 1.8;
        if (loading >= 70)  return base * 1.4;
        if (loading >= 50)  return base * 1.2;
        return base;
    }

    function initRoutePanes() {
        if (!window.map) return;
        ROUTE_TIERS.forEach(function(t) {
            var pId = "routePane" + t.kv;
            if (!window.map.getPane(pId)) {
                var p = window.map.createPane(pId);
                p.style.zIndex = t.zIdx;
            }
        });
        // Ring highlight pane sits above all route panes (zIndex 448, below substations)
        if (!window.map.getPane("ringPane")) {
            var rp = window.map.createPane("ringPane");
            rp.style.zIndex = 448;
        }
    }

    function removeRouteLayers() {
        pfState.routeLayers.forEach(function(rl) {
            if (rl && window.map && window.map.hasLayer(rl)) window.map.removeLayer(rl);
        });
        pfState.routeLayers = [];
        Object.keys(pfState.tierLayers).forEach(function(kv) {
            var layer = pfState.tierLayers[kv];
            if (layer && window.map) window.map.removeLayer(layer);
        });
        pfState.tierLayers = {};
        if (pfState.ringLayer && window.map) {
            window.map.removeLayer(pfState.ringLayer);
            pfState.ringLayer = null;
        }
        // NOTE: tier checkboxes are deliberately NOT reset — checked lower
        // tiers (110/77/66) reload below so the layers survive mode/region
        // switches (they used to vanish silently: 2026-06-11 user report).
        [110, 77, 66].forEach(function(kv) {
            var cb = document.getElementById("pf-tier-" + kv);
            if (cb && cb.checked) setTimeout(function() { pfLoadTier(kv); }, 0);
        });
    }

    // ── Color scales ──

    var LOADING_COLORS = [
        [0,   "#2ecc71"],
        [30,  "#27ae60"],
        [50,  "#f1c40f"],
        [70,  "#e67e22"],
        [90,  "#e74c3c"],
        [120, "#c0392b"],
        [200, "#8e44ad"],
    ];

    function loadingColor(pct) {
        pct = Math.min(Math.max(pct, 0), 200);
        for (var i = LOADING_COLORS.length - 1; i >= 0; i--) {
            if (pct >= LOADING_COLORS[i][0]) return LOADING_COLORS[i][1];
        }
        return LOADING_COLORS[0][1];
    }

    function loadingWeight(pct) {
        if (pct >= 100) return 4;
        if (pct >= 50)  return 3;
        return 2;
    }

    function thermalWeight(pct) {
        if (pct >= 120) return 8;
        if (pct >= 90)  return 6;
        if (pct >= 70)  return 5;
        if (pct >= 50)  return 4;
        if (pct >= 30)  return 3;
        return 2;
    }

    function flowWeight(p_mw) {
        var abs = Math.abs(p_mw);
        if (abs >= 500) return 5;
        if (abs >= 200) return 4;
        if (abs >= 50)  return 3;
        return 2;
    }

    function flowColor(p_mw) {
        var abs = Math.abs(p_mw);
        if (abs >= 500) return "#e74c3c";
        if (abs >= 200) return "#e67e22";
        if (abs >= 50)  return "#f1c40f";
        if (abs >= 10)  return "#27ae60";
        return "#2ecc71";
    }

    function vmColor(vm_pu) {
        if (vm_pu == null || isNaN(vm_pu)) return "#7f8c8d";  // 未収束/データなし=灰(健全と誤認させない)
        if (vm_pu >= 0.99) return "#2ecc71";
        if (vm_pu >= 0.97) return "#27ae60";
        if (vm_pu >= 0.95) return "#f1c40f";
        if (vm_pu >= 0.90) return "#e67e22";
        if (vm_pu >= 0.80) return "#e74c3c";
        return "#8e44ad";
    }

    function vmRadius(vm_pu) {
        if (vm_pu == null || isNaN(vm_pu)) return 3;  // 未収束/データなし=小さめ
        if (vm_pu >= 0.95) return 4;
        if (vm_pu >= 0.85) return 5;
        return 6;
    }

    function angleColor(va_deg) {
        // Voltage angle is modular (period 360°). Wrap to (-180, 180] before
        // coloring so disconnected-island angles (e.g. -5944°) are judged on
        // their true physical magnitude instead of always saturating red.
        var wrapped = ((va_deg % 360) + 540) % 360 - 180;
        var abs = Math.abs(wrapped);
        if (abs < 5)   return "#2ecc71";
        if (abs < 15)  return "#f1c40f";
        if (abs < 30)  return "#e67e22";
        return "#e74c3c";
    }

    // Synthetic (inferred) reconnection lines are drawn dashed + dimmer so
    // they read as inferred bridges, not observed OSM geometry.
    function isSynthetic(feature) {
        return !!(feature && feature.properties && feature.properties.synthetic);
    }

    var VOLTAGE_COLORS = {
        500: "#e74c3c", 275: "#e67e22", 220: "#d4a017",
        187: "#f1c40f", 154: "#2ecc71", 132: "#27ae60",
        110: "#1abc9c", 100: "#16a085", 77: "#3498db",
        66: "#2980b9",
    };

    function voltageClassColor(kv) {
        if (VOLTAGE_COLORS[kv]) return VOLTAGE_COLORS[kv];
        if (kv >= 500) return "#e74c3c";
        if (kv >= 275) return "#e67e22";
        if (kv >= 154) return "#2ecc71";
        if (kv >= 66)  return "#2980b9";
        return "#7f8c8d";
    }

    // ── Geometry helpers ──

    function lineMidpoint(coords) {
        if (coords.length === 2) {
            return {
                latlng: [(coords[0][1] + coords[1][1]) / 2, (coords[0][0] + coords[1][0]) / 2],
                segIdx: 0,
            };
        }
        var lengths = [];
        var total = 0;
        for (var i = 1; i < coords.length; i++) {
            var dx = coords[i][0] - coords[i-1][0];
            var dy = coords[i][1] - coords[i-1][1];
            var d = Math.sqrt(dx * dx + dy * dy);
            lengths.push(d);
            total += d;
        }
        var half = total / 2;
        var acc = 0;
        for (var j = 0; j < lengths.length; j++) {
            if (acc + lengths[j] >= half) {
                var frac = (half - acc) / lengths[j];
                var lon = coords[j][0] + frac * (coords[j+1][0] - coords[j][0]);
                var lat = coords[j][1] + frac * (coords[j+1][1] - coords[j][1]);
                return { latlng: [lat, lon], segIdx: j };
            }
            acc += lengths[j];
        }
        var last = coords.length - 1;
        return {
            latlng: [(coords[0][1] + coords[last][1]) / 2, (coords[0][0] + coords[last][0]) / 2],
            segIdx: 0,
        };
    }

    function segmentBearing(coords, segIdx) {
        var c0 = coords[segIdx];
        var c1 = coords[segIdx + 1];
        var lon1 = c0[0] * Math.PI / 180;
        var lat1 = c0[1] * Math.PI / 180;
        var lon2 = c1[0] * Math.PI / 180;
        var lat2 = c1[1] * Math.PI / 180;
        var dLon = lon2 - lon1;
        var y = Math.sin(dLon) * Math.cos(lat2);
        var x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
        var brng = Math.atan2(y, x) * 180 / Math.PI;
        return (brng + 360) % 360;
    }

    // ── Load summary ──

    async function loadSummary() {
        try {
            var res = await fetch(PF_DIR + "summary.json?v=" + Date.now());
            if (!res.ok) return null;
            var data = await res.json();
            // 全規模summaryは regions{} にネスト。per-region に展開し、旧コードが読む
            // フィールド名へマップ(name_ja / ac_vm_min など)。無い統計は欠損のまま
            // (resultItem が省略表示)。
            var regions = data.regions || data;
            for (var rk in regions) {
                var x = regions[rk];
                if (!x || typeof x !== "object") continue;
                if (x.name_ja == null) x.name_ja = PF_JA[rk] || rk;
                if (x.ac_vm_min == null && x.vm_min != null) x.ac_vm_min = x.vm_min;
                if (x.ac_vm_max == null && x.vm_max != null) x.ac_vm_max = x.vm_max;
                if (x.n_active_buses == null) x.n_active_buses = x.n_buses;
                if (x.n_lines == null) x.n_lines = x.n_lines_exported;
            }
            return regions;
        } catch (e) {
            console.error("Failed to load PF summary:", e);
            return null;
        }
    }

    // ── Region list ──

    var ALL_REGIONS = [
        "hokkaido","tohoku","tokyo","chubu","hokuriku",
        "kansai","chugoku","shikoku","kyushu","okinawa",
    ];

    // DB3(2026-06-18): 潮流タブの per-region / "all" 詳細表示を全規模(built正典)へ。
    // = docs/data/powerflow_full/(17,333バス・全バス・AC・縮約なし)。
    // national_backbone(500/275概観)/national_zonal(同期島)は別モデルゆえ旧データ据置。
    var PF_DIR = "./data/powerflow_full/";
    var PF_JA = {hokkaido:"北海道",tohoku:"東北",tokyo:"東京",chubu:"中部",hokuriku:"北陸",
                 kansai:"関西",chugoku:"中国",shikoku:"四国",kyushu:"九州",okinawa:"沖縄"};

    function buildRegionSelect(summary) {
        var sel = document.getElementById("pf-region");
        if (!sel) return;
        sel.innerHTML = "";
        sel.disabled = false;

        var allOpt = document.createElement("option");
        allOpt.value = "all";
        allOpt.textContent = "全国（地域詳細・統合）";
        sel.appendChild(allOpt);

        // Separate-granularity feature: the national 500/275 kV backbone model
        // (matpower, ~2189 buses) — intentionally a coarser, different model
        // than the per-region detailed (snapped) networks.
        var bbOpt = document.createElement("option");
        bbOpt.value = "national_backbone";
        bbOpt.textContent = "全国基幹（500/275kV 概観・別モデル）";
        sel.appendChild(bbOpt);

        // National zonal: 各同期島(hokkaido / east 50Hz / west 60Hz / okinawa)を
        // 連系線付きの単一系統として解いた正典(powerflow_full・全規模AC)を地域別に
        // 切り出してマージ。DB②(2026-06-20): 旧 powerflow_national(west DC固定)を廃し、
        // powerflow_full の全島AC収束結果へ置換(west も AC OK)。
        var nzOpt = document.createElement("option");
        nzOpt.value = "national_zonal";
        nzOpt.textContent = "全国ゾーン（同期島統合・全規模AC）";
        sel.appendChild(nzOpt);

        for (var i = 0; i < ALL_REGIONS.length; i++) {
            var r = ALL_REGIONS[i];
            var info = summary[r];
            if (!info) continue;
            var opt = document.createElement("option");
            opt.value = r;
            var ac = info.ac_converged ? "AC OK" : "AC FAIL";
            opt.textContent = info.name_ja + " (" + r + ") — " + ac;
            sel.appendChild(opt);
        }

        sel.addEventListener("change", function () {
            pfState.region = this.value;
            // DB②(2026-06-20): 正典 powerflow_full は west を含む全同期島が AC 収束する
            // ため、旧来の DC 固定を解除し AC で全島表示する。
            if (this.value === "national_zonal") {
                pfState.mode = "ac";
                var ms = document.getElementById("pf-mode");
                if (ms) ms.value = "ac";
            }
            runPF();
        });
    }

    // ── Enable controls ──

    function enableControls() {
        var modeSelect = document.getElementById("pf-mode");
        var vizSelect = document.getElementById("pf-viz");
        var runBtn = document.getElementById("btn-run-pf");

        if (modeSelect) {
            modeSelect.disabled = false;
            modeSelect.addEventListener("change", function () {
                pfState.mode = this.value;
                runPF();
            });
        }
        if (vizSelect) {
            vizSelect.disabled = false;
            vizSelect.addEventListener("change", function () {
                pfState.viz = this.value;
                if (pfState.lineData) {
                    removePFOverlays();
                    renderPFLayers(pfState.busData, pfState.lineData, pfState.mode);
                    if (pfState.region === "all") {
                        showAllRegionsResults(pfState.mode, Object.keys(pfState.summary).length);
                    } else {
                        showResults(pfState.region, pfState.mode, pfState.summary[pfState.region], true);
                    }
                }
            });
        }
        if (runBtn) {
            runBtn.disabled = false;
            runBtn.textContent = "Run Power Flow";
            runBtn.addEventListener("click", function () {
                runPF();
            });
        }

        // Layer toggles
        var gridCb = document.getElementById("pf-layer-grid");
        var linesCb = document.getElementById("pf-layer-lines");
        var busesCb = document.getElementById("pf-layer-buses");

        if (gridCb) {
            gridCb.addEventListener("change", function () {
                pfState.showGrid = this.checked;
                updatePFLayerVisibility();
            });
        }
        if (linesCb) {
            linesCb.addEventListener("change", function () {
                pfState.showLines = this.checked;
                updatePFLayerVisibility();
            });
        }
        if (busesCb) {
            busesCb.addEventListener("change", function () {
                pfState.showBuses = this.checked;
                updatePFLayerVisibility();
            });
        }
        var ofCb = document.getElementById("pf-layer-otherfreq");
        if (ofCb) {
            ofCb.addEventListener("change", function () {
                pfState.showOtherFreq = this.checked;
                if (pfState.showOtherFreq && !pfState.otherFreqLayer && pfState.region) {
                    loadOtherFreqLayer(pfState.region);
                }
                updatePFLayerVisibility();
            });
        }
    }

    // Other-frequency equipment physically present in the region slice but
    // belonging to the other synchronous system (e.g. TEPCO 50 Hz lines on
    // the Izu peninsula inside the 60 Hz chubu slice). Shown as a dashed
    // reference overlay — deliberately NOT part of the AC solve.
    async function loadOtherFreqLayer(region) {
        if (!window.map) return;
        try {
            var r = await fetch("./data/powerflow/" + region +
                                "_other_freq_lines.geojson?v=" + Date.now());
            if (!r.ok) return;
            var data = await r.json();
            if (!data.features || !data.features.length) return;
            pfState.otherFreqLayer = L.geoJSON(data, {
                style: { color: "#888888", weight: 1.3, opacity: 0.8,
                         dashArray: "6 5" },
                onEachFeature: function (f, layer) {
                    var pr = f.properties || {};
                    layer.bindPopup(
                        "<b>" + (pr.name || "(unnamed)") + "</b><br>" +
                        "operator: " + (pr.operator || "?") + "<br>" +
                        "voltage: " + (pr.voltage || "?") +
                        "  frequency: " + (pr.frequency || "(untagged)") + "<br>" +
                        "<i>" + (pr.note || "") + "</i>");
                },
            });
            if (pfState.showOtherFreq) window.map.addLayer(pfState.otherFreqLayer);
        } catch (e) { /* reference layer is best-effort */ }
    }

    function updatePFLayerVisibility() {
        if (!window.map) return;

        // Base grid layer
        if (pfState.gridLayer) {
            if (pfState.showGrid && !window.map.hasLayer(pfState.gridLayer)) {
                window.map.addLayer(pfState.gridLayer);
            } else if (!pfState.showGrid && window.map.hasLayer(pfState.gridLayer)) {
                window.map.removeLayer(pfState.gridLayer);
            }
        }
        // PF line layer
        if (pfState.lineLayer) {
            if (pfState.showLines && !window.map.hasLayer(pfState.lineLayer)) {
                window.map.addLayer(pfState.lineLayer);
            } else if (!pfState.showLines && window.map.hasLayer(pfState.lineLayer)) {
                window.map.removeLayer(pfState.lineLayer);
            }
        }
        // Arrow layer
        if (pfState.arrowLayer) {
            if (pfState.showLines && !window.map.hasLayer(pfState.arrowLayer)) {
                window.map.addLayer(pfState.arrowLayer);
            } else if (!pfState.showLines && window.map.hasLayer(pfState.arrowLayer)) {
                window.map.removeLayer(pfState.arrowLayer);
            }
        }
        // Other-frequency reference overlay
        if (pfState.otherFreqLayer) {
            if (pfState.showOtherFreq && !window.map.hasLayer(pfState.otherFreqLayer)) {
                window.map.addLayer(pfState.otherFreqLayer);
            } else if (!pfState.showOtherFreq && window.map.hasLayer(pfState.otherFreqLayer)) {
                window.map.removeLayer(pfState.otherFreqLayer);
            }
        }
        // Bus layer
        if (pfState.busLayer) {
            if (pfState.showBuses && !window.map.hasLayer(pfState.busLayer)) {
                window.map.addLayer(pfState.busLayer);
            } else if (!pfState.showBuses && window.map.hasLayer(pfState.busLayer)) {
                window.map.removeLayer(pfState.busLayer);
            }
        }
    }

    // ── Run PF visualization ──

    async function runPF() {
        var region = pfState.region;
        var mode = pfState.mode;
        if (!region || !pfState.summary) return;

        clearAllPFLayers();
        pfState.busData = null;
        pfState.lineData = null;

        // Separate-granularity features kept side by side:
        //  - "national_backbone": coarse 500/275 kV matpower overview (~2189 buses)
        //  - "all": detailed per-region (snapped) networks merged
        if (region === "national_backbone") {
            await runPFNational();
            return;
        }
        if (region === "national_zonal") {
            await runPFNationalZonal(mode);
            return;
        }
        if (region === "all") {
            await runPFAllRegions(mode);
            return;
        }

        // 全規模(built正典)は AC のみエクスポート → per-region は AC 固定。
        mode = "ac";
        var info = pfState.summary[region];
        if (!info) return;

        var converged = info.ac_converged;

        if (!converged) {
            showResults(region, mode, info, false);
            return;
        }

        var cb = "?v=" + Date.now();
        try {
            var busRes = await fetch(PF_DIR + region + "_ac_buses.geojson" + cb);
            var lineRes = await fetch(PF_DIR + region + "_ac_lines.geojson" + cb);

            if (!busRes.ok || !lineRes.ok) {
                showResults(region, mode, info, false);
                return;
            }

            var busData = await busRes.json();
            var lineData = await lineRes.json();

            pfState.busData = busData;
            pfState.lineData = lineData;

            // Show base grid background for this region
            showBaseGrid(region);
            if (pfState.showOtherFreq) loadOtherFreqLayer(region);

            renderPFLayers(busData, lineData, mode);
            showResults(region, mode, info, true);

            if (typeof selectRegion === "function") {
                selectRegion(region);
            }

        } catch (e) {
            console.error("PF load error:", e);
            showResults(region, mode, info, false);
        }
    }

    // Load national backbone overview (500/275 kV) from CANONICAL powerflow_full (17,333-bus AC).
    // DB②(2026-06-19): 旧 psdat 縮約 2189 バスを廃止し、全規模 AC の既存結果から抽出(再solveなし)。
    async function runPFNational() {
        var cb = "?v=" + Date.now();
        try {
            if (window.setStatus) window.setStatus("全国基幹概観 読み込み中... (500/275 kV・正典)");
            removeRouteLayers();
            removePFOverlays();
            initRoutePanes();
            showBaseGrid("all");

            // ── Bus voltage layer (all 2189 buses) ──────────────────────────
            var busRes = await fetch("./data/powerflow_full/national_overview_buses.geojson" + cb);
            if (busRes.ok) {
                var busData = await busRes.json();
                pfState.busData = busData;
                pfState.busLayer = L.geoJSON(busData, {
                    pointToLayer: function(feature, latlng) {
                        var vm  = feature.properties.vm_pu;  // null/NaN は健全1.0に化けさせない
                        var kv  = feature.properties.vn_kv || 66;
                        var r   = kv >= 500 ? 5 : kv >= 275 ? 4 : kv >= 154 ? 3 : 2;
                        return L.circleMarker(latlng, {
                            pane:        "substationPane",
                            radius:      r,
                            fillColor:   vmColor(vm),
                            color:       "#fff",
                            weight:      0.6,
                            fillOpacity: 0.9,
                        });
                    },
                    onEachFeature: busPopup,
                }).addTo(window.map);
            }

            // ── Real-route line layers (voltage-tiered) ──────────────────────
            // Eager: 500+275 kV (backbone). Others: skip by default.
            var eagerTiers = ROUTE_TIERS.filter(function(t) { return t.eager; });
            var fetches = eagerTiers.map(async function(tier) {
                try {
                    var r = await fetch("./data/powerflow_full/" + tier.file + cb);
                    if (!r.ok) return;
                    var data = await r.json();
                    var layer = L.geoJSON(data, {
                        style: function(feature) {
                            var ld = feature.properties.loading_pct || 0;
                            if (ld > 1) {
                                return {
                                    color:   loadingColor(ld),
                                    weight:  routeWeight(ld, tier.kv),
                                    opacity: 0.88,
                                    pane:    "routePane" + tier.kv,
                                };
                            }
                            // low-load: tier color, semi-transparent
                            return {
                                color:   tier.col,
                                weight:  tier.wt * 0.55,
                                opacity: 0.30,
                                pane:    "routePane" + tier.kv,
                            };
                        },
                        onEachFeature: function(feature, lyr) {
                            var p  = feature.properties;
                            var ld = (p.loading_pct || 0).toFixed(1);
                            lyr.bindPopup(
                                "<b>" + (p.name || "—") + "</b><br>" +
                                tier.kv + " kV | " + (p.region || "—") +
                                (p.tie ? " | <span style='color:#ff3b6b'>連系線</span>" : "") + "<br>" +
                                "潮流率: " + ld + "%" +
                                (ld > 0 ? "" : " <span style='color:#888'>(低負荷/未計算)</span>")
                            );
                        },
                        pane: "routePane" + tier.kv,
                    }).addTo(window.map);
                    pfState.routeLayers.push(layer);
                } catch(e) {
                    console.warn("Route load error:", tier.file, e);
                }
            });
            await Promise.all(fetches);
            // リング構造ハイライト(backbone_ring)は旧縮約モデル特有で正典に対応物が無いため
            // DB②で廃止。エリア間連系線は national_overview_* 各線の tie フラグで識別できる。

            if (window.setStatus) window.setStatus("全国基幹概観 表示完了 (500/275kV・正典17,333バス由来)");
            // ── Results panel: 正典 national_overview_buses から集計。捏造定数は使わない ──
            var feats = (pfState.busData && pfState.busData.features) || [];
            var nBus = feats.length;
            var vmin = Infinity, vmax = -Infinity, kvSet = {};
            for (var bi = 0; bi < feats.length; bi++) {
                var pr = feats[bi].properties || {};
                var v = pr.vm_pu;
                if (typeof v === "number" && isFinite(v)) {
                    if (v < vmin) vmin = v;
                    if (v > vmax) vmax = v;
                }
                if (pr.vn_kv != null) kvSet[pr.vn_kv] = 1;
            }
            var nLevels = Object.keys(kvSet).length;
            var el = document.getElementById("pf-results-content");
            if (el) {
                el.innerHTML =
                    "<b>全国基幹概観 — 500/275 kV（正典 full 由来）</b><br>" +
                    "バス数(≥154kV): " + (nBus ? nBus.toLocaleString() : "—") + "<br>" +
                    "電圧レベル数: " + (nLevels || "—") + " 種<br>" +
                    "電圧 Vm range: " + (isFinite(vmin) ? "[" + vmin.toFixed(2) + ", " + vmax.toFixed(2) + "] pu" : "—") + "<br>" +
                    '<div style="margin-top:6px;font-size:10px;color:#aaa">' +
                    "全規模AC(17,333バス・縮約なし)の結果から抽出。枝色=潮流率(loading)。" +
                    "下位電圧(110/77/66kV)はチェックで追加表示。</div>";
            }
            var sec = document.getElementById("pf-results-section");
            if (sec) sec.style.display = "";
            if (window.map) window.map.fitBounds([[24, 123], [46, 146]]);
        } catch(e) {
            console.error("National PF (routed) error:", e);
        }
    }

    // ── On-demand lower-voltage tier loading ──────────────────────────────────

    async function pfLoadTier(kv) {
        if (pfState.tierLayers[kv]) return;  // already loaded
        var tier = null;
        for (var i = 0; i < ROUTE_TIERS.length; i++) {
            if (ROUTE_TIERS[i].kv === kv) { tier = ROUTE_TIERS[i]; break; }
        }
        if (!tier || !window.map) return;

        initRoutePanes();
        if (window.setStatus) window.setStatus(kv + " kV ルート読み込み中...");
        var cb = "?v=" + Date.now();
        try {
            var res = await fetch("./data/powerflow_full/" + tier.file + cb);
            if (!res.ok) return;
            var data = await res.json();
            var layer = L.geoJSON(data, {
                style: function(feature) {
                    var ld = feature.properties.loading_pct || 0;
                    if (ld > 1) {
                        return {
                            color:   loadingColor(ld),
                            weight:  routeWeight(ld, kv),
                            opacity: 0.82,
                            pane:    "routePane" + kv,
                        };
                    }
                    return {
                        color:   tier.col,
                        weight:  tier.wt * 0.6,
                        opacity: 0.28,
                        pane:    "routePane" + kv,
                    };
                },
                onEachFeature: function(feature, lyr) {
                    var p  = feature.properties;
                    var ld = (p.loading_pct || 0).toFixed(1);
                    lyr.bindPopup(
                        "<b>" + (p.name || "—") + "</b><br>" +
                        kv + " kV | " + (p.region || "—") +
                        (p.tie ? " | <span style='color:#ff3b6b'>連系線</span>" : "") + "<br>" +
                        "潮流率: " + ld + "%" +
                        (p.loading_pct > 1 ? "" : " <span style='color:#888'>(低負荷/未計算)</span>")
                    );
                },
                pane: "routePane" + kv,
            }).addTo(window.map);
            pfState.tierLayers[kv] = layer;
            if (window.setStatus) window.setStatus(kv + " kV ルート表示完了");
        } catch(e) {
            console.warn("pfLoadTier error kv=" + kv, e);
        }
    }

    function pfUnloadTier(kv) {
        var layer = pfState.tierLayers[kv];
        if (layer && window.map) window.map.removeLayer(layer);
        delete pfState.tierLayers[kv];
    }

    // Called from HTML checkboxes: pfToggleTier(154, true/false)
    window.pfToggleTier = function(kv, checked) {
        if (checked) pfLoadTier(kv);
        else pfUnloadTier(kv);
    };

    // Toggle backbone ring highlight layer
    window.pfToggleRing = function(checked) {
        if (!pfState.ringLayer || !window.map) return;
        if (checked) pfState.ringLayer.addTo(window.map);
        else window.map.removeLayer(pfState.ringLayer);
    };

    async function runPFAllRegions(mode) {
        mode = "ac";   // 全規模(built正典)は AC のみ
        var cb = "?v=" + Date.now();
        var allBusFeatures = [];
        var allLineFeatures = [];
        var loadedCount = 0;
        var missingRegions = [];

        var fetches = ALL_REGIONS.map(async function (r) {
            var info = pfState.summary[r];
            if (!info) return;
            var converged = info.ac_converged;
            if (!converged) return;

            try {
                var busRes = await fetch(PF_DIR + r + "_ac_buses.geojson" + cb);
                var lineRes = await fetch(PF_DIR + r + "_ac_lines.geojson" + cb);
                if (!busRes.ok || !lineRes.ok) {
                    var miss = [];
                    if (!busRes.ok) miss.push("buses");
                    if (!lineRes.ok) miss.push("lines");
                    missingRegions.push(r + " (" + miss.join("+") + ")");
                    console.warn("PF data missing for " + r + ": " + miss.join("+"));
                    return;
                }

                var busData = await busRes.json();
                var lineData = await lineRes.json();

                if (busData.features) allBusFeatures = allBusFeatures.concat(busData.features);
                if (lineData.features) allLineFeatures = allLineFeatures.concat(lineData.features);
                loadedCount++;
            } catch (e) {
                missingRegions.push(r + " (error)");
                console.error("PF load error for " + r + ":", e);
            }
        });

        await Promise.all(fetches);
        pfState.missingRegions = missingRegions;

        var mergedBus = { type: "FeatureCollection", features: allBusFeatures };
        var mergedLine = { type: "FeatureCollection", features: allLineFeatures };

        pfState.busData = mergedBus;
        pfState.lineData = mergedLine;

        showBaseGrid("all");
        renderPFLayers(mergedBus, mergedLine, mode);
        showAllRegionsResults(mode, loadedCount);

        if (window.map) {
            window.map.fitBounds([[24, 123], [46, 146]]);
        }
    }

    // National zonal: per-region slices of the synchronous-island solutions,
    // merged across all regions. DB②(2026-06-20)で正典 powerflow_full(全規模AC・
    // 全島収束)に置換。各島は連系線付きの単一系統として solve 済み(per-region に切出)。
    async function runPFNationalZonal(mode) {
        var cb = "?v=" + Date.now();
        // DB②(2026-06-20): 旧 powerflow_national(縮約・west DC固定)→ 正典 powerflow_full
        // (全規模AC・全島収束)。summary は per-island だが regions{} に per-region の
        // island/ac_converged/vm を持つので、それを per-region サマリとして使う。
        var natDir = "./data/powerflow_full/";

        var natSummary = pfState.nationalSummary;
        if (!natSummary) {
            try {
                var sres = await fetch(natDir + "summary.json" + cb);
                var sj = sres.ok ? await sres.json() : {};
                natSummary = sj.regions || sj;   // powerflow_full は regions 配下が per-region
            } catch (e) {
                natSummary = {};
            }
            pfState.nationalSummary = natSummary;
        }

        var allBusFeatures = [];
        var allLineFeatures = [];
        var loadedCount = 0;
        var missingRegions = [];

        var fetches = ALL_REGIONS.map(async function (r) {
            var info = natSummary[r];
            // If summary absent, still attempt the file (the data may exist).
            if (info) {
                var converged = mode === "dc" ? info.dc_converged : info.ac_converged;
                if (!converged) return;
            }
            try {
                var busRes = await fetch(natDir + r + "_" + mode + "_buses.geojson" + cb);
                var lineRes = await fetch(natDir + r + "_" + mode + "_lines.geojson" + cb);
                if (!busRes.ok || !lineRes.ok) {
                    missingRegions.push(r);
                    return;
                }
                var busData = await busRes.json();
                var lineData = await lineRes.json();
                if (busData.features) allBusFeatures = allBusFeatures.concat(busData.features);
                if (lineData.features) allLineFeatures = allLineFeatures.concat(lineData.features);
                loadedCount++;
            } catch (e) {
                missingRegions.push(r + " (error)");
                console.error("National-zonal PF load error for " + r + ":", e);
            }
        });

        await Promise.all(fetches);
        pfState.missingRegions = missingRegions;

        var mergedBus = { type: "FeatureCollection", features: allBusFeatures };
        var mergedLine = { type: "FeatureCollection", features: allLineFeatures };

        pfState.busData = mergedBus;
        pfState.lineData = mergedLine;

        showBaseGrid("all");
        renderPFLayers(mergedBus, mergedLine, mode);
        showNationalZonalResults(mode, loadedCount, natSummary);

        if (window.map) {
            window.map.fitBounds([[24, 123], [46, 146]]);
        }
    }

    function showNationalZonalResults(mode, loadedCount, natSummary) {
        var section = document.getElementById("pf-results-section");
        var content = document.getElementById("pf-results-content");
        if (!section || !content) return;
        section.style.display = "block";

        var totalBuses = 0;
        var islands = {};
        for (var i = 0; i < ALL_REGIONS.length; i++) {
            var info = natSummary[ALL_REGIONS[i]];
            if (!info) continue;
            totalBuses += info.n_buses || 0;
            var isl = info.island || "?";
            if (!islands[isl]) islands[isl] = { ac: false, regions: 0 };
            islands[isl].ac = islands[isl].ac || !!info.ac_converged;
            islands[isl].regions++;
        }

        var html = "";
        var missing = pfState.missingRegions || [];
        if (missing.length) {
            html += '<div style="margin:0 0 10px;padding:8px 10px;border-radius:4px;' +
                'background:rgba(243,156,18,0.14);border:1px solid #f39c12">';
            html += '<div style="font-size:0.74rem;font-weight:600;color:#f39c12;margin-bottom:4px">' +
                '&#9888; 一部地域のデータが欠落</div>';
            html += '<div style="font-size:0.7rem;color:#d68910;line-height:1.5">次の地域は ' +
                mode.toUpperCase() + ' データなし: <b>' + missing.join("、 ") + '</b></div></div>';
        }

        // 電圧範囲・合成線・シャント数を集計（per-region のキー名は run_national_powerflow.py 由来）
        var vmMin = Infinity, vmMax = -Infinity, sumSyn = 0, sumShunt = 0, hasVm = 0;
        var failRegions = [];
        for (var r = 0; r < ALL_REGIONS.length; r++) {
            var info2 = natSummary[ALL_REGIONS[r]];
            if (!info2) continue;
            if (mode === "ac" && !info2.ac_converged) failRegions.push(ALL_REGIONS[r]);
            // powerflow_full の regions は vm_min/vm_max、旧 national は ac_vm_min/max。両対応。
            var rvmin = (typeof info2.ac_vm_min === "number") ? info2.ac_vm_min : info2.vm_min;
            var rvmax = (typeof info2.ac_vm_max === "number") ? info2.ac_vm_max : info2.vm_max;
            if (typeof rvmin === "number") { vmMin = Math.min(vmMin, rvmin); hasVm++; }
            if (typeof rvmax === "number") { vmMax = Math.max(vmMax, rvmax); }
            if (typeof info2.n_synthetic_lines === "number") sumSyn += info2.n_synthetic_lines;
            if (typeof info2.n_shunt_comp === "number") sumShunt += info2.n_shunt_comp;
        }

        html += '<div class="result-grid">';
        html += resultItem("Mode", mode.toUpperCase() + " (National zonal)");
        html += resultItem("Regions", loadedCount + "/10");
        html += resultItem("Island buses", totalBuses);
        if (mode === "ac" && hasVm > 0 && isFinite(vmMin) && isFinite(vmMax)) {
            html += resultItem("Voltage range",
                vmMin.toFixed(3) + " – " + vmMax.toFixed(3) + " pu");
        }
        if (sumSyn > 0) html += resultItem("Synthetic lines", sumSyn);
        if (sumShunt > 0) html += resultItem("Q shunts", sumShunt);
        var islNames = Object.keys(islands);
        for (var k = 0; k < islNames.length; k++) {
            var d = islands[islNames[k]];
            html += resultItem(islNames[k] + " island",
                (d.ac ? "AC OK" : "AC FAIL") + " (" + d.regions + " reg.)");
        }
        html += "</div>";
        if (mode === "ac" && failRegions.length) {
            html += '<div style="margin-top:8px;padding:6px 10px;border-radius:4px;' +
                'background:rgba(231,76,60,0.12);border:1px solid #c0392b;font-size:0.7rem;line-height:1.5">' +
                '<b style="color:#ff8a80">AC 未収束</b>: ' + failRegions.join("、") +
                '（下位網の品質限界。<a href="./WEST_AC_ANALYSIS.md" target="_blank" ' +
                'style="color:#f39c12">詳細</a>）</div>';
        }
        html += '<div class="pf-info" style="font-size:0.7rem;margin-top:8px">' +
            '各同期島（北海道 / 東 50Hz / 西 60Hz / 沖縄）を連系線付きの単一系統として解いた' +
            '正典(全規模AC・17,333バス)を地域別に切り出した結果です。west も含め全島 AC 収束。';
        html += '</div>';
        html += buildLegend(mode);
        content.innerHTML = html;
    }

    // ── Base grid background ──

    function showBaseGrid(region) {
        // Remove existing
        if (pfState.gridLayer && window.map) {
            window.map.removeLayer(pfState.gridLayer);
            pfState.gridLayer = null;
        }

        // Use rawLineData from grid_map.js (already loaded, no extra fetch)
        var data = window.rawLineData;
        if (!data || !data.features) return;

        // Filter by region if not "all"
        var features = data.features;
        if (region !== "all") {
            features = features.filter(function (f) {
                return f.properties._region === region;
            });
        }

        var filtered = { type: "FeatureCollection", features: features };

        pfState.gridLayer = L.geoJSON(filtered, {
            style: function (feature) {
                var kv = feature.properties._voltage_kv || 0;
                return {
                    color: voltageClassColor(kv),
                    weight: 1,
                    opacity: 0.25,
                };
            },
            interactive: false,  // no popups, no click events — pure background
        });

        if (pfState.showGrid) {
            pfState.gridLayer.addTo(window.map);
            // Ensure it's behind PF layers
            pfState.gridLayer.bringToBack();
        }
    }

    // ── Render PF layers based on viz mode ──

    function renderPFLayers(busData, lineData, mode) {
        removePFOverlays();
        if (!window.map) return;

        var viz = pfState.viz;

        if (viz === "voltage") {
            renderVoltageMode(busData, lineData, mode);
        } else {
            if (viz === "loading") {
                renderLoadingHeatmap(lineData);
            } else if (viz === "flow") {
                renderFlowDirection(lineData);
            } else if (viz === "thermal") {
                renderThermalHeatmap(lineData);
            }
        }

        updatePFLayerVisibility();
    }

    // ── Voltage mode ──

    function renderVoltageMode(busData, lineData, mode) {
        // Lines as thin context (slightly more visible than base grid)
        if (lineData && lineData.features && lineData.features.length > 0) {
            pfState.lineLayer = L.geoJSON(lineData, {
                style: function () {
                    return { color: "#888", weight: 1.5, opacity: 0.4 };
                },
                onEachFeature: linePopup,
            }).addTo(window.map);
        }

        if (busData && busData.features && busData.features.length > 0) {
            pfState.busLayer = L.geoJSON(busData, {
                pointToLayer: function (feature, latlng) {
                    var vm = feature.properties.vm_pu;  // null/NaN は健全1.0に化けさせない
                    var r = mode === "ac" ? vmRadius(vm) : 4;
                    var color = mode === "ac" ? vmColor(vm) : angleColor(feature.properties.va_deg || 0);
                    return L.circleMarker(latlng, {
                        pane: "substationPane",
                        radius: r,
                        fillColor: color,
                        color: "#fff",
                        weight: 0.6,
                        fillOpacity: 0.9,
                    });
                },
                onEachFeature: busPopup,
            }).addTo(window.map);
        }
    }

    // ── Loading heatmap ──

    function renderLoadingHeatmap(lineData) {
        if (!lineData || !lineData.features || lineData.features.length === 0) return;

        pfState.lineLayer = L.geoJSON(lineData, {
            style: function (feature) {
                var loading = feature.properties.loading_pct || 0;
                return {
                    color: loadingColor(loading),
                    weight: loadingWeight(loading),
                    opacity: isSynthetic(feature) ? 0.5 : 0.85,
                    dashArray: isSynthetic(feature) ? "5,5" : null,
                };
            },
            onEachFeature: linePopup,
        }).addTo(window.map);
    }

    // ── Flow direction ──

    function renderFlowDirection(lineData) {
        if (!lineData || !lineData.features || lineData.features.length === 0) return;

        pfState.lineLayer = L.geoJSON(lineData, {
            style: function (feature) {
                var p_mw = feature.properties.p_mw || 0;
                return {
                    color: flowColor(p_mw),
                    weight: flowWeight(p_mw),
                    opacity: isSynthetic(feature) ? 0.45 : 0.7,
                    dashArray: isSynthetic(feature) ? "5,5" : null,
                };
            },
            onEachFeature: function (feature, layer) {
                var p = feature.properties;
                var dir = p.p_mw >= 0 ? "from &rarr; to" : "to &rarr; from";
                layer.bindPopup(
                    "<b>" + (p.name || "Line") + "</b><br>" +
                    "P: " + p.p_mw + " MW (" + dir + ")<br>" +
                    "Loading: " + p.loading_pct + "%"
                );
            },
        }).addTo(window.map);

        // Arrow markers
        var arrowGroup = L.layerGroup();
        lineData.features.forEach(function (feature) {
            var coords = feature.geometry.coordinates;
            if (!coords || coords.length < 2) return;
            var p_mw = feature.properties.p_mw || 0;
            if (Math.abs(p_mw) < 0.1) return;

            var midInfo = lineMidpoint(coords);
            var brng = segmentBearing(coords, midInfo.segIdx);
            if (p_mw < 0) brng = (brng + 180) % 360;

            var color = flowColor(p_mw);
            var size = Math.abs(p_mw) >= 200 ? 14 : Math.abs(p_mw) >= 50 ? 11 : 8;

            var svg = '<svg width="' + size + '" height="' + size + '" viewBox="0 0 20 20" ' +
                'style="transform:rotate(' + brng + 'deg)">' +
                '<polygon points="10,2 18,16 10,12 2,16" fill="' + color + '" stroke="#fff" stroke-width="1"/>' +
                '</svg>';

            var icon = L.divIcon({
                html: svg,
                className: "flow-arrow",
                iconSize: [size, size],
                iconAnchor: [size / 2, size / 2],
            });

            L.marker(midInfo.latlng, { icon: icon, interactive: false }).addTo(arrowGroup);
        });

        pfState.arrowLayer = arrowGroup.addTo(window.map);
    }

    // ── Thermal heatmap ──

    function renderThermalHeatmap(lineData) {
        if (!lineData || !lineData.features || lineData.features.length === 0) return;

        pfState.lineLayer = L.geoJSON(lineData, {
            style: function (feature) {
                var loading = feature.properties.loading_pct || 0;
                return {
                    color: loadingColor(loading),
                    weight: thermalWeight(loading),
                    opacity: isSynthetic(feature) ? 0.5 : 0.9,
                    lineCap: "round",
                    lineJoin: "round",
                    dashArray: isSynthetic(feature) ? "5,5" : null,
                };
            },
            onEachFeature: function (feature, layer) {
                var p = feature.properties;
                var status = "";
                if (p.loading_pct >= 100) status = " <b style='color:#e74c3c'>[OVERLOAD]</b>";
                else if (p.loading_pct >= 80) status = " <b style='color:#e67e22'>[HIGH]</b>";
                layer.bindPopup(
                    "<b>" + (p.name || "Line") + "</b>" + status + "<br>" +
                    "Loading: " + p.loading_pct + "%<br>" +
                    "P: " + Math.abs(p.p_mw) + " MW"
                );
            },
        }).addTo(window.map);
    }

    // ── Popup helpers ──

    function linePopup(feature, layer) {
        var p = feature.properties;
        layer.bindPopup(
            "<b>" + (p.name || "Line") + "</b><br>" +
            "Loading: " + p.loading_pct + "%<br>" +
            "P: " + p.p_mw + " MW"
        );
    }

    function busPopup(feature, layer) {
        var p = feature.properties;
        var bad = function(x){ return x == null || (typeof x === "number" && isNaN(x)); };
        var vmTxt = bad(p.vm_pu) ? '<span style="color:#e74c3c">未収束/データなし</span>'
                                 : p.vm_pu + " pu";
        var vaTxt = bad(p.va_deg) ? "—" : p.va_deg + "&deg;";
        layer.bindPopup(
            "<b>" + (p.name || "Bus") + "</b><br>" +
            "V: " + vmTxt + "<br>" +
            "Angle: " + vaTxt + "<br>" +
            "Vn: " + (p.vn_kv != null ? p.vn_kv + " kV" : "—")
        );
    }

    // ── Clear layers ──

    function removePFOverlays() {
        // Remove PF result layers (not base grid)
        if (pfState.lineLayer && window.map) {
            window.map.removeLayer(pfState.lineLayer);
            pfState.lineLayer = null;
        }
        if (pfState.busLayer && window.map) {
            window.map.removeLayer(pfState.busLayer);
            pfState.busLayer = null;
        }
        if (pfState.arrowLayer && window.map) {
            window.map.removeLayer(pfState.arrowLayer);
            pfState.arrowLayer = null;
        }
        if (pfState.otherFreqLayer && window.map) {
            window.map.removeLayer(pfState.otherFreqLayer);
            pfState.otherFreqLayer = null;
        }
        removeRouteLayers();
    }

    function clearAllPFLayers() {
        removePFOverlays();
        if (pfState.gridLayer && window.map) {
            window.map.removeLayer(pfState.gridLayer);
            pfState.gridLayer = null;
        }
    }

    // ── Results display ──

    // Surface model-validity issues so a "converged" flag on a fragmented or
    // non-physical solution is not silently presented as a healthy grid.
    function pfValidityWarnings(mode, info) {
        var warns = [];
        var nc = info.n_components;
        if (nc && nc > 1) {
            var iso = (info.n_buses != null && info.n_active_buses != null)
                ? (info.n_buses - info.n_active_buses) : null;
            warns.push("ネットワークが <b>" + nc + " 個</b>に断片化しています。潮流は最大連結成分のみで求解され、" +
                (iso != null ? ("孤立 <b>" + iso + " バス</b>は無効化（地図非表示）") : "孤立部は無効化") +
                "。再接続(reconstruction)は未適用です。");
        }
        if (mode === "ac" && info.ac_converged) {
            if (info.ac_vm_min != null && info.ac_vm_min < 0.80) {
                warns.push("最低電圧 <b>" + info.ac_vm_min + " pu</b> は非物理的（電圧崩壊水準）。収束フラグは立っていますが解が無効の可能性。");
            }
            if (info.ac_max_loading != null && info.ac_max_loading > 100) {
                warns.push("最大潮流率 <b>" + info.ac_max_loading + "%</b>（熱容量超過）。");
            }
        }
        if (mode === "dc" && info.dc_converged) {
            var amax = Math.max(Math.abs(info.dc_va_min || 0), Math.abs(info.dc_va_max || 0));
            if (amax > 180) {
                warns.push("位相角 <b>" + info.dc_va_min + "° ~ " + info.dc_va_max + "°</b> が ±180° を超過。切断された部分系統で求解した兆候。");
            }
            if (info.dc_max_loading != null && info.dc_max_loading > 100) {
                warns.push("最大潮流率 <b>" + info.dc_max_loading + "%</b>（熱容量超過）。");
            }
        }
        if (!warns.length) return "";
        var html = '<div style="margin:0 0 10px;padding:8px 10px;border-radius:4px;' +
            'background:rgba(231,76,60,0.12);border:1px solid #e74c3c">';
        html += '<div style="font-size:0.74rem;font-weight:600;color:#e74c3c;margin-bottom:4px">' +
            '&#9888; モデル妥当性の警告</div>';
        html += '<ul style="margin:0;padding-left:16px;font-size:0.7rem;color:#c0392b;line-height:1.5">';
        for (var i = 0; i < warns.length; i++) html += '<li>' + warns[i] + '</li>';
        html += '</ul></div>';
        return html;
    }

    function showResults(region, mode, info, hasData) {
        var section = document.getElementById("pf-results-section");
        var content = document.getElementById("pf-results-content");
        if (!section || !content) return;

        section.style.display = "block";

        var modeLabel = mode.toUpperCase();
        var converged = mode === "dc" ? info.dc_converged : info.ac_converged;

        var html = pfValidityWarnings(mode, info);
        html += '<div class="result-grid">';
        html += resultItem("Convergence", converged ? "OK" : "FAIL", converged ? "success" : "fail");
        html += resultItem("Mode", modeLabel);
        html += resultItem("Buses", info.n_buses);
        html += resultItem("Lines", info.n_lines);
        html += resultItem("Generators", info.n_gens);
        html += resultItem("Transformers", info.n_trafos);
        html += resultItem("Active Buses", info.n_active_buses);
        html += resultItem("Components", info.n_components);
        html += resultItem("Load", Math.round(info.total_load_mw) + " MW");
        html += resultItem("Generation", Math.round(info.total_gen_mw) + " MW");

        if (mode === "dc" && info.dc_converged) {
            html += resultItem("Max Loading", info.dc_max_loading + "%");
            html += resultItem("Angle Range", info.dc_va_min + "&deg; ~ " + info.dc_va_max + "&deg;");
        } else if (mode === "ac" && info.ac_converged) {
            html += resultItem("AC Loss", info.ac_loss_mw + " MW");
            html += resultItem("Max Loading", info.ac_max_loading + "%");
            html += resultItem("V min", info.ac_vm_min + " pu");
            html += resultItem("V max", info.ac_vm_max + " pu");
            html += resultItem("Solver", info.ac_solver);
        }
        html += "</div>";

        html += buildLegend(mode);

        content.innerHTML = html;
    }

    function buildLegend(mode) {
        var viz = pfState.viz;
        var html = '<div style="margin-top:12px">';

        if (viz === "loading" || viz === "thermal") {
            var label = viz === "thermal" ? "Thermal Loading (line width = loading)" : "Line Loading";
            html += '<div style="font-size:0.72rem;color:#7f8c8d;margin-bottom:4px">' + label + '</div>';
            html += '<div style="display:flex;gap:4px;flex-wrap:wrap">';
            var legendItems = [
                ["< 30%", "#2ecc71"], ["30-50%", "#27ae60"], ["50-70%", "#f1c40f"],
                ["70-90%", "#e67e22"], ["> 90%", "#e74c3c"], ["> 120%", "#8e44ad"],
            ];
            var h = viz === "thermal" ? "5px" : "3px";
            for (var i = 0; i < legendItems.length; i++) {
                html += '<span style="font-size:0.68rem;display:flex;align-items:center;gap:3px">' +
                    '<span style="width:16px;height:' + h + ';background:' + legendItems[i][1] + ';display:inline-block;border-radius:1px"></span>' +
                    legendItems[i][0] + '</span>';
            }
            html += '</div>';
        }

        if (viz === "flow") {
            html += '<div style="font-size:0.72rem;color:#7f8c8d;margin-bottom:4px">Power Flow (arrow = direction)</div>';
            html += '<div style="display:flex;gap:4px;flex-wrap:wrap">';
            var flowLegend = [
                ["< 10 MW", "#2ecc71"], ["10-50 MW", "#27ae60"], ["50-200 MW", "#f1c40f"],
                ["200-500 MW", "#e67e22"], ["> 500 MW", "#e74c3c"],
            ];
            for (var j = 0; j < flowLegend.length; j++) {
                html += '<span style="font-size:0.68rem;display:flex;align-items:center;gap:3px">' +
                    '<span style="width:16px;height:3px;background:' + flowLegend[j][1] + ';display:inline-block;border-radius:1px"></span>' +
                    flowLegend[j][0] + '</span>';
            }
            html += '</div>';
        }

        if (viz === "voltage") {
            if (mode === "ac") {
                html += '<div style="font-size:0.72rem;color:#7f8c8d;margin-bottom:4px">Bus Voltage (AC)</div>';
                html += '<div style="display:flex;gap:4px;flex-wrap:wrap">';
                var vLegend = [
                    ["> 0.99 pu", "#2ecc71"], ["0.95-0.99", "#f1c40f"],
                    ["0.90-0.95", "#e67e22"], ["< 0.90", "#e74c3c"], ["< 0.80", "#8e44ad"],
                ];
                for (var k = 0; k < vLegend.length; k++) {
                    html += '<span style="font-size:0.68rem;display:flex;align-items:center;gap:3px">' +
                        '<span style="width:8px;height:8px;background:' + vLegend[k][1] + ';display:inline-block;border-radius:50%"></span>' +
                        vLegend[k][0] + '</span>';
                }
                html += '</div>';
            } else {
                html += '<div style="font-size:0.72rem;color:#7f8c8d;margin-bottom:4px">Bus Angle (DC)</div>';
                html += '<div style="display:flex;gap:4px;flex-wrap:wrap">';
                var aLegend = [
                    ["< 5&deg;", "#2ecc71"], ["5-15&deg;", "#f1c40f"],
                    ["15-30&deg;", "#e67e22"], ["> 30&deg;", "#e74c3c"],
                ];
                for (var m = 0; m < aLegend.length; m++) {
                    html += '<span style="font-size:0.68rem;display:flex;align-items:center;gap:3px">' +
                        '<span style="width:8px;height:8px;background:' + aLegend[m][1] + ';display:inline-block;border-radius:50%"></span>' +
                        aLegend[m][0] + '</span>';
                }
                html += '</div>';
            }
        }

        // Base grid legend (always shown when grid is visible)
        if (pfState.showGrid) {
            html += '<div style="font-size:0.72rem;color:#7f8c8d;margin:6px 0 4px">Base Grid (voltage class)</div>';
            html += '<div style="display:flex;gap:4px;flex-wrap:wrap">';
            var gLegend = [
                ["500 kV", "#e74c3c"], ["275 kV", "#e67e22"], ["154 kV", "#2ecc71"],
                ["77 kV", "#3498db"], ["66 kV", "#2980b9"],
            ];
            for (var n = 0; n < gLegend.length; n++) {
                html += '<span style="font-size:0.68rem;display:flex;align-items:center;gap:3px">' +
                    '<span style="width:16px;height:1px;background:' + gLegend[n][1] + ';display:inline-block;opacity:0.5"></span>' +
                    gLegend[n][0] + '</span>';
            }
            html += '</div>';
        }

        // Synthetic (inferred) reconnection line note — applies to line-based viz.
        if (viz === "loading" || viz === "thermal" || viz === "flow") {
            html += '<div style="font-size:0.68rem;color:#7f8c8d;margin-top:6px;display:flex;align-items:center;gap:4px">' +
                '<span style="width:18px;height:0;border-top:2px dashed #aaa;display:inline-block"></span>' +
                '破線 = 推定（再接続）線 / inferred bridge</div>';
        }

        html += '</div>';
        return html;
    }

    function resultItem(label, value, cls) {
        // 欠損値(null/undefined/NaN)は行ごと省略 — 全規模summaryに無い項目を
        // 「NaN MW」「undefined」等で出さない(捏造的な空欄を避ける)。
        if (value == null) return "";
        var sv = String(value);
        if (sv.indexOf("undefined") !== -1 || sv.indexOf("NaN") !== -1 ||
            sv === "null" || sv.indexOf("null ") === 0) return "";
        var valClass = cls ? ' class="value ' + cls + '"' : ' class="value"';
        return '<div class="result-item"><div class="label">' + label + '</div><div' + valClass + '>' + value + '</div></div>';
    }

    // ── All-region PF results ──

    function showAllRegionsResults(mode, loadedCount) {
        var section = document.getElementById("pf-results-section");
        var content = document.getElementById("pf-results-content");
        if (!section || !content) return;

        section.style.display = "block";

        var summary = pfState.summary;
        var totalBuses = 0, totalLines = 0, totalGens = 0, totalLoad = 0, totalGenMW = 0, totalLoss = 0;
        // 軽量summary(全規模)に無い統計は0として誤表示せず、利用可否を追跡し欠損は省略。
        var haveGens = false, haveLoad = false, haveGen = false, haveLoss = false;
        for (var i = 0; i < ALL_REGIONS.length; i++) {
            var info = summary[ALL_REGIONS[i]];
            if (!info) continue;
            totalBuses += info.n_active_buses || 0;
            totalLines += info.n_lines || 0;
            if (info.n_gens != null) { totalGens += info.n_gens; haveGens = true; }
            if (info.total_load_mw != null) { totalLoad += info.total_load_mw; haveLoad = true; }
            if (info.total_gen_mw != null) { totalGenMW += info.total_gen_mw; haveGen = true; }
            var lossv = (mode === "ac" ? info.ac_loss_mw : info.dc_loss_mw);
            if (lossv != null) { totalLoss += lossv; haveLoss = true; }
        }

        var html = "";
        var missing = pfState.missingRegions || [];
        if (missing.length) {
            html += '<div style="margin:0 0 10px;padding:8px 10px;border-radius:4px;' +
                'background:rgba(243,156,18,0.14);border:1px solid #f39c12">';
            html += '<div style="font-size:0.74rem;font-weight:600;color:#f39c12;margin-bottom:4px">' +
                '&#9888; 一部地域のデータが欠落</div>';
            html += '<div style="font-size:0.7rem;color:#d68910;line-height:1.5">次の地域は ' +
                mode.toUpperCase() + ' データが見つからず地図に表示されていません: <b>' +
                missing.join("、 ") + '</b></div></div>';
        }
        html += '<div class="result-grid">';
        html += resultItem("Mode", mode.toUpperCase() + " (All Japan)");
        html += resultItem("Regions", loadedCount + "/10");
        html += resultItem("Active Buses", totalBuses);
        html += resultItem("Lines", totalLines);
        html += resultItem("Generators", haveGens ? totalGens : null);
        html += resultItem("Load", haveLoad ? Math.round(totalLoad) + " MW" : null);
        html += resultItem("Generation", haveGen ? Math.round(totalGenMW) + " MW" : null);
        html += resultItem("Total Loss", haveLoss ? Math.round(totalLoss) + " MW" : null);
        html += "</div>";

        html += buildLegend(mode);

        content.innerHTML = html;
    }

    // ── All-region summary table ──

    function showAllRegionsSummary(summary) {
        var content = document.getElementById("pf-results-content");
        var section = document.getElementById("pf-results-section");
        if (!content || !section) return;

        section.style.display = "block";

        var html = '<table style="width:100%;border-collapse:collapse;font-size:0.72rem">';
        html += '<tr style="color:#7f8c8d;border-bottom:1px solid #0f3460">' +
            '<th style="text-align:left;padding:4px">Region</th>' +
            '<th>DC</th><th>AC</th>' +
            '<th>Buses</th><th>Gens</th>' +
            '<th>Loss(MW)</th></tr>';

        for (var i = 0; i < ALL_REGIONS.length; i++) {
            var r = ALL_REGIONS[i];
            var info = summary[r];
            if (!info) continue;
            var dcCell = info.dc_converged
                ? '<span style="color:#2ecc71">OK</span>'
                : '<span style="color:#e74c3c">FAIL</span>';
            var acCell = info.ac_converged
                ? '<span style="color:#2ecc71">OK</span>'
                : '<span style="color:#e74c3c">FAIL</span>';

            html += '<tr style="border-bottom:1px solid #16213e">' +
                '<td style="padding:3px 4px">' + info.name_ja + '</td>' +
                '<td style="text-align:center">' + dcCell + '</td>' +
                '<td style="text-align:center">' + acCell + '</td>' +
                '<td style="text-align:center">' + info.n_active_buses + '</td>' +
                '<td style="text-align:center">' + info.n_gens + '</td>' +
                '<td style="text-align:center">' + info.ac_loss_mw + '</td>' +
                '</tr>';
        }
        html += '</table>';

        content.innerHTML = html;
    }

    // ── Tab activation hook ──

    function setupTabHook() {
        document.querySelectorAll('.tab-btn[data-tab="tab-pf"]').forEach(function (btn) {
            btn.addEventListener("click", function () {
                pfState.active = true;
                if (!pfState.region && pfState.summary) {
                    var sel = document.getElementById("pf-region");
                    if (sel && sel.value) {
                        pfState.region = sel.value;
                    }
                }
                if (pfState.summary && !pfState.region) {
                    showAllRegionsSummary(pfState.summary);
                }
            });
        });

        document.querySelectorAll('.tab-btn:not([data-tab="tab-pf"])').forEach(function (btn) {
            btn.addEventListener("click", function () {
                pfState.active = false;
                clearAllPFLayers();
            });
        });
    }

    // ── Init ──

    document.addEventListener("DOMContentLoaded", async function () {
        var summary = await loadSummary();
        if (!summary) {
            var content = document.getElementById("pf-results-content");
            var section = document.getElementById("pf-results-section");
            if (content && section) {
                section.style.display = "block";
                content.innerHTML = '<div class="pf-info">Power flow data not available. Run:<br>' +
                    '<code style="font-size:0.75rem;color:#e94560;">PYTHONPATH=. python scripts/export_powerflow_pages.py</code></div>';
            }
            return;
        }

        pfState.summary = summary;
        buildRegionSelect(summary);
        enableControls();
        setupTabHook();
        // Panes created lazily in runPFNational (map may not be ready yet)

        showAllRegionsSummary(summary);
    });
})();
