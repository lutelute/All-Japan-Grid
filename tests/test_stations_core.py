"""変電所の構内結線(node-breaker)の規則。All-AU-Grid の回帰テストに All-EU-Grid が足したものを
移植し(src/stations/__init__.py)、日本の周波数の扱いを末尾に足した。"""

from src.stations.core import circuit_allocation, levels_of, model, mva


def site(osmid=1, voltage="132000;33000;11000", ring=((0, 0), (10, 0), (10, 10), (0, 10))):
    return {"type": "Feature", "properties": {"osm_type": "way", "osm_id": osmid, "voltage": voltage},
            "geometry": {"type": "Polygon", "coordinates": [[*map(list, ring), list(ring[0])]]}}


def wire(osmid, nodes, coords, voltage="132000", kind="bay", **tags):
    return {"type": "Feature", "properties": {"osm_type": "way", "osm_id": osmid, "node_ids": nodes,
            "power": "line", "line": kind, "voltage": voltage, **tags},
            "geometry": {"type": "LineString", "coordinates": coords}}


def device(osmid=9, power="transformer", lon=5, lat=5, **tags):
    return {"type": "node", "id": osmid, "lon": lon, "lat": lat, "tags": {"power": power, **tags}}


def kinds(data, kind):
    return [e for e in data["equipment"] if e["kind"] == kind]


def terms(data, eqid):
    return [t for t in data["terminals"] if t["equipment_id"] == eqid]


# ------------------------------------------------------------- All-AU-Grid's set
def test_three_windings_preserve_generator_primary_and_single_equipment():
    data = model([site()], [
        wire(11, [1, 9], [[1, 5], [5, 5]], "11000"),
        wire(12, [2, 9], [[5, 1], [5, 5]], "132000"),
        wire(13, [3, 9], [[9, 5], [5, 5]], "33000"),
    ], [device(**{"voltage:primary": "11000", "voltage:secondary": "132000", "voltage:tertiary": "33000",
                  "rating": "100 MVA"})])
    assert len(kinds(data, "transformer")) == 1
    ends = {e["role"]: e for e in data["ends"]}
    assert {k: e["kv"] for k, e in ends.items()} == {"primary": 11, "secondary": 132, "tertiary": 33}
    ts = {t["terminal_id"]: t for t in data["terminals"]}
    assert ts[ends["secondary"]["terminal_id"]]["sequence"] == 1
    assert len({ts[e["terminal_id"]]["node_id"] for e in ends.values()}) == 3
    assert all(e["rated_mva"] is None for e in ends.values())


def test_switch_breaks_conductive_path_even_in_middle_of_one_way():
    data = model([site()], [wire(11, [1, 9, 2], [[1, 5], [5, 5], [9, 5]], kind="busbar")], [device(power="switch")])
    sw = kinds(data, "switch")[0]
    ts = terms(data, sw["equipment_id"])
    assert len(ts) == 2 and ts[0]["node_id"] != ts[1]["node_id"]
    assert len(kinds(data, "busbar")) == 2
    assert "normal_open" not in sw["tags"]


def test_geometric_crossing_does_not_connect_and_no_automatic_voltage_ladder():
    data = model([site()], [wire(11, [1, 2], [[1, 5], [9, 5]]), wire(12, [3, 4], [[5, 1], [5, 9]])], [])
    assert len(data["nodes"]) == 2
    assert not data["ends"] and not kinds(data, "transformer")
    assert {r["kv"] for r in data["levels"]} == {132, 33, 11}


def test_untagged_line_must_not_bridge_midway_switch():
    # All-AU-Grid's case has the way inside the yard; here that makes it two station
    # conductors (it never leaves the footprint), still cut by the switch
    data = model([site()], [wire(11, [1, 9, 2], [[1, 5], [5, 5], [9, 5]], kind=None)], [device(power="switch")])
    ts = terms(data, kinds(data, "switch")[0]["equipment_id"])
    assert len(ts) == 2 and ts[0]["node_id"] != ts[1]["node_id"]
    assert len(kinds(data, "internal")) == 2 and not data["circuits"]
    # the same way leaving the yard: two line pieces, one bundle of circuits
    data = model([site()], [wire(11, [1, 9, 2], [[1, 5], [5, 5], [12, 5]], kind=None)], [device(power="switch")])
    ts = terms(data, kinds(data, "switch")[0]["equipment_id"])
    assert len(ts) == 2 and ts[0]["node_id"] != ts[1]["node_id"]
    assert len(kinds(data, "line")) == 2
    assert len(data["circuits"]) == 1


