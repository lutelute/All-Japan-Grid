"""起点から引用の網を広げる。総説の参考文献(後ろ向き)と、古典を引用する側(前向き)。結果は raw/expand.json。"""
import json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path
RAW = Path(sys.argv[1])
seeds = json.loads((RAW / "seeds.json").read_text(encoding="utf-8"))
sid = {k: v["hits"][0]["id"].rsplit("/", 1)[1] for k, v in seeds.items() if v.get("hits")}
KEY = re.compile(r"sub-?synchronous|super-?synchronous|torsional|\bSSR\b|\bSSCI\b|\bSSO\b|series.compensat|"
                 r"impedance|oscillat|resonan|interaction|benchmark|stability", re.I)
SEL = "id,doi,title,publication_year,cited_by_count,primary_location,type,referenced_works"
def get(params):
    u = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "AGJ-litsurvey"}), timeout=40))
def slim(w):
    return {"id": w["id"].rsplit("/", 1)[1], "doi": w.get("doi"), "title": w.get("title"), "year": w.get("publication_year"),
            "cites": w.get("cited_by_count"), "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name"),
            "type": w.get("type"), "refs": [r.rsplit("/", 1)[1] for r in (w.get("referenced_works") or [])]}
works = {}
# 起点そのもの
ids = list(sid.values())
for i in range(0, len(ids), 40):
    for w in get({"filter": "openalex_id:" + "|".join(ids[i:i + 40]), "per-page": 50, "select": SEL})["results"]:
        works[w["id"].rsplit("/", 1)[1]] = slim(w) | {"seed": True}
# 後ろ向き: 総説の参考文献
for hub in ("CHENG", "SHAIR", "HATZI", "WANGBLAA", "HAMI", "GUYUAN"):
    refs = works[sid[hub]]["refs"]
    for i in range(0, len(refs), 40):
        for w in get({"filter": "openalex_id:" + "|".join(refs[i:i + 40]), "per-page": 50, "select": SEL})["results"]:
            s = slim(w)
            if s["title"] and KEY.search(s["title"]):
                works.setdefault(s["id"], s).setdefault("via", []).append(f"ref:{hub}")
        time.sleep(0.2)
# 前向き: 古典を引用する側(SSO の語を含むものの被引用上位)
for hub in ("FBM", "SQBUTTE", "FSCAN", "SUN", "IRWIN"):
    d = get({"filter": f"cites:{sid[hub]},title_and_abstract.search:subsynchronous|sub-synchronous|supersynchronous|super-synchronous|torsional",
             "sort": "cited_by_count:desc", "per-page": 15, "select": SEL})
    for w in d["results"]:
        s = slim(w)
        works.setdefault(s["id"], s).setdefault("via", []).append(f"cites:{hub}")
    time.sleep(0.2)
(RAW / "expand.json").write_text(json.dumps({"seed_ids": sid, "works": works}, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(works), "works")
