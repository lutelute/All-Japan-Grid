"""Apply reviewed aliases within the existing one-site/voltage bus abstraction.

An alias identifies duplicate model records. It adds no line, transformer or
physical bus coupler. Distinct voltage levels and unresolved source identities
must be retained. Callers supply an explicit, SHA-bound plan on a copied model.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections import defaultdict


def model_digest(data):
    """Semantic digest independent of file whitespace, retaining list order."""
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def apply_site_aliases(data, plan):
    """Return (copy, change ledger), refusing ambiguous coordinate-only rewiring.

    A plan must declare equal, positive voltage, synchronous island, source OSM
    identity and explicit node IDs. Its input digest prevents stale index use.
    Source evidence is assessed by the caller; this function enforces the
    structural preconditions again. It never writes files or mutates ``data``.
    """
    from src.powerflow.connectivity import REGION_ISLAND

    if plan.get('input_model_digest') != model_digest(data):
        raise ValueError('Alias plan does not match the model snapshot')
    by_id = {n['id']: n for n in data['nodes']}
    if len(by_id) != len(data['nodes']):
        raise ValueError('Node IDs are not unique')
    at = defaultdict(list)
    key = lambda n: (round(n['lat'], 5), round(n['lon'], 5))
    for n in data['nodes']:
        at[key(n)].append(n['id'])
    aliases = plan.get('aliases', [])
    removed = {a['from_id'] for a in aliases}
    if len(removed) != len(aliases):
        raise ValueError('Each source node needs exactly one target')
    coord_map = {}
    for alias in aliases:
        a, b = by_id[alias['from_id']], by_id[alias['to_id']]
        if a['id'] == b['id'] or b['id'] in removed:
            raise ValueError('Self aliases and alias chains are not accepted')
        if not (a.get('sub') == b.get('sub') == 1):
            raise ValueError('Only substation model records can be aliased')
        if float(a.get('kv') or 0) <= 0 or abs(a['kv'] - b.get('kv', 0)) > 1e-6:
            raise ValueError('Unknown or distinct voltage classes cannot be merged')
        isl = REGION_ISLAND.get(a.get('region'))
        if not isl or isl != REGION_ISLAND.get(b.get('region')):
            raise ValueError('An alias cannot bridge synchronous islands')
        if not alias.get('osm_identity') or alias.get('decision') != 'trial_alias':
            raise ValueError('Verified source identity and trial decision required')
        if at[key(a)] != [a['id']]:
            raise ValueError('Source coordinate has other buses; endpoint IDs are required')
        if any(REGION_ISLAND.get(by_id[nid].get('region')) != isl for nid in at[key(b)]):
            raise ValueError('Target coordinate is shared by different synchronous islands')
        target_classes = {by_id[nid].get('kv', 0) for nid in at[key(b)]}
        if len(target_classes) > 1:
            for edge in data['edges']:
                if key(a) in (tuple(edge['a']), tuple(edge['b'])) and not edge.get('kv'):
                    raise ValueError('Unknown-voltage edge cannot select a target voltage bus')
        coord_map[key(a)] = key(b)

    result = copy.deepcopy(data)
    result['nodes'] = [n for n in result['nodes'] if n['id'] not in removed]
    targets = {n['id']: n for n in result['nodes']}
    for alias in aliases:
        target = targets[alias['to_id']]
        target.setdefault('identity_aliases', []).append(copy.deepcopy(alias))
    changes = []
    length_references = []
    for i, edge in enumerate(result['edges']):
        for side in ('a', 'b'):
            k = tuple(round(v, 5) for v in edge[side])
            if k in coord_map:
                path = edge.get('path') or []
                if not path or all(p == path[0] for p in path):
                    # This branch's length is estimated from bus coordinates.
                    # Identity changes must not silently change its impedance.
                    edge.setdefault('identity_length_reference',
                                    copy.deepcopy([data['edges'][i]['a'], data['edges'][i]['b']]))
                    if i not in length_references:
                        length_references.append(i)
                changes.append({'edge_index': i, 'side': side,
                                'before': list(edge[side]), 'after': list(coord_map[k])})
                edge[side] = list(coord_map[k])
    # Path coordinates are observations; changing bus identity must not redraw them.
    for before, after in zip(data['edges'], result['edges']):
        assert before.get('path') == after.get('path')
        assert before.get('kv') == after.get('kv') and before.get('par') == after.get('par')
    result['identity_trial'] = {'input_model_digest': plan['input_model_digest'],
                               'aliases': copy.deepcopy(aliases),
                               'scope': 'Copy only. Model-record identity, not new physical equipment.'}
    # Old cached main/degree/stats remain untouched here. The trial reporter
    # recomputes its own topology rather than treating these caches as evidence.
    return result, {'removed_nodes': sorted(removed), 'endpoint_changes': changes,
                    'preserved_length_estimate_edges': length_references,
                    'added_edges': 0, 'removed_edges': 0, 'changed_paths': 0}