def test_parallel_conductor_bypass_is_flagged_not_hidden():
    data = model([site()], [wire(11, [1, 9, 2], [[1, 5], [5, 5], [9, 5]], kind="busbar"),
                            wire(12, [1, 2], [[1, 5], [9, 5]])], [device(power="switch")])
    assert "switch_bypass_or_mapping_loop" in {i["code"] for i in data["issues"]}


def test_missing_device_voltage_can_use_tagged_incident_conductors():
    data = model([site()], [wire(11, [1, 9], [[1, 5], [5, 5]], "132000"),
                            wire(12, [9, 2], [[5, 5], [9, 5]], "33000")], [device()])
    assert {e["kv"] for e in data["ends"]} == {132, 33}
    assert {e["voltage_method"] for e in data["ends"]} == {"shared_node_conductor_voltage"}


def test_tag_only_interface_does_not_fabricate_wire_or_duplicate_same_voltage_ends():
    data = model([site()], [wire(11, [1, 9], [[1, 5], [5, 5]], "11000")], [device(**{
        "voltage:primary": "11000", "voltage:secondary": "11000", "voltage:tertiary": "132000"})])
    assert len(data["ends"]) == 3
    assert all(t["node_id"] is None for t in data["terminals"])


def test_overlapping_stations_are_ambiguous_not_double_counted():
    data = model([site(), site(2)], [], [device(**{"voltage:primary": "132000", "voltage:secondary": "33000"})])
    assert data["equipment"][0]["site"] is None
    assert all(t["level_id"] is None for t in data["terminals"])
    assert "ambiguous_site_containment" in {i["code"] for i in data["issues"]}


def test_mixed_voltage_circuit_counts_preserve_total_and_source_order():
    assert circuit_allocation({"voltage": "132000;33000", "circuits": "3;1"}) == [
        (132, 3, "ordered_circuits_tag"), (33, 1, "ordered_circuits_tag")]
    assert circuit_allocation({"voltage": "132000;33000", "circuits": "4"}) == [
        (132, None, "unallocated_total"), (33, None, "unallocated_total")]
    assert circuit_allocation({"voltage": "132000", "cables": "6"})[0][1] is None


def test_rating_units_are_not_guessed():
    assert mva("500 kVA") == .5
    assert mva("1 GVA") == 1000
    assert mva("50 MW") is None
    assert mva("50") is None


def test_interfaces_have_stable_ids_independent_of_source_order():
    ws = [wire(11, [1, 9], [[1, 5], [5, 5]], "132000"), wire(12, [9, 2], [[5, 5], [9, 5]], "33000")]
    a, b = model([site()], ws, [device()]), model([site()], ws[::-1], [device()])
    for key, id_field in (("levels", "level_id"), ("nodes", "node_id"), ("ends", "end_id"),
                          ("terminals", "terminal_id")):
        assert {r[id_field] for r in a[key]} == {r[id_field] for r in b[key]}
    assert {(t["terminal_id"], t["node_id"]) for t in a["terminals"]} == \
           {(t["terminal_id"], t["node_id"]) for t in b["terminals"]}


def test_strictly_nested_footprints_use_inner_site():
    inner = site(2, ring=((4, 4), (6, 4), (6, 6), (4, 6)))
    data = model([site(), inner], [], [device()])
    eq = data["equipment"][0]
    assert eq["site"] == "w2" and eq["membership"] == "innermost_nested"
    assert "ambiguous_site_containment" not in {i["code"] for i in data["issues"]}


