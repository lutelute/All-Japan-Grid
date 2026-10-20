#!/usr/bin/env python3
"""Scientific figures/animations for the story revision, from pinned model data."""
from pathlib import Path
import json
import hashlib
import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.screen_false_fragments import build_island_graph,k5,hav_km

OUT=ROOT/'docs/slides/ajg/revised/assets'
OUT.mkdir(parents=True,exist_ok=True)
plt.rcParams.update({'font.family':['Hiragino Sans','sans-serif'], 'axes.unicode_minus':False,
                     'font.size':16, 'axes.spines.top':False,'axes.spines.right':False})
INK='#132A3E';MUT='#536779';RED='#C73C43';BLUE='#1D8395';BG='#FFFFFF'
D=json.loads((ROOT/'docs/data/built/all.json').read_text())
R=json.loads((ROOT/'docs/reports/codex_connection_audit_2026-09-12/connections.json').read_text())


def frame(fig):
    fig.canvas.draw()
    im=Image.fromarray(np.asarray(fig.canvas.buffer_rgba())[:,:,:3].copy())
    plt.close(fig)
    return im


def local_network(ax,bbox,highlight=None):
    x0,x1,y0,y1=bbox
    bg=[];fg=[]
    for e in D['edges']:
        p=e.get('path') or [e['a'],e['b']]
        if not any(x0<=c[1]<=x1 and y0<=c[0]<=y1 for c in p):continue
        line=[[c[1],c[0]] for c in p]
        (fg if highlight and k5(*e['a']) in highlight and k5(*e['b']) in highlight else bg).append(line)
    ax.add_collection(LineCollection(bg,colors='#CBD5DB',linewidths=.8))
    if fg:ax.add_collection(LineCollection(fg,colors=RED,linewidths=2.3))
    ax.set_xlim(x0,x1);ax.set_ylim(y0,y1)
    ax.set_aspect(1/np.cos(np.radians((y0+y1)/2)))
    ax.set_xlabel('経度 [°]');ax.set_ylabel('緯度 [°]')
    ax.tick_params(labelsize=12)


keys,comps=build_island_graph(D['nodes'],D['edges'],'east')
case=next(r for r in R['near_candidates'] if r['fragment']['name']=='秩父変電所')
comp=comps[case['component']]
frames=[]
for phase in (0,1,2,3):
    fig=plt.figure(figsize=(11.2,5.8),dpi=120,facecolor=BG)
    if phase<2:
        ax=fig.add_axes([.08,.15,.63,.73]);local_network(ax,(138.78,139.16,35.91,36.10),comp)
        pts=np.array(sorted(comp));ax.scatter(pts[:,1],pts[:,0],color=RED,s=24,zorder=5)
        for name,offset in [('秩父変電所',(8,6)),('横瀬変電所',(8,-18)),('武州中川変電所',(-50,-25))]:
            n=next(keys[k] for k in comp if keys[k]['name']==name)
            ax.annotate(name,(n['lon'],n['lat']),xytext=offset,textcoords='offset points',fontsize=12,color=INK)
        fig.text(.75,.68,'既存枝でつながる\n12ノードの断片',color=RED,fontsize=19,linespacing=1.6)
        fig.text(.75,.42,'赤：この断片\n灰：周囲の既存枝',color=MUT,fontsize=16,linespacing=1.8)
        if phase==1:fig.text(.75,.19,'本系統の同名設備を\n次に拡大する',color=INK,fontsize=17,linespacing=1.7)
    else:
        ax=fig.add_axes([.08,.15,.63,.73]);a,b=case['fragment'],case['main'];x,y=a['lon'],a['lat']
        local_network(ax,(x-.0024,x+.0024,y-.0017,y+.0017),comp)
        ax.scatter([a['lon'],b['lon']],[a['lat'],b['lat']],c=[RED,BLUE],s=110,zorder=5)
        ax.annotate('断片側 66 kV',(a['lon'],a['lat']),xytext=(25,-50),textcoords='offset points',fontsize=15,color=RED,
                    arrowprops=dict(arrowstyle='-',color=RED,lw=1.2,shrinkB=8))
        ax.annotate('本系統側 66 kV',(b['lon'],b['lat']),xytext=(-160,40),textcoords='offset points',fontsize=15,color=BLUE,
                    arrowprops=dict(arrowstyle='-',color=BLUE,lw=1.2,shrinkB=8))
        ax.ticklabel_format(useOffset=False,style='plain')
        fig.text(.75,.68,f"同名の2点\n距離 {case['distance_m']:.1f} m",color=INK,fontsize=22,linespacing=1.7)
        fig.text(.75,.35,'同一設備の重複か、\n別母線かを確認する',color=MUT,fontsize=17,linespacing=1.8)
        if phase==3:fig.text(.75,.13,'接続は未変更',color=RED,fontsize=19)
    frames.append(frame(fig))
