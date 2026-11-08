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


def test_points_of_different_islands_are_moved_not_merged():
    """寄せ先に島(同期系統)の違う点しか無ければ、消さずに動かして残す(富士市変電所で踏んだ)。"""
    isl = lambda la, lo, reg: "east" if reg == "tokyo" else "west"
    out, led = align_copy_ends(_twins(), owner_of=lambda la, lo: "tokyo", island_of=isl)
    ids = {n["id"]: n for n in out["chubu"]["nodes"]}
    assert (ids["SC"]["lat"], ids["SC"]["lon"]) == S_T          # 同じ電圧の点が寄せ先にあっても、島が違うので残す
    assert led["n_nodes_kept_other_island"] >= 1


def test_load_point_aliases_checks_the_current_canon(tmp_path):
    import json
    from src.topology.region_dedup import load_point_aliases
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps({"ends": {"rows": [{"from": [35.0, 137.1], "to": [35.0002, 137.1002]}]}}))
    assert load_point_aliases({(35.0002, 137.1002)}, str(p)) == {(35.0, 137.1): (35.0002, 137.1002)}
    # 寄せた点がまだ正典にある(帳簿が古い・#59 を切った)ときは使わない
    assert load_point_aliases({(35.0, 137.1), (35.0002, 137.1002)}, str(p)) == {}
    assert load_point_aliases(set(), str(tmp_path / "none.json")) == {}


# ---- 介入#60(案): 区切りの違う写しの区切りをそろえる ----
from src.topology.region_dedup import align_copy_splits, heal_copy_splits  # noqa: E402

P = [(35.0, 137.0 + 0.01 * k) for k in range(7)]          # 1 本の way の頂点 P0..P6
Q = (35.05, 137.03)                                     # P3 から出る枝の先
SAME = lambda la, lo, reg: "east"                       # 島はすべて同じ


def _line(a, b, lo, hi, kv=66.0, name="L"):
    return {"a": list(a), "b": list(b), "kv": kv, "par": 1, "name": name, "path": [list(x) for x in P[lo:hi + 1]]}


def _run(col, owner, island_of=SAME):
    c1, ls = align_copy_splits(col, island_of=island_of)
    c2, _ = align_copy_ends(c1, owner_of=owner, island_of=island_of)
    c3, _ = dedup_region_copies(c2, owner_of=owner)
    c4, lh = heal_copy_splits(c3)
    return c4, ls, lh


def _ab(v):
    return sorted((tuple(e["a"]), tuple(e["b"])) for e in v["edges"])


def test_branch_point_of_one_region_splits_the_other_copy():
    """kansai は P3 に分岐があって区切り、chubu は通り抜ける。chubu の写しを P3 で区切ってから #58 でまとめる。"""
    col = {
        "kansai": {"nodes": [_n(*P[0], 66.0), _n(*P[3], 66.0), _n(*P[6], 66.0), _n(*Q, 66.0)],
                  "edges": [_line(P[0], P[3], 0, 3), _line(P[3], P[6], 3, 6),
                            {"a": list(P[3]), "b": list(Q), "kv": 66.0, "par": 1, "name": "枝"}]},
        "chubu": {"nodes": [_n(*P[0], 66.0), _n(*P[6], 66.0)], "edges": [_line(P[0], P[6], 0, 6)]},
    }
    out, ls, lh = _run(col, owner=lambda la, lo: "chubu")
    assert ls["n_edges_split"] == 1 and ls["rows"][0]["why"] == ["end"]
    assert _ab(out["chubu"]) == [(P[0], P[3]), (P[3], P[6])]            # 領土の chubu の写しを残し、P3 で区切る
    assert [e["name"] for e in out["kansai"]["edges"]] == ["枝"]           # kansai の写しは落ち、枝は P3 に付いたまま
    assert any("_jct_split_" in n["id"] for n in out["chubu"]["nodes"])
    assert lh["n_joints_healed"] == 0


def test_split_is_healed_when_nothing_else_needs_it():
    """kansai の区切り P3 に何も付かないなら、kansai の写しが落ちたあと chubu の枝をつなぎ直す(区切る前に戻る)。"""
    col = {
        "kansai": {"nodes": [_n(*P[0], 66.0), _n(*P[3], 66.0), _n(*P[6], 66.0)],
                  "edges": [_line(P[0], P[3], 0, 3), _line(P[3], P[6], 3, 6)]},
        "chubu": {"nodes": [_n(*P[0], 66.0), _n(*P[6], 66.0)], "edges": [_line(P[0], P[6], 0, 6)]},
    }
    out, _, lh = _run(col, owner=lambda la, lo: "chubu")
    assert lh["n_joints_healed"] == 1 and out["kansai"]["edges"] == []
    assert out["chubu"]["edges"] == [_line(P[0], P[6], 0, 6)]
    assert not any("_jct_split_" in n["id"] for n in out["chubu"]["nodes"])
    assert not any(k.startswith("_") for v in out.values() for x in v["edges"] + v["nodes"] for k in x)


