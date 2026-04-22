/**
 * Japan Power Grid Map - Static GitHub Pages version.
 *
 * Features:
 * - Layer visibility checkboxes (lines, substations, plants)
 * - Region filtering: click a region to show only its features
 * - Voltage tier files (275kv, 154kv, all) + client-side filter
 * - Plant category filter (utility / +IPP / all)
 * - Color modes: voltage class / region area
 */

// Voltage color scheme
const VOLTAGE_COLORS = {
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

// Region color scheme
const REGION_COLORS = {
    hokkaido: "#e6194b",
    tohoku:   "#3cb44b",
    tokyo:    "#4363d8",
    chubu:    "#f58231",
    hokuriku: "#911eb4",
    kansai:   "#42d4f4",
    chugoku:  "#f032e6",
    shikoku:  "#bfef45",
    kyushu:   "#fabebe",
    okinawa:  "#469990",
};
const REGION_NAMES_JA = {
    hokkaido: "\u5317\u6d77\u9053", tohoku: "\u6771\u5317", tokyo: "\u6771\u4eac",
    chubu: "\u4e2d\u90e8", hokuriku: "\u5317\u9678", kansai: "\u95a2\u897f",
    chugoku: "\u4e2d\u56fd", shikoku: "\u56db\u56fd", kyushu: "\u4e5d\u5dde",
    okinawa: "\u6c96\u7e04",
};
const REGION_ORDER = [
    "hokkaido","tohoku","tokyo","chubu","hokuriku",
    "kansai","chugoku","shikoku","kyushu","okinawa",
];

function voltageKvToBracket(kv) {
    if (kv >= 500) return 500;
    if (kv >= 275) return 275;
    if (kv >= 220) return 220;
    if (kv >= 187) return 187;
    if (kv >= 154) return 154;
    if (kv >= 132) return 132;
    if (kv >= 110) return 110;
    if (kv >= 77) return 77;
    if (kv >= 66) return 66;
    return 0;
}

function voltageColor(kv) {
    return VOLTAGE_COLORS[voltageKvToBracket(kv)] || "#cccccc";
}

function voltageLineWeight(kv) {
    if (kv >= 500) return 3;
    if (kv >= 275) return 2.5;
    if (kv >= 154) return 2;
    return 1.5;
}

// ── Voltage tier file mapping ──

function voltageTier(minKv) {
    if (minKv >= 500) return { suffix: "275kv", clientFilter: 500 };
    if (minKv >= 275) return { suffix: "275kv", clientFilter: 0 };
    if (minKv >= 154) return { suffix: "154kv", clientFilter: 0 };
    if (minKv >= 110) return { suffix: "all",   clientFilter: 110 };
    if (minKv >= 66)  return { suffix: "all",   clientFilter: 66 };
    return                    { suffix: "all",   clientFilter: 0 };
}

// Fuel type colors for power plants
const FUEL_COLORS = {
    nuclear: "#ff0000", coal: "#444444", gas: "#ff8800",
    oil: "#884400", hydro: "#0088ff", pumped_hydro: "#0044aa",
    wind: "#00cc88", solar: "#ffdd00", geothermal: "#cc4488",
    biomass: "#668833", waste: "#996633", tidal: "#006688",
    battery: "#aa00ff", unknown: "#999999",
};

// ── Map state ──

var map;
var substationLayer = null;
var lineLayer = null;
var plantLayer = null;
var legendControl = null;
var legendVisible = true;
var sidebarVisible = true;
var regionsData = [];

// Raw cached GeoJSON (before region filter)
var rawSubData = null;
var rawLineData = null;
var rawPlantData = null;

// Enriched data caches
var enrichedSubData = null;
var enrichedGenData = null;

// Per-tab state
var tabState = {
    voltage: { minKv: 275, region: "all" },
    region:  { minKv: 0,   region: "all" },
};
var selectedRegion = "all";
var plantFilter = "utility";
var colorMode = "voltage"; // "voltage" or "region"
var layerVisible = { lines: true, subs: true, plants: true };

// List panel state
var listSubsData = [];
var listLineData = [];
var listGenData = [];
var listCurrentTab = "subs";
var listCurrentSort = "name";
var listPanelVisible = true;

function initMap() {
    map = L.map("map", {
        center: [36.5, 137.0],
        zoom: 6,
        zoomControl: true,
        preferCanvas: true,
    });

    var cartoLayer = L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
        maxZoom: 19,
    });
    var osmLayer = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/">OpenStreetMap</a>',
        maxZoom: 19,
    });
    var satelliteLayer = L.tileLayer("https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}", {
        attribution: "Google",
        maxZoom: 20,
    });
    var gsiLayer = L.tileLayer("https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://maps.gsi.go.jp/development/ichiran.html">国土地理院</a>',
        maxZoom: 18,
    });
    var gsiPhotoLayer = L.tileLayer("https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg", {
        attribution: '&copy; <a href="https://maps.gsi.go.jp/development/ichiran.html">国土地理院</a>',
        maxZoom: 18,
    });
    cartoLayer.addTo(map);
    L.control.layers({
        "Dark (CartoDB)": cartoLayer,
        "OSM": osmLayer,
        "衛星 (Google)": satelliteLayer,
        "地図 (国土地理院)": gsiLayer,
        "航空写真 (国土地理院)": gsiPhotoLayer,
    }, null, { position: "topright", collapsed: true }).addTo(map);

    // Custom panes for z-ordering: substations & plants above lines
    map.createPane("substationPane").style.zIndex = 450;
    map.createPane("plantPane").style.zIndex = 460;

    updateLegend();
}

