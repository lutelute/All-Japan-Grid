/* AGJ の地図ページが共通で使うタブ部品(2026-10-20 io 一新の 1 段目).
 *
 * なぜ要るか: map.html では grid_map.js・sld.js・ybus_sim.js がそれぞれタブのボタンに
 * クリック処理を付けていて、URL の #tab-… を開く処理(grid_map.js)が、sld.js と ybus_sim.js
 * が処理を付けるより先に走っていた。そのため直リンク(map.html#tab-ybus)ではタブだけが
 * 切り替わり、中身が起動しなかった(07be84a4 から)。
 *
 * 使い方:
 *   AGJTabs.on("tab-ybus", function () { ... });   // そのタブを開いたとき
 *   AGJTabs.onChange(function (id, prev) { ... });  // どのタブに切り替わっても
 *   AGJTabs.open("tab-sld");                         // コードから開く
 * ボタンは <button class="tab-btn" data-tab="tab-…">、中身は <div class="tab-panel" id="tab-…">。
 * URL の # は、すべてのスクリプトが読み込まれた後(window の load)に読む。
 */
(function (global) {
    "use strict";

    var handlers = {};
    var changeHandlers = [];
    var current = null;
    var started = false;

    function on(id, fn) {
        (handlers[id] = handlers[id] || []).push(fn);
        if (started && current === id) fn(id);
    }

    function onChange(fn) {
        changeHandlers.push(fn);
    }

    function open(id) {
        var btn = document.querySelector('.tab-btn[data-tab="' + id + '"]');
        var panel = document.getElementById(id);
        if (!btn || !panel) return false;
        var prev = current;
        document.querySelectorAll(".tab-btn").forEach(function (b) { b.classList.toggle("active", b === btn); });
        document.querySelectorAll(".tab-panel").forEach(function (p) { p.classList.toggle("active", p === panel); });
        current = id;
        if (location.hash.slice(1) !== id) {
            var first = id === firstTab();
            history.replaceState(null, "", first ? location.pathname + location.search : "#" + id);
        }
        changeHandlers.forEach(function (fn) { fn(id, prev); });
        (handlers[id] || []).forEach(function (fn) { fn(id, prev); });
        return true;
    }

    function firstTab() {
        var b = document.querySelector(".tab-btn");
        return b ? b.dataset.tab : null;
    }

    function fromHash() {
        var id = location.hash.slice(1).replace(/[^\w-]/g, "");
        if (id && id !== current) open(id);
    }

    function bind() {
        document.querySelectorAll(".tab-btn").forEach(function (btn) {
            btn.addEventListener("click", function () { open(btn.dataset.tab); });
        });
        var active = document.querySelector(".tab-btn.active");
        current = active ? active.dataset.tab : firstTab();
    }

    // URL の # は、すべてのスクリプトの DOMContentLoaded の処理(各タブの登録)が済んだ後に読む
    function start() {
        if (started) return;
        started = true;
        window.addEventListener("hashchange", fromHash);
        fromHash();
    }

    function active() {
        return current;
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bind);
    else bind();
    if (document.readyState === "complete") start();
    else window.addEventListener("load", start);

    global.AGJTabs = { on: on, onChange: onChange, open: open, active: active, start: start };
})(window);
