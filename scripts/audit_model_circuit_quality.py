#!/usr/bin/env python3
"""Rebuild and inspect calculation circuits without changing canonical data.

Outputs SHA-pinned JSON findings and graph-only sensitivity. Net pickles are
optional scratch artifacts; they are not used as evidence unless freshly built
or explicitly requested with --reuse-scratch.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.validation.circuit_quality import (
    circuit_findings, source_nodes_by_bus, candidate_removal_connectivity,
    structure_voltage_findings, unknown_line_components)

REGIONS = ['hokkaido', 'tohoku', 'tokyo', 'chubu', 'hokuriku', 'kansai',
           'chugoku', 'shikoku', 'kyushu', 'okinawa']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assembly_signature():
    """Invalidate scratch models when implementation, inputs or flags change."""
    import pandapower as pp
    files={ROOT/'scripts/run_full_powerflow_from_db.py'}
    for folder in ('src/powerflow','src/converter','src/model','src/utils',
                   'config','data/reference','data/structures'):
        files.update(p for p in (ROOT/folder).rglob('*') if p.is_file()
                     and p.suffix in ('.py','.json','.jsonl','.yaml','.yml','.geojson'))
    extra=ROOT/'data/transformer_sources.jsonl'
    if extra.exists(): files.add(extra)
    sources={str(p.relative_to(ROOT)):digest(p) for p in sorted(files)}
    manifest=dict(sources=sources,pandapower_version=pp.__version__,
                  environment={k:os.environ.get(k) for k in
                               ('AGJ_CALIBRATED_LINES','AJG_STEPDOWN_CAPACITY')})
    signature=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    return signature,manifest


def structures_audit():
    from scripts.build_substation_structure import prepare_ways, _vclasses
    totals = Counter()
    findings, files, examples = [], {}, []
    for region in REGIONS:
        sp = ROOT/f'data/structures/{region}.json'
        lp = ROOT/f'data/{region}_lines.geojson'
        files[str(sp.relative_to(ROOT))] = digest(sp)
        files[str(lp.relative_to(ROOT))] = digest(lp)
        ways = prepare_ways(json.loads(lp.read_text()))
        classes = defaultdict(set)
        for way in ways:
            classes[way['key']].update(float(v) for v in _vclasses(way['props'].get('voltage')))
        data = json.loads(sp.read_text())
        for st in data['structures']:
            totals['sites'] += 1
            for field in ('voltage_levels', 'busbars', 'bays', 'terminals', 'transformers', 'switches'):
                totals[field] += len(st.get(field, []))
            sections = Counter(b['vl_id'] for b in st['busbars'])
            totals['sites_multisection'] += any(n > 1 for n in sections.values())
            for sw in st.get('switches', []):
                totals['switch_'+sw['kind']] += 1
                totals['switch_source_'+sw['source']] += 1
            result = structure_voltage_findings(st, classes)
            for field in ('terminal_voltage_conflicts', 'bay_voltage_conflicts'):
                totals[field] += len(result[field])
            totals['unknown_terminal_voltage'] += result['unknown_terminal_voltage']
            totals['missing_source_way'] += result['missing_source_way']
            if result['terminal_voltage_conflicts'] or result['bay_voltage_conflicts']:
                findings.append(result)
            if st['site']['name'] in ('新多摩変電所', '新京葉変電所', '嶺南変電所'):
                examples.append(dict(site=st['site'], busbars_by_vl=dict(sections),
                    switches_by_kind=dict(Counter(s['kind'] for s in st.get('switches', [])))))
    return dict(counts=dict(totals), findings=findings, examples=examples, source_sha256=files)


def membership_audit(nodes, edges):
    from src.powerflow.connectivity import compute_connectivity, REGION_ISLAND
    key = lambda n: (round(n['lat'],5),round(n['lon'],5))
    full = compute_connectivity(nodes, edges)
    own = {}
    for isl in ('hokkaido','east','west','okinawa'):
        ns = [n for n in nodes if REGION_ISLAND.get(n.get('region')) == isl]
        own[isl] = compute_connectivity(ns, edges)['main_keys']
    false_main, stale = [], []
    for n in nodes:
        is_main = key(n) in own.get(REGION_ISLAND.get(n.get('region')), set())
        if key(n) in full['main_keys'] and not is_main:
            false_main.append({k:n.get(k) for k in ('id','name','region','kv','lat','lon')})
        if bool(n.get('main')) != is_main:
            stale.append(n['id'])
    return dict(union_false_main=false_main, stored_main_disagreements=stale,
                definition='Same production stitch/tie rules in both comparisons; membership scoped to own island.')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--islands',nargs='+',default=['hokkaido','east','west','okinawa'])
    ap.add_argument('--out-dir',type=Path,default=ROOT/'docs/reports/codex_model_quality_2026-09-12')
    ap.add_argument('--scratch',type=Path,default=Path('/tmp/ajg_model_quality'))
    ap.add_argument('--reuse-scratch',action='store_true')
    args=ap.parse_args()
    args.out_dir.mkdir(parents=True,exist_ok=True)
    args.scratch.mkdir(parents=True,exist_ok=True)
    built=ROOT/'docs/data/built/all.json'
    sha=digest(built)
    data=json.loads(built.read_text())
    signature,manifest=assembly_signature()
    structure=structures_audit()
    (args.out_dir/'structure_findings.json').write_text(json.dumps(structure,ensure_ascii=False,indent=2)+'\n')
    print('Structure:',json.dumps(structure['counts']),flush=True)
    import pandapower as pp
    from scripts.run_full_powerflow_from_db import build_island_net, ISLAND_FREQ
    results={}
    for island in args.islands:
        start=time.time()
        np=args.scratch/f'{island}.p'
        mp=args.scratch/f'{island}_map.json'
        if args.reuse_scratch and np.exists() and mp.exists():
            saved=json.loads(mp.read_text())
            if saved.get('source_sha256') != sha or saved.get('assembly_signature') != signature:
                raise ValueError('Scratch provenance missing or different; rebuild without --reuse-scratch')
            net=pp.from_pickle(np)
            bus_of,stats=saved['bus_of'],saved['stats']
        else:
            net,bus_of,stats=build_island_net(island,copy.deepcopy(data['nodes']),data['edges'],ISLAND_FREQ[island],{},
                territory=True,dedup_nodes=True,site_trafos=False,deenergize_unbuilt=False,
                synthetic_ties_live=False,btb_split=True,freq_fix=True,implicit_stepdown=True,cap_calib=False)
            pp.to_pickle(net,str(np))
            mp.write_text(json.dumps(dict(bus_of={int(i):int(b) for i,b in bus_of.items()},stats=stats,
                                         source_sha256=sha,assembly_signature=signature),default=lambda v:v.item()))
        origins=source_nodes_by_bus(bus_of,data['nodes'],stats['implicit_stepdown_ledger'])
        result=circuit_findings(net,origins)
        result['unknown_line_components']=unknown_line_components(net,origins)
        result['topology_sensitivity']=candidate_removal_connectivity(net,result['transformers_without_site_witness'])
        result['builder_stats']=stats
        result['elapsed_seconds']=round(time.time()-start,2)
        results[island]=result
        (args.out_dir/f'circuit_{island}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=lambda v:v.item())+'\n')
        print(island,json.dumps(result['counts']),result['topology_sensitivity'],flush=True)
    report=dict(source_sha256=sha,assembly_signature=signature,assembly_manifest=manifest,
        islands=results,structure_counts=structure['counts'],
        membership=membership_audit(data['nodes'],data['edges']),
        scope='Default circuit assembly; no loads/generators added, no national power-flow solve; graph sensitivity only.',
        settings=dict(territory=True,dedup_nodes=True,site_trafos=False,deenergize_unbuilt=False,
                      synthetic_ties_live=False,btb_split=True,freq_fix=True,implicit_stepdown=True,cap_calib=False))
    (args.out_dir/'model_quality.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=lambda v:v.item())+'\n')
    assert digest(built)==sha
    print('Complete; canonical SHA unchanged',sha,flush=True)


if __name__=='__main__':
    main()