// ── Legend ──

function updateLegend() {
    if (legendControl) { map.removeControl(legendControl); legendControl = null; }

    legendControl = L.control({ position: "bottomright" });
    legendControl.onAdd = function () {
        var div = L.DomUtil.create("div", "legend");

        if (colorMode === "region") {
            div.innerHTML = "<h4>Region</h4>";
            for (var i = 0; i < REGION_ORDER.length; i++) {
                var rid = REGION_ORDER[i];
                div.innerHTML +=
                    '<div class="legend-item">' +
                    '<span class="legend-color" style="background:' + REGION_COLORS[rid] + '"></span>' +
                    REGION_NAMES_JA[rid] + '</div>';
            }
        } else {
            div.innerHTML = "<h4>Voltage Class</h4>";
            var voltages = [500, 275, 220, 187, 154, 132, 110, 77, 66];
            for (var j = 0; j < voltages.length; j++) {
                var kv = voltages[j];
                div.innerHTML +=
                    '<div class="legend-item">' +
                    '<span class="legend-color" style="background:' + VOLTAGE_COLORS[kv] + '"></span>' +
                    kv + ' kV</div>';
            }
        }

        // Plants legend (always shown)
        div.innerHTML += "<h4 style='margin-top:8px'>Power Plants</h4>";
        var fuelEntries = [
            ["nuclear","Nuclear"],["coal","Coal"],["gas","Gas"],["oil","Oil"],
            ["hydro","Hydro"],["wind","Wind"],["solar","Solar"],
            ["geothermal","Geothermal"],["biomass","Biomass"]
        ];
        for (var k = 0; k < fuelEntries.length; k++) {
            var fkey = fuelEntries[k][0], flabel = fuelEntries[k][1];
            div.innerHTML +=
                '<div class="legend-item">' +
                '<span class="legend-color" style="background:' + FUEL_COLORS[fkey] +
                ';height:6px;border-radius:50%"></span>' +
                flabel + '</div>';
        }
        return div;
    };
    legendControl.addTo(map);
}

// ── Tab switching ──

function initTabs() {
    document.querySelectorAll(".tab-btn").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var tabId = this.dataset.tab;
            document.querySelectorAll(".tab-btn").forEach(function (b) { b.classList.remove("active"); });
            document.querySelectorAll(".tab-panel").forEach(function (p) { p.classList.remove("active"); });
            this.classList.add("active");
            var panel = document.getElementById(tabId);
            if (panel) panel.classList.add("active");

            // Save current tab state before switching
            tabState[colorMode].region = selectedRegion;

            // Switch color mode based on tab
            var newMode = (tabId === "tab-area") ? "region" : "voltage";
            if (newMode !== colorMode) {
                colorMode = newMode;
                // Restore saved state for the new tab
                selectedRegion = tabState[newMode].region;
                setActiveRegionBtn(selectedRegion === "all" ? null : selectedRegion, "#region-list");
                setActiveRegionBtn(selectedRegion === "all" ? null : selectedRegion, "#area-region-list");
                updateLegend();
                loadData(tabState[newMode].minKv);
            }
        });
    });
}

// ── Filtering helpers ──

function filterByVoltage(geojson, minKv) {
    if (!minKv || minKv <= 0) return geojson;
    var filtered = geojson.features.filter(function (f) {
        var kv = f.properties._voltage_kv;
        return kv != null && kv >= minKv;
    });
    return { type: "FeatureCollection", features: filtered };
}

function filterByRegion(geojson, region) {
    if (!region || region === "all") return geojson;
    var filtered = geojson.features.filter(function (f) {
        return f.properties._region === region;
    });
    return { type: "FeatureCollection", features: filtered };
}

// ── Color helpers ──

function lineColor(feature) {
    if (colorMode === "region") {
        return REGION_COLORS[feature.properties._region] || "#cccccc";
    }
    return voltageColor(feature.properties._voltage_kv || 0);
}

function subColor(feature) {
    if (colorMode === "region") {
        return REGION_COLORS[feature.properties._region] || "#cccccc";
    }
    return voltageColor(feature.properties._voltage_kv || 0);
}

// ── Plant marker (canvas circleMarker for performance) ──

function plantMarker(latlng, fuel, mw) {
    var color = FUEL_COLORS[fuel] || FUEL_COLORS.unknown;
    var radius = mw >= 1000 ? 7 : mw >= 100 ? 5 : mw > 0 ? 3.5 : 2.5;
    return L.circleMarker(latlng, {
        pane: "plantPane",
        radius: radius,
        fillColor: color,
        color: "#000",
        weight: 1,
        opacity: 0.9,
        fillOpacity: 0.85,
    });
}

// ── Layer rendering ──

