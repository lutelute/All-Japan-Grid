"""起点を引用する側(前向き)を被引用数の順に引き、題名で絞る。python3 -I forward.py <out.json> KEY=Wid ..."""
import json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path
KEY = re.compile(r"sub-?synchronous|super-?synchronous|\bSSO\b|\bSSCI\b|oscillat|weak grid|weak ac|phase-locked|\bPLL\b|"
                 r"impedance|grid-forming|grid-following|short.circuit ratio|benchmark|event|stability", re.I)
SEL = "id,doi,title,publication_year,cited_by_count,primary_location,type"
out = {}
for arg in sys.argv[2:]:
    k, wid = arg.split("=")
    u = "https://api.openalex.org/works?" + urllib.parse.urlencode({"filter": f"cites:{wid}", "sort": "cited_by_count:desc",
                                                                     "per-page": 40, "select": SEL})
    d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "AGJ-litsurvey"}), timeout=40))
    rows = [{"id": w["id"].rsplit("/", 1)[1], "doi": w.get("doi"), "title": w.get("title"), "year": w.get("publication_year"),
             "cites": w.get("cited_by_count"), "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name")}
            for w in d["results"] if KEY.search(w.get("title") or "")]
    out[k] = rows
    print("==", k, d["meta"]["count"], "→", len(rows))
    for r in rows[:14]:
        print(f"  {r['year']} {str(r['cites']):>5s} {r['id']:12s} {str(r['doi'])[16:46]:30s} {str(r['title'])[:84]}")
    time.sleep(0.2)
Path(sys.argv[1]).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
