"""OSM に線の形が見つからなかった OCCTO の線路を、地理院の電子国土基本図の送電線(ベクトルタイル
experimental_bvmap の structurel・地物コード 8202、ZL14〜16)で確かめる。

地理院の送電線には電圧も名前も無い(架空の送電線だけで、地中のケーブルは載らない)。両端の点の近くの送電線どうしを、
送電線の上だけでたどって、直線の DETOUR 倍 + 3 km 以内でつながるかを見る。タイルは CACHE に置く(取り直さない)。

使い方: python3 scripts/match_occto_gsi.py targets_gsi.json out_gsi.json
(プロキシが要る所では、環境変数 https_proxy を設定する。タイルの置き場は環境変数 OCCTO_GSI_CACHE、既定は ./gsi_z14)
出典: 国土地理院 ベクトルタイル(地理院地図Vector)
"""
import heapq
import json
import math
import os
import sys
import time
import urllib.request
from collections import defaultdict

Z = 14
CACHE = os.environ.get("OCCTO_GSI_CACHE", "gsi_z14")
URL = "https://cyberjapandata.gsi.go.jp/xyz/experimental_bvmap/{z}/{x}/{y}.pbf"
CORRIDOR_KM = 3.0
DETOUR = 1.6
JUMP_KM = 0.05


def km(p, q):
    return math.hypot((p[0] - q[0]) * 111.32 * math.cos(math.radians((p[1] + q[1]) / 2)), (p[1] - q[1]) * 110.57)


# ---- ベクトルタイル(protobuf)の最小限の読み取り ----
def varint(b, i):
    r = s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        s += 7
        if c < 0x80:
            return r, i


def fields(b):
    i = 0
    while i < len(b):
        key, i = varint(b, i)
        f, t = key >> 3, key & 7
        if t == 0:
            v, i = varint(b, i)
        elif t == 2:
            n, i = varint(b, i)
            v = b[i:i + n]
            i += n
        elif t == 1:
            v = b[i:i + 8]
            i += 8
        elif t == 5:
            v = b[i:i + 4]
            i += 4
        else:
            raise ValueError(t)
        yield f, v


def packed(b):
    out, i = [], 0
    while i < len(b):
        v, i = varint(b, i)
        out.append(v)
    return out


def zz(n):
    return (n >> 1) ^ -(n & 1)


def lines_8202(tile, x, y, z):
    """タイルの structurel 層の ftCode 8202(送電線)を経緯度の折れ線で返す。"""
    out = []
    for f, layer in fields(tile):
        if f != 3:
            continue
        name, feats, keys, vals, extent = None, [], [], [], 4096
        for g, v in fields(layer):
            if g == 1:
                name = v.decode()
            elif g == 2:
                feats.append(v)
            elif g == 3:
                keys.append(v.decode())
            elif g == 4:
                val = None
                for h, w in fields(v):
                    val = w.decode() if h == 1 else (w if h in (4, 5) else (zz(w) if h == 6 else w))
                vals.append(val)
            elif g == 5:
                extent = v
        if name != "structurel":
            continue
        for fb in feats:
            tags, geom = [], []
            for g, v in fields(fb):
                if g == 2:
                    tags = packed(v)
                elif g == 4:
                    geom = packed(v)
            props = {keys[tags[k]]: vals[tags[k + 1]] for k in range(0, len(tags), 2)}
            if props.get("ftCode") != 8202:
                continue
            cx = cy = 0
            k, cur = 0, []
            while k < len(geom):
                cmd, cnt = geom[k] & 7, geom[k] >> 3
                k += 1
                if cmd == 1 and cur:
                    out.append(cur)
                    cur = []
                for _ in range(cnt if cmd in (1, 2) else 0):
                    cx += zz(geom[k])
                    cy += zz(geom[k + 1])
                    k += 2
                    n = 2 ** z
                    lon = (x + cx / extent) / n * 360 - 180
                    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + cy / extent) / n))))
                    cur.append((lon, lat))
            if cur:
                out.append(cur)
    return out


def tile_xy(lon, lat, z=Z):
    n = 2 ** z
    return int((lon + 180) / 360 * n), int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)


def tile_center(x, y, z=Z):
    n = 2 ** z
    return ((x + .5) / n * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + .5) / n)))))