def test_truncated_copy_joins_the_longer_copy():
    """kansai の写しは P3 で止まる(先の way が取り出しに無い)。重なる所は領土の写しを残し、P3 でつながる。"""
    col = {
        "kansai": {"nodes": [_n(*P[0], 66.0), _n(*P[3], 66.0)], "edges": [_line(P[0], P[3], 0, 3)]},
        "chubu": {"nodes": [_n(*P[0], 66.0), _n(*P[6], 66.0)], "edges": [_line(P[0], P[6], 0, 6)]},
    }
    out, _, _ = _run(col, owner=lambda la, lo: "kansai" if lo < P[3][1] else "chubu")
    assert _ab(out["kansai"]) == [(P[0], P[3])] and _ab(out["chubu"]) == [(P[3], P[6])]


def test_vertex_with_two_voltages_is_not_split():
    """電圧の違う併架の頂点は区切らない(同じ座標に電圧の違う点ができ、潮流計算が変圧器を作るため)。"""
    col = {
        "kansai": {"nodes": [_n(*P[0], 66.0), _n(*P[3], 66.0), _n(*P[6], 66.0)],
                  "edges": [_line(P[0], P[3], 0, 3), _line(P[3], P[6], 3, 6)]},
        "chubu": {"nodes": [_n(*P[0], 154.0), _n(*P[6], 154.0)], "edges": [_line(P[0], P[6], 0, 6, kv=154.0)]},
    }
    _, ls = align_copy_splits(col, island_of=SAME)
    assert ls["n_points_skipped_kv"] == 1 and ls["n_edges_split"] == 0


def test_copies_of_different_islands_are_not_split():
    """区切りの理由になった地域と潮流計算の島が違えば区切らない(周波数の境)。"""
    col = {
        "kansai": {"nodes": [_n(*P[0], 66.0), _n(*P[3], 66.0), _n(*P[6], 66.0)],
                  "edges": [_line(P[0], P[3], 0, 3), _line(P[3], P[6], 3, 6)]},
        "chubu": {"nodes": [_n(*P[0], 66.0), _n(*P[6], 66.0)], "edges": [_line(P[0], P[6], 0, 6)]},
    }
    _, ls = align_copy_splits(col, island_of=lambda la, lo, reg: "east" if reg == "kansai" else "west")
    assert ls["n_skipped_island"] == 1 and ls["n_edges_split"] == 0


def test_substation_the_line_enters_is_kept():
    """kansai の写しは P3 で変電所 S に入り、chubu の写し(S が取り出しに無い)は通り抜ける。区切った点を S に寄せ、
    継ぎ目に S があるのでつなぎ直さない(変電所の点を分岐点の方へ寄せて消さない。#59 の寄せ先は変電所の点が先)。"""
    S = (35.0008, 137.03)
    col = {
        "kansai": {"nodes": [_n(*P[0], 66.0), _n(*S, 66.0, sub=1, nid="S")], "edges": [_line(P[0], S, 0, 3)]},
        "chubu": {"nodes": [_n(*P[0], 66.0), _n(*P[6], 66.0)], "edges": [_line(P[0], P[6], 0, 6)]},
    }
    out, _, lh = _run(col, owner=lambda la, lo: "chubu")
    assert _ab(out["chubu"]) == [(P[0], S), (S, P[6])] and out["kansai"]["edges"] == []
    assert [n["id"] for n in out["kansai"]["nodes"]] == ["S"] and lh["n_joints_healed"] == 0


def test_copies_of_different_label_islands_are_not_split():
    """地域の名札の島が違えば(東京と中部)、潮流計算の島が同じでも区切らない(後段の #34 が名札で島を見るため)。"""
    col = {
        "tokyo": {"nodes": [_n(*P[0], 66.0), _n(*P[3], 66.0), _n(*P[6], 66.0)],
                  "edges": [_line(P[0], P[3], 0, 3), _line(P[3], P[6], 3, 6)]},
        "chubu": {"nodes": [_n(*P[0], 66.0), _n(*P[6], 66.0)], "edges": [_line(P[0], P[6], 0, 6)]},
    }
    _, ls = align_copy_splits(col, island_of=SAME)
    assert ls["n_skipped_island"] == 1 and ls["n_edges_split"] == 0


def test_unknown_voltage_junction_is_merged_into_the_substation():
    """電圧不明(0)の区切りの点を変電所の点に寄せたら、動かして残さずに消す(潮流計算の網で変電所の需要が外れるため)。"""
    S = (35.0008, 137.03)
    col = {
        "kansai": {"nodes": [_n(*P[0], 66.0), _n(*S, 66.0, sub=1, nid="S")], "edges": [_line(P[0], S, 0, 3)]},
        "chubu": {"nodes": [_n(*P[0], 0.0), _n(*P[6], 0.0)], "edges": [_line(P[0], P[6], 0, 6, kv=0.0)]},
    }
    out, _, _ = _run(col, owner=lambda la, lo: "chubu")
    at_s = [n for v in out.values() for n in v["nodes"] if (n["lat"], n["lon"]) == S]
    assert [n["id"] for n in at_s] == ["S"]
