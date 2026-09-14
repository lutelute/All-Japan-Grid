// node hazard/nankai/tool/test_model.mjs : JS に移した人員モデルを Python(reference.json)と照合する
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const M = require("./model.js");
const here = new URL(".", import.meta.url).pathname;
const D = JSON.parse(readFileSync(here + "data.json", "utf8"));
const REF = JSON.parse(readFileSync(here + "reference.json", "utf8"));
const P = M.prepare(D);
let bad = 0;
const rel = (a, b) => Math.abs(a - b) / Math.max(Math.abs(b), 1);
for (const [name, ref] of Object.entries(REF)) {
  const ov = ref.override;
  const o = { ...D.params.defaults, ...{ sigma: ov.sigma ?? 0.4, basis: ov.basis ?? "wooden_stock", old_split: ov.old_split ?? 0.5, collapse: ov.collapse ?? true,
    spm: ov.spm ?? 390, access: ov.access ?? 10, aid: ov.aid ?? 0.15, internal: ov.internal ?? true } };
  const t0 = Date.now();
  const R = M.run(D, P, o, false);
  const ms = Date.now() - t0;
  const bs = R.bld.brkS.reduce((a, b) => a + b, 0), bt = R.bld.brkT.reduce((a, b) => a + b, 0);
  const staff = R.bld.O.staff.reduce((a, b) => a + b, 0);
  const aidTot = R.sim.convoys.reduce((a, c) => a + c.people, 0);
  const i7 = 7 * 24;
  const dayIdx = d => R.ser.days.findIndex(x => Math.abs(x - d) < 1e-9);
  const checks = [
    ["broken_s", bs, ref.broken_s], ["broken_t", bt, ref.broken_t], ["staff", staff, ref.staff], ["aid_total", aidTot, ref.aid_total],
    ["own7", R.sim.rec.own[i7], ref.own7], ["internal7", R.sim.rec.internal[i7], ref.internal7], ["aid7", R.sim.rec.aid[i7], ref.aid7],
    ...[1, 7, 14].map(d => [`dist_any_${d}d`, R.ser.out[dayIdx(d)][4], ref.dist_any[`${d}d`]]),
  ];
  const roles = JSON.stringify([R.sim.senders.slice().sort(), R.sim.receivers.slice().sort()]) === JSON.stringify([ref.senders.slice().sort(), ref.receivers.slice().sort()]);
  console.log(`\n${name}  (${ms} ms)  送り手/受け手 一致: ${roles}`);
  if (!roles) bad++;
  for (const [k, js, py] of checks) {
    const e = rel(js, py), ok = e < 2e-3 || Math.abs(js - py) < 50;
    if (!ok) bad++;
    console.log(`  ${ok ? "ok " : "NG "} ${k.padEnd(14)} js ${js.toFixed(1).padStart(12)}  py ${Number(py).toFixed(1).padStart(12)}  rel ${e.toExponential(2)}`);
  }
}
console.log(bad ? `\n${bad} 件が不一致` : "\nすべて一致");
process.exit(bad ? 1 : 0);