def seg_km(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dy * dy
    t = 0 if l2 == 0 else max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2))
    return km(p, (a[0] + t * dx, a[1] + t * dy))


opener = urllib.request.build_opener(urllib.request.ProxyHandler())   # プロキシは環境変数から


def get_tile(x, y):
    p = f"{CACHE}/{x}_{y}.pbf"
    if os.path.exists(p):
        return open(p, "rb").read()
    for _ in range(3):
        try:
            b = opener.open(urllib.request.Request(URL.format(z=Z, x=x, y=y), headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                b = b""
                break
            time.sleep(2)
        except Exception:
            time.sleep(2)
    else:
        return b""
    open(p, "wb").write(b)
    time.sleep(0.15)
    return b


def main(tgt_p, out_p):
    os.makedirs(CACHE, exist_ok=True)
    out = []
    for t in json.load(open(tgt_p)):
        a, b = t["s"]
        straight = km(a, b)
        xa, ya = tile_xy(min(a[0], b[0]) - .04, max(a[1], b[1]) + .04)
        xb, yb = tile_xy(max(a[0], b[0]) + .04, min(a[1], b[1]) - .04)
        tiles = [(x, y) for x in range(xa, xb + 1) for y in range(ya, yb + 1)
                 if seg_km(tile_center(x, y), a, b) < CORRIDOR_KM + 2]
        lines = []
        for x, y in tiles:
            raw = get_tile(x, y)
            if raw:
                lines += lines_8202(raw, x, y, Z)
        # 網: 点は 1e-5 度に丸めた座標。タイルの境の切れ目と JUMP_KM 以内の端は飛べる
        adj = defaultdict(list)
        key = lambda p: (round(p[0], 5), round(p[1], 5))
        ends = []
        for ln in lines:
            for p, q in zip(ln, ln[1:]):
                u, v = key(p), key(q)
                d = km(p, q)
                adj[u].append((v, d))
                adj[v].append((u, d))
            ends += [key(ln[0]), key(ln[-1])]
        grid = defaultdict(list)
        for e in ends:
            grid[(int(e[0] * 200), int(e[1] * 200))].append(e)
        for e in ends:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for f in grid[(int(e[0] * 200) + dx, int(e[1] * 200) + dy)]:
                        if f != e and km(e, f) < JUMP_KM:
                            adj[e].append((f, km(e, f) * 2))
        r = min(0.8, max(0.15, straight * 0.3))
        src = [n for n in adj if km(n, a) < r]
        dst = {n for n in adj if km(n, b) < r}
        res = {k: t[k] for k in ("id", "kind", "kv", "n") if k in t}
        res.update(straight_km=round(straight, 2), tiles=len(tiles), gsi_lines=len(lines), near_a=len(src), near_b=len(dst))
        if not src or not dst:
            res.update(found=False, why="端の近くに地理院の送電線が無い" if not src and not dst else "片端の近くに地理院の送電線が無い")
            out.append(res)
            print(t["id"], res["why"], flush=True)
            continue
        dist = {n: km(n, a) for n in src}
        prev, h, hit = {}, [(d, n) for n, d in dist.items()], None
        heapq.heapify(h)
        while h:
            d, u = heapq.heappop(h)
            if d > dist.get(u, 1e18):
                continue
            if u in dst:
                hit = u
                break
            for v, w in adj[u]:
                if d + w < dist.get(v, 1e18):
                    dist[v], prev[v] = d + w, u
                    heapq.heappush(h, (d + w, v))
        if not hit:
            res.update(found=False, why="地理院の送電線で両端がつながらない")
        else:
            path, u = [hit], hit
            while u in prev:
                u = prev[u]
                path.append(u)
            path.reverse()
            length = sum(km(path[i], path[i + 1]) for i in range(len(path) - 1))
            res.update(found=length <= DETOUR * straight + 3, length_km=round(length, 2),
                       coords=[[round(p[0], 5), round(p[1], 5)] for p in path])
            if not res["found"]:
                res["why"] = "遠回りすぎる"
        out.append(res)
        print(t["id"], "found" if res.get("found") else res.get("why"), res.get("length_km"), flush=True)
    json.dump(out, open(out_p, "w"), ensure_ascii=False)


if __name__ == "__main__":
    main(*sys.argv[1:3])
