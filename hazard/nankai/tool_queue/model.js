// 復旧の待ち行列卓の計算。make_restoration_ops.py の availability / mutual_aid / run_queues をそのまま移したものと、
// 電源とのつながり判定(CascadeModel.evaluate の run_pf=False と同じ)。tool_queue/test_model.mjs で Python と照合する。
const QM = (() => {
  const DT_EPS = 1e-9;

  function buf(s) {
    const bin = atob(s); const u = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
    return u.buffer;
  }
  const f64 = s => new Float64Array(buf(s));
  const i32 = s => new Int32Array(buf(s));
  const u8 = s => new Uint8Array(buf(s));

  // ── データの展開 ──────────────────────────────────────────
  function prepare(D) {
    const jobs = D.jobs.map((j, k) => ({ ...j, k, key: `${j.island}:${j.kind}:${j.idx}` }));
    const zones = [...new Set(jobs.map(j => j.zone))].sort();
    const bases = D.bases.map(B => ({ ...B, clsA: u8(B.cls), tsA: u8(B.ts), wA: f64(B.w) }));
    const grid = {};
    for (const isl of D.islands) {
      const g = D.grid[isl];
      grid[isl] = { ...g, bus_site: i32(g.bus_site), cust: f64(g.cust), bo_until: f64(g.bo_until), f: i32(g.f), t: i32(g.t),
        gb: i32(g.gb), cap_e: f64(g.cap_e), cap_l: f64(g.cap_l), ginf: u8(g.ginf), done_gen: f64(g.done_gen) };
    }
    const co = D.companies; const comp = {};
    co.keys.forEach((z, i) => { comp[z] = { key: z, ja: co.ja[i], contracts: co.contracts_thousand[i], crews: co.crews_base[i], hq: co.hq[i] }; });
    return { D, jobs, zones, bases, grid, comp, compKeys: co.keys, classes: D.classes, tEval: D.t_eval, offset: D.offset };
  }

  function defaultInputs(M) {
    const p = M.D.params;
    return { policy: "kv_load", pins: [], defers: [], crewScale: 1.0, harm: 1.0, resupply_d: p.equipment.resupply_d, patrol_d: p.patrol_d,
      aidPerMillion: p.aid.crews_per_million, decision_d: p.aid.decision_d, mobilization_d: p.aid.mobilization_d, speed_kmh: p.aid.speed_kmh,
      aidAlloc: "backlog", aidWeights: {} };
  }

  // ── 要員と資機材の被災(availability) ─────────────────────────
  function baseGroups(M, B, inp) {
    const P = M.D.params.personnel, E = M.D.params.equipment, C = M.classes;
    const cap1 = x => Math.min(1, x);
    const groups = new Map();
    for (let i = 0; i < B.wA.length; i++) {
      const lab = C[B.clsA[i]], ts = B.tsA[i] === 1;
      const us = cap1((P.unavailable_by_class[lab] ?? 0) * inp.harm);
      const ut = ts ? cap1(P.tsunami_unavailable * inp.harm) : 0;
      const e0 = Math.max(ts ? E.loss_if_inundated : 0, E.loss_by_class[lab] ?? 0);
      const key = `${us}|${ut}|${e0}`;
      let g = groups.get(key);
      if (!g) { g = { us, ut, e0, w: 0, c: 0 }; groups.set(key, g); }
      const y = B.wA[i] - g.c; const t = g.w + y; g.c = t - g.w - y; g.w = t;       // pandas の groupby.sum と同じ補償付き加算
    }
    return [...groups.values()].sort((a, b) => a.us - b.us || a.ut - b.ut || a.e0 - b.e0);
  }

  function availability(M, inp, tg) {
    const P = M.D.params.personnel;
    const ps = P.permanent_share, ts_ = P.tau_shake_d, tt_ = P.tau_tsunami_d, rs = inp.resupply_d;
    const n = tg.length;
    const gs = new Float64Array(n), gt = new Float64Array(n), ge = new Float64Array(n);
    for (let s = 0; s < n; s++) {
      const t = tg[s];
      gs[s] = ps + (1 - ps) * Math.exp(-t / ts_); gt[s] = ps + (1 - ps) * Math.exp(-t / tt_);
      ge[s] = Math.min(1, Math.max(0, 1 - t / rs));
    }
    return M.bases.map(B => {
      const eff = new Float64Array(n), pers = new Float64Array(n), equip = new Float64Array(n);
      const nom = B.crews_nom * inp.crewScale;
      for (const g of baseGroups(M, B, inp)) {
        const cw = nom * g.w;
        for (let s = 0; s < n; s++) {
          const pa = (1 - g.us * gs[s]) * (1 - g.ut * gt[s]); const ea = 1 - g.e0 * ge[s];
          pers[s] += g.w * pa; equip[s] += g.w * ea; eff[s] += cw * pa * ea;
        }
      }
      return { eff, pers, equip, nom };
    });
  }

  // ── 他社応援(mutual_aid) ───────────────────────────────────
  const DEG = Math.PI / 180; const rad = d => d * DEG;                 // numpy.radians と同じ(定数を先に作ってから掛ける)
  function gcKm(la1, lo1, la2, lo2) {
    const p1 = rad(la1), p2 = rad(la2), dl = rad(lo2 - lo1);
    const s1 = Math.sin((p2 - p1) / 2), s2 = Math.sin(dl / 2);
    const a = s1 * s1 + Math.cos(p1) * Math.cos(p2) * (s2 * s2);
    return 6371.0 * 2 * Math.asin(Math.sqrt(Math.min(1, Math.max(0, a))));
  }

  function mutualAid(M, inp) {
    const A = M.D.params.aid;
    const backlog = {}, r = {};
    for (const z of M.compKeys) {
      let cd = 0; for (const j of M.jobs) if (j.zone === z) cd += j.dur;
      backlog[z] = cd; r[z] = cd / (M.comp[z].crews * inp.crewScale * A.horizon_d);
    }
    const excluded = new Set(A.excluded);
    const senders = {};
    for (const z of M.compKeys) {
      if (excluded.has(z) || !(r[z] < 1.0)) continue;
      const v = inp.aidPerMillion * M.comp[z].contracts / 1000.0 * Math.max(0.0, 1.0 - r[z]);
      if (v > 0.5) senders[z] = v;
    }
    const recv = M.compKeys.filter(z => r[z] > A.receiver_threshold_r);
    const weight = z => (inp.aidAlloc === "manual" ? (inp.aidWeights[z] ?? backlog[z]) : backlog[z]);
    let totW = 0; for (const z of recv) totW += weight(z);
    const road = (la1, lo1, la2, lo2) => gcKm(la1, lo1, la2, lo2) * A.detour / (inp.speed_kmh * A.drive_h);
    const convoys = [];
    for (const s of Object.keys(senders)) {
      const pool = senders[s];
      for (const z of recv) {
        if (z === s) continue;
        const tg = M.D.targets[z]; if (!tg) continue;
        const share = totW > 0 ? weight(z) / totW : 0;
        const [tla, tlo] = tg; const [hla, hlo] = M.comp[s].hq;
        let legs;
        if (s === "hokkaido") {
          const p1 = A.ferry.port_from, p2 = A.ferry.port_to;
          legs = [[hla, hlo, p1[0], p1[1], road(hla, hlo, p1[0], p1[1]), "road"], [p1[0], p1[1], p2[0], p2[1], A.ferry.sea_d, "sea"],
                  [p2[0], p2[1], tla, tlo, road(p2[0], p2[1], tla, tlo), "road"]];
        } else {
          legs = [[hla, hlo, tla, tlo, road(hla, hlo, tla, tlo), "road"]];
        }
        const extra = A.in_area_d * Math.min(1.0, r[z]);
        let travel = 0; for (const l of legs) travel += l[4]; travel += extra;
        A.waves.offsets.forEach((off, wv) => {
          const dep = inp.decision_d + inp.mobilization_d + off;
          convoys.push({ sender: s, zone: z, wave: wv, crews: pool * share * A.waves.shares[wv], depart: dep, arrive: dep + travel, legs, travel });
        });
      }
    }
    return { r, backlog, senders, receivers: recv, convoys };
  }

  // ── 待ち行列(run_queues) ────────────────────────────────────
  const POLICIES = {
    kv_load: (a, b) => (b.kv - a.kv) || (b.load_mw - a.load_mw),
    load: (a, b) => b.load_mw - a.load_mw,
    cust_per_day: (a, b) => (b.cust / b.dur) - (a.cust / a.dur),
    short: (a, b) => a.dur - b.dur,
    long: (a, b) => b.dur - a.dur,
  };

  function orderZone(M, z, inp) {
    const js = M.jobs.filter(j => j.zone === z);                  // 島の順・ジョブの順(Python と同じ)で並べてから安定ソート
    js.sort(POLICIES[inp.policy]);
    const pins = inp.pins.map(k => js.find(j => j.key === k)).filter(Boolean);
    const defer = inp.defers.map(k => js.find(j => j.key === k)).filter(Boolean);
    const skip = new Set([...pins, ...defer]);
    return [...pins, ...js.filter(j => !skip.has(j)), ...defer];
  }

  function heapPush(h, v) { h.push(v); let i = h.length - 1; while (i > 0) { const p = (i - 1) >> 1; if (h[p] <= h[i]) break; [h[p], h[i]] = [h[i], h[p]]; i = p; } }
  function heapPop(h) {
    const top = h[0]; const last = h.pop();
    if (h.length) { h[0] = last; let i = 0; for (;;) { const l = 2 * i + 1, r = l + 1; let m = i; if (l < h.length && h[l] < h[m]) m = l; if (r < h.length && h[r] < h[m]) m = r; if (m === i) break; [h[m], h[i]] = [h[i], h[m]]; i = m; } }
    return top;
  }

  function runQueues(M, inp, aid, avail, tg) {
    const P = M.D.params;
    const res = {}; const start = {}, end = {};
    for (const z of M.zones) {
      const jobs = orderZone(M, z, inp);
      const local = new Float64Array(tg.length);
      M.bases.forEach((B, k) => { if (B.zone === z) { const e = avail[k].eff; for (let s = 0; s < tg.length; s++) local[s] += e[s]; } });
      const cz = aid.convoys.filter(c => c.zone === z);
      const n = jobs.length; let qi = 0; const run = []; let tClear = null;
      const qlen = new Float32Array(tg.length), nrun = new Float32Array(tg.length), aidNow = new Float32Array(tg.length), cap = new Float32Array(tg.length);
      for (let s = 0; s < tg.length; s++) {
        const t = tg[s];
        while (run.length && run[0] <= t + DT_EPS) heapPop(run);
        let present = 0; for (const c of cz) if (c.arrive <= t) present += c.crews;
        if (tClear !== null && t > tClear + P.aid.return_d) present = 0.0;
        const c = t < inp.patrol_d ? 0.0 : local[s] + present;
        while (qi < n && run.length < Math.floor(c + 1e-6)) {
          const j = jobs[qi]; const en = t + j.dur; heapPush(run, en); start[j.key] = t; end[j.key] = en; qi++;
        }
        if (tClear === null && qi === n && run.length === 0) tClear = t;
        qlen[s] = n - qi; nrun[s] = run.length; aidNow[s] = present; cap[s] = c;
      }
      res[z] = { order: jobs.map(j => j.key), local, aid: aidNow, cap, queue: qlen, running: nrun, n, tClear };
    }
    return { zones: res, start, end };
  }

  // ── 電源とのつながり(CascadeModel.evaluate, run_pf=False) ─────────
  function customersOut(M, end, times) {
    const out = new Float64Array(times.length);
    for (const isl of M.D.islands) {
      const g = M.grid[isl];
      const ds = new Float64Array(g.n_site), dl = new Float64Array(g.n_br);
      for (const j of M.jobs) {
        if (j.island !== isl) continue;
        const e = end[j.key] ?? Infinity;
        if (j.kind === "s") ds[j.idx] = e; else dl[j.idx] = e;
      }
      const nb = g.n_bus, parent = new Int32Array(nb), alive = new Uint8Array(nb);
      const G = new Float64Array(nb), Ginf = new Uint8Array(nb);
      const find = x => { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
      times.forEach((t, k) => {
        for (let b = 0; b < nb; b++) { parent[b] = b; alive[b] = ds[g.bus_site[b]] > t ? 0 : 1; G[b] = 0; Ginf[b] = 0; }
        for (let e = 0; e < g.n_br; e++) {
          if (dl[e] > t) continue;
          const a = g.f[e], b = g.t[e];
          if (!alive[a] || !alive[b]) continue;
          const ra = find(a), rb = find(b); if (ra !== rb) parent[ra] = rb;
        }
        for (let q = 0; q < g.n_gen; q++) {
          const b = g.gb[q]; if (!alive[b]) continue;
          const r = find(b);
          if (!(g.done_gen[q] > t)) G[r] += t < 1.0 ? g.cap_e[q] : g.cap_l[q];
          if (g.ginf[q]) Ginf[r] = 1;
        }
        let tot = 0;
        for (let b = 0; b < nb; b++) {
          let phys = false;
          if (alive[b]) { const r = find(b); phys = (G[r] > 1e-6 || Ginf[r] === 1) && !(g.bo_until[b] > t); }
          if (!phys) tot += g.cust[b];
        }
        out[k] += tot;
      });
    }
    return out;
  }

  // ── 一式 ────────────────────────────────────────────────
  function simulate(M, inp) {
    const P = M.D.params;
    const n = Math.round(P.horizon_d / P.dt_d) + 1;
    const tg = new Float64Array(n); for (let s = 0; s < n; s++) tg[s] = s * P.dt_d;
    const avail = availability(M, inp, tg);
    const aid = mutualAid(M, inp);
    const Q = runQueues(M, inp, aid, avail, tg);
    const conn = customersOut(M, Q.end, M.tEval);
    const corr = Float64Array.from(conn, (v, k) => Math.max(0, v + M.offset[k]));
    return { inp, tg, avail, aid, Q, conn, corr };
  }

  return { prepare, defaultInputs, simulate, availability, mutualAid, runQueues, customersOut, orderZone, gcKm, POLICIES };
})();
if (typeof module !== "undefined") module.exports = QM;
