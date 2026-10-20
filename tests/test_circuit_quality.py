"""Circuit checks must expose assumptions without inventing device evidence."""
import copy
import pandapower as pp
from src.validation.circuit_quality import (
    circuit_findings, source_nodes_by_bus, candidate_removal_connectivity,
    structure_voltage_findings, unknown_line_components)


def two_voltage_net():
    net=pp.create_empty_network()
    a=pp.create_bus(net,154); b=pp.create_bus(net,66)
    pp.create_transformer_from_parameters(net,a,b,sn_mva=100,vn_hv_kv=154,vn_lv_kv=66,
        vkr_percent=.5,vk_percent=12,pfe_kw=0,i0_percent=0,name='coordinate ladder')
    return net,{a:[dict(id='j154',sub=0)],b:[dict(id='j66',sub=0)]}


def test_junction_transformer_is_candidate_and_removal_is_read_only():
    net,origins=two_voltage_net()
    before=net.trafo.copy(deep=True)
    result=circuit_findings(net,origins)
    assert result['counts']['transformers_without_site_witness']==1
    change=candidate_removal_connectivity(net,result['transformers_without_site_witness'])
    assert change['before']['components']==1
    assert change['without_candidates']['components']==2
    assert net.trafo.equals(before)


def test_substation_witness_is_not_reported_as_missing():
    net,origins=two_voltage_net()
    origins[0][0]['sub']=1
    assert circuit_findings(net,origins)['transformers_without_site_witness']==[]


def test_absent_provenance_is_not_mislabeled_junction():
    net,origins=two_voltage_net()
    del origins[1]
    out=circuit_findings(net,origins)
    assert out['transformer_source_mapping_missing']==[0]
    assert out['transformers_without_site_witness']==[]


def test_live_line_voltage_mismatch_is_detected_but_inactive_line_excluded():
    net,origins=two_voltage_net()
    li=pp.create_line_from_parameters(net,0,1,length_km=1,r_ohm_per_km=.1,
        x_ohm_per_km=.2,c_nf_per_km=10,max_i_ka=1,name='bad direct line')
    assert len(circuit_findings(net,origins)['line_voltage_mismatches'])==1
    net.line.at[li,'in_service']=False
    assert circuit_findings(net,origins)['line_voltage_mismatches']==[]


def test_open_coupler_is_respected_in_operational_connectivity():
    net=pp.create_empty_network()
    a=pp.create_bus(net,66);b=pp.create_bus(net,66)
    sw=pp.create_switch(net,a,b,et='b',closed=False)
    assert candidate_removal_connectivity(net,[])['before']['components']==2
    net.switch.at[sw,'closed']=True
    assert candidate_removal_connectivity(net,[])['before']['components']==1


def structure():
    return dict(site=dict(name='fixture'),voltage_levels=[dict(vl_id='s@154',nominal_kv=154),
        dict(vl_id='s@66',nominal_kv=66)],busbars=[dict(busbar_id='bb',vl_id='s@154')],
        bays=[dict(bay_id='bay',vl_id='s@66',busbar_ids=['bb'])],
        terminals=[dict(terminal_id='t',line_key='way',line_name='line',vl_id='s@154',
            binding='vertex-shared',attach_kind='busbar',attach_id='bb')])


def test_shared_vertex_does_not_override_known_voltage_conflict():
    out=structure_voltage_findings(structure(),{'way':{66}})
    assert len(out['terminal_voltage_conflicts'])==1
    assert len(out['bay_voltage_conflicts'])==1


def test_multivoltage_way_is_not_reduced_to_first_class():
    assert structure_voltage_findings(structure(),{'way':{66,154}})['terminal_voltage_conflicts']==[]


def test_unknown_voltage_and_missing_source_are_distinct():
    a=structure_voltage_findings(structure(),{'way':set()})
    b=structure_voltage_findings(structure(),{})
    assert a['unknown_terminal_voltage']==1 and a['missing_source_way']==0
    assert b['unknown_terminal_voltage']==0 and b['missing_source_way']==1
    assert not a['terminal_voltage_conflicts'] and not b['terminal_voltage_conflicts']


def test_sources_survive_deduplication_and_inserted_bus():
    nodes=[dict(id='junction',sub=0),dict(id='substation',sub=1)]
    out=source_nodes_by_bus({0:2,1:2},nodes,[dict(bus=2,new_bus=3)])
    assert [n['id'] for n in out[2]]==['junction','substation']
    assert [n['id'] for n in out[3]]==['junction','substation']
    assert all(n['via']=='implicit_stepdown' for n in out[3])


def test_unknown_line_propagation_does_not_treat_provisional_66_as_observed():
    net=pp.create_empty_network()
    a=pp.create_bus(net,154);b=pp.create_bus(net,66)
    li=pp.create_line_from_parameters(net,a,b,length_km=1,r_ohm_per_km=.1,
        x_ohm_per_km=.2,c_nf_per_km=10,max_i_ka=1)
    net.line.at[li,'kv_class']=0
    origins={a:[dict(kv=154)],b:[dict(kv=0)]}
    out=unknown_line_components(net,origins)
    assert out[0]['status']=='single_observed_class' and out[0]['observed_kv']==[154]
    origins[b]=[dict(kv=66)]
    assert unknown_line_components(net,origins)[0]['status']=='conflicting_observed_classes'


def test_inserted_lv_bus_does_not_inherit_hv_observation_as_its_own_voltage():
    net=pp.create_empty_network()
    a=pp.create_bus(net,66); b=pp.create_bus(net,66); c=pp.create_bus(net,66)
    for x,y,kv in [(a,b,0),(a,c,66)]:
        li=pp.create_line_from_parameters(net,x,y,length_km=1,r_ohm_per_km=.1,
            x_ohm_per_km=.2,c_nf_per_km=10,max_i_ka=1)
        net.line.at[li,'kv_class']=kv
    origins={a:[dict(kv=275,via='implicit_stepdown')],b:[dict(kv=0)]}
    out=unknown_line_components(net,origins)
    assert out[0]['observed_kv']==[66]
    assert out[0]['status']=='single_observed_class'
