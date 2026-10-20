#!/usr/bin/env python3
"""全国の変電所変圧器台帳(非公開・私的検証用)を各社の「空容量・予想潮流一覧」から作る.

目的
----
系統モデルの変圧器トポロジ(各変電所でどの電圧階級どうしが変圧器で直結しているか)の
正しさを検査するために、一般送配電事業者 10 社が公表している「空容量・予想潮流一覧」
(系統情報の公表ガイドラインに基づく様式)の**変圧器(変電所)の行**だけを集め、
1 行 = 1 つの公表行(事業者・変電所・一次/二次[/三次]電圧・台数・設備容量)に正規化する。

出典(2026-10-08 時点の配布形態。URL は年月入りで変わるので索引ページから拾う)
------------------------------------------------------------------------------
  hokkaido  ほくでんNW   public_document/zip/sys_capa_kikan.zip・sys_capa_localNN.zip
                         (NN=01.. を 404 まで)→ 中の *_Tr_*.csv
  tohoku    東北電力NW   consignment/system/announcement/ の ./data/sys_capa_*_tr_*.csv
  tokyo     東京電力PG   consignment/system/ の pdf/csv_yosochoryu_<地域>.zip
                         → *_hendensyo.csv(PDF 版 <地域>_yosochoryu.pdf と同内容)。
                         PDF も取得し、pdftotext の「変」行と CSV の行数・組を照合する
  chubu     中部電力PG   gridmap の pass_data/pass.json → geo_data/KRSIH010..016(中身は ZIP)
                         → 「変電所空容量」CSV(KRSIH003..009 は同内容の PDF)
  hokuriku  北陸電力送配電 nw_notification/U_154seiyaku.html の sys_capa_*_tr_*.csv
  kansai    関西電力送配電 interchange/takusou/pdf/154kv_more_trans.csv・154kv_less_trans.csv
  chugoku   中国電力NW   keitou/access/ の zip/csv_*.zip → *_tr_*.csv
                         (220kV 以上は mapping.pdf と同内容)
  shikoku   四国電力送配電 nw/line_access/data.html の sys_capa_*_tr_*.csv
  kyushu    九州電力送配電 td/service/wheeling/disclosure.html の「変圧器CSV(zip)」
  okinawa   沖縄電力     business-support/service/rule/plan/index.html の con_res_mapNN_MM.csv
                         (空容量マッピングの CSV。operating_capacity.pdf は 132kV 送電線だけで変圧器が無い)

ライセンス(厳守)
----------------
東京電力パワーグリッド・関西電力送配電の公表値は All-Rights-Reserved(転載禁止)。
他社も転載は前提にしていない。**取得物と出力はすべて git 管理外**の
  data/external/system_disclosure/transformer_lists/
にだけ書く(起動時に `git check-ignore` で確認し、無視されていなければ中止する)。
リポジトリ・レポートに書いてよいのは来歴(URL・sha256・バイト数・取得日時)と、
変電所ごとの「電圧の組が公表されているか」の判定まで。台数・容量の生値は書かない。

取得物の扱い
------------
ダウンロードは信頼しないデータとして扱う: 1 ファイル 1 ディレクトリ
(raw/<事業者>/<ファイル名の stem>/)に置き、ZIP はパスを無害化して同じディレクトリの
x/ に展開する。CSV は csv モジュールで文字列として読むだけ、PDF は pdftotext に
渡すだけで、取得物の中身を実行・import することはない。本スクリプトは
`python3 -I` で動かす(カレントやスクリプト横の .py を import しない)。

出力(transformer_lists/ 以下)
------------------------------
  raw/<utility>/...            取得した原本(ZIP は展開物も)
  raw/MANIFEST.json            ファイルごとの url・retrieved_at(UTC)・sha256・bytes
  transformer_registry.csv     本体(UTF-8)。列は COLUMNS を参照。末尾の note 列に、hv/lv の入れ替え・
                               電圧の組が非公表(東京の 22kV/配電用区分)・名称非公表などを書く
  summary.json                 事業者別の行数・変電所数・電圧の組・解析警告・未取得の社

substation_norm の規則
----------------------
  1. NFKC 正規化(全角数字・括弧・半角カナを揃える。①→1)
  2. 空白(全角・半角)をすべて除く
  3. 末尾の括弧書きを、中身が「番号・電圧・号機」のときだけ繰り返し除く
     例: (1) (２) (154) (66kV) (No.2) (#1) (1号) (2B) → 除く。(仮称) 等は残して警告に数える
  4. 括弧なしの末尾の付記を除く: 電圧の組「66/22kV」(北陸)・バンク名「11・12・14B」「1U」(東京)・
     「No.1」「№1、№2」「1号」(九州)。「第1」は別設備のことが多いので残す
  5. 末尾の設備種別語を除く(長いものから 1 つ): 周波数変換所・交直変換所・変換所・変電所・開閉所・
     変電・開閉
  6. 3〜5 を変化がなくなるまで繰り返す
     例: 「遠江変電所(1)」→「遠江」、「西谷(66kV)」→「西谷」、「西京都（154）」→「西京都」、
         「中島　66/22kV」→「中島」、「三田尻(変)」→「三田尻」
  発電所・火力・(塔)・(新綾部) などは名前の一部として残す(例:「阿南火力変電所」→「阿南火力」)。
  名前が「-」「変電所」だけの行(名称非公表)はそのまま残し note に "name withheld" と書く。
  東北の英数字だけの名前(「1113」「1A08」= 番号で掲載)も note に "name published as code"。

電圧の表記
----------
kV の数値で持つ。6→6.6、3→3.3 のように公称電圧に直す(公表表の慣用的な省略を戻す)。
3 巻線(「275/154/66」や三次電圧の列)は tv_kv に三次を入れる。

使い方
------
  python3 -I fetch_transformer_lists.py              # 取得 + 解析(既定)
  python3 -I fetch_transformer_lists.py --offline    # 取得せず raw/MANIFEST.json から再解析
  python3 -I fetch_transformer_lists.py --utilities kyushu chubu   # 一部の社だけ取り直す
                                                     # (他社は前回の raw を再利用)
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as _dt
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "data" / "external" / "system_disclosure" / "transformer_lists"
RAW = OUT / "raw"
MANIFEST = RAW / "MANIFEST.json"
UA = "Mozilla/5.0 (compatible; All-Japan-Grid research; private transformer registry)"
SLEEP = 1.0  # 礼儀: 1 リクエスト/秒

UTILITIES = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
             "kansai", "chugoku", "shikoku", "kyushu", "okinawa"]

COLUMNS = ["utility", "agj_region", "substation_raw", "substation_norm",
           "hv_kv", "lv_kv", "tv_kv", "n_units", "capacity_value", "capacity_unit",
           "source_url", "source_file", "row_text", "note"]


# ---------------------------------------------------------------------------
# 取得
# ---------------------------------------------------------------------------
def http_get(url: str, timeout: int = 120, tries: int = 3) -> bytes:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            last = e
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
        time.sleep(2 * (i + 1))
    raise last  # type: ignore[misc]


def links(page_url: str, pattern: str) -> list[str]:
    """索引ページの href のうち pattern に合うものを絶対 URL で(重複除去・順序保持)。"""
    html = http_get(page_url).decode("utf-8", errors="replace")
    time.sleep(SLEEP)
    out: list[str] = []
    for m in re.finditer(r'href\s*=\s*["\']([^"\']+)["\']', html):
        h = m.group(1)
        if re.search(pattern, h):
            u = urllib.parse.urljoin(page_url, h)
            if u not in out:
                out.append(u)
    return out


def anchors(page_url: str) -> list[tuple[str, str]]:
    """(絶対URL, リンク文字列) の一覧。"""
    html = http_get(page_url).decode("utf-8", errors="replace")
    time.sleep(SLEEP)
    out = []
    for m in re.finditer(r'<a\b[^>]*href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.S | re.I):
        text = re.sub(r"<[^>]+>", " ", m.group(2))
        text = unicodedata.normalize("NFKC", re.sub(r"\s+", " ", text)).strip()
        out.append((urllib.parse.urljoin(page_url, m.group(1)), text))
    return out


def resolve_sources(utility: str) -> tuple[list[str], list[str]]:
    """→ (取得する URL, メモ)。年月入りのファイル名は索引ページから拾う。"""
    notes: list[str] = []
    if utility == "hokkaido":
        base = "https://www.hepco.co.jp/network/con_service/public_document/zip/"
        urls = [base + "sys_capa_kikan.zip"]
        for i in range(1, 60):
            urls.append(base + f"sys_capa_local{i:02d}.zip")  # 404 で打ち切る(fetch 側)
        notes.append("索引ページが見つからないため固定 URL(local01.. は 404 まで)")
        return urls, notes
    if utility == "tohoku":
        return links("https://nw.tohoku-epco.co.jp/consignment/system/announcement/",
                     r"sys_capa_[^/]*_tr_[^/]*\.csv$"), notes
    if utility == "tokyo":
        page = "https://www.tepco.co.jp/pg/consignment/system/"
        z = links(page, r"csv_yosochoryu_[a-z0-9]+\.zip$")
        p = links(page, r"/[a-z0-9]+_yosochoryu\.pdf$")
        return z + p, notes
    if utility == "chubu":
        base = "https://gridmap.powergrid.chuden.co.jp/"
        pj = json.loads(http_get(base + "pass_data/pass.json").decode("utf-8-sig"))
        time.sleep(SLEEP)
        urls = []
        for k, v in pj.items():
            if k.startswith("unyoyoryotoIchiranhyo") and k.endswith("CsvFileName"):
                urls.append(urllib.parse.urljoin(base, str(v).lstrip("./")))
        notes.append("pass.json の *CsvFileName(KRSIH010..016)。PDF 版 KRSIH003..009 は同内容のため取らない")
        return urls, notes
    if utility == "hokuriku":
        return links("https://www.rikuden.co.jp/nw_notification/U_154seiyaku.html",
                     r"sys_capa_[^/]*_tr_[^/]*\.csv$"), notes
    if utility == "kansai":
        notes.append("索引ページ(interchange/takusou/)は 404。CSV は直リンクで取得")
        return ["https://www.kansai-td.co.jp/interchange/takusou/pdf/154kv_more_trans.csv",
                "https://www.kansai-td.co.jp/interchange/takusou/pdf/154kv_less_trans.csv"], notes
    if utility == "chugoku":
        return links("https://www.energia.co.jp/nw/service/retailer/keitou/access/",
                     r"zip/csv_[a-z0-9]+\.zip$"), notes
    if utility == "shikoku":
        return links("https://www.yonden.co.jp/nw/line_access/data.html",
                     r"sys_capa_[^/]*_tr_[^/]*\.csv$"), notes
    if utility == "kyushu":
        page = "https://www.kyuden.co.jp/td/service/wheeling/disclosure.html"
        urls = [u for u, t in anchors(page) if "変圧器CSV" in t and u.lower().endswith(".zip")]
        notes.append("リンク文字列「変圧器CSV（zipファイル）」で特定(ファイル名は版ごとに乱数)")
        return urls, notes
    if utility == "okinawa":
        # operating_capacity.pdf は 132kV 送電線だけで変圧器の行が無い(2026-10-08 確認)。
        # 「系統連系制約および流通設備計画について」の空容量マッピング CSV に変電所の行がある
        notes.append("rule/plan/index.html の con_res_mapNN_MM.csv(NN=01 本島 等, MM=01 送電線 / 02・03 変電所)")
        return links("https://www.okiden.co.jp/business-support/service/rule/plan/index.html",
                     r"con_res_map\d+_\d+\.csv$"), notes
    raise KeyError(utility)


def safe_name(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1]  # ZIP 内のパスは捨てる(展開先を外に出さない)
    name = unicodedata.normalize("NFKC", name)       # 全角スラッシュ等はこの後 _ に置換される
    name = re.sub(r"[^\w\-.()（）　 ]", "_", name).strip(" .")
    return name or "unnamed"


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def store(utility: str, url: str, blob: bytes, now: str) -> list[dict]:
    """1 ダウンロード = 1 ディレクトリ。ZIP は x/ に展開。→ MANIFEST の行。"""
    base = safe_name(urllib.parse.unquote(Path(urllib.parse.urlparse(url).path).name) or "download")
    is_zip = blob[:2] == b"PK"
    if is_zip and not base.lower().endswith(".zip"):
        base += ".zip"
    d = RAW / utility / Path(base).stem
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    p = d / base
    p.write_bytes(blob)
    rows = [{"utility": utility, "url": url, "retrieved_at": now, "path": str(p.relative_to(OUT)),
             "sha256": sha256(blob), "bytes": len(blob), "kind": "download"}]
    if is_zip:
        xd = d / "x"
        xd.mkdir()
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for i, info in enumerate(z.infolist()):
                if info.is_dir() or info.file_size > 50_000_000:
                    continue
                name = info.filename
                if not info.flag_bits & 0x800:  # UTF-8 フラグ無し → cp437 として読まれている
                    try:
                        name = name.encode("cp437").decode("cp932")
                    except (UnicodeDecodeError, UnicodeEncodeError):
                        name = f"member_{i}{Path(name).suffix}"
                q = xd / safe_name(name)
                if q.exists():
                    q = xd / f"{i:03d}_{safe_name(name)}"
                data = z.read(info)
                q.write_bytes(data)
                rows.append({"utility": utility, "url": url, "retrieved_at": now,
                             "path": str(q.relative_to(OUT)), "sha256": sha256(data),
                             "bytes": len(data), "kind": "zip_member", "zip_member": info.filename})
    return rows


def fetch(utilities: list[str], prev: dict) -> dict:
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    files = [f for f in prev.get("files", []) if f["utility"] not in utilities]
    resolve = {k: v for k, v in prev.get("resolve", {}).items() if k not in utilities}
    for u in utilities:
        try:
            urls, notes = resolve_sources(u)
        except Exception as e:  # 索引ページの取得失敗
            resolve[u] = {"urls": [], "notes": [f"索引の解決に失敗: {e!r}"[:300]], "failed": []}
            print(f"[{u}] 索引の解決に失敗: {e}")
            continue
        info = {"urls": urls, "notes": notes, "failed": [], "resolved_at": now}
        if (RAW / u).exists():
            shutil.rmtree(RAW / u)
        n_ok = 0
        for url in urls:
            try:
                blob = http_get(url)
            except urllib.error.HTTPError as e:
                if u == "hokkaido" and e.code == 404 and "local" in url:
                    time.sleep(SLEEP)
                    break  # 連番の終わり(info["urls"] はループ後に取得できたものへ置き換える)
                info["failed"].append({"url": url, "reason": f"HTTP {e.code}"})
                time.sleep(SLEEP)
                continue
            except Exception as e:
                info["failed"].append({"url": url, "reason": repr(e)[:200]})
                time.sleep(SLEEP)
                continue
            files.extend(store(u, url, blob, now))
            n_ok += 1
            time.sleep(SLEEP)
        if u == "hokkaido":
            info["urls"] = [f["url"] for f in files if f["utility"] == "hokkaido" and f["kind"] == "download"]
        resolve[u] = info
        print(f"[{u}] {n_ok} 件取得" + (f"・失敗 {len(info['failed'])}" if info["failed"] else ""))
    return {"generated_at": now, "files": files, "resolve": resolve}


# ---------------------------------------------------------------------------
# 正規化
# ---------------------------------------------------------------------------
# 末尾の括弧のうち「番号・電圧・号機・設備種別」だけを除く。例:
#   (1) (154) (66kV) (No.2) (#1) (1号) (1,2号) (66kV1,2号) (2B) (変) (配変)
# 「(新綾部)」「(塔)」のような名前の一部らしいものは残し、summary に数える。
_SUFFIX_PAREN = re.compile(
    r"\((?:"
    r"(?:\d+(?:\.\d+)?kV)?(?:No\.?|#|第)?\d+(?:\.\d+)?(?:[,、・~\-]\d+)*(?:kV|V|号機|号|B|T|Tr|バンク|系|側)?"
    r"|変|配変|変電所|開閉所"
    r")\)$", re.I)
_PAREN_ANY = re.compile(r"\([^()]*\)$")
_STATION_WORDS = ["周波数変換所", "交直変換所", "変換所", "変電所", "開閉所", "変電", "開閉"]
_odd_suffixes: collections.Counter = collections.Counter()


# 括弧なしの末尾の付記(番号・電圧の組・バンク名)。残りが空にならないときだけ除く
_BARE_SUFFIXES = [
    re.compile(r"\d+(?:\.\d+)?/\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?k?V$", re.I),   # 北陸「中島 66/22kV」
    re.compile(r"(?<=[^\d,・、\-~])(?:\d+(?:[,・、\-~]\d+)*[BU])+$"),          # 東京「新野田11・12・14B」「姉崎中央1U」
    re.compile(r"No\.?\d+(?:[,、]No\.?\d+)*$", re.I),                          # 九州「坂下№1」「布津№1、№2」
    re.compile(r"(?<=[^\d第])\d+(?:[,、・]\d+)*号機?$"),                           # 九州「桜1号」(「第1」は残す)
]
_WITHHELD = {"-", "－", "―", "ー", "変電所"}


def norm_name(raw: str) -> str:
    s = unicodedata.normalize("NFKC", raw or "")
    s = re.sub(r"\s+", "", s)
    if s in _WITHHELD:
        return s
    for _ in range(6):
        prev = s
        y = _SUFFIX_PAREN.sub("", s)
        s = y if y else s
        for rx in _BARE_SUFFIXES:
            y = rx.sub("", s)
            if y and y != s:
                s = y
        for w in _STATION_WORDS:
            if s.endswith(w) and len(s) > len(w):
                s = s[: -len(w)]
                break
        if s == prev:
            break
    m = _PAREN_ANY.search(s)
    if m:
        _odd_suffixes[m.group(0)] += 1
    return s


_NOMINAL = {"6": 6.6, "6.6": 6.6, "3": 3.3, "3.3": 3.3, "11": 11.0, "22": 22.0, "33": 33.0}


def parse_kv(cell: str) -> float | None:
    s = unicodedata.normalize("NFKC", str(cell or "")).strip()
    s = re.sub(r"(?i)\s*k?v$", "", s).replace(",", "").strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", s):
        return None
    if s in _NOMINAL:
        return _NOMINAL[s]
    v = float(s)
    return v if v > 0 else None


def fmt_kv(v: float | None) -> str:
    if v is None:
        return ""
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def parse_num(cell: str) -> float | None:
    s = unicodedata.normalize("NFKC", str(cell or "")).strip().replace(",", "")
    m = re.fullmatch(r"-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def parse_units(cell: str) -> int | None:
    s = unicodedata.normalize("NFKC", str(cell or "")).strip()
    m = re.match(r"(\d+)", s)
    return int(m.group(1)) if m else None


def fmt_num(v: float | None) -> str:
    if v is None:
        return ""
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def decode(b: bytes) -> str:
    for enc in ("utf-8-sig", "cp932"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode("cp932", errors="replace")


def short(cells: list[str], n: int = 6) -> str:
    t = ",".join(re.sub(r"\s+", " ", unicodedata.normalize("NFKC", c)).strip() for c in cells[:n])
    return t[:160]


# ---------------------------------------------------------------------------
# 解析: ガイドライン様式の CSV(9 社でほぼ共通)
# ---------------------------------------------------------------------------
class Warn:
    def __init__(self) -> None:
        self.counts: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        self.examples: dict[str, dict[str, list[str]]] = collections.defaultdict(lambda: collections.defaultdict(list))

    def add(self, utility: str, kind: str, example: str) -> None:
        self.counts[utility][kind] += 1
        ex = self.examples[utility][kind]
        if len(ex) < 4:
            ex.append(example[:200])


def _hcell(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))


def find_header(rows: list[list[str]]) -> tuple[int, dict[str, int], str] | None:
    """見出し行を探して列位置を返す。→ (行番号, {name, hv, lv, tv?, units, cap}, 容量の単位)。"""
    for i, r in enumerate(rows[:30]):
        cells = [_hcell(c) for c in r]
        col: dict[str, int] = {}
        cap_unit = "unknown"
        for j, c in enumerate(cells):
            if "name" not in col and ("変電所名" in c or c in ("変電所", "設備名称", "名称")):
                col["name"] = j
            elif "hv" not in col and "一次" in c and "電圧" in c:
                col["hv"] = j
            elif "lv" not in col and "二次" in c and "電圧" in c:
                col["lv"] = j
            elif "tv" not in col and "三次" in c and "電圧" in c:
                col["tv"] = j
            elif "units" not in col and c.startswith("台数"):
                col["units"] = j
            elif "cap" not in col and "設備容量" in c:
                col["cap"] = j
                m = re.search(r"(MVA|MW|kVA|kW)", c)
                cap_unit = m.group(1) if m else "unknown"
        if {"name", "hv", "lv"} <= col.keys():
            return i, col, cap_unit
    return None


def parse_standard_csv(utility: str, path: Path, url: str, warn: Warn,
                       name_strip_re: str | None = None) -> list[dict]:
    text = decode(path.read_bytes())
    rows = list(csv.reader(io.StringIO(text)))
    h = find_header(rows)
    if h is None:
        warn.add(utility, "no_header", f"{path.name}")
        return []
    hi, col, cap_unit = h
    out = []
    for r in rows[hi + 1:]:
        if not any(c.strip() for c in r):
            continue
        get = lambda k: (r[col[k]] if k in col and col[k] < len(r) else "")  # noqa: E731
        name = get("name").strip().lstrip("'")
        hv, lv = parse_kv(get("hv")), parse_kv(get("lv"))
        tv = parse_kv(get("tv")) if "tv" in col else None
        note = ""
        if hv is not None and lv is None:
            # 二次の欄に 2 つの電圧(例 "22-13.8")= 3 巻線または二次 2 系統。二次・三次として持つ
            m2 = re.fullmatch(r"(\d+(?:\.\d+)?)\s*[-/・,、]\s*(\d+(?:\.\d+)?)",
                              unicodedata.normalize("NFKC", get("lv")).strip())
            if m2 and tv is None:
                lv, tv = parse_kv(m2.group(1)), parse_kv(m2.group(2))
                note = f"secondary published as '{get('lv').strip()}'"
                warn.add(utility, "two_secondary_voltages_split_to_lv_tv", f"{path.name}: {short(r, 6)}")
        if not name or hv is None or lv is None:
            # 注記行・小計行・空行はここで落ちる。名前があるのに電圧が読めない行だけ数える
            if name and not re.match(r"^[※＊*注]", name) and (get("hv").strip() or get("lv").strip()):
                warn.add(utility, "unparsed_voltage", f"{path.name}: {short(r, 8)}")
            continue
        if name_strip_re:
            name = re.sub(name_strip_re, "", name)
        out.append(dict(
            utility=utility, substation_raw=name,
            hv_kv=hv, lv_kv=lv, tv_kv=tv,
            n_units=parse_units(get("units")), capacity_value=parse_num(get("cap")),
            capacity_unit=cap_unit if "cap" in col else "", source_url=url,
            source_file=str(path.relative_to(OUT)), row_text=short(r, 6), note=note,
        ))
    if not out:
        warn.add(utility, "no_rows", path.name)
    return out


# ---------------------------------------------------------------------------
# 解析: 東京電力PG の CSV(見出しが多段・列位置が独自)
# ---------------------------------------------------------------------------
# 行頭の欄が「変<地域> <区分> <番号>」(例: 変群馬県 154kV 2 / 変基幹 275kV 1-1 /
# 変東京都（23区） 配電用変電所 12)。区分 154kV・66kV・275kV の行には「一次/二次」の
# 電圧の組(例 500/154)が載るが、22kV と配電用変電所の区分は組の欄が空で、電圧は公表されて
# いない。空の行も「その区分に変圧器がある」情報として残し、hv_kv/lv_kv を空にして note に
# 区分を書く(区分の電圧を一次・二次のどちらかに推定して埋めることはしない)。
# 同じ変圧器が複数の区分(154kV と 66kV)に重ねて載るので、完全一致の重複は後段で落とす。
_TOKYO_LABEL = re.compile(r"^変(?P<area>.+?)\s+(?P<sec>\d+(?:\.\d+)?kV|配電用変電所)\s+(?P<no>[\d\-]+)$")
_PAIR = re.compile(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)(?:\s*/\s*(\d+(?:\.\d+)?))?")


def parse_tokyo_csv(path: Path, url: str, warn: Warn) -> list[dict]:
    text = decode(path.read_bytes())
    rows = list(csv.reader(io.StringIO(text)))
    # 見出し(多段)の 1 段目から列位置を取る
    col = None
    for r in rows[:15]:
        cells = [_hcell(c) for c in r]
        if "変電所名" in cells:
            col = {"name": cells.index("変電所名")}
            for j, c in enumerate(cells):
                if c == "電圧" and "pair" not in col:
                    col["pair"] = j
                elif c.startswith("台数") and "units" not in col:
                    col["units"] = j
                elif c.startswith("設備容量") and "cap" not in col:
                    col["cap"] = j
            break
    if not col or not {"pair", "units", "cap"} <= col.keys():
        warn.add("tokyo", "no_header", path.name)
        return []
    # 設備容量の単位は見出しに無い(「設備容量 (100%×台数)」。隣の運用容量値は MW)
    out = []
    for r in rows:
        if not r or not r[0].strip().startswith("変"):
            continue
        label = unicodedata.normalize("NFKC", re.sub(r"\s+", " ", r[0])).strip()
        if label == "変電所":  # 多段見出しの 2 段目
            continue
        m = _TOKYO_LABEL.match(label)
        if not m:
            warn.add("tokyo", "unparsed_label", f"{path.name}: {short(r, 6)}")
            continue
        get = lambda k: (r[col[k]] if col[k] < len(r) else "")  # noqa: E731
        name = get("name").strip()
        if not name:
            warn.add("tokyo", "empty_name", f"{path.name}: {short(r, 6)}")
            continue
        pm = _PAIR.fullmatch(unicodedata.normalize("NFKC", get("pair")).strip())
        hv = lv = tv = None
        note = ""
        if pm:
            hv, lv = parse_kv(pm.group(1)), parse_kv(pm.group(2))
            tv = parse_kv(pm.group(3)) if pm.group(3) else None
        elif get("pair").strip():
            warn.add("tokyo", "unparsed_voltage", f"{path.name}: {short(r, 6)}")
            note = f"voltage cell unparsed: {get('pair').strip()}"
        else:
            note = f"pair not published; listed under section {m.group('sec')}"
            warn.add("tokyo", f"pair_not_published(section {m.group('sec')})", f"{path.name}: {short(r, 5)}")
        out.append(dict(
            utility="tokyo", substation_raw=name, hv_kv=hv, lv_kv=lv, tv_kv=tv,
            n_units=parse_units(get("units")), capacity_value=parse_num(get("cap")),
            capacity_unit="unknown", source_url=url, source_file=str(path.relative_to(OUT)),
            row_text=short(r, 5), note=note, _label=f"{m.group('area')} {m.group('sec')} {m.group('no')}"))
    if not out:
        warn.add("tokyo", "no_rows", path.name)
    return out


# ---------------------------------------------------------------------------
# 解析: PDF(pdftotext -layout の行)。東京の CSV との照合用
# ---------------------------------------------------------------------------
def pdftotext(path: Path) -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        return ""
    r = subprocess.run([exe, "-layout", "-enc", "UTF-8", str(path), "-"],
                       capture_output=True, timeout=300)
    return r.stdout.decode("utf-8", errors="replace")


def tokyo_pdf_rows(path: Path) -> list[tuple[str, str, float | None, float | None]]:
    """東京 PDF の「変<地域> <区分> <番号>」行 → (区分つき番号, 名前, 一次, 二次)。

    PDF は -layout で列が空白区切りになるので、番号の直後の語を名前、その次が
    「数/数」なら電圧の組とみなす。CSV との照合(件数と組)にだけ使う。
    """
    out = []
    pat = re.compile(r"^変(\S+?)\s+(\d+(?:\.\d+)?kV|配電用変電所)\s+([\d\-]+)\s+(\S+)(?:\s+(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?))?")
    for line in pdftotext(path).splitlines():
        s = unicodedata.normalize("NFKC", line).strip()
        m = pat.match(s)
        if m:
            hv = parse_kv(m.group(5)) if m.group(5) else None
            lv = parse_kv(m.group(6)) if m.group(6) else None
            out.append((f"{m.group(1)} {m.group(2)} {m.group(3)}", m.group(4), hv, lv))
    return out


# ---------------------------------------------------------------------------
# まとめ
# ---------------------------------------------------------------------------
def _pair_str(hv, lv, tv) -> str:
    parts = [fmt_kv(x) for x in (hv, lv, tv) if x is not None]
    return "/".join(parts) if len(parts) >= 2 else "(not published)"


def _rawkey(name: str) -> str:
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", name or ""))


def parse_all(man: dict) -> tuple[list[dict], dict]:
    warn = Warn()
    recs: list[dict] = []
    crosscheck: dict = {}
    by_u = collections.defaultdict(list)
    for f in man.get("files", []):
        by_u[f["utility"]].append(f)

    for u in UTILITIES:
        for f in by_u.get(u, []):
            p = OUT / f["path"]
            name, low = p.name, p.name.lower()
            if low.endswith(".zip") or not p.exists():
                continue
            if u in ("hokkaido", "tohoku", "hokuriku", "chugoku", "shikoku"):
                if low.endswith(".csv") and "_tr_" in low:
                    recs += parse_standard_csv(u, p, f["url"], warn)
            elif u == "chubu":
                if low.endswith(".csv") and "変電所" in name:
                    recs += parse_standard_csv(u, p, f["url"], warn)
            elif u in ("kansai", "kyushu"):
                if low.endswith(".csv"):
                    recs += parse_standard_csv(u, p, f["url"], warn)
            elif u == "tokyo":
                if low.endswith(".csv") and "hendensyo" in low:
                    recs += parse_tokyo_csv(p, f["url"], warn)
            elif u == "okinawa":
                # con_res_mapNN_01 は送電線(見出しに一次/二次電圧が無い)なので変電所の表だけ読む
                if low.endswith(".csv") and find_header(list(csv.reader(io.StringIO(decode(p.read_bytes()))))):
                    recs += parse_standard_csv(u, p, f["url"], warn)

    # 東京: PDF(同内容)の「変」行と CSV の行を照合する
    if by_u.get("tokyo"):
        pdf_rows = collections.Counter()
        for f in by_u["tokyo"]:
            if f["path"].lower().endswith(".pdf") and (OUT / f["path"]).exists():
                for lab, nm, hv, lv in tokyo_pdf_rows(OUT / f["path"]):
                    pdf_rows[(lab, norm_name(nm), hv, lv)] += 1
        csv_rows = collections.Counter(
            (r["_label"], norm_name(r["substation_raw"]), r["hv_kv"], r["lv_kv"]) for r in recs if r["utility"] == "tokyo")
        fmt = lambda k: f"{k[0]} | {k[1]} {_pair_str(k[2], k[3], None)}"  # noqa: E731
        crosscheck["tokyo_pdf_vs_csv"] = {
            "note": "東京の PDF(<地域>_yosochoryu.pdf)は CSV と同内容のはず。区分・番号・名前・組で照合",
            "pdf_rows": sum(pdf_rows.values()), "csv_rows": sum(csv_rows.values()),
            "matched": sum((pdf_rows & csv_rows).values()),
            "in_pdf_not_csv": sum((pdf_rows - csv_rows).values()),
            "in_csv_not_pdf": sum((csv_rows - pdf_rows).values()),
            "examples_in_pdf_not_csv": sorted(fmt(k) for k in (pdf_rows - csv_rows))[:6],
            "examples_in_csv_not_pdf": sorted(fmt(k) for k in (csv_rows - pdf_rows))[:6],
        }
        # 区分ラベル・重複掲載を無視して (名前, 組) の集合で照合。23区と多摩の PDF は 66kV 区分を
        # 同じ表で重ねて載せ、多摩の CSV は 23区側と重なる行を省いているため、件数ではなく集合で比べる
        p2 = {k[1:] for k in pdf_rows}
        c2 = {k[1:] for k in csv_rows}
        crosscheck["tokyo_pdf_vs_csv"].update({
            "set_name_pair_pdf": len(p2), "set_name_pair_csv": len(c2),
            "set_in_pdf_not_csv": len(p2 - c2), "set_in_csv_not_pdf": len(c2 - p2),
            "set_diff_examples": sorted(f"{k[0]} {_pair_str(k[1], k[2], None)}" for k in (p2 ^ c2))[:8],
        })

    # 正規化
    for r in recs:
        r["substation_norm"] = norm_name(r["substation_raw"])
        r["agj_region"] = r["utility"]
        r.setdefault("note", "")
        hv, lv = r["hv_kv"], r["lv_kv"]
        if hv is not None and lv is not None and hv < lv:
            # 発電所の昇圧用などで「一次」が低圧側として載っている。列名(hv/lv)に合わせて入れ替える
            r["hv_kv"], r["lv_kv"] = lv, hv
            r["note"] = (r["note"] + "; " if r["note"] else "") + \
                f"swapped: published primary={fmt_kv(hv)} secondary={fmt_kv(lv)}"
            warn.add(r["utility"], "primary_lt_secondary_swapped", r["row_text"])
        if _rawkey(r["substation_raw"]) in _WITHHELD:
            r["note"] = (r["note"] + "; " if r["note"] else "") + "name withheld in source"
            warn.add(r["utility"], "name_withheld", r["row_text"])
        elif re.fullmatch(r"[0-9A-Za-z\-]+", r["substation_norm"]):
            # 東北は一部の変電所(発電所構内・需要家設備らしい)を名前でなく番号で載せる
            r["note"] = (r["note"] + "; " if r["note"] else "") + "name published as code (withheld)"
            warn.add(r["utility"], "name_published_as_code", r["row_text"])

    # 重複除去 1: 完全一致(名前raw・電圧・台数・容量)。東京は同じ変圧器が 154kV と 66kV の
    # 区分に重ねて載る。組が非公表の行は区分(note)も鍵に入れ、区分違いを潰さない
    seen: dict[tuple, dict] = {}
    stage1: list[dict] = []
    dup_within = collections.Counter()
    dup_cross = collections.Counter()
    for r in recs:
        key = (r["utility"], _rawkey(r["substation_raw"]), r["hv_kv"], r["lv_kv"], r["tv_kv"],
               r["n_units"], r["capacity_value"], r["note"] if r["hv_kv"] is None else "")
        if key in seen:
            if seen[key]["source_file"] == r["source_file"]:
                dup_within[r["utility"]] += 1
            else:
                dup_cross[r["utility"]] += 1
            continue
        seen[key] = r
        stage1.append(r)

    # 重複除去 2: 台数・容量の無い行は、同じ (名前raw・組) で値のある行があれば落とす
    # (沖縄は同じ変電所が N-1 一覧と空容量一覧の両方に載り、前者には台数・容量の列が無い)
    has_vals = {(r["utility"], _rawkey(r["substation_raw"]), r["hv_kv"], r["lv_kv"], r["tv_kv"])
                for r in stage1 if r["n_units"] is not None or r["capacity_value"] is not None}
    final: list[dict] = []
    dup_novals = collections.Counter()
    for r in stage1:
        k = (r["utility"], _rawkey(r["substation_raw"]), r["hv_kv"], r["lv_kv"], r["tv_kv"])
        if r["n_units"] is None and r["capacity_value"] is None and r["hv_kv"] is not None and k in has_vals:
            dup_novals[r["utility"]] += 1
            continue
        final.append(r)

    # 同じ (事業者, 変電所 raw, 組) が値違いで複数ある(バンク別掲載・区分間で値が違う等)
    k2 = collections.Counter((r["utility"], _rawkey(r["substation_raw"]), r["hv_kv"], r["lv_kv"], r["tv_kv"])
                             for r in final if r["hv_kv"] is not None)
    multi = collections.Counter(k[0] for k, n in k2.items() if n > 1)
    for k, n in k2.items():
        if n > 1:
            warn.add(k[0], "same_raw_name_and_pair_multiple_rows(kept)", f"{k[1]} {_pair_str(k[2], k[3], k[4])} x{n}")

    dups = {"exact_duplicates_dropped_within_file": dup_within, "exact_duplicates_dropped_across_files": dup_cross,
            "rows_without_units_dropped_in_favour_of_valued_row": dup_novals}
    summary = build_summary(final, warn, man, crosscheck, dups, multi)
    return final, summary


def build_summary(final, warn, man, crosscheck, dups, multi) -> dict:
    per = {}
    for u in UTILITIES:
        rs = [r for r in final if r["utility"] == u]
        paired = [r for r in rs if r["hv_kv"] is not None and r["lv_kv"] is not None]
        pairs = collections.Counter(_pair_str(r["hv_kv"], r["lv_kv"], r["tv_kv"]) for r in paired)
        per[u] = {
            "rows": len(rs),
            "rows_with_voltage_pair": len(paired),
            "rows_without_voltage_pair": len(rs) - len(paired),
            "substations_norm": len({r["substation_norm"] for r in rs}),
            "substations_norm_with_pair": len({r["substation_norm"] for r in paired}),
            "distinct_voltage_pairs": len(pairs),
            "voltage_pairs": dict(pairs.most_common()),
            "three_winding_rows": sum(1 for r in paired if r["tv_kv"] is not None),
            "capacity_units": dict(collections.Counter(r["capacity_unit"] for r in rs)),
            "files_contributing_rows": len({r["source_file"] for r in rs}),
            **{k: v.get(u, 0) for k, v in dups.items()},
            "keys_with_multiple_rows": multi.get(u, 0),
            "warnings": {k: {"count": n, "examples": warn.examples[u][k]} for k, n in warn.counts[u].items()},
            "source_resolution": man.get("resolve", {}).get(u, {}),
        }
    allpairs = collections.Counter(_pair_str(r["hv_kv"], r["lv_kv"], r["tv_kv"]) for r in final
                                   if r["hv_kv"] is not None)
    not_found = [u for u in UTILITIES if per[u]["rows"] == 0]
    return {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "license_note": "東京電力PG・関西電力送配電は All-Rights-Reserved(他社も転載不可)。"
                        "このディレクトリ(git 管理外)から出さない。リポジトリに書くのは来歴と組の有無の判定まで",
        "total_rows": len(final),
        "total_rows_with_voltage_pair": sum(p["rows_with_voltage_pair"] for p in per.values()),
        "total_substations_norm": len({(r["utility"], r["substation_norm"]) for r in final}),
        "distinct_voltage_pairs_all": dict(allpairs.most_common()),
        "per_utility": per,
        "utilities_not_found": not_found,
        "unstripped_paren_suffixes": dict(_odd_suffixes.most_common(30)),
        "crosscheck": crosscheck,
        "substation_norm_rule": "NFKC → 空白除去 → [末尾の括弧(番号・電圧・号機・(変)(配変)) / 括弧なしの末尾付記"
                                "(66/22kV・11・12・14B・1U・No.1・1号) / 末尾の 周波数変換所|交直変換所|変換所|変電所|開閉所|変電|開閉"
                                "] を変化がなくなるまで繰り返す。(新綾部)(塔)(発)(局配) と「第N」は名前の一部として残す",
        "row_unit_rule": "1 行 = 1 公表行。完全一致(名前raw・電圧・台数・容量)の重複は除去。"
                         "一次<二次で公表された行は hv/lv を入れ替えて note に原表記を残す。"
                         "東京の 22kV 区分・配電用変電所区分は電圧の組が非公表 → hv/lv 空・note に区分",
        "capacity_unit_note": "見出しに単位があるもの(MW)はそのまま。東京・関西は設備容量の見出しに単位が無いので"
                              " unknown(同じ表の運用容量値は MW)",
    }


def write_outputs(final: list[dict], summary: dict) -> None:
    final.sort(key=lambda r: (UTILITIES.index(r["utility"]), r["substation_norm"],
                              -(r["hv_kv"] or 0), -(r["lv_kv"] or 0), r["source_file"]))
    with open(OUT / "transformer_registry.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in final:
            row = dict(r)
            for k in ("hv_kv", "lv_kv", "tv_kv"):
                row[k] = fmt_kv(r[k])
            row["n_units"] = "" if r["n_units"] is None else r["n_units"]
            row["capacity_value"] = fmt_num(r["capacity_value"])
            w.writerow({k: row.get(k, "") for k in COLUMNS})
    with open(OUT / "summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)


def assert_ignored() -> None:
    probe = OUT / "transformer_registry.csv"
    r = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", str(probe)])
    if r.returncode != 0:
        sys.exit(f"中止: {probe} が git に無視されていない(ライセンス上、管理外にしか書けない)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="空容量一覧から変圧器台帳を作る(非公開)")
    ap.add_argument("--offline", action="store_true", help="取得せず raw/MANIFEST.json から再解析")
    ap.add_argument("--utilities", nargs="*", default=None, help="取り直す社(既定: 全社)")
    args = ap.parse_args(argv)
    assert_ignored()
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    prev = json.loads(MANIFEST.read_text("utf-8")) if MANIFEST.exists() else {}
    if args.offline:
        man = prev
    else:
        man = fetch(args.utilities or UTILITIES, prev)
        MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1), "utf-8")
    final, summary = parse_all(man)
    write_outputs(final, summary)
    for u in UTILITIES:
        s = summary["per_utility"][u]
        print(f"{u:9s} rows={s['rows']:5d} subs={s['substations_norm']:5d} pairs={s['distinct_voltage_pairs']:3d}"
              f" warn={sum(v['count'] for v in s['warnings'].values())}")
    print("not found:", summary["utilities_not_found"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
