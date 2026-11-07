"""地図の線を OSM の実際の経路(鉄塔をたどる形)で描くための形の作り直し(2026-11-07)。

正典の枝(docs/data/built/all.json)の形(path)は OSM の線から作っているが、
  - OSM の線の切れ目を直線で飛んでいる所がある(1 km を超える直線が 1,676 本・4,340 km。うち 3,747 km)
  - 形を持たない枝(引込み・連系線など、593 km)は両端を直線で結んでいる
  - 地図用の書き出しで座標を小数 4 桁(約 11 m)に丸めていた
ため、地図の線が地形に合わず、鉄塔からずれていた(2026-11-07 オーナー「直線にならないように」)。

ここでは基底 OSM の線(data/{region}_lines.geojson。git に入っているので CI でも同じ結果になる)を網にし、
  1. 枝の形の頂点を、座標が一致する OSM の点(小数 5 桁で一致)に置き換える(小数 7 桁の OSM の座標になる)
  2. 隣り合う頂点が離れている所(既定 300 m 超)は、電圧の合う OSM の線をたどる最短の経路で埋める
     (遠回りしすぎる経路は採らない: 長さが直線の 1.6 倍 + 1 km まで)
  3. 形を持たない枝は、両端の近く(既定 800 m 以内)の OSM の点から 2 と同じように探す
  4. 見つからない区間は直線のまま残し、その区間の番号を返す(地図では破線で「経路未取得(直線は仮)」と描く)
推測で新しい線は作らない。たどるのは OSM に実在する線だけ。
"""
from __future__ import annotations

import heapq
import json
import math
import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

JUMP_M = 300.0          # これより離れた隣の頂点の間は、OSM の線をたどって埋める
SNAP_END_M = 800.0      # 枝の端(変電所の点)を、この距離以内の OSM の点に寄せる
SNAP_MID_M = 300.0      # 形の途中の頂点が OSM の点と一致しないとき、この距離以内なら寄せる
BRIDGE_M = 80.0         # OSM の線の端が別の線とこの距離以内で離れているだけなら、経路を探すときはつないでみる
# たどった経路の長さの上限 = 直線 × 倍率 + 足し。上から順に試す(電圧の合う線 → 少し遠回り → 電圧を問わない)
TRIES = ((1.6, 1000.0, True), (2.2, 3000.0, True), (1.6, 1000.0, False))
DETOUR_RATIO, DETOUR_ADD_M = TRIES[0][0], TRIES[0][1]

Key = Tuple[int, int]   # (lat×1e7, lon×1e7)


def _key(lat: float, lon: float) -> Key:
    return (int(round(lat * 1e7)), int(round(lon * 1e7)))


