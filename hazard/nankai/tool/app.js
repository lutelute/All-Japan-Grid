(function () {
  "use strict";
  const D = window.NANKAI_DATA, M = window.NankaiModel;
  const P = M.prepare(D);
  const DEF = Object.assign({}, D.params.defaults);
  const $ = id => document.getElementById(id);
  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const fmt = (x, d = 0) => Number(x).toLocaleString("ja-JP", { minimumFractionDigits: d, maximumFractionDigits: d });
  const man = x => fmt(x / 1e4) + "";           // 万軒
  const pct = (x, d = 1) => fmt(x * 100, d);

  // ── 状態(URL の # に入れて共有できる) ─────────────────────
  const KEYS = { ol: "ol", tr: "tr", tb: "tb", collapse: "c", sigma: "s", basis: "b", old_split: "os", spm: "spm", aid: "aid", internal: "int", access: "acc" };
  function readHash() {
    const st = Object.assign({}, DEF);
    try {
      const q = new URLSearchParams(location.hash.replace(/^#/, ""));
      for (const [k, h] of Object.entries(KEYS)) {
        if (!q.has(h)) continue;
        const v = q.get(h);
        if (k === "basis") st[k] = v === "a" ? "all_dwellings" : "wooden_stock";
        else if (k === "collapse" || k === "internal") st[k] = v === "1";
        else if (k === "ol" || k === "tr" || k === "tb") st[k] = v === "0" ? 0 : 1;
        else if (!Number.isNaN(parseFloat(v))) st[k] = parseFloat(v);
      }
    } catch (e) { /* 既定のまま */ }
    return st;
  }
  function writeHash(st) {
    const q = new URLSearchParams();
    for (const [k, h] of Object.entries(KEYS)) {
      if (st[k] === DEF[k]) continue;
      q.set(h, k === "basis" ? (st[k] === "all_dwellings" ? "a" : "w") : (typeof st[k] === "boolean" ? (st[k] ? "1" : "0") : String(st[k])));
    }
    const s = q.toString();
    try { history.replaceState(null, "", s ? "#" + s : location.pathname + location.search); } catch (e) { /* 共有リンクは作れないが計算は続ける */ }
  }
  let state = readHash();

  // ── 入力 ────────────────────────────────────────────────
  function syncInputs() {
    for (const k of ["ol", "tr", "tb"]) $(k + state[k]).checked = true;
    $("collapse").checked = state.collapse; $("internal").checked = state.internal;
    $("basisW").checked = state.basis === "wooden_stock"; $("basisA").checked = state.basis === "all_dwellings";
    $("sigma").value = state.sigma; $("oldSplit").value = state.old_split; $("spm").value = state.spm; $("aid").value = state.aid; $("access").value = state.access;
    labels();
  }
  function labels() {
    $("sigmaOut").textContent = Number(state.sigma).toFixed(2);
    $("oldSplitOut").textContent = Math.round(state.old_split * 100) + "%";
    $("spmOut").textContent = state.spm + " 人";
    $("aidOut").textContent = Math.round(state.aid * 100) + "%";
    $("accessOut").textContent = state.access + " 日後";
    $("sigma").disabled = !state.collapse; $("oldSplit").disabled = !state.collapse;
  }
  function readInputs() {
    const radio = name => document.querySelector(`input[name="${name}"]:checked`).value;
    state = Object.assign({}, state, {
      ol: +radio("ol"), tr: +radio("tr"), tb: +radio("tb"), basis: radio("basis"),
      collapse: $("collapse").checked, internal: $("internal").checked,
      sigma: +$("sigma").value, old_split: +$("oldSplit").value, spm: +$("spm").value, aid: +$("aid").value, access: +$("access").value,
    });
  }
  let timer = null;
  function onInput() { readInputs(); labels(); document.body.classList.add("busy"); clearTimeout(timer); timer = setTimeout(recompute, 70); }
  document.querySelectorAll(".rail input").forEach(el => el.addEventListener(el.type === "range" ? "input" : "change", onInput));
  $("resetBtn").addEventListener("click", () => { state = Object.assign({}, DEF); syncInputs(); recompute(); });
  $("copyBtn").addEventListener("click", async () => {
    const b = $("copyBtn");
    try { await navigator.clipboard.writeText(location.href); b.textContent = "コピーしました"; }
    catch (e) { b.textContent = "アドレス欄の URL を使ってください"; }
    setTimeout(() => { b.textContent = "この前提のリンクをコピー"; }, 2200);
  });

  // ── 計算 ────────────────────────────────────────────────
  const base = M.run(D, P, DEF, false);
  let cur = null;
  function recompute() {
    const t0 = performance.now();
    cur = M.run(D, P, state, true);
    const ms = performance.now() - t0;
    writeHash(state);
    render(ms);
    document.body.classList.remove("busy");
  }

  // ── 表示 ────────────────────────────────────────────────
  const dayIndex = d => M.REC_DAYS.findIndex(x => Math.abs(x - d) < 1e-9);
  function dynOf(keys) { return { west: D.dyn.west[keys.west], east: D.dyn.east[keys.east] }; }
  function atT(blk, arr, t) { const j = blk.t_s.indexOf(t); return blk[arr][j]; }

  const PREMISE_TEXT = {
    tr: v => v ? null : "変圧器は元のモデル", tb: v => v ? null : "東京湾の湾奥は津波被害なし", ol: v => v ? null : "過負荷リレーなし",
    collapse: v => v ? null : "建物全壊の巻き込みなし", sigma: v => `σ ${Number(v).toFixed(2)}`, basis: v => v === "all_dwellings" ? "全建物に対する全壊率" : null,
    old_split: v => `旧築年 ${Math.round(v * 100)}%`, spm: v => `人員 ${v} 人/百万口`, aid: v => `応援 ${Math.round(v * 100)}%`, internal: v => v ? null : "社内融通なし", access: v => `着手 ${v} 日後`,
  };
  function diffChip() {
    const parts = [];
    for (const k of Object.keys(PREMISE_TEXT)) if (state[k] !== DEF[k]) { const t = PREMISE_TEXT[k](state[k]); if (t) parts.push(t); }
    const el = $("diffChip");
    el.textContent = parts.length ? "既定から変更: " + parts.join("・") : "既定の前提";
    el.classList.toggle("changed", parts.length > 0);
  }

  function kpis() {
    const dc = dynOf(cur.keys), db = dynOf(base.keys);
    const oc = cur.ser.out, ob = base.ser.out;
    const i1 = dayIndex(1), i7 = dayIndex(7), i14 = dayIndex(14);
    const aidC = cur.sim.convoys.reduce((s, c) => s + c.people, 0), aidB = base.sim.convoys.reduce((s, c) => s + c.people, 0);
    const tiles = [
      { cls: "west", label: "西 60 Hz 10 分後の受電率", v: atT(dc.west, "energized", 600), b: atT(db.west, "energized", 600), f: x => pct(x), unit: "%", good: "up", d: x => pct(x) + " pt" },
      { cls: "east", label: "東 50 Hz 10 分後の受電率", v: atT(dc.east, "energized", 600), b: atT(db.east, "energized", 600), f: x => pct(x), unit: "%", good: "up", d: x => pct(x) + " pt" },
      { cls: "west", label: "西 3 時間後にほぼ全域が崩壊", v: dc.west.near_total, b: db.west.near_total, f: x => pct(x, 0), unit: "%", good: "down", d: x => pct(x, 0) + " pt" },
      { cls: "east", label: "東 3 時間後にほぼ全域が崩壊", v: dc.east.near_total, b: db.east.near_total, f: x => pct(x, 0), unit: "%", good: "down", d: x => pct(x, 0) + " pt" },
      { cls: "", label: "停電中 1 日後", v: oc[i1][0], b: ob[i1][0], f: man, unit: "万軒", good: "down", d: x => man(x) + " 万" },
      { cls: "", label: "停電中 7 日後", v: oc[i7][0], b: ob[i7][0], f: man, unit: "万軒", good: "down", d: x => man(x) + " 万" },
      { cls: "", label: "配電の停電 14 日後", v: oc[i14][4], b: ob[i14][4], f: man, unit: "万軒", good: "down", d: x => man(x) + " 万" },
      { cls: "", label: "他社応援", v: aidC, b: aidB, f: x => fmt(x), unit: "人", good: "up", d: x => fmt(x) + " 人" },
    ];
    $("kpis").innerHTML = tiles.map(t => {
      const dv = t.v - t.b, same = Math.abs(dv) < (t.unit === "%" ? 5e-4 : 0.5 * (t.unit === "人" ? 1 : 1e4));
      const cls = same ? "" : ((dv > 0) === (t.good === "up") ? "better" : "worse");
      const sign = dv > 0 ? "+" : "−";
      return `<div class="kpi ${t.cls}"><span class="k-label">${t.label}</span><span class="k-val">${t.f(t.v)}<span class="k-unit">${t.unit}</span></span>` +
        `<span class="k-delta ${cls}">${same ? "既定と同じ" : `既定から ${sign}${t.d(Math.abs(dv))}`}</span></div>`;
    }).join("");
  }

  // SVG の小道具
  const el = (tag, attrs, inner = "") => `<${tag} ${Object.entries(attrs).map(([k, v]) => `${k}="${v}"`).join(" ")}>${inner}</${tag}>`;
  function pathOf(xs, ys) { return xs.map((x, i) => `${i ? "L" : "M"}${x.toFixed(1)},${ys[i].toFixed(1)}`).join(""); }

  function chartDyn() {
    const W = 760, H = 250, L = 44, R = 12, T = 12, B = 30;
    const xt = t => t <= 300 ? t : 300 + (Math.log10(Math.max(t, 300)) - Math.log10(300)) / (Math.log10(10800) - Math.log10(300)) * 150;
    const X = t => L + xt(t) / 450 * (W - L - R), Y = v => T + (1 - v) * (H - T - B);
    const dc = dynOf(cur.keys), db = dynOf(base.keys);
    let g = `<g class="grid">`;
    for (const v of [0, .25, .5, .75, 1]) g += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/>`;
    g += `</g>`;
    const ticks = [[0, "0"], [60, "1分"], [120, "2分"], [180, "3分"], [300, "5分"], [1800, "30分"], [3600, "1時間"], [10800, "3時間"]];
    let ax = ticks.map(([t, l]) => `<text x="${X(t)}" y="${H - 10}" text-anchor="middle">${l}</text>`).join("");
    ax += [0, .25, .5, .75, 1].map(v => `<text x="${L - 6}" y="${Y(v) + 4}" text-anchor="end">${v * 100}%</text>`).join("");
    let body = "";
    for (const [isl, col] of [["west", css("--west")], ["east", css("--east")]]) {
      const c = dc[isl], b = db[isl];
      const xs = c.t_s.map(X);
      const band = pathOf(xs, c.energized.map(Y)) + pathOf(xs.slice().reverse(), c.p10.slice().reverse().map(Y)).replace(/^M/, "L") + "Z";
      body += `<path d="${band}" fill="${col}" opacity="0.12"/>`;
      body += `<path d="${pathOf(b.t_s.map(X), b.energized.map(Y))}" fill="none" stroke="${col}" stroke-width="1.5" stroke-dasharray="4 4" opacity="0.75"/>`;
      body += `<path d="${pathOf(xs, c.energized.map(Y))}" fill="none" stroke="${col}" stroke-width="2.4"/>`;
      const e = c.energized[c.energized.length - 1];
      body += `<circle cx="${X(10800)}" cy="${Y(e)}" r="3.5" fill="${col}"/>`;
    }
    $("chartDyn").innerHTML = el("svg", { viewBox: `0 0 ${W} ${H}` }, g + ax + body);
    $("legendDyn").innerHTML = `<span><i class="line" style="border-color:var(--west)"></i>西 60 Hz(需要 ${fmt(dc.west.load_gw, 1)} GW)</span>` +
      `<span><i class="line" style="border-color:var(--east)"></i>東 50 Hz(需要 ${fmt(dc.east.load_gw, 1)} GW)</span><span><i class="dash" style="border-color:var(--muted)"></i>既定の前提</span>` +
      `<span>10 分で 2 つ以上に分かれた割合 西 ${pct(dc.west.split10, 0)}%・東 ${pct(dc.east.split10, 0)}%</span>`;
  }

  function stackedChart(target, legendTarget, days, series, colors, names, baseTotal, yFmt) {
    const W = 520, H = 250, L = 52, R = 10, T = 12, B = 30;
    const lx = d => Math.log10(1 + d) / Math.log10(91);
    const X = d => L + lx(d) * (W - L - R);
    const tot = days.map((_, j) => series.reduce((s, a) => s + a[j], 0));
    const ymax = niceMax(Math.max(...tot, ...(baseTotal || [0])));
    const Y = v => T + (1 - v / ymax) * (H - T - B);
    let g = `<g class="grid">`;
    const yt = [0, .25, .5, .75, 1].map(f => f * ymax);
    for (const v of yt) g += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/>`;
    g += `</g>`;
    let ax = [[0, "直後"], [1, "1日"], [3, "3日"], [7, "1週"], [14, "2週"], [30, "1月"], [90, "3月"]].map(([d, l]) => `<text x="${X(d)}" y="${H - 10}" text-anchor="middle">${l}</text>`).join("");
    ax += yt.map(v => `<text x="${L - 6}" y="${Y(v) + 4}" text-anchor="end">${yFmt(v)}</text>`).join("");
    let body = "", lower = days.map(() => 0);
    series.forEach((s, k) => {
      const upper = lower.map((v, j) => v + s[j]);
      const xs = days.map(X);
      const d = pathOf(xs, upper.map(Y)) + pathOf(xs.slice().reverse(), lower.slice().reverse().map(Y)).replace(/^M/, "L") + "Z";
      body += `<path d="${d}" fill="${colors[k]}" opacity="0.85"/>`;
      lower = upper;
    });
    if (baseTotal) body += `<path d="${pathOf(days.map(X), baseTotal.map(Y))}" fill="none" stroke="var(--ink)" stroke-width="1.4" stroke-dasharray="4 4" opacity="0.7"/>`;
    $(target).innerHTML = el("svg", { viewBox: `0 0 ${W} ${H}` }, g + ax + body);
    $(legendTarget).innerHTML = names.map((n, k) => `<span><i style="background:${colors[k]}"></i>${n}</span>`).join("") + (baseTotal ? `<span><i class="dash" style="border-color:var(--ink)"></i>既定の合計</span>` : "");
  }
  function niceMax(v) { if (v <= 0) return 1; const p = Math.pow(10, Math.floor(Math.log10(v))); for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= v) return m * p; return 10 * p; }

  function chartOut() {
    const days = cur.ser.days, o = cur.ser.out;
    stackedChart("chartOut", "legendOut", days, [o.map(r => r[3]), o.map(r => r[1]), o.map(r => r[2])],
      [css("--lost"), css("--outage"), css("--dist") || "#8a5bb0"], ["津波で全壊相当(復旧対象外)", "送電側の停電", "配電だけの停電"],
      base.ser.out.map(r => r[0]), v => fmt(v / 1e4) + "万");
  }
  function chartPeople() {
    const days = M.REC_DAYS, idx = days.map(d => Math.round(d * 24));
    const s = cur.sim.rec, b = base.sim.rec;
    stackedChart("chartPeople", "legendPeople", days, [idx.map(i => s.own[i]), idx.map(i => s.internal[i]), idx.map(i => s.aid[i])],
      [css("--own"), css("--internal"), css("--aid")], ["地元の事業所", "社内の融通", "他社応援"],
      idx.map(i => b.own[i] + b.internal[i] + b.aid[i]), v => fmt(v / 1e3) + "千");
  }

  // 地図
  const cv = $("map"), ctx = cv.getContext("2d");
  const EXT = { lon0: 128.6, lon1: 142.6, lat0: 30.6, lat1: 41.8 }, KX = Math.cos(35 * Math.PI / 180);
  const RAMP = [[0, [159, 182, 178]], [0.25, [232, 193, 74]], [0.5, [224, 120, 45]], [0.75, [198, 65, 45]], [1, [110, 31, 58]]];
  function rampColor(p) {
    for (let k = 1; k < RAMP.length; k++) if (p <= RAMP[k][0]) {
      const [a, ca] = RAMP[k - 1], [b, cb] = RAMP[k], f = (p - a) / (b - a);
      return `rgb(${ca.map((v, i) => Math.round(v + (cb[i] - v) * f)).join(",")})`;
    }
    return "rgb(110,31,58)";
  }
  function dayLabel(d) { return d === 0 ? "直後" : d < 1 ? `${Math.round(d * 24)} 時間` : `${fmt(d, d % 1 ? 2 : 0)} 日`; }
  function drawMap() {
    const rect = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    const w = Math.max(320, Math.round(rect.width)), h = Math.round(w * 10 / 16);
    cv.width = w * dpr; cv.height = h * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const sx = (w - 20) / ((EXT.lon1 - EXT.lon0) * KX), sy = (h - 20) / (EXT.lat1 - EXT.lat0), s = Math.min(sx, sy);
    const ox = (w - (EXT.lon1 - EXT.lon0) * KX * s) / 2, oy = (h - (EXT.lat1 - EXT.lat0) * s) / 2;
    const px = lon => ox + (lon - EXT.lon0) * KX * s, py = lat => h - oy - (lat - EXT.lat0) * s;
    ctx.fillStyle = css("--map-bg"); ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = css("--map-land"); ctx.strokeStyle = css("--map-edge"); ctx.lineWidth = 0.7;
    for (const ring of D.outline) {
      ctx.beginPath(); ring.forEach(([lo, la], i) => i ? ctx.lineTo(px(lo), py(la)) : ctx.moveTo(px(lo), py(la))); ctx.closePath(); ctx.fill(); ctx.stroke();
    }
    const j = +$("mapDay").value, day = M.REC_DAYS[j];
    $("mapDayOut").textContent = dayLabel(day);
    const pb = cur.ser.perBus[j], order = Array.from({ length: P.n }, (_, i) => i).sort((a, b) => pb[a] - pb[b]);
    for (const i of order) {
      const r = 0.9 + Math.min(2.6, Math.sqrt(P.cust[i]) / 90);
      ctx.fillStyle = rampColor(pb[i]); ctx.beginPath(); ctx.arc(px(P.lon[i]), py(P.lat[i]), r, 0, 6.283); ctx.fill();
    }
    // 応援の車列
    const comp = D.companies, zi = Object.fromEntries(comp.keys.map((z, k) => [z, k])), O = cur.bld.O;
    const cent = {};
    for (let k = 0; k < P.nOffice; k++) { const z = O.zone[k]; (cent[z] ||= [0, 0, 0]); cent[z][0] += D.offices.lat[k] * O.cust[k]; cent[z][1] += D.offices.lon[k] * O.cust[k]; cent[z][2] += O.cust[k]; }
    const groups = {};
    for (const c of cur.sim.convoys) { const key = c.sender + ">" + c.receiver; (groups[key] ||= { s: c.sender, r: c.receiver, dep: 1e9, arr: 0, people: 0 }); const gg = groups[key]; gg.dep = Math.min(gg.dep, c.depart); gg.arr = Math.max(gg.arr, c.arrive); gg.people += c.people; }
    ctx.strokeStyle = css("--aid"); ctx.globalAlpha = 0.85;
    for (const gg of Object.values(groups)) {
      if (day < gg.dep) continue;
      const hs = comp.hq[zi[gg.s]], ce = cent[zi[gg.r]]; if (!hs || !ce) continue;
      const x0 = px(hs[1]), y0 = py(hs[0]), x1 = px(ce[1] / ce[2]), y1 = py(ce[0] / ce[2]);
      const f = Math.min(1, Math.max(0, (day - gg.dep) / Math.max(gg.arr - gg.dep, 1e-6)));
      ctx.lineWidth = 0.8 + 3 * Math.sqrt(gg.people / 3000);
      ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x0 + (x1 - x0) * f, y0 + (y1 - y0) * f); ctx.stroke();
    }
    ctx.globalAlpha = 1;
    // 選んだ時刻の数字(地図の左上の海に置く)
    const o5 = cur.ser.out[j], aidNow = cur.sim.rec.aid[Math.round(day * 24)] || 0;
    const lines = [[`発災から ${dayLabel(day)}`, css("--ink"), `700 ${Math.max(15, Math.round(w / 55))}px ${css("--f-display")}`],
      [`停電中 ${man(o5[0])} 万軒`, css("--outage"), `500 ${Math.max(14, Math.round(w / 62))}px ${css("--f-num")}`],
      [`送電側 ${man(o5[1])}・配電だけ ${man(o5[2])}・全壊相当 ${man(o5[3])} 万軒`, css("--muted"), `400 ${Math.max(11, Math.round(w / 85))}px ${css("--f-body")}`],
      [`他社応援 ${fmt(aidNow)} 人が作業中`, css("--aid"), `400 ${Math.max(11, Math.round(w / 85))}px ${css("--f-body")}`]];
    let yy = 18 + Math.max(15, Math.round(w / 55));
    for (const [txt, col, font] of lines) { ctx.font = font; ctx.fillStyle = col; ctx.fillText(txt, 18, yy); yy += Math.round(parseInt(font.split(" ")[1]) * 1.5); }
    // 事業所
    const fs = cur.sim.rec.fs[j], ft = cur.sim.rec.ft[j];
    ctx.lineWidth = 2;
    for (let k = 0; k < P.nOffice; k++) {
      const work = O.workS[k] + O.workT[k];
      const rem = work > 1 ? (fs[k] * O.workS[k] + ft[k] * O.workT[k]) / work : 0;
      const r = 2 + Math.sqrt(O.staff[k]) * 0.55;
      ctx.beginPath(); ctx.arc(px(D.offices.lon[k]), py(D.offices.lat[k]), r, 0, 6.283);
      ctx.fillStyle = css("--surface"); ctx.globalAlpha = 0.55; ctx.fill(); ctx.globalAlpha = 1;
      ctx.strokeStyle = work > 1 ? rampColor(rem) : css("--map-edge"); ctx.stroke();
    }
  }
  $("mapDay").max = M.REC_DAYS.length - 1;
  $("mapDay").addEventListener("input", () => cur && drawMap());
  let rz = null; window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => cur && drawMap(), 120); });

  function coTable() {
    const comp = D.companies, O = cur.bld.O, sim = cur.sim, by = cur.bld.byCo;
    const rows = [];
    for (let z = 0; z < comp.keys.length; z++) {
      const key = comp.keys[z];
      let cust = 0; for (let i = 0; i < P.n; i++) if (P.zone[i] === z) cust += P.cust[i];
      let staff = 0; for (let k = 0; k < P.nOffice; k++) if (O.zone[k] === z) staff += O.staff[k];
      if (cust <= 0 && !sim.senders.includes(key)) continue;
      const inAid = sim.convoys.filter(c => c.receiver === key).reduce((s, c) => s + c.people, 0);
      const outAid = sim.convoys.filter(c => c.sender === key).reduce((s, c) => s + c.people, 0);
      const first = Math.min(...sim.convoys.filter(c => c.receiver === key).map(c => c.arrive), Infinity);
      const r = sim.r[key];
      rows.push({ ja: comp.ja[z], cust, shake: by.shake[z], col: by.collapse[z], tsu: by.tsunami[z], staff, r, role: sim.receivers.includes(key) ? "recv" : sim.senders.includes(key) ? "send" : "", inAid, outAid, first });
    }
    rows.sort((a, b) => (b.r || 0) - (a.r || 0));
    const rmax = Math.max(...rows.map(x => x.r || 0), 0.5);
    $("coTable").innerHTML = `<thead><tr><th>会社</th><th>需要家</th><th>折れた電柱 揺れ</th><th>建物全壊</th><th>津波</th><th>人員</th><th>被害度</th><th>役割</th><th>応援を受ける</th><th>応援を送る</th><th>第 1 陣</th></tr></thead><tbody>` +
      rows.map(x => `<tr><td>${x.ja}</td><td class="num">${x.cust ? fmt(x.cust / 1e4) + " 万" : "—"}</td><td class="num">${fmt(x.shake)}</td><td class="num">${fmt(x.col)}</td><td class="num">${fmt(x.tsu)}</td>` +
        `<td class="num">${x.staff ? fmt(x.staff) : "—"}</td><td class="num">${x.r != null ? fmt(x.r, 2) : "—"}<span class="bar" style="width:${Math.round(40 * Math.min(1, (x.r || 0) / rmax))}px"></span></td>` +
        `<td>${x.role === "recv" ? '<span class="role recv">受け手</span>' : x.role === "send" ? '<span class="role send">送り手</span>' : ""}</td>` +
        `<td class="num">${x.inAid ? fmt(x.inAid) + " 人" : ""}</td><td class="num">${x.outAid ? fmt(x.outAid) + " 人" : ""}</td><td class="num">${isFinite(x.first) ? fmt(x.first, 2) + " 日" : ""}</td></tr>`).join("") + `</tbody>`;
  }

  function render(ms) {
    diffChip(); kpis(); chartDyn(); chartOut(); chartPeople(); drawMap(); coTable();
    const dc = dynOf(cur.keys);
    $("metaLine").textContent = `系統: 西 ${dc.west.run}・東 ${dc.east.run}(過負荷による遮断 西 ${fmt(dc.west.overload_trips, 1)}・東 ${fmt(dc.east.overload_trips, 1)} 回/サンプル)・計算 ${Math.round(ms)} ms・データ ${D.generated}`;
  }

  // テーマの切り替えに合わせて描き直す
  try { window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => cur && render(0)); } catch (e) { /* 古いブラウザ */ }
  new MutationObserver(() => cur && render(0)).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  syncInputs();
  recompute();
})();
