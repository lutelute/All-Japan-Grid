#!/usr/bin/env python3
"""Cache public GSI photo tiles for the bounded same-site visual review.

Coordinates use Web Mercator, matching the HTML overlay exactly. Images remain
unmodified; saved URLs and hashes make the reviewed background inspectable.
"""
import concurrent.futures
import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'docs/reports/codex_same_site_trial_2026-09-13'
CIRCUMFERENCE = 40075016.68557849


def mercator(lat, lon):
    return ((lon+180)/360, (1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2)


def main():
    report = json.loads((OUT/'trial.json').read_text())
    frames, requests = {}, {}
    for case in report['candidates']:
        a, b = case['fragment'], case['main']
        lat, lon = (a['lat']+b['lat'])/2, (a['lon']+b['lon'])/2
        cx, cy = mercator(lat, lon)
        ground = CIRCUMFERENCE*math.cos(math.radians(lat))
        frames[case['case_id']] = {}
        for zoom in [.5, 1, 3, 12]:
            extent = max(220, case['distance_m']*1.2)*zoom
            k = 410/(2*extent)
            # Aim at native photo resolution, capped at the provider's z18.
            z = min(18, max(14, math.ceil(math.log2(ground*k/256))))
            n = 2**z
            xs = range(math.floor((cx-310/(ground*k))*n), math.floor((cx+310/(ground*k))*n)+1)
            ys = range(math.floor((cy-230/(ground*k))*n), math.floor((cy+230/(ground*k))*n)+1)
            tiles = []
            for x in xs:
                for y in ys:
                    key = f'{z}/{x}/{y}'
                    tiles.append(dict(key=key, x=310+(x/n-cx)*ground*k,
                                      y=230+(y/n-cy)*ground*k, size=ground*k/n))
                    requests[key] = dict(url=f'https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{key}.jpg',
                                         path=f'basemap/{z}_{x}_{y}.jpg')
            frames[case['case_id']][str(zoom)] = dict(z=z, center=[lat, lon], tiles=tiles)
    (OUT/'basemap').mkdir(exist_ok=True)

    def fetch(item):
        key, rec = item
        path = OUT/rec['path']
        if not path.exists():
            result = subprocess.run(['curl', '-sS', '--fail', '--retry', '2', '--max-time', '30',
                                     rec['url'], '-o', str(path)], capture_output=True, text=True)
            if result.returncode:
                return key, dict(rec, available=False, error=result.stderr.strip())
        data = path.read_bytes()
        assert data[:2] == b'\xff\xd8', rec['url']
        return key, dict(rec, available=True, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))

    print(f'Fetching {len(requests)} bounded GSI photo tiles with 4 workers.', flush=True)
    records = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for key, rec in pool.map(fetch, requests.items()):
            records[key] = rec
    result = dict(source='国土地理院 全国最新写真（シームレス）',
                  source_url='https://maps.gsi.go.jp/development/ichiran.html',
                  photo_description_url='https://maps.gsi.go.jp/legend/seamlessphoto.pdf',
                  accessed_at=datetime.now(timezone.utc).isoformat(),
                  date_note='取得日と撮影日は異なる。地点別撮影年月は未確認。画像のない範囲は明示し、補完しない。',
                  source_sha256=report['source_sha256'], frames=frames, tiles=records)
    # Provider's photography-date layer uses native z11 GeoJSON polygons.
    from shapely.geometry import Point, shape
    spec_cache, dates = {}, {}
    for case in report['candidates']:
        dates[case['case_id']] = {}
        points = dict(A=[case['fragment']['lat'], case['fragment']['lon']],
                      B=[case['main']['lat'], case['main']['lon']])
        for label, point in points.items():
            x, y = (int(v*2048) for v in mercator(*point))
            key = f'11/{x}/{y}'
            if key not in spec_cache:
                path = OUT/f'basemap/spec_11_{x}_{y}.geojson'
                url = f'https://maps.gsi.go.jp/xyz/seamlessphoto_spec/{key}.geojson'
                if not path.exists():
                    got = subprocess.run(['curl', '-sS', '--fail', '--retry', '2', '--max-time', '30',
                                          url, '-o', str(path)], capture_output=True, text=True)
                    if got.returncode:
                        spec_cache[key] = dict(url=url, error=got.stderr.strip())
                        continue
                spec_cache[key] = dict(url=url, path=str(path.relative_to(OUT)),
                                       sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                       features=json.loads(path.read_text())['features'])
            rec = spec_cache[key]
            matched = [f['properties'] for f in rec.get('features', [])
                       if shape(f['geometry']).covers(Point(point[1], point[0]))]
            dates[case['case_id']][label] = dict(coordinate=point, source_url=rec['url'],
                observations=[{k:v for k,v in props.items() if not k.startswith('_')} for props in matched])
    result['photography_dates'] = dates
    result['date_sources'] = {k:{a:b for a,b in v.items() if a != 'features'} for k,v in spec_cache.items()}
    result['date_note'] = '取得日と撮影日は異なる。A/B地点の撮影年月は地理院の撮影期間レイヤと照合。表示範囲内のモザイク境界・地点別の精度には留意。'
    (OUT/'basemap_manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(tiles=len(records), unavailable=sum(not r['available'] for r in records.values()),
                         bytes=sum(r.get('bytes', 0) for r in records.values()))), flush=True)


if __name__ == '__main__':
    main()
