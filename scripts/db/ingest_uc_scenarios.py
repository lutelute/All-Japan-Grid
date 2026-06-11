"""UCシナリオを grid.db に取り込む（YAML → DB の機械的同期）。

正本は git 追跡の config/uc_scenarios/*.yaml と data/reference/*.yaml。
このスクリプトはそれらを uc_scenarios / uc_scenario_generators テーブルに
ミラーし、下流ツールがリポジトリのconfigツリーに触れずにシナリオを
解決できるようにする（DB統一方針: 機械的に更新できる仕組み）。

使い方:
    python scripts/db/ingest_uc_scenarios.py                # 全シナリオ
    python scripts/db/ingest_uc_scenarios.py --scenario fy2023
    python scripts/db/ingest_uc_scenarios.py --db data/grid.db
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(os.path.join(os.path.dirname(__file__), "..", ".."))

import yaml  # noqa: E402

from src.db.grid_db import GridDatabase  # noqa: E402
from src.uc.scenario import SCENARIO_DIR, load_scenario_config  # noqa: E402

# 参照リスト → uc_scenario_generators の kind と行展開方法
_REFERENCE_KINDS = {
    "nuclear_status": ("operational", "name"),
    "pumped_storage": ("plants", "name"),
    "capacity_patches": ("patches", "match"),
}


def ingest_scenario(db: GridDatabase, name: str) -> dict:
    """1シナリオをDBへ同期し、件数サマリを返す。"""
    cfg = load_scenario_config(name)
    db.upsert_uc_scenario(
        cfg.name,
        config_json=json.dumps(cfg.raw, ensure_ascii=False),
        fiscal_year=cfg.fiscal_year,
        description=cfg.description,
    )

    counts: dict = {}
    for ref_key, (list_key, key_field) in _REFERENCE_KINDS.items():
        path = cfg.reference_path(ref_key)
        if not path or not os.path.exists(path):
            continue
        with open(path) as f:
            ref = yaml.safe_load(f) or {}
        entries = ref.get(list_key, [])
        for entry in entries:
            db.upsert_uc_scenario_generator(
                cfg.name,
                kind=ref_key,
                gen_key=str(entry[key_field]),
                payload_json=json.dumps(entry, ensure_ascii=False),
            )
        counts[ref_key] = len(entries)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", default="data/grid.db", help="SQLite DBパス")
    parser.add_argument("--scenario", default=None,
                        help="シナリオ名（省略時は config/uc_scenarios/ の全YAML）")
    args = parser.parse_args()

    names = (
        [args.scenario]
        if args.scenario
        else sorted(p.stem for p in Path(SCENARIO_DIR).glob("*.yaml"))
    )
    if not names:
        print(f"シナリオが見つかりません: {SCENARIO_DIR}")
        return 1

    db = GridDatabase(args.db)
    for name in names:
        counts = ingest_scenario(db, name)
        detail = ", ".join(f"{k}={v}" for k, v in counts.items())
        print(f"ingested uc_scenario '{name}' ({detail})")
    print(f"DB: {args.db} (schema v{db.get_schema_version()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