def test_partly_overlapping_footprints_stay_unresolved():
    overlap = site(2, ring=((4, 0), (12, 0), (12, 10), (4, 10)))
    data = model([site(), overlap], [], [device()])
    assert data["equipment"][0]["site"] is None
    assert "ambiguous_site_containment" in {i["code"] for i in data["issues"]}


def test_source_node_inside_station_recovers_through_way_without_inventing_nodes():
    data = model([site()], [wire(11, [1, 2, 3, 4], [[-2, 5], [2, 5], [8, 5], [12, 5]], kind=None)], [])
    assert len(data["equipment"]) == 3
    assert {m for n in data["nodes"] for m in n["members"]} == {"2", "3"}
    assert len(data["terminals"]) == 4
    crossing = model([site()], [wire(12, [10, 20], [[-2, 5], [12, 5]], kind=None)], [])
    assert not crossing["equipment"] and not crossing["terminals"]


# ------------------------------------------------------------- added for Europe
# Real-scale geometry for the metre buffer: a 100 m x 100 m yard at 50 N.
DX, DY = 100 / 71700, 100 / 111200
YARD = ((8, 50), (8 + DX, 50), (8 + DX, 50 + DY), (8, 50 + DY))


def test_portal_just_outside_the_fence_is_buffer_member_and_strict_view_keeps_label():
    # Line ends at a portal 10 m outside the fence; a bay runs from it to the busbar.
    portal = [8 + DX + 10 / 71700, 50 + DY / 2]
    bar = [[8 + DX / 4, 50 + DY / 2], [8 + 3 * DX / 4, 50 + DY / 2]]
    data = model([site(1, "110000", YARD)], [
        wire(21, [5, 6], bar, "110000", kind="busbar"),
        wire(22, [7, 6], [portal, bar[1]], "110000", kind="bay"),
        wire(23, [8, 7], [[8.05, 50.05], portal], "110000", kind=None)], [])
    bay = kinds(data, "bay")[0]
    assert bay["site"] == "w1" and bay["membership"] == "buffer"
    line_t = terms(data, kinds(data, "line")[0]["equipment_id"])
    assert len(line_t) == 1 and line_t[0]["detail"]["membership"] == "buffer"
    bb_t = terms(data, kinds(data, "busbar")[0]["equipment_id"])
    assert line_t[0]["node_id"] == bb_t[0]["node_id"]     # wired through the bay


def test_buffer_never_reaches_beyond_metres_or_from_a_point_substation():
    far = [8 + DX + 60 / 71700, 50 + DY / 2]
    data = model([site(1, "110000", YARD)], [wire(22, [7, 6], [far, [8 + DX * 1.5, 50 + DY / 2]], "110000")], [])
    assert not data["equipment"]
    point_site = {"type": "Feature", "properties": {"osm_type": "node", "osm_id": 3, "voltage": "20000"},
                  "geometry": {"type": "Point", "coordinates": [8, 50]}}
    data = model([point_site], [], [device(lon=8 + 5 / 71700, lat=50)])
    assert data["equipment"][0]["site"] is None


def test_transformer_voltage_list_gives_unordered_interfaces():
    data = model([site()], [wire(11, [1, 9], [[1, 5], [5, 5]], "132000"),
                            wire(12, [9, 2], [[5, 5], [9, 5]], "33000")], [device(voltage="132000;33000")])
    assert {(e["role"], e["kv"], e["voltage_method"]) for e in data["ends"]} == {
        ("listed_1", 132, "device_voltage_list"), ("listed_2", 33, "device_voltage_list")}
    assert all(t["node_id"] for t in data["terminals"])


def test_rail_conductors_form_their_own_level_at_the_same_kv():
    data = model([site(voltage="110000")], [
        wire(11, [1, 2], [[1, 5], [4, 5]], "110000", kind="busbar"),
        wire(12, [3, 4], [[6, 5], [9, 5]], "110000", kind="busbar", frequency="16.7")], [])
    assert {r["level_id"] for r in data["levels"]} == {"w1@110", "w1@110~rail"}
    assert levels_of({"voltage": "380000;110000", "frequency": "50;16.7"}) == [(380, "ac"), (110, "rail")]
    assert levels_of({"voltage": "320000", "frequency": "0"}) == []
    assert levels_of({"voltage": "medium"}) == [(None, None)]


