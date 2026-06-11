"""MSM（気象庁メソ数値予報モデル GPV）コネクタ — 所在ガード付きIF。

設計（docs/DATA_SPACE.md §4）: MSMアーカイブ（GRIB2、TB級）は研究室NASに
留め、ここでは**地域集約済みのCF系列のみ**を生成・返却する。集約処理は
NASをマウントしたホスト（pws-160core等）で実行する前提。

所在は契約の ``location: env:AJGRID_MSM_ROOT`` で指す。未設定の場合は
**設定方法を案内して明示的に失敗**する — 暗黙にどこかへ取りに行かない。

Phase 2 実装予定（NAS所在の確定後）:
- query: {kind: "regional_cf", variable: "dswrf"|"u10v10",
          period: "fy2023"|[start,end], regions: [...]}
- 処理: GRIB2読込(pygrib/cfgrib) → 地域bboxマスク平均 →
  dswrf→太陽光CF（パネル温度補正は簡易） / 風速→パワーカーブCF
- 返却: {region: [hourly CF ...]}（数百KB、redistribute_derived=true）
"""

from __future__ import annotations

import os
from typing import Any, Dict


class MSMConnector:
    def fetch(self, query: Dict[str, Any], contract) -> Any:
        root = contract.resolve_location()
        if not root:
            raise RuntimeError(
                "MSM connector: アーカイブの所在が未設定です。\n"
                "  データは源泉（研究室NAS）に留める設計のため、暗黙の取得は"
                "行いません。\n"
                "  設定方法: NASをマウントしたホストで環境変数 "
                "AJGRID_MSM_ROOT=/path/to/msm を設定して実行してください\n"
                "  （例: pws-160core で NASマウント先を指定）。"
            )
        if not os.path.isdir(root):
            raise RuntimeError(
                f"MSM connector: AJGRID_MSM_ROOT={root} がディレクトリとして"
                f"見つかりません。"
            )
        raise NotImplementedError(
            "MSM regional aggregation is Phase 2 — "
            "docs/DATA_SPACE.md §6 のとおりNAS所在の確定後に実装します "
            f"(root={root} は確認済み)。"
        )
