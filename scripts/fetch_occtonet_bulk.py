#!/usr/bin/env python3
"""OCCTO 系統情報サービス(occtonet3)の「情報ダウンロード」(CF01S010C)から CSV をまとめて取って保存する.

画面「公表 > ダウンロード情報 > CSVダウンロード > 情報ダウンロード」と同じ手順をブラウザなしでたどる。

    GET  LOGIN_login・POST 画面      → 公開利用者のセッションと、画面の入力欄の既定値
    POST actionSubType=ok            → downloadKey と requestToken(入力の検査を通ったとき)
    POST actionSubType=download      → CSV 本体

画面で「検索」を挟まないので、1 回の CSV に 2 リクエストで済む。期間を指定できる種類は 1 か月を
1 回で取り、日次の実行では当月(月初の数日は前月も)を取り直して上書きする(冪等)。

取り溜めを減らさない決まり(2026-11-06): 中身が同じなら書かない・行が減る応答では上書きしない・
過去の値が替わったら前の版を _versions/ に残す(save())。どこまで覆ったかを {種類}/_manifest.json に
記録し、途中で止まった月や公開範囲が後から延びた月は --backfill が取り直す(run())。

保存先: {out}/{種類のフォルダ}/{YYYY}/{種類}_{期間}.csv(サーバーが返したバイト列のまま。cp932)

アクセスの間隔: OCCTO は 2026-10-23 に「過度なアクセスはアクセス制限することがある」と告知して
いる。1 リクエストごとに --sleep 秒(既定 5 秒)空ける。

使い方:
    python3 scripts/fetch_occtonet_bulk.py --out /mnt/nas03/occto_raw --daily            # 日次(当月を取り直す)
    python3 scripts/fetch_occtonet_bulk.py --out DIR --dataset chinai_flow --month 2025-04
    python3 scripts/fetch_occtonet_bulk.py --out DIR --backfill                          # 公開範囲の欠けている月を全部
    python3 scripts/fetch_occtonet_bulk.py --list                                        # 種類と公開範囲
"""
from __future__ import annotations

import argparse
import calendar
import datetime as dt
import html.parser
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests

BASE = "https://occtonet3.occto.or.jp/public/dfw/RP11/OCCTO/SD/"
SCREEN = "CF01S010C"
PAGE = f"{BASE}{SCREEN}?fwExtention.pathInfo={SCREEN}&fwExtention.prgbrh=0"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
AREA_BOXES = ["hkd", "thk", "tko", "chb", "hkr", "kns", "cgk", "skk", "kys", "oki"]
AREA_CODES = {b: f"{i + 1:02d}" for i, b in enumerate(AREA_BOXES)}

log = logging.getLogger("occtonet_bulk")


@dataclass(frozen=True)
class Spec:
    key: str        # 保存フォルダ名
    tab: str        # "0"=連系線 "1"=エリア
    kind: str       # rklDataKnd / areaDataKnd の値
    mode: str       # "range"(日付の範囲を 1 か月ずつ) / "day"(1 日ずつ) / "year" / "month"
    kkn: str        # 画面に出る公開範囲の欄(「(2025/04/01〜2026/11/05)」)
    label: str
    areas: bool = True  # エリア(連系線)の全選択を付けるか


# 取る種類。AGJ(潮流・容量・停止)に効くものと、公開範囲が短いもの
SPECS = {s.key: s for s in [
    Spec("chinai_flow", "1", "17", "range", "abbFlowRsltKkn", "地内基幹送電線潮流実績(30 分値)", areas=False),
    Spec("chinai_capacity_result", "1", "16", "range", "abbsdlUnyrYsuflowRsltkkn", "地内基幹送電線運用容量・予想潮流 実績", areas=False),
    Spec("interconnector_flow", "0", "11", "range", "rklFlowRsltKkn", "連系線潮流実績"),
    Spec("interconnector_capacity_nd", "0", "06", "range", "akyuryNdKkn", "連系線空容量 翌日"),
    Spec("demand_result_daily", "1", "12", "range", "jyyuRsltDbtKkn", "需要実績 日別"),
    Spec("outage_plan_result", "1", "18", "range", "sgSplnRsltKkn", "作業停止計画・実績", areas=False),
    Spec("fault_info", "1", "19", "range", "fltInfKkn", "故障情報", areas=False),
    Spec("frequency_50hz", "1", "08", "day", "tjyyuSyuuha50HzPwrsysKkn", "周波数(50Hz 系統)", areas=False),
    Spec("frequency_60hz", "1", "09", "day", "tjyyuSyuuha60HzPwrsysKkn", "周波数(60Hz 系統)", areas=False),
    Spec("re_curtailment_month", "1", "21", "month", "reEnYksRsltNngtKkn", "再生可能エネルギー出力抑制実績 年月", areas=False),
]}