function renderLayers() {
    clearLayers();

    if (!rawSubData || !rawLineData) return;

    // Filter by region
    var subData = filterByRegion(rawSubData, selectedRegion);
    var lineData = filterByRegion(rawLineData, selectedRegion);

    // Lines
    if (layerVisible.lines) {
        try {
            lineLayer = L.geoJSON(lineData, {
                style: function (feature) {
                    var kv = feature.properties._voltage_kv || 0;
                    return {
                        color: lineColor(feature),
                        weight: voltageLineWeight(kv),
                        opacity: 0.7,
                    };
                },
                onEachFeature: function (feature, layer) {
                    var p = feature.properties;
                    var kv = p._voltage_kv ? p._voltage_kv + " kV" : "Unknown";
                    layer.bindPopup(
                        "<b>" + (p._display_name || "Unnamed") + "</b><br>" +
                        "Voltage: " + kv + "<br>" +
                        "Region: " + (p._region_ja || "")
                    );
                },
            }).addTo(map);
        } catch (e) { console.error("Lines render error:", e); }
    }

    // Substations (filter to Point only — some OSM ways are MultiPolygon)
    if (layerVisible.subs) {
        try {
            var subPoints = {
                type: "FeatureCollection",
                features: subData.features.filter(function (f) {
                    return f.geometry && f.geometry.type === "Point";
                }),
            };
            substationLayer = L.geoJSON(subPoints, {
                pane: "substationPane",
                pointToLayer: function (feature, latlng) {
                    var kv = feature.properties._voltage_kv || 0;
                    var bracket = voltageKvToBracket(kv);
                    var radius = bracket >= 500 ? 5 : bracket >= 275 ? 4 : 3;
                    return L.circleMarker(latlng, {
                        pane: "substationPane",
                        radius: radius,
                        fillColor: subColor(feature),
                        color: "#fff",
                        weight: 0.8,
                        fillOpacity: 0.9,
                    });
                },
                onEachFeature: function (feature, layer) {
                    try {
                        var p = feature.properties;
                        var coords = feature.geometry ? feature.geometry.coordinates : null;
                        var enriched = (coords && coords.length >= 2) ? lookupEnrichedSub(coords[0], coords[1]) : null;
                        if (enriched) {
                            layer.bindPopup(buildSubPopup(enriched), { maxWidth: 350 });
                        } else {
                            var kv = p._voltage_kv ? p._voltage_kv + " kV" : "Unknown";
                            layer.bindPopup(
                                "<b>" + (p._display_name || "Unnamed") + "</b><br>" +
                                "Voltage: " + kv + "<br>" +
                                "Region: " + (p._region_ja || "")
                            );
                        }
                    } catch (e) { console.warn("Sub popup error:", e); }
                },
            }).addTo(map);
        } catch (e) { console.error("Substations render error:", e); }
    }

    // Plants (canvas circleMarkers — all visible, no clustering)
    if (layerVisible.plants && rawPlantData) {
        try {
            var plantData = filterByRegion(rawPlantData, selectedRegion);
            plantLayer = L.geoJSON(plantData, {
                pointToLayer: function (feature, latlng) {
                    var p = feature.properties;
                    var fuel = p.fuel_type || "unknown";
                    var mw = p.capacity_mw || 0;
                    return plantMarker(latlng, fuel, mw);
                },
                onEachFeature: function (feature, layer) {
                    try {
                        var p = feature.properties;
                        var coords = feature.geometry ? feature.geometry.coordinates : null;
                        var enriched = (coords && coords.length >= 2) ? lookupEnrichedGen(coords[0], coords[1]) : null;
                        if (enriched) {
                            layer.bindPopup(buildGenPopup(enriched), { maxWidth: 350 });
                        } else {
                            var cap = p.capacity_mw ? p.capacity_mw + " MW" : "N/A";
                            layer.bindPopup(
                                "<b>" + (p._display_name || "Unnamed") + "</b><br>" +
                                "Fuel: " + (p.fuel_type || "unknown") + "<br>" +
                                "Capacity: " + cap + "<br>" +
                                "Region: " + (p._region_ja || "")
                            );
                        }
                    } catch (e) { console.warn("Plant popup error:", e); }
                },
            }).addTo(map);
        } catch (e) { console.error("Plants render error:", e); }
    }

    updateStatus();
    buildLists();
}

function updateStatus() {
    var subCount = substationLayer ? substationLayer.getLayers().length : 0;
    var lineCount = lineLayer ? lineLayer.getLayers().length : 0;
    var plantCount = plantLayer ? plantLayer.getLayers().length : 0;

    var regionLabel = "All regions";
    if (selectedRegion !== "all") {
        var r = regionsData.find(function (rd) { return rd.id === selectedRegion; });
        if (r) regionLabel = r.name_en + " (" + r.name_ja + ")";
    }

    var minKv = parseFloat((document.getElementById("min-kv") || {}).value || 275);
    var kvLabel = minKv > 0 ? " [" + minKv + " kV+]" : "";
    var modeLabel = colorMode === "region" ? " [Area]" : "";

    setStatus(regionLabel + kvLabel + modeLabel + ": " + subCount + " subs, " + lineCount + " lines, " + plantCount + " plants");
}

// ── Data loading ──

async function loadData(minKv) {
    if (minKv === undefined) {
        var sel = document.getElementById("min-kv");
        minKv = sel ? parseFloat(sel.value) : 275;
    }

    setStatus("Loading...");
    clearLayers();

    var tier = voltageTier(minKv);
    var cacheBust = "?v=" + Date.now();
    var linesFile = "./data/lines_" + tier.suffix + ".geojson" + cacheBust;
    var subsFile  = "./data/subs_"  + tier.suffix + ".geojson" + cacheBust;

    try {
        var responses = await Promise.all([
            fetch(subsFile),
            fetch(linesFile),
        ]);

        if (!responses[0].ok || !responses[1].ok) {
            setStatus("Failed to load data");
            return;
        }

        rawSubData  = await responses[0].json();
        rawLineData = await responses[1].json();

        // Apply client-side voltage filter if needed
        if (tier.clientFilter > 0) {
            rawSubData  = filterByVoltage(rawSubData, tier.clientFilter);
            rawLineData = filterByVoltage(rawLineData, tier.clientFilter);
        }

        // Load plants
        await loadPlantData();

        renderLayers();

        // Zoom
        if (selectedRegion === "all") {
            map.setView([36.5, 137.0], 6);
        } else {
            zoomToRegion(selectedRegion);
        }

    } catch (err) {
        setStatus("Error: " + err.message);
    }
}

