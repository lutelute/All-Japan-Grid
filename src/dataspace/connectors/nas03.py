"""nas03 (PWS_DB) コネクタ — エリア需給実績（電源種別・30分/1時間値）。

研究室NAS pws-nas03 の `/volume1/PWS_DB/demand_raw/{company}/` から
**必要な月のCSVだけ** を取得し、正規形（時刻×正規燃料キーのMW平均）で返す
（zero-copy原則 / docs/UC_VALIDATION_PLAN.md §2.2）。

所在は ``AJGRID_NAS03_ROOT``（契約カタログの env: 参照）:
- ``ssh://user@host/path`` — ssh cat で取得（既定。研究室Tailscale経由）
- ローカルパス — pws-gpu3060 の /mnt/nas03 等のマウント済み環境

形式（2026-06-12 実地調査）:
- 新形式（2024-04〜、5社で互換確認: hokkaido/tohoku/tepco/hokuriku/shikoku）:
  ``DATE,TIME,エリア需要,原子力,火力(LNG),火力(石炭),火力(石油),火力(その他),
  [火力出力制御量,]水力,地熱,バイオマス,[バイオマス出力制御量,]太陽光発電実績,
  太陽光出力制御量,風力発電実績,風力出力制御量,揚水,蓄電池,連系線,その他,合計``
  （hokkaido は制御量2列が多い → 列名マップで吸収。CP932・30分値MW平均）
- 旧形式（〜2024-03）は火力が合算列 — Phase B で対応（PLAN §3）
"""

from __future__ import annotations

import io
import os
import subprocess
from typing import Any, Dict

from src.utils.logging_config import get_logger

logger = get_logger(__name__)

# CSV列名（部分一致） → 正規燃料キー
_FUEL_COLUMNS = {
    "エリア需要": "demand",
    "原子力": "nuclear",
    "火力(LNG)": "lng",
    "火力(石炭)": "coal",
    "火力(石油)": "oil",
    "火力(その他)": "thermal_other",
    "水力": "hydro",
    "地熱": "geothermal",
    "バイオマス": "biomass",
    "太陽光発電実績": "solar",
    "太陽光出力制御量": "solar_curtailed",
    "風力発電実績": "wind",
    "風力出力制御量": "wind_curtailed",
    "揚水": "pumped_hydro",
    "蓄電池": "battery",
    "連系線": "interconnector",
    "その他": "other",
    # chugoku別名（「需給実績」形式: DATE,TIME + 需要/火力合算/括弧表記）
    "需要": "demand",
    "火力": "thermal_combined",
    "太陽光(実績)": "solar",
    "太陽光(抑制量)": "solar_curtailed",
    "風力(実績)": "wind",
    "風力(抑制量)": "wind_curtailed",
    "連系線潮流": "interconnector",
}
# 「バイオマス出力制御量」等が「バイオマス」に部分一致しないよう長い順に照合
_FUEL_KEYS_ORDERED = sorted(_FUEL_COLUMNS, key=len, reverse=True)

# PWS_DB の会社ディレクトリ名 → AGJ地域キー
COMPANY_TO_REGION = {
    "hokkaido": "hokkaido", "tohoku": "tohoku", "tepco": "tokyo",
    "chubu": "chubu", "hokuriku": "hokuriku", "kansai": "kansai",
    "chugoku": "chugoku", "shikoku": "shikoku", "kyushu": "kyushu",
    "okinawa": "okinawa",
}


def _read_remote(root: str, relpath: str) -> bytes:
    """AJGRID_NAS03_ROOT の形式に応じて CSV バイト列を取得する。"""
    if root.startswith("ssh://"):
        rest = root[len("ssh://"):]
        host, _, base = rest.partition("/")
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=15", "-o", "BatchMode=yes",
             host, f"cat /{base}/{relpath}"],
            capture_output=True, timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"nas03 ssh cat failed ({relpath}): "
                f"{result.stderr.decode(errors='replace')[:200]}")
        return result.stdout
    path = os.path.join(root, relpath)
    with open(path, "rb") as f:
        return f.read()


