/**
 * Japan Power Grid Map - Power flow stub for static GitHub Pages.
 */

document.addEventListener("DOMContentLoaded", function () {
    var section = document.getElementById("pf-results-section");
    var content = document.getElementById("pf-results-content");
    if (section && content) {
        section.style.display = "block";
        content.innerHTML =
            '<div class="pf-info">' +
            "<strong>Experimental</strong><br><br>" +
            "OSM data provides geographic topology only. " +
            "Power flow requires line impedance (R, X, B), generators, and demand data " +
            "that are not available in OpenStreetMap.<br><br>" +
            "The local server can run power flow with synthetic parameters, " +
            "but results are not physically meaningful.<br><br>" +
            '<pre style="margin:8px 0;padding:8px;background:#16213e;border-radius:4px;font-size:0.75rem;color:#7f8c8d;">' +
            "uvicorn src.server.app:app --reload" +
            "</pre>" +
            "See <a href='https://github.com/lutelute/All-Japan-Grid#limitations--what-this-data-is-not' style='color:#e94560;'>README</a> for details." +
            "</div>";
    }
});
