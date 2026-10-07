"""柵外の節点の読み方(any / enters / station)で線路の端の変電所がどう変わるかを、公表の線区間の端で採点する。"""
import csv, json, pickle, re, sys, unicodedata
from collections import defaultdict, Counter
from pathlib import Path
sys.path.insert(0, '.')
import src.stations.core as core
from src.stations.extract_pbf import read_sites
pbf = Path('data/osm_pbf/japan-power.osm.pbf')
sites = read_sites(pbf)
got = pickle.load(open('data/stations/read_cache.pkl', 'rb'))
names = {core.key_of(f['properties']['osm_type'], f['properties']['osm_id']): (f['properties'].get('name') or '') for f in sites}
tags = {f'w{f["properties"]["osm_id"]}': f['properties'] for f in got['lines']}

def stem(s):
    s = unicodedata.normalize('NFKC', s or ''); s = re.sub(r'\(.*?\)|（.*?）', '', s); s = re.sub(r'\s+', '', s)
    return re.sub(r'(変電所|開閉所|発電所|変換所|変)$', '', s)

def lstem(s):
    s = unicodedata.normalize('NFKC', s or ''); s = re.sub(r'\(.*?\)|（.*?）', '', s); s = re.sub(r'\s+', '', s)
    s = re.sub(r'[0-9・･]+L$', '', s); return re.sub(r'(線|幹線|支線)$', '', s)

obs = defaultdict(set)
for r in csv.DictReader(open('data/external/system_disclosure/normalized/line_observations.csv')):
    for st in (r['from_node'], r['to_node']):
        if stem(st): obs[lstem(r['name'])].add(stem(st))

def ends(mode):
    core.BUFFER_PORTALS = mode
    d = core.model(sites, got['lines'], got['elements'], extension_m=100)
    out = defaultdict(set)
    for e in d['equipment']:
        if e['kind'] == 'line':
            for s in e.get('end_sites') or ():
                if s: out[e['osm_id']].add(s)
        elif e['kind'] == 'internal' and e.get('conductor_rule') == 'inside_one_footprint' and e['site']:
            out[e['osm_id']].add(e['site'])
    return out

R = {m: ends(m) for m in ('station', 'enters', 'any')}
for m in ('enters', 'any'):
    A, B = R[m], R['station']
    sc = Counter()
    for w in set(A) | set(B):
        extra = A.get(w, set()) - B.get(w, set())
        if not extra:
            continue
        ln = lstem(tags.get(w, {}).get('name'))
        if not ln or ln not in obs:
            sc['extra_no_official_line'] += len(extra); continue
        good = sum(1 for x in extra if stem(names.get(x, '')) in obs[ln])
        sc['extra_official'] += good; sc['extra_not_official'] += len(extra) - good
    print(m, 'vs station:', dict(sc))
