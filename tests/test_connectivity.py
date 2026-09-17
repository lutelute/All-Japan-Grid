"""Phase 3 (全面改修): 全国連結性の単一権威 src.powerflow.connectivity の不変条件。

national.py(潮流)と built_view_all / build_editor_data(表示)が同一権威を消費する
ことで「Pages島色=潮流の島=census」を構造的に一致させる。合成入力で核心規則を高速検証:
  - 4周波数同期島(east 50Hz / west 60Hz)は近接でも AC stitch されない(非同期)
  - 越境 stitch は同一電圧階級のみ(~110m)
  - OCCTO AC タイの定義は national.load_interconnections に一本化(6本)
"""
from src.powerflow.connectivity import compute_connectivity, REGION_ISLAND
from src.powerflow.national import ISLANDS, load_interconnections


def test_region_island_map_matches_islands():
    """REGION_ISLAND は ISLANDS の反転(単一の正)。"""
    for isl, (regs, _f) in ISLANDS.items():
        for r in regs:
            assert REGION_ISLAND[r] == isl


def test_east_west_not_ac_merged():
    """東(tokyo,50Hz)と西(chubu,60Hz)は ~7m 同電圧でも別島=AC連結しない。"""
    nodes = [
        {"id": "e", "lat": 35.00000, "lon": 138.00000, "kv": 500, "region": "tokyo", "name": "E"},
        {"id": "w", "lat": 35.00005, "lon": 138.00005, "kv": 500, "region": "chubu", "name": "W"},
    ]
    conn = compute_connectivity(nodes, [])
    assert conn["island_of"][(35.0, 138.0)] == "east"
    assert conn["island_of"][(35.00005, 138.00005)] == "west"
    # 別島なので別グラフ=stitchされず、各島1ノードの単独成分(各々その島のmain)
    assert conn["meta"]["components"]["east"] == 1
    assert conn["meta"]["components"]["west"] == 1
    assert conn["meta"]["n_stitch"] == 0


def test_cross_region_same_vclass_stitched():
    """同一島の越境近接・同電圧階級は stitch して1成分(タイの無い chubu+kyushu で分離検証)。"""
    nodes = [
        {"id": "a", "lat": 37.0, "lon": 140.0, "kv": 500, "region": "chubu", "name": "A"},
        {"id": "b", "lat": 37.00005, "lon": 140.00005, "kv": 500, "region": "kyushu", "name": "B"},
    ]
    conn = compute_connectivity(nodes, [])
    assert conn["meta"]["components"]["west"] == 1
    assert conn["meta"]["n_stitch"] >= 1


def test_cross_region_diff_vclass_not_stitched():
    """同一島の越境近接でも電圧階級が違えば stitch しない(変圧器結合は別経路)。

    chubu+kyushu は直接タイが無いので、stitch 規則を単独で検証できる。
    """
    nodes = [
        {"id": "a", "lat": 37.0, "lon": 140.0, "kv": 500, "region": "chubu", "name": "A"},
        {"id": "b", "lat": 37.00005, "lon": 140.00005, "kv": 66, "region": "kyushu", "name": "B"},
    ]
    conn = compute_connectivity(nodes, [])
    assert conn["meta"]["components"]["west"] == 2
    assert conn["meta"]["n_stitch"] == 0


def test_ac_tie_connects_same_island_pair():
    """OCCTO AC タイ(ic_002 東北-東京)が同一島の region 対を連結する。"""
    nodes = [
        {"id": "a", "lat": 37.5, "lon": 140.9, "kv": 500, "region": "tohoku", "name": "相馬変電所"},
        {"id": "b", "lat": 37.0, "lon": 140.5, "kv": 500, "region": "tokyo", "name": "新いわき変電所"},
    ]
    conn = compute_connectivity(nodes, [])
    # 離れていてもタイで連結(stitchは効かない距離)→ east 1成分・n_tie>=1
    assert conn["meta"]["n_tie"] >= 1
    assert conn["meta"]["components"]["east"] == 1


def test_ac_tie_definitions_single_source():
    """ACタイ定義は national.load_interconnections に一本化(6本・東北東京+西内)。

    2026-08-19 正本化(介入#33)で 7→6: ic_005 中部北陸間は南福光BTB(非同期)、
    ic_007 関西四国間は紀伊水道直流(HVDC)と判明して AC から外れ、欠落していた
    ic_010 北陸関西間(越前嶺南線)が加わった。非同期側は 4 本になる。
    """
    ac, asyncs = load_interconnections()
    assert len(ac) == 6
    assert len(asyncs) == 4
    ids = {t["id"] for t in ac}
    assert "ic_002" in ids  # 東北-東京
