"""OpenAlex の全文検索(題名・要旨)で上位を出す。python3 -I search.py <out.json> '<query>' ['<query>' ...]"""
import json, sys, time, urllib.parse, urllib.request
from pathlib import Path
out = {}
for q in sys.argv[2:]:
    u = "https://api.openalex.org/works?" + urllib.parse.urlencode({"search": q, "per-page": 8, "sort": "cited_by_count:desc",
        "select": "id,doi,title,publication_year,cited_by_count,primary_location,type"})
    d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "AGJ-litsurvey"}), timeout=30))
    out[q] = [{"id": w["id"], "doi": w.get("doi"), "title": w.get("title"), "year": w.get("publication_year"),
               "cites": w.get("cited_by_count"), "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name"),
               "type": w.get("type")} for w in d.get("results", [])]
    print("==", q)
    for h in out[q]:
        print(f"  {h['year']} {str(h['cites']):>5s} {str(h['doi'])[16:50]:34s} {str(h['title'])[:78]} | {str(h['venue'])[:28]}")
    time.sleep(0.2)
Path(sys.argv[1]).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
