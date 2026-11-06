"""OSM の送電線(way)を「路線」にまとめる(2026-11-07、ビューアーの路線ごとの選択のため)。

OSM の送電線は細切れの way で描かれていて、1 本の路線(例: ○○幹線)が何十本にも分かれている。
地図で線を選んだときに路線の全体を光らせるため、way を次の 3 つの規則だけでまとめる。
どの規則でつないだかは路線ごとに数えて残す(推測でつないだ所が見えるように)。

  1. same_name     同じ名前(``name`` を ; / で分けた組が全く同じ)で、電圧が矛盾せず、点を共有する。
                   「上群線/群馬幹線」のように 1 本の way に 2 つの線の名前があるもの(1 列の鉄塔に 2 路線)は、
                   その組と全く同じ名前の way としかつながない(上群線と群馬幹線を 1 つの路線にしない)
  2. continuation  名前の無い way どうしが端点で会い、その点に way が 2 本しかなく、電圧が同じ
  3. half_named    片方だけ名前のある way どうしが 2 と同じ条件で会い、電圧が分かっている
                   (名前の無い側は「隣の区間の名前」= 推定と印を付ける)

つながないもの:
  - 1 基の鉄塔に別の線が載っている(併架)。OSM では鉄塔の点を共有するが、電気的には別の線
  - 電圧の違う way(電圧が分かっている同士で共通の値が無い)
  - 名前の違う 2 つのまとまりを、名前の無い区間で橋渡しすること(まとまりの名前が食い違うなら止める)

これは観測(OSM)から作った derived の層で、正典(docs/data/built)は変えない
(docs/OBSERVED_VS_DERIVED.md)。入力は Overpass で取った ``data/osm_raw_towers/tw_*_t*.json``
(scripts/tower_connectivity.py が書く。git の外)。
"""
from __future__ import annotations

import collections
import glob
import hashlib
import json
import os
import re
from typing import Dict, Iterable, List, Optional, Set, Tuple

LINE_POWER = ("line", "cable", "minor_line")


# ── 読み込み ─────────────────────────────────────────────

def raw_files(raw_dir: str) -> List[str]:
    return sorted(glob.glob(os.path.join(raw_dir, "tw_*_t*.json")))


def load_raw(raw_dir: str):
    """タイルに分けて取った Overpass の結果を重複なしにまとめる。

    返り値: (nodes: {id: element}, ways: {id: element}, info: {files, sha256, osm_base_min/max})
    タイルは地域の外接矩形を 3x3 に割ったもので重なりがあるので、同じ id は最初の 1 つだけ使う。
    """
    nodes: Dict[int, dict] = {}
    ways: Dict[int, dict] = {}
    h = hashlib.sha256()
    stamps = []
    files = raw_files(raw_dir)
    for f in files:
        with open(f, "rb") as fh:
            blob = fh.read()
        h.update(os.path.basename(f).encode())
        h.update(hashlib.sha256(blob).digest())
        d = json.loads(blob)
        ts = (d.get("osm3s") or {}).get("timestamp_osm_base")
        if ts:
            stamps.append(ts)
        for e in d.get("elements", []):
            if e["type"] == "node":
                nodes.setdefault(e["id"], e)
            elif e["type"] == "way" and (e.get("tags") or {}).get("power") in LINE_POWER:
                ways.setdefault(e["id"], e)
    info = {
        "files": len(files),
        "sha256": h.hexdigest(),
        "osm_base_min": min(stamps) if stamps else None,
        "osm_base_max": max(stamps) if stamps else None,
    }
    return nodes, ways, info


# ── 値の読み方 ───────────────────────────────────────────

def kv_set(tags: dict) -> Set[float]:
    """voltage タグ("154000;66000" など)を kV の集合にする。1 kV 未満の数字は捨てる。"""
    out = set()
    for x in re.findall(r"\d+(?:\.\d+)?", str(tags.get("voltage") or "")):
        v = float(x)
        if v >= 1000:
            out.add(round(v / 1000.0, 1))
    return out


