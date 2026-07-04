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
    """planned(整備計画)は現況モデルに適用されない(東北の計画サイト)。

    西山形は 2026-07-04 に既設(existing=増強前値 275/154 300MVA×2)を得たため
    このリストから卒業。existing/planned の峻別は下の
    test_before_value_applied_nishi_yamagata が検証する。
    """
    from scripts.build_structures_batch import build_region
    structures, _conns, _rep = build_region("tohoku")
    for s in structures:
        if s.site.name in ("東花巻変電所", "岩手変電所"):
            for tr in s.transformers:
                assert tr.source != "nameplate", s.site.name


def test_before_value_applied_nishi_yamagata():
    """増強前値(existing)は適用され、同サイトのplanned(将来値)は適用されない。

    西山形: 既設 275/154 300MVA×2(existing) / 昇圧後 500/154 450MVA×2(planned,
    2031年度以降)。TransformerSpec には 300 が入り 450 が入らないこと=峻別の核心。
    """
    from scripts.build_structures_batch import build_region
    structures, _conns, _rep = build_region("tohoku")
    ny = next(s for s in structures if s.site.name == "西山形変電所")
    plated = [t for t in ny.transformers if t.source == "nameplate"]
    assert plated, "西山形に existing 銘板が適用されていない"
    assert plated[0].sn_mva == 300.0          # 既設値(planned の 450 ではない)
    assert plated[0].n_parallel == 2


def test_normalize_site_key_matching():
    """OSM表記ゆれ(「新生駒 変電所」等の空白・全角)を照合時に吸収する。

    構造DBには「新生駒 変電所」(スペース入り)が実在し、素朴な文字列一致では
    レコード(「新生駒変電所」)が永久に当たらない。正本は書き換えず照合側で吸収。
    """
    import json
    from scripts.transformer_provenance import by_site, normalize_site_key

    assert (normalize_site_key("kansai:新生駒 変電所")
            == normalize_site_key("kansai:新生駒変電所"))
    assert normalize_site_key("tokyo:新野田　変電所") == "tokyo:新野田変電所"
    assert normalize_site_key("kyushu:１/２号 開閉所") == "kyushu:1/2号開閉所"


def test_by_site_normalized(tmp_path):
    """by_site(normalize=True) は表記ゆれキーを同一実体に統合する。"""
    import json
    from scripts.transformer_provenance import by_site

    r1 = _good()
    r1["site_key"] = "kansai:新生駒変電所"
    r2 = _good()
    r2["site_key"] = "kansai:新生駒 変電所"
    r2["field"], r2["value"], r2["unit"] = "n_units", 3, "units"
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                           for r in (r1, r2)) + "\n")
    merged = by_site(path=str(p), normalize=True)
    assert set(merged) == {"kansai:新生駒変電所"}
    assert set(merged["kansai:新生駒変電所"]) == {"sn_mva", "n_units"}
