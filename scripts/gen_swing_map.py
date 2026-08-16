#!/usr/bin/env python3
"""運転点込みモーダル: 収束ACのV∠δから機械内部電圧E∠δを構成し、
K_ij=E_iE_j(B_ij cosδij − G_ij sinδij) で最低inter-areaモードの形を地図化。"""
import json, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid')
import numpy as np, scipy.sparse as sp
from scipy.sparse.linalg import splu

from scripts.run_full_powerflow_from_db import (build_island_net, attach_generators,
    allocate_loads, add_per_component_slacks, balance_by_zone, solve_island)
from src.powerflow.load_estimator import load_demand_config
from src.powerflow.pipeline import add_reactive_compensation
from src.powerflow.pref_demand import pref_zone_gwh
from scripts.gen_ybus_numeric import load_ybus_npz  # noqa: E402
from src.dynamics.machine_agg import aggregate_machines

ROOT = '/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid'
S = 'docs/reports/figs'

built = json.load(open(f'{ROOT}/docs/data/built/all.json'))
cfg = load_demand_config()
results = {}
for island, freq in (('east',50), ('west',60)):
    z = np.load(f'{ROOT}/dist/ybus/{island}.npz', allow_pickle=True)
    Y, base, _z = load_ybus_npz(f'{ROOT}/dist/ybus/{island}.npz')
    Y = Y.tocsc()
    n = Y.shape[0]
    bus_pp = np.asarray(z['bus_pp'])
    pos = {int(b): i for i, b in enumerate(bus_pp)}
    lat, lon = np.asarray(z['bus_lat']), np.asarray(z['bus_lon'])

    net, bus_of, _ = build_island_net(island, built['nodes'], built['edges'], freq, {})
    attach_generators(net, bus_of, built['nodes'], island, attach_mode='cap')  # 本番既定=介入#24採用済
    allocate_loads(net, cfg, pref_gwh=pref_zone_gwh(built['nodes'])[0])   # 本番既定=#19県別配分ON(罠3)
    add_reactive_compensation(net, factor=cfg.get('reactive_compensation_factor', 0.8))  # 本番既定0.8(介入#20再較正)
    add_per_component_slacks(net)
    balance_by_zone(net, cfg, use_zone_src=True)   # 本番既定=介入#26 ON
    _, dc, net_ac, ac = solve_island(net, 20000)
    assert ac.get('converged') if hasattr(ac,'get') else ac, f'{island}: AC非収束'
    vm = net_ac.res_bus.vm_pu.values
    va = np.deg2rad(net_ac.res_bus.va_degree.values)

    agg = aggregate_machines(net_ac)
    # 機械ごとのP,Q(バス集約・res_gen)
    pg = net_ac.res_gen.groupby(net_ac.gen.bus).p_mw.sum() if len(net_ac.gen) else {}
    qg = net_ac.res_gen.groupby(net_ac.gen.bus).q_mvar.sum() if len(net_ac.gen) else {}
    sync = []
    for s in agg['sync']:
        if s['bus'] not in pos: continue
        b = s['bus']
        if b >= len(vm) or not np.isfinite(vm[b]) or not np.isfinite(va[b]):
            continue          # 非通電バス(vm=NaN)の機械は運転点が無い→除外
        sync.append(dict(s))
    m = len(sync)
    yg = np.zeros(m, dtype=complex)
    E = np.zeros(m, dtype=complex)
    for k, s in enumerate(sync):
        b_net = s['bus']; i = pos[b_net]
        xd2s = s['xd2'] * base / s['S_mva']
        yg[k] = 1.0 / (1j * xd2s)
        V = (vm[b_net] if b_net < len(vm) else 1.0) * np.exp(1j * (va[b_net] if b_net < len(va) else 0))
        P = float(pg.get(b_net, s['P_mw'])) / base
        Q = float(qg.get(b_net, 0.0)) / base
        I = np.conj((P + 1j * Q) / V) if abs(V) > 0.1 else 0
        E[k] = V + 1j * xd2s * I
        s['ybus_i'] = i
    buses = np.array([pos[s['bus']] for s in sync])
    add = np.zeros(n, dtype=complex)
    for k, i in enumerate(buses):
        add[i] += yg[k]
    Y_ll = (Y + sp.diags(add)).tocsc()
    dgm = np.abs(Y_ll.diagonal())
    if (dgm < 1e-9).any():
        Y_ll = (Y_ll + sp.diags(np.where(dgm < 1e-9, 1e-6j, 0))).tocsc()
    Y_gl = sp.csr_matrix((-yg, (np.arange(m), buses)), shape=(m, n)).tocsc()
    lu = splu(Y_ll)
    X = lu.solve(Y_gl.T.toarray())
    Y_red = np.diag(yg) - (Y_gl @ X)

    Em, dl = np.abs(E), np.angle(E)
    G, B = Y_red.real, Y_red.imag
    K = np.zeros((m, m))
    for i in range(m):
        for j in range(m):
            if i == j: continue
            dij = dl[i] - dl[j]
            K[i, j] = -(Em[i]*Em[j]*(B[i,j]*np.cos(dij) - G[i,j]*np.sin(dij)))
    np.fill_diagonal(K, -K.sum(axis=1))
    omega_s = 2*np.pi*freq
    M = np.array([2.0*(s['H_mb']*s['S_mva']/base)/omega_s for s in sync])
    A = np.diag(1.0/M) @ K
    A = np.nan_to_num(A, nan=0.0, posinf=0.0, neginf=0.0)
    lam, vec = np.linalg.eig(A)
    order = np.argsort(np.real(lam))
    lam, vec = np.real(lam[order]), np.real(vec[:, order])
    pos_l = lam[lam > 1e-8]
    freqs = np.sqrt(pos_l)/(2*np.pi)
    # 最低振動モード(ゼロモード=剛体回転を除く最初)
    k0 = int(np.argmax(lam > 1e-8))
    shape = vec[:, k0]
    # M重み正規化
    shape = shape/np.max(np.abs(shape))
    results[island] = dict(
        f0=float(np.sqrt(lam[k0])/(2*np.pi)),
        lats=[float(lat[s['ybus_i']]) for s in sync],
        lons=[float(lon[s['ybus_i']]) for s in sync],
        S=[float(s['S_mva']) for s in sync],
        shape=[float(x) for x in shape])
    print(f"{island}: 運転点込み 最低モード {results[island]['f0']:.3f}Hz (機械{m})、"
          f"モード数{len(freqs)} 帯{freqs.min():.2f}-{freqs.max():.2f}Hz")

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
matplotlib.rcParams['font.family'] = ['Hiragino Sans', 'sans-serif']
fig, ax = plt.subplots(figsize=(12, 13), dpi=150)
# 背景: 本系統
for e in built['edges']:
    if not e.get('main'): continue
    p = e.get('path') or [e['a'], e['b']]
    ax.plot([q[1] for q in p], [q[0] for q in p], color='#dce2e6', lw=0.3, zorder=0)
