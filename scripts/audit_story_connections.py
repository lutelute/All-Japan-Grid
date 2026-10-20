#!/usr/bin/env python3
"""Read-only, reproducible audit of the built graph and its connection evidence.

Never proposes automatic connections on proximity alone. Coordinate components
are geographical diagnostics, not bus-breaker electrical connectivity. All edge
indices refer to the SHA256-pinned input. Outputs JSON, GeoJSON and Markdown.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.screen_false_fragments import ISLAND_OF, build_island_graph, hav_km, k5


def node_ref(n):
    return {k: n.get(k) for k in ('id', 'name', 'region', 'kv', 'lat', 'lon', 'sub')}


def recovered_voltage_evidence(data, features):
    """Find literal segment overlap with source ways of incompatible classes.

    This is candidate evidence, not reconstruction of the original algorithm's
    selected route: coincident or multi-voltage ways can overlap geometrically.
    """
    from scripts.connection_voltage import route_voltage_compatible
    segments = defaultdict(set)
    for fi, feature in enumerate(features):
        g = feature.get('geometry') or {}
        coords = g.get('coordinates') or []
        parts = [coords] if g.get('type') == 'LineString' else coords
        for part in parts:
            for a, b in zip(part, part[1:]):
                ka, kb = k5(a[1], a[0]), k5(b[1], b[0])
                if ka != kb:
                    segments[tuple(sorted((ka, kb)))].add(fi)
    candidates = []
    for ei, edge in enumerate(data['edges']):
        if edge.get('recovery') not in ('osm_chain', 'osm_chain3'):
            continue
        hits = Counter()
        coords = edge.get('path') or []
        for a, b in zip(coords, coords[1:]):
            hits.update(segments.get(tuple(sorted((k5(*a), k5(*b)))), ()))
        ways = []
        for fi, count in sorted(hits.items()):
            if count < 2:
                continue
            pr = features[fi].get('properties') or {}
            ways.append(dict(feature_index=fi, name=pr.get('_display_name'),
                             kv=pr.get('_voltage_kv'), shared_segments=count,
                             osm_id=pr.get('osm_id') or pr.get('id')))
        if not route_voltage_compatible(w['kv'] for w in ways):
            candidates.append(dict(edge_index=ei, name=edge.get('name'),
                kv=edge.get('kv'), recovery=edge.get('recovery'), source_ways=ways,
                status='candidate_only_literal_shared_geometry'))
    return candidates


def audit(data, near_m=300):
    nodes, edges = data['nodes'], data['edges']
    at = defaultdict(list)
    for n in nodes:
        at[k5(n['lat'], n['lon'])].append(n)
    graphs, mains, comp_id, islands = {}, {}, {}, {}
    for isl in ('hokkaido', 'east', 'west', 'okinawa'):
        keys, comps = build_island_graph(nodes, edges, isl)
        graphs[isl] = (keys, comps)
        mains[isl] = comps[0] if comps else set()
        comp_id[isl] = {k: i for i, c in enumerate(comps) for k in c}
        islands[isl] = {
            'coordinate_keys': len(keys), 'main_keys': len(mains[isl]),
            'fragment_components': max(0, len(comps)-1),
            'fragment_keys': sum(map(len, comps[1:])),
            'fragment_substation_keys': sum(bool(keys[k].get('sub')) for c in comps[1:] for k in c),
        }
    def memberships(k):
        return {ISLAND_OF[n['region']] for n in at.get(k, []) if n.get('region') in ISLAND_OF}
    def endpoint(k):
        return [node_ref(n) for n in at.get(k, [])]

    missing, crossings, ambiguous, gaps, loop_edges = [], [], [], [], []
    edge_degree = Counter()
    for i, e in enumerate(edges):
        if not e.get('a') or not e.get('b'):
            missing.append({'edge_index': i, 'reason': 'missing endpoint field'})
            continue
        a, b = k5(*e['a']), k5(*e['b'])
        ia, ib = memberships(a), memberships(b)
        ref = {'edge_index': i, 'name': e.get('name'), 'kv': e.get('kv'),
               'a': list(a), 'b': list(b), 'recovery': e.get('recovery'),
               'tie': bool(e.get('tie')), 'disclosure': e.get('disclosure')}
        if a not in at or b not in at:
            missing.append(dict(ref, missing_a=a not in at, missing_b=b not in at))
        if a == b:
            loop_edges.append(ref)
        if ia and ib and not ia.intersection(ib):
            crossings.append(dict(ref, islands_a=sorted(ia), islands_b=sorted(ib),
                                  endpoints_a=endpoint(a), endpoints_b=endpoint(b),
                                  status='review_async_or_attribution'))
        if len(ia) > 1 or len(ib) > 1:
            ambiguous.append(dict(ref, islands_a=sorted(ia), islands_b=sorted(ib)))
        for isl in ia.intersection(ib):
            edge_degree[(isl, a)] += 1
            edge_degree[(isl, b)] += 1
        path = e.get('path') or []
        if len(path) >= 2:
            # Either orientation is accepted. A substation centroid can be away
            # from its physical line terminal, so this is only a review signal.
            direct = (hav_km(a, path[0]), hav_km(b, path[-1]))
            reverse = (hav_km(a, path[-1]), hav_km(b, path[0]))
            da, db = min((direct, reverse), key=sum)
            for k, distance, side in ((a, da, 'a'), (b, db, 'b')):
                if distance > 0.5:
                    gaps.append(dict(ref, side=side, gap_m=round(distance*1000, 1),
                                     coordinate=list(k), nodes=endpoint(k),
                                     junction_only=bool(at[k]) and all(not n.get('sub') for n in at[k]),
                                     status='review_geometry_attachment'))

    twin_fragments, main_disagreements, cross_island_groups = [], [], []
    for k, ns in at.items():
        if len(memberships(k)) > 1:
            cross_island_groups.append({'coordinate': list(k), 'nodes': endpoint(k)})
    for isl, (keys, comps) in graphs.items():
        for ci, comp in enumerate(comps[1:], 1):
            twins = [k for k in comp if any(k in mains[o] for o in mains if o != isl)]
            if twins:
                twin_fragments.append({'island': isl, 'component': ci, 'n_keys': len(comp),
                    'twin_main_keys': len(twins), 'fraction': len(twins)/len(comp),
                    'nodes': [node_ref(keys[k]) for k in sorted(comp)],
                    'status': 'review_duplicate_or_attribution'})
    for n in nodes:
        isl = ISLAND_OF.get(n.get('region'))
        if isl is None:
            continue
        k = k5(n['lat'], n['lon'])
        actual = k in mains[isl]
        union = any(k in m for m in mains.values())
        if bool(n.get('main')) != actual:
            main_disagreements.append(dict(node_ref(n), stored_main=bool(n.get('main')),
                recomputed_main=actual, union_main=union,
                component=comp_id[isl][k]))

    near = []
    # Small bounded cell search avoids a dependency on a spatial library.
    cell_size = 0.01
    for isl, (keys, comps) in graphs.items():
        grid = defaultdict(list)
        for k in sorted(mains[isl]):
            grid[(math.floor(k[0]/cell_size), math.floor(k[1]/cell_size))].append(k)
        for ci, comp in enumerate(comps[1:], 1):
            for k in sorted(comp):
                if not (keys[k].get('sub') or edge_degree[(isl, k)] <= 1):
                    continue
                c = (math.floor(k[0]/cell_size), math.floor(k[1]/cell_size))
                candidates = []
                for di in range(-1, 2):
                    for dj in range(-1, 2):
                        for m in grid.get((c[0]+di, c[1]+dj), []):
                            distance = hav_km(k, m)*1000
                            if distance <= near_m:
                                candidates.append((distance, m))
                for distance, m in sorted(candidates)[:3]:
                    # Use all voltage records at each endpoint, not first-wins.
                    va = {n.get('kv') for n in at[k] if ISLAND_OF.get(n.get('region')) == isl and n.get('kv')}
                    vb = {n.get('kv') for n in at[m] if ISLAND_OF.get(n.get('region')) == isl and n.get('kv')}
                    voltage = 'same_observed_class' if va & vb else ('different_observed_classes' if va and vb else 'unknown')
                    near.append({'island': isl, 'component': ci, 'fragment_keys': len(comp),
                        'distance_m': round(distance, 1), 'fragment': node_ref(keys[k]),
                        'main': node_ref(keys[m]), 'voltage_evidence': voltage,
                        'cross_island_ambiguity': len(memberships(k)) > 1 or len(memberships(m)) > 1,
                        'status': 'candidate_only_requires_way_and_terminal_evidence'})
    near.sort(key=lambda r: (r['cross_island_ambiguity'], r['voltage_evidence'] != 'same_observed_class', -r['fragment_keys'], r['distance_m']))
    gaps.sort(key=lambda r: (not r['junction_only'], -r['gap_m']))
    st = data.get('stats', {})
    return {'definitions': {
        'components': 'Per synchronous island, rounded coordinate keys, supplied edges only; no extra stitch/tie. Includes isolated nodes. Not electrical bus-breaker connectivity.',
        'main': 'Largest coordinate component in the node own island. Cached main flags are not trusted.',
        'near': 'Geographical candidates only. Same nominal voltage and proximity do not prove a physical electrical connection.',
        'crossing': 'Disjoint endpoint island memberships. May be legitimate HVDC/FC or attribution error; never automatically classified as an AC fault.',
        'geometry_gap': 'Endpoint to first/last path point >500m, choosing the better orientation. Substation centroid attachments may be intentional.',
        'self_loops': 'Coordinate loops include declared intra-substation stubs. They are not automatically errors or candidates for removal.',
    }, 'counts': {'nodes': len(nodes), 'edges': len(edges),
        'cached_nodes': st.get('n_nodes'), 'cached_edges': st.get('n_edges'),
        'missing_endpoints': len(missing), 'self_loops': len(loop_edges),
        'declared_intra_substation_loops': sum('intra-substation' in (e.get('name') or '') for e in loop_edges),
        'disjoint_island_edges': len(crossings), 'ambiguous_island_edges': len(ambiguous),
        'cross_island_coordinate_groups': len(cross_island_groups),
        'fragment_components': sum(r['fragment_components'] for r in islands.values()),
        'fragment_substation_keys': sum(r['fragment_substation_keys'] for r in islands.values()),
        'cached_main_disagreements': len(main_disagreements),
        'near_candidates': len(near), 'geometry_gap_endpoints': len(gaps)},
        'islands': islands, 'missing_endpoints': missing, 'self_loops': loop_edges,
        'disjoint_island_edges': crossings, 'ambiguous_island_edges': ambiguous,
        'cross_island_coordinate_groups': cross_island_groups,
        'twin_fragments': sorted(twin_fragments, key=lambda r: (-r['fraction'], -r['n_keys'])),
        'main_disagreements': main_disagreements, 'near_candidates': near,
        'geometry_gaps': gaps}


def write_outputs(report, out):
    out.mkdir(parents=True, exist_ok=True)
    (out/'connections.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    features = []
    for r in report['near_candidates']:
        props = {k: v for k,v in r.items() if k not in ('fragment','main')}
        props.update(fragment_name=r['fragment']['name'], main_name=r['main']['name'])
        features.append({'type':'Feature','properties':dict(props,kind='near_candidate'),
            'geometry':{'type':'LineString','coordinates':[[r[x]['lon'],r[x]['lat']] for x in ('fragment','main')]}})
    for r in report['disjoint_island_edges']:
        features.append({'type':'Feature','properties':dict(r,kind='disjoint_island_edge'),
            'geometry':{'type':'LineString','coordinates':[[r[x][1],r[x][0]] for x in ('a','b')]}})
    (out/'connection_candidates.geojson').write_text(json.dumps({'type':'FeatureCollection','features':features},ensure_ascii=False)+'\n')
    c=report['counts']
    lines=['# 系統接続監査', '', f"入力 SHA256: `{report['source_sha256']}`", '',
        '正典は変更していない。件数はこの入力スナップショットに対する監査値。', '',
        '## 確認済みのデータ整合性', '',
        f"- ノード {c['nodes']:,}（保存済み統計 {c['cached_nodes']:,}）、枝 {c['edges']:,}（保存済み統計 {c['cached_edges']:,}）。",
        f"- 保存済み main と所属島別の再計算が異なるノード: {c['cached_main_disagreements']}。定義差と更新漏れの両方を含み得る。",
        f"- 端点ノード欠落: {c['missing_endpoints']}。座標自己ループ: {c['self_loops']}（うち {c['declared_intra_substation_loops']} は構内stubと明示。誤接続件数ではない）。", '',
        '## 座標グラフの残存断片', '',
        '既存枝のみ・島内k5座標。追加stitch/tieなし。変電所は座標キー単位で、サイト数や電気母線数ではない。', '',
        '| 島 | 座標キー | 最大成分 | 断片成分 | 断片ノード | 断片変電所 |',
        '|---|---:|---:|---:|---:|---:|']
    for isl,r in report['islands'].items():
        lines.append(f"| {isl} | {r['coordinate_keys']} | {r['main_keys']} | {r['fragment_components']} | {r['fragment_keys']} | {r['fragment_substation_keys']} |")
    lines += ['', '## 接続候補（未確定）', '',
        '近いだけでは接続しない。同一way・頂点共有・敷地への引込・電圧階級・周波数・公式図の順に確認する。', '',
        '| 島 | 断片側 | 本系統側 | 距離m | 断片ノード | 電圧証拠 | 跨島重複 |',
        '|---|---|---|---:|---:|---|---|']
    for r in report['near_candidates'][:25]:
        lines.append(f"| {r['island']} | {r['fragment']['name']} | {r['main']['name']} | {r['distance_m']} | {r['fragment_keys']} | {r['voltage_evidence']} | {r['cross_island_ambiguity']} |")
    lines += ['', '## その他の確認対象', '',
        f"- 別島に同一座標が存在: {c['cross_island_coordinate_groups']}座標。異電圧端子や変換所の可能性もあるため一括統合しない。",
        f"- 端点の島集合が互いに重ならない枝: {c['disjoint_island_edges']}。HVDC/FCの実線と地域誤帰属を分類する必要がある。",
        f"- pathと接続先座標が500m超離れる端点: {c['geometry_gap_endpoints']}。変電所重心への取付を除外して判読する。", '',
        '全件・ノードID・枝index・根拠は connections.json。候補直線は位置の比較用で、実在線路を意味しない。']
    (out/'connections.md').write_text('\n'.join(lines)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--built',type=Path,default=ROOT/'docs/data/built/all.json')
    p.add_argument('--out-dir',type=Path,default=ROOT/'docs/reports/codex_connection_audit_2026-09-12')
    p.add_argument('--near-m',type=float,default=300)
    p.add_argument('--lines',type=Path,default=ROOT/'docs/data/lines_all.geojson')
    args=p.parse_args()
    raw=args.built.read_bytes()
    report=audit(json.loads(raw),args.near_m)
    report.update(source=str(args.built.resolve()),source_sha256=hashlib.sha256(raw).hexdigest(),
                  audited_at=datetime.now(timezone.utc).isoformat(),near_m=args.near_m)
    if args.lines.exists():
        source_lines = args.lines.read_bytes()
        evidence = recovered_voltage_evidence(json.loads(raw), json.loads(source_lines)['features'])
        report['counts']['recovered_voltage_geometry_candidates'] = len(evidence)
        report['recovered_voltage_evidence'] = evidence
        report['lines_source'] = str(args.lines.resolve())
        report['lines_sha256'] = hashlib.sha256(source_lines).hexdigest()
    write_outputs(report,args.out_dir)
    if 'recovered_voltage_evidence' in report:
        (args.out_dir/'recovered_voltage_evidence.json').write_text(json.dumps({
            'source_sha256':report['source_sha256'],'lines_sha256':report['lines_sha256'],
            'note':'Candidate only: literal shared segments (>=2 per source way). Coincident/multivoltage ways require review; original selected route is not reconstructed.',
            'candidates':report['recovered_voltage_evidence']},ensure_ascii=False,indent=2)+'\n')
    assert hashlib.sha256(args.built.read_bytes()).hexdigest()==report['source_sha256']
    print(json.dumps(report['counts'],ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
