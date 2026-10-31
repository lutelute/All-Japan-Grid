"""起点の文献を OpenAlex の題名検索で引き、DOI・年・誌・被引用数を確かめる。結果は raw/seeds.json。"""
import json, sys, time, urllib.parse, urllib.request
from pathlib import Path
OUT = Path(sys.argv[1])
SEEDS = [
 ("FBM", "First benchmark model for computer simulation of subsynchronous resonance"),
 ("SBM", "Second benchmark model for computer simulation of subsynchronous resonance"),
 ("TERMS", "Terms, definitions and symbols for subsynchronous oscillations"),
 ("MOHAVE", "Results of subsynchronous resonance test at Mohave"),
 ("KILGORE", "The prediction and control of self-excited oscillations due to series capacitors in power systems"),
 ("SQBUTTE", "Experience with HVDC turbine-generator torsional interaction at Square Butte"),
 ("FSCAN", "Use of frequency scanning techniques for subsynchronous resonance analysis"),
 ("NGH", "A new scheme for subsynchronous resonance damping of torsional oscillations and transient torque"),
 ("ANDERSON", "Subsynchronous resonance in power systems Anderson Agrawal Van Ness"),
 ("PADIYAR", "Analysis of subsynchronous resonance in power systems Padiyar"),
 ("IRWIN", "Sub-synchronous control interactions between type 3 wind turbines and series compensated AC transmission systems"),
 ("ERCOT", "ERCOT experience with sub-synchronous control interaction and proposed remediation"),
 ("SUN", "Impedance-based stability criterion for grid-connected inverters"),
 ("CESPEDES", "Impedance modeling and analysis of grid-connected voltage-source converters"),
 ("BAKHSH", "Couplings in phase domain impedance modeling of grid-connected converters"),
 ("WANGBLAA", "Harmonic stability in power electronic-based power systems: concept, modeling, and analysis"),
 ("HATZI", "Definition and classification of power system stability revisited and extended"),
 ("HAMI", "Subsynchronous interaction between direct-drive PMSG based wind farms and weak AC networks"),
 ("GUYUAN", "Characteristic analysis of subsynchronous resonance in practical wind farms connected to series-compensated transmissions"),
 ("SHAIR", "Overview of emerging subsynchronous oscillations in practical wind power systems"),
 ("CHENG", "Real-world subsynchronous oscillation events in power grids with high penetrations of inverter-based resources"),
 ("FANMIAO", "Nyquist-stability-criterion-based SSR explanation for type-3 wind generators"),
 ("KUNDUR", "Power system stability and control Kundur"),
 ("UIF", "unit interaction factor HVDC torsional interaction screening"),
]
out = {}
for key, q in SEEDS:
    u = "https://api.openalex.org/works?" + urllib.parse.urlencode({"search": q, "per-page": 3,
        "select": "id,doi,title,publication_year,cited_by_count,primary_location,type"})
    try:
        d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "AGJ-litsurvey"}), timeout=30))
    except Exception as e:
        out[key] = {"error": str(e)}; continue
    hits = []
    for w in d.get("results", []):
        src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name")
        hits.append({"id": w["id"], "doi": w.get("doi"), "title": w.get("title"), "year": w.get("publication_year"),
                     "cites": w.get("cited_by_count"), "venue": src, "type": w.get("type")})
    out[key] = {"q": q, "hits": hits}
    time.sleep(0.2)
OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
for k, v in out.items():
    h = (v.get("hits") or [{}])[0]
    print(f"{k:9s} {h.get('year')} {str(h.get('cites')):>5s} {str(h.get('doi'))[:45]:45s} {str(h.get('title'))[:70]} | {str(h.get('venue'))[:40]}")
