"""読むだけ: 供給ノード台帳の局の近く(≤300m)に、基底に無く PBF(10-06)にある変電所があるか。"""
import json, math, sys
import osmium, yaml
PBF, ROOT = sys.argv[1], sys.argv[2]
R = ["hokkaido","tohoku","tokyo","chubu","hokuriku","kansai","chugoku","shikoku","kyushu","okinawa"]
base = set()
for r in R:
    for f in json.load(open(f"{ROOT}/data/{r}_substations.geojson"))["features"]:
        base.add((f["properties"]["osm_type"], f["properties"]["osm_id"]))
sup = yaml.safe_load(open(f"{ROOT}/config/disclosure_supplement_nodes.yaml"))["nodes"]
class H(osmium.SimpleHandler):
    def __init__(s): super().__init__(); s.new=[]
    def way(s, w):
        if w.tags.get("power")!="substation" or ("way",w.id) in base: return
        try: pts=[(n.lat,n.lon) for n in w.nodes]
        except osmium.InvalidLocationError: return
        s.new.append((sum(p[0] for p in pts)/len(pts), sum(p[1] for p in pts)/len(pts), w.tags.get("name"), w.id))
    def node(s, n):
        if n.tags.get("power")=="substation" and ("node",n.id) not in base:
            s.new.append((n.location.lat, n.location.lon, n.tags.get("name"), n.id))
h=H(); h.apply_file(PBF, locations=True)
def m(a,b):
    return 6371000*2*math.asin(math.sqrt(math.sin(math.radians(b[0]-a[0])/2)**2+math.cos(math.radians(a[0]))*math.cos(math.radians(b[0]))*math.sin(math.radians(b[1]-a[1])/2)**2))
print("supplement nodes", len(sup), "new PBF subs", len(h.new))
for s in sup:
    near=[(round(m((s["lat"],s["lon"]),(x[0],x[1]))),x[2],x[3]) for x in h.new if m((s["lat"],s["lon"]),(x[0],x[1]))<=300]
    if near: print(" ", s["name"], s.get("region"), near)
