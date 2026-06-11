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

# 実証済みエンドポイント（main側 fetch_occto_kohyo.py / IMPROVEMENT_LOG ⑲）。
# 日付は YYYY/MM/DD 形式、User-Agent 必須（無いと拒否されるOverpass同様の慣行）
DEFAULT_ENDPOINT = (
    "https://web-kohyo.occto.or.jp/kks-web-public/download/downloadCsv"
)
_UA = {"User-Agent": "All-Japan-Grid dataspace (research; contact in repo)"}


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
        params.setdefault(
            "tgtYmdFrom", str(query.get("date_from", "")).replace("-", "/"))
        params.setdefault(
            "tgtYmdTo", str(query.get("date_to", "")).replace("-", "/"))

        logger.info("occto fetch %s %s", endpoint, params)
        resp = requests.get(endpoint, params=params, headers=_UA, timeout=120)
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
        """OCCTOエリア需給CSV（jhSybt=02、実構造=行指向）をパースする。

        実フォーマット（2026-06実測）: 1行目=UPDATEスタンプ、2行目=ヘッダ
        （「エリア名」「エリア需要(MW)」列を含む）、以降 1行=時刻×エリア。
        ヘッダ名でindexを特定するため列の追加・並び替えに頑健。

        返却: {region: [MW...]}（時刻順series）または
        {region: {n, median, p95, max}}（summary）。
        """
        reader = csv.reader(io.StringIO(text))
        rows = [r for r in reader if r]
        # ヘッダ行（「エリア名」を含む行）を探す（先頭はUPDATEスタンプ等）
        h_idx = next(
            (i for i, r in enumerate(rows) if any("エリア名" in c for c in r)),
            None,
        )
        if h_idx is None:
            return {}
        header = rows[h_idx]
        try:
            i_area = next(i for i, c in enumerate(header) if "エリア名" in c)
            i_dem = next(i for i, c in enumerate(header)
                         if "エリア需要" in c)
        except StopIteration:
            return {}
        series: Dict[str, list] = {}
        for row in rows[h_idx + 1:]:
            if len(row) <= max(i_area, i_dem):
                continue
            region = AREA_TO_REGION.get(row[i_area].strip())
            if region is None:
                continue
            try:
                val = float(row[i_dem].replace(",", ""))
            except ValueError:
                continue
            series.setdefault(region, []).append(val)
        if stat == "series":
            return series
        out = {}
        for region, vals in series.items():
            sv = sorted(vals)
            out[region] = {
                "n": len(sv),
                "median": sv[len(sv) // 2],
                "p95": sv[min(int(len(sv) * 0.95), len(sv) - 1)],
                "max": sv[-1],
            }
        return out
