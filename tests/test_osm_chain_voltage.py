"""Exercise the second-wave CLI against tiny local source data."""
import json
import pytest
from scripts import hunt_fragment_osm_chains as chain


@pytest.mark.parametrize('last_kv, expected', [(154, 0), (66, 1)])
def test_second_wave_unknown_start_cannot_bridge_voltage_classes(tmp_path, monkeypatch, last_kv, expected):
    lat, lon = 35., 137.
    dx = 1/(111*.8192)
    def node(name, la, lo, kv, region):
        return dict(id=name,name=name,lat=la,lon=lo,kv=kv,region=region,sub=1)
    a=node('A',lat,lon,last_kv,'chubu')
    b=node('B',lat+.01,lon,last_kv,'chubu')
    c=node('C',lat+.02,lon,last_kv,'chubu')
    f=node('F',lat,lon+2*dx,0,'chubu')
    nodes=[a,b,c,f]+[node(isl,40+i,140,66,isl) for i,isl in enumerate(('hokkaido','tokyo','okinawa'))]
    edges=[dict(a=[x['lat'],x['lon']],b=[y['lat'],y['lon']]) for x,y in ((a,b),(b,c))]
    def way(points,kv):
        return dict(geometry=dict(type='LineString',coordinates=[[y,x] for x,y in points]),
                    properties={'_voltage_kv':kv,'_display_name':str(kv)})
    ways=[way([(lat,lon+2*dx),(lat,lon+dx)],66),way([(lat,lon+.97*dx),(lat,lon)],last_kv)]
    (tmp_path/'docs/data/built').mkdir(parents=True)
    (tmp_path/'docs/data/fragments').mkdir()
    source=tmp_path/'docs/data/built/all.json'
    original=json.dumps(dict(nodes=nodes,edges=edges))
    source.write_text(original)
    (tmp_path/'docs/data/lines_all.geojson').write_text(json.dumps(dict(features=ways)))
    monkeypatch.setattr(chain,'ROOT',tmp_path)
    monkeypatch.setattr('sys.argv',['hunt_fragment_osm_chains.py'])
    assert chain.main()==0
    result=json.loads((tmp_path/'docs/data/fragments/evidence_chains.json').read_text())
    assert result['summary']['west']==expected
    assert source.read_text()==original
