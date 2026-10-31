"""候補の DOI を OpenAlex で引き、書誌・要旨・参考文献を raw/meta.json に。python3 -I fetch.py <cand.tsv> <out.json>"""
import json, sys, time, urllib.parse, urllib.request
from pathlib import Path
rows = [l.split("\t") for l in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
SEL = "id,doi,title,publication_year,cited_by_count,primary_location,authorships,abstract_inverted_index,referenced_works,type"
out = {}
for i in range(0, len(rows), 25):
    chunk = rows[i:i + 25]
    f = "doi:" + "|".join(r[1].strip().lower() for r in chunk)
    u = "https://api.openalex.org/works?" + urllib.parse.urlencode({"filter": f, "per-page": 50, "select": SEL})
    d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "AGJ-litsurvey"}), timeout=40))
    got = {w["doi"].lower().replace("https://doi.org/", ""): w for w in d["results"] if w.get("doi")}
    for key, doi in ((r[0].strip(), r[1].strip().lower()) for r in chunk):
        w = got.get(doi)
        if not w:
            out[key] = {"doi": doi, "missing": True}; continue
        inv = w.get("abstract_inverted_index") or {}
        pos = sorted((p, t) for t, ps in inv.items() for p in ps)
        out[key] = {"doi": doi, "oa": w["id"].rsplit("/", 1)[1], "title": w["title"], "year": w["publication_year"],
                    "cites": w["cited_by_count"], "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name"),
                    "authors": [a["author"]["display_name"] for a in w.get("authorships", [])],
                    "abstract": " ".join(t for _, t in pos), "refs": [r.rsplit("/", 1)[1] for r in (w.get("referenced_works") or [])]}
    time.sleep(0.3)
Path(sys.argv[2]).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
for k, v in out.items():
    if v.get("missing"): print(f"{k:14s} MISSING {v['doi']}"); continue
    a = ", ".join(v["authors"][:2]) + (" ほか" if len(v["authors"]) > 2 else "")
    print(f"{k:14s} {v['year']} {v['cites']:>4} | {a[:40]} | {v['title'][:70]}\n    {v['abstract'][:330]}")
