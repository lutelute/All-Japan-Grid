/* All-Japan-Grid pulse — 「日本の送電網、いま」をどこにでも貼れる表示部品.
 *
 *   <div class="ajg-pulse"></div>
 *   <script src="https://lutelute.github.io/All-Japan-Grid/js/pulse.js" defer></script>
 *
 * data-* で調整: data-src(pulse.json の場所。既定はこのスクリプトと同じサイトの data/flow_map/pulse.json)
 *               data-lang="ja|en"  data-controls="false"(時刻の操作を隠す)  data-labels="false"(エリア名を隠す)
 * データは scripts/export_pulse.py が毎時作る推定潮流(運用値ではない)。線の明るさ = 潮流の大きさ、
 * 光の粒の向き = 潮流の向き(p>0 は座標の並び順)。動きを減らす設定のときは粒を出さない。
 */
(() => {
  "use strict";
  const SCRIPT = document.currentScript;
  const DEFAULT_SRC = SCRIPT ? new URL("../data/flow_map/pulse.json", SCRIPT.src).href : "data/flow_map/pulse.json";
  const HOME = SCRIPT ? new URL("../", SCRIPT.src).href : "https://lutelute.github.io/All-Japan-Grid/";

  const LON0 = 128.3, LON1 = 146.0, LAT0 = 30.8, LAT1 = 45.7;
  const KX = Math.cos((37 * Math.PI) / 180);
  const CAP = { 500: 3000, 275: 1200, 220: 900, 187: 500, 154: 400 };
  const BOUNDARY = [[137.72, 38.15], [137.86, 37.05], [137.98, 36.55], [138.2, 36.05], [138.42, 35.55], [138.62, 35.12]];
  const ZONES = {
    hokkaido: [144.6, 44.7, "北海道", "Hokkaido"], tohoku: [142.7, 39.6, "東北", "Tohoku"],
    tokyo: [141.9, 35.3, "東京", "Tokyo"], chubu: [138.0, 33.95, "中部", "Chubu"],
    hokuriku: [135.4, 37.3, "北陸", "Hokuriku"], kansai: [135.5, 33.15, "関西", "Kansai"],
    chugoku: [132.2, 35.75, "中国", "Chugoku"], shikoku: [133.4, 32.55, "四国", "Shikoku"],
    kyushu: [129.2, 31.4, "九州", "Kyushu"], okinawa: [131.6, 42.1, "沖縄", "Okinawa"],
  };
  const TXT = {
    ja: { play: "今日を再生", pause: "止める", now: "いま", fc: "50Hz⇄60Hz", hk: "北本", e2w: "東→西", w2e: "西→東",
          h2h: "北海道→本州", h2n: "本州→北海道", demand: "需要", note: "推定値（運用値ではありません）", err: "潮流データを読み込めませんでした" },
    en: { play: "Replay today", pause: "Pause", now: "Now", fc: "50⇄60 Hz", hk: "Hokkaido–Honshu", e2w: "E→W", w2e: "W→E",
          h2h: "Hokkaido→Honshu", h2n: "Honshu→Hokkaido", demand: "Demand", note: "Estimates, not operational values", err: "Could not load the flow data" },
  };
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const cache = new Map();
  const getData = (src) => {
    if (!cache.has(src)) cache.set(src, fetch(src).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }));
    return cache.get(src);
  };

  function injectCSS() {
    if (document.getElementById("ajgp-css")) return;
    const st = document.createElement("style");
    st.id = "ajgp-css";
    st.textContent = `
.ajgp{font:13px/1.5 system-ui,-apple-system,"Hiragino Sans","Noto Sans JP",sans-serif;color:inherit}
.ajgp-stage{position:relative;aspect-ratio:1/1;overflow:hidden;border-radius:18px;color:#e8eef1;
 background:radial-gradient(120% 90% at 70% 35%,#10212b 0%,#0a141b 45%,#060b10 80%);border:1px solid rgba(255,255,255,.06)}
.ajgp-stage canvas{position:absolute;inset:0;width:100%;height:100%}
.ajgp-lab{position:absolute;inset:0;pointer-events:none}
.ajgp-z{position:absolute;transform:translate(-50%,-50%);display:inline-flex;gap:5px;align-items:baseline;white-space:nowrap;
 font-weight:600;font-size:11.5px;line-height:1;color:rgba(255,255,255,.88);background:rgba(8,16,22,.6);
 border:1px solid rgba(255,255,255,.14);border-radius:999px;padding:4px 8px}
.ajgp-z b{font:600 11px/1 ui-monospace,Menlo,monospace;color:#f2b34e}
.ajgp-tie{position:absolute;width:12px;height:12px;transform:translate(-50%,-50%);border-radius:50%;border:2px solid #f2b34e;box-shadow:0 0 10px #f2b34e}
.ajgp-tip{position:absolute;transform:translate(12px,-50%);pointer-events:none;font:600 11.5px/1 ui-monospace,Menlo,monospace;
 color:#fff;background:rgba(6,12,16,.9);border:1px solid rgba(255,255,255,.15);border-radius:6px;padding:5px 7px;white-space:nowrap}
.ajgp-bar{display:flex;align-items:center;gap:8px;margin-top:8px}
.ajgp-bar button{font-family:inherit;font-weight:600;font-size:12px;line-height:1;color:inherit;background:transparent;cursor:pointer;
 border:1px solid rgba(128,128,128,.4);border-radius:999px;padding:7px 11px;white-space:nowrap}
.ajgp-bar button:disabled{opacity:.45;cursor:default}
.ajgp-bar input{flex:1;min-width:0;accent-color:#e0a03a}
.ajgp-read{margin:6px 0 0;font:600 12px/1.6 ui-monospace,Menlo,monospace;opacity:.85}
.ajgp-cap{margin:2px 0 0;font-size:11.5px;opacity:.65}
.ajgp-cap a{color:inherit}
.ajgp-err{position:absolute;inset:0;display:grid;place-items:center;color:rgba(255,255,255,.6)}
[hidden].ajgp-tip{display:none}`;
    document.head.append(st);
  }

  function mount(root) {
    const lang = (root.dataset.lang || document.documentElement.lang || "ja").startsWith("ja") ? "ja" : "en";
    const T = TXT[lang];
    const src = root.dataset.src || DEFAULT_SRC;
    const showControls = root.dataset.controls !== "false";
    const showLabels = root.dataset.labels !== "false";
    root.classList.add("ajgp");
    root.innerHTML = `<div class="ajgp-stage"><canvas></canvas><canvas></canvas><div class="ajgp-lab"></div><div class="ajgp-tip" hidden></div></div>
<div class="ajgp-bar"${showControls ? "" : " hidden"}><button type="button" class="ajgp-play"></button><input type="range" min="0" max="23" step="1" aria-label="hour"><button type="button" class="ajgp-now"></button></div>
<p class="ajgp-read" aria-live="polite"></p>
<p class="ajgp-cap">${T.note} · <a href="${HOME}">All-Japan-Grid</a> · © OpenStreetMap contributors</p>`;
    const stage = root.querySelector(".ajgp-stage");
    const [base, fx] = stage.querySelectorAll("canvas");
    const lab = stage.querySelector(".ajgp-lab"), tip = stage.querySelector(".ajgp-tip");
    const slider = root.querySelector("input"), playBtn = root.querySelector(".ajgp-play"), nowBtn = root.querySelector(".ajgp-now");
    const read = root.querySelector(".ajgp-read");
    playBtn.textContent = T.play; nowBtn.textContent = T.now;
    const bctx = base.getContext("2d"), fctx = fx.getContext("2d");

    let D = null, Q = 1000, W = 0, H = 0, dpr = 1, s = 1, ox = 0, oy = 0, unit = 1;
    let lines = [], sil = null, parts = [], hi = 0, running = true, playing = null, last = 0, sprite = null;
    const proj = (lon, lat) => [ox + (lon - LON0) * KX * s, oy + (LAT1 - lat) * s];
    const pAt = (l) => l.p[hi] ?? 0;
    const capOf = (kv) => CAP[kv] || 300;
    const ramp = (i) => {
      const a = [70, 205, 190], b = [245, 196, 92], c = [255, 108, 72], t = Math.min(1, Math.max(0, i));
      const [p, q, u] = t < 0.5 ? [a, b, t / 0.5] : [b, c, (t - 0.5) / 0.5];
      return p.map((v, k) => Math.round(v + (q[k] - v) * u));
    };

    function layout() {
      const r = stage.getBoundingClientRect();
      if (!r.width || !D) return;
      W = r.width; H = r.height; dpr = Math.min(2, window.devicePixelRatio || 1);
      for (const c of [base, fx]) { c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); }
      const pad = Math.max(6, W * 0.02);
      s = Math.min((W - 2 * pad) / ((LON1 - LON0) * KX), (H - 2 * pad) / (LAT1 - LAT0));
      ox = (W - (LON1 - LON0) * KX * s) / 2; oy = (H - (LAT1 - LAT0) * s) / 2; unit = W / 640;
      sil = new Path2D();
      for (const [, xy] of D.silhouette) {
        let [x, y] = proj(xy[0] / Q, xy[1] / Q); sil.moveTo(x, y);
        for (let i = 2; i < xy.length; i += 2) { [x, y] = proj(xy[i] / Q, xy[i + 1] / Q); sil.lineTo(x, y); }
      }
      lines = D.lines.map(([kv, xy, p]) => {
        const n = xy.length / 2, pts = new Float32Array(n * 2), cum = new Float32Array(n);
        for (let i = 0; i < n; i++) {
          const [x, y] = proj(xy[2 * i] / Q, xy[2 * i + 1] / Q);
          pts[2 * i] = x; pts[2 * i + 1] = y;
          if (i) cum[i] = cum[i - 1] + Math.hypot(x - pts[2 * i - 2], y - pts[2 * i - 1]);
        }
        return { kv, p, pts, cum, len: cum[n - 1] };
      }).filter((l) => l.len > 0.5).sort((a, b) => a.kv - b.kv);
      const r0 = 6 * dpr, cv = document.createElement("canvas");
      cv.width = cv.height = r0 * 2;
      const g = cv.getContext("2d"), grd = g.createRadialGradient(r0, r0, 0, r0, r0, r0);
      grd.addColorStop(0, "rgba(255,250,235,1)"); grd.addColorStop(0.35, "rgba(255,226,170,.55)"); grd.addColorStop(1, "rgba(255,200,120,0)");
      g.fillStyle = grd; g.fillRect(0, 0, r0 * 2, r0 * 2); sprite = cv;
      redraw();
    }

    function redraw() {
      const c = bctx;
      c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, W, H); c.lineCap = "round"; c.lineJoin = "round";
      const [bx0, by0] = proj(128.9, 44.1), [bx1, by1] = proj(132.4, 41.6);
      c.strokeStyle = "rgba(140,180,200,.22)"; c.lineWidth = 1; c.setLineDash([3, 4]); c.strokeRect(bx0, by0, bx1 - bx0, by1 - by0); c.setLineDash([]);
      c.strokeStyle = "rgba(120,170,190,.16)"; c.lineWidth = 0.7 * Math.max(0.8, unit); c.stroke(sil);
      for (const l of lines) {
        const i = Math.abs(pAt(l)) / capOf(l.kv), [r, g, b] = ramp(i);
        c.strokeStyle = `rgba(${r},${g},${b},${0.38 + 0.55 * Math.min(1, i * 1.4)})`;
        c.lineWidth = (l.kv >= 500 ? 2.1 : l.kv >= 275 ? 1.5 : 1.0) * Math.max(0.8, unit);
        c.beginPath(); c.moveTo(l.pts[0], l.pts[1]);
        for (let k = 2; k < l.pts.length; k += 2) c.lineTo(l.pts[k], l.pts[k + 1]);
        c.stroke();
      }
      c.strokeStyle = "rgba(255,255,255,.35)"; c.setLineDash([2, 5]); c.beginPath();
      BOUNDARY.forEach(([lon, lat], k) => { const [x, y] = proj(lon, lat); k ? c.lineTo(x, y) : c.moveTo(x, y); });
      c.stroke(); c.setLineDash([]);
      c.font = `600 ${Math.max(10, 11 * unit)}px ui-monospace, Menlo, monospace`; c.fillStyle = "rgba(255,255,255,.55)";
      let [x, y] = proj(137.92, 38.25); c.textAlign = "left"; c.fillText("50 Hz", x, y);
      [x, y] = proj(137.52, 38.25); c.textAlign = "right"; c.fillText("60 Hz", x, y); c.textAlign = "left";
      labels(); spawn(); readout();
    }

    function labels() {
      lab.replaceChildren();
      const isNow = D.hours[hi] === D.now_hour;
      if (showLabels) {
        for (const [key, [lon, lat, ja, en]] of Object.entries(ZONES)) {
          const [x, y] = proj(lon, lat), el = document.createElement("span");
          el.className = "ajgp-z"; el.textContent = lang === "ja" ? ja : en;
          const mw = isNow ? (D.zones_now || {})[key] : null;
          if (mw) { const b = document.createElement("b"); b.textContent = `${(mw / 1000).toFixed(1)} GW`; el.append(b); }
          el.style.left = `${x}px`; el.style.top = `${y}px`; lab.append(el);
          const half = el.offsetWidth / 2;
          if (x - half < 6 || x + half > W - 6) el.style.left = `${Math.min(W - 6 - half, Math.max(6 + half, x))}px`;
        }
      }
      for (const [key, at] of [["fc", [138.05, 35.7]], ["hokuhon", [140.75, 41.35]]]) {
        if ((D.cross || {})[key]?.[hi] == null) continue;
        const [x, y] = proj(at[0], at[1]), m = document.createElement("span");
        m.className = "ajgp-tie"; m.style.left = `${x}px`; m.style.top = `${y}px`; lab.append(m);
      }
    }

    function readout() {
      const d = D.date, h = D.hours[hi];
      const md = lang === "ja" ? `${+d.slice(4, 6)}/${+d.slice(6, 8)} ${h}:00` : `${new Date(+d.slice(0, 4), +d.slice(4, 6) - 1, +d.slice(6, 8)).toLocaleDateString("en", { month: "short", day: "numeric" })} ${h}:00 JST`;
      const bits = [md];
      const z = D.zones_now || {};
      if (h === D.now_hour && Object.keys(z).length) bits.push(`${T.demand} ${(Object.values(z).reduce((a, b) => a + b, 0) / 1000).toFixed(1)} GW`);
      const fc = (D.cross || {}).fc?.[hi], hk = (D.cross || {}).hokuhon?.[hi];
      if (fc != null) bits.push(`${T.fc} ${Math.abs(fc).toLocaleString()} MW ${fc >= 0 ? T.e2w : T.w2e}`);
      if (hk != null) bits.push(`${T.hk} ${Math.abs(hk).toLocaleString()} MW ${hk >= 0 ? T.h2h : T.h2n}`);
      read.textContent = bits.join(" · ");
      nowBtn.disabled = h === D.now_hour;
    }

    function spawn() {
      parts = [];
      fctx.clearRect(0, 0, fx.width, fx.height);
      if (reduce) return;
      const budget = Math.round(1100 * Math.min(1.4, unit)), want = [];
      let total = 0;
      for (const l of lines) {
        const p = pAt(l);
        if (Math.abs(p) < 20) continue;
        const i = Math.min(1.5, Math.abs(p) / capOf(l.kv));
        const n = Math.max(1, Math.round((l.len / (34 * unit)) * (0.15 + 1.0 * i)));
        want.push([l, n, i, Math.sign(p)]); total += n;
      }
      const k = total > budget ? budget / total : 1;
      for (const [l, n, i, dir] of want) {
        for (let j = 0; j < Math.max(1, Math.round(n * k)); j++) {
          const t = Math.random() * l.len;
          let seg = 0; while (seg < l.cum.length - 2 && l.cum[seg + 1] < t) seg++;
          parts.push({ l, t, seg, v: (16 + 46 * Math.min(1, i)) * unit * dir, a: 0.22 + 0.6 * Math.min(1, i), z: l.kv >= 500 ? 1.15 : l.kv >= 275 ? 0.95 : 0.75 });
        }
      }
    }

    function frame(ts) {
      requestAnimationFrame(frame);
      if (!running || !parts.length) { last = ts; return; }
      const dt = Math.min(0.05, (ts - last) / 1000 || 0); last = ts;
      const c = fctx, r0 = 3.4 * dpr * Math.max(0.8, unit);
      c.setTransform(1, 0, 0, 1, 0, 0); c.clearRect(0, 0, fx.width, fx.height); c.globalCompositeOperation = "lighter";
      for (const q of parts) {
        const l = q.l, cum = l.cum;
        q.t += q.v * dt;
        if (q.t >= l.len) { q.t -= l.len; q.seg = 0; } else if (q.t < 0) { q.t += l.len; q.seg = cum.length - 2; }
        while (q.seg < cum.length - 2 && cum[q.seg + 1] < q.t) q.seg++;
        while (q.seg > 0 && cum[q.seg] > q.t) q.seg--;
        const k = q.seg, u = (q.t - cum[k]) / (cum[k + 1] - cum[k] || 1);
        const x = (l.pts[2 * k] + (l.pts[2 * k + 2] - l.pts[2 * k]) * u) * dpr;
        const y = (l.pts[2 * k + 1] + (l.pts[2 * k + 3] - l.pts[2 * k + 1]) * u) * dpr;
        const r = r0 * q.z; c.globalAlpha = q.a; c.drawImage(sprite, x - r, y - r, r * 2, r * 2);
      }
      c.globalAlpha = 1; c.globalCompositeOperation = "source-over";
    }

    function setHour(i) { hi = Math.max(0, Math.min(D.hours.length - 1, i)); slider.value = String(hi); redraw(); }
    function stop() { if (playing) { clearInterval(playing); playing = null; } playBtn.textContent = T.play; }

    stage.addEventListener("pointermove", (e) => {
      if (!D || e.pointerType === "touch") return;
      const r = stage.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
      let best = null, bd = 64;
      for (const l of lines) {
        const p = l.pts;
        for (let i = 0; i < p.length - 2; i += 2) {
          const dx = p[i + 2] - p[i], dy = p[i + 3] - p[i + 1], L2 = dx * dx + dy * dy || 1;
          let u = ((px - p[i]) * dx + (py - p[i + 1]) * dy) / L2; u = u < 0 ? 0 : u > 1 ? 1 : u;
          const qx = p[i] + u * dx - px, qy = p[i + 1] + u * dy - py, d = qx * qx + qy * qy;
          if (d < bd) { bd = d; best = l; }
        }
      }
      if (!best) { tip.hidden = true; return; }
      tip.textContent = `${best.kv} kV · ${Math.abs(pAt(best)).toLocaleString()} MW`;
      tip.style.left = `${px}px`; tip.style.top = `${py}px`; tip.hidden = false;
    });
    stage.addEventListener("pointerleave", () => { tip.hidden = true; });
    new IntersectionObserver(([en]) => { running = en.isIntersecting && !document.hidden; }).observe(root);
    let rz = 0;
    new ResizeObserver(() => { clearTimeout(rz); rz = setTimeout(layout, 120); }).observe(stage);

    getData(src).then((d) => {
      D = d; Q = d.q || 1000;
      hi = Math.max(0, d.hours.indexOf(d.now_hour));
      slider.max = String(d.hours.length - 1); slider.value = String(hi);
      slider.addEventListener("input", () => { stop(); setHour(+slider.value); });
      nowBtn.addEventListener("click", () => { stop(); setHour(D.hours.indexOf(D.now_hour)); });
      playBtn.addEventListener("click", () => {
        if (playing) { stop(); return; }
        if (hi >= D.hours.length - 1) setHour(0);
        playBtn.textContent = T.pause;
        playing = setInterval(() => { if (hi >= D.hours.length - 1) { stop(); return; } setHour(hi + 1); }, 900);
      });
      layout();
      requestAnimationFrame(frame);
    }).catch(() => {
      const e = document.createElement("div"); e.className = "ajgp-err"; e.textContent = T.err; stage.append(e);
    });
  }

  function init() {
    injectCSS();
    document.querySelectorAll(".ajg-pulse:not(.ajgp)").forEach(mount);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
  window.AJGPulse = { mount: (el) => { injectCSS(); mount(el); } };
})();
