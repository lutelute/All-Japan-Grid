#!/usr/bin/env python3
"""gem.wiki の日本の発電所ページを機械収穫する(1-C GEM容量充填の入力・scratchpad限り).

出力: gem_japan_pages.jsonl (1ページ1行)
  {title, ja_name, tracker, lat, lon, coord_exact, categories, units:[{name,status,cap_raw,cap_mw}]}

規約: 収穫キャッシュはリポジトリに入れない(dataspace方針=外部データは源泉に留める)。
リポジトリに入るのは突合確定後の出典レコード(URL+逐語quote)のみ。
API作法: User-Agent明示・maxlag=5・~2req/s。
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request

API = "https://www.gem.wiki/w/api.php"
UA = "All-Japan-Grid provenance harvester (research; contact: lutebass@gmail.com)"
CATS = [
    "Nuclear power plants in Japan",
    "Coal power stations in Japan",
    "Oil & Gas power stations in Japan",
    "Bioenergy power stations in Japan",
    "Solar farms in Japan",
    "Wind farms in Japan",
    "Hydroelectric power plants in Japan",
    "Geothermal power plants in Japan",
]

def api(params):
    params = dict(params, format="json", maxlag=5)
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                d = json.load(r)
            if "error" in d and d["error"].get("code") == "maxlag":
                time.sleep(3 + attempt * 2)
                continue
            return d
        except Exception as e:  # noqa: BLE001
            if attempt == 4:
                raise
            time.sleep(2 + attempt * 3)
    return None

def members(cat):
    out, cont = [], None
    while True:
        p = {"action": "query", "list": "categorymembers",
             "cmtitle": f"Category:{cat}", "cmlimit": 500, "cmnamespace": 0}
        if cont:
            p["cmcontinue"] = cont
        d = api(p)
        out += [m["title"] for m in d["query"]["categorymembers"]]
        cont = d.get("continue", {}).get("cmcontinue")
        if not cont:
            break
        time.sleep(0.3)
    return out

CAP_RE = re.compile(
    r"([\d,]+(?:\.\d+)?)\s*(MW(?:p|ac|dc)?(?:/(?:dc|ac))?|GW|kW)?\s*$",
    re.IGNORECASE)
COORD_RE = re.compile(r"(-?\d{1,3}\.\d+),\s*(-?\d{1,3}\.\d+)\s*\(exact\)")
COORD_MAP_RE = re.compile(r"#display_map:\s*\n?\s*(-?\d{1,3}\.\d+),\s*(-?\d{1,3}\.\d+)")
JA_RE = re.compile(r"'''.*?'''\s*[（(]([^()（）]*[぀-ヿ㐀-䶿一-鿿][^()（）]*)[）)]")
NAVBAR_RE = re.compile(r"\{\{Navbar-(\w+)\}\}")

def _clean(cell):
    c = re.sub(r"<ref[^>]*/>", "", cell)
    c = re.sub(r"<ref[^>]*>.*?</ref>", "", c, flags=re.DOTALL)
    c = re.sub(r"\[\[([^]|]*\|)?([^]]*)\]\]", r"\2", c)
    return c.strip()

def parse_tables(text):
    """Status列とcapacity列を持つ wikitable からユニット行を抜く(トラッカー横断の汎用)。"""
    units = []
    for tbl in re.findall(r"\{\|.*?\|\}", text, flags=re.DOTALL):
        # ヘッダ行(!...)を集める
        headers = [_clean(h) for h in re.findall(r"^!\s*(.+)$", tbl, flags=re.MULTILINE)]
        if not headers:
            continue
        low = [h.lower() for h in headers]
        try:
            i_status = next(i for i, h in enumerate(low) if h == "status")
            i_cap = next(i for i, h in enumerate(low) if "capacity" in h)
        except StopIteration:
            continue
        i_unit = next((i for i, h in enumerate(low)
                       if h in ("unit name", "phase name", "unit", "phase", "project name")), None)
        # 容量詳細表(Reference net 等)は除外: ヘッダに 'nameplate' が無く 'net' があればスキップ
        if "nameplate" not in " ".join(low) and "capacity" not in low[i_cap]:
            continue
        rows = tbl.split("|-")[1:]
        for row in rows:
            cells = [_clean(c) for c in re.findall(
                r"^\|\s*(.*?)\s*$", row, flags=re.MULTILINE) if not c.startswith("}")]
            cells = [c for c in cells if c != "" or True]
            if len(cells) <= max(i_status, i_cap):
                continue
            status = cells[i_status]
            cap_raw = cells[i_cap]
            m = CAP_RE.search(cap_raw)
            cap_mw = None
            if m:
                v = float(m.group(1).replace(",", ""))
                u = (m.group(2) or "MW").lower()   # 単位なし=列ヘッダのMW
                cap_mw = v * 1000 if u == "gw" else (v / 1000 if u == "kw" else v)
            units.append({
                "name": (cells[i_unit] if i_unit is not None and i_unit < len(cells) else ""),
                "status": status,
                "cap_raw": cap_raw,
                "cap_mw": cap_mw,
            })
    return units

def parse_page(title, text, cat):
    ja = JA_RE.search(text[:1500])
    nav = NAVBAR_RE.search(text)
    lat = lon = None
    exact = False
    m = COORD_RE.search(text)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        exact = True
    else:
        m = COORD_MAP_RE.search(text)
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
    return {
        "title": title,
        "ja_name": ja.group(1).strip() if ja else None,
        "tracker": nav.group(1) if nav else None,
        "category": cat,
        "lat": lat, "lon": lon, "coord_exact": exact,
        "units": parse_tables(text),
    }

def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "gem_japan_pages.jsonl"
    title_cat = {}
    for cat in CATS:
        ms = members(cat)
        print(f"[cat] {cat}: {len(ms)}", flush=True)
        for t in ms:
            title_cat.setdefault(t, cat)
        time.sleep(0.3)
    titles = sorted(title_cat)
    print(f"[total] {len(titles)} pages", flush=True)

    n_done = 0
    with open(out_path, "w", encoding="utf-8") as fh:
        for i in range(0, len(titles), 50):
            batch = titles[i:i + 50]
            d = api({"action": "query", "prop": "revisions", "rvprop": "content",
                     "rvslots": "main", "titles": "|".join(batch)})
            pages = d["query"]["pages"]
            got = {}
            for p in pages.values():
                revs = p.get("revisions")
                if not revs:
                    continue
                content = revs[0].get("slots", {}).get("main", {}).get("*") or revs[0].get("*")
                if content:
                    got[p["title"]] = content
            for t in batch:
                # API側で正規化されたタイトルにも対応
                text = got.get(t)
                if text is None:
                    norm = {k.replace("_", " "): v for k, v in got.items()}
                    text = norm.get(t.replace("_", " "))
                if text is None:
                    continue
                rec = parse_page(t, text, title_cat[t])
                rec["wikitext"] = text
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n_done += 1
            if (i // 50) % 20 == 0:
                print(f"[fetch] {min(i+50,len(titles))}/{len(titles)} parsed={n_done}", flush=True)
            time.sleep(0.4)
    print(f"[done] parsed {n_done} -> {out_path}", flush=True)

if __name__ == "__main__":
    main()
