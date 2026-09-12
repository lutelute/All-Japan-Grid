"""Connection audit must separate evidence, coordinate identity and physics."""
from scripts.audit_story_connections import audit
from scripts.connection_voltage import route_voltage_compatible


def n(name,lat,lon,region='tokyo',kv=66,main=False):
    return dict(id=name,name=name,lat=lat,lon=lon,region=region,kv=kv,sub=1,main=main)


def e(a,b,**kwargs):
    return dict(a=[a['lat'],a['lon']],b=[b['lat'],b['lon']],**kwargs)


def test_main_membership_is_not_inherited_from_other_island():
    a=n('east A',35,138);b=n('east B',35.01,138)
    twin=n('west twin',35,138,'chubu',main=True)
    c=n('west C',35.1,138,'chubu');d=n('west D',35.11,138,'chubu')
    out=audit(dict(nodes=[a,b,twin,c,d],edges=[e(a,b),e(c,d)]))
    diff=next(r for r in out['main_disagreements'] if r['id']=='west twin')
    assert diff['recomputed_main'] is False and diff['union_main'] is True


def test_unknown_voltage_candidate_is_never_confirmed_connection():
    a=n('main A',35,138);b=n('main B',35.01,138);f=n('unknown',35,138.0003,kv=0)
    out=audit(dict(nodes=[a,b,f],edges=[e(a,b)]))
    assert out['near_candidates'][0]['voltage_evidence']=='unknown'
    assert out['near_candidates'][0]['status'].startswith('candidate_only')


def test_same_site_voltage_records_are_not_discarded_by_first_record():
    a=n('A500',35,138,kv=500);a66=n('A66',35,138,kv=66)
    b=n('B',35.01,138);f=n('F66',35,138.0003)
    out=audit(dict(nodes=[a,a66,b,f],edges=[e(a,b)]))
    assert out['near_candidates'][0]['voltage_evidence']=='same_observed_class'


def test_reverse_path_is_not_geometry_gap_and_stub_not_error():
    a=n('A',35,138);b=n('B',35.01,138)
    edge=e(a,b,path=[[b['lat'],b['lon']],[a['lat'],a['lon']]])
    stub=e(a,a,name='A intra-substation stub')
    out=audit(dict(nodes=[a,b],edges=[edge,stub]))
    assert out['geometry_gaps']==[]
    assert out['counts']['declared_intra_substation_loops']==1


def test_unknown_cannot_reset_known_route_voltage():
    assert not route_voltage_compatible([None,66,None,154,0])
    assert not route_voltage_compatible([66,77,95])  # no gradual voltage drift
    assert route_voltage_compatible([None,66,0,66])
    assert route_voltage_compatible([None,0])  # still unknown, not physical proof