async function loadPlantData() {
    rawPlantData = null;
    var cb = "?v=" + Date.now();

    try {
        var plantData;
        if (plantFilter === "utility") {
            var res = await fetch("./data/plants_utility.geojson" + cb);
            if (res.ok) plantData = await res.json();
        } else if (plantFilter === "ipp") {
            var responses = await Promise.all([
                fetch("./data/plants_utility.geojson" + cb),
                fetch("./data/plants_ipp.geojson" + cb),
            ]);
            if (responses[0].ok && responses[1].ok) {
                var d1 = await responses[0].json();
                var d2 = await responses[1].json();
                plantData = {
                    type: "FeatureCollection",
                    features: d1.features.concat(d2.features),
                };
            }
        } else {
            var res2 = await fetch("./data/plants_all.geojson" + cb);
            if (res2.ok) plantData = await res2.json();
        }
        rawPlantData = plantData || null;
    } catch (err) {
        console.error("Failed to load plants:", err);
    }
}

function zoomToRegion(region) {
    var r = regionsData.find(function (rd) { return rd.id === region; });
    if (!r || !r.bounding_box) return;
    var bb = r.bounding_box;
    map.fitBounds([
        [bb.lat_min, bb.lon_min],
        [bb.lat_max, bb.lon_max],
    ], { padding: [30, 30] });
}

function selectRegion(region) {
    selectedRegion = region || "all";
    tabState[colorMode].region = selectedRegion;
    // Update active button in both region lists
    setActiveRegionBtn(region, "#region-list");
    setActiveRegionBtn(region, "#area-region-list");
    renderLayers();

    if (selectedRegion === "all") {
        map.setView([36.5, 137.0], 6);
    } else {
        zoomToRegion(selectedRegion);
    }
}

function clearLayers() {
    if (substationLayer) { map.removeLayer(substationLayer); substationLayer = null; }
    if (lineLayer) { map.removeLayer(lineLayer); lineLayer = null; }
    if (plantLayer) { map.removeLayer(plantLayer); plantLayer = null; }
}

// ── Enriched data loaders ──

async function loadEnrichedData() {
    var cb = "?v=" + Date.now();
    try {
        var res = await fetch("./data/substations.geojson" + cb);
        if (res.ok) enrichedSubData = await res.json();
    } catch (e) { console.warn("No enriched substations:", e); }
    try {
        var res2 = await fetch("./data/generators.geojson" + cb);
        if (res2.ok) enrichedGenData = await res2.json();
    } catch (e) { console.warn("No enriched generators:", e); }
}

// ── Detail popup builders ──

function fmtNum(n) {
    if (n == null) return "-";
    if (typeof n === "number" && n >= 1000) return n.toLocaleString();
    return String(n);
}

function buildSubPopup(p) {
    var html = '<div class="detail-popup">';
    html += '<h3>' + (p.name || p._display_name || "(unnamed)") + '</h3>';
    var meta = [];
    if (p.operator) meta.push(p.operator);
    if (p.region_ja) meta.push(p.region_ja);
    if (meta.length) html += '<div class="popup-meta">' + meta.join(" | ") + '</div>';

    html += '<div class="popup-section"><div class="popup-section-title">Electrical</div><table>';
    var kvStr = p.voltage_kv != null ? p.voltage_kv + " kV" : "Unknown";
    if (p.voltage_source && p.voltage_source !== "osm") {
        kvStr += ' <span style="color:#e94560;font-size:0.68rem">(' + p.voltage_source.replace(/_/g," ") + ')</span>';
    }
    html += '<tr><td>Voltage</td><td>' + kvStr + '</td></tr>';
    if (p.voltage_label) html += '<tr><td>Class</td><td>' + p.voltage_label + '</td></tr>';
    if (p.frequency_hz) html += '<tr><td>Frequency</td><td>' + p.frequency_hz + ' Hz</td></tr>';
    if (p.rating) html += '<tr><td>Rating</td><td>' + p.rating + '</td></tr>';
    html += '</table></div>';

    html += '<div class="popup-section"><div class="popup-section-title">Classification</div><table>';
    if (p.category_ja) html += '<tr><td>Type</td><td>' + p.category_ja + '</td></tr>';
    if (p.substation_type) html += '<tr><td>OSM Type</td><td>' + p.substation_type + '</td></tr>';
    if (p.gas_insulated != null) html += '<tr><td>GIS</td><td>' + (p.gas_insulated ? "Yes" : "No") + '</td></tr>';
    html += '</table></div>';

    if (p.operator || p.operator_en) {
        html += '<div class="popup-section"><div class="popup-section-title">Operator</div><table>';
        if (p.operator) html += '<tr><td>Name</td><td>' + p.operator + '</td></tr>';
        if (p.operator_en) html += '<tr><td>English</td><td>' + p.operator_en + '</td></tr>';
        html += '</table></div>';
    }

    if (p.ref || p.addr_city || p.website) {
        html += '<div class="popup-section"><div class="popup-section-title">Reference</div><table>';
        if (p.ref) html += '<tr><td>Ref</td><td>' + p.ref + '</td></tr>';
        if (p.addr_city) html += '<tr><td>City</td><td>' + p.addr_city + '</td></tr>';
        if (p.website) html += '<tr><td>Web</td><td><a href="' + p.website + '" target="_blank" style="color:#3498db">Link</a></td></tr>';
        html += '</table></div>';
    }
    html += '</div>';
    return html;
}

