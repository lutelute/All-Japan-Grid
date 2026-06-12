"""JEPX スポット価格コネクタ — nas03/PWS_DB の spot_summary_{年度}.csv。

`price_raw/jepx/spot_summary_{YYYY}.csv`（年度ファイル、30分48コマ、
システムプライス+エリアプライス9地域、円/kWh）から **必要な月・エリア
のみ** を返す（zero-copy）。タスク#12（経済停止の構造要因分解）の入力:
市場価格分布から実勢SRMC（coal/lngの限界費用クラスタ）を推定し、
UCの fuel_cost 較正の出典にする。

所在は nas03 と同一NAS — 契約 `jepx_spot` の location（env:AJGRID_NAS03_ROOT）。
"""

from __future__ import annotations

import io
from typing import Any, Dict

from src.dataspace.connectors.nas03 import _read_remote
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

# CSVヘッダのエリア名 → AGJ地域キー
AREA_COLS = {
    "エリアプライス北海道": "hokkaido", "エリアプライス東北": "tohoku",
    "エリアプライス東京": "tokyo", "エリアプライス中部": "chubu",
    "エリアプライス北陸": "hokuriku", "エリアプライス関西": "kansai",
    "エリアプライス中国": "chugoku", "エリアプライス四国": "shikoku",
    "エリアプライス九州": "kyushu",
}


class JepxConnector:
    """query:
        fiscal_year: 年度ファイル（spot_summary_{fy}.csv。FY2025=2025）
        month: 省略可 'YYYYMM' — 受渡日の年月で絞る
        area: 省略可 AGJ地域キー（'tohoku' 等） — 省略時はsystem+全エリア
    返却: {"fiscal_year", "month", "n_rows",
           "rows": [{"date", "slot", "system", <area>: 円/kWh...}...]}
    """

    def fetch(self, query: Dict[str, Any], contract) -> Any:
        import csv as _csv

        fy = int(query["fiscal_year"])
        month = str(query.get("month", "") or "")
        area = str(query.get("area", "") or "")
        root = contract.resolve_location()
        if not root:
            raise RuntimeError(
                "JEPXの所在が未設定 — AJGRID_NAS03_ROOT を設定してください"
                "（nas03_generation_records と同一NAS）")
        raw = _read_remote(root, f"price_raw/jepx/spot_summary_{fy}.csv")
        text = None
        for enc in ("utf-8-sig", "cp932"):
            try:
                cand = raw.decode(enc)
            except UnicodeDecodeError:
                continue
            if "受渡日" in cand:
                text = cand
                break
        if text is None:
            text = raw.decode("cp932", errors="replace")

        reader = _csv.reader(io.StringIO(text))
        rows_in = list(reader)
        header = rows_in[0]
        i_date = next(i for i, c in enumerate(header) if "受渡日" in c)
        i_slot = next(i for i, c in enumerate(header) if "時刻コード" in c)
        i_sys = next(i for i, c in enumerate(header)
                     if "システムプライス" in c)
        area_idx = {}
        for i, c in enumerate(header):
            for jp, key in AREA_COLS.items():
                if jp in c:
                    area_idx[key] = i
        want_areas = [area] if area else list(area_idx)

        out = []
        for r in rows_in[1:]:
            if len(r) <= i_sys or not r[i_date].strip():
                continue
            date_s = r[i_date].strip()         # "2025/08/06"
            if month and date_s.replace("/", "")[:6] != month:
                continue
            try:
                rec: Dict[str, Any] = {
                    "date": date_s,
                    "slot": int(r[i_slot]),
                    "system": float(r[i_sys]),
                }
                for key in want_areas:
                    idx = area_idx.get(key)
                    if idx is not None and idx < len(r) and r[idx].strip():
                        rec[key] = float(r[idx])
            except ValueError:
                continue
            out.append(rec)

        logger.info("jepx fetch FY%d month=%s area=%s: %d rows",
                    fy, month or "*", area or "*", len(out))
        return {"fiscal_year": fy, "month": month or None,
                "n_rows": len(out), "rows": out}
