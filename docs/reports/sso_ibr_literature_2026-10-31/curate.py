"""厳選した文献の書誌(OpenAlex)と BibTeX(doi.org)を取り、引用の辺を作る。結果は lit.json と refs.bib。python3 -I curate.py <このフォルダ>"""
import json, sys, time, urllib.parse, urllib.request
from pathlib import Path
D = Path(sys.argv[1])
cur = json.loads((D / "curated.json").read_text(encoding="utf-8"))
def req(u, accept=None):
    h = {"User-Agent": "AGJ-litsurvey"}
    if accept: h["Accept"] = accept
    return urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=40).read().decode("utf-8", "replace")
meta = {}
dois = [c[2] for c in cur if c[2]]
for i in range(0, len(dois), 30):
    f = "doi:" + "|".join("https://doi.org/" + d for d in dois[i:i + 30])
    res = json.loads(req("https://api.openalex.org/works?" + urllib.parse.urlencode({"filter": f, "per-page": 50,
        "select": "id,doi,title,publication_year,cited_by_count,primary_location,authorships,referenced_works"})))["results"]
    for w in res:
        meta[w["doi"].lower().replace("https://doi.org/", "")] = w
    time.sleep(0.3)
oa2key = {}
lit = []
for lane, key, doi, role, note in cur:
    w = meta.get(doi.lower()) if doi else None
    if w: oa2key[w["id"].rsplit("/", 1)[1]] = key
    lit.append({"lane": lane, "key": key, "doi": doi, "role": role, "note": note,
                "title": w["title"] if w else None, "year": w["publication_year"] if w else None,
                "cites": w["cited_by_count"] if w else None,
                "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name") if w else None,
                "authors": [a["author"]["display_name"] for a in (w.get("authorships") or [])][:6] if w else [],
                "oa": w["id"].rsplit("/", 1)[1] if w else None,
                "refs": [r.rsplit("/", 1)[1] for r in (w.get("referenced_works") or [])] if w else []})
for x in lit:
    x["cites_in_set"] = sorted({oa2key[r] for r in x["refs"] if r in oa2key})
    del x["refs"]
# doi.org の BibTeX に題名・著者が無いもの(J-STAGE の記事ページの表記で補う)
BIB_ADD = {"JP2021K": "title={技術開発レポート：新北海道本州間連系設備に適用した大容量自励式直流送電システムの開発・実用化}, author={内海, 貴徳}, "}
bib, miss = [], []
for x in lit:
    if not x["doi"]:
        continue
    try:
        b = req("https://doi.org/" + x["doi"], accept="application/x-bibtex").strip()
        if b.startswith("@"):
            b = b.split("{", 1)[0] + "{" + x["key"] + "," + b.split(",", 1)[1]
            if x["key"] in BIB_ADD: b = b.replace("{" + x["key"] + ", ", "{" + x["key"] + ", " + BIB_ADD[x["key"]], 1)
            bib.append(b); x["bib"] = True
        else:
            miss.append(x["key"])
    except Exception as e:
        miss.append(x["key"])
    time.sleep(0.25)
(D / "lit.json").write_text(json.dumps(lit, ensure_ascii=False, indent=1), encoding="utf-8")
(D / "refs.bib").write_text("\n\n".join(bib) + "\n", encoding="utf-8")
print("lit", len(lit), "openalex", sum(1 for x in lit if x["oa"]), "bib", len(bib), "bib-miss", miss)
print("no-openalex", [x["key"] for x in lit if x["doi"] and not x["oa"]])
print("edges", sum(len(x["cites_in_set"]) for x in lit))
