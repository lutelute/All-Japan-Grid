#!/usr/bin/env python3
"""Verify site/terminal separation on the full east circuit at fixed injections."""
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT = ROOT/'docs/reports/codex_same_site_trial_2026-09-13'


def main():
    import pandapower as pp
    from pandapower.toolbox import fuse_buses
    from src.powerflow.site_terminals import build_site_terminal_view, project_site_terminals
    from src.powerflow.pipeline import add_reactive_compensation
    from scripts.run_full_powerflow_from_db import (build_island_net, attach_generators, attach_default_for,
        allocate_loads, add_per_component_slacks, balance_by_zone, load_demand_config)
    built = ROOT/'docs/data/built/all.json'
    digest = hashlib.sha256(built.read_bytes()).hexdigest()
    data = json.loads(built.read_text())
    report = json.loads((OUT/'trial.json').read_text())
    assert digest == report['source_sha256']
    view = build_site_terminal_view(data,report['candidates'],report['plan'])
    (OUT/'site_terminals.json').write_text(json.dumps(view,ensure_ascii=False,indent=2)+'\n')
    options = json.loads((OUT/'powerflow.json').read_text())['assembly_options']
    nodes = copy.deepcopy(data['nodes'])
    net,bus_of,_ = build_island_net('east',nodes,data['edges'],50,{},**options)
    cfg = load_demand_config()
    attach_generators(net,bus_of,nodes,'east',attach_mode=attach_default_for('east'),stats=True)
    allocate_loads(net,cfg,pop_tilt=False)
    add_reactive_compensation(net,factor=cfg.get('reactive_compensation_factor',.8))
    balance_by_zone(net,cfg,use_zone_src=True)
    ids = {data['nodes'][i]['id']:b for i,b in bus_of.items()}
    fused = copy.deepcopy(net)
    for a in view['electrical_aliases']:
        fuse_buses(fused,ids[a['to_id']],ids[a['from_id']],drop=True)
    separated,changes = project_site_terminals(net,ids,view)
    checks = {}
    for name in ['line','trafo','load','gen','sgen','shunt','switch']:
        checks[name] = fused[name].equals(separated[name])
    columns = [c for c in fused.bus.columns if c != 'geo']
    checks['bus_electrical_attributes'] = fused.bus[columns].equals(separated.bus[columns])
    assert all(checks.values()),checks
    for circuit in [fused,separated]:
        add_per_component_slacks(circuit)
        pp.rundcpp(circuit,check_connectivity=True)
    flow_delta = float((fused.res_line.p_from_mw-separated.res_line.p_from_mw).abs().max())
    assert flow_delta < 1e-9
    result = dict(source_sha256=digest, electrical_tables_equal=checks,
        dc_converged=bool(fused.converged and separated.converged),
        max_line_flow_difference_mw=flow_delta, load_mw=float(separated.load.p_mw.sum()),
        bus_count=len(separated.bus), line_count=len(separated.line), trafo_count=len(separated.trafo),
        terminal_count=len(view['terminals']), site_count=len(view['sites']), changes=changes,
        source_observations=view['preservation'],
        ac='The same electrical tables and injections as the 13-alias trial; AC was not rerun for display-only geometry.',
        scope='Demonstrates coordinate-independent electrical projection, not physical confirmation of the 13 aliases.',
        source_files={path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in
            ['src/powerflow/site_terminals.py','scripts/trial_site_terminal_projection.py',
             'docs/reports/codex_same_site_trial_2026-09-13/site_terminals.json']})
    assert hashlib.sha256(built.read_bytes()).hexdigest() == digest
    (OUT/'site_terminal_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
