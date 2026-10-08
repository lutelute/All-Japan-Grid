#!/usr/bin/env python3
"""Build ~/agj-hazard-data/hazard_support.sqlite from raw files + curated JSONL records.

Run on pws-160core:
  ~/agj-hazard-data/.venv/bin/python ~/agj-hazard-data/scripts/build_db.py

Parsers (machine-readable primary files):
  D1  TEPCO PG 予想潮流・空容量 CSV (zip)  -> hv_transformers, hv_lines
  D2  令和2年国勢調査 都道府県・市区町村別の主な結果 (xlsx) -> municipal_population
  D3  令和5年住宅・土地統計調査 第6-3表 (xlsx) -> municipal_housing
Curated records (records/*.jsonl, hand-transcribed with verbatim quotes):
  hv_transformers(plan), plant_connections, damage_functions, utility_scale,
  restoration_records, utility_offices, missing
Every row keeps source_url / retrieved_at (from manifest) and quote or cell reference.
quote_verified = 1 when NFKC(quote) with whitespace removed is a substring of the
same-normalised text of the raw source file.
"""
import csv
import glob
import io
import json
import re
import sqlite3
import unicodedata
import zipfile
from pathlib import Path

ROOT = Path.home() / "agj-hazard-data"
RAW = ROOT / "raw"
DB = ROOT / "hazard_support.sqlite"
REC = ROOT / "records"

SCHEMA = """
CREATE TABLE sources(url TEXT, final_url TEXT, local_path TEXT, sha256 TEXT, bytes INTEGER,
  retrieved_at TEXT, dataset TEXT, license TEXT, note TEXT, http_status INTEGER, content_type TEXT);
CREATE TABLE hv_transformers(utility TEXT, source_kind TEXT, area_file TEXT, equipment_id TEXT,
  substation TEXT, voltage_hi_kv REAL, voltage_lo_kv REAL, voltage_as_published TEXT,
  n_banks INTEGER, capacity_total REAL, capacity_unit_as_published TEXT,
  mva_per_bank TEXT, operating_capacity_mw REAL, constraint_factor TEXT, level TEXT,
  status TEXT, source_url TEXT, raw_member TEXT, page TEXT, cell TEXT, quote TEXT,
  retrieved_at TEXT, license TEXT, quote_verified INTEGER, note TEXT);
CREATE TABLE hv_lines(utility TEXT, area_file TEXT, equipment_id TEXT, line_name TEXT,
  voltage_kv REAL, circuits INTEGER, capacity_total REAL, operating_capacity_mw REAL,
  from_node TEXT, to_node TEXT, remarks TEXT, source_url TEXT, raw_member TEXT, cell TEXT,
  quote TEXT, retrieved_at TEXT, license TEXT, quote_verified INTEGER);
CREATE TABLE plant_connections(plant TEXT, operator TEXT, utility TEXT, connection_kv REAL,
  substation TEXT, line_name TEXT, claim TEXT, source_url TEXT, page TEXT, cell TEXT,
  quote TEXT, retrieved_at TEXT, license TEXT, quote_verified INTEGER, note TEXT);
CREATE TABLE municipal_population(muni_code TEXT, pref_code TEXT, pref_name TEXT, muni_name TEXT,
  area_type_code TEXT, population INTEGER, male INTEGER, female INTEGER,
  households_total INTEGER, households_general INTEGER, pop_65plus INTEGER, area_km2 REAL,
  source_url TEXT, sheet TEXT, row_number INTEGER, cells TEXT, nonnumeric_cells TEXT, retrieved_at TEXT, license TEXT);
CREATE TABLE municipal_housing(survey TEXT, muni_code TEXT, muni_name TEXT, area_type_code TEXT,
  construction_period TEXT, category TEXT, dwellings INTEGER, value_as_published TEXT,
  source_url TEXT, sheet TEXT, cell TEXT, retrieved_at TEXT, license TEXT);
CREATE TABLE damage_functions(kind TEXT, parameter TEXT, value REAL, value_as_published TEXT,
  unit TEXT, applies_to TEXT, source_title TEXT, source_url TEXT, page TEXT, cell TEXT,
  quote TEXT, retrieved_at TEXT, license TEXT, quote_verified INTEGER, note TEXT);
CREATE TABLE utility_offices(utility TEXT, office_name TEXT, office_type TEXT, address TEXT,
  phone TEXT, lat REAL, lon REAL, geocode_source TEXT, geocode_title TEXT,
  geocode_n_candidates INTEGER, geocode_check TEXT, source_url TEXT, quote TEXT, retrieved_at TEXT, license TEXT,
  quote_verified INTEGER, note TEXT);
CREATE TABLE utility_scale(utility TEXT, field TEXT, label_verbatim TEXT, value REAL,
  value_as_published TEXT, unit TEXT, fiscal_year TEXT, scope TEXT, source_url TEXT, page TEXT,
  cell TEXT, quote TEXT, retrieved_at TEXT, license TEXT, quote_verified INTEGER, note TEXT);
CREATE TABLE restoration_records(event TEXT, event_label TEXT, utility TEXT, date_or_day TEXT,
  date_verbatim TEXT, metric TEXT, value REAL, value_as_published TEXT, approx INTEGER, unit TEXT,
  definition TEXT, source_url TEXT, page TEXT, cell TEXT, quote TEXT, retrieved_at TEXT,
  license TEXT, quote_verified INTEGER, note TEXT);
CREATE TABLE missing(dataset TEXT, item TEXT, searched TEXT, note TEXT);
CREATE TABLE build_log(key TEXT, value TEXT);
"""