for island, r in results.items():
    sh = np.array(r['shape']); Smva = np.array(r['S'])
    sc = ax.scatter(r['lons'], r['lats'], c=sh, cmap='coolwarm', vmin=-1, vmax=1,
                    s=8 + np.sqrt(Smva)*1.2, edgecolor='k', linewidths=0.2, zorder=3)
    # 島ラベル
fig.colorbar(sc, ax=ax, shrink=0.55, label='最低inter-areaモードの形(正規化・赤⇔青が逆位相)')
ax.set_xlim(129, 146); ax.set_ylim(30, 45.8)
ax.set_aspect(1/0.80); ax.grid(alpha=0.2, lw=0.3)
ax.set_title(f"長軸(inter-area)振動の地理 — 運転点込み古典モデル\n"
             f"east 最低{results['east']['f0']:.2f}Hz / west 最低{results['west']['f0']:.2f}Hz"
             f" (点=同期機バス・大きさ=容量・色=モード形=揺れの向き)", fontsize=12)
fig.tight_layout()
fig.savefig(f'{S}/fig_swing_map.png', bbox_inches='tight')
print('saved fig_swing_map.png')
json.dump({k: dict(f0=v['f0']) for k, v in results.items()},
          open(f'{ROOT}/docs/reports/swing_interarea_2026-08-17.json','w'), indent=1)
