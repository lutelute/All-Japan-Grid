#!/usr/bin/env python3
"""系統強度(短絡容量)マップ — IBR安定性検討のPhase 0(オーナー指示2026-08-17「実施」)。

動的検討ロードマップ: Phase0=本マップ → Phase1=ZIP負荷+実R/XでZ(jω) → Phase2=GFL/GFMナイキスト → Phase3=RMS動的。 — 数値Ybus+機械典型値(xd''=0.2pu)でZthを全バス計算。
本番のbuild_island_net(罠3)で発電機バスを取得し、Ybusはgen_ybus_numericの出荷npzを使う。"""
import json, sys, time
sys.path.insert(0, '/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid')
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import splu

from scripts.run_full_powerflow_from_db import build_island_net, attach_generators
from scripts.gen_ybus_numeric import ISLANDS, load_ybus_npz

ROOT = '/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid'
S = 'docs/reports/figs'
XD2 = 0.2      # 機械次過渡リアクタンス典型値(pu, 機械ベース)

built = json.load(open(f'{ROOT}/docs/data/built/all.json'))
nodes, edges = built['nodes'], built['edges']

out = {}
for island, freq in ISLANDS:
    t0 = time.time()
    z = np.load(f'{ROOT}/dist/ybus/{island}.npz', allow_pickle=True)
    Y, base, _z = load_ybus_npz(f'{ROOT}/dist/ybus/{island}.npz' if isinstance(island,str) else island)
    Y = Y.tocsc()
    n = Y.shape[0]
    bus_pp = np.asarray(z['bus_pp'])
    lat, lon, kv = np.asarray(z['bus_lat']), np.asarray(z['bus_lon']), np.asarray(z['bus_kv'])

    net, bus_of, _ = build_island_net(island, nodes, edges, freq, {})
    attach_generators(net, bus_of, nodes, island)   # 本番の発電機注入(介入#24既定)
    assert len(net.bus) >= n, f"{island}: net{len(net.bus)} < ybus{n}"
    pp2y = {int(p): i for i, p in enumerate(bus_pp)}

    yg = np.zeros(n, dtype=complex)
    n_mach = 0
    for tbl in ('gen', 'sgen', 'ext_grid'):
        df = getattr(net, tbl)
        if df is None or len(df) == 0:
            continue
        for _, r in df.iterrows():
            b = pp2y.get(int(r['bus']))
            if b is None:
                continue
            smva = None
            for c in ('sn_mva', 'max_p_mw', 'p_mw'):
                if c in df.columns and r.get(c) and r.get(c) == r.get(c) and r.get(c) > 0:
                    smva = float(r[c]); break
            if not smva:
                smva = 10.0
            yg[b] += 1.0 / (1j * XD2 * base / smva)   # 系統ベースpuのアドミタンス
            n_mach += 1
    Yp = (Y + sp.diags(yg)).tocsc()
    # 非連結成分のゼロ行対策: ゼロ対角へ微小シャント(結果はNaN化して除外)
    dg = np.abs(Yp.diagonal())
    fix = dg < 1e-9
    if fix.any():
        Yp = (Yp + sp.diags(np.where(fix, 1e-6j, 0))).tocsc()

    lu = splu(Yp)
    diag = np.empty(n, dtype=complex)
    B = 512
    for s0 in range(0, n, B):
        e0 = min(s0 + B, n)
        rhs = np.zeros((n, e0 - s0), dtype=complex)
        rhs[np.arange(s0, e0), np.arange(e0 - s0)] = 1.0
        X = lu.solve(rhs)
        diag[s0:e0] = X[np.arange(s0, e0), np.arange(e0 - s0)]
    zabs = np.abs(diag)
    ssc = base / np.where(zabs > 0, zabs, np.inf)   # MVA (V=1pu 三相)
    ssc[zabs > 1e4] = np.nan                        # 非連結(正則化痕)は除外

    out[island] = dict(lat=lat, lon=lon, kv=kv, ssc=ssc)
    med66 = np.nanmedian(ssc[(kv >= 60) & (kv <= 80)]) if ((kv >= 60) & (kv <= 80)).any() else float('nan')
    print(f"{island}: n={n} machines={n_mach} 非連結{int(np.isnan(ssc).sum())} S_sc median={np.nanmedian(ssc):.0f}MVA "
          f"(66-77kV帯 {med66:.0f}MVA) min={np.nanmin(ssc):.1f} max={np.nanmax(ssc):.0f} [{time.time()-t0:.0f}s]")

np.savez(f'{S}/scr_map_data.npz', **{f"{k}_{f}": v for k, d in out.items() for f, v in d.items()})

# ---- 地図 ----
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
matplotlib.rcParams['font.family'] = ['Hiragino Sans', 'sans-serif']
fig, ax = plt.subplots(figsize=(12.5, 13.5), dpi=150)
allv = np.concatenate([d['ssc'][~np.isnan(d['ssc'])] for d in out.values()])
vmin, vmax = np.percentile(allv, 2), np.percentile(allv, 98)
for island, d in out.items():
    m = d['kv'] >= 60
    scq = ax.scatter(d['lon'][m], d['lat'][m], c=np.clip(d['ssc'][m], vmin, vmax),
                     s=4, cmap='RdYlGn', norm=LogNorm(vmin=vmin, vmax=vmax),
                     linewidths=0, alpha=0.85)
cb = fig.colorbar(scq, ax=ax, shrink=0.6, label='短絡容量 S_sc [MVA] (log)')
ax.set_xlim(127, 146); ax.set_ylim(26, 45.8)
ax.set_aspect(1 / 0.80)
ax.grid(alpha=0.2, lw=0.3)
ax.set_title('系統強度マップ(Phase 0) — 全バスのテブナン短絡容量\n'
             'Ybus(正典・par合成済)+機械典型値xd″=0.2pu。緑=強い/赤=弱い系統(IBR連系リスク帯)',
             fontsize=12)
fig.tight_layout()
fig.savefig(f'{S}/fig_scr_map.png', bbox_inches='tight')
print('saved fig_scr_map.png')

# 弱点リスト(66kV+で最弱20)
rows = []
for island, d in out.items():
    m = (d['kv'] >= 60) & ~np.isnan(d['ssc'])
    for la, lo, k, s2 in zip(d['lat'][m], d['lon'][m], d['kv'][m], d['ssc'][m]):
        rows.append((island, k, s2, la, lo))
rows.sort(key=lambda r: r[2])
print('\n== 最弱バス(≥66kV) top12 ==')
for r in rows[:12]:
    print(f"  {r[0]:8} {r[1]:.0f}kV S_sc={r[2]:.1f}MVA ({r[3]:.4f},{r[4]:.4f})")
