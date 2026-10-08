"""Identity trials must preserve injections' topology inputs and reject unsafe merges."""
import copy
import pytest

from src.powerflow.site_identity import apply_site_aliases, model_digest


def fixture():
    nodes = [dict(id=i, name='同じ設備', sub=1, kv=66, region='tokyo', lat=35, lon=x)
             for i, x in [('duplicate', 139.001), ('target', 139), ('neighbor', 138.99)]]
    edge = dict(a=[35, 139.001], b=[35, 138.99], kv=66, par=2,
                path=[[35, 139.0008], [35.001, 138.995], [35, 138.99]], name='observed_line')
    return dict(nodes=nodes, edges=[edge])


def plan(data):
    return dict(input_model_digest=model_digest(data), aliases=[dict(from_id='duplicate', to_id='target',
                osm_identity='way/123', decision='trial_alias')])


def test_alias_preserves_observed_paths_and_input():
    data = fixture()
    original = copy.deepcopy(data)
    after, changes = apply_site_aliases(data, plan(data))
    assert data == original
    assert [n['id'] for n in after['nodes']] == ['target', 'neighbor']
    assert after['edges'][0]['a'] == [35, 139]
    for key in ['path', 'kv', 'par', 'name', 'b']:
        assert after['edges'][0][key] == data['edges'][0][key]
    assert changes['added_edges'] == changes['removed_edges'] == changes['changed_paths'] == 0


def test_stale_plan_cannot_rewire_changed_input():
    data = fixture()
    proposal = plan(data)
    data['edges'][0]['par'] = 1
    with pytest.raises(ValueError, match='snapshot'):
        apply_site_aliases(data, proposal)


def test_rebuild_keeps_estimated_impedance_when_a_bus_moves():
    from scripts.run_full_powerflow_from_db import build_island_net
    data = fixture()
    data['edges'][0].pop('path')
    after, changes = apply_site_aliases(data, plan(data))
    options = dict(nameplates=None, territory=False, dedup_nodes=True, site_trafos=False,
                   btb_split=False, freq_fix=False, implicit_stepdown=False, cap_calib=False)
    before_net, _, _ = build_island_net('east', copy.deepcopy(data['nodes']), data['edges'], 50, {}, **options)
    after_net, _, _ = build_island_net('east', copy.deepcopy(after['nodes']), after['edges'], 50, {}, **options)
    assert changes['preserved_length_estimate_edges'] == [0]
    assert before_net.line.length_km.tolist() == after_net.line.length_km.tolist()
    assert before_net.line.r_ohm_per_km.tolist() == after_net.line.r_ohm_per_km.tolist()
    assert len(after_net.bus) == len(before_net.bus)-1
    assert 'path' not in after['edges'][0]


@pytest.mark.parametrize('kv', [0, -66, 154])
def test_unknown_or_different_voltage_keeps_separate_buses(kv):
    data = fixture()
    data['nodes'][0]['kv'] = kv
    if kv < 0:
        data['nodes'][1]['kv'] = kv
    with pytest.raises(ValueError, match='voltage'):
        apply_site_aliases(data, plan(data))


def test_site_name_cannot_bridge_frequency_islands():
    data = fixture()
    data['nodes'][0]['region'] = 'chubu'
    with pytest.raises(ValueError, match='islands'):
        apply_site_aliases(data, plan(data))


def test_coordinate_shared_by_another_bus_needs_endpoint_identity():
    data = fixture()
    data['nodes'].append(dict(data['nodes'][0], id='different_voltage', kv=154))
    with pytest.raises(ValueError, match='other buses'):
        apply_site_aliases(data, plan(data))


def test_unknown_edge_cannot_silently_attach_to_high_voltage_bus():
    data = fixture()
    data['nodes'].append(dict(data['nodes'][1], id='target_hv', kv=154))
    data['edges'][0]['kv'] = 0
    with pytest.raises(ValueError, match='Unknown-voltage edge'):
        apply_site_aliases(data, plan(data))


def test_multiple_targets_for_same_node_are_rejected():
    data = fixture()
    proposal = plan(data)
    proposal['aliases'].append(dict(proposal['aliases'][0], to_id='neighbor'))
    with pytest.raises(ValueError, match='exactly one'):
        apply_site_aliases(data, proposal)
