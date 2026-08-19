#!/usr/bin/env python3
"""各社「エリア需給実績」(燃料別・30分値)の取得 → zone×hour×燃料MW.

オーナー方針(2026-08-19): 時事(原発停止等)はニュースを手で追わず、一次データ
(公表実績)から自動反映する。手法(a)「エリア需給実績の燃料別注入」の取得器。

取得可能性(2026-08-19実地確認・全URLは実fetchで検証済み):
  月次CSV(当月ファイルが日次更新・前日分まで):
    tokyo(03)/chubu(04)/hokuriku(05)/chugoku(07)/shikoku(08)/kyushu(09)
    = eria_jukyu_YYYYMM_NN.csv
  tohoku(02) = 同形式だが公表が約2か月遅れ(2026-08時点で6月分まで)
  hokkaido   = 日別ファイル YYYYMMDD_hokkaido_jukyu.csv(当日も随時更新)
  kansai     = jisseki.json(当日のみ・万kW・30分48枠) → 日々の蓄積で埋める
  okinawa    = 燃料別の機械可読公表を未特定(独立島・ほぼ火力のみ) → 対象外

出力: data/realtime/fuelmix_YYYYMMDD.json (untracked・蓄積)
  {date, unit:"MW", zones:{zone:{fuels:{fuel:[24h MW]}, source_url, updated}}}
  既存ファイルにはzone単位でマージ(関西の当日蓄積が翌日消えないように)。

燃料キーはnas03コネクタ(src/dataspace/connectors/nas03.py)と同じ正規化:
  demand, nuclear, lng, coal, oil, thermal_other, hydro, geothermal, biomass,
  solar, solar_curtailed, wind, wind_curtailed, pumped_hydro, battery,
  interconnector, other  (揚水・蓄電池は負値=充電)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import time
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "realtime"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

# 列名(部分一致)→正規燃料キー。順序が重要: 「太陽光出力制御量」を「太陽光発電実績」
# より先に判定する(部分一致の誤爆防止)。nas03コネクタと同じ語彙。
FUEL_COLUMNS = [
    ("エリア需要", "demand"),
    ("原子力", "nuclear"),
    ("火力(LNG)", "lng"),
    ("火力(石炭)", "coal"),
    ("火力(石油)", "oil"),
    ("火力(その他)", "thermal_other"),
    ("火力出力制御量", "thermal_curtailed"),
    ("水力", "hydro"),
    ("地熱", "geothermal"),
    ("バイオマス出力制御量", "biomass_curtailed"),
    ("バイオマス", "biomass"),
    ("太陽光出力制御量", "solar_curtailed"),
    ("太陽光抑制量", "solar_curtailed"),      # hokkaido方言
    ("太陽光発電実績", "solar"),
    ("太陽光実績", "solar"),                  # hokkaido方言
    ("風力出力制御量", "wind_curtailed"),
    ("風力抑制量", "wind_curtailed"),         # hokkaido方言
    ("風力発電実績", "wind"),
    ("風力実績", "wind"),                     # hokkaido方言
    ("揚水", "pumped_hydro"),
    ("蓄電池", "battery"),
    ("連系線", "interconnector"),
    ("その他", "other"),
    ("合計", "total"),
]

MONTHLY = {
    "tokyo": "https://www.tepco.co.jp/forecast/html/images/eria_jukyu_{ym}_03.csv",
    "chubu": "https://powergrid.chuden.co.jp/denki_yoho_content_data/eria_jukyu_{ym}_04.csv",
    "hokuriku": "https://www.rikuden.co.jp/nw/denki-yoho/csv/eria_jukyu_{ym}_05.csv",
    "chugoku": "https://www.energia.co.jp/nw/jukyuu/sys/eria_jukyu_{ym}_07.csv",
    "shikoku": "https://www.yonden.co.jp/nw/supply_demand/csv/eria_jukyu_{ym}_08.csv",
    "kyushu": "https://www.kyuden.co.jp/td_area_jukyu/csv/eria_jukyu_{ym}_09.csv",
    "tohoku": "https://setsuden.nw.tohoku-epco.co.jp/common/demand/eria_jukyu_{ym}_02.csv",
}
HOKKAIDO = "https://denkiyoho.hepco.co.jp/area/data/{ymd}_hokkaido_jukyu.csv"
KANSAI_TODAY = ("https://www.kansai-td.co.jp/interchange/denkiyoho/"
                "area-performance/jisseki.json")
# 関西jisseki.jsonの系列名 → 正規キー(値は万kW→×10でMW)
KANSAI_NAMES = {
    "demand": "demand", "nuclear": "nuclear", "geothermal": "geothermal",
    "hydroelectric": "hydro", "lng": "lng", "coal": "coal", "oil": "oil",
    "other_thermal": "thermal_other", "biomass": "biomass", "wind": "wind",
    "solar": "solar", "pumped": "pumped_hydro", "battery": "battery",
    "interconnection": "interconnector", "others": "other",
}


def _get(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
        for enc in ("cp932", "utf-8-sig", "utf-8"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("cp932", errors="replace")
    except Exception as ex:  # noqa: BLE001
        print(f"  ! {url.rsplit('/', 1)[-1]}: {ex}")
        return None


def parse_eria_csv(text: str, target: dt.date) -> dict | None:
    """eria_jukyu形式CSV → {fuel: [24h MW]}。30分値は時間平均。

    方言吸収: 列名はNFKC正規化(九州の全角「火力（ＬＮＧ）」等・中部CSVで既知の罠)、
    ヘッダは DATE / 年月日 の両様式、日付は YYYY/MM/DD・YYYY/M/D・YYYYMMDD の3様式。
    """
    lines = text.splitlines()
    header = None
    for ln in lines:
        norm = unicodedata.normalize("NFKC", ln)
        if norm.startswith("DATE") or norm.startswith('"DATE') \
                or norm.startswith("年月日"):
            header = [unicodedata.normalize("NFKC", c).strip('"').strip()
                      for c in ln.split(",")]
            break
    if header is None:
        return None
    colmap = {}   # index -> fuel key
    for i, name in enumerate(header):
        for kw, key in FUEL_COLUMNS:
            if kw in name:
                colmap[i] = key
                break
    tgts = {target.strftime("%Y/%m/%d"),
            f"{target.year}/{target.month}/{target.day}",
            target.strftime("%Y%m%d")}
    slot: dict[str, dict[int, list]] = {}
    for ln in lines:
        ps = [c.strip('"') for c in ln.split(",")]
        if len(ps) < 3 or ps[0] not in tgts:
            continue
        m = re.match(r"(\d+):", ps[1])
        if not m:
            continue
        h = int(m.group(1))
        for i, key in colmap.items():
            if i >= len(ps):
                continue
            try:
                v = float(ps[i])
            except ValueError:
                continue
            slot.setdefault(key, {}).setdefault(h, []).append(v)
    if not slot.get("demand"):
        return None
    out = {}
    for key, hh in slot.items():
        arr = [None] * 24
        for h, vs in hh.items():
            if 0 <= h < 24 and vs:
                arr[h] = round(sum(vs) / len(vs), 1)
        out[key] = arr
    return out


def fetch_kansai_today() -> tuple[dict | None, str | None]:
    """関西jisseki.json(当日・万kW・48枠) → ({fuel:[24h MW]}, 日付文字列)。"""
    txt = _get(KANSAI_TODAY)
    if not txt:
        return None, None
    try:
        d = json.loads(txt)
    except json.JSONDecodeError:
        return None, None
    date_s = (d.get("date") or "")[:10].replace("-", "/")
    out = {}
    for it in d.get("list", []):
        key = KANSAI_NAMES.get(it.get("name"))
        if not key:
            continue
        vals = it.get("value") or []
        arr = [None] * 24
        for h in range(24):
            two = [v for v in vals[2 * h:2 * h + 2] if v is not None]
            if two:
                arr[h] = round(sum(two) / len(two) * 10.0, 1)  # 万kW→MW
        out[key] = arr
    return (out if out.get("demand") else None), date_s


def fetch_date(date: dt.date) -> dict:
    """{zone: {fuels, source_url, updated}} — 取れたzoneのみ。"""
    ym, ymd = date.strftime("%Y%m"), date.strftime("%Y%m%d")
    zones: dict[str, dict] = {}
    for zone, pat in MONTHLY.items():
        url = pat.format(ym=ym)
        txt = _get(url)
        time.sleep(0.5)
        if not txt:
            continue
        fuels = parse_eria_csv(txt, date)
        if fuels:
            zones[zone] = {"fuels": fuels, "source_url": url,
                           "updated": dt.datetime.now().isoformat(timespec="seconds")}
    url = HOKKAIDO.format(ymd=ymd)
    txt = _get(url)
    if txt:
        fuels = parse_eria_csv(txt, date)
        if fuels:
            zones["hokkaido"] = {"fuels": fuels, "source_url": url,
                                 "updated": dt.datetime.now().isoformat(timespec="seconds")}
    # 関西: 当日のみ配信 — 要求日が今日のときだけ
    if date == dt.date.today():
        fuels, date_s = fetch_kansai_today()
        if fuels and date_s == date.strftime("%Y/%m/%d"):
            zones["kansai"] = {"fuels": fuels, "source_url": KANSAI_TODAY,
                               "updated": dt.datetime.now().isoformat(timespec="seconds")}
    return zones


def merge_kohyo04(cur: dict, date: dt.date) -> None:
    """島間連系(FC・北本)の計画潮流をfuelmix jsonへ追記(in-place)。"""
    flows = fetch_kohyo04_flows(date)
    if flows:
        cur["interconnectors"] = {
            "flows": flows,
            "source_url": KOHYO04.format(d=date.strftime("%Y/%m/%d")),
            "note": "OCCTO系統情報公表04・順方向計画潮流(順: fc=東京→中部/"
                    "hokuhon=北海道→東北)・30分値の時間平均",
        }


# OCCTO系統情報公表(種別04)= 連系線の運用容量・計画潮流(30分値・当日あり)。
# 島間連系(FC・北本)の計画潮流を日付断面の境界注入に使う(UTF-8 BOM・順方向
# 計画潮流=8列目。順方向の定義: FC=東京→中部 / 北本=北海道→東北、
# boundary.py _OCCTO_IC の検証済み対応と同じ)
KOHYO04 = ("https://web-kohyo.occto.or.jp/kks-web-public/download/"
           "downloadCsv?jhSybt=04&tgtYmdFrom={d}&tgtYmdTo={d}")
KOHYO04_LINKS = {"周波数変換設備": "fc", "北海道・本州間電力連系設備": "hokuhon"}


def fetch_kohyo04_flows(date: dt.date) -> dict | None:
    """{link_key: [24h 順方向計画潮流MW]}(時間平均)。取れなければNone。"""
    url = KOHYO04.format(d=date.strftime("%Y/%m/%d"))
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            txt = r.read().decode("utf-8-sig", errors="replace")
    except Exception as ex:  # noqa: BLE001
        print(f"  ! kohyo04: {ex}")
        return None
    tgt = date.strftime("%Y/%m/%d")
    slot: dict[str, dict[int, list]] = {}
    for ln in txt.splitlines():
        ps = [c.strip('"') for c in ln.split(",")]
        if len(ps) < 9 or ps[0] != tgt:
            continue
        key = KOHYO04_LINKS.get(ps[2])
        if not key:
            continue
        m = re.match(r"(\d+):", ps[1])
        if not m:
            continue
        try:
            v = float(ps[7])   # 順方向計画潮流(MW)
        except ValueError:
            continue
        slot.setdefault(key, {}).setdefault(int(m.group(1)), []).append(v)
    if not slot:
        return None
    out = {}
    for key, hh in slot.items():
        arr = [None] * 24
        for h, vs in hh.items():
            if 0 <= h < 24 and vs:
                arr[h] = round(sum(vs) / len(vs), 1)
        out[key] = arr
    return out


def load_fuelmix(date_str: str) -> dict | None:
    """蓄積済み fuelmix_YYYYMMDD.json を読む(無ければNone)。"""
    p = STORE / f"fuelmix_{date_str}.json"
    if p.exists():
        return json.loads(p.read_text())
    return None


def ensure_fuelmix(date_str: str) -> dict | None:
    """蓄積を読み、無ければその場でfetchして保存して返す(export側の入口)。"""
    cur = load_fuelmix(date_str)
    if cur and cur.get("zones"):
        return cur
    date = dt.datetime.strptime(date_str, "%Y%m%d").date()
    zones = fetch_date(date)
    if not zones:
        return cur
    STORE.mkdir(parents=True, exist_ok=True)
    cur = cur or {"date": date_str, "unit": "MW", "zones": {}}
    cur["zones"].update(zones)
    if "interconnectors" not in cur:
        merge_kohyo04(cur, date)
    (STORE / f"fuelmix_{date_str}.json").write_text(
        json.dumps(cur, ensure_ascii=False))
    return cur


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", action="append", default=None,
                    help="YYYYMMDD(複数可)。省略時=前日と当日")
    args = ap.parse_args()
    if args.date:
        dates = [dt.datetime.strptime(x, "%Y%m%d").date() for x in args.date]
    else:
        today = dt.date.today()
        dates = [today - dt.timedelta(days=1), today]
    STORE.mkdir(parents=True, exist_ok=True)
    for date in dates:
        ds = date.strftime("%Y%m%d")
        zones = fetch_date(date)
        p = STORE / f"fuelmix_{ds}.json"
        cur = {"date": ds, "unit": "MW", "zones": {},
               "note": ("各一般送配電事業者「エリア需給実績」(燃料別・30分値)を"
                        "1時間平均MW化。出典=各zonesのsource_url。負値(揚水・蓄電池)"
                        "=充電。tohokuは公表約2か月遅れ・kansaiは当日配信の蓄積・"
                        "okinawaは燃料別公表を未特定のため対象外")}
        if p.exists():
            cur = json.loads(p.read_text())
        cur["zones"].update(zones)     # zone単位マージ(既存の関西蓄積等を保持)
        merge_kohyo04(cur, date)
        p.write_text(json.dumps(cur, ensure_ascii=False))
        got = sorted(cur["zones"].keys())
        n_h = {z: sum(1 for v in cur["zones"][z]["fuels"].get("demand", [])
                      if v is not None) for z in got}
        print(f"{ds}: {len(got)}zone " +
              " ".join(f"{z}:{n_h[z]}h" for z in got))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