_ROMAJI_SUFFIX = re.compile(r"\s*[(（][\x20-\x7eÀ-ɏḀ-ỿ]+[)）]\s*$")


def name_set(tags: dict) -> Set[str]:
    """name を ; と / で分け、空白と末尾のローマ字の読み(「東海幹線 (Tōkai-kansen)」の括弧)を除いた集合にする。"""
    raw = str(tags.get("name") or "")
    out = set()
    for p in re.split(r"[;/]", raw):
        p = _ROMAJI_SUFFIX.sub("", p.strip())
        p = re.sub(r"\s+", "", p)
        if p:
            out.add(p)
    return out


def kv_compatible(a: Set[float], b: Set[float]) -> bool:
    return not a or not b or bool(a & b)


# ── まとめる ─────────────────────────────────────────────

class _Comp:
    """Union-Find。まとまりごとに名前と電圧の集合を持ち、食い違うまとめ方を拒む。"""

    def __init__(self, ways: Dict[int, dict]):
        self.par = {w: w for w in ways}
        self.names = {w: set(name_set(ways[w].get("tags") or {})) for w in ways}
        self.kvs = {w: set(kv_set(ways[w].get("tags") or {})) for w in ways}

    def find(self, x):
        p = self.par
        while p[x] != x:
            p[x] = p[p[x]]
            x = p[x]
        return x

    def union(self, a, b) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        na, nb = self.names[ra], self.names[rb]
        if na and nb and not (na & nb):
            return False          # 名前の違うまとまりは橋渡ししない
        if not kv_compatible(self.kvs[ra], self.kvs[rb]):
            return False
        if ra > rb:               # 小さい id を根にして結果を順序に依らず決める
            ra, rb = rb, ra
        self.par[rb] = ra
        self.names[ra] |= self.names.pop(rb)
        self.kvs[ra] |= self.kvs.pop(rb)
        return True


def node_index(ways: Dict[int, dict]) -> Dict[int, List[int]]:
    idx: Dict[int, List[int]] = collections.defaultdict(list)
    for wid in sorted(ways):
        for nid in dict.fromkeys(ways[wid]["nodes"]):   # 閉じた way で同じ点を二度数えない
            idx[nid].append(wid)
    return idx


def assemble(ways: Dict[int, dict]):
    """way をまとめる。返り値: (route_of: {way_id: route_id}, joins: {route_id: Counter(規則)})。

    route_id はまとまりの中で一番小さい way id(OSM が変わらない限り同じ番号になる)。
    """
    comp = _Comp(ways)
    nidx = node_index(ways)
    tags = {w: (ways[w].get("tags") or {}) for w in ways}
    ends = {w: (ways[w]["nodes"][0], ways[w]["nodes"][-1]) for w in ways}
    reason_edges = []   # (way_a, way_b, 規則)

    def try_join(a, b, why):
        if comp.union(a, b):
            reason_edges.append((a, b, why))

    nodes_sorted = sorted(nidx)
    # 1. 同じ名前
    for nid in nodes_sorted:
        ws = nidx[nid]
        if len(ws) < 2:
            continue
        for i in range(len(ws)):
            ni = name_set(tags[ws[i]])
            if not ni:
                continue
            for j in range(i + 1, len(ws)):
                nj = name_set(tags[ws[j]])
                if nj and ni == nj and kv_compatible(kv_set(tags[ws[i]]), kv_set(tags[ws[j]])):
                    try_join(ws[i], ws[j], "same_name")
    # 2・3. 端点で 2 本だけが会うつなぎ
    for nid in nodes_sorted:
        ws = nidx[nid]
        if len(ws) != 2:
            continue
        a, b = ws
        if nid not in ends[a] or nid not in ends[b]:
            continue
        ka, kb = kv_set(tags[a]), kv_set(tags[b])
        na, nb = name_set(tags[a]), name_set(tags[b])
        if not na and not nb:
            if ka == kb:
                try_join(a, b, "continuation")
        elif bool(na) != bool(nb):
            if ka and ka == kb:
                try_join(a, b, "half_named")
    route_of = {w: comp.find(w) for w in ways}
    joins: Dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    for a, _b, why in reason_edges:
        joins[route_of[a]][why] += 1
    return route_of, joins