function buildGenPopup(p) {
    var fuel = (p.fuel_type_ja || "") + " / " + (p.fuel_type_en || "");
    var html = '<div class="detail-popup">';
    html += '<h3>' + (p.name || "Unknown") + '</h3>';
    var meta = [];
    if (p.operator) meta.push(p.operator);
    if (p.region) meta.push(p.region);
    if (meta.length) html += '<div class="popup-meta">' + meta.join(" | ") + '</div>';

    html += '<div class="popup-section"><div class="popup-section-title">Basic</div><table>';
    html += '<tr><td>Fuel</td><td>' + fuel + '</td></tr>';
    html += '<tr><td>Capacity</td><td>' + fmtNum(p.capacity_mw) + ' MW</td></tr>';
    html += '<tr><td>P_min</td><td>' + fmtNum(p.p_min_mw) + ' MW</td></tr>';
    html += '<tr><td>Dispatchable</td><td>' + (p.dispatchable ? "Yes" : "No") + '</td></tr>';
    html += '</table></div>';

    html += '<div class="popup-section"><div class="popup-section-title">Ramp & Timing</div><table>';
    html += '<tr><td>Ramp Up</td><td>' + fmtNum(p.ramp_up_mw_per_h) + ' MW/h</td></tr>';
    html += '<tr><td>Ramp Down</td><td>' + fmtNum(p.ramp_down_mw_per_h) + ' MW/h</td></tr>';
    html += '<tr><td>Min Up Time</td><td>' + fmtNum(p.min_up_time_h) + ' h</td></tr>';
    html += '<tr><td>Min Down Time</td><td>' + fmtNum(p.min_down_time_h) + ' h</td></tr>';
    html += '<tr><td>Startup Time</td><td>' + fmtNum(p.startup_time_h) + ' h</td></tr>';
    html += '<tr><td>Shutdown Time</td><td>' + fmtNum(p.shutdown_time_h) + ' h</td></tr>';
    html += '</table></div>';

    html += '<div class="popup-section"><div class="popup-section-title">Costs (JPY)</div><table>';
    html += '<tr><td>Startup</td><td>' + fmtNum(p.startup_cost_jpy) + '</td></tr>';
    html += '<tr><td>Shutdown</td><td>' + fmtNum(p.shutdown_cost_jpy) + '</td></tr>';
    html += '<tr><td>Fuel</td><td>' + fmtNum(p.fuel_cost_per_mwh_jpy) + ' /MWh</td></tr>';
    html += '</table></div>';

    html += '<div class="popup-section"><div class="popup-section-title">Efficiency & Emissions</div><table>';
    html += '<tr><td>Heat Rate</td><td>' + fmtNum(p.heat_rate_kj_per_kwh) + ' kJ/kWh</td></tr>';
    html += '<tr><td>CO2</td><td>' + fmtNum(p.co2_intensity_kg_per_mwh) + ' kg/MWh</td></tr>';
    if (p.capacity_factor != null) html += '<tr><td>Capacity Factor</td><td>' + (p.capacity_factor * 100).toFixed(0) + '%</td></tr>';
    html += '</table></div>';

    html += '<div class="popup-section"><div class="popup-section-title">Reliability & Lifecycle</div><table>';
    if (p.planned_outage_rate != null) html += '<tr><td>Planned Outage</td><td>' + (p.planned_outage_rate * 100).toFixed(1) + '%</td></tr>';
    if (p.forced_outage_rate != null) html += '<tr><td>Forced Outage</td><td>' + (p.forced_outage_rate * 100).toFixed(1) + '%</td></tr>';
    html += '<tr><td>Lifetime</td><td>' + fmtNum(p.typical_lifetime_years) + ' years</td></tr>';
    html += '<tr><td>Construction</td><td>' + fmtNum(p.typical_construction_years) + ' years</td></tr>';
    html += '</table></div>';

    html += '</div>';
    return html;
}

// ── Enriched data lookup by coordinates ──

var _enrichedSubIndex = null;
var _enrichedGenIndex = null;

function buildSpatialIndex(geojson) {
    if (!geojson || !geojson.features) return {};
    var idx = {};
    for (var i = 0; i < geojson.features.length; i++) {
        var f = geojson.features[i];
        if (!f.geometry || !f.geometry.coordinates) continue;
        var c = f.geometry.coordinates;
        if (c.length < 2 || c[0] == null || c[1] == null) continue;
        var key = c[0].toFixed(4) + "," + c[1].toFixed(4);
        idx[key] = f.properties;
    }
    return idx;
}

function lookupEnrichedSub(lon, lat) {
    if (!_enrichedSubIndex && enrichedSubData) {
        _enrichedSubIndex = buildSpatialIndex(enrichedSubData);
    }
    if (!_enrichedSubIndex) return null;
    var key = lon.toFixed(4) + "," + lat.toFixed(4);
    return _enrichedSubIndex[key] || null;
}

function lookupEnrichedGen(lon, lat) {
    if (!_enrichedGenIndex && enrichedGenData) {
        _enrichedGenIndex = buildSpatialIndex(enrichedGenData);
    }
    if (!_enrichedGenIndex) return null;
    var key = lon.toFixed(4) + "," + lat.toFixed(4);
    return _enrichedGenIndex[key] || null;
}

// ── Region list ──

