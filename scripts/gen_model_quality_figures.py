#!/usr/bin/env python3
"""Pair the observed geography with the circuit assumption it produces."""
import json
import math
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.patches import Circle

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/reports/codex_model_quality_2026-09-12'
DATA=json.loads((ROOT/'docs/data/built/all.json').read_text())
R=json.loads((OUT/'circuit_east.json').read_text())
case=next(c for c in R['transformers_without_site_witness'] if len(c['origins'])==2
          and {n['kv'] for n in c['origins']}=={154,66})
lat,lon=case['origins'][0]['lat'],case['origins'][0]['lon']
plt.rcParams.update({'font.family':['Hiragino Sans','sans-serif'],'font.size':15,
                     'axes.unicode_minus':False,'axes.spines.top':False,'axes.spines.right':False})
ink='#173348';teal='#147F91';red='#C43C43';mut='#546E7F';orange='#BD761B'
fig=plt.figure(figsize=(13,6.4),dpi=150,facecolor='white')
ax=fig.add_axes([.08,.24,.40,.57]);sc=fig.add_axes([.57,.23,.38,.57])
fig.text(.07,.91,'同じ座標を、変圧器の存在根拠にしていないか',fontsize=25,color=ink,weight='bold')
paths={154:[],66:[],'other':[]}
for e in DATA['edges']:
    p=e.get('path') or [e['a'],e['b']]
    if not any(abs(x[0]-lat)<.018 and abs(x[1]-lon)<.023 for x in p):continue
    cls=e.get('kv');key=cls if cls in (154,66) else 'other'
    paths[key].append([[x[1],x[0]] for x in p])
for kv,color in [('other','#CCD8DF'),(154,teal),(66,red)]:
    ax.add_collection(LineCollection(paths[kv],colors=color,linewidths=1 if kv=='other' else 2.2,
                                     label=f'{kv} kV' if kv!='other' else '周囲の枝'))
ax.scatter([lon],[lat],s=90,facecolors='white',edgecolors=ink,lw=2,zorder=5)
ax.set_xlim(lon-.023,lon+.023);ax.set_ylim(lat-.018,lat+.018)
ax.set_aspect(1/math.cos(math.radians(lat)))
ax.set_xlabel('経度 [°]');ax.set_ylabel('緯度 [°]');ax.tick_params(labelsize=11)
ax.ticklabel_format(useOffset=False,style='plain')
ax.legend(loc='lower left',fontsize=11,frameon=False)
ax.set_title('保存された線形・電圧タグ',fontsize=18,color=ink,pad=15)
sc.set_xlim(0,1);sc.set_ylim(0,1);sc.axis('off')
sc.set_title('この点に生成された計算回路',fontsize=18,color=ink,pad=15)
for y,label,col in [(.8,'154 kV',teal),(.2,'66 kV',red)]:
    sc.plot([.07,.93],[y,y],color=col,lw=3)
    sc.text(.07,y+.045,label,fontsize=20,color=col)
sc.plot([.40,.40],[.8,.58],color=orange,lw=2,ls='--')
sc.plot([.40,.40],[.42,.2],color=orange,lw=2,ls='--')
sc.add_patch(Circle((.40,.55),.07,fill=False,edgecolor=orange,lw=2))
sc.add_patch(Circle((.40,.45),.07,fill=False,edgecolor=orange,lw=2))
sc.text(.57,.53,'変圧器を追加',fontsize=18,color=orange)
sc.text(.57,.43,f"{case['sn_mva']:.0f} MVA（推定）",fontsize=15,color=mut)
fig.text(.08,.09,f'対象座標 {lat:.5f}, {lon:.5f} ／ 両ノードとも junction・変電所登録なし',fontsize=15,color=ink)
fig.text(.08,.035,'実在する変圧器の有無は未確認。図は、保存データとビルダーの仮定を比較したもの。',fontsize=14,color=mut)
fig.savefig(OUT/'coordinate_vs_circuit.png',facecolor='white')
fig.savefig(OUT/'coordinate_vs_circuit.svg',facecolor='white')
# Keep generated path data readable without trailing whitespace in Git diffs.
svg=OUT/'coordinate_vs_circuit.svg'
svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines())+'\n')
plt.close(fig)
print(OUT/'coordinate_vs_circuit.png')