def dist_m(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """2 点(lat, lon)の距離(m)。"""
    p = math.pi / 180.0
    x = (math.sin((b[0] - a[0]) * p / 2) ** 2
         + math.cos(a[0] * p) * math.cos(b[0] * p) * math.sin((b[1] - a[1]) * p / 2) ** 2)
    return 2 * 6371000.0 * math.asin(min(1.0, math.sqrt(x)))


def kv_set(v) -> frozenset:
    return frozenset(round(float(x) / 1000.0, 1) for x in re.findall(r"\d+(?:\.\d+)?", str(v or "")) if float(x) >= 1000)


class OsmNet:
    """OSM の線の網。点は座標(小数 7 桁)、辺は way の隣り合う頂点。"""

    def __init__(self):
        self.way_of: Dict[Key, set] = {}
        self.n_ways = 0
        self.pos: Dict[Key, Tuple[float, float]] = {}
        self.adj: Dict[Key, List[Tuple[Key, float, frozenset]]] = {}
        self.by5: Dict[Tuple[float, float], List[Key]] = {}
        self.grid: Dict[Tuple[int, int], List[Key]] = {}

    def add_way(self, coords_lonlat: Sequence[Sequence[float]], kvs: frozenset):
        prev = None
        self.n_ways += 1
        wid = self.n_ways
        for c in coords_lonlat:
            lon, lat = float(c[0]), float(c[1])
            k = _key(lat, lon)
            self.way_of.setdefault(k, set()).add(wid)
            if k not in self.pos:
                self.pos[k] = (lat, lon)
                self.adj[k] = []
                self.by5.setdefault((round(lat, 5), round(lon, 5)), []).append(k)
                self.grid.setdefault((int(math.floor(lat * 100)), int(math.floor(lon * 100))), []).append(k)
            if prev is not None and prev != k:
                d = dist_m(self.pos[prev], self.pos[k])
                self.adj[prev].append((k, d, kvs))
                self.adj[k].append((prev, d, kvs))
            prev = k

    def add_bridges(self, max_m: float = BRIDGE_M) -> int:
        """OSM の線の端(つながる辺が 1 本の点)が、別の線の点と max_m 以内で離れているだけなら、つないでおく。

        OSM では、続いている線が点を共有せずに数十 m 離れて描かれていることが多い(つなぎ忘れ)。
        経路を探すときだけ使う短い橋で、描く形にはその数十 m の直線が入るだけ。
        """
        n = 0
        for k in sorted(self.pos):
            if len(self.adj[k]) != 1:
                continue
            lat, lon = self.pos[k]
            mine = self.way_of.get(k, set())
            kv = self.adj[k][0][2]
            j = self.nearest(lat, lon, max_m, lambda q: q != k and not (self.way_of.get(q, set()) & mine))
            if j is None:
                continue
            d = dist_m(self.pos[k], self.pos[j])
            self.adj[k].append((j, d, kv))
            self.adj[j].append((k, d, kv))
            n += 1
        return n

    def node_kvs(self, k: Key) -> frozenset:
        out = set()
        for _, _, kv in self.adj.get(k, ()):
            out |= kv
        return frozenset(out)

    def exact(self, lat: float, lon: float) -> Optional[Key]:
        ks = self.by5.get((round(lat, 5), round(lon, 5)))
        return min(ks) if ks else None

    def nearest(self, lat: float, lon: float, max_m: float, ok=None) -> Optional[Key]:
        r = int(math.ceil(max_m / 1000.0)) + 1      # 0.01° ≈ 1.1 km の格子
        ci, cj = int(math.floor(lat * 100)), int(math.floor(lon * 100))
        best, bd = None, max_m
        for i in range(ci - r, ci + r + 1):
            for j in range(cj - r, cj + r + 1):
                for k in self.grid.get((i, j), ()):
                    if ok and not ok(k):
                        continue
                    d = dist_m((lat, lon), self.pos[k])
                    if d < bd or (d == bd and best is not None and k < best):
                        best, bd = k, d
        return best

    def route(self, s: Key, t: Key, edge_ok, limit_m: float) -> Optional[List[Key]]:
        """s から t まで、edge_ok(kvs) を満たす辺だけで、長さ limit_m 以内の最短経路(A*)。"""
        if s == t:
            return [s]
        goal = self.pos[t]
        h0 = dist_m(self.pos[s], goal)
        if h0 > limit_m:
            return None
        g = {s: 0.0}
        prev: Dict[Key, Key] = {}
        heap = [(h0, 0.0, s)]
        done = set()
        while heap:
            f, gs, u = heapq.heappop(heap)
            if u in done:
                continue
            if u == t:
                path = [t]
                while path[-1] != s:
                    path.append(prev[path[-1]])
                return path[::-1]
            done.add(u)
            for v, d, kvs in self.adj[u]:
                if v in done or not edge_ok(kvs):
                    continue
                ng = gs + d
                if ng > limit_m:
                    continue
                if ng < g.get(v, math.inf):
                    g[v] = ng
                    prev[v] = u
                    nf = ng + dist_m(self.pos[v], goal)
                    if nf <= limit_m:
                        heapq.heappush(heap, (nf, ng, v))
        return None


def load_net(data_dir: str, regions: Sequence[str]) -> OsmNet:
    """基底 OSM の線(data/{region}_lines.geojson)から網を作る。手で足した線(supplement)は使わない。"""
    net = OsmNet()
    for reg in regions:
        p = os.path.join(data_dir, f"{reg}_lines.geojson")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
        for ft in d.get("features", []):
            pr = ft.get("properties") or {}
            if not pr.get("osm_id"):
                continue
            g = ft.get("geometry") or {}
            parts = [g.get("coordinates") or []] if g.get("type") == "LineString" else (g.get("coordinates") or [])
            kvs = kv_set(pr.get("voltage"))
            for part in parts:
                net.add_way(part, kvs)
    net.n_bridges = net.add_bridges()
    return net


def kv_ok_for(edge_kv: Optional[float]):
    """枝の電圧に合う OSM の線か。電圧の分からない枝(連系線など)は 154 kV 以上か電圧不明の線だけ。"""
    if edge_kv:
        return lambda kvs: (not kvs) or any(abs(x - edge_kv) < 0.6 for x in kvs)
    return lambda kvs: (not kvs) or any(x >= 154 for x in kvs)


def refine(points: Sequence[Tuple[float, float]], edge_kv: Optional[float], net: OsmNet, has_path: bool):
    """枝の形(lat, lon の並び)を OSM の経路で描き直す。

    返り値: (形 [(lat, lon)...], 直線のまま残った区間の始点の番号の並び, 数えた結果 dict)
    """
    edge_ok = kv_ok_for(edge_kv)
    node_ok = lambda k: edge_ok(net.node_kvs(k))
    # 1. 頂点を OSM の点に置き換える(一致 → 近く)。端は広めに寄せる
    ctrl: List[Tuple[Tuple[float, float], Optional[Key]]] = []
    n = len(points)
    for i, (lat, lon) in enumerate(points):
        k = net.exact(lat, lon)
        if k is None:
            r = SNAP_END_M if i in (0, n - 1) else SNAP_MID_M
            k = net.nearest(lat, lon, r, node_ok) or net.nearest(lat, lon, min(r, SNAP_MID_M))
        ctrl.append(((lat, lon), k))
    any_ok = lambda kvs: True
    out: List[Tuple[float, float]] = []
    straight: List[int] = []
    stats = {"jumps": 0, "routed": 0, "unrouted": 0}

    def push(pt):
        if not out or out[-1] != pt:
            out.append(pt)

    for i in range(n):
        (pt, k) = ctrl[i]
        here = net.pos[k] if k is not None else pt
        if i == 0:
            # 枝の端(変電所の点)から最初の OSM の点まで(敷地の中・寄せた距離だけ)をつなぐ
            push(pt)
            if k is not None and dist_m(pt, here) > 1:
                push(here)
            continue
        (ppt, pk) = ctrl[i - 1]
        prev_here = net.pos[pk] if pk is not None else ppt
        d = dist_m(prev_here, here)
        if d > JUMP_M:
            stats["jumps"] += 1
            path = None
            if pk is not None and k is not None:
                for ratio, add, by_kv in TRIES:
                    path = net.route(pk, k, edge_ok if by_kv else any_ok, d * ratio + add)
                    if path:
                        break
            if path:
                stats["routed"] += 1
                for q in path[1:]:
                    push(net.pos[q])
                continue
            stats["unrouted"] += 1
            straight.append(len(out) - 1)
        push(here)
        if i == n - 1 and k is not None and dist_m(pt, here) > 1:
            push(pt)
    return out, straight, stats