class _Form(html.parser.HTMLParser):
    """画面の HTML から入力欄の既定値を拾う(ブラウザが送るのと同じ形にするため)。"""

    def __init__(self):
        super().__init__()
        self.fields: dict[str, str] = {}
        self._select: str | None = None
        self._first: str | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        name = a.get("name")
        if tag == "input" and name:
            t = (a.get("type") or "text").lower()
            if t in ("radio", "checkbox"):
                if "checked" in a:
                    self.fields[name] = a.get("value", "on")
                else:
                    self.fields.setdefault(name, "") if t == "radio" else None
            elif t not in ("button", "submit", "image", "file"):
                self.fields[name] = a.get("value", "")
        elif tag == "select" and name:
            self._select, self._first = name, None
            self.fields.setdefault(name, "")
        elif tag == "option" and self._select:
            v = a.get("value", "")
            if self._first is None:
                self._first = v
                self.fields[self._select] = v
            if "selected" in a:
                self.fields[self._select] = v

    def handle_endtag(self, tag):
        if tag == "select":
            self._select = None


class Client:
    def __init__(self, sleep: float):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.sleep = sleep
        self.defaults: dict[str, str] | None = None

    def _wait(self):
        time.sleep(self.sleep)

    def open(self):
        # 公開側の入口でセッションを張ってから画面を開く(飛ばすと「タイムアウト」で弾かれる)
        self.s.get(BASE + "LOGIN_login", timeout=60).raise_for_status()
        self._wait()
        r = self.s.post(PAGE, data={}, timeout=60, headers={"Referer": BASE + "LOGIN_login"})
        r.raise_for_status()
        p = _Form()
        p.feed(r.content.decode("utf-8", "replace"))
        if "abbFlowRsltKkn" not in p.fields:
            raise RuntimeError("情報ダウンロード画面の入力欄が見つからない(画面が変わった?)")
        self.defaults = {k: v for k, v in p.fields.items() if v is not None}
        self._wait()
        # 公開範囲(…Kkn)や年の選択肢(…Hdn)は、画面を開いた直後の initDisplay の応答で埋まる
        init = dict(self.defaults)
        init.update({"fwExtention.actionType": "reference", "fwExtention.actionSubType": "initDisplay",
                     "fwExtention.pathInfo": SCREEN, "fwExtention.prgbrh": "0",
                     "fwExtention.formId": "CF01S010P", "transitionContextKey": "DEFAULT"})
        d = self._ajax(init)
        hdr = ((d.get("root") or {}).get("bizRoot") or {}).get("header") or {}
        for k, v in hdr.items():
            if isinstance(v, dict) and isinstance(v.get("value"), str) and k in self.defaults:
                self.defaults[k] = v["value"]

    def window(self, spec: Spec) -> tuple[str, str]:
        """画面に出ている公開範囲(例 '(2025/04/01〜2026/11/05)')。"""
        if self.defaults is None:
            self.open()
        v = self.defaults.get(spec.kkn, "")
        m = re.findall(r"(\d{4}(?:/\d{2}(?:/\d{2})?)?)", v)
        return (m[0], m[-1]) if m else ("", "")

    def _form(self, spec: Spec, sub: str, **dates) -> dict:
        f = dict(self.defaults)
        f.update({
            "fwExtention.actionType": "reference", "fwExtention.actionSubType": sub,
            "fwExtention.pathInfo": SCREEN, "fwExtention.prgbrh": "0", "fwExtention.formId": "CF01S010P",
            "transitionContextKey": "DEFAULT", "tabSntk": spec.tab,
        })
        if spec.tab == "1":
            f["areaDataKnd"] = spec.kind
            f["allAreaSectDwld"] = "11"
            for b in AREA_BOXES:
                f[b] = AREA_CODES[b]
            f.pop("areaSum", None)
            f.pop("areaAllTermDwld", None)
            key = {"range": ("areaNngpFrom", "areaNngpTo"), "day": ("areaNngp",),
                   "year": ("areaNnd",), "month": ("areaYear", "monthCd2")}[spec.mode]
        else:
            f["rklDataKnd"] = spec.kind
            f["allTgtRklSectDwld"] = "Y"
            for i in range(1, 16):
                f[f"rkl{i}"] = f"{i:02d}"
            f.pop("rklAllTermDwld", None)
            key = {"range": ("rklNngpFrom", "rklNngpTo"), "day": ("rklNngp",),
                   "year": ("rklNnd",), "month": ("rklYear", "monthCd")}[spec.mode]
        for k, v in zip(key, dates["values"]):
            f[k] = v
        return f

    def _ajax(self, form: dict) -> dict:
        r = self.s.post(BASE + SCREEN, data=form, timeout=180, headers={
            "sdreqtype": "AJAX", "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01", "Referer": PAGE})
        r.raise_for_status()
        self._wait()
        return r.json()

    def download(self, spec: Spec, values: tuple[str, ...]) -> bytes | None:
        if self.defaults is None:
            self.open()
        ok = self._ajax(self._form(spec, "ok", values=values))
        root = ok.get("root") or {}
        if root.get("interceptorErr"):
            self.defaults = None
            raise RuntimeError(f"セッションが切れた: {root['interceptorErr'].get('errMessage')}")
        if root.get("errMessage"):
            msgs = "; ".join(m.get("msgFormat", "") for m in root["errMessage"])
            log.info("    %s %s: %s", spec.key, "/".join(values), msgs)
            return None
        hdr = ((root.get("bizRoot") or {}).get("header")) or {}
        key = (hdr.get("downloadKey") or {}).get("value")
        tok = (hdr.get("requestToken") or {}).get("value")
        if not key or not tok:
            raise RuntimeError(f"downloadKey/requestToken が返らない: {json.dumps(ok, ensure_ascii=False)[:300]}")
        form = self._form(spec, "download", values=values)
        form.update({"downloadKey": key, "requestToken": tok})
        r = self.s.post(BASE + SCREEN, data=form, timeout=600, headers={"Referer": PAGE})
        r.raise_for_status()
        self._wait()
        body = r.content
        if "attachment" not in r.headers.get("content-disposition", ""):
            raise RuntimeError(f"CSV でない応答: {r.headers.get('content-type')} {body[:200]!r}")
        return body


