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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_PATH = os.path.join(ROOT, "data", "transformer_sources.jsonl")

REQUIRED_FIELDS = [
    "site_key", "name", "field", "value", "unit",
    "source_type", "source_url", "source_title", "quote",
    "retrieved_at", "confidence", "collected_by", "status",
]
VALID_STATUS = {"existing", "planned"}
VALID_FIELDS = {"sn_mva", "n_units", "sn_total_mva", "hv_kv", "lv_kv",
                "tap_min", "tap_max", "tap_neutral", "tap_step_percent"}
VALID_SOURCE_TYPES = {"official", "gov", "ir", "wikipedia", "news", "other"}
VALID_CONFIDENCE = {"high", "medium", "low"}
URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_record(rec):
    """1レコード検証。(ok, reasons)。capacity_provenance と同一の拒否規約。"""
    reasons = []
    for f in REQUIRED_FIELDS:
        if f not in rec or rec[f] in (None, ""):
            reasons.append(f"missing-{f}")
    if reasons:
        return False, reasons
    if rec["field"] not in VALID_FIELDS:
        reasons.append("bad-field")
    try:
        float(rec["value"])
    except (TypeError, ValueError):
        reasons.append("value-not-number")
    if rec["source_type"] not in VALID_SOURCE_TYPES:
        reasons.append("bad-source-type")
    if not URL_RE.match(str(rec["source_url"]).strip()):
        reasons.append("source_url-not-http")
    if len(str(rec["quote"]).strip()) < 2:
        reasons.append("quote-too-short")
    if not DATE_RE.match(str(rec["retrieved_at"])):
        reasons.append("bad-date")
    if rec["confidence"] not in VALID_CONFIDENCE:
        reasons.append("bad-confidence")
    if rec["status"] not in VALID_STATUS:
        reasons.append("bad-status")
    if ":" not in str(rec["site_key"]):
        reasons.append("site_key-not-region-qualified")
    return not reasons, reasons


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


def by_site(path=SOURCES_PATH):
    """site_key -> {field: [records]} (適用側の入口)。"""
    out = {}
    for rec in load_records(path):
        out.setdefault(rec["site_key"], {}).setdefault(
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
