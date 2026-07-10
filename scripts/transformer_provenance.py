#!/usr/bin/env python3
"""変電所の変圧器(容量・台数・タップ)を **出典必須** で記録する DB — Phase B 本命.

オーナー指示(2026-07-02)「本命化=変圧器の実データ化。DB進めて」。
capacity_provenance(発電容量の45件実証・オーナー規約 2026-06-20「嘘をつかず必ず
引用となるように」)と**同一の捏造防止規約**を変圧器に適用する:

  値を単独で持たせない。必ず (source_url, 原文引用 quote) とセットで記録し、
  欠けた値は機械的に拒否する。「LLMが記憶から数値を書く」経路を構造的に封じる。

正本ファイル: data/transformer_sources.jsonl (1値1行・git追跡・diff可読)

レコード schema (note 以外すべて必須):
  site_key     : 変電所の安定キー "region:変電所名" (例 "kansai:嶺南変電所")
  name         : 変電所名(人間可読)
  field        : 対象量
                 "sn_mva"           変圧器1台の定格容量(MVA)
                 "n_units"          変圧器台数
                 "sn_total_mva"     合計容量(MVA)
                 "hv_kv"/"lv_kv"    一次/二次電圧(kV)
                 "tap_min"/"tap_max"/"tap_neutral"  タップ位置
                 "tap_step_percent" タップ刻み(%)
  value        : 数値
  unit         : 単位 ("MVA"|"units"|"kV"|"tap"|"percent")
  source_type  : official|gov|ir|wikipedia|news|other
  source_url   : http(s):// の実URL (捏造防止の要)
  source_title : 出典ページ名
  quote        : 値の根拠となる原文抜粋 (空は拒否)
  retrieved_at : 取得日 YYYY-MM-DD
  confidence   : high|medium|low
  collected_by : 収集者 (モデル名 or 人名)
  status       : existing|planned (既設か整備計画か。**applyはexistingのみ使用**。
                 planned は将来断面の資産として保持)
  note         : 補足(換算 "1,000MVA×3台"・使用開始年度・転載禁止資料は引用最小の旨等)。省略可。

使い方:
  python scripts/transformer_provenance.py verify
  from scripts.transformer_provenance import append_records, load_records
"""
import json
import os
import re
import sys
import unicodedata

try:  # scripts が package として見えるか(root on path)否か両対応の薄いラッパ
    from scripts.provenance import ProvenanceSpec, validate
except ModuleNotFoundError:  # scripts ディレクトリのみ path に載る実行(直接起動)
    from provenance import ProvenanceSpec, validate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_PATH = os.path.join(ROOT, "data", "transformer_sources.jsonl")


def normalize_site_key(key):
    """site_key 照合用の正規化 (NFKC + 空白除去)。

    OSM由来のサイト名には「新生駒 変電所」のような空白入りが実在し、
    レコード側の「新生駒変電所」と照合できない。表記ゆれ(全角英数・空白)を
    吸収して同一実体に当てるための正規化。正本の site_key 自体は書き換えない。
    """
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(key)))

# 変圧器出典の系統仕様。捏造防止の核心は scripts/provenance.validate が持ち、
# ここは変圧器固有の差分(site_key の region 修飾必須・existing/planned の status・
# 電気量 field の白リスト)だけを宣言する薄いラッパ。
SPEC = ProvenanceSpec(
    key_field="site_key",
    valid_source_types=frozenset(
        {"official", "gov", "ir", "wikipedia", "news", "other"}),
    extra_required=("unit", "source_title"),
    valid_fields=frozenset(
        {"sn_mva", "n_units", "sn_total_mva", "hv_kv", "lv_kv",
         "tap_min", "tap_max", "tap_neutral", "tap_step_percent"}),
    require_status=True,
    valid_status=frozenset({"existing", "planned"}),
    require_region_qualified_key=True,
)


def validate_record(rec):
    """1レコード検証。(ok, reasons)。capacity_provenance と同一の拒否規約。

    捏造防止規約の実体は :func:`scripts.provenance.validate`(単一実装)。
    """
    return validate(rec, SPEC)


def load_records(path=SOURCES_PATH):
    out = []
    if not os.path.exists(path):
        return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"[warn] broken line skipped: {line[:60]}",
                      file=sys.stderr)
    return out


def append_records(records, path=SOURCES_PATH):
    """検証を通った行だけ追記。(n_appended, rejected[(rec, reasons)])。"""
    ok_rows, rejected = [], []
    for rec in records:
        ok, reasons = validate_record(rec)
        (ok_rows if ok else rejected).append((rec, reasons))
    with open(path, "a") as f:
        for rec, _ in ok_rows:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    return len(ok_rows), [(r, why) for r, why in rejected]


def verify_file(path=SOURCES_PATH):
    recs = load_records(path)
    bad = []
    for i, rec in enumerate(recs):
        ok, reasons = validate_record(rec)
        if not ok:
            bad.append((i, reasons))
    return len(recs), bad


def by_site(path=SOURCES_PATH, normalize=False):
    """site_key -> {field: [records]} (適用側の入口)。

    normalize=True で正規化キー(normalize_site_key)に統合する。
    構造DB照合(apply_transformer_provenance)はこちらを使う。
    """
    out = {}
    for rec in load_records(path):
        key = normalize_site_key(rec["site_key"]) if normalize else rec["site_key"]
        out.setdefault(key, {}).setdefault(
            rec["field"], []).append(rec)
    return out


def _cli():
    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        n, bad = verify_file()
        print(f"records={n} invalid={len(bad)}")
        for i, reasons in bad[:10]:
            print(f"  line {i}: {reasons}")
        sys.exit(1 if bad else 0)
    print(__doc__)


if __name__ == "__main__":
    _cli()
