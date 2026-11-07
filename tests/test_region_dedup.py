"""介入#58(地域をまたぐ写しを 1 つにまとめる)の決まりを、合成の地域ごとの正典で確かめる(2026-11-07)。"""
from src.topology.region_dedup import dedup_region_copies


def _n(lat, lon, kv, sub=0, nid=None):
    return {"id": nid or f"n{lat}:{lon}:{kv}", "lat": lat, "lon": lon, "kv": kv, "sub": sub, "deg": 1,
            "main": 1, "name": nid or "j"}


def _e(a, b, kv, name="L", mid=None, par=1):
    path = [list(a)] + ([list(mid)] if mid else []) + [list(b)]
    return {"a": list(a), "b": list(b), "kv": kv, "par": par, "name": name, "path": path}


A, B, M = (35.0, 137.0), (35.0, 137.1), (35.0, 137.05)


def _col():
    # 2 つの地域に同じ線(両端の点と形が同じ)。tokyo は 66 kV、chubu は電圧不明
    return {
        "tokyo": {"nodes": [_n(*A, 66.0), _n(*B, 66.0)], "edges": [_e(A, B, 66.0, mid=M)]},
        "chubu": {"nodes": [_n(*A, 0.0), _n(*B, 0.0)], "edges": [_e(A, B, 0.0, mid=M)]},
    }


def test_keeps_the_territory_copy_and_drops_orphans():
    out, led = dedup_region_copies(_col(), owner_of=lambda la, lo: "tokyo")
    assert len(out["tokyo"]["edges"]) == 1 and out["chubu"]["edges"] == []
    assert out["chubu"]["nodes"] == []                       # 枝の付かなくなった写しの点は消す
    assert led["n_groups"] == 1 and led["n_edges_dropped"] == 1 and led["n_nodes_dropped"] == 2


def test_fills_unknown_voltage_from_the_other_copy():
    out, led = dedup_region_copies(_col(), owner_of=lambda la, lo: "chubu")
    e = out["chubu"]["edges"][0]
    assert e["kv"] == 66.0 and e["kv_from_copy"] == 1         # 残す写しが電圧不明なら、ほかの写しの電圧を採る
    assert out["tokyo"]["edges"] == [] and led["kinds"] == {"kv0_filled": 1}


def test_same_shape_but_different_end_is_not_a_copy():
    """形が同じでも、端を結ぶ点が違うものは写しとしない(阿波の 500 kV 線で踏んだ)。"""
    col = _col()
    col["chubu"]["edges"][0]["b"] = [35.0003, 137.1003]
    out, led = dedup_region_copies(col, owner_of=lambda la, lo: "tokyo")
    assert led["n_groups"] == 0 and len(out["chubu"]["edges"]) == 1


def test_substation_kept_unless_another_region_has_the_point():
    col = _col()
    col["chubu"]["nodes"].append(_n(35.0, 137.1, 0.0, sub=1, nid="S"))      # B に変電所の点(tokyo にも同じ座標の点がある)
    col["chubu"]["nodes"].append(_n(35.2, 137.2, 0.0, sub=1, nid="T"))      # 枝の付かない変電所(写しに関わらない)
    out, _ = dedup_region_copies(col, owner_of=lambda la, lo: "tokyo")
    ids = {n["id"] for n in out["chubu"]["nodes"]}
    assert "S" not in ids and "T" in ids


def test_other_region_lines_keep_their_points():
    """写しを落としても、その地域の別の線が付く点は残す。"""
    col = _col()
    col["chubu"]["edges"].append(_e(B, (35.1, 137.1), 0.0, name="別の線"))
    col["chubu"]["nodes"].append(_n(35.1, 137.1, 0.0))
    out, _ = dedup_region_copies(col, owner_of=lambda la, lo: "tokyo")
    pts = {(n["lat"], n["lon"]) for n in out["chubu"]["nodes"]}
    assert (35.0, 137.1) in pts and (35.0, 137.0) not in pts
