/**
 * Japan Power Grid - Power Flow Visualization (static, pre-computed)
 *
 * Loads pre-computed DC/AC power flow results and renders:
 *  - Line loading heatmap (green → yellow → red)
 *  - Bus voltage magnitude heatmap
 *  - Summary statistics table
 */

(function () {
    "use strict";

    var pfState = {
        region: null,
        mode: "ac",
        summary: null,
        busLayer: null,
        lineLayer: null,
        active: false,
    };

    var LOADING_COLORS = [
        [0,   "#2ecc71"],  // green
        [30,  "#27ae60"],
        [50,  "#f1c40f"],  // yellow
        [70,  "#e67e22"],  // orange
        [90,  "#e74c3c"],  // red
        [120, "#c0392b"],
        [200, "#8e44ad"],  // purple (extreme)
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

    function vmColor(vm_pu) {
        if (vm_pu >= 0.99)  return "#2ecc71";
        if (vm_pu >= 0.97)  return "#27ae60";
        if (vm_pu >= 0.95)  return "#f1c40f";
        if (vm_pu >= 0.90)  return "#e67e22";
        if (vm_pu >= 0.80)  return "#e74c3c";
        return "#8e44ad";
    }

    function vmRadius(vm_pu) {
        if (vm_pu >= 0.95) return 4;
        if (vm_pu >= 0.85) return 5;
        return 6;
    }

    // ── Load summary ──

    async function loadSummary() {
        try {
            var res = await fetch("./data/powerflow/summary.json?v=" + Date.now());
            if (!res.ok) return null;
            return await res.json();
        } catch (e) {
            console.error("Failed to load PF summary:", e);
            return null;
        }
    }

    // ── Build region selector ──

    function buildRegionSelect(summary) {
        var sel = document.getElementById("pf-region");
        if (!sel) return;
        sel.innerHTML = "";
        sel.disabled = false;

        var regions = [
            "hokkaido","tohoku","tokyo","chubu","hokuriku",
            "kansai","chugoku","shikoku","kyushu","okinawa",
        ];

        for (var i = 0; i < regions.length; i++) {
            var r = regions[i];
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
            runPF();
        });
    }

    // ── Enable controls ──

    function enableControls() {
        var modeSelect = document.getElementById("pf-mode");
        var runBtn = document.getElementById("btn-run-pf");

        if (modeSelect) {
            modeSelect.disabled = false;
            modeSelect.addEventListener("change", function () {
                pfState.mode = this.value;
                runPF();
            });
        }
        if (runBtn) {
            runBtn.disabled = false;
            runBtn.textContent = "Run Power Flow";
            runBtn.addEventListener("click", function () {
                runPF();
            });
        }
    }

    // ── Run PF visualization ──

    async function runPF() {
        var region = pfState.region;
        var mode = pfState.mode;
        if (!region || !pfState.summary) return;

        var info = pfState.summary[region];
        if (!info) return;

        var converged = mode === "dc" ? info.dc_converged : info.ac_converged;

        // Clear existing PF layers
        clearPFLayers();

        if (!converged) {
            showResults(region, mode, info, false);
            return;
        }

        // Load GeoJSON
        var cb = "?v=" + Date.now();
        try {
            var busRes = await fetch("./data/powerflow/" + region + "_" + mode + "_buses.geojson" + cb);
            var lineRes = await fetch("./data/powerflow/" + region + "_" + mode + "_lines.geojson" + cb);

            if (!busRes.ok || !lineRes.ok) {
                showResults(region, mode, info, false);
                return;
            }

            var busData = await busRes.json();
            var lineData = await lineRes.json();

            renderPFLayers(busData, lineData, mode);
            showResults(region, mode, info, true);

            // Zoom to region
            if (typeof selectRegion === "function") {
                selectRegion(region);
            }

        } catch (e) {
            console.error("PF load error:", e);
            showResults(region, mode, info, false);
        }
    }

    function renderPFLayers(busData, lineData, mode) {
        clearPFLayers();
        if (!window.map) return;

        // Lines: loading heatmap
        if (lineData && lineData.features && lineData.features.length > 0) {
            pfState.lineLayer = L.geoJSON(lineData, {
                style: function (feature) {
                    var loading = feature.properties.loading_pct || 0;
                    return {
                        color: loadingColor(loading),
                        weight: loadingWeight(loading),
                        opacity: 0.85,
                    };
                },
                onEachFeature: function (feature, layer) {
                    var p = feature.properties;
                    layer.bindPopup(
                        "<b>" + (p.name || "Line") + "</b><br>" +
                        "Loading: " + p.loading_pct + "%<br>" +
                        "P: " + p.p_mw + " MW"
                    );
                },
            }).addTo(window.map);
        }

        // Buses: voltage heatmap (AC only, DC has vm_pu=1.0 everywhere)
        if (mode === "ac" && busData && busData.features && busData.features.length > 0) {
            pfState.busLayer = L.geoJSON(busData, {
                pointToLayer: function (feature, latlng) {
                    var vm = feature.properties.vm_pu || 1.0;
                    return L.circleMarker(latlng, {
                        pane: "substationPane",
                        radius: vmRadius(vm),
                        fillColor: vmColor(vm),
                        color: "#fff",
                        weight: 0.6,
                        fillOpacity: 0.9,
                    });
                },
                onEachFeature: function (feature, layer) {
                    var p = feature.properties;
                    layer.bindPopup(
                        "<b>" + (p.name || "Bus") + "</b><br>" +
                        "V: " + p.vm_pu + " pu<br>" +
                        "Angle: " + p.va_deg + "°<br>" +
                        "Vn: " + p.vn_kv + " kV"
                    );
                },
            }).addTo(window.map);
        }
    }

    function clearPFLayers() {
        if (pfState.lineLayer && window.map) {
            window.map.removeLayer(pfState.lineLayer);
            pfState.lineLayer = null;
        }
        if (pfState.busLayer && window.map) {
            window.map.removeLayer(pfState.busLayer);
            pfState.busLayer = null;
        }
    }

    // ── Results display ──

    function showResults(region, mode, info, hasData) {
        var section = document.getElementById("pf-results-section");
        var content = document.getElementById("pf-results-content");
        if (!section || !content) return;

        section.style.display = "block";

        var modeLabel = mode.toUpperCase();
        var converged = mode === "dc" ? info.dc_converged : info.ac_converged;

        var html = '<div class="result-grid">';
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
            html += resultItem("Angle Range", info.dc_va_min + "° ~ " + info.dc_va_max + "°");
        } else if (mode === "ac" && info.ac_converged) {
            html += resultItem("AC Loss", info.ac_loss_mw + " MW");
            html += resultItem("Max Loading", info.ac_max_loading + "%");
            html += resultItem("V min", info.ac_vm_min + " pu");
            html += resultItem("V max", info.ac_vm_max + " pu");
            html += resultItem("Solver", info.ac_solver);
        }
        html += "</div>";

        // Legend
        html += '<div style="margin-top:12px">';
        html += '<div style="font-size:0.72rem;color:#7f8c8d;margin-bottom:4px">Line Loading</div>';
        html += '<div style="display:flex;gap:4px;flex-wrap:wrap">';
        var legendItems = [
            ["< 30%", "#2ecc71"], ["30-50%", "#27ae60"], ["50-70%", "#f1c40f"],
            ["70-90%", "#e67e22"], ["> 90%", "#e74c3c"], ["> 120%", "#8e44ad"],
        ];
        for (var i = 0; i < legendItems.length; i++) {
            html += '<span style="font-size:0.68rem;display:flex;align-items:center;gap:3px">' +
                '<span style="width:16px;height:3px;background:' + legendItems[i][1] + ';display:inline-block;border-radius:1px"></span>' +
                legendItems[i][0] + '</span>';
        }
        html += '</div>';

        if (mode === "ac") {
            html += '<div style="font-size:0.72rem;color:#7f8c8d;margin:6px 0 4px">Bus Voltage</div>';
            html += '<div style="display:flex;gap:4px;flex-wrap:wrap">';
            var vLegend = [
                ["> 0.99", "#2ecc71"], ["0.95-0.99", "#f1c40f"],
                ["0.90-0.95", "#e67e22"], ["< 0.90", "#e74c3c"],
            ];
            for (var j = 0; j < vLegend.length; j++) {
                html += '<span style="font-size:0.68rem;display:flex;align-items:center;gap:3px">' +
                    '<span style="width:8px;height:8px;background:' + vLegend[j][1] + ';display:inline-block;border-radius:50%"></span>' +
                    vLegend[j][0] + ' pu</span>';
            }
            html += '</div>';
        }
        html += '</div>';

        content.innerHTML = html;
    }

    function resultItem(label, value, cls) {
        var valClass = cls ? ' class="value ' + cls + '"' : ' class="value"';
        return '<div class="result-item"><div class="label">' + label + '</div><div' + valClass + '>' + value + '</div></div>';
    }

    // ── All-region summary table ──

    function showAllRegionsSummary(summary) {
        var content = document.getElementById("pf-results-content");
        var section = document.getElementById("pf-results-section");
        if (!content || !section) return;

        section.style.display = "block";

        var regions = [
            "hokkaido","tohoku","tokyo","chubu","hokuriku",
            "kansai","chugoku","shikoku","kyushu","okinawa",
        ];

        var html = '<table style="width:100%;border-collapse:collapse;font-size:0.72rem">';
        html += '<tr style="color:#7f8c8d;border-bottom:1px solid #0f3460">' +
            '<th style="text-align:left;padding:4px">Region</th>' +
            '<th>DC</th><th>AC</th>' +
            '<th>Buses</th><th>Gens</th>' +
            '<th>Loss(MW)</th></tr>';

        for (var i = 0; i < regions.length; i++) {
            var r = regions[i];
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

        // Deactivate PF layers when switching to other tabs
        document.querySelectorAll('.tab-btn:not([data-tab="tab-pf"])').forEach(function (btn) {
            btn.addEventListener("click", function () {
                pfState.active = false;
                clearPFLayers();
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

        // Show summary immediately
        showAllRegionsSummary(summary);
    });
})();
