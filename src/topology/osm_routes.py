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
(docs/OBSERVED_VS_DERIVED.md)。入力は Overpass の JSON と同じ形の ``tw_*_t*.json``。
2026-11-07 から nas03 の ``osm_jp_power/20261105_agj_transmission/json/tw_japan_t0.json``
(Geofabrik の日本の抽出 2026-11-05 を scripts/osm_pbf_to_power_json.py で変換)を読む。取得データは Mac に
置かない決まりなので、Mac の ``data/osm_raw_towers/`` は読まない(場所は ``default_raw_dir``)。
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


# 鉄塔の生データ(Overpass の JSON と同じ形)の置き場所。取得データは Mac に置かず NAS に置く(オーナー 2026-11-07)
NAS_RAW_DIRS = (
    "/mnt/nas03/osm_jp_power/20261105_agj_transmission/json",       # pws-160core(nas03 の PWS_DB)
    "/Volumes/PWS_DB/osm_jp_power/20261105_agj_transmission/json",   # Mac で smb://pws-nas03.local/PWS_DB をつないだとき
)


def default_raw_dir() -> str:
    """環境変数 AJG_OSM_RAW_TOWERS(旧名 AGJ_OSM_RAW_TOWERS も読む)→ nas03 の 20261105 の抽出、の順。

    どれにも無ければ最初の NAS の場所を返す(読む側が「見つからない」と言って止まる)。
    Mac の data/osm_raw_towers/ には戻らない(6 月の Overpass の取得分で、NAS へ移す)。
    """
    for key in ("AJG_OSM_RAW_TOWERS", "AGJ_OSM_RAW_TOWERS"):
        v = os.environ.get(key)
        if v:
            return v
    for d in NAS_RAW_DIRS:
        if raw_files(d):
            return d
    return NAS_RAW_DIRS[0]


def missing_raw_message(raw_dir: str) -> str:
    return (f"鉄塔の生データ(tw_*_t*.json)が見つからない: {raw_dir}\n"
            "  nas03 の osm_jp_power/20261105_agj_transmission/json を読む。pws-160core なら /mnt/nas03 にある。"
            "Mac なら smb://pws-nas03.local/PWS_DB をつなぐか、--raw / 環境変数 AJG_OSM_RAW_TOWERS で場所を渡す")


def load_raw(raw_dir: str):
    """タイルに分けて取った Overpass の結果を重複なしにまとめる。

    返り値: (nodes: {id: element}, ways: {id: element}, info: {files, sha256, osm_base_min/max})
    タイルは地域の外接矩形を 3x3 に割ったもので重なりがあるので、同じ id は最初の 1 つだけ使う。
    """
    nodes: Dict[int, dict] = {}
    ways: Dict[int, dict] = {}
    rels: Dict[int, dict] = {}
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
            elif e["type"] == "relation" and (e.get("tags") or {}).get("route") == "power":
                rels.setdefault(e["id"], e)
    info = {
        "files": len(files),
        "sha256": h.hexdigest(),
        "osm_base_min": min(stamps) if stamps else None,
        "osm_base_max": max(stamps) if stamps else None,
        "relations": rels,
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


# ── 補完(2026-11-07 オーナー「鉄塔名などをちゃんと補完してほしい」「回線も省略されている可能性がある」) ──
# 推定で埋めたものは、必ず推定と分かる印を付けて出す(本物の番号・回線数に見せない)。

_REF_NUM = re.compile(r"^\s*(?:No\.?\s*|NO\.?\s*|no\.?\s*|#|＃)?\s*(\d{1,4})\s*(?:号|番)?\s*$")


def ref_number(ref) -> Optional[int]:
    """鉄塔の番号(ref)を整数にする。「55」「No. 71」「12号」は数、「376 / 320」「12A」などは None。"""
    m = _REF_NUM.match(str(ref or ""))
    return int(m.group(1)) if m else None


def chains(way_ids: Iterable[int], ways: Dict[int, dict]):
    """路線の way を、端点でつないで一筆書きの点の並びにする。

    返り値: (並びのリスト, 一筆書きか)。分かれ道・つながらない所がある路線は、way ごとの並びを返す(False)。
    """
    wids = sorted(way_ids)
    ends = collections.defaultdict(list)
    for w in wids:
        ns = ways[w]["nodes"]
        ends[ns[0]].append(w)
        ends[ns[-1]].append(w)
    per_way = [list(ways[w]["nodes"]) for w in wids]
    if not wids or any(len(v) > 2 for v in ends.values()):
        return per_way, False
    starts = sorted(n for n, v in ends.items() if len(v) == 1)
    cur = starts[0] if starts else ways[wids[0]]["nodes"][0]
    seq, used = [], set()
    while True:
        nxt = [w for w in ends[cur] if w not in used]
        if not nxt:
            break
        w = nxt[0]
        used.add(w)
        ns = ways[w]["nodes"]
        if ns[0] != cur:
            ns = ns[::-1]
        seq.extend(ns if not seq else ns[1:])
        cur = ns[-1]
    if len(used) != len(wids):
        return per_way, False
    return [seq], True


def infer_numbers(seq: List[int], is_tower, num_of) -> Dict[int, int]:
    """並び seq の上の鉄塔のうち番号の無いものに、前後の番号から番号を埋める。

    埋めるのは、前後の番号のある鉄塔の間の基数が、番号の差と合うときだけ(例: 12 と 15 の間に 2 基 → 13・14)。
    合わない所(番号が飛ぶ・建て替えで数が違う)は埋めない。
    """
    tw = []
    for n in seq:
        if is_tower(n) and (not tw or tw[-1] != n):
            tw.append(n)
    known = [(i, num_of(n)) for i, n in enumerate(tw) if num_of(n) is not None]
    out: Dict[int, int] = {}
    for (i1, n1), (i2, n2) in zip(known, known[1:]):
        gap = i2 - i1 - 1
        if gap <= 0 or abs(n2 - n1) - 1 != gap:
            continue
        step = 1 if n2 > n1 else -1
        for k in range(1, gap + 1):
            out[tw[i1 + k]] = n1 + step * k
    return out


def is_dc(tags: dict) -> bool:
    return str(tags.get("frequency") or "").strip() == "0" or "dc" in str(tags.get("current") or "").lower()


def circuits_estimate(tags: dict, n_relations: int = 0):
    """OSM に回線数(circuits)の無い線の回線数を推定する。返り値: (回線数, 根拠) か None。

    根拠: "cables" 交流で導体数が 3 の倍数 → 導体数 ÷ 3 / "cables_dc" 直流 → 導体数 ÷ 2 /
          "relations" この線を通る route=power の relation の数(1 つの relation が 1 回線)
    """
    if tags.get("circuits"):
        return None
    cab = str(tags.get("cables") or "").strip()
    if cab.isdigit():
        c = int(cab)
        if is_dc(tags):
            if c >= 2:
                return (c // 2, "cables_dc")
        elif c >= 3 and c % 3 == 0:
            return (c // 3, "cables")
    if n_relations >= 1:
        return (n_relations, "relations")
    return None
