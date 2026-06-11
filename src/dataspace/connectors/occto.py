"""OCCTO web-kohyo（系統情報公表）コネクタ — エリア需給の公開CSV。

main側セッションで疎通実証済みのAPI（IMPROVEMENT_LOG ⑲: 登録不要・
30分値・保持窓~14ヶ月、jhSybt=02=エリア需要実測 / 04=連系線潮流計画）。
集計実績は docs/reports/occto_calibration_2026-06-11.json。

契約上、生CSVは保存・再配布しない。返すのは日別に整形した30分値系列
または期間統計のみ（redistribute_derived=true の範囲）。

エンドポイントの細部（フォームパラメータ）は OCCTO 側の改修で変わり得る
ため、query の ``endpoint``/``params`` で上書き可能にしてある。疎通不可時は
HTTPステータスを添えて明示的に失敗する。
"""

from __future__ import annotations

import csv
import io
from typing import Any, Dict

from src.utils.logging_config import get_logger

logger = get_logger(__name__)

# エリア名（OCCTO CSVの表記）→ AGJ地域キー
AREA_TO_REGION = {
    "北海道": "hokkaido", "東北": "tohoku", "東京": "tokyo",
    "中部": "chubu", "北陸": "hokuriku", "関西": "kansai",
    "中国": "chugoku", "四国": "shikoku", "九州": "kyushu",
    "沖縄": "okinawa",
}

DEFAULT_ENDPOINT = "https://web-kohyo.occto.or.jp/kks-web-public/dl/csv"


class OcctoConnector:
    """query:
        kind: "area_demand"（jhSybt=02） | "interconnector_flow"（04）
        date_from / date_to: "YYYY-MM-DD"
        endpoint / params: 省略可（API改修時の上書き口）
        stat: "series"（既定: 日別30分値） | "summary"（中央値/p95/max）
    """

    def fetch(self, query: Dict[str, Any], contract) -> Any:
        import requests

        kind = query.get("kind", "area_demand")
        jh = {"area_demand": "02", "interconnector_flow": "04"}.get(kind)
        if jh is None:
            raise ValueError(f"occto connector: unknown kind '{kind}'")
        endpoint = query.get("endpoint", DEFAULT_ENDPOINT)
        params = dict(query.get("params") or {})
        params.setdefault("jhSybt", jh)
        params.setdefault("dateFrom", query.get("date_from"))
        params.setdefault("dateTo", query.get("date_to"))

        logger.info("occto fetch %s %s", endpoint, params)
        resp = requests.get(endpoint, params=params, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(
                f"occto connector: HTTP {resp.status_code} from {endpoint} — "
                f"エンドポイント仕様が変わった可能性。query['endpoint']/"
                f"['params'] で上書きして再試行してください"
            )
        resp.encoding = resp.apparent_encoding or "shift_jis"
        return self.parse_area_csv(resp.text, stat=query.get("stat", "series"))

    @staticmethod
    def parse_area_csv(text: str, stat: str = "series") -> Dict[str, Any]:
        """OCCTOエリア需給CSV（ヘッダにエリア名列を含む形式）をパースする。

        返却: {region: [MW...]}（series）または {region: {median,p95,max,n}}。
        列構成のゆらぎに対し「エリア名を含む列を需要値として拾う」寛容パース。
        """
        reader = csv.reader(io.StringIO(text))
        rows = [r for r in reader if r]
        if not rows:
            return {}
        header = rows[0]
        col_of: Dict[str, int] = {}
        for i, h in enumerate(header):
            for area, region in AREA_TO_REGION.items():
                if area in h and region not in col_of:
                    col_of[region] = i
        series: Dict[str, list] = {r: [] for r in col_of}
        for row in rows[1:]:
            for region, i in col_of.items():
                if i < len(row):
                    try:
                        series[region].append(float(row[i].replace(",", "")))
                    except ValueError:
                        continue
        if stat == "series":
            return series
        out = {}
        for region, vals in series.items():
            if not vals:
                continue
            sv = sorted(vals)
            out[region] = {
                "n": len(sv),
                "median": sv[len(sv) // 2],
                "p95": sv[int(len(sv) * 0.95)],
                "max": sv[-1],
            }
        return out
