#!/usr/bin/env python3
"""flow_map配信データの軽量化(数値整数化+実線形パスのRDP簡略化20m許容).
export_flow_map_data/export_day_flows の後に実行(realtime_cycleに組込済)。冪等。"""
import json, glob, os, sys

def rdp(pts, eps):
    if len(pts) < 3: return pts
    ax, ay = pts[0]; bx, by = pts[-1]
    dmax, idx = 0, 0
    dx, dy = bx-ax, by-ay
    L2 = dx*dx+dy*dy or 1e-12
    for i in range(1, len(pts)-1):
        px, py = pts[i]
        t = max(0, min(1, ((px-ax)*dx+(py-ay)*dy)/L2))
        d = ((px-(ax+t*dx))**2+(py-(ay+t*dy))**2)**.5
        if d > dmax: dmax, idx = d, i
    if dmax <= eps: return [pts[0], pts[-1]]
    return rdp(pts[:idx+1], eps)[:-1] + rdp(pts[idx:], eps)

def main():
    sys.setrecursionlimit(10000)
    t0 = t1 = 0
    for fp in (glob.glob('docs/data/flow_map/flows_*.geojson')
               + glob.glob('docs/data/flow_map/days/2*.json')):
        s0 = os.path.getsize(fp)
        d = json.load(open(fp))
        if 'features' in d:
            for f in d['features']:
                pr = f['properties']
                for k in ('p24','ld24'):
                    if pr.get(k):
                        pr[k] = [None if x is None else int(round(x)) for x in pr[k]]
                for k in ('p_mw','loading_pct'):
                    if isinstance(pr.get(k), float): pr[k] = int(round(pr[k]))
                cs = f['geometry']['coordinates']
                if len(cs) > 3:
                    f['geometry']['coordinates'] = [[round(x,5),round(y,5)]
                                                    for x,y in rdp(cs, 0.0002)]
        elif 'islands' in d:
            for isl in d['islands'].values():
                for key in ('p','ld'):
                    isl[key] = [[None if x is None else int(round(x)) for x in r]
                                for r in isl[key]]
        json.dump(d, open(fp,'w'), ensure_ascii=False, separators=(',',':'))
        t0 += s0; t1 += os.path.getsize(fp)
    print(f"slim: {t0//1024}KB → {t1//1024}KB")
    return 0

if __name__ == '__main__':
    sys.exit(main())
