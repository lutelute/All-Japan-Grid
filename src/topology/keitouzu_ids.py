"""open-keitouzu の対応表が指す AGJ のノード id を、今の正典の id に引き直す。

対応表 ``data/external/keitouzu/crosswalk.csv`` の ajg 行(657 件)は、AGJ v1.6.0
(2026-07-10)のノード id を指す(``target_version = ajg-v1.6.0``)。変電所のノード id
``{region}_sub_{i}`` の ``i`` は基底の変電所ファイルの中の順番なので、OSM を取り直すと
後ろの番号がずれる。2026-08-16 の取り直しのあと、v1.6.0 の id のうち今の正典にあるのは
227 件、そのうち同じ名前の変電所を指すのは 9 件だけだった(2026-10-24 に確認)。

そこで id では引かず、その版のノードの座標・kV・地域・名前(``data/reference/keitouzu_ajg_anchor_<版>.csv``、
``scripts/keitouzu/build_ajg_anchor.py`` が git のタグから書く)から、今の正典のノードを選ぶ。

1. ``NAME_RADIUS_M`` 以内に、その版と同じ名前のノードがあればそれ(取り直しで変電所の重心が
   300 m 以上動いたものがある: 到津 約 365 m・北相模 約 340 m。座標だけだと隣の別の施設を選ぶ)
2. 無ければ ``RADIUS_M`` 以内でいちばん近いノード

どちらも、選ぶ順は kV が同じ → 地域が同じ → 近い。地域を見るのは、地域の切り出しの重なりで
同じ座標に別の地域の双子が載るため(``src/topology/coords.py`` の注記)。

対応表そのもの(上流のデータ)は書き換えない。
"""
from __future__ import annotations

import csv
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "data" / "reference"
RADIUS_M = 300.0
NAME_RADIUS_M = 1000.0
_CELL = 0.01  # 度。RADIUS_M より十分大きい升目で近傍を引く


def anchor_path(version: str) -> Path:
    return REF / f"keitouzu_ajg_anchor_{version}.csv"


def load_anchor(version: str) -> dict[str, dict]:
    p = anchor_path(version)
    if not p.exists():
        return {}
    out = {}
    for r in csv.DictReader(p.open(encoding="utf-8")):
        out[r["target_id"]] = {"lat": float(r["lat"]), "lon": float(r["lon"]),
                               "kv": float(r["kv"]) if r["kv"] else None,
                               "region": r["region"], "name": r["name"]}
    return out


_NAME_DROP = re.compile(r"\s*\d+(\.\d+)?kV$|\s*\(untyped\)$")
_NAME_STRIP = re.compile(r"^\S*電力\s+|変電所|開閉所|変換所|\s")


def norm_name(s: str | None) -> str:
    """名前の比べ方: 末尾の kV・会社名・「変電所」などを落とす(「九州電力 到津変電所」=「到津変電所 66kV」)。"""
    return _NAME_STRIP.sub("", _NAME_DROP.sub("", s or ""))


def _dist_m(lat1, lon1, lat2, lon2) -> float:
    return math.hypot((lat2 - lat1) * 111_000.0,
                      (lon2 - lon1) * 111_000.0 * math.cos(math.radians(lat1)))


class IdRebaser:
    """版の決まった AGJ の id → 今の正典の id。``stats`` に引き方の内訳を数える。"""

    def __init__(self, nodes: list[dict], radius_m: float = RADIUS_M):
        self.radius_m = radius_m
        self.ids = {n["id"] for n in nodes}
        self._grid: dict[tuple[int, int], list[dict]] = defaultdict(list)
        for n in nodes:
            self._grid[(int(n["lat"] // _CELL), int(n["lon"] // _CELL))].append(n)
        self._anchors: dict[str, dict[str, dict]] = {}
        self.stats: Counter = Counter()

    def _anchor(self, version: str) -> dict[str, dict]:
        if version not in self._anchors:
            self._anchors[version] = load_anchor(version)
        return self._anchors[version]

    def _within(self, a: dict, radius_m: float):
        cy, cx = int(a["lat"] // _CELL), int(a["lon"] // _CELL)
        span = int(radius_m // (_CELL * 111_000.0 * 0.7)) + 1
        for dy in range(-span, span + 1):
            for dx in range(-span, span + 1):
                for n in self._grid.get((cy + dy, cx + dx), ()):
                    d = _dist_m(a["lat"], a["lon"], n["lat"], n["lon"])
                    if d <= radius_m:
                        yield d, n

    def nearest(self, a: dict) -> tuple[dict, float, str] | None:
        """(ノード, 距離 m, 引き方 "name" か "coord")。"""
        def rank(d, n):
            return (n.get("kv") != a["kv"], n.get("region") != a["region"], d, n["id"])
        want = norm_name(a["name"])
        if len(want) >= 2:
            named = [(d, n) for d, n in self._within(a, NAME_RADIUS_M) if norm_name(n.get("name")) == want]
            if named:
                d, n = min(named, key=lambda t: rank(*t))
                return n, d, "name"
        near = list(self._within(a, self.radius_m))
        if not near:
            return None
        d, n = min(near, key=lambda t: rank(*t))
        return n, d, "coord"

    def resolve(self, target_id: str, version: str) -> str | None:
        """今の正典の id。引けなければ None。版の座標が無い id は、id がそのまま今もあれば使う。"""
        a = self._anchor(version).get(target_id)
        if a is None:
            self.stats["no_anchor_same_id" if target_id in self.ids else "no_anchor_missing"] += 1
            return target_id if target_id in self.ids else None
        hit = self.nearest(a)
        if hit is None:
            self.stats["anchor_no_node_within_radius"] += 1
            return None
        n, _d, how = hit
        self.stats[f"by_{how}"] += 1
        self.stats["same_id" if n["id"] == target_id else "new_id"] += 1
        return n["id"]