def test_shared_tower_in_a_yard_keeps_voltages_apart():
    # 380 and 110 kV conductors share a node inside the yard (a tower drawn there).
    data = model([site(voltage="380000;110000")], [
        wire(11, [1, 2, 3], [[1, 5], [5, 5], [9, 5]], "380000", kind=None),
        wire(12, [4, 2, 5], [[5, 1], [5, 5], [5, 9]], "110000", kind=None)], [])
    nodes_at_2 = [n for n in data["nodes"] if "2" in n["members"]]
    assert len(nodes_at_2) == 2 and {n["level_id"] for n in nodes_at_2} == {"w1@380", "w1@110"}


# ------------------------------------------------------------- derived readings
def _yard():
    """Two 110 kV busbar sections, a coupler (DS-CB-DS), a line bay and a transformer bay.

        bar A (1-2) --DS 51-- 60 --CB 52-- 61 --DS 53-- bar B (3-4)
        bar A at 2 --DS 54-- 62 --CB 55-- 63 -- line 70 leaves the yard
        bar B at 4 --CB 56-- 64 -- transformer 80 (110/20 kV) -- 20 kV bay 65-66
    """
    y = 5
    ws = [wire(1, [1, 2], [[1, y], [3, y]], "110000", kind="busbar"),
          wire(2, [3, 4], [[6, y], [8, y]], "110000", kind="busbar"),
          wire(3, [1, 51, 60, 52, 61, 53, 3], [[1, y], [1, 3], [2, 3], [3, 3], [4, 3], [5, 3], [6, y]], "110000"),
          wire(4, [2, 54, 62, 55, 63], [[3, y], [3, 6], [3, 7], [3, 8], [3, 9]], "110000"),
          wire(5, [63, 70], [[3, 9], [3, 20]], "110000", kind=None, name="Nord"),
          wire(6, [4, 56, 64, 80], [[8, y], [8, 6], [8, 7], [8, 8]], "110000"),
          wire(7, [80, 65, 66], [[8, 8], [9, 8], [9.5, 8]], "20000")]
    sw = [device(i, "switch", lon=lon, lat=lat, switch=k) for i, lon, lat, k in (
        (51, 1, 3, "disconnector"), (52, 3, 3, "circuit_breaker"), (53, 5, 3, "disconnector"),
        (54, 3, 6, "disconnector"), (55, 3, 8, "circuit_breaker"), (56, 8, 6, "circuit_breaker"))]
    tr = device(80, lon=8, lat=8, **{"voltage:primary": "110000", "voltage:secondary": "20000"})
    return model([site(voltage="110000;20000")], ws, sw + [tr])


def test_bays_get_their_function_from_what_they_reach():
    from src.stations.views import analyse
    data = _yard()
    v = analyse(data)
    fn = {b["function"]: b for b in v["bays"]}
    assert set(fn) == {"coupler", "line_bay", "transformer_bay"}
    assert fn["coupler"]["switch_kinds"] == {"circuit_breaker": 1, "disconnector": 2}
    assert len(fn["coupler"]["busbar_nodes"]) == 2
    assert len(fn["line_bay"]["line_terminals"]) == 1 and len(fn["transformer_bay"]["winding_terminals"]) == 1
    assert not [i for i in data["issues"] if i["code"] != "transformer_interfaces_unknown"]


def test_line_terminal_binding_and_all_closed_topological_nodes():
    from src.stations.views import analyse
    data = _yard()
    v = analyse(data)
    line_eq = [e for e in data["equipment"] if e["kind"] == "line"][0]
    t = terms(data, line_eq["equipment_id"])[0]
    assert v["binding"][t["terminal_id"]] == {"binding": "wired", "reaches_busbar": True}
    assert v["levels"]["w1@110"] == {"tn": 1, "tn_external": 1, "tn_mapped": 1}   # coupler closed: one bus
    assert v["levels"]["w1@20"]["tn"] == 1
    assert {(p["hv_kv"], p["lv_kv"]) for p in v["pairs"]} == {(110, 20)}


