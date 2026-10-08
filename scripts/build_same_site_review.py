#!/usr/bin/env python3
"""Render the same-site experiment as an offline HTML evidence report."""
import hashlib
import difflib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.screen_false_fragments import build_island_graph

SOURCE_PATHS = ['.gitattributes', 'src/powerflow/site_identity.py', 'src/powerflow/site_terminals.py',
    'scripts/run_full_powerflow_from_db.py', 'scripts/trial_same_site_connections.py',
    'scripts/solve_same_site_trial.py', 'scripts/trial_site_terminal_projection.py',
    'scripts/audit_site_path_overlaps.py', 'scripts/fetch_same_site_basemaps.py',
    'scripts/build_same_site_review.py', 'scripts/check_same_site_review.py',
    'scripts/templates/same_site_review.html', 'scripts/templates/before_after_review.html',
    'tests/test_site_identity.py', 'tests/test_site_terminals.py',
    'docs/slides/ajg/build_site_trial_review.mjs', 'docs/slides/ajg/site_trial/TALK_NOTES.md',
    'docs/slides/ajg/site_trial/.gitignore',
    'docs/reports/codex_same_site_trial_2026-09-13/README.md',
    'docs/reports/codex_same_site_trial_2026-09-13/REVIEW.md']


def source_review():
    base = 'e6b1c6c33e1a687555852be5e7ec467ca3cb83ec'
    rows = []
    for path in SOURCE_PATHS:
        result = subprocess.run(['git','show',base+':'+path],cwd=ROOT,capture_output=True)
        before = result.stdout.decode() if result.returncode == 0 else ''
        after = (ROOT/path).read_text()
        rows.append(dict(path=path, before=before, after=after,
            before_sha256=hashlib.sha256(before.encode()).hexdigest() if before else None,
            after_sha256=hashlib.sha256(after.encode()).hexdigest(),
            diff=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),
                                             fromfile='before/'+path,tofile='after/'+path))))
    return dict(base_commit=base, files=rows,
                scope='All 20 implementation/template/review-text files in this change. Generated evidence files are listed separately.')


def main():
    out = ROOT/'docs/reports/codex_same_site_trial_2026-09-13'
    report = json.loads((out/'trial.json').read_text())
    powerflow = json.loads((out/'powerflow.json').read_text())
    assert powerflow['complete'], 'Finish the controlled power-flow experiment first'
    assert powerflow['source_sha256'] == report['source_sha256']
    built = ROOT/'docs/data/built/all.json'
    assert hashlib.sha256(built.read_bytes()).hexdigest() == report['source_sha256']
    data = json.loads(built.read_text())
    graphs = {isl: build_island_graph(data['nodes'], data['edges'], isl) for isl in ['hokkaido','east','west','okinawa']}
    for case in report['candidates']:
        case['fragment_component_keys'] = sorted(graphs[case['island']][1][case['component']])
    report['powerflow'] = powerflow
    report['source_review'] = source_review()
    (out/'source_review.json').write_text(json.dumps(report['source_review'],ensure_ascii=False,indent=2)+'\n')
    report['artifact_files'] = [dict(path=str(p.relative_to(out)), bytes=p.stat().st_size)
        for p in sorted(out.rglob('*')) if p.is_file() and p.name not in
        ['index.html','source_review.json','qa.json']]
    for name in ['basemap_manifest', 'visual_review', 'site_terminals', 'site_terminal_verification', 'path_overlaps']:
        path = out/f'{name}.json'
        if path.exists():
            report[name] = json.loads(path.read_text())
    from src.powerflow.site_identity import apply_site_aliases
    from scripts.run_full_powerflow_from_db import _haversine_km
    after, _ = apply_site_aliases(data, report['plan'])
    length_trials = []
    for index in report['changes']['preserved_length_estimate_edges']:
        old, new = data['edges'][index], after['edges'][index]
        length_trials.append(dict(edge_index=index, name=old.get('name'), old_endpoints=[old['a'],old['b']],
            rewired_endpoints=[new['a'],new['b']], original_estimate_km=max(_haversine_km(*old['a'],*old['b']), .05),
            naive_rebuild_estimate_km=max(_haversine_km(*new['a'],*new['b']), .05),
            preserved_reference=new['identity_length_reference']))
    report['length_trials'] = length_trials
    (out/'length_preservation.json').write_text(json.dumps(length_trials,ensure_ascii=False,indent=2)+'\n')
    content = json.dumps(report, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    template = (ROOT/'scripts/templates/same_site_review.html').read_text()
    (out/'index.html').write_text(template.replace('/*__DATA__*/', content))
    print(out/'index.html')


if __name__ == '__main__':
    main()
