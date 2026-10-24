"""読むだけ: 10-06 の Geofabrik 電力 PBF と、基底 data/*_{lines,substations}.geojson(08-16)の osm id を比べる。"""
import json, sys, collections
import osmium

PBF, DATA = sys.argv[1], sys.argv[2]
R = ["hokkaido","tohoku","tokyo","chubu","hokuriku","kansai","chugoku","shikoku","kyushu","okinawa"]
import yaml
cfg = yaml.safe_load(open(DATA + "/../config/regions.yaml"))
bbs = [v["bounding_box"] for v in cfg["regions"].values() if v.get("bounding_box")]
def inside(lat, lon):
    return any(b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"] for b in bbs)

base = {"lines": {}, "substations": {}}
for r in R:
    for layer in base:
        for f in json.load(open(f"{DATA}/{r}_{layer}.geojson"))["features"]:
            p = f["properties"]
            k = (p.get("osm_type"), p.get("osm_id"))
            g = f["geometry"]
            if g["type"] == "LineString":
                c = g["coordinates"]; sig = (len(c), tuple(round(x, 6) for x in c[0]), tuple(round(x, 6) for x in c[-1]))
            else:
                sig = None
            tags = {t: p.get(t) for t in ("voltage", "circuits", "cables", "name", "power")}
            base[layer][k] = (sig, tags)

class H(osmium.SimpleHandler):
    def __init__(self):
        super().__init__(); self.lines = {}; self.subs = {}
    def way(self, w):
        pw = w.tags.get("power")
        if pw not in ("line", "cable", "substation"):
            return
        try:
            locs = [(n.lon, n.lat) for n in w.nodes]
        except osmium.InvalidLocationError:
            return
        if not locs: return
        lat, lon = locs[0][1], locs[0][0]
        if not inside(lat, lon): return
        tags = {t: w.tags.get(t) for t in ("voltage", "circuits", "cables", "name", "power")}
        if pw in ("line", "cable"):
            sig = (len(locs), tuple(round(x, 6) for x in locs[0]), tuple(round(x, 6) for x in locs[-1]))
            self.lines[("way", w.id)] = (sig, tags)
        else:
            self.subs[("way", w.id)] = (None, tags)
    def node(self, n):
        if n.tags.get("power") == "substation" and inside(n.location.lat, n.location.lon):
            self.subs[("node", n.id)] = (None, {t: n.tags.get(t) for t in ("voltage","circuits","cables","name","power")})

h = H(); h.apply_file(PBF, locations=True)
for layer, new in (("lines", h.lines), ("substations", h.subs)):
    old = base[layer]
    ow = {k: v for k, v in old.items() if k[0] in ("way", "node")}
    gone = ow.keys() - new.keys(); added = new.keys() - ow.keys(); common = ow.keys() & new.keys()
    geom = sum(1 for k in common if ow[k][0] and new[k][0] and ow[k][0] != new[k][0])
    tagch = collections.Counter()
    for k in common:
        for t in ("voltage", "circuits", "cables", "name"):
            a, b = ow[k][1].get(t), new[k][1].get(t)
            if t == "name" and a and not b: continue  # 基底の名前は enrich 込み
            if (a or None) != (b or None) and not (t == "name" and a and b and a != b and False):
                tagch[t] += 1
    print(f"{layer}: base(way/node)={len(ow)} pbf={len(new)} 消えた={len(gone)} 増えた={len(added)} 共通={len(common)} 幾何変化={geom} タグ変化={dict(tagch)}")
