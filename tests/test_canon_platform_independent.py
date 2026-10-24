"""正典が OS・ライブラリの版で変わらないこと(2026-10-24)。

STRtree.query は候補を木の中の順で返す。その順は OS(libc++ と libstdc++ の並べ替え)や shapely/GEOS の版で
変わる。東京の同じ形の多角形 2 つ(基底と補足の重複)のどちらに線を結ぶかが macOS と Linux で違い、CI で
作り直した正典がコミットと一致しなかった。多角形の選び方は _poly_pick(距離 → 面積 → 番号)だけにする。
ここでは、query の結果を順に依って使う書き方が戻っていないことだけを見る。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "src" / "powerflow" / "snapped_topology.py").read_text(encoding="utf-8")


def test_poly_tree_queries_go_through_the_order_independent_picker():
    uses = [ln.strip() for ln in SRC.splitlines() if "poly_tree.query(" in ln]
    unsorted = [ln for ln in uses if "sorted(" not in ln]
    assert uses and not unsorted, f"query の結果を順に依って使っている: {unsorted}"
    assert SRC.count("_poly_pick(") >= 3   # 定義 + 結び付け + 引込線


# 本当の保証は CI の reproduce-canon(Linux で作り直した正典がコミットとバイト一致するか)。