def _ymd(s: str) -> dt.date:
    return dt.datetime.strptime(s, "%Y/%m/%d").date()


def units(spec: Spec, lo: dt.date, hi: dt.date) -> list[tuple[str, tuple[str, ...]]]:
    """[(ファイル名の期間, 画面に入れる値)]。range は 1 か月ずつ、day は 1 日ずつ。"""
    out = []
    if spec.mode == "range":
        d = lo.replace(day=1)
        while d <= hi:
            last = d.replace(day=calendar.monthrange(d.year, d.month)[1])
            a, b = max(d, lo), min(last, hi)
            out.append((f"{d:%Y%m}", (f"{a:%Y/%m/%d}", f"{b:%Y/%m/%d}")))
            d = last + dt.timedelta(days=1)
    elif spec.mode == "day":
        d = lo
        while d <= hi:
            out.append((f"{d:%Y%m%d}", (f"{d:%Y/%m/%d}",)))
            d += dt.timedelta(days=1)
    elif spec.mode == "month":
        d = lo.replace(day=1)
        while d <= hi:
            out.append((f"{d:%Y%m}", (f"{d:%Y}", f"{d:%m}")))
            d = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    elif spec.mode == "year":
        for y in range(lo.year, hi.year + 1):
            out.append((f"{y}", (f"{y}",)))
    return out


def path_for(out: Path, spec: Spec, tag: str) -> Path:
    return out / spec.key / tag[:4] / f"{spec.key}_{tag}.csv"


def unit_end(spec: Spec, tag: str) -> dt.date:
    """単位(ファイル)が覆う期間の最後の日(公開範囲で切る前)。"""
    y = int(tag[:4])
    if len(tag) == 8:
        return dt.date(y, int(tag[4:6]), int(tag[6:]))
    if len(tag) == 6:
        m = int(tag[4:])
        return dt.date(y, m, calendar.monthrange(y, m)[1])
    return dt.date(y, 12, 31)


