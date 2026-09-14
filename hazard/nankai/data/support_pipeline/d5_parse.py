#!/usr/bin/env python3
"""D5: extract utility office names/addresses from fetched official office-list pages (dataset D5
in manifest.jsonl) and write records/utility_offices.raw.jsonl (no coordinates yet).

Heuristic per page: an address is a line with a postal code (〒NNN-NNNN, address may continue on
the following lines) or, for Kansai TD (no postal codes), a line that starts with a prefecture/city
and ends with a lot number. The office name is the nearest preceding line that looks like an office
name. For Tohoku NW per-office pages the page title is the office name.
quote = the address text exactly as it appears (lines joined with a space); build_db verifies it.
"""
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path.home() / "agj-hazard-data"
OUT = ROOT / "work" / "utility_offices_raw.jsonl"
HOST_UTIL = {
    "powergrid.chuden.co.jp": "中部電力パワーグリッド", "www.kansai-td.co.jp": "関西電力送配電",
    "www.yonden.co.jp": "四国電力送配電", "www.kyuden.co.jp": "九州電力送配電", "www.energia.co.jp": "中国電力ネットワーク",
    "www.tepco.co.jp": "東京電力パワーグリッド", "www.rikuden.co.jp": "北陸電力送配電", "nw.tohoku-epco.co.jp": "東北電力ネットワーク",
    "www.hepco.co.jp": "北海道電力ネットワーク", "www.okiden.co.jp": "沖縄電力",
}
POSTAL = re.compile(r"〒\s*\d{3}\s*[-－ー‐]\s*\d{4}")
NAME = re.compile(r"(本社|本店|総支社|支社|支店|本部|営業所|事業所|センタ[ーｰ―]|電力所|制御所|事務所|電業所|工務所|分室|給電所)")
BAD_NAME = re.compile(r"[。、「」:：]|お問い?合わせ|一覧|エリアの|について|ください|担当|区域|詳細|検索|地図|MAP|TEL|Tel|電話|住所|所在地|ご案内|0120")
ADDR_NOPOSTAL = re.compile(r"^(北海道|東京都|京都府|大阪府|[^\s]{2,3}県)?[^\s、。]{1,12}?[市区町村郡][^\s、。]*\d")
ADDR_CONT = re.compile(r"[市区町村郡丁目番地号]|\d")
NOISE = re.compile(r"^(別のウィンドウで開きます。?|地図|MAP|Google Maps|Tel.*|TEL.*|電話.*|0\d{1,4}-\d{1,4}-\d{3,4}|0120-.*|住所|所在地)$")


def office_type(name):
    for t in ["総支社", "統括支店", "支社", "支店", "本社", "本店", "本部", "配電営業所", "営業所", "配電事業所", "事業所",
              "ネットワークサービスセンター", "ネットワークセンター", "電力センター", "電力所", "制御所", "電業所", "事務所", "センター"]:
        if t in name:
            return t
    return None


def lines_of(path):
    raw = Path(path).read_bytes()
    soup = BeautifulSoup(raw, "lxml")
    title = soup.title.get_text().strip() if soup.title else ""
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    lines = [re.sub(r"[ \t　]+", " ", ln).strip() for ln in soup.get_text("\n").splitlines()]
    return title, [ln for ln in lines if ln]


def parse(url, path, host):
    title, L = lines_of(path)
    recs = []
    tohoku_page = host == "nw.tohoku-epco.co.jp" and re.search(r"/office/[a-z]{2}_", url)
    kansai = host == "www.kansai-td.co.jp"
    start = 0
    if kansai:
        start = next((i for i, ln in enumerate(L) if ln == "本店・本部一覧"), 0)
    for i in range(start, len(L)):
        ln = L[i]
        addr_lines = None
        skipped_noise = False
        if POSTAL.search(ln):
            addr_lines = [ln]
            rest = POSTAL.sub("", ln).strip()
            j = i + 1
            if len(rest) < 4:  # postal code only: address continues on following lines
                while j < len(L) and j <= i + 3:
                    if NOISE.match(L[j]):
                        skipped_noise = True
                        j += 1
                        continue
                    if ADDR_CONT.search(L[j]) and not NAME.search(L[j][-6:]) and len(L[j]) < 60:
                        addr_lines.append(L[j])
                    break
        elif kansai and ADDR_NOPOSTAL.match(ln) and not NAME.search(ln[-5:]):
            addr_lines = [ln]
            prev = L[i - 1] if i > 0 else ""
            if re.search(r"[市区町村郡]$", prev) and not NAME.search(prev) and not re.search(r"\d", prev):
                addr_lines.insert(0, prev)  # address split over two lines (e.g. 京都府京都市下京区 / 塩小路通…)
            if i + 1 < len(L) and not NAME.search(L[i + 1]) and re.search(r"\d", L[i + 1]) and not re.search(r"\d", ln[-3:]):
                addr_lines.append(L[i + 1])
        if not addr_lines:
            continue
        if len(POSTAL.sub("", " ".join(addr_lines)).strip()) < 4:
            continue  # postal code without a street address
        if tohoku_page:
            name = re.split(r"[｜|]", title)[0].strip()
            label = L[i - 1] if i > 0 and L[i - 1].startswith("■") else ""
            if label:
                name = f"{name} {label}"
        else:
            name = None
            first = i - (len(addr_lines) - 1) if kansai and len(addr_lines) > 1 and not POSTAL.search(addr_lines[0]) else i
            for k in range(first - 1, max(start - 1, first - 9), -1):
                c = L[k]
                if POSTAL.search(c):
                    break
                if NAME.search(c) and not BAD_NAME.search(c) and len(c) <= 30:
                    name = c
                    break
            if not name:
                continue
        addr = " ".join(addr_lines)
        # quote must be contiguous in the page text: drop the postal line when noise lines sat in between
        quote = " ".join(addr_lines[1:]) if skipped_noise and len(addr_lines) > 1 else addr
        recs.append(dict(utility=HOST_UTIL[host], office_name=name, office_type=office_type(name),
                         address=addr, source_url=url, quote=quote, lat=None, lon=None,
                         note="d5_parse.py ヒューリスティック抽出(名称=住所直前の事業所名らしき行)"))
    return recs


def main():
    man = {}
    for ln in (ROOT / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(ln)
        if r["dataset"] == "D5" and r["http_status"] == 200 and "html" in r.get("content_type", "") + r["local_path"]:
            man[r["url"]] = r
    out, seen = [], set()
    for url, r in man.items():
        host = url.split("/")[2]
        if host not in HOST_UTIL:
            continue
        for rec in parse(url, r["local_path"], host):
            key = (rec["utility"], rec["office_name"], re.sub(r"\s", "", rec["address"]))
            if key in seen:
                continue
            seen.add(key)
            out.append(rec)
    OUT.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in out), encoding="utf-8")
    from collections import Counter
    print(Counter(x["utility"] for x in out))
    print(len(out), "->", OUT)


if __name__ == "__main__":
    main()
