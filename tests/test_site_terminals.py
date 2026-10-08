"""Geographic evidence must not silently become electrical connectivity."""
from src.powerflow.site_terminals import endpoint_evidence, project_site_terminals

POLYGON = {'type':'Polygon','coordinates':[[[139,36],[139.001,36],[139.001,36.001],[139,36.001],[139,36]]]}


def test_through_line_keeps_outside_terminal_and_unconfirmed_connectivity():
    edge = dict(a=[36.0005,138.999],b=[36.0005,139.002],
                path=[[36.0005,138.999],[36.0005,139.002]])
    result = endpoint_evidence(edge,'a',POLYGON)
    assert result['geometry_status'] == 'path_crosses_site_end_outside'
    assert result['saved_path_endpoint'] == edge['path'][0]
    assert result['electrical_confirmation'] is False
    assert len(edge['path']) == 2


def test_reversed_path_finds_real_end_in_site():
    edge = dict(a=[36.0005,139.0005],b=[36.01,139.01],
                path=[[36.01,139.01],[36.0005,139.0005]])
    result = endpoint_evidence(edge,'a',POLYGON)
    assert result['geometry_status'] == 'endpoint_in_site'
    assert result['saved_path_endpoint'] == edge['path'][-1]
    assert result['electrical_confirmation'] is False


def test_missing_geometry_never_fabricates_terminal():
    result = endpoint_evidence(dict(a=[36,139],b=[36.01,139.01]),'a',POLYGON)
    assert result['saved_path_endpoint'] is None
    assert result['geometry_status'] == 'no_saved_path'


def test_distinct_voltage_buses_survive_same_display_anchor():
    import pandapower as pp
    net = pp.create_empty_network()
    hv = pp.create_bus(net,vn_kv=154,geodata=(139,36))
    lv = pp.create_bus(net,vn_kv=66,geodata=(139.01,36))
    pp.create_transformer_from_parameters(net,hv,lv,100,154,66,10,.5,0,0)
    original = net.trafo.copy()
    view = dict(electrical_aliases=[],observations={'hv':{'site_id':'way/1'},'lv':{'site_id':'way/1'}},
                sites={'way/1':{'display_anchor':[36.0005,139.0005]}})
    result,_ = project_site_terminals(net,{'hv':hv,'lv':lv},view)
    assert len(result.bus) == 2
    assert result.trafo.equals(original)
    assert result.bus.at[hv,'geo'] == result.bus.at[lv,'geo']
    assert result.bus.at[hv,'vn_kv'] != result.bus.at[lv,'vn_kv']
    assert net.bus.at[hv,'geo'] != result.bus.at[hv,'geo']
