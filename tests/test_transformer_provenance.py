"""変圧器出典DB(Phase B)の品質ゲート — 捏造防止規約と正典伝播の回帰保証.

規約(capacity_provenance と同一・オーナー 2026-06-20/07-02):
  値は必ず (source_url, 原文引用 quote) とセット。欠けたら機械的 REJECT。
  planned(整備計画)は正本に保持するが現況モデルへは適用しない。
"""
import pytest

from scripts.transformer_provenance import (
    SOURCES_PATH,
    append_records,
    load_records,
    validate_record,
    verify_file,
)


def _good():
    return {
        "site_key": "kansai:テスト変電所", "name": "テスト変電所",
        "field": "sn_mva", "value": 750, "unit": "MVA",
        "source_type": "official", "source_url": "https://example.com/x",
        "source_title": "公式", "quote": "各 750MVA",
        "retrieved_at": "2026-07-02", "confidence": "high",
        "collected_by": "test", "status": "existing",
    }


def test_reject_without_provenance():
    """捏造防止: URL/引用/statusの欠落・不正を機械的に拒否。"""
    ok, _ = validate_record(_good())
    assert ok
    for mutate, reason in [
        (lambda r: r.update(source_url=""), "missing-source_url"),
        (lambda r: r.update(source_url="記憶による"), "source_url-not-http"),
        (lambda r: r.update(quote=""), "missing-quote"),
        (lambda r: r.update(status="rumor"), "bad-status"),
        (lambda r: r.update(field="magic"), "bad-field"),
        (lambda r: r.update(site_key="信貴"), "site_key-not-region-qualified"),
    ]:
        r = _good()
        mutate(r)
        ok, reasons = validate_record(r)
        assert not ok and reason in reasons


def test_sources_file_all_valid():
    """正本 jsonl は全行が検証を通る(壊れた値の混入ゼロ)。"""
    n, bad = verify_file(SOURCES_PATH)
    assert n >= 31          # パイロット31行(信貴既設+東北計画)以上
    assert bad == []


def test_apply_to_structure_db_shigi():
    """existing レコードが構造DBの TransformerSpec に伝播する(信貴 pin)。"""
    from scripts.build_structures_batch import build_region
    structures, _conns, rep = build_region("kansai")
    assert rep["n_trafo_nameplate"] >= 1
    shigi = next(s for s in structures if s.site.name == "信貴変電所")
    tr = next(t for t in shigi.transformers if t.source == "nameplate")
    assert tr.sn_mva == 750.0
    assert tr.n_parallel == 3
    assert "jstage" in (tr.note or "")


def test_planned_not_applied():
    """planned(整備計画)は現況モデルに適用されない(東北の計画6サイト)。"""
    from scripts.build_structures_batch import build_region
    structures, _conns, _rep = build_region("tohoku")
    for s in structures:
        if s.site.name in ("東花巻変電所", "岩手変電所", "西山形変電所"):
            for tr in s.transformers:
                assert tr.source != "nameplate", s.site.name
