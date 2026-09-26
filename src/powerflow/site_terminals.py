"""Separate saved site/line geometry from an explicit electrical projection.

Sites are physical footprints, buses are voltage-class abstractions, and line
terminals retain their saved coordinates. Site membership is metadata, never
a fabricated straight wire. Unresolved terminals and input model records stay. Saved paths may contain earlier reconstructions.
"""
from __future__ import annotations
import copy
import json
import math
from collections import defaultdict


def endpoint_evidence(edge, side, geometry):
    """Locate the existing path end without extending or cutting the path."""
    from shapely.geometry import LineString, Point, shape
    from shapely.ops import transform
    path = edge.get('path') or []
    if len(path) < 2 or all(p == path[0] for p in path):
        return dict(saved_path_endpoint=None, geometry_status='no_saved_path',
                    distance_to_site_m=None, electrical_confirmation=False)
    dist = lambda a,b: math.hypot(a[0]-b[0], a[1]-b[1])
    rev = dist(edge['a'], path[0])+dist(edge['b'], path[-1]) > dist(edge['b'], path[0])+dist(edge['a'], path[-1])
    point = path[-1 if (side == 'a') == rev else 0]
    footprint = shape(geometry)
    if footprint.geom_type not in ('Polygon', 'MultiPolygon'):
        return dict(saved_path_endpoint=point, geometry_status='site_boundary_unknown',
                    distance_to_site_m=None, electrical_confirmation=False)
    lat = footprint.centroid.y
    project = lambda x,y,z=None: (x*111320*math.cos(math.radians(lat)), y*111320)
    polygon = transform(project, footprint)
    end = Point(project(point[1],point[0]))
    line = LineString([project(p[1],p[0]) for p in path])
    distance = end.distance(polygon)
    status = ('endpoint_in_site' if polygon.covers(end) else
              'endpoint_near_site' if distance <= 25 else
              'path_crosses_site_end_outside' if line.intersects(polygon) else 'endpoint_outside_site')
    return dict(saved_path_endpoint=point, geometry_status=status,
                distance_to_site_m=round(distance, 2), electrical_confirmation=False)


def build_site_terminal_view(data, cases, plan):
    """Preserve input records; explicitly describe the previously trialed aliases."""
    from shapely.geometry import shape
    from src.powerflow.site_identity import apply_site_aliases, model_digest
    # Reuse the validated, snapshot-bound alias preconditions; keep its input.
    apply_site_aliases(data, plan)
    at = defaultdict(list)
    for node in data['nodes']:
        at[(round(node['lat'],5),round(node['lon'],5))].append(node)
    sites, observations, case_nodes = {}, {}, {}
    for case in cases:
        case_nodes[case['case_id']] = {case['fragment']['id'], case['main']['id']}
        for node, source in [(case['fragment'],case['source_fragment']), (case['main'],case['source_main'])]:
            if not source.get('validated'):
                continue
            sid = source['osm_identity']
            geometry = shape(source['geometry'])
            # A display anchor inside a concave footprint, not a measured busbar.
            anchor = geometry.representative_point()
            sites.setdefault(sid, dict(site_id=sid, geometry=source['geometry'],
                display_anchor=[anchor.y,anchor.x], anchor_role='site_display_only',
                source_geometry_sha256=source['geometry_sha256'],
                source_path=source['path'], model_records=[]))
            observations[node['id']] = dict(site_id=sid, kv=node.get('kv'),
                original_coordinate=[node['lat'],node['lon']], source_voltage_kv=source['voltage_kv'])
            if node['id'] not in sites[sid]['model_records']:
                sites[sid]['model_records'].append(node['id'])
    terminals = []
    for index, edge in enumerate(data['edges']):
        for side in ['a','b']:
            candidates = at[tuple(round(v,5) for v in edge[side])]
            if not candidates:
                continue
            kv = float(edge.get('kv') or 0)
            matches = [n for n in candidates if kv > 0 and abs((n.get('kv') or 0)-kv) < .5]
            # Preserve the current builder's decision as a traceable hypothesis.
            node = (matches or candidates)[0]
            if node['id'] not in observations:
                continue
            sid = observations[node['id']]['site_id']
            terminals.append(dict(terminal_id=f'e{index}:{side}', edge_index=index, side=side,
                source_node_id=node['id'], site_id=sid, model_kv=node.get('kv'), edge_kv=kv,
                name=edge.get('name'), path_provenance={k:edge[k] for k in ['recovery','disclosure','conn_class','same_site','tie'] if k in edge},
                geometry_basis='saved_built_path_may_include_prior_reconstruction',
                original_bus_reference=list(edge[side]),
                assignment_basis='existing_builder_voltage_choice' if matches else 'existing_builder_first_candidate',
                **endpoint_evidence(edge, side, sites[sid]['geometry'])))
    return dict(schema='site-terminal-trial/v1', input_model_digest=model_digest(data),
        sites=sites, observations=observations, terminals=terminals,
        cases={cid:dict(node_ids=sorted(ids), site_ids=sorted({observations[n]['site_id'] for n in ids if n in observations}),
                       terminal_ids=[t['terminal_id'] for t in terminals if t['source_node_id'] in ids])
               for cid,ids in case_nodes.items()},
        electrical_aliases=copy.deepcopy(plan['aliases']),
        preservation=dict(source_nodes=len(data['nodes']), source_edges=len(data['edges']),
                          source_nodes_removed=0, source_edges_removed=0, paths_modified=0,
                          new_physical_wires=0),
        scope='Input model records retained. Electrical projection uses the same 13 conditional aliases; '
              'site membership and geometric proximity do not certify internal busbar connectivity.')


def project_site_terminals(base_net, node_bus_map, view):
    """Apply an explicit trial projection by IDs, independent of map coordinates.

    ``base_net`` already holds the fixed operating point. Source devices and
    branch parameters stay unchanged. Only bus identity and display geo change.
    """
    from pandapower.toolbox import fuse_buses
    net = copy.deepcopy(base_net)
    alias_map = {a['from_id']:a['to_id'] for a in view['electrical_aliases']}
    for alias in view['electrical_aliases']:
        old, target = node_bus_map[alias['from_id']], node_bus_map[alias['to_id']]
        if old != target:
            fuse_buses(net, target, old, drop=True)
    moved = {}
    for nid, obs in view['observations'].items():
        if nid not in node_bus_map:
            continue
        bus = node_bus_map[alias_map.get(nid,nid)]
        anchor = view['sites'][obs['site_id']]['display_anchor']
        if bus in moved and moved[bus] != obs['site_id']:
            raise ValueError('One electrical bus maps to distinct physical sites')
        moved[bus] = obs['site_id']
        net.bus.at[bus,'geo'] = json.dumps(dict(type='Point',coordinates=[anchor[1],anchor[0]]))
    return net, dict(display_buses_anchored=len(moved), site_ids=sorted(set(moved.values())))
