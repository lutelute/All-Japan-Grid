#!/usr/bin/env python3
"""PV有無×UC → 動的比較: ①24h系統慣性カーブ ②正午の動揺モード ③正午のS_sc(66-77kV)。
橋=UCの(region,fuel)起動率をAGJ機械集約へ適用(容量比例・介入#10と同族の近似・開示)。"""
import json, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid')
import numpy as np, scipy.sparse as sp
from scipy.sparse.linalg import splu
from scripts.run_full_powerflow_from_db import build_island_net, attach_generators
from scripts.gen_ybus_numeric import load_ybus_npz
from src.dynamics.machine_agg import aggregate_machines, build_classical_model, classify

ROOT = '/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid'
S = '/private/tmp/claude-501/-Users-shigenoburyuto-Documents-GitHub-project-Hayashi-All-Japan-Grid/69ca6350-e35f-4ce1-b335-621694b92146/scratchpad'
uc = json.load(open(f'{S}/uc_pv_compare.json'))

H_OF = {'nuclear':6.0,'coal':5.0,'lng':5.5,'oil':4.5,'hydro':3.5,'pumped_hydro':3.5,
        'geothermal':4.0,'biomass':4.0,'battery':0.0,'unknown':4.5}
ISL = {'hokkaido':['hokkaido'],'east':['tohoku','tokyo'],
       'west':['chubu','hokuriku','kansai','chugoku','shikoku','kyushu'],'okinawa':['okinawa']}
# モデル燃料(OSM英語)→UC燃料クラス
F2UC = {'gas':'lng','lng':'lng','coal':'coal','nuclear':'nuclear','oil':'oil',
        'hydro':'hydro','pumped_storage':'pumped_hydro','pumped-storage':'pumped_hydro',
        'geothermal':'geothermal','biomass':'biomass','waste':'biomass'}

# ① 24h慣性カーブ [GW·s]
curves = {}
for lab in ('pv','nopv'):
    comm = uc[lab]['committed_mw']
    for isl, regs in ISL.items():
        e = np.zeros(24)
        for key, series in comm.items():
            reg, fuel = key.split('|')
            if reg not in regs: continue
            H = H_OF.get(fuel, 4.5)
            e += H * np.array(series[:24]) / 1000.0
        curves[(lab, isl)] = e
for isl in ('east','west'):
    a, b = curves[('pv',isl)], curves[('nopv',isl)]
    dip = (b[12]-a[12])/b[12]*100
    print(f"{isl}: 正午慣性 PVあり{a[12]:.0f} / なし{b[12]:.0f} GW·s (PVで-{dip:.0f}%)")

# ② 正午の起動率 → 機械集約スケール → モード/S_sc
built = json.load(open(f'{ROOT}/docs/data/built/all.json'))
res = {}
for island, freq in (('east',50), ('west',60)):
    Y, base, z = load_ybus_npz(f'{ROOT}/dist/ybus/{island}.npz'); Y = Y.tocsc()
    pos = {int(b): i for i, b in enumerate(np.asarray(z['bus_pp']))}
    kv = np.asarray(z['bus_kv'])
    net, bus_of, _ = build_island_net(island, built['nodes'], built['edges'], freq, {})
    attach_generators(net, bus_of, built['nodes'], island, attach_mode='cap')
    zone_of_bus = dict(zip(net.bus.index, net.bus.zone))
    for lab in ('pv','nopv'):
        comm = uc[lab]['committed_mw']; tot = uc[lab]['total_mw']
        frac = {}
        for key, series in comm.items():
            t = tot.get(key, 0)
            frac[tuple(key.split('|'))] = (series[12]/t) if t > 0 else 0.0
        # 機械集約(起動率でSをスケール)
        sync = {}
        yg_extra = np.zeros(Y.shape[0], dtype=complex)
        for _, g in net.gen.iterrows():
            cap = float(g.get('max_p_mw') or 0)
            if cap <= 0: continue
            Hm, xd2, is_ibr = classify(g.get('type'), cap)
            if is_ibr: continue
            zone = zone_of_bus.get(int(g['bus']))
            uf = F2UC.get(str(g.get('type') or '').lower())
            f = frac.get((zone, uf), None)
            if f is None: f = 0.7   # UC側に対応クラスが無い場合の既定(開示)
            Se = cap * f
            if Se < 0.5: continue
            b = int(g['bus'])
            if b not in pos: continue
            s = sync.setdefault(b, {'bus':pos[b],'S_mva':0.0,'_HS':0.0,'_invx':0.0,'P_mw':0.0})
            s['S_mva'] += Se; s['_HS'] += Hm*Se; s['_invx'] += Se/max(xd2,1e-3)
        agg = {'sync':[{'bus':s['bus'],'S_mva':s['S_mva'],'H_mb':s['_HS']/s['S_mva'],
                        'xd2':s['S_mva']/s['_invx'],'P_mw':0.0} for s in sync.values()],
               'ibr':{}, 'stats':{}}
        freqs, M, K, syncL = build_classical_model(Y, agg, base, freq)
        # S_sc(正午の起動機のみ寄与)
        ygv = np.zeros(Y.shape[0], dtype=complex)
        for s in agg['sync']:
            ygv[s['bus']] += 1.0/(1j*s['xd2']*base/s['S_mva'])
        Yp = (Y + sp.diags(ygv)).tocsc()
        dg = np.abs(Yp.diagonal()); 
        if (dg<1e-9).any(): Yp = (Yp + sp.diags(np.where(dg<1e-9,1e-6j,0))).tocsc()
        lu = splu(Yp); n = Y.shape[0]
        diag = np.empty(n, dtype=complex)
        B = 512
        for s0 in range(0,n,B):
            e0 = min(s0+B,n); rhs = np.zeros((n,e0-s0),dtype=complex)
            rhs[np.arange(s0,e0),np.arange(e0-s0)] = 1.0
            X = lu.solve(rhs); diag[s0:e0] = X[np.arange(s0,e0),np.arange(e0-s0)]
        za = np.abs(diag); ssc = base/np.where(za>0,za,np.inf); ssc[za>1e4]=np.nan
        m66 = (kv>=60)&(kv<=80)&~np.isnan(ssc)
        res[(island,lab)] = dict(
            f_min=float(freqs.min()) if len(freqs) else None,
            n_sync=len(agg['sync']),
            S_on=round(sum(s['S_mva'] for s in agg['sync'])),
            ssc66_med=float(np.nanmedian(ssc[m66])))
        r = res[(island,lab)]
        print(f"{island}/{lab}: 起動同期 {r['S_on']}MVA/{r['n_sync']}バス f_min={r['f_min']:.3f}Hz Ssc66中央値={r['ssc66_med']:.0f}MVA")

json.dump({'curves':{f'{a}_{b}':list(map(float,v)) for (a,b),v in curves.items()},
           'noon':{f'{a}_{b}':v for (a,b),v in res.items()}},
          open(f'{S}/pv_dynamics_compare.json','w'), indent=1)
print('saved pv_dynamics_compare.json')
