#!/usr/bin/env python3
"""Measure alias effects with identical injections on the actual east circuit.

Uses the saved trial plan. Builds the original circuit, allocates its synthetic
load/generation once, then merges duplicate buses in a copy. No load is dropped
or redistributed. AC uses a fixed solver with no pruning or relaxed fallback.
"""
from __future__ import annotations
import copy
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT/'docs/reports/codex_same_site_trial_2026-09-13'
SCRATCH = Path('/tmp/ajg_same_site_trial')


def safe(value):
    import numpy as np
    if isinstance(value, dict):
        return {str(k): safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(v) for v in value]
    if isinstance(value, np.generic):
        return safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def write(result):
    (OUT/'powerflow.json').write_text(json.dumps(safe(result), ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def main():
    import networkx as nx
    import numpy as np
    import pandapower as pp
    from pandapower.toolbox import fuse_buses
    from pandapower.topology import create_nxgraph
    from scripts.run_full_powerflow_from_db import (build_island_net, attach_generators, attach_default_for,
        allocate_loads, add_per_component_slacks, balance_by_zone, load_demand_config)
    from scripts.audit_model_circuit_quality import assembly_signature
    from src.powerflow.pipeline import add_reactive_compensation
    from src.powerflow.site_identity import model_digest

    built = ROOT/'docs/data/built/all.json'
    before_sha = hashlib.sha256(built.read_bytes()).hexdigest()
    data = json.loads(built.read_text())
    report = json.loads((OUT/'trial.json').read_text())
    assert model_digest(data) == report['plan']['input_model_digest']
    signature, manifest = assembly_signature()
    flags = dict(territory=True, dedup_nodes=True, site_trafos=False, deenergize_unbuilt=False,
                 synthetic_ties_live=False, btb_split=True, freq_fix=True, implicit_stepdown=True, cap_calib=False)
    print('Building the east circuit with the same explicit assembly options.', flush=True)
    nodes = copy.deepcopy(data['nodes'])
    net, bus_of, build_stats = build_island_net('east', nodes, data['edges'], 50, {}, **flags)
    # Preserve source IDs on existing buses for interpretation after aliases.
    id_index = {n['id']: i for i, n in enumerate(data['nodes'])}
    moves = []
    for a in report['plan']['aliases']:
        old_bus, target_bus = bus_of[id_index[a['from_id']]], bus_of[id_index[a['to_id']]]
        assert abs(net.bus.at[old_bus, 'vn_kv']-net.bus.at[target_bus, 'vn_kv']) < 1e-6
        moves.append(dict(a, from_bus=int(old_bus), to_bus=int(target_bus)))
    cfg = load_demand_config()
    mode = attach_default_for('east')
    print('Allocating load and generation once; preserving every injection in all variants.', flush=True)
    gen_stats = attach_generators(net, bus_of, nodes, 'east', attach_mode=mode, stats=True)
    allocated = allocate_loads(net, cfg, pop_tilt=False)
    compensation = cfg.get('reactive_compensation_factor', .8)
    add_reactive_compensation(net, factor=compensation)
    balance_by_zone(net, cfg, use_zone_src=True)
    solver = dict(algorithm='nr', init='dc', max_iteration=50, tolerance_mva=1e-4,
                  enforce_q_lims=True, numba=True, check_connectivity=True)
    output = dict(source_sha256=before_sha, assembly_signature=signature, assembly_manifest=manifest,
                  assembly_options=flags, pandapower=pp.__version__,
                  scope='East full circuit; one synthetic regional-demand operating point at load_factor=0.85. '
                        'Same P/Q injections and compensation in all variants. No pruning, no new provisional infeed, '
                        'no low-voltage aggregation. Per-component slack remains a modelling assumption.',
                  settings=dict(load_factor=cfg.get('load_factor'), power_factor=cfg.get('power_factor'),
                                reactive_compensation_factor=compensation, generator_attach=mode,
                                gen_zone_by_operator=True, solver=solver),
                  allocated_load_mw=allocated, gen_stats=gen_stats, moves=moves, variants={}, complete=False)
    for path in sorted((ROOT/'data').glob('*_plants*.geojson')):
        output.setdefault('additional_source_sha256', {})[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in [ROOT/'scripts/solve_same_site_trial.py', OUT/'alias_plan.json']:
        output.setdefault('additional_source_sha256', {})[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    write(output)
    baseline_dc = None
    for label, selected in [('before', []), ('source_voltage_confirmed', [a for a in moves if a['voltage_basis']=='source_tag']),
                            ('all_eligible_aliases', moves)]:
        start = time.time()
        trial = copy.deepcopy(net)
        for a in selected:
            fuse_buses(trial, a['to_bus'], a['from_bus'], drop=True)
        # All device injections retain identical row IDs, P/Q, capacities and status.
        for table in ['load', 'gen', 'sgen', 'shunt']:
            cols = [c for c in net[table].columns if c != 'bus']
            assert net[table][cols].equals(trial[table][cols]), table
        graph = create_nxgraph(trial, respect_switches=True, include_out_of_service=False)
        comps = sorted(nx.connected_components(graph), key=len, reverse=True)
        mismatch = [int(i) for i, line in trial.line.iterrows() if line.in_service and
                    abs(trial.bus.at[line.from_bus,'vn_kv']-trial.bus.at[line.to_bus,'vn_kv']) > .5]
        n_comp, n_slack, n_synth = add_per_component_slacks(trial)
        result = dict(bus_count=len(trial.bus), line_count=len(trial.line), trafo_count=len(trial.trafo),
                      components=len(comps), largest_component=len(comps[0]),
                      slack_count=n_slack, synthetic_slack_count=n_synth,
                      line_voltage_mismatch_count=len(mismatch), line_voltage_mismatch_indices=mismatch,
                      preserved_load_mw=float(trial.load.p_mw.sum()), preserved_load_mvar=float(trial.load.q_mvar.sum()),
                      preserved_gen_mw=float(trial.gen.p_mw.sum()), aliases=len(selected))
        dc_net = copy.deepcopy(trial)
        try:
            pp.rundcpp(dc_net, check_connectivity=True)
            result['dc'] = dict(converged=bool(dc_net.converged),
                                served_mw=float(dc_net.res_load.p_mw.sum()),
                                slack_mw=float(dc_net.res_ext_grid.p_mw.sum()),
                                max_line_loading_pct=float(dc_net.res_line.loading_percent.max()))
            if baseline_dc is None:
                baseline_dc = dc_net.res_line.copy()
            delta = (dc_net.res_line.p_from_mw-baseline_dc.p_from_mw).abs().sort_values(ascending=False)
            result['dc']['max_abs_line_flow_change_mw'] = float(delta.max())
            result['dc']['largest_flow_changes'] = [dict(line=int(i), name=str(dc_net.line.at[i,'name']),
                before_mw=float(baseline_dc.at[i,'p_from_mw']), after_mw=float(dc_net.res_line.at[i,'p_from_mw']),
                absolute_change_mw=float(delta[i])) for i in delta.head(8).index]
            worst = dc_net.res_line.loading_percent.sort_values(ascending=False).head(5)
            result['dc']['largest_loadings'] = [dict(line=int(i), name=str(dc_net.line.at[i,'name']),
                loading_pct=float(v), from_bus=str(dc_net.bus.at[dc_net.line.at[i,'from_bus'],'name']),
                to_bus=str(dc_net.bus.at[dc_net.line.at[i,'to_bus'],'name'])) for i,v in worst.items()]
        except Exception as exc:
            result['dc'] = dict(converged=False, error=str(exc))
        print(label, 'AC attempt', flush=True)
        try:
            pp.runpp(trial, **solver)
            valid = trial.res_bus.vm_pu.dropna()
            result['ac'] = dict(converged=bool(trial.converged),
                served_mw=float(trial.res_load.p_mw.sum()), served_frac=float(trial.res_load.p_mw.sum()/allocated),
                slack_mw=float(trial.res_ext_grid.p_mw.sum()),
                line_loss_mw=float(trial.res_line.pl_mw.sum()), trafo_loss_mw=float(trial.res_trafo.pl_mw.sum()),
                vm_min=float(valid.min()), vm_max=float(valid.max()), buses_below_0_9=int((valid<.9).sum()),
                max_line_loading_pct=float(trial.res_line.loading_percent.max()),
                max_trafo_loading_pct=float(trial.res_trafo.loading_percent.max()),
                iterations=trial._ppc.get('iterations'))
        except Exception as exc:
            result['ac'] = dict(converged=False, error=str(exc), iterations=trial.get('_ppc', {}).get('iterations'))
        result['seconds'] = round(time.time()-start, 2)
        output['variants'][label] = result
        # Source-bus local values for the HTML are evidence only on converged AC.
        for a in moves:
            bus = a['to_bus'] if a in selected else a['from_bus']
            entry = dict(case_id=a['case_id'], selected=a in selected, bus=int(bus),
                         load_mw=float(trial.load.loc[trial.load.bus==bus, 'p_mw'].sum()),
                         vm_pu=float(trial.res_bus.at[bus, 'vm_pu']) if result['ac']['converged'] else None)
            result.setdefault('site_results', []).append(entry)
        write(output)
        print(label, json.dumps(safe(result), ensure_ascii=False), flush=True)
    # Independently rebuild the proposed copied built data and compare its
    # electrical branches with the fused circuit used for fixed-injection PF.
    from src.powerflow.site_identity import apply_site_aliases
    after_data, _ = apply_site_aliases(data, report['plan'])
    rebuilt, rebuilt_map, _ = build_island_net('east', copy.deepcopy(after_data['nodes']), after_data['edges'], 50, {}, **flags)
    fused = copy.deepcopy(net)
    bus_moves = {a['from_bus']: a['to_bus'] for a in moves}
    for a in moves:
        fuse_buses(fused, a['to_bus'], a['from_bus'], drop=True)
    alias_ids = {a['from_id']: a['to_id'] for a in moves}

    def fingerprint(circuit, source_nodes, mapping, moves_by_bus):
        origins = {}
        for i, b in mapping.items():
            b = moves_by_bus.get(int(b), int(b))
            nid = source_nodes[int(i)]['id']
            origins.setdefault(b, set()).add(alias_ids.get(nid, nid))
        bus_keys = {int(b): 'source:'+','.join(sorted(origins[b])) if b in origins else
                    'generated:'+str(row['name'])+':'+str(row['vn_kv'])+':'+str(row['zone'])
                    for b, row in circuit.bus.iterrows()}
        assert len(set(bus_keys.values())) == len(bus_keys)
        sections = {}
        for element, terminals, cols in [
            ('line', ['from_bus','to_bus'], ['length_km','r_ohm_per_km','x_ohm_per_km','c_nf_per_km','g_us_per_km','max_i_ka','parallel','in_service']),
            ('trafo', ['hv_bus','lv_bus'], ['sn_mva','vn_hv_kv','vn_lv_kv','vk_percent','vkr_percent','pfe_kw','i0_percent','shift_degree','tap_side','tap_neutral','tap_min','tap_max','tap_step_percent','tap_pos','in_service','parallel'])]:
            rows = []
            for _, row in circuit[element].iterrows():
                ends = [bus_keys[int(row[t])] for t in terminals]
                if element == 'line': ends.sort()
                item = dict(ends=ends, **{c:safe(row[c]) for c in cols if c in row})
                rows.append(json.dumps(item, sort_keys=True))
            sections[element] = sorted(rows)
        return sections
    f1 = fingerprint(fused, data['nodes'], bus_of, bus_moves)
    f2 = fingerprint(rebuilt, after_data['nodes'], rebuilt_map, {})
    output['rebuild_crosscheck'] = dict(
        line_parameters_and_endpoints_equal=f1['line']==f2['line'],
        trafo_parameters_and_endpoints_equal=f1['trafo']==f2['trafo'],
        fused_counts=dict(bus=len(fused.bus), line=len(fused.line), trafo=len(fused.trafo)),
        rebuilt_counts=dict(bus=len(rebuilt.bus), line=len(rebuilt.line), trafo=len(rebuilt.trafo)))
    print('Rebuild crosscheck:', output['rebuild_crosscheck'], flush=True)
    output['complete'] = True
    assert hashlib.sha256(built.read_bytes()).hexdigest() == before_sha
    write(output)
    print('Finished; canonical data unchanged.', flush=True)


if __name__ == '__main__':
    main()