def test_level_parts_that_stay_apart_with_every_switch_closed():
    from src.stations.views import analyse
    data = model([site(voltage="110000")], [
        wire(11, [1, 2], [[1, 5], [4, 5]], "110000", kind="busbar"),
        wire(12, [3, 4], [[6, 5], [9, 5]], "110000", kind="busbar"),
        wire(13, [2, 20], [[4, 5], [4, 20]], "110000", kind=None),
        wire(14, [4, 21], [[9, 5], [9, 20]], "110000", kind=None),
        wire(15, [30, 31], [[2, 8], [2, 20]], "110000", kind=None)], [])
    v = analyse(data)
    assert v["levels"]["w1@110"]["tn_external"] == 3 and v["levels"]["w1@110"]["tn_mapped"] == 2
    b = {v["binding"][t["terminal_id"]]["binding"] for e in data["equipment"] if e["kind"] == "line"
         for t in terms(data, e["equipment_id"])}
    assert b == {"wired", "footprint_only"}


def test_earthing_switch_grounds_the_conductor_it_stands_on_without_cutting_it():
    data = model([site()], [wire(11, [1, 9, 2], [[1, 5], [5, 5], [9, 5]], kind="busbar")],
                 [device(power="switch", switch="earthing")])
    sw = kinds(data, "switch")[0]
    assert len(kinds(data, "busbar")) == 1                     # the busbar is not cut
    ts = terms(data, sw["equipment_id"])
    assert len(ts) == 1 and ts[0]["node_id"] == terms(data, kinds(data, "busbar")[0]["equipment_id"])[0]["node_id"]
    assert not data["issues"]


def test_busbar_disconnector_at_a_bay_crossing_joins_bay_to_busbar_not_busbar_to_itself():
    # double busbar: the bay crosses both busbars; a disconnector at each crossing
    data = model([site(voltage="110000")], [
        wire(1, [1, 31, 2], [[1, 6], [5, 6], [9, 6]], "110000", kind="busbar"),
        wire(2, [3, 32, 4], [[1, 4], [5, 4], [9, 4]], "110000", kind="busbar"),
        wire(3, [40, 31, 32, 41], [[5, 8], [5, 6], [5, 4], [5, 2]], "110000"),
        wire(4, [41, 50], [[5, 2], [5, -5]], "110000", kind=None)],
        [device(31, "switch", lon=5, lat=6, switch="disconnector"), device(32, "switch", lon=5, lat=4, switch="disconnector")])
    from src.stations.views import analyse
    assert not [i for i in data["issues"] if i["code"] == "switch_ports_unresolved"]
    assert len(kinds(data, "busbar")) == 2                     # neither busbar is cut at the crossing
    assert {t["method"] for e in kinds(data, "switch") for t in terms(data, e["equipment_id"])} == {"busbar_junction"}
    v = analyse(data)
    bay = [b for b in v["bays"]]
    assert len(bay) == 1 and bay[0]["function"] == "line_bay" and len(bay[0]["busbar_nodes"]) == 2


def test_a_way_cut_at_the_fence_is_a_pass_through_not_a_joint():
    from src.stations.views import analyse
    data = model([site()], [wire(11, [1, 2, 3, 4], [[-2, 5], [2, 5], [8, 5], [12, 5]], kind=None)], [])
    assert {b["binding"] for b in analyse(data)["binding"].values()} == {"pass_through"}


def test_selector_disconnectors_landing_on_one_node_are_not_a_coupler():
    # a feeder bay on two busbars (selector DS each) whose outgoing cable is not mapped
    from src.stations.views import analyse
    data = model([site(voltage="110000")], [
        wire(1, [1, 31, 2], [[1, 6], [5, 6], [9, 6]], "110000", kind="busbar"),
        wire(2, [3, 32, 4], [[1, 4], [5, 4], [9, 4]], "110000", kind="busbar"),
        wire(3, [40, 31, 32, 41, 42], [[5, 8], [5, 6], [5, 4], [5, 2], [5, 1]], "110000")],
        [device(31, "switch", lon=5, lat=6, switch="disconnector"), device(32, "switch", lon=5, lat=4, switch="disconnector"),
         device(41, "switch", lon=5, lat=2, switch="circuit_breaker")])
    assert [b["function"] for b in analyse(data)["bays"]] == ["open_end"]


