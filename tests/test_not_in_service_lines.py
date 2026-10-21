"""介入#23 の台帳(data/reference/not_in_service_lines.json)と照合(2026-10-21).

台帳は「供用していない線(建設中・計画・廃止)」を潮流で止める。行ごとに一次資料の出典と逐語引用が要る。
照合を部分一致だけにしていたので、「青梅線（廃線）」を足すと同じ鉄塔で使われている
「東京西線;青梅線（廃線）」(約 1,000 MW)まで止まるところだった(docs/reports/unbuilt_retired_lines_2026-10-21.md)。
"""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LEDGER = json.loads((ROOT / "data" / "reference" / "not_in_service_lines.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("rule", LEDGER["lines"], ids=lambda r: r.get("real_name", "")[:20])
def test_every_rule_has_a_primary_source(rule):
    assert rule.get("source_url") and rule.get("quote"), rule.get("real_name")
    m = rule["match"]
    assert ("name_equals" in m) != ("name_contains" in m), "照合は name_equals か name_contains のどちらか 1 つ"


def test_exact_match_does_not_stop_shared_tower_lines():
    from src.powerflow.full_from_built import nis_rule_matches
    rule = next(r for r in LEDGER["lines"] if r["match"].get("name_equals") == "青梅線（廃線）")
    assert nis_rule_matches(rule, "青梅線（廃線）", 275.0)
    assert not nis_rule_matches(rule, "東京西線;青梅線（廃線）", 275.0), "同じ鉄塔の東京西線は使われている"
    assert not nis_rule_matches(rule, "青梅線（廃線）", 66.0)


def test_rules_hit_the_canon_as_intended():
    """正典で当たる枝の数を固定する(当たり過ぎ・外れを防ぐ)。"""
    from src.powerflow.full_from_built import nis_rule_matches
    built = json.loads((ROOT / "docs" / "data" / "built" / "all.json").read_text(encoding="utf-8"))
    hits = {r["real_name"][:6]: 0 for r in LEDGER["lines"]}
    for e in built["edges"]:
        for r in LEDGER["lines"]:
            if nis_rule_matches(r, e.get("name"), float(e.get("kv") or 0) or float(r["match"].get("kv", 0))):
                hits[r["real_name"][:6]] += 1
    assert hits["旧 青梅線 "] == 3          # 単独名の 3 本だけ(併記の 2 本は当たらない)
    assert hits["西谷八幡線（"] == 6        # 中国・九州の二重抽出 3 組
    assert hits["佐久間東幹線"] == 1        # 新ルートの 1 本(合成名の 66 kV 区間は当たらない)
