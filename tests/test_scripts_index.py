"""scripts/ の索引の「状態」の欄(2026-10-24・全体構造の台帳 B2・C2・C5)."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_curated_status_names_exist():
    d = yaml.safe_load((ROOT / "scripts" / "script_status.yaml").read_text(encoding="utf-8"))
    for label, items in d.items():
        assert label in ("退役", "比較用", "記録"), label
        for name, why in items.items():
            assert (ROOT / "scripts" / name).is_file(), f"{name} が scripts/ に無い"
            assert why, f"{name} に理由が無い"


def test_status_rules():
    import scripts.scripts_index as si
    entries, curated, cards = si.entry_text(), si.curated_status(), si.card_text()
    st = lambda n: si.status_of(ROOT / "scripts" / n, entries, curated, cards)[0]
    assert st("export_matpower_canonical.py") == "現役"          # 正典の手順・CLI が呼ぶ
    assert st("realtime_publish.sh") == "現役"
    assert st("uc_to_pf.py") == "退役"                           # 台帳で指定
    assert st("export_generators_geojson.py") == "起動不可"      # src.parser が無い(C2)
    assert st("run_cpf.py") == "旧系譜"                          # カードはあるが旧系譜(と注記)
