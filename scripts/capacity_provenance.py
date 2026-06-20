#!/usr/bin/env python3
"""発電所の発電量・容量を **出典必須(provenance-first)** で記録する DB。

設計意図 (オーナー指示 2026-06-20)
----------------------------------
「発電量や容量が上手く入っていないのをスクリーニングして、web から情報を集めてくるとき、
**嘘をつかず必ず引用となるように DB を作っておく**」。

= 値(value)を単独で持たせない。**必ず (出典URL, 原文引用) とセット**で記録し、
それが欠けた値は機械的に拒否する。これにより「モデル(LLM)が記憶から数値を捏造する」
経路を構造的に封じる。各値は人が source_url を開いて quote を照合し検証できる。

正本ファイル: data/generator_capacity_sources.jsonl (1値1行・git追跡・diff可読)

レコード schema (全フィールド必須):
  plant_key    : 発電所の安定キー(例 "p03:kyushu_gen_0917" / "osm:川内原子力:31.83,130.19")
  name         : 発電所名(人間可読)
  field        : 対象量 ("capacity_mw" | "unit_capacity_mw" | "p_min_mw" ...)
  value        : 数値
  unit         : 単位 ("MW")
  source_type  : 出典種別 (official|gov|ir|wikipedia|news|p03|osm|other)
  source_url   : http(s):// の実URL (捏造防止の要=空・非URLは拒否)
  source_title : 出典ページ名
  quote        : 値の根拠となる **原文抜粋** (空は拒否=値の出所が辿れないため)
  retrieved_at : 取得日 (YYYY-MM-DD)
  confidence   : high|medium|low (一次情報=high / 二次=medium / 推定=low)
  collected_by : 収集者 (モデル名 or 人名)
  note         : 任意の補足(換算式 "89万kW×2基=1780MW" 等)。省略可。

使い方:
  from capacity_provenance import validate_record, append_records, verify_file
  append_records(PATH, [rec, ...])     # 検証を通った行だけ追記、rejectは戻り値に
  python scripts/capacity_provenance.py verify   # 正本ファイルを全行検証
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_PATH = os.path.join(ROOT, "data", "generator_capacity_sources.jsonl")

REQUIRED_FIELDS = [
    "plant_key", "name", "field", "value", "unit",
    "source_type", "source_url", "source_title", "quote",
    "retrieved_at", "confidence", "collected_by",
]
VALID_SOURCE_TYPES = {"official", "gov", "ir", "wikipedia", "news", "p03", "osm", "other"}
VALID_CONFIDENCE = {"high", "medium", "low"}
URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_record(rec):
    """1レコードを検証。戻り値 (ok: bool, reasons: list[str])。

    捏造防止の核心:
      - source_url が実 http(s) URL でなければ拒否(=出所のない値を入れない)
      - quote(原文抜粋) が空なら拒否(=値の根拠が辿れない)
      - value が数値でなければ拒否
    これらを満たさないレコードは DB に入れない。
    """
    reasons = []
    if not isinstance(rec, dict):
        return False, ["not a dict"]
    for k in REQUIRED_FIELDS:
        if k not in rec or rec[k] is None or (isinstance(rec[k], str) and not rec[k].strip()):
            reasons.append(f"missing:{k}")
    if reasons:
        return False, reasons

    # 値は数値
    try:
        float(rec["value"])
    except (TypeError, ValueError):
        reasons.append("value-not-numeric")

    # 出典 URL は実 http(s)（捏造防止の要）
    if not URL_RE.match(str(rec["source_url"]).strip()):
        reasons.append("source_url-not-http")

    # 引用(原文)は実体のある長さ
    if len(str(rec["quote"]).strip()) < 2:
        reasons.append("quote-too-short")

    if rec["source_type"] not in VALID_SOURCE_TYPES:
        reasons.append(f"bad-source_type:{rec['source_type']}")
    if rec["confidence"] not in VALID_CONFIDENCE:
        reasons.append(f"bad-confidence:{rec['confidence']}")
    if not DATE_RE.match(str(rec["retrieved_at"]).strip()):
        reasons.append("retrieved_at-not-YYYY-MM-DD")

    return (len(reasons) == 0), reasons


def load_records(path=SOURCES_PATH):
    """正本 jsonl を読み込む(壊れた行はスキップしログ)。戻り値 list[dict]。"""
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"[warn] line {i}: invalid JSON skipped ({exc})", file=sys.stderr)
    return out


def append_records(records, path=SOURCES_PATH):
    """検証を通ったレコードだけを追記する。捏造値は弾く。

    戻り値: {"accepted": int, "rejected": [(rec, reasons), ...]}。
    """
    accepted, rejected = [], []
    for rec in records:
        ok, reasons = validate_record(rec)
        (accepted if ok else rejected).append(rec if ok else (rec, reasons))
    if accepted:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for rec in accepted:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"accepted": len(accepted), "rejected": rejected}


def verify_file(path=SOURCES_PATH):
    """正本ファイル全行を検証。戻り値 (n_ok, n_bad, problems)。"""
    recs = load_records(path)
    n_ok, problems = 0, []
    for i, rec in enumerate(recs, 1):
        ok, reasons = validate_record(rec)
        if ok:
            n_ok += 1
        else:
            problems.append((i, rec.get("name", "?"), reasons))
    return n_ok, len(problems), problems


def _cli():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if cmd == "verify":
        n_ok, n_bad, problems = verify_file()
        print(f"verify {SOURCES_PATH}: ok={n_ok} bad={n_bad}")
        for ln, name, reasons in problems[:50]:
            print(f"  line {ln} [{name}]: {reasons}")
        return 0 if n_bad == 0 else 1
    if cmd == "selftest":
        # 捏造防止が効くことの自己実証(出典なし値は拒否される)
        good = {
            "plant_key": "p03:test", "name": "テスト発電所", "field": "capacity_mw",
            "value": 1780, "unit": "MW", "source_type": "official",
            "source_url": "https://example.com/plant", "source_title": "公式",
            "quote": "出力 89万kW×2基", "retrieved_at": "2026-06-20",
            "confidence": "high", "collected_by": "selftest",
        }
        bad_no_url = dict(good, source_url="")           # 出典URL欠落
        bad_no_quote = dict(good, quote="")              # 引用欠落
        bad_fake_url = dict(good, source_url="記憶による")  # 非URL(捏造)
        for label, rec in [("good", good), ("no_url", bad_no_url),
                           ("no_quote", bad_no_quote), ("fake_url", bad_fake_url)]:
            ok, reasons = validate_record(rec)
            print(f"  {label:9} -> {'ACCEPT' if ok else 'REJECT'} {reasons}")
        return 0
    print(f"usage: {sys.argv[0]} [verify|selftest]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli())
