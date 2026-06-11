"""Boundary-injection mechanics (synthetic yaml + nets).

Pins the phase-10 behaviours:

- name-matched boundary substation gets the import as an sgen (highest
  voltage class of the yard wins), exports become boundary_* loads;
- the ヶ/ケ normalisation (関ヶ原 official vs OSM 関ケ原町) name-matches;
- positional fallback clusters near-coincident candidates and splits the
  injection per corridor cluster;
- balance_power dispatches local generation to load MINUS imports.

Measured effect on real data (recorded in IMPROVEMENT_LOG): tokyo flow
rho 0.691 -> 0.707, 新いわき線 left the top mismatches; backbone AC 10/10
held with injections in all regions.
"""

import json

import pandapower as pp
import pytest

from src.powerflow.boundary import apply_boundary_imports
from src.powerflow.transforms import balance_power


def _yaml(tmp_path, from_region="tohoku", to_region="tokyo",
          capacity=1000.0, to_sub="関ヶ原変電所", from_sub="相馬変電所"):
    text = f"""
interconnections:
  - id: "ic_t1"
    from_region: "{from_region}"
    to_region: "{to_region}"
    capacity_mw: {capacity}
    voltage_kv: 500
    type: "AC"
    route:
      from_substation_ja: "{from_sub}"
      to_substation_ja: "{to_sub}"
"""
    p = tmp_path / "ics.yaml"
    p.write_text(text, encoding="utf-8")
    return str(p)


def _geo(lon, lat):
    return json.dumps({"coordinates": [lon, lat], "type": "Point"})


def _net_with(names_kv_pos):
    net = pp.create_empty_network(f_hz=50)
    for name, kv, (lon, lat) in names_kv_pos:
        b = pp.create_bus(net, vn_kv=kv, name=name)
        net.bus.at[b, "geo"] = _geo(lon, lat)
    pp.create_ext_grid(net, bus=0, vm_pu=1.0)
    return net


def test_name_match_import_picks_highest_class(tmp_path):
    net = _net_with([
        ("関ケ原町変電所 154kV", 154.0, (136.46, 35.36)),
        ("関ケ原町変電所 500kV", 500.0, (136.46, 35.36)),
    ])
    y = _yaml(tmp_path, capacity=2000.0)
    s = apply_boundary_imports(net, "tokyo", yaml_path=y,
                               utilisation={"ic_t1": 0.5})
    assert s["ics"]["ic_t1"]["method"] == "name"
    assert s["import_mw"] == pytest.approx(1000.0)
    assert len(net.sgen) == 1
    assert int(net.sgen.at[0, "bus"]) == 1            # the 500 kV bus
    assert net.sgen.at[0, "name"] == "boundary_ic_t1"


def test_export_side_becomes_load(tmp_path):
    net = _net_with([("相馬変電所 500kV", 500.0, (140.9, 37.8))])
    y = _yaml(tmp_path, capacity=2000.0)
    s = apply_boundary_imports(net, "tohoku", yaml_path=y,
                               utilisation={"ic_t1": 0.5})
    assert s["export_mw"] == pytest.approx(1000.0)
    assert len(net.sgen) == 0
    assert len(net.load) == 1
    assert net.load.at[0, "p_mw"] == pytest.approx(1000.0)
    assert net.load.at[0, "name"] == "boundary_ic_t1"


def test_positional_fallback_clusters_corridors(tmp_path, monkeypatch):
    # no name match; two corridor ends ~100 km apart + a duplicate vertex
    net = _net_with([
        ("a-corridor j1", 500.0, (140.80, 37.38)),
        ("a-corridor j2", 500.0, (140.81, 37.39)),   # same cluster as j1
        ("b-corridor j1", 500.0, (139.86, 36.99)),
        ("far south", 500.0, (139.7, 35.5)),          # beyond spread window
    ])
    y = _yaml(tmp_path, to_sub="不在変電所")
    import src.powerflow.boundary as bd
    monkeypatch.setattr(bd, "_partner_centroid",
                        lambda *a, **k: (38.3, 140.6))
    s = apply_boundary_imports(net, "tokyo", yaml_path=y,
                               utilisation={"ic_t1": 0.6})
    assert "position(2 corridors" in s["ics"]["ic_t1"]["method"]  # equal/measured-weighted variants
    assert len(net.sgen) == 2
    assert sorted(net.sgen["p_mw"]) == pytest.approx([300.0, 300.0])


def test_balance_power_covers_load_minus_imports():
    net = pp.create_empty_network(f_hz=50)
    b = pp.create_bus(net, vn_kv=275.0)
    pp.create_ext_grid(net, bus=b, vm_pu=1.0)
    pp.create_load(net, bus=b, p_mw=1000.0, q_mvar=100.0)
    pp.create_gen(net, bus=b, p_mw=0.0, vm_pu=1.0, max_p_mw=3000.0, type="gas")
    pp.create_sgen(net, bus=b, p_mw=400.0, q_mvar=0.0,
                   name="boundary_ic_t1", type="boundary_import")
    balance_power(net, {"reserve_margin": 0.05})
    # local dispatch covers 1000*1.05 - 400 = 650
    assert float(net.gen.at[0, "p_mw"]) == pytest.approx(650.0)