function buildRegionList(containerId) {
    var list = document.getElementById(containerId);
    if (!list || !regionsData.length) return;

    list.innerHTML = "";

    // "All Regions" button
    var allBtn = document.createElement("button");
    allBtn.className = "region-btn active";
    allBtn.innerHTML = '<span>All Regions (\u5168\u56fd)</span><span class="count"></span>';
    allBtn.onclick = function () { selectRegion(null); };
    list.appendChild(allBtn);

    // Individual regions
    for (var i = 0; i < regionsData.length; i++) {
        (function (r) {
            var btn = document.createElement("button");
            btn.className = "region-btn";
            btn.dataset.region = r.id;
            var colorDot = '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' +
                (REGION_COLORS[r.id] || "#999") + ';margin-right:5px;vertical-align:middle"></span>';
            btn.innerHTML =
                "<span>" + colorDot + r.name_en + " (" + r.name_ja + ")</span>" +
                '<span class="count">' + (r.substations + r.lines) + "</span>";
            btn.onclick = function () { selectRegion(r.id); };
            list.appendChild(btn);
        })(regionsData[i]);
    }
}

async function initRegionList() {
    try {
        var res = await fetch("./data/regions.json?v=" + Date.now());
        if (!res.ok) return;
        regionsData = await res.json();
        buildRegionList("region-list");
        buildRegionList("area-region-list");
    } catch (err) {
        console.error("Failed to load regions:", err);
    }
}

function setActiveRegionBtn(region, containerSelector) {
    var container = containerSelector || "#region-list";
    document.querySelectorAll(container + " .region-btn").forEach(function (btn) {
        btn.classList.toggle("active", btn.dataset.region === region);
    });
    if (!region) {
        var first = document.querySelector(container + " .region-btn:first-child");
        if (first) first.classList.add("active");
    }
}

// ── Status ──

function setStatus(msg) {
    var el = document.getElementById("status-text");
    if (el) el.textContent = msg;
}

// ── CSV Download ──

