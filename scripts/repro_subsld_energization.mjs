// Characterize the current GUI classifier using its actual source, without a DOM.
// This reports behavior for review; it does not assert that a bus is energized.
// Usage: node scripts/repro_subsld_energization.mjs [output.json]
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = fs.readFileSync(path.join(root, 'docs/subsld.html'), 'utf8');
const start = source.indexOf('function swKey(');
const end = source.indexOf('// この変電所がループ', start);
if (start < 0 || end < start) throw new Error('GUI function boundaries changed; review the extraction.');
const functions = source.slice(start, end);
const context = vm.createContext({SWSTATE: {}});
vm.runInContext(functions, context, {timeout: 1000});
const result = vm.runInContext(`(() => {
  const state = energized({i: 'fixture'}, {b: 1, sw: [[1, 0, [0]]]}, 0);
  return {marked_live: [...state.live], hasFeeder: state.hasFeeder};
})()`, context, {timeout: 1000});
const report = {
  fixture: 'one busbar, one closed feeder, no source supplied to classifier',
  ...result,
  source: 'docs/subsld.html energized()',
  source_sha256: createHash('sha256').update(source).digest('hex'),
  extracted_functions_sha256: createHash('sha256').update(functions).digest('hex'),
  interpretation: 'Local closed-feeder classification; upstream source reachability is not supplied to this function.',
};
const json = JSON.stringify(report, null, 2) + '\n';
if (process.argv[2]) fs.writeFileSync(path.resolve(process.argv[2]), json);
process.stdout.write(json);
