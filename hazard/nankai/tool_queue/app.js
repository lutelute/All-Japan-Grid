// 復旧の待ち行列卓の画面。計算は model.js(QM)。
(() => {
  const D = window.QUEUE_DATA;
  const M = QM.prepare(D);
  const $ = id => document.getElementById(id);
  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const JA = z => (M.comp[z] ? M.comp[z].ja : z);
  const DT = D.params.dt_d;
  const TMAX = 90, LMAX = Math.log10(1 + TMAX);
  const posToT = p => Math.pow(10, (p / 1000) * LMAX) - 1;
  const tToPos = t => Math.round((Math.log10(1 + t) / LMAX) * 1000);
  const xt = t => Math.log10(1 + Math.min(Math.max(t, 0), TMAX)) / LMAX;
  const TICKS = [[0, "直後"], [1, "1日"], [3, "3日"], [7, "1週"], [14, "2週"], [30, "1月"], [90, "3月"]];
  const jobByKey = new Map(M.jobs.map(j => [j.key, j]));

  const DEF_INP = QM.defaultInputs(M);
  const DEF = QM.simulate(M, DEF_INP);
  let inp = structuredClone(DEF_INP);
  let S = DEF;
  let tNow = 3;
  const senderColor = {};
  Object.keys(DEF.aid.senders).forEach((s, i) => { senderColor[s] = `--s${(i % 5) + 1}`; });
  const colorOf = s => { if (!senderColor[s]) senderColor[s] = `--s${(Object.keys(senderColor).length % 5) + 1}`; return css(senderColor[s]); };
  const zoneColor = z => css(`--z-${z}`) || css("--muted");
  let zoneSel = [...M.zones].sort((a, b) => M.jobs.filter(j => j.zone === b).length - M.jobs.filter(j => j.zone === a).length)[0];

  // ── 書式 ────────────────────────────────────────────────
  const man = v => (v / 1e4).toLocaleString("ja-JP", { maximumFractionDigits: 0 });
  const fmtDay = t => (t === undefined || t === null ? "—" : t < 1 ? `${Math.round(t * 24)} 時間` : `${t < 10 ? t.toFixed(1) : t.toFixed(0)} 日`);
  const clockText = t => { const d = Math.floor(t + 1e-9); let h = Math.round((t - d) * 24); let dd = d; if (h === 24) { dd += 1; h = 0; } return dd === 0 ? `${h} 時間` : h === 0 ? `${dd} 日` : `${dd} 日 ${h} 時間`; };
  const sIdx = t => Math.min(Math.round(t / DT), S.tg.length - 1);
  const interp = (xs, ys, x) => { if (x <= xs[0]) return ys[0]; for (let i = 1; i < xs.length; i++) if (x <= xs[i]) { const f = (x - xs[i - 1]) / (xs[i] - xs[i - 1]); return ys[i - 1] + f * (ys[i] - ys[i - 1]); } return ys[ys.length - 1]; };
  const outAt = (R, t) => interp(M.tEval, R.corr, t);
  const clearDay = R => { let m = 0; for (const z of M.zones) { const c = R.Q.zones[z].tClear; if (c === null) return null; m = Math.max(m, c); } return m; };
  const jobState = (R, j, t) => { const en = R.Q.end[j.key], st = R.Q.start[j.key]; if (en !== undefined && en <= t) return "done"; if (st !== undefined && st <= t) return "work"; return "wait"; };

  // ── 操作 ────────────────────────────────────────────────
  const SLIDERS = [
    ["crewScale", "crewScale", v => `×${v.toFixed(1)}`],
    ["harm", "harm", v => `×${v.toFixed(1)}`],
    ["resupply", "resupply_d", v => `${v} 日`],
    ["patrol", "patrol_d", v => `${v} 日`],
    ["aidPer", "aidPerMillion", v => v.toFixed(1)],
    ["decision", "decision_d", v => `${v} 日`],
    ["mobil", "mobilization_d", v => `${v} 日`],
    ["speed", "speed_kmh", v => `${v} km/h`],
  ];
  let timer = null;
  const schedule = () => { clearTimeout(timer); timer = setTimeout(recompute, 90); };
  for (const [id, key, fmt] of SLIDERS) {
    const el = $(id);
    el.addEventListener("input", () => { inp[key] = parseFloat(el.value); $(id + "Out").textContent = fmt(inp[key]); schedule(); });
  }
  document.querySelectorAll('input[name="policy"]').forEach(el => el.addEventListener("change", () => { inp.policy = el.value; recompute(); }));
  document.querySelectorAll('input[name="alloc"]').forEach(el => el.addEventListener("change", () => {
    inp.aidAlloc = el.value;
    if (inp.aidAlloc === "manual") ensureWeights();
    recompute();
  }));
  $("clearMoves").addEventListener("click", () => { inp.pins = []; inp.defers = []; recompute(); });
  $("resetBtn").addEventListener("click", () => { inp = structuredClone(DEF_INP); syncControls(); recompute(); });

  function syncControls() {
    for (const [id, key, fmt] of SLIDERS) { $(id).value = inp[key]; $(id + "Out").textContent = fmt(inp[key]); }
    document.querySelectorAll('input[name="policy"]').forEach(el => { el.checked = el.value === inp.policy; });
    document.querySelectorAll('input[name="alloc"]').forEach(el => { el.checked = el.value === inp.aidAlloc; });
  }

  function ensureWeights() {
    const recv = S.aid.receivers; let tot = 0; for (const z of recv) tot += S.aid.backlog[z];
    for (const z of recv) if (inp.aidWeights[z] === undefined) inp.aidWeights[z] = Math.round((100 * S.aid.backlog[z]) / Math.max(tot, 1e-9));
  }

  function renderWeights() {
    const box = $("weights"); const manual = inp.aidAlloc === "manual";
    const recv = S.aid.receivers; let totB = 0; for (const z of recv) totB += S.aid.backlog[z];
    let totW = 0; for (const z of recv) totW += manual ? (inp.aidWeights[z] ?? 0) : S.aid.backlog[z];
    box.innerHTML = recv.map(z => {
      const w = manual ? (inp.aidWeights[z] ?? 0) : Math.round((100 * S.aid.backlog[z]) / Math.max(totB, 1e-9));
      const share = manual ? (inp.aidWeights[z] ?? 0) / Math.max(totW, 1e-9) : S.aid.backlog[z] / Math.max(totB, 1e-9);
      return `<div class="w-row"><label for="w_${z}">${JA(z)}</label><input type="range" id="w_${z}" data-z="${z}" min="0" max="100" step="1" value="${w}" ${manual ? "" : "disabled"}><output for="w_${z}">${Math.round(share * 100)}%</output></div>`;
    }).join("");
    box.querySelectorAll("input").forEach(el => el.addEventListener("input", () => { inp.aidWeights[el.dataset.z] = parseFloat(el.value); schedule(); }));
  }

  // 例を試す: 既定の前提に戻してから 1 か所だけ変える
  const EXAMPLES = { short: { policy: "short" }, long: { policy: "long" }, half: { crewScale: 0.5 }, aid: { aidPerMillion: 5 } };
  $("examples").addEventListener("click", e => {
    const b = e.target.closest(".ex"); if (!b) return;
    inp = Object.assign(structuredClone(DEF_INP), EXAMPLES[b.dataset.ex]); syncControls(); recompute();
  });
  function activeExample() {
    if (movedCount() || inp.aidAlloc !== DEF_INP.aidAlloc) return null;
    for (const [name, ov] of Object.entries(EXAMPLES)) {
      const want = { ...DEF_INP, ...ov };
      if (inp.policy === want.policy && SLIDERS.every(([, key]) => inp[key] === want[key])) return name;
    }
    return null;
  }

  function renderSummary() {
    const box = $("summary");
    const aidTot = Object.values(S.aid.senders).reduce((a, v) => a + v, 0);
    const nomTot = S.avail.reduce((a, v) => a + v.nom, 0);
    const aidNote = `応援は合わせて ${aidTot.toFixed(0)} 班で、地元の ${nomTot.toFixed(0)} 班の ${Math.round((100 * aidTot) / Math.max(nomTot, 1))}% にあたる。`;
    const c = clearDay(S), c0 = clearDay(DEF);
    if (changedCount() === 0) {
      box.innerHTML = `既定の前提では、停電は 3 日後 <b>${man(outAt(S, 3))}</b> 万軒、1 か月後 <b>${man(outAt(S, 30))}</b> 万軒まで減り、送変電の修理が全部片付くのは <b>${c === null ? "400 日超" : Math.round(c) + " 日目"}</b>。左の前提を変えるか例を押すと、ここに既定との違いが出る。`;
      return;
    }
    const parts = [];
    for (const [d, lab] of [[7, "7 日後"], [30, "1 か月後"]]) {
      const dv = outAt(S, d) - outAt(DEF, d);
      if (Math.abs(dv) >= 1e4) parts.push(`${lab} <b class="${dv < 0 ? "better" : "worse"}">${dv < 0 ? "−" : "+"}${man(Math.abs(dv))} 万軒</b>`);
    }
    let txt = parts.length ? `既定と比べて、停電は ${parts.join("・")}。` : "既定と比べて、停電の数はほとんど変わらない(差は 1 万軒未満)。";
    if (c !== null && c0 !== null && Math.abs(c - c0) >= 1) txt += `修理が全部片付くのは <b class="${c < c0 ? "better" : "worse"}">${Math.abs(c - c0).toFixed(0)} 日${c < c0 ? "早い" : "遅い"}</b>(${Math.round(c)} 日目)。`;
    else if (c === null) txt += "修理は 400 日たっても片付かない。";
    const ex = activeExample();
    if (ex === "short") txt += "短い修理で件数を先に稼ぐぶん、津波で壊れた変電所のような長い修理が最後まで残る。";
    if (ex === "long") txt += "長い修理が先に班を抱え込み、その間ほかの修理が待たされる。";
    if (ex === "half") txt += "動ける班が減ったぶん、待ち行列が長く残る。";
    if (ex === "aid" || inp.aidPerMillion !== DEF_INP.aidPerMillion) txt += aidNote;
    box.innerHTML = txt;
  }

  function movedCount() { return inp.pins.length + inp.defers.length; }
  function changedCount() {
    let n = 0;
    for (const [, key] of SLIDERS) if (inp[key] !== DEF_INP[key]) n++;
    if (inp.policy !== DEF_INP.policy) n++;
    if (inp.aidAlloc !== DEF_INP.aidAlloc) n++;
    return n + (movedCount() ? 1 : 0);
  }

  // ── 計算し直し ──────────────────────────────────────────
  function recompute() {
    S = QM.simulate(M, inp);
    // 手で配っているときに受け手のエリアが増えたら、そのエリアの重みを修理の量の比で足して計算し直す
    if (inp.aidAlloc === "manual" && S.aid.receivers.some(z => inp.aidWeights[z] === undefined)) { ensureWeights(); S = QM.simulate(M, inp); }
    renderAll();
  }

  function renderAll() {
    const n = changedCount();
    const chip = $("diffChip"); chip.textContent = n ? `前提を ${n} 項目変えている` : "既定の前提"; chip.classList.toggle("changed", n > 0);
    $("movedCount").textContent = `${movedCount()} 件`;
    renderKpis(); renderSummary(); renderWeights(); renderTabs(); renderAtTime();
    const ex = activeExample();
    document.querySelectorAll("#examples .ex").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.ex === ex)));
    $("metaLine").textContent = `代表サンプル 西 #${D.seeds.west}・東 #${D.seeds.east} ・ 修理 ${M.jobs.length} 件(変電所 ${M.jobs.filter(j => j.kind === "s").length}・送電線 ${M.jobs.filter(j => j.kind === "l").length}) ・ 班の拠点 ${M.bases.length} ・ 生成 ${D.generated}`;
  }

  function renderAtTime() { renderStage(); renderQueue(); renderCharts(); }

  // ── KPI ────────────────────────────────────────────────
  function renderKpis() {
    const tile = (label, val, unit, delta, better) => `<div class="kpi"><span class="k-label">${label}</span><span class="k-val">${val}<span class="k-unit">${unit}</span></span><span class="k-delta ${better === null ? "" : better ? "better" : "worse"}">${delta}</span></div>`;
    const out = [];
    for (const d of [3, 7, 30]) {
      const v = outAt(S, d), v0 = outAt(DEF, d), dv = v - v0;
      const same = Math.abs(dv) < 5e3;
      out.push(tile(`停電 ${d === 30 ? "1 か月" : d + " 日"}後`, man(v), "万軒", same ? "既定と同じ" : `既定より ${dv > 0 ? "+" : "−"}${man(Math.abs(dv))} 万`, same ? null : dv < 0));
    }
    const c = clearDay(S), c0 = clearDay(DEF);
    const cTxt = c === null ? "400 日超" : `${Math.round(c)}`;
    const dd = c === null || c0 === null ? null : c - c0;
    out.push(tile("修理が全部片付く", cTxt, c === null ? "" : "日目", dd === null ? `既定 ${c0 === null ? "400 日超" : Math.round(c0) + " 日目"}` : Math.abs(dd) < 0.5 ? "既定と同じ" : `既定より ${dd > 0 ? "+" : "−"}${Math.abs(dd).toFixed(0)} 日`, dd === null || Math.abs(dd) < 0.5 ? null : dd < 0));
    $("kpis").innerHTML = out.join("");
  }

  // ── 地図と状態 ──────────────────────────────────────────
  const LON0 = 129.0, LON1 = 146.2, LAT0 = 30.8, LAT1 = 44.0, KX = Math.cos((37.5 * Math.PI) / 180);
  function convoyPaths() {
    const A = D.params.aid; const out = new Map();
    for (const c of S.aid.convoys) {
      const key = `${c.sender}>${c.zone}`;
      if (out.has(key)) { out.get(key).cs.push(c); continue; }
      const pts = [[c.legs[0][1], c.legs[0][0]]]; const segt = [];
      for (const l of c.legs) {
        if (l[5] === "sea" && A.ferry.waypoints.length) {
          const chain = [[l[1], l[0]], ...A.ferry.waypoints.map(q => [q[1], q[0]]), [l[3], l[2]]];
          const L = []; let sum = 0;
          for (let m = 0; m < chain.length - 1; m++) { const d = QM.gcKm(chain[m][1], chain[m][0], chain[m + 1][1], chain[m + 1][0]); L.push(d); sum += d; }
          for (let m = 0; m < chain.length - 1; m++) { pts.push(chain[m + 1]); segt.push((l[4] * L[m]) / sum); }
        } else { pts.push([l[3], l[2]]); segt.push(l[4]); }
      }
      let s0 = 0; for (const v of segt) s0 += v; segt[segt.length - 1] += c.travel - s0;
      out.set(key, { sender: c.sender, zone: c.zone, pts, segt, cs: [c] });
    }
    return [...out.values()];
  }

  function renderStage() {
    const t = tNow; const s = sIdx(t);
    $("clock").innerHTML = `${clockText(t)}<small>発災から</small>`;
    $("tScrub").value = tToPos(t);
    // 状態の集計
    let nW = 0, nR = 0, nD = 0;
    for (const j of M.jobs) { const st = jobState(S, j, t); if (st === "wait") nW++; else if (st === "work") nR++; else nD++; }
    let effNow = 0, nomAll = 0; S.avail.forEach(a => { effNow += a.eff[s]; nomAll += a.nom; });
    let aidNow = 0; for (const z of M.zones) aidNow += S.Q.zones[z].aid[s];
    const arr = S.aid.convoys.map(c => c.arrive); const first = arr.length ? Math.min(...arr) : Infinity, last = arr.length ? Math.max(...arr) : Infinity;
    let ph;
    if (t < inp.patrol_d) ph = "巡視・安全確認 — まだ修理に着手できない";
    else if (t < first) ph = "地元の班だけで着手 — 被災した拠点は人も車両も欠ける";
    else if (t <= last) ph = "他社の応援が順に到着する";
    else if (nW > 0) ph = "待ち行列を消化している";
    else if (nR > 0) ph = "残った長い修理を片付けている";
    else ph = "送変電の修理はすべて終わった";
    $("phase").textContent = ph;
    $("facts").innerHTML = [
      ["地元の班", `動ける ${effNow.toFixed(0)} / 被災前 ${nomAll.toFixed(0)} 班`],
      ["他社の応援", `着いている ${aidNow.toFixed(0)} 班`],
      ["修理", `作業中 ${nR} ・ 待ち ${nW} ・ 完了 ${nD} 件`],
      ["停電", `${man(outAt(S, t))} 万軒(既定 ${man(outAt(DEF, t))} 万)`],
    ].map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
    const snd = Object.entries(S.aid.senders);
    $("convoys").innerHTML = snd.length ? snd.map(([sd, pool]) => {
      const w0 = S.aid.convoys.filter(c => c.sender === sd && c.wave === 0);
      const a0 = Math.min(...w0.map(c => c.arrive)), a1 = Math.max(...w0.map(c => c.arrive));
      return `<li><i style="background:${colorOf(sd)}"></i><span><b>${JA(sd)}</b> ${pool.toFixed(0)} 班${sd === "hokkaido" ? "(海路)" : ""}</span><span class="num">${fmtDay(a0)}〜${fmtDay(a1)}</span></li>`;
    }).join("") : `<li><i></i><span>送り手になれる会社が無い(応援 0)</span><span></span></li>`;
    drawMap(t, s);
  }

  function drawMap(t, s) {
    const cv = $("map"); const dpr = window.devicePixelRatio || 1;
    const W = cv.clientWidth, H = cv.clientHeight; if (!W || !H) return;
    if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
    const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const sx = (W - 16) / ((LON1 - LON0) * KX), sy = (H - 16) / (LAT1 - LAT0); const sc = Math.min(sx, sy);
    const ox = (W - (LON1 - LON0) * KX * sc) / 2, oy = (H - (LAT1 - LAT0) * sc) / 2;
    const P = (lat, lon) => [ox + (lon - LON0) * KX * sc, oy + (LAT1 - lat) * sc];
    g.fillStyle = css("--map-bg"); g.fillRect(0, 0, W, H);
    g.fillStyle = css("--map-land"); g.strokeStyle = css("--map-edge"); g.lineWidth = 0.7;
    for (const ring of D.outline) { g.beginPath(); ring.forEach(([lo, la], i) => { const [x, y] = P(la, lo); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.closePath(); g.fill(); g.stroke(); }
    // 応援の経路と移動中の班
    const paths = convoyPaths();
    for (const p of paths) {
      const dep = Math.min(...p.cs.map(c => c.depart)), arrN = Math.max(...p.cs.map(c => c.arrive));
      if (t < dep) continue;
      const col = colorOf(p.sender);
      g.strokeStyle = col; g.globalAlpha = t < arrN ? 0.55 : 0.15; g.lineWidth = 1.3; g.setLineDash(p.sender === "hokkaido" ? [4, 3] : []);
      g.beginPath(); p.pts.forEach(([lo, la], i) => { const [x, y] = P(la, lo); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke();
      g.setLineDash([]); g.globalAlpha = 1;
      const cum = [0]; for (const v of p.segt) cum.push(cum[cum.length - 1] + v);
      for (const c of p.cs) {
        if (!(c.depart <= t && t < c.arrive)) continue;
        const el = t - c.depart; let k = 0; while (k < p.segt.length - 1 && cum[k + 1] <= el) k++;
        const f = Math.min(1, (el - cum[k]) / Math.max(p.segt[k], 1e-9));
        const a = p.pts[k], b = p.pts[k + 1]; const [x, y] = P(a[1] + (b[1] - a[1]) * f, a[0] + (b[0] - a[0]) * f);
        g.fillStyle = col; g.strokeStyle = css("--surface"); g.lineWidth = 1.2;
        g.beginPath(); g.arc(x, y, 3 + Math.sqrt(c.crews) * 0.9, 0, 2 * Math.PI); g.fill(); g.stroke();
      }
    }
    // 壊れた設備(完了したものは描かない)
    const cw = css("--wait"), ck = css("--work");
    for (const j of M.jobs) {
      const st = jobState(S, j, t); if (st === "done") continue;
      const [x, y] = P(j.lat, j.lon); const r = Math.max(1.8, Math.min(5.5, j.kv / 60));
      g.fillStyle = st === "work" ? ck : cw; g.globalAlpha = st === "work" ? 1 : 0.85;
      g.beginPath(); g.arc(x, y, r, 0, 2 * Math.PI); g.fill();
      if (j.key === hoverKey) { g.globalAlpha = 1; g.strokeStyle = css("--ink"); g.lineWidth = 2; g.beginPath(); g.arc(x, y, r + 4, 0, 2 * Math.PI); g.stroke(); }
    }
    g.globalAlpha = 1;
    // 地元の班の拠点
    const acc = css("--accent"), mut = css("--muted"), out = css("--outage");
    M.bases.forEach((B, k) => {
      const a = S.avail[k]; const eff = a.eff[s], nom = a.nom; const [x, y] = P(B.lat, B.lon);
      const rn = 2 + Math.sqrt(nom) * 1.6, re = 2 + Math.sqrt(Math.max(eff, 0)) * 1.6;
      g.strokeStyle = mut; g.lineWidth = 1; g.beginPath(); g.arc(x, y, rn, 0, 2 * Math.PI); g.stroke();
      g.fillStyle = eff / Math.max(nom, 1e-9) < 0.6 ? out : acc; g.globalAlpha = 0.8;
      g.beginPath(); g.arc(x, y, re, 0, 2 * Math.PI); g.fill(); g.globalAlpha = 1;
    });
    // 送り手の本店
    g.font = `700 12px ${css("--f-body")}`; g.textBaseline = "middle";
    for (const [sd, pool] of Object.entries(S.aid.senders)) {
      const [la, lo] = M.comp[sd].hq; const [x, y] = P(la, lo); const col = colorOf(sd);
      g.fillStyle = col; g.strokeStyle = css("--surface"); g.lineWidth = 1.5; g.fillRect(x - 5, y - 5, 10, 10); g.strokeRect(x - 5, y - 5, 10, 10);
      g.fillStyle = col; g.fillText(`${JA(sd)} ${pool.toFixed(0)} 班`, x + 9, y);
    }
  }

  // ── 待ち行列の表 ────────────────────────────────────────
  let hoverKey = null;
  function renderTabs() {
    const zs = [...M.zones].sort((a, b) => M.jobs.filter(j => j.zone === b).length - M.jobs.filter(j => j.zone === a).length);
    $("tabs").innerHTML = zs.map(z => `<button type="button" class="tab" role="tab" data-z="${z}" aria-selected="${z === zoneSel}"><span>${JA(z)}</span><span class="n">${M.jobs.filter(j => j.zone === z).length}</span></button>`).join("");
    $("tabs").querySelectorAll(".tab").forEach(b => b.addEventListener("click", () => { zoneSel = b.dataset.z; renderTabs(); renderQueue(); }));
  }

  function renderQueue() {
    const z = zoneSel, R = S.Q.zones[z], R0 = DEF.Q.zones[z], t = tNow;
    const pins = new Set(inp.pins), defs = new Set(inp.defers);
    let nW = 0, nR = 0, nD = 0;
    const rows = R.order.map((k, i) => {
      const j = jobByKey.get(k); const st = jobState(S, j, t);
      if (st === "wait") nW++; else if (st === "work") nR++; else nD++;
      const moved = pins.has(k) || defs.has(k);
      const stTxt = st === "done" ? `<span class="st done">完了</span>` : st === "work" ? `<span class="st work">修理中</span>` : `<span class="st wait">待ち</span>`;
      const tags = (j.ts >= 1 ? `<span class="tag ts">津波</span>` : "") + (pins.has(k) ? `<span class="tag pin">先に</span>` : defs.has(k) ? `<span class="tag pin">後回し</span>` : "");
      const acts = moved ? `<button type="button" class="mini" data-act="undo" data-key="${k}">戻す</button>`
        : `<button type="button" class="mini" data-act="pin" data-key="${k}">先に</button><button type="button" class="mini" data-act="defer" data-key="${k}">後回し</button>`;
      return `<tr class="${st === "work" ? "running" : st === "done" ? "done" : ""} ${moved ? "moved" : ""}" data-key="${k}">
        <td class="num">${i + 1}</td><td class="l name" title="${j.name}">${j.name}${tags}</td><td class="l">${j.kind === "s" ? "変電所" : "送電線"}</td>
        <td class="num">${j.kv.toFixed(0)}</td><td class="num">${j.cust > 0 ? Math.round(j.cust).toLocaleString("ja-JP") : "—"}</td>
        <td class="num">${j.dur.toFixed(1)}</td><td class="num">${fmtDay(S.Q.start[k])}</td><td class="num">${fmtDay(S.Q.end[k])}</td>
        <td>${stTxt}</td><td><span class="acts">${acts}</span></td></tr>`;
    });
    $("qtable").innerHTML = `<thead><tr><th>順</th><th class="l">設備</th><th class="l">種類</th><th>kV</th><th>直結の需要家</th><th>修理日数</th><th>着手</th><th>完了</th><th>状態</th><th>順番</th></tr></thead><tbody>${rows.join("")}</tbody>`;
    const s = sIdx(t);
    const clr = R.tClear === null ? "400 日超" : `${Math.round(R.tClear)} 日目`, clr0 = R0.tClear === null ? "400 日超" : `${Math.round(R0.tClear)} 日目`;
    $("qbar").innerHTML = `<span class="count">${JA(z)} <b>${R.n}</b> 件</span><span class="count">修理中 <b>${nR}</b> ・ 待ち <b>${nW}</b> ・ 完了 <b>${nD}</b></span>` +
      `<span class="count">当たれる班 <b>${Math.floor(R.cap[s] + 1e-6)}</b>(地元 ${R.local[s].toFixed(0)}・応援 ${R.aid[s].toFixed(0)})</span><span class="spacer"></span>` +
      `<span class="count">全部片付く <b>${clr}</b>(既定 ${clr0})</span>`;
  }

  $("qtable").addEventListener("click", e => {
    const b = e.target.closest("button[data-act]"); if (!b) return;
    const k = b.dataset.key;
    inp.pins = inp.pins.filter(x => x !== k); inp.defers = inp.defers.filter(x => x !== k);
    if (b.dataset.act === "pin") inp.pins.unshift(k);
    if (b.dataset.act === "defer") inp.defers.push(k);
    recompute();
  });
  $("qtable").addEventListener("mouseover", e => { const tr = e.target.closest("tr[data-key]"); const k = tr ? tr.dataset.key : null; if (k !== hoverKey) { hoverKey = k; drawMap(tNow, sIdx(tNow)); } });
  $("qtable").addEventListener("mouseleave", () => { hoverKey = null; drawMap(tNow, sIdx(tNow)); });

  // ── グラフ ─────────────────────────────────────────────
  const DISP = (() => { const out = []; for (let s = 0; s < S.tg.length; s++) { const t = s * DT; if (t > TMAX + 1e-9) break; if (t < 3 || (t < 14 && s % 3 === 0) || s % 12 === 0) out.push(s); } return out; })();
  function frame(Wd, Hd, ymax, ylab) {
    const m = { l: 46, r: 14, t: 10, b: 26 }; const iw = Wd - m.l - m.r, ih = Hd - m.t - m.b;
    const X = t => m.l + xt(t) * iw, Y = v => m.t + ih - (v / ymax) * ih;
    const yt = niceTicks(ymax);
    let s = `<g class="grid">${yt.map(v => `<line x1="${m.l}" x2="${m.l + iw}" y1="${Y(v)}" y2="${Y(v)}"/>`).join("")}</g>`;
    s += yt.map(v => `<text x="${m.l - 6}" y="${Y(v) + 4}" text-anchor="end">${v.toLocaleString("ja-JP")}</text>`).join("");
    s += TICKS.map(([t, l]) => `<text x="${X(t)}" y="${m.t + ih + 17}" text-anchor="middle">${l}</text>`).join("");
    s += `<line class="axis" x1="${m.l}" x2="${m.l + iw}" y1="${m.t + ih}" y2="${m.t + ih}"/>`;
    s += `<line class="now" x1="${X(tNow)}" x2="${X(tNow)}" y1="${m.t}" y2="${m.t + ih}"/>`;
    if (ylab) s += `<text x="${m.l}" y="${m.t - 0}" dy="-2" style="font-family:var(--f-body)">${ylab}</text>`;
    return { s, X, Y, m, iw, ih };
  }
  function niceTicks(max) { const raw = max / 4; const p = Math.pow(10, Math.floor(Math.log10(raw))); const st = [1, 2, 2.5, 5, 10].map(k => k * p).find(k => k >= raw) || raw; const out = []; for (let v = 0; v <= max + 1e-9; v += st) out.push(Math.round(v * 100) / 100); return out; }
  const path = (xs, ys) => xs.map((x, i) => `${i ? "L" : "M"}${x.toFixed(1)},${ys[i].toFixed(1)}`).join("");

  function crewSeries(R) {
    const local = DISP.map(s => { let v = 0; for (const z of M.zones) v += R.Q.zones[z].local[s]; return v; });
    const bySender = {};
    for (const sd of Object.keys(R.aid.senders)) bySender[sd] = DISP.map(() => 0);
    for (const c of R.aid.convoys) {
      const tc = R.Q.zones[c.zone] ? R.Q.zones[c.zone].tClear : null;
      DISP.forEach((s, i) => { const t = s * DT; if (c.arrive <= t && (tc === null || t <= tc + D.params.aid.return_d)) bySender[c.sender][i] += c.crews; });
    }
    return { local, bySender };
  }

  function renderCharts() {
    const Wd = 560, Hd = 230;
    // 1) 班
    const cs = crewSeries(S), c0 = crewSeries(DEF);
    const tot = DISP.map((_, i) => cs.local[i] + Object.values(cs.bySender).reduce((a, v) => a + v[i], 0));
    const tot0 = DISP.map((_, i) => c0.local[i] + Object.values(c0.bySender).reduce((a, v) => a + v[i], 0));
    const ymax1 = Math.max(10, ...tot, ...tot0) * 1.12;
    let F = frame(Wd, Hd, ymax1, "班");
    const xs = DISP.map(s => F.X(s * DT));
    let base = DISP.map(() => 0); let body = "";
    const layers = [["地元", cs.local, css("--accent")], ...Object.entries(cs.bySender).map(([sd, v]) => [`応援: ${JA(sd)}`, v, colorOf(sd)])];
    for (const [, v, col] of layers) {
      const top = base.map((b, i) => b + v[i]);
      body += `<path d="${path(xs, top.map(F.Y))}L${xs[xs.length - 1].toFixed(1)},${F.Y(base[base.length - 1]).toFixed(1)}${xs.slice().reverse().map((x, i) => `L${x.toFixed(1)},${F.Y(base[base.length - 1 - i]).toFixed(1)}`).join("")}Z" fill="${col}" fill-opacity="0.8" stroke="none"/>`;
      base = top;
    }
    body += `<path d="${path(xs, tot0.map(F.Y))}" fill="none" stroke="${css("--ink")}" stroke-opacity=".55" stroke-width="1.4" stroke-dasharray="5 4"/>`;
    $("chartCrews").innerHTML = `<svg viewBox="0 0 ${Wd} ${Hd}">${F.s}${body}</svg>`;
    $("legendCrews").innerHTML = layers.map(([l, , c]) => `<span><i style="background:${c}"></i>${l}</span>`).join("") + `<span><i class="dash" style="border-color:${css("--ink")}"></i>既定の合計</span>`;
    // 2) 待ち行列
    const zs = [...M.zones];
    const ymax2 = Math.max(5, ...zs.map(z => Math.max(...DISP.map(s => S.Q.zones[z].queue[s])))) * 1.12;
    F = frame(Wd, Hd, ymax2, "件");
    body = zs.map(z => `<path d="${path(xs, DISP.map(s => F.Y(S.Q.zones[z].queue[s])))}" fill="none" stroke="${zoneColor(z)}" stroke-width="${z === zoneSel ? 2.6 : 1.5}"/>`).join("");
    $("chartQueue").innerHTML = `<svg viewBox="0 0 ${Wd} ${Hd}">${F.s}${body}</svg>`;
    $("legendQueue").innerHTML = zs.map(z => `<span><i class="line" style="border-color:${zoneColor(z)}"></i>${JA(z)}</span>`).join("");
    // 3) 停電
    const W3 = 1100, H3 = 250;
    const ymax3 = Math.max(...S.corr, ...DEF.corr) / 1e4 * 1.1;
    F = frame(W3, H3, ymax3, "万軒");
    const xe = M.tEval.map(t => F.X(t));
    body = `<path d="${path(xe, Array.from(DEF.corr, v => F.Y(v / 1e4)))}" fill="none" stroke="${css("--ink")}" stroke-opacity=".55" stroke-width="1.4" stroke-dasharray="5 4"/>`;
    body += `<path d="${path(xe, Array.from(S.corr, v => F.Y(v / 1e4)))}" fill="none" stroke="${css("--outage")}" stroke-width="2.6"/>`;
    const vNow = outAt(S, tNow) / 1e4;
    body += `<circle cx="${F.X(tNow)}" cy="${F.Y(vNow)}" r="4" fill="${css("--outage")}"/><text x="${F.X(tNow) + (xt(tNow) < 0.85 ? 8 : -8)}" y="${F.Y(vNow) - 8}" text-anchor="${xt(tNow) < 0.85 ? "start" : "end"}" style="fill:var(--ink)">${man(vNow * 1e4)} 万軒</text>`;
    $("chartOut").innerHTML = `<svg viewBox="0 0 ${W3} ${H3}">${F.s}${body}</svg>`;
    $("legendOut").innerHTML = `<span><i class="line" style="border-color:${css("--outage")}"></i>いまの前提</span><span><i class="dash" style="border-color:${css("--ink")}"></i>既定の前提</span>`;
  }

  // ── 時刻 ───────────────────────────────────────────────
  let raf = null, playing = false;
  $("tScrub").addEventListener("input", e => { tNow = posToT(parseFloat(e.target.value)); stop(); requestAnimationFrame(renderAtTime); });
  function stop() { playing = false; $("playBtn").textContent = "▶ 再生"; $("playBtn").setAttribute("aria-pressed", "false"); if (raf) cancelAnimationFrame(raf); raf = null; }
  $("playBtn").addEventListener("click", () => {
    if (playing) { stop(); return; }
    playing = true; $("playBtn").textContent = "❚❚ 止める"; $("playBtn").setAttribute("aria-pressed", "true");
    let p = tToPos(tNow); if (p >= 999) p = 0;
    let last = performance.now();
    const step = now => {
      if (!playing) return;
      p = Math.min(1000, p + ((now - last) / 20000) * 1000); last = now;
      tNow = posToT(p); renderAtTime();
      if (p >= 1000) { stop(); return; }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
  });
  window.addEventListener("resize", () => drawMap(tNow, sIdx(tNow)));
  if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", renderAll);
  new MutationObserver(renderAll).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  syncControls();
  renderAll();
})();
