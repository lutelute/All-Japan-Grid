// model.js(ブラウザの計算)を Python(build_queue_tool.py が書いた reference.json)と照合する。
//   node hazard/nankai/tool_queue/test_model.mjs
// 1) 優先順位 5 通りで、修理の完了時刻が一致するか
// 2) 電源とのつながりだけで数えた停電需要家が一致するか
// 3) 補正(既定の優先順位で測った 潮流あり − つながりだけ)を足した値が、潮流ありとどれだけずれるか(当てはまりの確認)
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const here = new URL(".", import.meta.url).pathname;
globalThis.atob = s => Buffer.from(s, "base64").toString("binary");
const QM = require(here + "model.js");
const D = JSON.parse(readFileSync(here + "data.json", "utf8"));
const R = JSON.parse(readFileSync(here + "reference.json", "utf8"));
const M = QM.prepare(D);
let bad = 0;
for (const [pol, ref] of Object.entries(R.policies)) {
  const t0 = Date.now();
  const inp = { ...QM.defaultInputs(M), policy: pol };
  const S = QM.simulate(M, inp);
  let dmax = 0, miss = 0;
  for (const [k, e] of Object.entries(ref.end)) {
    const v = S.Q.end[k];
    if (v === undefined) { miss++; continue; }
    dmax = Math.max(dmax, Math.abs(v - e));
  }
  let cmax = 0, rmax = 0;
  ref.conn.forEach((c, i) => {
    cmax = Math.max(cmax, Math.abs(S.conn[i] - c));
    rmax = Math.max(rmax, Math.abs(S.corr[i] - ref.full[i]));
  });
  const ok = miss === 0 && dmax < 1e-6 && cmax < 1;
  if (!ok) bad++;
  console.log(`${ok ? "ok " : "NG "} ${pol.padEnd(13)} 完了時刻の差 最大 ${dmax.toExponential(1)} 日(見つからない ${miss})・` +
    `つながりの差 最大 ${cmax.toFixed(1)} 軒・補正つき − 潮流あり 最大 ${(rmax / 1e4).toFixed(1)} 万軒(Python ${(ref.resid_max / 1e4).toFixed(1)})` +
    `  ${Date.now() - t0} ms`);
}
console.log(bad ? `\n一致しないもの ${bad} 件` : "\nすべて一致");
process.exit(bad ? 1 : 0);
