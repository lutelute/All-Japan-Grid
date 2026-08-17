#!/usr/bin/env python3
"""PV有無×UC: 両シナリオの24h UCを解き、(region,fuel,hour)の起動容量とdispatchを保存。"""
import json, sys, time
sys.path.insert(0, '/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid')
from src.uc.scenario import build_national_scenario
from src.uc.solver import solve_uc
from collections import defaultdict

S = '/private/tmp/claude-501/-Users-shigenoburyuto-Documents-GitHub-project-Hayashi-All-Japan-Grid/69ca6350-e35f-4ce1-b335-621694b92146/scratchpad'
out = {}
for label, scen in (('pv', 'fy2023'), ('nopv', 'fy2023_nopv')):
    t0 = time.time()
    scn = build_national_scenario(scenario=scen)
    params = scn.to_uc_parameters()
    res = solve_uc(params)
    gmeta = {g.generator_id if getattr(g,'generator_id',None) else f'g{i}':
             (g.region, g.fuel_type, float(g.capacity_mw))
             for i, g in enumerate(scn.generators)}
    # schedule側のid対応: params.generatorsの並び=schedulesの並びを仮定して添字で
    sched = res.schedules if hasattr(res, 'schedules') else res.generator_schedules
    T = scn.num_periods
    comm = defaultdict(lambda: [0.0]*T)   # (region,fuel) -> committed MW per hour
    disp = defaultdict(lambda: [0.0]*T)
    for i, sc in enumerate(sched):
        g = scn.generators[i]
        key = f"{g.region}|{g.fuel_type}"
        for h in range(min(T, len(sc.commitment))):
            comm[key][h] += float(g.capacity_mw) * (sc.commitment[h] or 0)
            disp[key][h] += float(sc.power_output_mw[h]) if h < len(sc.power_output_mw) else 0.0
    total = defaultdict(float)
    for g in scn.generators:
        total[f"{g.region}|{g.fuel_type}"] += float(g.capacity_mw)
    out[label] = {
        'status': str(getattr(res, 'status', '?')),
        'solve_s': round(time.time()-t0, 1),
        'committed_mw': {k: [round(x) for x in v] for k, v in comm.items()},
        'dispatch_mw': {k: [round(x) for x in v] for k, v in disp.items()},
        'total_mw': {k: round(v) for k, v in total.items()},
        'solar_noon_mw': {r: round(v[12]) for r, v in scn.solar_gen_r.items()},
    }
    print(label, out[label]['status'], f"{out[label]['solve_s']}s",
          '正午起動同期容量計:', sum(v[12] for v in comm.values()))
json.dump(out, open(f'{S}/uc_pv_compare.json', 'w'))
print('saved uc_pv_compare.json')