function geojsonToCSV(geojson, columns) {
    if (!geojson || !geojson.features || !geojson.features.length) return null;

    if (!columns) {
        var keySet = {};
        for (var i = 0; i < Math.min(geojson.features.length, 50); i++) {
            var p = geojson.features[i].properties;
            for (var k in p) {
                if (k.charAt(0) !== "_") keySet[k] = true;
            }
        }
        keySet["latitude"] = true;
        keySet["longitude"] = true;
        columns = Object.keys(keySet).sort();
    }

    var rows = [columns.join(",")];
    for (var j = 0; j < geojson.features.length; j++) {
        var feat = geojson.features[j];
        var props = feat.properties;
        var coords = feat.geometry ? feat.geometry.coordinates : [];
        var vals = [];
        for (var c = 0; c < columns.length; c++) {
            var col = columns[c];
            var val;
            if (col === "latitude") val = coords.length >= 2 ? coords[1] : "";
            else if (col === "longitude") val = coords.length >= 2 ? coords[0] : "";
            else val = props[col];

            if (val == null) val = "";
            val = String(val);
            if (val.indexOf(",") >= 0 || val.indexOf("\n") >= 0 || val.indexOf('"') >= 0) {
                val = '"' + val.replace(/"/g, '""') + '"';
            }
            vals.push(val);
        }
        rows.push(vals.join(","));
    }
    return rows.join("\n");
}

function downloadCSV(csv, filename) {
    var bom = "\uFEFF";
    var blob = new Blob([bom + csv], { type: "text/csv;charset=utf-8;" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

var GEN_CSV_COLUMNS = [
    "name", "operator", "region", "fuel_type", "fuel_type_ja", "fuel_type_en",
    "category", "dispatchable", "capacity_mw", "p_min_mw",
    "ramp_up_mw_per_h", "ramp_down_mw_per_h",
    "min_up_time_h", "min_down_time_h", "startup_time_h", "shutdown_time_h",
    "startup_cost_jpy", "shutdown_cost_jpy", "fuel_cost_per_mwh_jpy",
    "heat_rate_kj_per_kwh", "co2_intensity_kg_per_mwh",
    "planned_outage_rate", "forced_outage_rate", "capacity_factor",
    "typical_lifetime_years", "typical_construction_years",
    "latitude", "longitude",
];

var SUB_CSV_COLUMNS = [
    "name", "name_en", "name_reading", "operator", "operator_en",
    "region", "region_ja",
    "voltage_kv", "voltage_source", "voltage_label", "frequency_hz", "rating",
    "substation_type", "category", "category_ja", "gas_insulated", "building",
    "ref", "addr_city", "addr_province", "website", "operator_wikidata",
    "latitude", "longitude",
];

var LINE_CSV_COLUMNS = null;

async function downloadGeneratorsCSV() {
    var data = enrichedGenData;
    if (!data) {
        try {
            var res = await fetch("./data/generators.geojson");
            if (res.ok) data = await res.json();
        } catch (e) {}
    }
    if (!data) { alert("Generator data not available"); return; }
    var csv = geojsonToCSV(data, GEN_CSV_COLUMNS);
    downloadCSV(csv, "generators.csv");
}

async function downloadSubstationsCSV() {
    var data = enrichedSubData;
    if (!data) {
        try {
            var res = await fetch("./data/substations.geojson");
            if (res.ok) data = await res.json();
        } catch (e) {}
    }
    if (!data) { alert("Substation data not available"); return; }
    var csv = geojsonToCSV(data, SUB_CSV_COLUMNS);
    downloadCSV(csv, "substations.csv");
}

async function downloadLinesCSV() {
    var data = rawLineData;
    if (!data) {
        try {
            var res = await fetch("./data/lines_all.geojson");
            if (res.ok) data = await res.json();
        } catch (e) {}
    }
    if (!data) { alert("Line data not available"); return; }
    var csv = geojsonToCSV(data, LINE_CSV_COLUMNS);
    downloadCSV(csv, "transmission_lines.csv");
}

// ── List panel ──

var LIST_MAX = 1500; // 全国表示時の上限

function buildLists() {
    listSubsData = [];
    listLineData = [];
    listGenData  = [];

    // 変電所: 電圧フィルター反映済みの rawSubData から収集
    if (rawSubData && rawSubData.features) {
        for (var i = 0; i < rawSubData.features.length; i++) {
            var f = rawSubData.features[i];
            if (!f.geometry || f.geometry.type !== "Point") continue;
            var p = f.properties;
            var name = (p._display_name || p.name || "").trim();
            if (!name) continue;
            listSubsData.push({
                name: name,
                kv:   p._voltage_kv || 0,
                region:    p._region || "",
                region_ja: p._region_ja || REGION_NAMES_JA[p._region] || "",
                lat: f.geometry.coordinates[1],
                lon: f.geometry.coordinates[0],
            });
        }
    }

    // 送電線: rawLineData から名前付きラインのみ収集
    if (rawLineData && rawLineData.features) {
        for (var j = 0; j < rawLineData.features.length; j++) {
            var lf = rawLineData.features[j];
            if (!lf.geometry) continue;
            var lp = lf.properties;
            var lname = (lp._display_name || lp.name || "").trim();
            if (!lname) continue;
            var coords = lf.geometry.coordinates;
            if (!coords || !coords.length) continue;
            var mid = coords[Math.floor(coords.length / 2)];
            listLineData.push({
                name: lname,
                kv:   lp._voltage_kv || 0,
                region:    lp._region || "",
                region_ja: lp._region_ja || REGION_NAMES_JA[lp._region] || "",
                lat: mid[1],
                lon: mid[0],
            });
        }
    }

    // 発電所: rawPlantData から収集（表示フィルター反映済み）
    if (rawPlantData && rawPlantData.features) {
        for (var k = 0; k < rawPlantData.features.length; k++) {
            var gf = rawPlantData.features[k];
            if (!gf.geometry || !gf.geometry.coordinates) continue;
            var gp = gf.properties;
            var gname = (gp._display_name || gp.name || "").trim();
            if (!gname) continue;
            listGenData.push({
                name: gname,
                fuel: gp.fuel_type || "unknown",
                mw:   gp.capacity_mw || 0,
                region:    gp._region || "",
                region_ja: REGION_NAMES_JA[gp._region] || "",
                lat: gf.geometry.coordinates[1],
                lon: gf.geometry.coordinates[0],
            });
        }
    }

    renderListPanel();
}

function renderListPanel() {
    var subsEl  = document.getElementById("list-tab-subs");
    var lineEl  = document.getElementById("list-tab-lines");
    var genEl   = document.getElementById("list-tab-plants");
    if (!subsEl || !lineEl || !genEl) return;

    var sortedSubs  = sortListData(listSubsData.slice(), listCurrentSort, "sub");
    var sortedLines = sortListData(listLineData.slice(),  listCurrentSort, "line");
    var sortedGen   = sortListData(listGenData.slice(),   listCurrentSort, "gen");

    var truncSubs  = sortedSubs.length  > LIST_MAX;
    var truncLines = sortedLines.length > LIST_MAX;
    var truncGen   = sortedGen.length   > LIST_MAX;
    if (truncSubs)  sortedSubs  = sortedSubs.slice(0, LIST_MAX);
    if (truncLines) sortedLines = sortedLines.slice(0, LIST_MAX);
    if (truncGen)   sortedGen   = sortedGen.slice(0, LIST_MAX);

    function renderSubEntry(s) {
        return '<div class="list-entry" style="border-left-color:' + voltageColor(s.kv) + '"' +
            ' onclick="map.setView([' + s.lat + ',' + s.lon + '],14)">' +
            '<b>' + escHtml(s.name) + '</b>' +
            '<small>' + (s.kv > 0 ? s.kv + "kV" : "") + (s.region_ja ? " " + s.region_ja : "") + "</small>" +
            "</div>";
    }
    function renderLineEntry(l) {
        return '<div class="list-entry" style="border-left-color:' + voltageColor(l.kv) + '"' +
            ' onclick="map.setView([' + l.lat + ',' + l.lon + '],12)">' +
            '<b>' + escHtml(l.name) + '</b>' +
            '<small>' + (l.kv > 0 ? l.kv + "kV" : "") + (l.region_ja ? " " + l.region_ja : "") + "</small>" +
            "</div>";
    }
    function renderGenEntry(g) {
        return '<div class="list-entry" style="border-left-color:' + (FUEL_COLORS[g.fuel] || FUEL_COLORS.unknown) + '"' +
            ' onclick="map.setView([' + g.lat + ',' + g.lon + '],14)">' +
            '<b>' + escHtml(g.name) + '</b>' +
            '<small>' + g.fuel + (g.mw > 0 ? " " + g.mw + "MW" : "") + "</small>" +
            "</div>";
    }

    var truncMsg = '<div class="list-trunc">上位' + LIST_MAX + '件表示。リージョンを絞り込んでください。</div>';
    subsEl.innerHTML  = sortedSubs.map(renderSubEntry).join("")   + (truncSubs  ? truncMsg : "") || '<div class="list-empty">データなし</div>';
    lineEl.innerHTML  = sortedLines.map(renderLineEntry).join("") + (truncLines ? truncMsg : "") || '<div class="list-empty">データなし</div>';
    genEl.innerHTML   = sortedGen.map(renderGenEntry).join("")    + (truncGen   ? truncMsg : "") || '<div class="list-empty">データなし</div>';

    var tabs = document.querySelectorAll("#sublist .list-tab-btn");
    var counts = [sortedSubs.length, sortedLines.length, sortedGen.length];
    var labels = ["変電所", "送電線", "発電所"];
    tabs.forEach(function (btn, i) {
        btn.textContent = labels[i] + " (" + counts[i] + (i === 0 && truncSubs || i === 1 && truncLines || i === 2 && truncGen ? "+" : "") + ")";
    });
}

function sortListData(arr, mode) {
    if (mode === "name")    return arr.sort(function (a, b) { return a.name.localeCompare(b.name, "ja"); });
    if (mode === "voltage") return arr.sort(function (a, b) { return (b.kv || b.mw || 0) - (a.kv || a.mw || 0); });
    if (mode === "area")    return arr.sort(function (a, b) {
        var d = (a.region || "").localeCompare(b.region || "");
        return d !== 0 ? d : a.name.localeCompare(b.name, "ja");
    });
    return arr;
}

function escHtml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function showListTab(tab, btn) {
    listCurrentTab = tab;
    ["subs", "lines", "plants"].forEach(function (t) {
        var el = document.getElementById("list-tab-" + t);
        if (el) el.style.display = t === tab ? "" : "none";
    });
    document.querySelectorAll("#sublist .list-tab-btn").forEach(function (b) { b.classList.remove("active"); });
    if (btn) btn.classList.add("active");
}

function filterListPanel(q) {
    var el = document.getElementById("list-tab-" + listCurrentTab);
    if (!el) return;
    var ql = q.toLowerCase();
    el.querySelectorAll(".list-entry").forEach(function (e) {
        e.style.display = e.textContent.toLowerCase().indexOf(ql) >= 0 ? "" : "none";
    });
}

function sortListPanel(mode) {
    listCurrentSort = mode;
    document.querySelectorAll("#sublist .list-sort-btn").forEach(function (b) { b.classList.remove("active"); });
    var id = "listSort" + mode.charAt(0).toUpperCase() + mode.slice(1) + "Btn";
    var btn = document.getElementById(id);
    if (btn) btn.classList.add("active");
    renderListPanel();
}

function toggleListPanel(show) {
    listPanelVisible = show;
    var panel = document.getElementById("sublist");
    var toggleBtn = document.getElementById("list-toggle-btn");
    if (panel) panel.classList.toggle("visible", show);
    if (toggleBtn) toggleBtn.style.display = show ? "none" : "";
    if (show && rawSubData) buildLists();
    _syncUiToggles();
}

function toggleSidebar() {
    sidebarVisible = !sidebarVisible;
    var sidebar = document.getElementById("sidebar");
    if (sidebar) sidebar.style.display = sidebarVisible ? "" : "none";
    _syncUiToggles();
}

function toggleLegend() {
    legendVisible = !legendVisible;
    if (legendControl) {
        if (legendVisible) legendControl.addTo(map);
        else map.removeControl(legendControl);
    }
    _syncUiToggles();
}

function _syncUiToggles() {
    var b = document.getElementById("btn-toggle-sidebar");
    var l = document.getElementById("btn-toggle-legend");
    var p = document.getElementById("btn-toggle-list");
    if (b) b.classList.toggle("inactive", !sidebarVisible);
    if (l) l.classList.toggle("inactive", !legendVisible);
    if (p) p.classList.toggle("inactive", !listPanelVisible);
}

// ── Init ──

document.addEventListener("DOMContentLoaded", function () {
    initMap();
    initTabs();
    initRegionList();

    // Layer visibility checkboxes (synced across tabs)
    document.querySelectorAll(".layer-cb").forEach(function (cb) {
        cb.addEventListener("change", function () {
            var key = this.dataset.layer;
            layerVisible[key] = this.checked;
            // Sync all checkboxes with same data-layer
            document.querySelectorAll('.layer-cb[data-layer="' + key + '"]').forEach(function (el) {
                el.checked = layerVisible[key];
            });
            renderLayers();
        });
    });

    // Voltage filter (系統図 tab)
    var minKvSelect = document.getElementById("min-kv");
    if (minKvSelect) {
        minKvSelect.addEventListener("change", function () {
            var v = parseFloat(this.value);
            tabState.voltage.minKv = v;
            loadData(v);
        });
    }

    // Voltage filter (エリア tab)
    var areaMinKvSelect = document.getElementById("area-min-kv");
    if (areaMinKvSelect) {
        areaMinKvSelect.addEventListener("change", function () {
            var v = parseFloat(this.value);
            tabState.region.minKv = v;
            loadData(v);
        });
    }

    // Plant filter dropdown
    var plantFilterSelect = document.getElementById("plant-filter");
    if (plantFilterSelect) {
        plantFilterSelect.addEventListener("change", function () {
            plantFilter = this.value;
            loadPlantData().then(function () { renderLayers(); });
        });
    }

    // CSV download buttons
    var dlGen = document.getElementById("dl-generators");
    var dlSub = document.getElementById("dl-substations");
    var dlLines = document.getElementById("dl-lines");
    if (dlGen) dlGen.addEventListener("click", downloadGeneratorsCSV);
    if (dlSub) dlSub.addEventListener("click", downloadSubstationsCSV);
    if (dlLines) dlLines.addEventListener("click", downloadLinesCSV);

    // Load enriched data, then load map data
    loadEnrichedData().then(function () {
        loadData(275);
    });
});
