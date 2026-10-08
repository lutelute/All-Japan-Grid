"""構造DB(node-breaker)の資産品質ゲート — build_structures_batch の回帰保証.

資産の不変条件(オーナー指示 2026-07-02「構造的に資産になりうるDBに」):
  1. 全数生成: 全 substation feature が例外ゼロでレコード化
  2. 参照整合性: vl_id 参照に dangling ゼロ
  3. 決定性: 同一入力 → 同一出力(構造部)
  4. 接続レコード: 両端束縛の線からサイト間接続が導出される
  5. 回帰 pin: okinawa の構造数(意図的なモデル改善時のみ更新すること)

okinawa(最小地域・~0.1s)で全ゲートを実行する。
"""
import json

import pytest

from scripts.build_structures_batch import (
    build_region,
    check_integrity,
    payload_dict,
)


@pytest.fixture(scope="module")
def okinawa():
    structures, conns, report = build_region("okinawa")
    return structures, conns, report


def test_full_coverage_no_errors(okinawa):
    """ゲート1: 全数生成・例外ゼロ。"""
    _s, _c, rep = okinawa
    assert rep["n_errors"] == 0, rep["errors"]
    assert rep["n_sites"] + rep["dup_features"] == rep["n_features"]


def test_referential_integrity(okinawa):
    """ゲート2: dangling 参照ゼロ。"""
    structures, _c, _r = okinawa
    for s in structures:
        assert check_integrity(s) == [], s.site.site_id


def test_determinism(okinawa):
    """ゲート3: 再生成で構造部がバイト一致。"""
    structures, conns, _r = okinawa
    s2, c2, _ = build_region("okinawa")
    a = json.dumps(payload_dict("okinawa", structures, conns),
                   ensure_ascii=False, sort_keys=True)
    b = json.dumps(payload_dict("okinawa", s2, c2),
                   ensure_ascii=False, sort_keys=True)
    assert a == b


def test_connections_derived(okinawa):
    """ゲート4: 接続レコードが導出され、必須フィールドを持つ。"""
    _s, conns, _r = okinawa
    assert len(conns) > 0
    for c in conns[:20]:
        assert c["from_site"] != c["to_site"]
        assert c["from_binding"] and c["to_binding"]
        assert 0 < c["confidence"] <= 1.0


def test_terminal_provenance(okinawa):
    """全 Terminal が根拠(binding)と信頼度を持つ(捏造禁止の構造保証)。"""
    structures, _c, _r = okinawa
    allowed = {"vertex-shared", "polygon", "leadin", "name-evidence", "manual"}
    for s in structures:
        for t in s.terminals:
            assert t.binding in allowed
            assert 0 < t.confidence <= 1.0


def test_regression_pin_okinawa(okinawa):
    """ゲート5: 回帰 pin(モデル改善で意図的に変える時のみ更新)。"""
    _s, conns, rep = okinawa
    # 2026-10-07 更新: 母線・ベイの帰属を敷地の多角形で決めるよう直した(旧: 外接矩形+約1km)。
    # 津花波変電所が 0.6 km 離れた西原変電所のベイ 7 本を自分のものにし、そこに刺さる線で
    # 西原~津花波 などの架空の接続を 4 件作っていた。旧pin: 60/167/59
    # (2026-08-27 の OSM 再取得時の旧pin: 59/164/54)
    assert rep["n_sites"] == 60
    assert rep["n_terminals"] == 165
    assert len(conns) == 55


def test_internal_ways_belong_to_one_site(okinawa):
    """母線・ベイは 1 つの敷地にだけ帰属する(隣の変電所と二重に数えない)。"""
    structures, _c, rep = okinawa
    owner = {}
    for s in structures:
        for x in s.busbars + s.bays:
            for k in x.osm_way_keys:
                assert owner.setdefault(k, s.site.site_id) == s.site.site_id, k
    by_name = {s.site.name: s for s in structures}
    assert not by_name["津花波変電所"].bays           # 0.6 km 先の西原のベイを取らない
    assert len(by_name["西原変電所"].bays) == 7       # 柵の外 33 m まで描かれたベイは残す
    m = rep["internal_way_membership"]
    assert m.get("bay:partly_covered", 0) > 0
