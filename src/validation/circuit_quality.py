"""Read-only checks of the assembled circuit, distinct from map connectivity.

A transformer without a substation witness is a review candidate, not proof
that no transformer exists in the real world. These checks never repair a net.
"""
from collections import Counter, defaultdict


def circuit_findings(net, node_sources_by_bus):
    """Inspect a pandapower net and source-node provenance for its buses."""
    mismatches, unwitnessed, missing_sources = [], [], []
    for li, row in net.line.iterrows():
        if not bool(row.in_service):
            continue
        a, b = int(row.from_bus), int(row.to_bus)
        ka, kb = float(net.bus.at[a, 'vn_kv']), float(net.bus.at[b, 'vn_kv'])
        if abs(ka - kb) > 0.5:
            mismatches.append(dict(line=int(li), name=str(row['name']),
                                   from_bus=a, to_bus=b, from_kv=ka, to_kv=kb,
                                   recorded_line_kv=float(row.get('kv_class', 0) or 0)))
    for ti, row in net.trafo.iterrows():
        if not bool(row.in_service):
            continue
        a, b = int(row.hv_bus), int(row.lv_bus)
        sa, sb = node_sources_by_bus.get(a, []), node_sources_by_bus.get(b, [])
        if not sa or not sb:
            missing_sources.append(int(ti))
            continue
        if not any(n.get('sub') == 1 for n in [*sa, *sb]):
            origins = {n['id']: n for n in [*sa, *sb]}
            unwitnessed.append(dict(trafo=int(ti), name=str(row['name']),
                hv_bus=a, lv_bus=b, hv_kv=float(row.vn_hv_kv), lv_kv=float(row.vn_lv_kv),
                sn_mva=float(row.sn_mva), origins=list(origins.values()),
                mechanism='implicit_stepdown' if '#43a' in str(row['name']) else 'coordinate_ladder',
                status='review_no_substation_node_witness'))
    return dict(line_voltage_mismatches=mismatches,
                transformers_without_site_witness=unwitnessed,
                transformer_source_mapping_missing=missing_sources,
                counts=dict(buses=len(net.bus), lines=len(net.line),
                    transformers=len(net.trafo), switches=len(net.switch),
                    line_voltage_mismatches=len(mismatches),
                    transformers_without_site_witness=len(unwitnessed),
                    transformer_source_mapping_missing=len(missing_sources),
                    unwitnessed_by_mechanism=dict(Counter(x['mechanism'] for x in unwitnessed))))


def source_nodes_by_bus(bus_of_nodeidx, nodes, stepdown_ledger=()):
    """Preserve every deduplicated source; inherit origins for inserted buses."""
    out = defaultdict(list)
    for ni, bi in bus_of_nodeidx.items():
        n = nodes[int(ni)]
        out[int(bi)].append({k: n.get(k) for k in
            ('id', 'name', 'kv', 'sub', 'region', 'lat', 'lon')})
    for item in stepdown_ledger:
        out[int(item['new_bus'])] = [dict(n,via='implicit_stepdown')
                                     for n in out.get(int(item['bus']), [])]
    return dict(out)


def unknown_line_components(net, node_sources_by_bus):
    """Screen unknown-line components by original observed boundary voltage.

    One observed class is a propagation candidate conditional on the existing
    endpoint bindings being correct. Conflicts must not create transformers.
    The computation layer's provisional 66 kV is not an observed boundary.
    """
    import networkx as nx
    g=nx.MultiGraph()
    incident_classes=defaultdict(set)
    for li,row in net.line.iterrows():
        if not bool(row.in_service):
            continue
        kv=float(row.get('kv_class',0) or 0)
        if kv<=0:
            g.add_edge(int(row.from_bus),int(row.to_bus),key=int(li))
        else:
            for b in (int(row.from_bus),int(row.to_bus)):
                incident_classes[b].add(kv)
    results=[]
    for comp in nx.connected_components(g):
        classes={float(n.get('kv') or 0) for b in comp for n in node_sources_by_bus.get(b,[])
                 if float(n.get('kv') or 0)>0 and not n.get('via')}
        classes.update(kv for b in comp for kv in incident_classes.get(b,()))
        lines=[int(key) for _,_,key in g.subgraph(comp).edges(keys=True)]
        status=('single_observed_class' if len(classes)==1 else
                'conflicting_observed_classes' if classes else 'unanchored')
        mismatch=sum(abs(float(net.bus.at[int(net.line.at[li,'from_bus']),'vn_kv'])-
                         float(net.bus.at[int(net.line.at[li,'to_bus']),'vn_kv']))>.5 for li in lines)
        results.append(dict(buses=sorted(comp),lines=sorted(lines),observed_kv=sorted(classes),
                            status=status,mismatched_lines=mismatch))
    return results


def candidate_removal_connectivity(net, candidates):
    """Sensitivity only: remove candidate transformers from a graph copy.

    No load/generation allocation, slack insertion, or power-flow solve occurs.
    A component increase is exposure to an assumption, not improved accuracy.
    """
    import networkx as nx
    import pandapower.topology as top
    before = top.create_nxgraph(net, respect_switches=True)
    after = before.copy()
    removed = 0
    for item in candidates:
        key = ('trafo', item['trafo'])
        if after.has_edge(item['hv_bus'], item['lv_bus'], key):
            after.remove_edge(item['hv_bus'], item['lv_bus'], key)
            removed += 1
    def counts(g):
        comps = list(nx.connected_components(g))
        return dict(components=len(comps), largest_component=max(map(len, comps), default=0))
    return dict(before=counts(before), without_candidates=counts(after), removed=removed)


def structure_voltage_findings(structure, way_voltage_classes):
    """Compare known source line/bay classes with attached structure classes.

    All observed classes on a source geometry key are allowed, including
    multivoltage ways. Unknowns are counted separately, never guessed.
    """
    vls = {v['vl_id']: float(v['nominal_kv']) for v in structure['voltage_levels']}
    bbs = {b['busbar_id']: b for b in structure['busbars']}
    terminals, bays = [], []
    unknown, missing = 0, 0
    for t in structure['terminals']:
        kv = vls.get(t['vl_id'], 0)
        if t['line_key'] not in way_voltage_classes:
            missing += 1
            continue
        classes = set(way_voltage_classes[t['line_key']])
        if kv <= 0 or not classes:
            unknown += 1
        elif not any(abs(kv - c) < 0.5 for c in classes):
            terminals.append(dict(terminal=t['terminal_id'], line_key=t['line_key'],
                line_name=t.get('line_name'), source_kv=sorted(classes), attached_kv=kv,
                binding=t['binding'], attach_kind=t['attach_kind'], attach_id=t['attach_id']))
    for bay in structure['bays']:
        kv = vls.get(bay['vl_id'], 0)
        for bbid in bay['busbar_ids']:
            bb = bbs.get(bbid)
            bkv = vls.get(bb['vl_id'], 0) if bb else 0
            if kv > 0 and bkv > 0 and abs(kv-bkv) > 0.5:
                bays.append(dict(bay=bay['bay_id'], busbar=bbid, bay_kv=kv, busbar_kv=bkv))
    return dict(site=structure['site'], terminal_voltage_conflicts=terminals,
                bay_voltage_conflicts=bays, unknown_terminal_voltage=unknown,
                missing_source_way=missing)
