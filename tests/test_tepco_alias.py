"""端点別名表（介入#44 の端点解決・2026-09-03 F2）のゲート。

公表資料の端点表記はモデルの変電所名と一致しないことがある。実測（未解決 1,454 種）の内訳は
匿名コード 1,344 / 構造マーカー 348 / 正典に不在 453 / 電圧階級違い 42 / 地域違い 53 で、
**別名で解けるのは九州の設備番号プレフィックス**（「32武雄」= 設備番号32 + 武雄変電所）だけ。
匿名コードと不在は原理的に解けないので別名を作らない（捏造禁止）。

このテストは (a) 別名表のスキーマ (b) 別名で端点が解決される (c) low は既定で使わない
(d) 別名表が無くても従来どおり動く (e) 同じ alias に別の model_name が付いていない、を固定する。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ALIAS = ROOT / "data" / "reference" / "tepco_endpoint_aliases.json"
VALID_CONF = {"high", "medium", "low"}


def _acs():
    spec = importlib.util.spec_from_file_location(
        "acs_under_test", ROOT / "scripts" / "apply_circuit_sources.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["acs_under_test"] = m
    spec.loader.exec_module(m)
    return m


def _doc():
    if not ALIAS.exists():
        pytest.skip("別名表が無い")
    return json.loads(ALIAS.read_text(encoding="utf-8"))


# ── (a) スキーマ ────────────────────────────────────────────────────────
def test_alias_schema_is_complete_and_evidenced():
    doc = _doc()
    assert doc.get("_meta"), "_meta が無い（何のための表かが書かれていない）"
    for e in doc["aliases"]:
        for k in ("alias", "model_name", "region", "evidence", "evidence_type",
                  "confidence", "resolved_by"):
            assert e.get(k) not in (None, ""), f"{e.get('alias')}: {k} が空"
        assert e["confidence"] in VALID_CONF, f"{e['alias']}: confidence={e['confidence']}"
        assert len(e["evidence"]) >= 20, f"{e['alias']}: 根拠が短すぎる（1行の説明では検証できない）"


def test_every_alias_target_exists_in_canon():
    """別名の行き先が正典に実在すること（存在しない変電所へ寄せない）。"""
    doc = _doc()
    acs = _acs()
    built_p = ROOT / "docs" / "data" / "built" / "all.json"
    if not built_p.exists():
        pytest.skip("正典が無い")
    model = acs.Model(json.loads(built_p.read_text(encoding="utf-8")))
    missing = [e["alias"] for e in doc["aliases"] if not model.sub_index.get(e["model_name"])]
    assert missing == [], f"行き先が正典に無い別名: {missing[:8]}"


# ── (e) 重複 ────────────────────────────────────────────────────────────
def test_no_alias_maps_to_two_targets():
    doc = _doc()
    seen: dict[tuple, str] = {}
    dup = []
    for e in doc["aliases"]:
        key = (e["region"], e["alias"], e.get("kv"))
        if key in seen and seen[key] != e["model_name"]:
            dup.append((key, seen[key], e["model_name"]))
        seen[key] = e["model_name"]
    assert dup == [], f"同じ別名に別の行き先: {dup[:5]}"


# ── (b) 解決 ────────────────────────────────────────────────────────────
def test_alias_resolves_numbered_prefix_endpoint():
    acs = _acs()
    al = acs.EndpointAliases()
    if not al.n_entries:
        pytest.skip("別名表が空")
    doc = _doc()
    e = doc["aliases"][0]
    got = al.resolve(e["alias"], e["region"], None)
    assert got == e["model_name"], f"{e['alias']} が解決されない: {got}"
    # 別名でない名前はそのまま返る
    assert al.resolve("信貴変電所", "kansai", 500.0) == "信貴変電所"


def test_non_endpoint_and_anonymized_are_classified():
    acs = _acs()
    al = acs.EndpointAliases()
    if al.non_endpoint is None:
        pytest.skip("別名表が無い")
    for nm in ("需要家", "需要家分岐", "開放点", "発電所分岐", "山梨線#29", "島2L2分岐から"):
        assert al.classify(nm) == "non-endpoint marker", f"{nm} が構造マーカーと分類されない"
    for nm in ("北CZ", "奈AT", "BF", "姫CE"):
        assert al.classify(nm) == "anonymized endpoint code", f"{nm} が匿名コードと分類されない"
    # 本物の変電所名は素通り
    assert al.classify("武雄") is None
    assert al.classify("新豊洲") is None


# ── (c) low は既定で使わない ────────────────────────────────────────────
def test_low_confidence_is_skipped_by_default(tmp_path):
    acs = _acs()
    doc = {"aliases": [
        {"alias": "テスト高", "model_name": "武雄", "region": "kyushu", "kv": None,
         "evidence": "テスト用の高信頼エントリ（20文字以上の根拠）", "evidence_type": "test",
         "confidence": "high", "resolved_by": "test"},
        {"alias": "テスト低", "model_name": "武雄", "region": "kyushu", "kv": None,
         "evidence": "テスト用の低信頼エントリ（20文字以上の根拠）", "evidence_type": "test",
         "confidence": "low", "resolved_by": "test"},
    ]}
    p = tmp_path / "a.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    default = acs.EndpointAliases(path=p, use_low=False)
    assert default.n_entries == 1 and default.n_skipped_low == 1
    assert default.resolve("テスト低", "kyushu", None) == "テスト低", "low が既定で使われた"
    assert default.resolve("テスト高", "kyushu", None) == "武雄"

    opted = acs.EndpointAliases(path=p, use_low=True)
    assert opted.n_entries == 2 and opted.n_skipped_low == 0
    assert opted.resolve("テスト低", "kyushu", None) == "武雄"


def test_entry_without_evidence_is_ignored(tmp_path):
    """根拠の無い行は読み込まない（捏造を表に持ち込ませない）。"""
    acs = _acs()
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"aliases": [
        {"alias": "根拠なし", "model_name": "武雄", "region": "kyushu",
         "confidence": "high"},
    ]}, ensure_ascii=False), encoding="utf-8")
    al = acs.EndpointAliases(path=p)
    assert al.n_entries == 0
    assert al.resolve("根拠なし", "kyushu", None) == "根拠なし"


# ── (d) 表が無くても動く ────────────────────────────────────────────────
def test_missing_table_is_a_no_op(tmp_path):
    acs = _acs()
    al = acs.EndpointAliases(path=tmp_path / "does_not_exist.json")
    assert al.n_entries == 0
    assert al.non_endpoint is None and al.anonymized is None
    assert al.resolve("需要家", "tokyo", 66.0) == "需要家"       # 素通り
    assert al.classify("需要家") is None                          # 分類もしない
