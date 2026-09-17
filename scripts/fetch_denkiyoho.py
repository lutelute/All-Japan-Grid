#!/usr/bin/env python3
"""でんき予報(各社 当日需要実績・1時間値)の準リアルタイム取得.

オーナー指示(2026-08-18): 「DBとして、直接リアルタイムが取れるといいね」

取得: 各一般送配電事業者の「でんき予報」CSV(公表・出典明記で利用可の慣例)から
  「DATE,TIME,当日実績(万kW)」セクションを共通パーサで抽出(万kW→MW)。
蓄積: data/realtime/denkiyoho_YYYYMMDD.json(ローカル・untracked)
  ※nas03再起動期間(2026-08-19〜20頃)はローカル蓄積し、復帰後に
    nas03(pws-nas03)のAGJ領域へrsyncする(sync_realtime_to_nas.shを用意)
公開: docs/data/realtime/latest.json(zone×hourly MW+出典・取得時刻。
  でんき予報の数値はエリア合計の公表値=転載可の慣例。出典を明記)

関西: 現行でんき予報が動的配信でCSV URL未特定(juyo1_kansai.csvは2020年で凍結)
  → TODO。四国: 当日速報CSVなし・年次CSV(前日まで)で代替。
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "realtime"
PUB = ROOT / "docs" / "data" / "realtime"
# TEPCOはUA文字列の形式判定があり素朴なUAは403(2026-08-18実測) — ブラウザ形式で
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

TODAY = dt.date.today()
D = TODAY.strftime("%Y%m%d")

SOURCES = {
    "hokkaido": f"https://denkiyoho.hepco.co.jp/area/data/juyo_01_{D}.csv",
    "tohoku": f"https://setsuden.nw.tohoku-epco.co.jp/common/demand/juyo_02_{D}.csv",
    "tokyo": "https://www.tepco.co.jp/forecast/html/images/juyo-d1-j.csv",
    "chubu": "https://powergrid.chuden.co.jp/denki_yoho_content_data/juyo_cepco003.csv",
    "hokuriku": f"https://www.rikuden.co.jp/nw/denki-yoho/csv/juyo_05_{D}.csv",
    # kansai: 現行CSV URL未特定(TODO) — juyo1_kansai.csv系は更新停止を確認(2026-08-18)
    "chugoku": f"https://www.energia.co.jp/nw/jukyuu/sys/juyo_07_{D}.csv",
    "shikoku": "https://www.yonden.co.jp/nw/denkiyoho/csv/juyo_shikoku_2026.csv",
    "kyushu": f"https://www.kyuden.co.jp/td_power_usages/csv/juyo-hourly-{D}.csv",
    "okinawa": f"https://www.okiden.co.jp/denki2/juyo_10_{D}.csv",
}


def fetch(url: str) -> str | None:
    for enc in ("cp932", "utf-8"):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode(enc, errors="replace")
        except UnicodeDecodeError:
            continue
        except Exception as ex:  # noqa: BLE001
            print(f"  ! fetch失敗: {ex}")
            return None
    return None


def parse_hourly(text: str, zone: str) -> dict:
    """「DATE,TIME,当日実績(万kW)」共通セクション→ {hour:int -> MW:float}。
    四国は年次形式(日付,時刻,実績,供給力)なので当日/最新日の行を抽出。"""
    out: dict[int, float] = {}
    updated = None
    m = re.match(r"([\d/]+ [\d:]+) UPDATE", text)
    if m:
        updated = m.group(1)
    lines = text.splitlines()
    date_used = None
    if zone == "shikoku":
        # 年次形式: 2026/08/17,23:00,266,366 (実績が3列目・最新日を採用)
        rows = [ln.split(",") for ln in lines
                if re.match(r"20\d\d/\d\d?/\d\d?,\d", ln)]
        if rows:
            date_used = rows[-1][0]
            for r in rows:
                if r[0] != date_used or len(r) < 3:
                    continue
                try:
                    h = int(r[1].split(":")[0])
                    v = float(r[2])
                except ValueError:
                    continue
                if v > 0:
                    out[h] = v * 10.0  # 万kW→MW
        return {"hourly_mw": out, "updated": updated, "date": date_used}
    in_sec = False
    for ln in lines:
        if re.match(r"DATE,TIME,当日実績", ln):
            in_sec = True
            continue
        if in_sec:
            parts = ln.split(",")
            if len(parts) < 3 or not re.match(r"20\d\d/", parts[0]):
                if ln.strip() == "":
                    break
                continue
            date_used = parts[0]
            try:
                h = int(parts[1].split(":")[0])
                v = float(parts[2])
            except ValueError:
                continue
            if v > 0:  # 0=未来時刻(未実績)
                out[h] = v * 10.0
    return {"hourly_mw": out, "updated": updated, "date": date_used}


def main() -> int:
    STORE.mkdir(parents=True, exist_ok=True)
    PUB.mkdir(parents=True, exist_ok=True)
    snap = {"fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
            "unit": "MW", "zones": {}, "note": (
                "各一般送配電事業者「でんき予報」当日実績(1時間値・万kW)を10倍でMW化。"
                "出典=各社でんき予報(下記URL)。kansai=URL未特定のため未収載(TODO)・"
                "shikoku=年次CSV(前日まで)")}
    ok = 0
    for zone, url in SOURCES.items():
        txt = fetch(url)
        time.sleep(0.6)
        if txt is None:
            snap["zones"][zone] = {"error": "fetch failed", "source": url}
            continue
        p = parse_hourly(txt, zone)
        p["source"] = url
        snap["zones"][zone] = p
        n = len(p["hourly_mw"])
        if n:
            ok += 1
            last = max(p["hourly_mw"])
            print(f"  {zone:9s} {n:2d}時間分 最新{last}時 "
                  f"{p['hourly_mw'][last]:,.0f}MW ({p.get('date')})")
        else:
            print(f"  {zone:9s} 実績0件(形式変更?)")
    # 蓄積(日別・ローカル→nas03復帰後に同期)
    day_file = STORE / f"denkiyoho_{D}.json"
    hist = {}
    if day_file.exists():
        hist = json.loads(day_file.read_text())
    hist[snap["fetched_at"]] = snap["zones"]
    day_file.write_text(json.dumps(hist, ensure_ascii=False))
    # 公開スナップショット
    (PUB / "latest.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=1))
    print(f"取得成功 {ok}/{len(SOURCES)}社 -> {day_file.name} / "
          f"docs/data/realtime/latest.json")
    return 0 if ok >= 5 else 1


if __name__ == "__main__":
    sys.exit(main())
