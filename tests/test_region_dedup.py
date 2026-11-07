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


# ---- 介入#59(案): 形が同じで端を結ぶ点だけが違う写しの、端の点を寄せる ----
from src.topology.region_dedup import align_copy_ends  # noqa: E402

S_T, S_C = (35.0, 137.1), (35.0002, 137.1002)      # 同じ変電所の点が地域ごとに約 28 m ずれて 2 つ


def _twins():
    """tokyo と chubu に同じ線の写し(形は同じ)。B の側の端を、それぞれ自分の地域の変電所の点に結んでいる。"""
    def line(b):
        return {"a": list(A), "b": list(b), "kv": 66.0, "par": 1, "name": "L", "path": [list(A), list(M), [35.0001, 137.1001]]}
    col = {
        "tokyo": {"nodes": [_n(*A, 66.0), _n(*S_T, 66.0, sub=1, nid="ST"), _n(35.1, 137.1, 66.0)],
                  "edges": [line(S_T), _e(S_T, (35.1, 137.1), 66.0, name="東京の別の線")]},
        "chubu": {"nodes": [_n(*A, 66.0), _n(*S_C, 66.0, sub=1, nid="SC"), _n(*S_C, 77.0, sub=1, nid="SC77"),
                            _n(35.1, 137.2, 77.0)],
                  "edges": [line(S_C), _e(S_C, (35.1, 137.2), 77.0, name="中部の別の線")]},
    }
    for v in col.values():
        for n in v["nodes"]:
            if n["sub"]:
                n["name"] = "甲変電所 66kV" if n["kv"] == 66.0 else "甲変電所 77kV"
    return col


def test_twin_ends_are_aligned_then_deduped():
    col, led = align_copy_ends(_twins(), owner_of=lambda la, lo: "tokyo")
    assert led["n_points_aliased"] == 1 and led["rows"][0]["kind"] == "same_substation"
    # 寄せ先は領土の地域(tokyo)の点。chubu の別の線の端も寄せ先へ書き換える
    assert led["rows"][0]["to"] == list(S_T)
    other = [e for e in col["chubu"]["edges"] if e["name"] == "中部の別の線"][0]
    assert tuple(other["a"]) == S_T
    ids = {n["id"]: n for n in col["chubu"]["nodes"]}
    assert "SC" not in ids                                     # 寄せ先に同じ電圧の変電所の点がある → 消す
    assert (ids["SC77"]["lat"], ids["SC77"]["lon"]) == S_T     # 寄せ先に無い電圧の点 → 寄せ先へ動かす
    out, l2 = dedup_region_copies(col, owner_of=lambda la, lo: "tokyo")
    assert l2["n_groups"] == 1 and len([e for e in out["chubu"]["edges"] if e["name"] == "L"]) == 0


def test_dangling_copy_end_goes_to_the_connected_point():
    """片方の写しの端が行き止まりなら、ほかの線が付く方へ寄せる(領土の地域の写しでも)。"""
    col = _twins()
    col["tokyo"]["edges"] = col["tokyo"]["edges"][:1]          # tokyo の変電所の点には写しだけが付く
    col["tokyo"]["nodes"] = col["tokyo"]["nodes"][:2]
    out, led = align_copy_ends(col, owner_of=lambda la, lo: "tokyo")
    r = led["rows"][0]
    assert r["kind"] == "dangling" and r["to"] == list(S_C) and r["from"] == list(S_T)
    assert all(n["id"] != "ST" for n in out["tokyo"]["nodes"])  # 寄せ先に変電所の点があるので消す


def test_far_ends_are_left_alone():
    col = _twins()
    far = (35.01, 137.1)                                       # 約 1.1 km 離れた点
    col["chubu"]["edges"][0]["b"] = list(far)
    col["chubu"]["nodes"].append(_n(*far, 66.0))
    _, led = align_copy_ends(col, owner_of=lambda la, lo: "tokyo")
    assert led["n_points_aliased"] == 0 and len(led["too_far"]) == 1


def test_edge_between_twin_points_collapses():
    col = _twins()
    col["chubu"]["edges"].append(_e(S_C, S_T, 66.0, name="構内の短い枝"))
    out, led = align_copy_ends(col, owner_of=lambda la, lo: "tokyo")
    assert led["n_edges_collapsed"] == 1 and all(e["name"] != "構内の短い枝" for e in out["chubu"]["edges"])


def test_identical_ends_are_untouched():
    out, led = align_copy_ends(_col(), owner_of=lambda la, lo: "tokyo")
    assert led["n_points_aliased"] == 0 and out["chubu"]["edges"] == _col()["chubu"]["edges"]