# 取得の台帳 {種類}/_manifest.json: {期間: {"to": 覆い終えた日, "at": 取った時刻, ...}}
# 「to」は、公開範囲の終わりと「取った日の前日」の早い方。当日分は途中までしか出ていないので
# 覆い終えたとはみなさない。to が単位の終わり(公開範囲で切ったもの)に届いていない単位は、
# 次の実行で取り直す。月末に 160core が止まって前月が途中のまま残る、公開範囲が後から延びる
# (故障情報は公開の終わりが今日より前)、といった場合にも欠けを残さないため。
MANIFEST = "_manifest.json"


def load_manifest(out: Path, spec: Spec) -> dict:
    p = out / spec.key / MANIFEST
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as e:
        log.warning("  台帳が読めない(作り直す): %s %s", p, e)
        return {}


def write_manifest(out: Path, spec: Spec, man: dict):
    p = out / spec.key / MANIFEST
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".part")
    tmp.write_text(json.dumps(man, ensure_ascii=False, sort_keys=True, indent=0), encoding="utf-8")
    os.replace(tmp, p)


def _rows(b: bytes) -> int:
    return b.count(b"\n")


def save(path: Path, body: bytes) -> str:
    """保存して、何をしたかを返す(取り溜めを減らさないための決まり)。

    new      新しいファイル
    same     中身が同じ。書かない(更新時刻も変えないので、統合 DB の作り直しも起きない)
    grown    行が増えた(当月の日が増えたなど)。上書きする
    revised  行の数は同じで中身が違う(過去の値の改訂)。前の版を {種類}/_versions/ に残して上書きする
    kept     行が減った応答。いまのファイルは残し、応答は _versions/{名前}.shorter.csv に置く
             (通信の途中切れや公開の取り下げで、取り溜めた行を失わないため)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    status = "new"
    if path.exists():
        old = path.read_bytes()
        if old == body:
            return "same"
        vdir = path.parent.parent / "_versions"
        if _rows(body) < _rows(old):
            vdir.mkdir(exist_ok=True)
            (vdir / f"{path.stem}.shorter{path.suffix}").write_bytes(body)
            return "kept"
        if _rows(body) == _rows(old):
            vdir.mkdir(exist_ok=True)
            stamp = dt.date.fromtimestamp(path.stat().st_mtime)
            v = vdir / f"{path.stem}.{stamp:%Y%m%d}{path.suffix}"
            if not v.exists():
                v.write_bytes(old)
            status = "revised"
        else:
            status = "grown"
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(body)
    os.replace(tmp, path)
    return status


def parse_window(spec: Spec, cli: Client) -> tuple[dt.date, dt.date] | None:
    a, b = cli.window(spec)
    if not a:
        return None
    def to_date(s, end):
        parts = [int(x) for x in s.split("/")]
        if len(parts) == 3:
            return dt.date(*parts)
        if len(parts) == 2:
            y, m = parts
            return dt.date(y, m, calendar.monthrange(y, m)[1] if end else 1)
        return dt.date(parts[0], 12 if end else 1, 31 if end else 1)
    lo, hi = to_date(a, False), to_date(b, True)
    return lo, min(hi, dt.date.today())


def run(cli: Client, out: Path, spec: Spec, lo: dt.date, hi: dt.date, force_tags: set[str], max_units: int,
        refetch_open: bool = True) -> tuple[int, int, int]:
    got = skip = miss = 0
    today = dt.date.today()
    man = load_manifest(out, spec)
    dirty = False
    try:
        for tag, values in units(spec, lo, hi):
            p = path_for(out, spec, tag)
            want = min(unit_end(spec, tag), hi)      # この単位で覆いたい最後の日
            if p.exists():
                ent = man.get(tag)
                if ent is None:
                    # 台帳ができる前(2026-11-05〜06)に取ったファイル。取った日の前日まで、
                    # かつ今の公開範囲の終わりまでを覆っているとみなす
                    got_on = dt.date.fromtimestamp(p.stat().st_mtime)
                    ent = man[tag] = {"to": str(min(want, got_on - dt.timedelta(days=1))),
                                      "at": dt.datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
                                      "note": "台帳より前"}
                    dirty = True
                done = dt.date.fromisoformat(ent["to"]) >= want
                still_open = unit_end(spec, tag) >= today   # 当月・当日(日次の受け持ち)
                if tag not in force_tags and (done or (still_open and not refetch_open)):
                    skip += 1
                    continue
            if max_units and got + miss >= max_units:
                break
            for attempt in range(3):
                try:
                    body = cli.download(spec, values)
                    break
                except Exception as e:  # noqa: BLE001  通信・応答の崩れは 3 回まで取り直す
                    log.warning("    %s %s 失敗(%d回目): %s", spec.key, tag, attempt + 1, e)
                    cli.defaults = None
                    time.sleep(cli.sleep * 6)
            else:
                miss += 1
                continue
            if not body:
                miss += 1
                continue
            status = save(p, body)
            got += 1
            if status == "kept":
                # 減った応答では「覆い終えた日」を進めない(次の実行でまた確かめる)
                log.warning("    %s %s: 行が減った応答(%d bytes)。いまのファイルを残した", spec.key, tag, len(body))
            else:
                man[tag] = {"to": str(min(want, today - dt.timedelta(days=1))),
                            "at": dt.datetime.now().isoformat(timespec="seconds"),
                            "bytes": len(body), "status": status}
                log.info("    %s %s: %d bytes (%s)", spec.key, tag, len(body), status)
            dirty = True
            if got % 25 == 0:
                write_manifest(out, spec, man)
    finally:
        if dirty:
            write_manifest(out, spec, man)
    return got, skip, miss


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--dataset", action="append", help="種類(複数可。既定は --daily/--backfill の既定の組)")
    ap.add_argument("--daily", action="store_true", help="当月(月初 5 日は前月も)を取り直す。day 型は直近 3 日")
    ap.add_argument("--backfill", action="store_true",
                    help="公開範囲のうち、無い単位と覆い終えていない単位(台帳 _manifest.json で判断)を古い順に取る")
    ap.add_argument("--revisit-months", type=int, default=0,
                    help="締まった直近 N か月を取り直す(過去の値の改訂を拾う。中身が替われば前の版を _versions/ に残す。日ごとの種類は対象外)")
    ap.add_argument("--month", help="この月だけ取り直す(YYYY-MM)")
    ap.add_argument("--max-units", type=int, default=0, help="1 種類あたり 1 回に取る最大の単位数(0=制限なし)")
    ap.add_argument("--sleep", type=float, default=5.0)
    ap.add_argument("--list", action="store_true", help="種類と、いまの公開範囲を出す")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%F %T")

    cli = Client(args.sleep)
    if args.list:
        cli.open()
        for s in SPECS.values():
            a, b = cli.window(s)
            print(f"{s.key:28s} {s.mode:6s} {a}〜{b}  {s.label}")
        return 0
    if not args.out:
        ap.error("--out が要る")

    keys = args.dataset or list(SPECS)
    today = dt.date.today()
    total = [0, 0, 0]
    for k in keys:
        spec = SPECS[k]
        win = parse_window(spec, cli)
        if not win:
            log.warning("%s: 公開範囲が読めない(画面の欄 %s)", k, spec.kkn)
            continue
        lo, hi = win
        if args.month:
            m0 = dt.date.fromisoformat(args.month + "-01")
            m1 = m0.replace(day=calendar.monthrange(m0.year, m0.month)[1])
            lo, hi = max(lo, m0), min(hi, m1)
            force = {u[0] for u in units(spec, lo, hi)}
        elif args.revisit_months:
            if spec.mode == "day":
                continue
            m_end = today.replace(day=1) - dt.timedelta(days=1)          # 前月末
            m_start = m_end.replace(day=1)
            for _ in range(args.revisit_months - 1):
                m_start = (m_start - dt.timedelta(days=1)).replace(day=1)
            lo, hi = max(lo, m_start), min(hi, m_end)
            if lo > hi:
                continue
            force = {u[0] for u in units(spec, lo, hi)}
        elif args.daily:
            start = today - dt.timedelta(days=3) if spec.mode == "day" else (
                (today.replace(day=1) - dt.timedelta(days=1)).replace(day=1) if today.day <= 5 else today.replace(day=1))
            lo = max(lo, start)
            force = {u[0] for u in units(spec, lo, hi)}
        else:  # backfill
            force = set()
        log.info("%s(%s): %s〜%s", k, spec.label, lo, hi)
        g, s_, m = run(cli, args.out, spec, lo, hi, force, args.max_units,
                       refetch_open=not (args.backfill and not args.daily and not args.month))
        log.info("  → 取得 %d / 既存 %d / 取れず %d", g, s_, m)
        total = [total[0] + g, total[1] + s_, total[2] + m]
    log.info("完了: 取得 %d / 既存 %d / 取れず %d", *total)
    return 0 if total[2] == 0 or total[0] > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
