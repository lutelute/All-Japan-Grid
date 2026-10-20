#!/usr/bin/env python3
"""Replay small, controlled review experiments from pinned Git source.

Uses synthetic inputs, never runs nationwide power flow or edits canonical data.
The old/new route pair shares all geometry and dependencies. The transformer
fixture isolates coordinate-ladder generation, not production default assembly.
"""
from __future__ import annotations
import copy
import datetime as dt
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = '13b89c926f522fd623699c80a8f0b1bb85c3d4be'
HEAD = 'e0d8a2888153c07eff0b89d8662c52c5adb8f557'


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def sha(data):
    return hashlib.sha256(data).hexdigest()


def module(name, path, source=None):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    exec(compile(source if source is not None else path.read_bytes(), str(path), 'exec'), m.__dict__)
    return m


def main():
    canonical = ROOT/'docs/data/built/all.json'
    before_sha = sha(canonical.read_bytes()) if canonical.exists() else None
    source_path = 'scripts/hunt_fragment_third_wave.py'
    old_source = git('show', f'{BASE}:{source_path}')
    new_source = git('show', f'{HEAD}:{source_path}')
    # The shared geometric helper did not change between the compared commits.
    helper = 'scripts/hunt_fragment_osm_bridges.py'
    assert git('show', f'{BASE}:{helper}') == git('show', f'{HEAD}:{helper}')
    with tempfile.TemporaryDirectory(prefix='ajg-review-replay-') as td:
        snapshot = Path(td)
        archive = git('archive', HEAD, 'scripts', 'src', 'config', 'tests/test_fragment_third_wave.py')
        with tarfile.open(fileobj=io.BytesIO(archive)) as t:
            t.extractall(snapshot, filter='data')
        sys.path.insert(0, str(snapshot))
        fixture = module('review_fixture', snapshot/'tests/test_fragment_third_wave.py')
        old = module('review_route_before', snapshot/source_path, old_source)
        new = module('review_route_after', snapshot/source_path, new_source)
        routes = []
        for conflict in [True, False]:
            built, lines = fixture._built(seam_km=0.03, frag_kv=0, way_kv=66)
            if conflict:
                for node in built['nodes'][:3]:
                    node['kv'] = 154
                lines[1]['properties']['_voltage_kv'] = 154
            outcomes = {}
            for label, m in [('before', old), ('after', new)]:
                stage, report = fixture._chains_at(m, copy.deepcopy(built), copy.deepcopy(lines), 60)
                outcomes[label] = {'accepted': stage['chains'], 'stage': stage, 'chains': report['chains']}
            assert outcomes['before']['accepted'] == 1
            assert outcomes['after']['accepted'] == (0 if conflict else 1)
            routes.append({'case': 'mixed_voltage' if conflict else 'same_voltage_control',
                           'voltage_path_kv': [0, 66, 154, 154] if conflict else [0, 66, 66, 66],
                           'input': {'built': built, 'lines': lines}, 'result': outcomes})
        from scripts.connection_voltage import route_voltage_compatible
        drift = [66, 77, 95]
        adjacent = all(route_voltage_compatible(drift[i:i+2]) for i in range(2))
        entire = route_voltage_compatible(drift)
        assert adjacent and not entire
        builder = module('review_circuit_builder', snapshot/'scripts/run_full_powerflow_from_db.py')
        nodes = [{'id': f'junction_{kv}', 'name': f'junction_{kv}', 'lat': 37.33051,
                  'lon': 140.34098, 'kv': kv, 'region': 'tokyo', 'sub': 0} for kv in [154, 66]]
        options = dict(nameplates=None, territory=False, dedup_nodes=True, site_trafos=False,
                       deenergize_unbuilt=False, synthetic_ties_live=False, btb_split=False,
                       freq_fix=False, implicit_stepdown=False, cap_calib=False)
        net, bus_map, stats = builder.build_island_net('east', copy.deepcopy(nodes), [], 50, {}, **options)
        assert len(net.bus) == 2 and len(net.line) == 0 and len(net.trafo) == 1
        transformer = {'input': {'nodes': nodes, 'edges': [], 'frequency_hz': 50},
                       'options': options, 'bus_count': len(net.bus), 'line_count': len(net.line),
                       'transformers': json.loads(net.trafo.to_json(orient='records')), 'stats': stats,
                       'scope': 'Coordinate-ladder mechanism in isolation; no load-flow solution.'}
        import pandapower
        dependencies = {str(p.relative_to(snapshot)): sha(p.read_bytes())
                        for folder in ['scripts', 'src', 'config']
                        for p in (snapshot/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
        after_sha = sha(canonical.read_bytes()) if canonical.exists() else None
        assert before_sha == after_sha
        result = dict(recorded_at=dt.datetime.now(dt.timezone.utc).isoformat(), base=BASE, head=HEAD,
                      scope='Synthetic-input replay. Historical nationwide AC reports were not rerun.',
                      python=sys.version, pandapower=pandapower.__version__,
                      route_source_sha256={'before': sha(old_source), 'after': sha(new_source)},
                      snapshot_file_sha256=dependencies, routes=routes,
                      gradual_drift={'kv': drift, 'adjacent_pairs_pass': adjacent, 'whole_route_pass': entire},
                      transformer=transformer, canonical_sha256_before=before_sha, canonical_sha256_after=after_sha)
    target = ROOT/'docs/reports/codex_before_after_2026-09-12/methods_replay.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'routes': [{k: v for k, v in r.items() if k != 'input'} for r in routes],
                      'transformer_count': len(transformer['transformers']),
                      'canonical_unchanged': before_sha == after_sha, 'output': str(target)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