def test_untagged_wire_inside_the_yard_is_a_station_conductor():
    # line ends at a gantry (node 5); a short power=line runs on to the transformer (node 9)
    data = model([site(voltage="132000;33000")], [
        wire(11, [4, 5], [[-5, 5], [2, 5]], "132000", kind=None),
        wire(12, [5, 9], [[2, 5], [5, 5]], "132000", kind=None),
        wire(13, [9, 6], [[5, 5], [8, 5]], "33000")],
        [device(**{"voltage:primary": "132000", "voltage:secondary": "33000"})])
    from src.stations.views import analyse
    assert [e["conductor_rule"] for e in kinds(data, "internal")] == ["inside_one_footprint"]
    assert len(kinds(data, "line")) == 1
    t = terms(data, kinds(data, "line")[0]["equipment_id"])[0]
    assert analyse(data)["binding"][t["terminal_id"]]["binding"] == "wired"
    assert all(x["node_id"] for x in data["terminals"] if x["equipment_id"] == "n9")


def test_a_line_passing_just_outside_the_fence_is_not_cut_there():
    along = [[8 - DX, 50 + DY + 10 / 111200], [8 + DX / 2, 50 + DY + 10 / 111200], [8 + 2 * DX, 50 + DY + 10 / 111200]]
    data = model([site(1, "110000", YARD)], [wire(23, [1, 2, 3], along, "110000", kind=None)], [])
    assert not data["equipment"] and not data["terminals"]


# ------------------------------------------------------------- All-Japan-Grid's additions
def test_japan_50_and_60_hz_share_one_level():
    # 西日本の線は frequency=60 が付き、同じ変電所の無タグの母線と同じ階級に入る
    data = model([site(voltage="154000")], [
        wire(11, [1, 2], [[1, 5], [4, 5]], "154000", kind="busbar"),
        wire(12, [2, 3], [[4, 5], [4, 20]], "154000", kind=None, frequency="60")], [])
    assert {r["level_id"] for r in data["levels"]} == {"w1@154"}
    assert levels_of({"voltage": "275000;154000", "frequency": "50;60"}) == [(275, "ac"), (154, "ac")]


def test_bay_drawn_to_a_portal_past_the_fence_brings_the_line_in():
    # 柵の外 47 m の門型鉄構までベイが描かれ、線路はそこから出る(日本の OSM で中央値 47 m)
    portal = [8 + DX + 47 / 71700, 50 + DY / 2]
    bar = [[8 + DX / 4, 50 + DY / 2], [8 + 3 * DX / 4, 50 + DY / 2]]
    ways = [wire(21, [5, 6], bar, "110000", kind="busbar"),
            wire(22, [7, 6], [portal, bar[1]], "110000", kind="bay"),
            wire(23, [8, 7], [[8.05, 50.05], portal], "110000", kind=None)]
    strict = model([site(1, "110000", YARD)], ways, [])
    assert [i["code"] for i in strict["issues"]] == ["internal_way_without_unique_site"]
    assert not kinds(strict, "line")
    data = model([site(1, "110000", YARD)], ways, [], extension_m=100)
    assert not data["issues"]
    bay = kinds(data, "bay")[0]
    assert bay["site"] == "w1" and bay["membership"] == "internal_extension"
    line_t = terms(data, kinds(data, "line")[0]["equipment_id"])
    assert len(line_t) == 1 and line_t[0]["detail"]["membership"] == "internal_extension"
    assert line_t[0]["node_id"] == terms(data, kinds(data, "busbar")[0]["equipment_id"])[0]["node_id"]
    # 上限を超えるはみ出し・2 つの敷地にまたがるものは厳密な読み方のまま
    far = model([site(1, "110000", YARD)], ways, [], extension_m=40)
    assert [i["code"] for i in far["issues"]] == ["internal_way_without_unique_site"]
