#!/usr/bin/env python3
"""でんき予報(10 社の当日需要実績と当日の予測値・1時間値)の準リアルタイム取得.

オーナー指示(2026-08-18): 「DBとして、直接リアルタイムが取れるといいね」

取得: 各一般送配電事業者の「でんき予報」CSV(公表・出典明記で利用可の慣例)から
  「DATE,TIME,当日実績(万kW),予測値(万kW),…」セクションを共通パーサで抽出(万kW→MW)。
  - hourly_mw: 当日実績(0 は未来の時刻なので入れない)
  - forecast_mw: 各社の当日の予測値(関西は「予想値」の列。2026-11-25 追加・24 時間ぶん)
蓄積: data/realtime/denkiyoho_YYYYMMDD.json(ローカル・untracked)
  ※nas03再起動期間(2026-08-19〜20頃)はローカル蓄積し、復帰後に
    nas03(pws-nas03)のAGJ領域へrsyncする(sync_realtime_to_nas.shを用意)
公開: docs/data/realtime/latest.json(zone×hourly MW+出典・取得時刻。
  でんき予報の数値はエリア合計の公表値=転載可の慣例。出典を明記)

10 社の置き場(2026-11-25 に各社のでんき予報のページから確かめた):
  関西: ページ(/denkiyoho/)が /yamasou/jisseki-latest.json で指す juyo_06_YYYYMMDD.csv
    (他社と同じ形)。前は juyo1_kansai.csv 系(2020 年で凍結)しか見つからず未収載だった
  四国: ページ(/nw/denkiyoho/)の「本日の使用状況データ」juyo_08_YYYYMMDD.csv(他社と同じ形)。
    前は年次 CSV(毎日 0 時に前の日までを足す)を読んでいて、date が毎回前の日だった。
    当日の CSV が取れないときだけ年次 CSV を読む(前の日の値・date も前の日)
  東北: 2026-11-20 から東北電力ネットワークが「当社ホームページの一部機能の一時停止」で
    でんき予報を止めている(10-22 の PHP の脆弱性での停止と同じ)。名前
    setsuden.nw.tohoku-epco.co.jp に A が無く(HTTPS レコードの別名先の負荷分散も空)、
    毎時「fetch failed」になる。URL は同社のトップページのリンクのままなので、再開すればこのまま取れる

  python3 scripts/fetch_denkiyoho.py                       # 毎時の処理(既定の置き場)
  python3 scripts/fetch_denkiyoho.py --out-dir /tmp/dk     # 試し: 蓄積も latest.json もそこへ
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
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
    # 2026-11-20〜 同社がでんき予報を一時停止中(名前が引けない)。再開すればこのまま取れる
    "tohoku": f"https://setsuden.nw.tohoku-epco.co.jp/common/demand/juyo_02_{D}.csv",
    "tokyo": "https://www.tepco.co.jp/forecast/html/images/juyo-d1-j.csv",
    "chubu": "https://powergrid.chuden.co.jp/denki_yoho_content_data/juyo_cepco003.csv",
    "hokuriku": f"https://www.rikuden.co.jp/nw/denki-yoho/csv/juyo_05_{D}.csv",
    "kansai": f"https://www.kansai-td.co.jp/yamasou/juyo_06_{D}.csv",
    "chugoku": f"https://www.energia.co.jp/nw/jukyuu/sys/juyo_07_{D}.csv",
    "shikoku": f"https://www.yonden.co.jp/nw/denkiyoho/juyo_08_{D}.csv",
    "kyushu": f"https://www.kyuden.co.jp/td_power_usages/csv/juyo-hourly-{D}.csv",
    "okinawa": f"https://www.okiden.co.jp/denki2/juyo_10_{D}.csv",
}
# 当日の CSV が取れないときに読む予備(年次形式: 日付,時刻,実績,供給力。前の日まで)
FALLBACK = {
    "shikoku": f"https://www.yonden.co.jp/nw/denkiyoho/csv/juyo_shikoku_{TODAY.year}.csv",
}

# 当日の 1 時間値のセクション。5 分値のセクション「当日実績(５分間隔値)」とは見出しで分ける
HOURLY_HEAD = re.compile(r"DATE,TIME,当日実績\(万kW\)")
# 予測値の列の見出し(関西だけ「予想値」)
FORECAST_HEAD = re.compile(r"^(予測値|予想値)\(万kW\)")


def fetch(url: str) -> tuple[str | None, str | None]:
    """(本文, 失敗の理由)。本文は cp932 で読む(10 社とも Shift_JIS。前の版も errors=replace の cp932 で読んでいた)"""
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("cp932", errors="replace"), None
    except Exception as ex:  # noqa: BLE001
        print(f"  ! fetch失敗: {ex}")
        return None, str(ex)[:200]


def _num(s: str) -> float | None:
    try:
        return float(s)
    except ValueError:
        return None


def parse_hourly(text: str, zone: str, yearly: bool = False) -> dict:
    """共通セクション → {hourly_mw: {時: MW}, forecast_mw: {時: MW}, updated, date}。
    yearly=True は四国の年次形式(日付,時刻,実績,供給力)で、いちばん新しい日の行だけを読む(予測値の列は無い)"""
    out: dict[int, float] = {}
    fc: dict[int, float] = {}
    updated = None
    m = re.match(r"([\d/]+ [\d:]+) UPDATE", text)
    if m:
        updated = m.group(1)
    lines = text.splitlines()
    date_used = None
    if yearly:
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
    fc_col = None
    for ln in lines:
        if HOURLY_HEAD.match(ln):
            in_sec = True
            cols = ln.split(",")
            fc_col = next((i for i, c in enumerate(cols) if FORECAST_HEAD.match(c.strip())), None)
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
            except ValueError:
                continue
            if not 0 <= h < 24:
                continue
            v = _num(parts[2])
            if v is not None and v > 0:  # 0=未来時刻(未実績)
                out[h] = v * 10.0
            if fc_col is not None and fc_col < len(parts):
                f = _num(parts[fc_col])
                if f is not None and f > 0:
                    fc[h] = f * 10.0
    res = {"hourly_mw": out, "updated": updated, "date": date_used}
    if fc:
        res["forecast_mw"] = fc
    return res


def _write_atomic(path: Path, text: str) -> None:
    """一時ファイルに書いてから置き換える(途中で止まっても前のファイルが残る)"""
    tmp = path.with_name(f".{path.name}.tmp{os.getpid()}")
    tmp.write_text(text)
    os.replace(tmp, path)


def _show(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--store", type=Path, default=STORE, help="日別の蓄積 denkiyoho_YYYYMMDD.json の置き場")
    ap.add_argument("--pub", type=Path, default=PUB, help="公開スナップショット latest.json の置き場")
    ap.add_argument("--out-dir", type=Path, help="試し用: --store と --pub をどちらもここにする")
    a = ap.parse_args(argv)
    store, pub = (a.out_dir, a.out_dir) if a.out_dir else (a.store, a.pub)
    store.mkdir(parents=True, exist_ok=True)
    pub.mkdir(parents=True, exist_ok=True)
    snap = {"fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
            "unit": "MW", "zones": {}, "note": (
                "各一般送配電事業者「でんき予報」当日実績(1時間値・万kW)を10倍でMW化。"
                "forecast_mw=各社の当日の予測値(関西は予想値)。出典=各社でんき予報(下記URL)。"
                "tohoku=2026-11-20から同社がでんき予報を一時停止中")}
    ok = 0
    for zone, url in SOURCES.items():
        txt, why = fetch(url)
        time.sleep(0.6)
        yearly = False
        if txt is None and zone in FALLBACK:
            print(f"  {zone:9s} 当日のCSVが取れない → 予備の年次CSV")
            url, yearly = FALLBACK[zone], True
            txt, why = fetch(url)
            time.sleep(0.6)
        if txt is None:
            snap["zones"][zone] = {"error": "fetch failed", "source": url, "reason": why}
            continue
        p = parse_hourly(txt, zone, yearly=yearly)
        p["source"] = url
        snap["zones"][zone] = p
        n = len(p["hourly_mw"])
        nf = len(p.get("forecast_mw") or {})
        if n:
            ok += 1
            last = max(p["hourly_mw"])
            print(f"  {zone:9s} {n:2d}時間分 最新{last}時 "
                  f"{p['hourly_mw'][last]:,.0f}MW 予測{nf:2d}時間 ({p.get('date')})")
        else:
            print(f"  {zone:9s} 実績0件(形式変更?)")
    # 蓄積(日別・ローカル→nas03復帰後に同期)
    day_file = store / f"denkiyoho_{D}.json"
    hist = {}
    if day_file.exists():
        hist = json.loads(day_file.read_text())
    hist[snap["fetched_at"]] = snap["zones"]
    _write_atomic(day_file, json.dumps(hist, ensure_ascii=False))
    # 公開スナップショット
    _write_atomic(pub / "latest.json", json.dumps(snap, ensure_ascii=False, indent=1))
    print(f"取得成功 {ok}/{len(SOURCES)}社 -> {day_file.name} / {_show(pub / 'latest.json')}")
    return 0 if ok >= 5 else 1


if __name__ == "__main__":
    sys.exit(main())
