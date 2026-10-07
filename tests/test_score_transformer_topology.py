"""全国の変圧器台帳での採点(scripts/score_transformer_topology.py)の照合部分。"""
from scripts.score_transformer_topology import load_registry, site_norm


def test_site_names_from_both_sides_meet():
    assert site_norm("九州電力 木佐木変電所") == site_norm("木佐木") == "木佐木"
    assert site_norm("西濃変電所(2)") == site_norm("西濃") == "西濃"
    assert site_norm("大間町変電所_2") == "大間町"
    assert site_norm("新綾部変電所") != site_norm("綾部変電所")


def test_three_winding_rows_expand_to_pairs(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text("utility,agj_region,substation_raw,substation_norm,hv_kv,lv_kv,tv_kv\n"
                 "okinawa,okinawa,X変電所,X,66,22,13.8\n"
                 "tokyo,tokyo,東毛,東毛,275,66,\n", encoding="utf-8")
    r = load_registry(p)
    assert r[("okinawa", "X")] == {(66, 22), (66, 13), (22, 13)}
    assert r[("tokyo", "東毛")] == {(275, 66)}