def members(route_of: Dict[int, int]) -> Dict[int, List[int]]:
    out: Dict[int, List[int]] = collections.defaultdict(list)
    for w, r in route_of.items():
        out[r].append(w)
    for r in out:
        out[r].sort()
    return dict(out)


# ── 路線の属性 ───────────────────────────────────────────

def route_name(way_ids: Iterable[int], ways: Dict[int, dict], nodes: Dict[int, dict]):
    """路線の名前 = 名前の付いた way のうち、長さで一番多い名前。

    返り値: (name or None, 名前の無い way の本数)
    """
    acc = collections.Counter()
    unnamed = 0
    for w in way_ids:
        t = ways[w].get("tags") or {}
        nm = str(t.get("name") or "").strip()
        if nm:
            acc[nm] += way_length_km(ways[w], nodes) + 1e-9
        else:
            unnamed += 1
    if not acc:
        return None, unnamed
    best = sorted(acc.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return best, unnamed


def _hav_km(lat1, lon1, lat2, lon2):
    import math
    p = math.pi / 180.0
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(a)))


def way_coords(way: dict, nodes: Dict[int, dict]) -> List[Tuple[float, float]]:
    return [(nodes[n]["lat"], nodes[n]["lon"]) for n in way["nodes"] if n in nodes]


def way_length_km(way: dict, nodes: Dict[int, dict]) -> float:
    c = way_coords(way, nodes)
    return sum(_hav_km(c[i][0], c[i][1], c[i + 1][0], c[i + 1][1]) for i in range(len(c) - 1))


# ── 線の形を短く書く(Google の polyline 形式・小数 5 桁) ─────────────

def encode_polyline(coords: List[Tuple[float, float]]) -> str:
    out = []
    plat = plon = 0
    for lat, lon in coords:
        ilat, ilon = int(round(lat * 1e5)), int(round(lon * 1e5))
        for v in (ilat - plat, ilon - plon):
            v = ~(v << 1) if v < 0 else (v << 1)
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        plat, plon = ilat, ilon
    return "".join(out)


def decode_polyline(s: str) -> List[Tuple[float, float]]:
    coords, i, lat, lon = [], 0, 0, 0
    while i < len(s):
        vals = []
        for _ in range(2):
            shift = res = 0
            while True:
                b = ord(s[i]) - 63
                i += 1
                res |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            vals.append(~(res >> 1) if res & 1 else res >> 1)
        lat += vals[0]
        lon += vals[1]
        coords.append((lat / 1e5, lon / 1e5))
    return coords


def way_style(tags: dict) -> str:
    """描き分けの印。s=海底, u=地中, c=ケーブル(場所の記載なし), ''=架空。"""
    loc = str(tags.get("location") or "")
    if "underwater" in loc or "submarine" in loc or tags.get("submarine") == "yes":
        return "s"
    if "underground" in loc or str(tags.get("layer") or "").startswith("-"):
        return "u"
    if tags.get("power") == "cable":
        return "c"
    return ""


def edge_key(coords_lonlat: List[List[float]]) -> str:
    """地図の正典の線(docs/data/map/lines_*.geojson、座標 4 桁)を引く鍵。JS 側と同じ書き方にする。

    鍵 = 始点と終点の座標(×1e4 の整数)と頂点の数。docs/js/osm_routes.js の edgeKey() と一致させる。
    """
    a, b = coords_lonlat[0], coords_lonlat[-1]
    q = lambda x: str(int(round(x * 1e4)))
    return ",".join([q(a[0]), q(a[1]), q(b[0]), q(b[1]), str(len(coords_lonlat))])
