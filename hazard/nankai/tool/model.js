/* 南海トラフ停電シナリオ卓の計算部。make_restoration_workforce.py の build() / simulate() / customers_out を移したもの。
   ブラウザでは window.NankaiModel、node では module.exports。照合は tool/test_model.mjs(Python の reference.json と比べる)。 */
(function (root) {
  "use strict";

  function decode(b64, Type) {
    let bin;
    if (typeof atob === "function") {
      const s = atob(b64); bin = new Uint8Array(s.length);
      for (let i = 0; i < s.length; i++) bin[i] = s.charCodeAt(i);
    } else {
      bin = new Uint8Array(Buffer.from(b64, "base64"));
    }
    return new Type(bin.buffer, bin.byteOffset, bin.byteLength / Type.BYTES_PER_ELEMENT);
  }

  // 標準正規分布: Φ は erf の近似(Abramowitz & Stegun 7.1.26、誤差 1.5e-7)、Φ⁻¹ は Acklam の有理近似
  function normCdf(x) {
    const z = Math.abs(x) / Math.SQRT2, t = 1 / (1 + 0.3275911 * z);
    const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-z * z);
    return x >= 0 ? 0.5 * (1 + y) : 0.5 * (1 - y);
  }
  function normPpf(p) {
    const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
    const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
    const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
    const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
    const pl = 0.02425;
    if (p < pl) { const q = Math.sqrt(-2 * Math.log(p)); return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
    if (p > 1 - pl) { const q = Math.sqrt(-2 * Math.log(1 - p)); return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
    const q = p - 0.5, r = q * q;
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  }
  function gcKm(la1, lo1, la2, lo2) {
    const R = Math.PI / 180, p1 = la1 * R, p2 = la2 * R, dl = (lo2 - lo1) * R;
    const h = Math.sin((p2 - p1) / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
    return 6371 * 2 * Math.asin(Math.sqrt(Math.min(1, Math.max(0, h))));
  }

  /** 埋め込みデータを型付き配列にほどく(1 回だけ) */
  function prepare(D) {
    const B = D.buses, n = B.n;
    const P = {
      n, island: decode(B.island, Uint8Array), zone: decode(B.zone, Uint8Array), lat: decode(B.lat, Float32Array), lon: decode(B.lon, Float32Array),
      cust: decode(B.cust, Float32Array), intensity: decode(B.intensity, Float32Array), tsRank: decode(B.ts_rank, Uint8Array),
      tokyoBay: decode(B.tokyo_bay, Uint8Array), era: decode(B.era, Float32Array), woodenShare: decode(B.wooden_share, Float32Array), office: decode(B.office, Uint16Array),
    };
    // 島の中での通し番号(動的カスケードの母線配列と対応)
    P.local = new Int32Array(n); let w = 0, e = 0;
    for (let i = 0; i < n; i++) P.local[i] = P.island[i] ? e++ : w++;
    P.nWest = w; P.nEast = e;
    const cls = D.params.jma_classes;
    P.cls = new Array(n);
    for (let i = 0; i < n; i++) { let lab = "0"; for (const [th, l] of cls) if (P.intensity[i] >= th) lab = l; P.cls[i] = lab; }
    P.nOffice = D.offices.zone.length;
    P.dynCache = {};
    return P;
  }

  function dynArrays(D, P, island, key) {
    const ck = island + ":" + key;
    if (!P.dynCache[ck]) {
      const blk = D.dyn[island][key];
      P.dynCache[ck] = { pb: decode(blk.pb, Uint8Array), e10: decode(blk.e10, Uint8Array), tl: blk.timeline_days, nT: blk.timeline_days.length };
    }
    return P.dynCache[ck];
  }

  function scenarioKeys(o) {
    return { west: `ol${o.ol}_tr${o.tr}`, east: `ol${o.ol}_tr${o.tr}_tb${o.tb}` };
  }

  /** build(): 母線ごとの電柱被害 → 事業所に集計 */
  function build(D, P, o) {
    const pr = D.params, n = P.n, nO = P.nOffice, comp = D.companies;
    const sig = o.sigma, I0 = pr.anchor_intensity, ar = pr.anchor_rates;
    const mu = [I0 - sig * normPpf(ar.old), I0 - sig * normPpf(ar.mid), I0 - sig * normPpf(ar.new)];
    const brkS = new Float64Array(n), brkT = new Float64Array(n), outS = new Float64Array(n), outT = new Float64Array(n), lost = new Float64Array(n);
    const brkShakeOnly = new Float64Array(n), collapse = new Float64Array(n);
    const O = { workS: new Float64Array(nO), workT: new Float64Array(nO), outS: new Float64Array(nO), outT: new Float64Array(nO), cust: new Float64Array(nO),
      staff: new Float64Array(nO), uShake: new Float64Array(nO), uTs: new Float64Array(nO), zone: D.offices.zone };
    const byCo = { shake: new Float64Array(comp.keys.length), collapse: new Float64Array(comp.keys.length), tsunami: new Float64Array(comp.keys.length) };
    const cpp = pr.customers_per_broken_pole, coef = pr.collapse_coefficient, ppd = pr.poles_per_person_day;
    for (let i = 0; i < n; i++) {
      const rank = (!o.tb && P.tokyoBay[i]) ? 0 : P.tsRank[i];
      const ts = rank > 0, isLost = rank >= pr.not_restorable_tsunami_rank_min;
      const z = P.zone[i], cust = P.cust[i];
      const poles = cust * comp.poles_per_customer[z];
      const rate = pr.shaking_break_rate[P.cls[i]] || 0;
      let col = 0;
      if (o.collapse) {
        const x0 = P.era[3 * i], x1 = P.era[3 * i + 1], xn = P.era[3 * i + 2];
        const sh = [x0 * o.old_split, x0 * (1 - o.old_split) + x1, xn];
        const I = P.intensity[i];
        col = sh[0] * normCdf((I - mu[0]) / sig) + sh[1] * normCdf((I - mu[1]) / sig) + sh[2] * normCdf((I - mu[2]) / sig);
        if (o.basis === "all_dwellings") col *= P.woodenShare[i];
      }
      collapse[i] = col;
      let bs = ts ? 0 : Math.min(poles * (rate + coef * col), poles);
      let bt = ts ? poles * pr.tsunami_break_rate : 0;
      outS[i] = isLost ? 0 : Math.min(cust, bs * cpp);
      outT[i] = isLost ? 0 : Math.min(cust, bt * cpp);
      if (isLost) { bs = 0; bt = 0; }
      brkS[i] = bs; brkT[i] = bt; lost[i] = isLost ? cust : 0;
      const bso = ts ? 0 : poles * rate; brkShakeOnly[i] = isLost ? 0 : bso;
      byCo.shake[z] += isLost ? 0 : Math.min(bso, bs); byCo.collapse[z] += bs - Math.min(bso, bs); byCo.tsunami[z] += bt;
      const k = P.office[i];
      O.workS[k] += bs / ppd; O.workT[k] += bt / ppd; O.outS[k] += outS[i]; O.outT[k] += outT[i]; O.cust[k] += cust;
      O.uShake[k] += (pr.unavailable_by_class[P.cls[i]] || 0) * cust; O.uTs[k] += (ts ? pr.tsunami_unavailable : 0) * cust;
    }
    for (let k = 0; k < nO; k++) {
      O.staff[k] = O.cust[k] / 1e6 * o.spm;
      O.uShake[k] = O.cust[k] > 0 ? O.uShake[k] / O.cust[k] : 0; O.uTs[k] = O.cust[k] > 0 ? O.uTs[k] / O.cust[k] : 0;
    }
    return { brkS, brkT, outS, outT, lost, collapse, O, byCo };
  }

  const REC_DAYS = (() => {
    const a = [];
    for (let h = 0; h < 24; h += 2) a.push(h / 24);
    for (let d = 1; d < 14; d += 0.25) a.push(d);
    for (let d = 14; d <= 90; d += 2) a.push(d);
    return a;
  })();

  /** simulate(): 事業所の人員・社内融通・他社応援で残作業を減らす(1 時間刻み・90 日) */
  function simulate(D, P, o, bld) {
    const pr = D.params, comp = D.companies, O = bld.O, nO = P.nOffice;
    const dt = 1 / 24, nT = 90 * 24 + 1;
    const perm = pr.permanent_share, tauS = pr.tau_shake_d, tauT = pr.tau_tsunami_d;
    const zoneKey = comp.keys;
    const zonesPresent = [...new Set(O.zone)];
    const hqKeys = zoneKey.filter((z, i) => comp.hq[i] && comp.hq[i][0] != null);
    const compList = [...new Set([...zonesPresent.map(z => zoneKey[z]), ...hqKeys])].sort();
    const zi = Object.fromEntries(zoneKey.map((z, i) => [z, i]));
    const mob = {}, workC = {}, r = {};
    for (const c of compList) {
      mob[c] = comp.contracts_thousand[zi[c]] / 1000 * o.spm;
      let w = 0; for (let k = 0; k < nO; k++) if (zoneKey[O.zone[k]] === c) w += O.workS[k] + O.workT[k];
      workC[c] = w; r[c] = w / Math.max(mob[c] * 7, 1e-9);
    }
    const receivers = compList.filter(c => r[c] >= pr.receiver_threshold_r);
    const senders = compList.filter(c => r[c] < pr.sender_max_r && !receivers.includes(c) && c !== "okinawa" && mob[c] > 0);
    let wsum = receivers.reduce((s, c) => s + workC[c], 0) || 1;
    const convoys = [];
    for (const s of senders) {
      const people = o.aid * mob[s] * (1 - r[s] / pr.sender_max_r);
      for (const rc of receivers) {
        const share = workC[rc] / wsum; if (share <= 0) continue;
        const hs = comp.hq[zi[s]], hr = comp.hq[zi[rc]];
        const km = gcKm(hs[0], hs[1], hr[0], hr[1]) * pr.detour_factor;
        let travel = km / pr.convoy_speed_kmh / pr.drive_h_per_day;
        if (s === "hokkaido") travel += 1.0;
        pr.waves.offsets_d.forEach((off, wv) => {
          const tArr = pr.decision_d + pr.mobilization_d + off + travel;
          convoys.push({ sender: s, receiver: rc, people: people * share * pr.waves.shares[wv], arrive: tArr, depart: tArr - travel, km });
        });
      }
    }
    const remS = Float64Array.from(O.workS), remT = Float64Array.from(O.workT);
    const totS = O.workS.map(x => Math.max(x, 1e-9)), totT = O.workT.map(x => Math.max(x, 1e-9));
    const officesByZone = {}; for (let k = 0; k < nO; k++) (officesByZone[O.zone[k]] ||= []).push(k);
    const recIdx = new Map(REC_DAYS.map((d, j) => [Math.round(d * 24), j]));
    const rec = { days: REC_DAYS, fs: [], ft: [], own: new Float64Array(nT), internal: new Float64Array(nT), aid: new Float64Array(nT), remPolesByZone: [] };
    const base = new Float64Array(nO), people = new Float64Array(nO), internal = new Float64Array(nO), aid = new Float64Array(nO);
    const ppd = pr.poles_per_person_day, iw = pr.internal;
    for (let step = 0; step < nT; step++) {
      const t = step * dt;
      const ramp = Math.min(1, Math.max(0, (t - pr.patrol_d) / pr.call_up_d));
      const es = (1 - perm) * Math.exp(-t / tauS) + perm, et = (1 - perm) * Math.exp(-t / tauT) + perm;
      for (let k = 0; k < nO; k++) {
        const av = Math.min(1, Math.max(0.05, 1 - O.uShake[k] * es - O.uTs[k] * et));
        base[k] = O.staff[k] * av * ramp; people[k] = base[k]; internal[k] = 0; aid[k] = 0;
      }
      if (o.internal && t >= iw.start_d) {
        for (const z of zonesPresent) {
          const ks = officesByZone[z];
          let giveSum = 0, needSum = 0; const light = [], heavy = [];
          for (const k of ks) {
            const cap7 = Math.max(base[k] * 7, 1e-9), rem = remS[k] + remT[k];
            if (rem / cap7 < iw.light_ratio) light.push(k); else if (rem > 0) heavy.push(k);
          }
          if (light.length && heavy.length) {
            for (const k of light) { const g = base[k] * iw.share; people[k] -= g; giveSum += g; }
            for (const k of heavy) needSum += remS[k] + remT[k];
            for (const k of heavy) internal[k] += giveSum * (remS[k] + remT[k]) / needSum;
          }
        }
      }
      if (convoys.length) {
        const arrived = {};
        for (const cv of convoys) if (cv.arrive <= t) arrived[cv.receiver] = (arrived[cv.receiver] || 0) + cv.people;
        for (const rc in arrived) {
          const ks = officesByZone[zi[rc]] || [];
          let need = 0; for (const k of ks) need += remS[k] + remT[k];
          if (need > 0) for (const k of ks) aid[k] += arrived[rc] * (remS[k] + remT[k]) / need;
        }
      }
      let so = 0, si = 0, sa = 0;
      for (let k = 0; k < nO; k++) {
        let cap = (people[k] + internal[k] + aid[k]) * dt;
        const us = Math.min(cap, remS[k]); remS[k] -= us; cap -= us;
        if (t >= o.access) { const ut = Math.min(cap, remT[k]); remT[k] -= ut; }
        so += people[k]; si += internal[k]; sa += aid[k];
      }
      rec.own[step] = so; rec.internal[step] = si; rec.aid[step] = sa;
      const j = recIdx.get(step);
      if (j !== undefined) {
        const fs = new Float32Array(nO), ft = new Float32Array(nO), rz = {};
        for (let k = 0; k < nO; k++) { fs[k] = remS[k] / totS[k]; ft[k] = remT[k] / totT[k]; rz[O.zone[k]] = (rz[O.zone[k]] || 0) + (remS[k] + remT[k]) * ppd; }
        rec.fs[j] = fs; rec.ft[j] = ft; rec.remPolesByZone[j] = rz;
      }
    }
    return { rec, convoys, r, senders, receivers, mob, workC };
  }

  function interp(tl, arr, off, nT, t) {
    // arr[off + k] は timeline_days[k] の値(0..255)。make_restoration_workforce.bulk_out と同じ線形補間
    let k = 0; while (k + 1 < nT && tl[k + 1] <= t) k++;
    if (k >= nT - 1) return arr[off + nT - 1] / 255;
    const f = (t - tl[k]) / (tl[k + 1] - tl[k]);
    return (arr[off + k] * (1 - f) + arr[off + k + 1] * f) / 255;
  }

  /** customers_out: 各記録時刻の停電中の需要家 [合計, 送電側, 配電だけ, 復旧対象外, 配電の停電(送電側を問わない)] */
  function outageSeries(D, P, o, bld, sim, withBus) {
    const keys = scenarioKeys(o);
    const dw = dynArrays(D, P, "west", keys.west), de = dynArrays(D, P, "east", keys.east);
    const days = sim.rec.days, n = P.n;
    const out = days.map(() => [0, 0, 0, 0, 0]);
    const perBus = withBus ? days.map(() => new Float32Array(n)) : null;
    for (let i = 0; i < n; i++) {
      const dA = P.island[i] ? de : dw, off = P.local[i] * dA.nT;
      const cust = P.cust[i], lost = bld.lost[i], rest = cust - lost, k = P.office[i];
      for (let j = 0; j < days.length; j++) {
        const pb = interp(dA.tl, dA.pb, off, dA.nT, days[j]);
        const fd = rest > 0 ? Math.min(1, Math.max(0, (bld.outS[i] * sim.rec.fs[j][k] + bld.outT[i] * sim.rec.ft[j][k]) / Math.max(rest, 1e-9))) : 0;
        const bulk = rest * pb, dist = rest * (1 - pb) * fd, o5 = out[j];
        o5[0] += bulk + dist + lost; o5[1] += bulk; o5[2] += dist; o5[3] += lost; o5[4] += rest * fd;
        if (perBus) perBus[j][i] = cust > 0 ? (bulk + dist + lost) / cust : 0;
      }
    }
    return { days, out, perBus };
  }

  function run(D, P, o, withBus) {
    const bld = build(D, P, o);
    const sim = simulate(D, P, o, bld);
    const ser = outageSeries(D, P, o, bld, sim, withBus);
    return { bld, sim, ser, keys: scenarioKeys(o) };
  }

  const api = { decode, normCdf, normPpf, gcKm, prepare, build, simulate, outageSeries, run, scenarioKeys, dynArrays, REC_DAYS };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.NankaiModel = api;
})(typeof window !== "undefined" ? window : globalThis);
