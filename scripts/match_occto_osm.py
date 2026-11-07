"""OCCTO の線路の点線(両端の変電所を結んだ模式・モデルの線の切れ目)に、OSM の送電線があるかを確かめる。

OSM(Geofabrik 2026-11-05 の power=line/cable と route=power)の網の上で、両端の点の近く(END_KM)の
OSM の点どうしを、電圧が合う線だけでたどる最短の道を探す。線路名が合う way(way の name か、属する route=power の
name)は近いとみなして優先する。OSM の way の切れ目(JUMP_KM 以内の端どうし)は飛べるが遠いとみなす。
道の長さが直線の DETOUR 倍 + 3 km を超えたら採らない。電圧の合う線だけでつながらなければ、電圧の違う線も
遠いとみなして通る 2 回目を探し、道の半分以上が電圧の合う線か名前の合う線のときだけ採る。両端の点の近さ(半径)は
直線の長さの 0.35 倍(0.15〜1.2 km)。

使い方(OSM の取得データ tw_japan_t0.json を置いた計算機で。環境変数 AJG_OSM_RAW_TOWERS の指すフォルダにある):
    python3 scripts/match_occto_osm.py $AJG_OSM_RAW_TOWERS/tw_japan_t0.json targets.json out_osm.json
対象(targets.json)と結果のまとめは scripts/build_occto_line_shapes.py。地図データ © OpenStreetMap contributors(ODbL 1.0)
"""
import heapq
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict

END_KM = 1.2
JUMP_KM = 0.25
DETOUR = 1.6


def km(p, q):
    return math.hypot((p[0] - q[0]) * 111.32 * math.cos(math.radians((p[1] + q[1]) / 2)), (p[1] - q[1]) * 110.57)


def nf(s):
    return unicodedata.normalize("NFKC", str(s or "")).replace(" ", "").replace("　", "")


def stem(name):
    n = nf(name)
    n = re.sub(r"[(（].*?[)）]", "", n)
    n = re.sub(r"\d+/?\d*L$", "", n)
    n = re.sub(r"\d+号(線)?$", "", n)
    n = re.sub(r"(第?\d+|[一二三四])号?$", "", n)
    return n


def volts(t):
    out = set()
    for v in re.split(r"[;,]", str(t.get("voltage", ""))):
        try:
            x = float(v)
            out.add(int(round(x / 1000)) if x > 1000 else int(round(x)))
        except ValueError:
            pass
    return out