frames[0].save(OUT/'chichibu_review.gif',save_all=True,append_images=frames[1:],duration=[2600,2200,3400,3800],loop=0)
frames[-1].save(OUT/'chichibu_detail.png')
frames[0].save(OUT/'chichibu_overview.png')

# Tie coordinates are model observations. The green dashed chord indicates the
# endpoints documented by the utility, and is explicitly not the actual route.
def find(name):
    return next(n for n in D['nodes'] if n['name']==name and n['kv']==500)
a=find('東山口変電所 (Higashi Yamaguchi Hendensho) 500kV')
b=find('讃岐変電所 500kV');c=find('東岡山変電所 500kV')
fig=plt.figure(figsize=(11.2,5.8),dpi=120,facecolor=BG);ax=fig.add_axes([.08,.16,.86,.73])
local_network(ax,(131.55,134.6,33.7,35.25))
ax.set_xlabel('')  # Keep the endpoint-distance caption clear of the axis label.
ax.plot([a['lon'],b['lon']],[a['lat'],b['lat']],color=RED,lw=3,label='現行 tie の直線')
ax.plot([c['lon'],b['lon']],[c['lat'],b['lat']],color=BLUE,lw=3,ls='--',label='公開図の端点同士（実経路ではない）')
for n,label,offset in [(a,'東山口',(-26,18)),(b,'讃岐',(15,-20)),(c,'東岡山',(12,12))]:
    ax.scatter(n['lon'],n['lat'],s=80,color=INK,zorder=5);ax.annotate(label,(n['lon'],n['lat']),xytext=offset,textcoords='offset points',fontsize=18,color=INK)
ax.legend(loc='upper left',fontsize=13,frameon=False)
fig.text(.30,.08,'現行の合成枝：端点間 195.7 km',color=RED,fontsize=18)
frame(fig).save(OUT/'honshi_endpoint_audit.png')

# Fresh recovery animation from the same named trace used by the original deck.
p=ROOT/'docs/data/agc/mm_traces_east_n3pk.npz'
z=np.load(p,allow_pickle=True);t=z['t'];w=z['w'];M=z['M'];f0=float(z['f0'])
ok=np.isfinite(w);weighted=np.where(ok,w*M[:,None],0).sum(axis=0)
coi=f0+f0*weighted/np.where(ok,M[:,None],0).sum(axis=0)
samples=np.unique(np.concatenate([np.arange(0,11),np.arange(15,61,5),np.arange(90,float(t[-1])+1,30),[float(t[-1])]]))
freqframes=[]
for end in samples:
    fig=plt.figure(figsize=(11.2,5.4),dpi=120,facecolor=BG);ax=fig.add_axes([.1,.18,.84,.67])
    ax.plot(t,coi,color='#DCE4E9',lw=2)
    idx=int(np.searchsorted(t,end));idx=min(idx,len(t)-1)
    ax.plot(t[:idx+1],coi[:idx+1],color=BLUE,lw=3)
    ax.scatter(t[idx],coi[idx],s=50,color=RED,zorder=5)
    ax.axhline(50,color=MUT,lw=1,ls='--');ax.set_xlim(0,float(t[-1]));ax.set_ylim(48.3,50.12)
    ax.set_xlabel('シミュレーション時間 [s]（脱落 t = 1 s）',fontsize=15)
    ax.set_ylabel('慣性重み付き平均周波数 [Hz]',fontsize=15)
    ax.tick_params(labelsize=13);ax.grid(axis='y',alpha=.15)
    label='事故前' if end<1 else ('周波数が急低下' if end<8 else ('急低下後の回復' if end<60 else ('回復が緩やかになる' if end<180 else '50 Hzへ近づくが、未復帰')))
    fig.text(.1,.93,label,color=INK,fontsize=22,weight='bold')
    fig.text(.94,.93,f'{end:.0f} s   {coi[idx]:.2f} Hz',ha='right',color=BLUE,fontsize=20)
    freqframes.append(frame(fig))
freqframes[0].save(OUT/'east_frequency_explained.gif',save_all=True,append_images=freqframes[1:],duration=[800]+[170]*(len(freqframes)-2)+[4000],loop=0)
freqframes[-1].save(OUT/'east_frequency_final.png')
sample_idx=np.unique(np.r_[np.arange(0,min(1200,len(t)),10),np.arange(1200,len(t),300),len(t)-1])
summary={'source':str(p.relative_to(ROOT)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
 't_end':float(t[-1]),'nadir_hz':float(np.nanmin(coi)),'end_hz':float(coi[-1]),
 'nadir_t':float(t[np.nanargmin(coi)]),'sixty_hz':float(coi[np.searchsorted(t,60)]),
 't':t[sample_idx].tolist(),'f':coi[sample_idx].tolist()}
(OUT/'frequency_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in summary.items() if k not in ('t','f')},ensure_ascii=False))
print(OUT)
