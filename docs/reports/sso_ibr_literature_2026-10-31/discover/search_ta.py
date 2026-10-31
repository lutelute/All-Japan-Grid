"""OpenAlex の題名・要旨の検索(関連度順)で上位を出す。python3 -I search_ta.py <out.json> '<query>' ..."""
import json, sys, time, urllib.parse, urllib.request
from pathlib import Path
out = {}
for q in sys.argv[2:]:
    u = "https://api.openalex.org/works?" + urllib.parse.urlencode({"filter": f"title_and_abstract.search:{q}", "per-page": 10,
        "select": "id,doi,title,publication_year,cited_by_count,primary_location,type"})
    d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "AGJ-litsurvey"}), timeout=30))
    out[q] = [{"id": w["id"], "doi": w.get("doi"), "title": w.get("title"), "year": w.get("publication_year"),
               "cites": w.get("cited_by_count"), "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name"),
               "type": w.get("type")} for w in d.get("results", [])]
    print("==", q, d.get("meta", {}).get("count"))
    for h in out[q]:
        print(f"  {h['year']} {str(h['cites']):>5s} {str(h['doi'])[16:48]:32s} {str(h['title'])[:80]} | {str(h['venue'])[:24]}")
    time.sleep(0.2)
Path(sys.argv[1]).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