class Nas03Connector:
    """query:
        company: PWS_DB の会社キー（'hokuriku' 等、COMPANY_TO_REGION参照）
        month: 'YYYYMM'（新形式の在庫がある月）
        date: 省略可 'YYYY-MM-DD' — 指定日のみに絞る
    返却: {"region", "company", "month", "rows": [{"dt", fuel: mw, ...}...],
           "fuels": [...], "n_rows": int}
    （30分値MW平均の行リスト。再配布可能な集約・正規化済み形式）
    """

    def fetch(self, query: Dict[str, Any], contract) -> Any:
        import csv as _csv

        company = str(query["company"])
        month = str(query["month"])
        if company not in COMPANY_TO_REGION:
            raise ValueError(f"nas03: unknown company '{company}'")
        root = contract.resolve_location()
        if not root:
            raise RuntimeError(
                "nas03の所在が未設定 — 環境変数 AJGRID_NAS03_ROOT を設定して"
                "ください（例: ssh://pwslab@100.102.148.23/volume1/PWS_DB、"
                "マウント済み環境では /mnt/nas03）。暗黙のフォールバックは"
                "しない方針（DATA_SPACE.md §4）")
        candidates = [f"demand_raw/{company}/{month}.csv"]
        # kyushu等の四半期ファイル命名（2023_3Q.csv / 2023_Q4.csv 混在）:
        # FY四半期(4-6=1Q…1-3=4Q)と暦四半期の両解釈を候補に足す
        y, m = int(month[:4]), int(month[4:6])
        fq = (m - 4) // 3 % 4 + 1 if m >= 4 else 4
        cq = (m - 1) // 3 + 1
        fy = y if m >= 4 else y - 1
        for name in (f"{fy}_{fq}Q", f"{fy}_Q{fq}", f"{y}_Q{cq}",
                     f"{y}_{cq}Q"):
            candidates.append(f"demand_raw/{company}/{name}.csv")
        raw = None
        last_err = None
        for rel in candidates:
            try:
                raw = _read_remote(root, rel)
                break
            except (RuntimeError, FileNotFoundError) as exc:
                last_err = exc
        if raw is None:
            raise RuntimeError(
                f"nas03: {company} {month} のファイルが見つからない "
                f"(tried {len(candidates)}): {last_err}")
        # tepco月次はUTF-8-SIG、他社はCP932 — 「エリア需要」が読める方を採用
        # （CP932固定だとtepcoの列名が化けてdemand列が消え全行棄却になる）
        text = None
        for enc in ("utf-8-sig", "cp932"):
            try:
                cand = raw.decode(enc)
            except UnicodeDecodeError:
                continue
            if "エリア需要" in cand:
                text = cand
                break
        if text is None:
            text = raw.decode("cp932", errors="replace")

        reader = _csv.reader(io.StringIO(text))
        rows_in = [r for r in reader if r]
        h_idx = next((i for i, r in enumerate(rows_in)
                      if r and r[0].strip() == "DATE"), None)
        if h_idx is None:
            # kansai旧形式（Phase B）: DATE_TIME 1列・1時間値MWh・火力合算。
            # 列位置固定（2行ヘッダで7-10列目の実績/抑制は1行目の
            # 太陽光/風力と組合せ — 位置で確定する方が頑健）
            kx = next((i for i, r in enumerate(rows_in)
                       if r and r[0].strip() == "DATE_TIME"), None)
            if kx is None:
                raise RuntimeError(
                    f"nas03: {company}/{month}.csv のヘッダが未知形式 — "
                    f"DATE/TIME でも DATE_TIME でもない")
            KANSAI_COLS = ["demand", "nuclear", "thermal_combined", "hydro",
                           "geothermal", "biomass", "solar",
                           "solar_curtailed", "wind", "wind_curtailed",
                           "pumped_hydro", "interconnector"]
            want_date = str(query.get("date", "")).replace("-", "/")
            want_alt = None
            if want_date:
                y, m, d = want_date.split("/")
                want_alt = f"{y}/{int(m)}/{int(d)}"
            out_rows = []
            for r in rows_in[kx + 1:]:
                if len(r) < 3 or not r[0].strip():
                    continue
                dt_s = r[0].strip()           # "2023/12/13 0:00"
                date_part = dt_s.split()[0]
                if want_date and date_part not in (want_date, want_alt):
                    continue
                rec: Dict[str, Any] = {"dt": dt_s}
                ok = False
                for i, fuel in enumerate(KANSAI_COLS, start=1):
                    if i >= len(r):
                        continue
                    v = r[i].strip().replace(",", "")
                    if v in ("", "－", "-"):
                        continue
                    try:
                        rec[fuel] = float(v)   # 1時間値MWh = MW平均と同値
                        ok = True
                    except ValueError:
                        continue
                if ok and "demand" in rec:
                    out_rows.append(rec)
            fuels = sorted({k for rec in out_rows for k in rec if k != "dt"})
            logger.info("nas03 fetch %s/%s (legacy DATE_TIME): %d rows",
                        company, month, len(out_rows))
            return {
                "region": COMPANY_TO_REGION[company],
                "company": company,
                "month": month,
                "date": str(query.get("date", "")) or None,
                "format": "legacy_datetime",
                "n_rows": len(out_rows),
                "fuels": fuels,
                "rows": out_rows,
            }
        header = rows_in[h_idx]
        col_map: Dict[int, str] = {}
        for i, col in enumerate(header):
            c = col.strip()
            for key in _FUEL_KEYS_ORDERED:
                if key in c:
                    # 「バイオマス出力制御量」等、キー側に無い制御量列が
                    # 本体キー（バイオマス）へ部分一致して値を上書きする
                    # のを防ぐ（hokkaido変種で実害を確認）
                    if "出力制御量" in c and "出力制御量" not in key:
                        break
                    col_map[i] = _FUEL_COLUMNS[key]
                    break

        want_date = str(query.get("date", "")).replace("-", "/")
        # "2025/08/06" と "2025/8/6" の両表記に対応
        want_alt = None
        if want_date:
            y, m, d = want_date.split("/")
            want_alt = f"{y}/{int(m)}/{int(d)}"

        out_rows = []
        for r in rows_in[h_idx + 1:]:
            if len(r) < 3 or not r[0].strip():
                continue
            date_s = r[0].strip()
            if want_date and date_s not in (want_date, want_alt):
                continue
            rec: Dict[str, Any] = {"dt": f"{date_s} {r[1].strip()}"}
            ok = False
            for i, fuel in col_map.items():
                if i >= len(r):
                    continue
                v = r[i].strip().replace(",", "")
                if v in ("", "－", "-"):
                    continue
                try:
                    rec[fuel] = float(v)
                    ok = True
                except ValueError:
                    continue
            if ok and "demand" in rec:
                out_rows.append(rec)

        fuels = sorted({k for rec in out_rows for k in rec if k != "dt"})
        logger.info("nas03 fetch %s/%s: %d rows, fuels=%s",
                    company, month, len(out_rows), fuels)
        return {
            "region": COMPANY_TO_REGION[company],
            "company": company,
            "month": month,
            "date": str(query.get("date", "")) or None,
            "n_rows": len(out_rows),
            "fuels": fuels,
            "rows": out_rows,
        }
