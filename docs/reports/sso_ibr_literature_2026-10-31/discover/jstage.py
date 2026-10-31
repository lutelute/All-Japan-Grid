"""J-STAGE の検索 API で国内の文献を引く。python3 -I jstage.py <out.json> 語 ..."""
import json, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
NS = {"a": "http://www.w3.org/2005/Atom", "p": "http://prismstandard.org/namespaces/basic/2.0/"}
out = {}
for kw in sys.argv[2:]:
    u = "https://api.jstage.jst.go.jp/searchapi/do?" + urllib.parse.urlencode({"service": 3, "text": kw, "count": 20})
    try:
        x = ET.fromstring(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "AGJ-litsurvey"}), timeout=40).read())
    except Exception as e:
        print(kw, "ERR", e); continue
    rows = []
    for e in x.findall("a:entry", NS):
        t = e.find("a:article_title/a:ja", NS); te = e.find("a:article_title/a:en", NS)
        j = e.find("a:material_title/a:ja", NS)
        doi = e.find("p:doi", NS); yr = e.find("a:pubyear", NS)
        rows.append({"title": (t.text if t is not None and t.text else (te.text if te is not None else None)),
                     "journal": j.text if j is not None else None, "doi": doi.text if doi is not None else None,
                     "year": yr.text if yr is not None else None})
    out[kw] = rows
    print("==", kw, len(rows))
    for r in rows[:12]: print(f"  {r['year']} {str(r['doi'])[:32]:32s} {str(r['title'])[:70]} | {str(r['journal'])[:22]}")
    time.sleep(0.5)
Path(sys.argv[1]).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
