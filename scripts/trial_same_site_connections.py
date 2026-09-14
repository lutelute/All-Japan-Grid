#!/usr/bin/env python3
"""Trace fragmented same-name sites to source OSM identity and try explicit aliases.

Canonical data is read only. All proposals, rejections, copied-model differences
and source hashes are saved. Positive model voltage is not treated as observed
equipment voltage; contradictory or unknown voltage cases remain separate.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.screen_false_fragments import ISLAND_OF, build_island_graph, hav_km, k5
from src.powerflow.site_identity import apply_site_aliases, model_digest

OUT = ROOT/'docs/reports/codex_same_site_trial_2026-09-13'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def normalize_name(value):
    value = ''.join(unicodedata.normalize('NFKC', str(value or '')).split())
    for _ in range(3):
        value = re.sub(r'(_\d+|\d+(?:\.\d+)?kV)$', '', value, flags=re.I)
    return value


def voltage_classes(value):
    # OSM voltage is in volts, including tokens such as dc1500.
    return sorted({float(v)/1000 for v in re.findall(r'\d+(?:\.\d+)?', str(value or ''))
                   if float(v) > 0})


class SourceCatalog:
    """Reproduce the builder's base + supplement ordinal ID assignment.

    Ordinals are valid only for this hash-pinned snapshot. Name and distance
    guards reject obvious stale mappings; the raw OSM identity is retained for
    downstream work, so future regeneration need not rely on this ordinal.
    """
    def __init__(self):
        self.regions = {}
        self.files = {}

    def resolve(self, node):
        match = re.fullmatch(r'([a-z]+)_sub_(\d+)(?:@.*)?', node['id'])
        if not match:
            return {'error': 'node_id_has_no_source_ordinal'}
        region, index = match[1], int(match[2])
        if region not in self.regions:
            records = []
            for suffix in ('', '_supplement'):
                path = ROOT/f'data/{region}_substations{suffix}.geojson'
                if not path.exists():
                    continue
                self.files[str(path.relative_to(ROOT))] = sha(path)
                records.extend((str(path.relative_to(ROOT)), i, f)
                               for i, f in enumerate(json.loads(path.read_text())['features']))
            self.regions[region] = records
        if index >= len(self.regions[region]):
            return {'error': 'source_ordinal_out_of_range'}
        path, local_index, feature = self.regions[region][index]
        props = feature.get('properties', {})
        osm_type = props.get('osm_type') or ('way' if props.get('osm_way_id') else
                                            'node' if props.get('osm_node_id') else None)
        osm_id = props.get('osm_id') or props.get('osm_way_id') or props.get('osm_node_id')
        from src.powerflow.snapped_topology import _get_centroid
        lat, lon = _get_centroid(feature)
        distance = hav_km((node['lat'], node['lon']), (lat, lon))*1000 if lat is not None else None
        valid = (bool(props.get('name')) and normalize_name(props['name']) == normalize_name(node.get('name'))
                 and distance is not None and distance <= 1500 and bool(osm_type and osm_id))
        return dict(path=path, feature_index=local_index, builder_ordinal=index,
                    osm_identity=f'{osm_type}/{osm_id}' if osm_type and osm_id else None,
                    name_matches=bool(props.get('name')) and normalize_name(props['name']) == normalize_name(node.get('name')),
                    validated=valid, centroid=[lat, lon], node_to_centroid_m=round(distance, 2) if distance is not None else None,
                    voltage_kv=voltage_classes(props.get('voltage')), properties=props,
                    geometry=feature['geometry'],
                    geometry_sha256=hashlib.sha256(json.dumps(feature['geometry'], sort_keys=True).encode()).hexdigest())


def topology(data):
    report = {}
    for isl in ('hokkaido', 'east', 'west', 'okinawa'):
        keys, comps = build_island_graph(data['nodes'], data['edges'], isl)
        report[isl] = dict(components=len(comps), fragments=max(0, len(comps)-1),
                           largest=len(comps[0]), keys=len(keys),
                           fragment_keys=sum(map(len, comps[1:])))
    return report


def screen(data, catalog, max_m=500):
    groups = defaultdict(list)
    at = defaultdict(list)
    for n in data['nodes']:
        at[k5(n['lat'], n['lon'])].append(n)
        if n.get('sub'):
            groups[normalize_name(n.get('name'))].append(n)
    rows = []
    for isl in ('hokkaido', 'east', 'west', 'okinawa'):
        keys, comps = build_island_graph(data['nodes'], data['edges'], isl)
        ci = {k: i for i, comp in enumerate(comps) for k in comp}
        for name, ns in groups.items():
            for a in ns:
                ka = k5(a['lat'], a['lon'])
                if ISLAND_OF.get(a['region']) != isl or ci[ka] == 0:
                    continue
                for b in ns:
                    kb = k5(b['lat'], b['lon'])
                    if ISLAND_OF.get(b['region']) != isl or ci[kb] != 0:
                        continue
                    distance = hav_km(ka, kb)*1000
                    if distance > max_m:
                        continue
                    sa, sb = catalog.resolve(a), catalog.resolve(b)
                    reasons = []
                    if not sa.get('validated') or not sb.get('validated'):
                        reasons.append('source_identity_unresolved')
                    if not sa.get('osm_identity') or sa.get('osm_identity') != sb.get('osm_identity'):
                        reasons.append('different_osm_objects')
                    if not a.get('kv') or not b.get('kv'):
                        reasons.append('model_voltage_unknown')
                    elif abs(a['kv']-b['kv']) > 1e-6:
                        reasons.append('model_voltage_conflict')
                    for node, source in [(a, sa), (b, sb)]:
                        observed = source.get('voltage_kv', [])
                        if observed and node.get('kv') and not any(abs(v-node['kv']) < .5 for v in observed):
                            reasons.append('source_voltage_conflict')
                    if len(at[ka]) != 1:
                        reasons.append('ambiguous_source_coordinate')
                    if any(ISLAND_OF.get(n['region']) != isl for n in at[kb]):
                        reasons.append('cross_island_target_coordinate')
                    if len({n.get('kv') for n in at[kb]}) > 1:
                        if any(not e.get('kv') and ka in (tuple(e['a']), tuple(e['b'])) for e in data['edges']):
                            reasons.append('unknown_edge_at_multivoltage_target')
                    observed = bool(sa.get('voltage_kv') and sb.get('voltage_kv'))
                    rows.append(dict(name=name, island=isl, fragment=copy.deepcopy(a), main=copy.deepcopy(b),
                        distance_m=round(distance, 1), component=ci[ka], fragment_keys=len(comps[ci[ka]]),
                        source_fragment=sa, source_main=sb, reasons=sorted(set(reasons)),
                        decision='hold' if reasons else 'trial_alias',
                        voltage_basis='source_tag' if observed else 'same_model_class_only',
                        scope='Duplicate site/voltage records, not evidence for an internal bus coupler.'))
    rows.sort(key=lambda r: (r['decision'] != 'trial_alias', -r['fragment_keys'], r['distance_m'], r['fragment']['id'], r['main']['id']))
    for i, r in enumerate(rows, 1):
        r['case_id'] = f'SS{i:02d}'
    return rows


def alias_plan(data, rows):
    return dict(input_model_digest=model_digest(data),
                aliases=[dict(case_id=r['case_id'], from_id=r['fragment']['id'], to_id=r['main']['id'],
                              osm_identity=r['source_fragment']['osm_identity'], decision='trial_alias',
                              kv=r['fragment']['kv'], voltage_basis=r['voltage_basis'],
                              source_geometry_equal=r['source_fragment']['geometry_sha256'] == r['source_main']['geometry_sha256'])
                         for r in rows if r['decision'] == 'trial_alias'])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=OUT)
    ap.add_argument('--scratch', type=Path, default=Path('/tmp/ajg_same_site_trial'))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    args.scratch.mkdir(parents=True, exist_ok=True)
    built = ROOT/'docs/data/built/all.json'
    before_sha = sha(built)
    data = json.loads(built.read_text())
    catalog = SourceCatalog()
    candidates = screen(data, catalog)
    plan = alias_plan(data, candidates)
    counts = Counter(a['from_id'] for a in plan['aliases'])
    assert max(counts.values(), default=0) <= 1, 'Multiple identity targets require individual review'
    after, changes = apply_site_aliases(data, plan)
    variants = {'before': topology(data), 'all_eligible_aliases': topology(after)}
    for label, selected in [('source_voltage_confirmed', [r for r in candidates if r['voltage_basis'] == 'source_tag']),
                            ('chichibu_only', [r for r in candidates if r['fragment']['id'] == 'chubu_sub_1147']),
                            ('chichibu_yokoze', [r for r in candidates if r['fragment']['id'] in ('chubu_sub_1147', 'chubu_sub_1146')])]:
        trial, _ = apply_site_aliases(data, alias_plan(data, selected))
        variants[label] = topology(trial)
    # Local network geometry and source polygons for visual review; no map tiles needed.
    for r in candidates:
        a, b = r['fragment'], r['main']
        center = [(a['lat']+b['lat'])/2, (a['lon']+b['lon'])/2]
        edge_indices = []
        for i, e in enumerate(data['edges']):
            path = e.get('path') or [e['a'], e['b']]
            if any(abs(p[0]-center[0]) < .012 and abs(p[1]-center[1]) < .015 for p in path):
                edge_indices.append(i)
        r['local_edges'] = [dict(index=i, before=data['edges'][i], after=after['edges'][i]) for i in edge_indices]
        r['local_nodes'] = [n for n in data['nodes'] if abs(n['lat']-center[0]) < .012 and abs(n['lon']-center[1]) < .015]
    files = dict(catalog.files)
    for path in ['src/powerflow/site_identity.py', 'src/powerflow/snapped_topology.py',
                 'scripts/trial_same_site_connections.py', 'scripts/screen_false_fragments.py']:
        files[path] = sha(ROOT/path)
    report = dict(recorded_at=datetime.now(timezone.utc).isoformat(), source_sha256=before_sha,
                  input_model_digest=model_digest(data), source_files=files,
                  screen=dict(radius_m=500, candidates=len(candidates),
                              eligible=len(plan['aliases']), held=sum(r['decision']=='hold' for r in candidates),
                              observed_voltage_eligible=sum(r['decision']=='trial_alias' and r['voltage_basis']=='source_tag' for r in candidates)),
                  scope='Same-name fragment-to-main pairs within 500m, recomputed per synchronous island. Explicit trial copies only.',
                  candidates=candidates, plan=plan, changes=changes, topology_variants=variants)
    (args.out/'trial.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    (args.out/'alias_plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2)+'\n')
    (args.scratch/'before.json').write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    (args.scratch/'after.json').write_text(json.dumps(after, ensure_ascii=False, separators=(',', ':')))
    assert sha(built) == before_sha
    print(json.dumps({'screen': report['screen'], 'changes': {k: len(v) if isinstance(v, list) else v for k, v in changes.items()},
                      'topology': variants}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
