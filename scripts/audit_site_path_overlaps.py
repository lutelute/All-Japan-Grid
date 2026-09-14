#!/usr/bin/env python3
"""Find shared saved path segments around reviewed terminals; never delete lines.

Equal geometry can be valid parallel circuits. Results require raw way/circuit
provenance, so geometry overlap alone is not an electrical deduplication rule.
"""
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT = ROOT/'docs/reports/codex_same_site_trial_2026-09-13'


def segments(edge):
    points = [tuple(round(v,5) for v in p) for p in edge.get('path',[])]
    return {tuple(sorted([a,b])) for a,b in zip(points,points[1:]) if a != b}


def main():
    from scripts.screen_false_fragments import hav_km
    built = ROOT/'docs/data/built/all.json'
    data = json.loads(built.read_text())
    sites = json.loads((OUT/'site_terminals.json').read_text())
    edges = data['edges']
    per_edge = [segments(e) for e in edges]
    reverse = defaultdict(set)
    for i,(edge,segs) in enumerate(zip(edges,per_edge)):
        for s in segs:
            reverse[(edge.get('kv',0),s)].add(i)
    targets = {t['edge_index'] for t in sites['terminals']}
    checked,rows = set(),[]
    for i in sorted(targets):
        others = set().union(*(reverse[(edges[i].get('kv',0),s)] for s in per_edge[i]))
        for j in sorted(others-{i}):
            pair = tuple(sorted([i,j]))
            if pair in checked:
                continue
            checked.add(pair)
            shared = per_edge[i]&per_edge[j]
            fraction = len(shared)/min(len(per_edge[i]),len(per_edge[j]))
            if len(shared) < 3 or fraction < .5:
                continue
            rows.append(dict(edge_indices=list(pair), shared_segments=[list(map(list,s)) for s in sorted(shared)],
                shared_segment_count=len(shared), shorter_path_segment_fraction=fraction,
                shared_length_km=round(sum(hav_km(a,b) for a,b in shared),6),
                branches=[dict(edge_index=k,name=edges[k].get('name'),kv=edges[k].get('kv'),
                    par=edges[k].get('par'),segment_count=len(per_edge[k]),
                    disclosure=edges[k].get('disclosure'),recovery=edges[k].get('recovery')) for k in pair],
                decision='review_raw_way_and_circuit_lineage; do_not_delete_from_geometry_alone'))
    for i,row in enumerate(rows,1):
        row['overlap_id'] = f'OV{i:02d}'
    by_case = {}
    for cid,c in sites['cases'].items():
        ids = {t['edge_index'] for t in sites['terminals'] if t['terminal_id'] in c['terminal_ids']}
        by_case[cid] = [r['overlap_id'] for r in rows if ids & set(r['edge_indices'])]
    result = dict(source_sha256=hashlib.sha256(built.read_bytes()).hexdigest(),
        method='Equal undirected segments at 5 decimal coordinate precision, equal model kV, '
               'at least 3 shared segments and at least 50% of the shorter unique-segment path.',
        scope='Pairs involving branches assigned to the reviewed site terminals. Shared geometry is not proof of duplicate circuits.',
        rows=rows, cases=by_case)
    (OUT/'path_overlaps.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(overlap_pairs=len(rows),chichibu=[r for r in rows if 5923 in r['edge_indices']]),ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
