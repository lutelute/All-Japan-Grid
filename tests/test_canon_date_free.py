"""正典と追跡している台帳が、再生成した日によって変わらないこと(2026-10-24)。

それまで正典の注記(#44 の par_note・#34 第三波の disclosure)に実行日が入り、ノード衛生の台帳には
実行時刻が入っていた。同じ日に 2 回流せばバイト一致するが、別の日(別の人)が流すと一致しない。
注記の日付は介入の採用日(固定)にし、台帳には時刻を書かない。
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILT = ROOT / "docs" / "data" / "built" / "all.json"
DATE = re.compile(r"20\d\d-\d\d-\d\d")


def test_canon_notes_carry_only_adoption_dates():
    edges = json.loads(BUILT.read_text(encoding="utf-8"))["edges"]
    par = {d for e in edges if (n := e.get("par_note")) for d in DATE.findall(n)}
    third = {d for e in edges if e.get("recovery") == "osm_chain3" for d in DATE.findall(e.get("disclosure", ""))}
    assert par <= {"2026-09-02"}, par
    assert third <= {"2026-09-02"}, third


def test_step_scripts_do_not_stamp_run_dates_into_the_canon():
    acs = (ROOT / "scripts/apply_circuit_sources.py").read_text(encoding="utf-8")
    tw = (ROOT / "scripts/hunt_fragment_third_wave.py").read_text(encoding="utf-8")
    nh = (ROOT / "scripts/apply_node_hygiene.py").read_text(encoding="utf-8")
    assert 'f"介入#44 {args.date}' not in acs
    assert "第三波 {args.date}" not in tw
    assert "datetime.now" not in nh


def test_hygiene_ledgers_have_no_run_timestamps():
    for name in ("mixed_pref_ledger.json", "uniform_freq_ledger.json"):
        p = ROOT / "docs" / "data" / "fragments" / name
        if p.exists():
            runs = json.loads(p.read_text(encoding="utf-8")).get("runs", [])
            assert all("at" not in r for r in runs), name
