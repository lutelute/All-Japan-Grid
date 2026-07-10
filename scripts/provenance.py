#!/usr/bin/env python3
"""出典必須(provenance-first)レコードの **汎用バリデータ** — 捏造防止規約の単一実装.

背景(オーナー指示 2026-06-20 / 07-02)
--------------------------------------
発電容量(capacity_provenance)と変圧器(transformer_provenance)は、いずれも
「値を単独で持たせず、必ず (出典URL, 原文引用 quote) とセットで記録し、欠けた値は
機械的に拒否する」という **同一の捏造防止規約** を実装していた。両者の
``validate_record`` はほぼ同一の二重実装だったため、ここに1本化する。

このモジュールは規約そのもの(捏造防止の核心)を持ち、系統ごとの差分
(キー名・status の有無・field 白リスト・許容 source_type 等)は
:class:`ProvenanceSpec` で表現する。系統別スクリプト
(``scripts/capacity_provenance.py`` / ``scripts/transformer_provenance.py``)は
自分の ``ProvenanceSpec`` を渡すだけの薄いラッパになる。

捏造防止の核心(全系統で不変):
  - source_url が実 http(s) URL でなければ拒否(出所のない値を入れない)
  - quote(原文抜粋) が空なら拒否(値の根拠が辿れない)
  - value が数値でなければ拒否
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import FrozenSet, List, Optional, Tuple

URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 全出典レコードが共有する必須欄(値の出所が辿れることの最小集合)。
# 系統固有のキー(site_key/plant_key)・単位・タイトルは ProvenanceSpec で足す。
BASE_REQUIRED: Tuple[str, ...] = (
    "name", "field", "value", "source_type", "source_url",
    "quote", "retrieved_at", "confidence", "collected_by",
)

DEFAULT_CONFIDENCE: FrozenSet[str] = frozenset({"high", "medium", "low"})


@dataclass(frozen=True)
class ProvenanceSpec:
    """1系統の出典スキーマの差分を記述する仕様。

    Attributes:
        key_field: 実体キーの欄名(``"site_key"`` / ``"plant_key"`` /
            汎用なら ``"entity_key"``)。必須欄に含める。
        valid_source_types: 許容する ``source_type`` の集合。
        valid_confidence: 許容する ``confidence`` の集合。
        extra_required: BASE_REQUIRED に加えて必須とする欄(例 ``("unit",
            "source_title")``)。
        valid_fields: ``field`` の白リスト。``None`` なら任意の field を許容
            (発電容量側は field を制限しない)。
        require_status: ``status`` 欄を必須・検証するか(変圧器の
            existing/planned 峻別に使う)。
        valid_status: ``require_status`` のとき許容する status 集合。
        require_region_qualified_key: キーに ``:`` を要求するか
            (``"region:名称"`` 形式の担保。変圧器の site_key で使う)。
    """

    key_field: str
    valid_source_types: FrozenSet[str]
    valid_confidence: FrozenSet[str] = DEFAULT_CONFIDENCE
    extra_required: Tuple[str, ...] = ()
    valid_fields: Optional[FrozenSet[str]] = None
    require_status: bool = False
    valid_status: FrozenSet[str] = field(default_factory=frozenset)
    require_region_qualified_key: bool = False

    @property
    def required_fields(self) -> List[str]:
        """この系統で必須となる欄の並び(欠落チェックの対象)。"""
        req = [self.key_field, *BASE_REQUIRED, *self.extra_required]
        if self.require_status:
            req.append("status")
        return req


def _is_missing(value: object) -> bool:
    """None / 空文字 / 空白のみ を「欠落」とみなす(両系統の欠落判定を統合)。"""
    return value is None or (isinstance(value, str) and not value.strip())


def validate(rec: object, spec: ProvenanceSpec) -> Tuple[bool, List[str]]:
    """1レコードを ``spec`` に照らして検証。戻り値 ``(ok, reasons)``。

    捏造防止の核心(source_url が実URL・quote が非空・value が数値)を満たさない
    レコードは DB に入れない。理由文字列は系統横断で共通(hyphen 区切り)。

    Args:
        rec: 検証対象のレコード(dict 想定)。
        spec: 系統ごとの :class:`ProvenanceSpec`。

    Returns:
        ``(ok, reasons)``。``ok`` が True のとき ``reasons`` は空。
    """
    if not isinstance(rec, dict):
        return False, ["not-a-dict"]

    reasons: List[str] = []
    for f in spec.required_fields:
        if f not in rec or _is_missing(rec[f]):
            reasons.append(f"missing-{f}")
    if reasons:
        # 必須欠落は他検査より優先(欠落したまま型検査してもノイズになる)。
        return False, reasons

    if spec.valid_fields is not None and rec["field"] not in spec.valid_fields:
        reasons.append("bad-field")
    try:
        float(rec["value"])
    except (TypeError, ValueError):
        reasons.append("value-not-number")
    if rec["source_type"] not in spec.valid_source_types:
        reasons.append("bad-source-type")
    if not URL_RE.match(str(rec["source_url"]).strip()):
        reasons.append("source_url-not-http")
    if len(str(rec["quote"]).strip()) < 2:
        reasons.append("quote-too-short")
    if not DATE_RE.match(str(rec["retrieved_at"]).strip()):
        reasons.append("bad-date")
    if rec["confidence"] not in spec.valid_confidence:
        reasons.append("bad-confidence")
    if spec.require_status and rec["status"] not in spec.valid_status:
        reasons.append("bad-status")
    if spec.require_region_qualified_key and ":" not in str(rec[spec.key_field]):
        reasons.append(f"{spec.key_field}-not-region-qualified")

    return not reasons, reasons