TABLE_COLS = {}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"\s+", "", s)


def load_manifest():
    m = {}
    for ln in (ROOT / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        if ln.strip():
            r = json.loads(ln)
            m[r["url"]] = r  # last fetch wins
    return m


_text_cache = {}


def source_text(path: str, member: str = None) -> str:
    key = (path, member)
    if key in _text_cache:
        return _text_cache[key]
    p = Path(path)
    txt = ""
    try:
        if member:
            with zipfile.ZipFile(p) as z:
                b = z.read(member)
            txt = decode(b)
        elif p.suffix.lower() == ".pdf" or p.name.endswith(".pdf"):
            side = Path(str(p) + ".txt")
            txt = side.read_text(encoding="utf-8") if side.exists() else ""
        else:
            b = p.read_bytes()
            if b[:5] == b"%PDF-":
                side = Path(str(p) + ".txt")
                txt = side.read_text(encoding="utf-8") if side.exists() else ""
            elif b"<html" in b[:3000].lower() or b"<!doctype" in b[:3000].lower():
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(b, "lxml")
                for t in soup(["script", "style", "noscript"]):
                    t.decompose()
                txt = soup.get_text("\n")
            else:
                txt = decode(b)
    except Exception as e:  # keep going; verification will fail
        txt = f"__ERROR__ {e}"
    _text_cache[key] = norm(txt)
    return _text_cache[key]


def decode(b: bytes) -> str:
    if b[:3] == b"\xef\xbb\xbf":
        return b[3:].decode("utf-8")
    for enc in ("utf-8", "cp932"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode("utf-8", "replace")


def verify(man, url, quote, member=None):
    if not quote or url not in man:
        return 0
    t = source_text(man[url]["local_path"], member)
    return 1 if norm(quote) in t else 0


def find_page(man, url, quote):
    """PDF page number (1-based) whose text contains the quote, using the .txt page markers."""
    if not quote or url not in man:
        return None
    side = Path(man[url]["local_path"] + ".txt")
    if not side.exists():
        return None
    q = norm(quote)
    pages = re.split(r"\n=== page (\d+) ===\n", side.read_text(encoding="utf-8"))
    hits = [pages[i] for i in range(1, len(pages) - 1, 2) if q in norm(pages[i + 1])]
    return ",".join(hits) if hits else None


def num(s):
    if s is None:
        return None
    s = str(s).strip().replace(",", "")
    if s in ("", "-", "－", "…", "x", "X", "***"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def insert(con, table, row):
    cols = TABLE_COLS[table]
    con.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                [row.get(c) if not isinstance(row.get(c), (list, dict)) else json.dumps(row.get(c), ensure_ascii=False) for c in cols])


# ---------------------------------------------------------------- D1 TEPCO CSV
TEPCO_BASE = "https://www.tepco.co.jp/pg/consignment/system/pdf/csv_yosochoryu_{}.zip"
TEPCO_UNIT = ("設備容量(100%×台数)。東京電力PGのCSV/PDFには設備容量単独の単位表記なし(運用容量値は(MW))。"
              "同じ空容量一覧様式の中部電力PG CSVは『設備容量(100%×台数)（MW）』と明記")


def parse_tepco(con, man):
    n_tr = n_ln = 0
    for area in ["kikan", "chiba", "ibaraki", "tokyo", "tama", "kanagawa", "saitama", "tochigi",
                 "gunma", "yamanashi", "shizuoka", "nagano", "niigata", "fukushima"]:
        url = TEPCO_BASE.format(area)
        if url not in man:
            continue
        zpath = man[url]["local_path"]
        lic = man[url]["license"]
        with zipfile.ZipFile(zpath) as z:
            for member in z.namelist():
                if not member.endswith(".csv"):
                    continue
                text = decode(z.read(member))
                lines = text.splitlines()
                rows = list(csv.reader(io.StringIO(text)))
                # map csv record index -> physical line for quoting (multi-line headers exist)
                hdr_i = next(i for i, r in enumerate(rows[:10])
                             if any(c.strip() in ("変電所名", "送電線名") for c in r))
                hdr = [c.replace("\n", "").strip() for c in rows[hdr_i]]
                is_sub = "変電所名" in hdr

                def col(name, start=0):
                    return hdr.index(name, start)
                # physical line lookup by exact join is unreliable with quotes; quote = csv line re-serialised
                for ri, r in enumerate(rows[hdr_i + 1:], start=hdr_i + 1):
                    if not r or len(r) < 6:
                        continue
                    idc = next((c for c in r[:3] if re.match(r"^(変|基幹|千葉県|茨城県|東京都|多摩|神奈川県|埼玉県|栃木県|群馬県|山梨県|静岡県|長野県|新潟県|福島県)", c)), None)
                    if not idc or not re.search(r"\d", idc):
                        continue  # header continuation rows such as "変電所,,(kV)"
                    nm = r[hdr.index("変電所名" if is_sub else "送電線名")]
                    raw_line = next((ln for ln in lines if (idc + ",") in ln and ("," + nm) in ln), None)
                    quote = raw_line or ""
                    if is_sub:
                        ci = col("変電所名")
                        v = r[col("電圧")].strip()
                        hi = lo = None
                        m = re.match(r"^(\d+)/(\d+)$", v)
                        if m:
                            hi, lo = float(m.group(1)), float(m.group(2))
                        level = ("基幹" if "基幹" in idc else "配電用変電所" if "配電用変電所" in idc
                                 else (re.search(r"(\d+kV)", idc).group(1) if re.search(r"(\d+kV)", idc) else None))
                        opcol = col("運用")
                        row = dict(utility="東京電力パワーグリッド", source_kind="空容量一覧CSV",
                                   area_file=member, equipment_id=idc.strip(), substation=r[ci].strip(),
                                   voltage_hi_kv=hi, voltage_lo_kv=lo, voltage_as_published=v,
                                   n_banks=int(num(r[col("台数")])) if num(r[col("台数")]) is not None else None,
                                   capacity_total=num(r[col("設備容量")]),
                                   capacity_unit_as_published=TEPCO_UNIT, mva_per_bank=None,
                                   operating_capacity_mw=num(r[opcol]),
                                   constraint_factor=r[opcol + 1].strip() if len(r) > opcol + 1 else None,
                                   level=level, status="existing(2026-06-22時点の一覧)",
                                   source_url=url, raw_member=member, cell=f"{member} csv_record={ri + 1}",
                                   quote=quote, retrieved_at=man[url]["retrieved_at"], license=lic,
                                   note="kikan表の運用列は『運用容量値（電制適用前）』" if area == "kikan" else None)
                        row["quote_verified"] = verify(man, url, quote, member)
                        insert(con, "hv_transformers", row)
                        n_tr += 1
                    else:
                        ci = col("送電線名")
                        fi = col("潮流方向")
                        opcol = col("運用")
                        row = dict(utility="東京電力パワーグリッド", area_file=member, equipment_id=idc.strip(),
                                   line_name=r[ci].strip(), voltage_kv=num(r[col("電圧")]),
                                   circuits=int(num(r[col("回線数")])) if num(r[col("回線数")]) is not None else None,
                                   capacity_total=num(r[col("設備容量")]), operating_capacity_mw=num(r[opcol]),
                                   from_node=r[fi].strip() if len(r) > fi else None,
                                   to_node=r[fi + 2].strip() if len(r) > fi + 2 else None,
                                   remarks=r[col("備考")].strip() if len(r) > col("備考") else None,
                                   source_url=url, raw_member=member, cell=f"{member} csv_record={ri + 1}",
                                   quote=quote, retrieved_at=man[url]["retrieved_at"], license=lic)
                        row["quote_verified"] = verify(man, url, quote, member)
                        insert(con, "hv_lines", row)
                        n_ln += 1
    return n_tr, n_ln


# ---------------------------------------------------------------- D1 Chubu PG 500/275 kV substations
CHUBU_URL = "https://gridmap.powergrid.chuden.co.jp/geo_data/KRSIH010"


def parse_chubu(con, man):
    if CHUBU_URL not in man:
        return 0
    rec = man[CHUBU_URL]
    n = 0
    with zipfile.ZipFile(rec["local_path"]) as z:
        for member in z.namelist():
            if not member.startswith("500"):
                continue
            text = decode(z.read(member))
            lines = text.splitlines()
            hdr_i = next(i for i, ln in enumerate(lines) if ln.startswith("変電所 No"))
            hdr = next(csv.reader([lines[hdr_i]]))
            for li in range(hdr_i + 1, len(lines)):
                r = next(csv.reader([lines[li]]))
                if len(r) < 8 or not r[0].strip().isdigit():
                    continue
                row = dict(utility="中部電力パワーグリッド", source_kind="空容量一覧CSV(500/275kV変電所)",
                           area_file="500/275kV変電所空容量_予想潮流一覧表(zip内CSV)", equipment_id=f"変電所No{r[0]}",
                           substation=r[1], voltage_hi_kv=num(r[2]), voltage_lo_kv=num(r[3]),
                           voltage_as_published=f"{r[2]}/{r[3]}", n_banks=int(num(r[4])), capacity_total=num(r[5]),
                           capacity_unit_as_published=hdr[5], mva_per_bank=None, operating_capacity_mw=num(r[6]),
                           constraint_factor=r[7], level="基幹", status="existing(" + lines[0].strip() + ")",
                           source_url=CHUBU_URL, raw_member=member, cell=f"zip内500/275kV CSV line={li + 1}",
                           quote=lines[li], retrieved_at=rec["retrieved_at"], license=rec["license"])
                row["quote_verified"] = verify(man, CHUBU_URL, lines[li], member)
                insert(con, "hv_transformers", row)
                n += 1
    return n


# ---------------------------------------------------------------- D2 census
CENSUS_URL = "https://www.e-stat.go.jp/stat-search/file-download?statInfId=000032143614&fileKind=0"


def parse_census(con, man):
    import openpyxl
    if CENSUS_URL not in man:
        return 0
    rec = man[CENSUS_URL]
    wb = openpyxl.load_workbook(rec["local_path"], read_only=True)
    ws = wb.worksheets[0]
    n = 0
    for i, r in enumerate(ws.iter_rows(min_row=10, values_only=True), start=10):
        if not r[1]:
            continue
        code, name = str(r[1]).split("_", 1)
        pcode, pname = str(r[0]).split("_", 1)
        from openpyxl.utils import get_column_letter
        nonnum = {get_column_letter(j + 1): r[j] for j in (4, 5, 6, 10, 16, 35, 36)
                  if r[j] is not None and not isinstance(r[j], (int, float))}
        v = lambda j: r[j] if isinstance(r[j], (int, float)) else None
        row = dict(muni_code=code, pref_code=pcode, pref_name=pname, muni_name=name,
                   area_type_code=str(r[3]), population=v(4), male=v(5), female=v(6),
                   households_total=v(35), households_general=v(36), pop_65plus=v(16), area_km2=v(10),
                   nonnumeric_cells=json.dumps(nonnum, ensure_ascii=False) if nonnum else None,
                   source_url=CENSUS_URL, sheet=ws.title, row_number=i,
                   cells=f"B{i}=地域, E{i}=総人口総数(人), F/G=男/女, Q{i}=65歳以上(※不詳補完), K{i}=面積(参考), AJ{i}=総世帯, AK{i}=一般世帯",
                   retrieved_at=rec["retrieved_at"], license=rec["license"])
        insert(con, "municipal_population", row)
        n += 1
    return n


# ---------------------------------------------------------------- D3 housing
HLS_URL = "https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040209854&fileKind=0"


def parse_housing(con, man):
    import openpyxl
    from openpyxl.utils import get_column_letter
    if HLS_URL not in man:
        return 0
    rec = man[HLS_URL]
    wb = openpyxl.load_workbook(rec["local_path"], read_only=True)
    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    hdr = None
    n = 0
    for i, r in enumerate(rows, start=1):
        if i == 7:
            hdr = r
        if i < 10 or not r[1]:
            continue
        code, name = str(r[1]).split("_", 1)
        for j in range(3, len(r)):
            if hdr[j] is None:
                continue
            raw = r[j]
            val = raw if isinstance(raw, (int, float)) else None
            row = dict(survey="令和5年住宅・土地統計調査 第6-3表", muni_code=code, muni_name=name.replace("　", " "),
                       area_type_code=str(r[0]), construction_period=str(r[2]), category=str(hdr[j]),
                       dwellings=val, value_as_published=str(raw), source_url=HLS_URL, sheet=ws.title,
                       cell=f"{get_column_letter(j + 1)}{i}", retrieved_at=rec["retrieved_at"], license=rec["license"])
            insert(con, "municipal_housing", row)
            n += 1
    return n


# ---------------------------------------------------------------- D6 retail contracts by area
EGC_URL = "https://www.egc.meti.go.jp/info/public/excel/20260615001b.xlsx"
AREA_UTIL = {"北海道": "北海道電力ネットワーク", "東北": "東北電力ネットワーク", "東京": "東京電力パワーグリッド",
             "中部": "中部電力パワーグリッド", "北陸": "北陸電力送配電", "関西": "関西電力送配電",
             "中国": "中国電力ネットワーク", "四国": "四国電力送配電", "九州": "九州電力送配電", "沖縄": "沖縄電力"}


def parse_egc_contracts(con, man):
    import openpyxl
    if EGC_URL not in man:
        return 0
    rec = man[EGC_URL]
    ws = openpyxl.load_workbook(rec["local_path"], read_only=True)["契約口数"]
    rows = list(ws.iter_rows(values_only=True))
    start = next(i for i, r in enumerate(rows) if r[0] and str(r[0]).startswith("契約口数"))
    n = 0
    cols = [(1, "retail_contracts_extra_high_voltage", "特別高圧"), (2, "retail_contracts_high_voltage", "高圧"),
            (3, "retail_contracts_low_voltage", "低圧計"), (4, "retail_contracts_low_voltage_lighting", "低圧 電灯"),
            (6, "retail_contracts_total", "合計")]
    for i in range(start + 3, start + 13):
        r = rows[i]
        area = str(r[0])
        for j, field, label in cols:
            row = dict(utility=AREA_UTIL.get(area, area), field=field, label_verbatim=f"契約口数 合計 {label}",
                       value=r[j], value_as_published=str(r[j]), unit="件", fiscal_year="2026年3月分",
                       scope=f"供給区域={area} の小売契約口数(みなし小売+新電力)。一般送配電事業者の需要家数そのものではない",
                       source_url=EGC_URL, page=None, cell=f"シート契約口数 {chr(65 + j)}{i + 1} (行={area})",
                       quote=None, retrieved_at=rec["retrieved_at"], license=rec["license"], quote_verified=None,
                       note="電力取引報 令和8年3月分(令和8年6月15日公表)。数値はセル参照で確認")
            insert(con, "utility_scale", row)
            n += 1
    return n


# ---------------------------------------------------------------- curated JSONL
def load_records(con, man):
    counts = {}
    for f in sorted(glob.glob(str(REC / "*.jsonl"))):
        name = Path(f).stem
        table = re.sub(r"^(missing).*", r"\1", name)
        table = re.sub(r"\.(.*)$", "", table)
        if table not in TABLE_COLS:
            print("skip", f)
            continue
        for ln_no, ln in enumerate(Path(f).read_text(encoding="utf-8").splitlines(), 1):
            if not ln.strip():
                continue
            r = json.loads(ln)
            if table != "missing":
                url = r.get("source_url")
                if url in man:
                    r.setdefault("retrieved_at", man[url]["retrieved_at"])
                    r.setdefault("license", man[url]["license"])
                    if not r.get("retrieved_at"):
                        r["retrieved_at"] = man[url]["retrieved_at"]
                else:
                    r["note"] = ((r.get("note") or "") + " [source_url not in manifest]").strip()
                r["quote_verified"] = verify(man, url, r.get("quote"), r.get("raw_member"))
                if "page" in TABLE_COLS[table] and not r.get("page"):
                    pg = find_page(man, url, r.get("quote"))
                    if pg:
                        r["page"] = f"PDF p.{pg} (auto)"
                if isinstance(r.get("approx"), bool):
                    r["approx"] = int(r["approx"])
                if r.get("page") is not None:
                    r["page"] = str(r["page"])
            insert(con, table, r)
            counts[table] = counts.get(table, 0) + 1
    return counts


def main():
    tmp = DB.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        TABLE_COLS[t] = [c[1] for c in con.execute(f"PRAGMA table_info({t})")]
    man = load_manifest()
    for r in man.values():
        insert(con, "sources", r)
    log = {}
    log["hv_transformers_csv"], log["hv_lines_csv"] = parse_tepco(con, man)
    log["hv_transformers_chubu"] = parse_chubu(con, man)
    log["municipal_population"] = parse_census(con, man)
    log["municipal_housing"] = parse_housing(con, man)
    log["utility_scale_egc"] = parse_egc_contracts(con, man)
    log.update({f"records:{k}": v for k, v in load_records(con, man).items()})
    import datetime as dt
    log["built_at"] = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds")
    for k, v in log.items():
        con.execute("INSERT INTO build_log VALUES(?,?)", (k, str(v)))
    con.execute("CREATE VIEW municipal_housing_wooden AS SELECT muni_code, muni_name, area_type_code, "
                "MAX(CASE WHEN category='0_総数' THEN dwellings END) total, "
                "MAX(CASE WHEN category='1_木造' THEN dwellings END) wooden, "
                "MAX(CASE WHEN category='2_非木造' THEN dwellings END) non_wooden "
                "FROM municipal_housing WHERE construction_period='00_総数' GROUP BY muni_code, muni_name, area_type_code")
    con.commit()
    for t in TABLE_COLS:
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        extra = ""
        if "quote_verified" in TABLE_COLS[t] and n:
            v = con.execute(f"SELECT SUM(quote_verified) FROM {t}").fetchone()[0]
            extra = f" quote_verified={v}/{n}"
        print(f"{t}: {n}{extra}")
    con.close()
    tmp.replace(DB)
    print(json.dumps(log, ensure_ascii=False))


if __name__ == "__main__":
    main()
