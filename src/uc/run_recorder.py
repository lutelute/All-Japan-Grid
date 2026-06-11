"""UC実行のDB索引記録 — ベストエフォート。

docs/reports/ のレポートJSONが正本で、grid.db の ``uc_runs`` はその
機械検索可能な索引層（DB統一方針 R/C/D の D=派生）。記録に失敗しても
UC実行そのものは失敗させない — DBが無い・ロックされている環境
（CI・サーバーチャンク並列等）でも安全に呼べる。

使い方（各ドライバの json.dump 直後）::

    from src.uc.run_recorder import record_run
    record_run(out_path, kind="benchmark", run_date=meta["date"],
               scenario_id="fy2023r2", status="Optimal", ...)
"""

from __future__ import annotations

import os

from src.utils.logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_DB = os.path.join("data", "grid.db")


def record_run(report_path: str, *, kind: str, run_date: str,
               db_path: str = DEFAULT_DB, **fields: object) -> bool:
    """1実行を uc_runs へ upsert する（キー=レポートパス）。

    Args:
        report_path: 正本レポートJSONのリポジトリ相対パス。
        kind: 'benchmark' | 'annual' | 'pf_link' | 'pf_national'。
        run_date: 実行日（ISO、レポートmetaのdate）。
        db_path: grid.db のパス（テスト用に差し替え可）。
        **fields: UCRun の任意列（git_head / scenario_id /
            scenario_sha256 / demand_profile_sha / status /
            total_cost_jpy / solve_time_s / l1_total_pp / summary_json）。

    Returns:
        記録できたら True。DB不調はFalse（実行は止めない）。
    """
    try:
        from src.db.grid_db import GridDatabase

        db = GridDatabase(db_path)
        db.record_uc_run(report_path, kind=kind, run_date=run_date, **fields)
        logger.info("uc_runs recorded: %s (%s)", report_path, kind)
        return True
    except Exception as exc:  # DB欠如・ロック等 — 実行は止めない
        logger.warning("uc_runs 記録をスキップ (%s): %s",
                       type(exc).__name__, exc)
        return False
