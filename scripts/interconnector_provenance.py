#!/usr/bin/env python3
"""連系線の運用容量を **出典必須(provenance-first)** で記録する DB。

背景
----
本モデルの容量は電圧階級から機械的に振った理論値（√3·V·I）で、出典を持たなかった。
感度行列による接続可能量の算出でも「基準潮流が既に容量を超える枝がある」という形で
表面化している（`docs/reports/hosting_capacity_*.md`）。

連系線については OCCTO が**運用容量そのもの**を 30 分値で公表しており、利用条件も
「出典明記で自由利用」なので、ここだけは出典付きの実値にできる。値の抽出は
`scripts/capacity/occto_interconnector_capacity.py`。

捏造防止の規約は発電容量・変圧器と共通（`scripts/provenance.py` が単一実装）。
値を単独で持たせず、必ず (出典URL, 原文引用) とセットで記録し、欠けた値は機械的に拒否する。

正本ファイル: data/interconnector_capacity_sources.jsonl（1値1行・git追跡・diff可読）

レコード schema:
  link_key     : 連系線の安定キー（"occto:関門連系線:順方向" 形式。方向まで含める）
  name         : 連系線名（OCCTO の公表名そのまま）
  direction    : "順方向" | "逆方向"
  field        : "operational_capacity_mw"
  value        : 数値（期間中の最大運用容量）
  unit         : "MW"
  source_type  : "official"（OCCTO は一次情報）
  source_url / source_title / quote / retrieved_at / confidence / collected_by
  note         : 分布（最小・中央値・最大）と観測断面数、出典ファイル名

使い方:
  python scripts/interconnector_provenance.py verify   # 正本ファイルを全行検証
"""
import json
import os
import sys

try:
    from scripts.provenance import ProvenanceSpec, validate
except ModuleNotFoundError:
    from provenance import ProvenanceSpec, validate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_PATH = os.path.join(ROOT, "data", "interconnector_capacity_sources.jsonl")

# 連系線容量の系統仕様。運用容量は公表値なので一次情報のみを許容し、
# field は運用容量に限定する（熱容量と混ざると意味が変わるため）。
SPEC = ProvenanceSpec(
    key_field="link_key",
    valid_source_types=frozenset({"official", "gov"}),
    extra_required=("unit", "source_title", "direction"),
    valid_fields=frozenset({"operational_capacity_mw"}),
    require_region_qualified_key=True,   # "occto:名称:方向" 形式を担保
)


def validate_record(rec):
    """1レコードを検証。戻り値 (ok: bool, reasons: list[str])。"""
    return validate(rec, SPEC)


def load_records(path=SOURCES_PATH):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def verify_file(path=SOURCES_PATH):
    recs = load_records(path)
    bad = []
    for i, rec in enumerate(recs):
        ok, reasons = validate_record(rec)
        if not ok:
            bad.append((i, reasons))
    return len(recs), bad


def by_link(path=SOURCES_PATH):
    """link_key -> レコード（適用側の入口）。"""
    return {r["link_key"]: r for r in load_records(path)}


def main(argv):
    if len(argv) > 1 and argv[1] == "verify":
        n, bad = verify_file()
        if bad:
            print(f"NG {len(bad)}/{n} レコードが規約違反")
            for i, reasons in bad[:20]:
                print(f"  #{i}: {'; '.join(reasons)}")
            return 1
        print(f"OK {n} レコードすべて出典付き（URL・原文引用・数値が揃っている）")
        links = {r["name"] for r in load_records()}
        print(f"   連系線 {len(links)} 本 × 2 方向")
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