def main(raw_p, tgt_p, out_p):
    E = json.load(open(raw_p))["elements"]
    node = {e["id"]: (e["lon"], e["lat"]) for e in E if e["type"] == "node"}
    ways = {e["id"]: e for e in E if e["type"] == "way" and e.get("tags", {}).get("power") in ("line", "cable", "minor_line")}
    rel_names = defaultdict(set)
    for r in E:
        if r["type"] == "relation":
            nm = r.get("tags", {}).get("name")
            for m in r.get("members", []):
                if m["type"] == "way" and nm:
                    rel_names[m["ref"]].add(nf(nm))
    wv = {w: volts(e.get("tags", {})) for w, e in ways.items()}
    wname = {w: {nf(e.get("tags", {}).get("name", ""))} | rel_names[w] for w, e in ways.items()}
    adj = defaultdict(list)            # node -> [(node, km, way)]
    grid = defaultdict(set)            # 0.01° の升目 -> node
    ends = []
    for w, e in ways.items():
        ns = [n for n in e["nodes"] if n in node]
        for u, v in zip(ns, ns[1:]):
            d = km(node[u], node[v])
            adj[u].append((v, d, w))
            adj[v].append((u, d, w))
        for n in ns:
            p = node[n]
            grid[(int(p[0] * 100), int(p[1] * 100))].add(n)
        if ns:
            ends += [(ns[0], w), (ns[-1], w)]
    # way の端どうしの切れ目を飛ぶ
    egrid = defaultdict(list)
    for n, w in ends:
        p = node[n]
        egrid[(int(p[0] * 100), int(p[1] * 100))].append((n, w))
    jumps = 0
    for n, w in ends:
        p = node[n]
        gx, gy = int(p[0] * 100), int(p[1] * 100)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for m, w2 in egrid[(gx + dx, gy + dy)]:
                    if m != n and w2 != w:
                        d = km(p, node[m])
                        if d < JUMP_KM:
                            adj[n].append((m, d, -w2))     # 負の way = 飛び
                            jumps += 1

    def near(p, r):
        gx, gy = int(p[0] * 100), int(p[1] * 100)
        k = int(r / 0.9) + 1
        return [n for dx in range(-k, k + 1) for dy in range(-k, k + 1) for n in grid[(gx + dx, gy + dy)]
                if km(node[n], p) < r]

    def search(a, b, kv, st, r, relax):
        src, dst = set(near(a, r)), set(near(b, r))
        if not src or not dst:
            return None, (len(src), len(dst))
        limit = DETOUR * km(a, b) + 3.0
        dist = {n: km(node[n], a) * 2 for n in src}
        prev = {}
        h = [(d, n) for n, d in dist.items()]
        heapq.heapify(h)
        while h:
            d, u = heapq.heappop(h)
            if d > dist.get(u, 1e18):
                continue
            if u in dst and u not in src:
                break
            if d > limit * 1.5:
                return None, "far"
            for v, l, w in adj[u]:
                if w < 0:
                    c = l * 3
                else:
                    vs, hit = wv[w], st and any(st in nm for nm in wname[w])
                    if vs and kv not in vs:
                        if not relax:
                            continue
                        c = l * (0.8 if hit else 2.5)
                    else:
                        c = l * (1.0 if vs else 1.5) * (0.7 if hit else 1.0)
                if d + c < dist.get(v, 1e18):
                    dist[v], prev[v] = d + c, (u, w, l)
                    heapq.heappush(h, (d + c, v))
        else:
            return None, "nopath"
        path, used = [u], []
        while u in prev:
            u0, w, l = prev[u]
            path.append(u0)
            used.append((w, l))
            u = u0
        path.reverse()
        return (path, used), None

    out = []
    for t in json.load(open(tgt_p)):
        a, b = t["s"]
        kv, st = t["kv"], stem(t["n"])
        straight = km(a, b)
        res = {k: t[k] for k in ("id", "kind", "gap", "kv", "n") if k in t}
        res["straight_km"] = round(straight, 2)
        r = min(END_KM, max(0.15, straight * 0.35))
        if straight < 0.3:
            res.update(found=False, why="短い(300 m 未満)")
            out.append(res)
            continue
        plen = lambda g: sum(l for _, l in g[1])
        got, why = search(a, b, kv, st, r, False)
        res["pass"] = 1
        # 電圧の合う線だけでは、つながらないか遠回りすぎるとき(500 kV で造って 275 kV で使う線など)は 2 回目
        if not (isinstance(why, tuple) and 0 in why) and (got is None or plen(got) > DETOUR * straight + 3.0):
            got2, _ = search(a, b, kv, st, r, True)
            if got2 is not None and (got is None or plen(got2) < plen(got)):
                got, res["pass"] = got2, 2
        if got is None:
            res["found"] = False
            res["why"] = ("端の近くに OSM の送電線が無い" if why == (0, 0) else "片端の近くに OSM の送電線が無い"
                          if isinstance(why, tuple) else "OSM の線で両端がつながらない")
            out.append(res)
            continue
        path, used = got
        length = sum(l for _, l in used)
        named = sum(l for w, l in used if w > 0 and st and any(st in nm for nm in wname[w]))
        kvok = sum(l for w, l in used if w > 0 and (not wv[w] or kv in wv[w]))
        jumped = sum(l for w, l in used if w < 0)
        coords = [list(node[n]) for n in path]
        res.update({
            "length_km": round(length, 2), "named_frac": round(named / length, 2) if length else 0,
            "kv_frac": round(kvok / length, 2) if length else 0, "jump_km": round(jumped, 2),
            "ways": sorted({abs(w) for w, _ in used}),
            "names": sorted({nm for w, _ in used if w > 0 for nm in wname[w] if nm}),
            "volts": sorted({v for w, _ in used if w > 0 for v in wv[w]}),
            "end_gap_km": [round(km(a, coords[0]), 2), round(km(b, coords[-1]), 2)],
            "coords": [[round(x, 5), round(y, 5)] for x, y in coords],
        })
        ok_len = length <= DETOUR * straight + 3.0
        ok_ev = res["pass"] == 1 or res["kv_frac"] >= 0.5 or res["named_frac"] >= 0.5
        res["found"] = ok_len and ok_ev
        if not res["found"]:
            res["why"] = "遠回りすぎる" if not ok_len else "電圧も名前も合わない線しか無い"
        out.append(res)
    json.dump(out, open(out_p, "w"), ensure_ascii=False)
    n = sum(1 for r in out if r["found"])
    print(f"ways {len(ways)}・飛び {jumps}・対象 {len(out)}・見つかった {n}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
