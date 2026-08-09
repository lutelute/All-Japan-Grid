"""建造モデルの座標→ノード解決の正典実装。

**1つの座標には複数のノードが載る。** これが built の性質で、ここを取り違えると
静かに壊れる:

- 多層変電所は電圧層ごとにノードを持ち、**座標を完全に共有する**（1,655 箇所）
- 地域抽出の bbox が境界で重なるため、同じ設備が別 region 接頭辞で
  **二重に載る**（884 組。多くは距離 0m）

`coord2id[key] = node_id` のように座標→単一 ID で潰すと、後から来たノードが
先のノードを上書きし、辺の端点解決から静かに脱落する。2026-08-08 に
3 つのスクリプトで同じ事故を起こした:

- `scripts/keitouzu/crosscheck_keitouzu.py` — **610 変電所**が隣接グラフから消え、
  存在する接続を「断絶」と誤判定（整合率 83.5% → 修正後 88.1%）
- `scripts/gen_ybus_from_db.py` — 同一座標の辺（層間＝変圧器）が `ia == ib` で
  弾かれ、**2,180 本**が図から消えていた
- `scripts/toporag/vectorize_substations.py` — 孤立扱いのノードが 1,022 → 386 に

そこで解決はこのモジュールに一本化する。新しく built の幾何を触るコードは
自前で座標辞書を作らず、`CoordIndex` を使うこと。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Iterator, Sequence

PRECISION = 5          # 5桁 ≈ 1m。built の同一地点判定はこの粒度
KV_TOL = 0.5           # 電圧一致とみなす許容


def ckey(lat: float, lon: float, precision: int = PRECISION) -> tuple[float, float]:
    """座標キー。built 全体でこの丸めを共有する。"""
    return (round(lat, precision), round(lon, precision))


class CoordIndex:
    """座標 → その地点に載るノード**群**の索引。

    >>> nodes = [{"id": "a@154", "lat": 1.0, "lon": 2.0, "kv": 154.0},
    ...          {"id": "a@66",  "lat": 1.0, "lon": 2.0, "kv": 66.0}]
    >>> ix = CoordIndex(nodes)
    >>> ix.at(1.0, 2.0)                      # 同一地点の2層とも返る
    [0, 1]
    >>> ix.endpoints((1.0, 2.0), kv=154.0)   # 電圧が一致する層を優先
    [0]
    >>> list(ix.colocated_pairs())           # 層間リンク（変圧器）の候補
    [(0, 1)]
    """

    def __init__(self, nodes: Sequence[dict], precision: int = PRECISION):
        self.nodes = nodes
        self.precision = precision
        self._by_coord: dict[tuple[float, float], list[int]] = defaultdict(list)
        for i, n in enumerate(nodes):
            self._by_coord[ckey(n["lat"], n["lon"], precision)].append(i)

    # ── 参照 ────────────────────────────────────────────────
    def at(self, lat: float, lon: float) -> list[int]:
        """その座標に載る全ノードの索引。無ければ空リスト。"""
        return list(self._by_coord.get(ckey(lat, lon, self.precision), ()))

    def endpoints(self, pt: Iterable[float], kv: float | None = None) -> list[int]:
        """辺の端点を解決する。

        電圧が一致する層があればそれを返し、無ければその地点の全ノードを返す。
        線路は自分の電圧の層に着くべきで、全層に着けると過剰結線になる。
        """
        lat, lon = tuple(pt)[:2]
        cand = self._by_coord.get(ckey(lat, lon, self.precision))
        if not cand:
            return []
        if kv is not None:
            m = [i for i in cand
                 if self.nodes[i].get("kv") is not None
                 and abs(self.nodes[i]["kv"] - kv) < KV_TOL]
            if m:
                return m
        return list(cand)

    def colocated_pairs(self) -> Iterator[tuple[int, int]]:
        """同一地点に載るノードの全ペア。

        同じ物理サイトなので電気的に繋がっている——多層変電所なら層間の変圧器、
        重複コピーなら同一設備。隣接グラフを組むときはこれも辺として入れる。
        """
        for group in self._by_coord.values():
            for a in range(len(group)):
                for b in range(a + 1, len(group)):
                    yield group[a], group[b]

    # ── 診断 ────────────────────────────────────────────────
    @property
    def n_coords(self) -> int:
        return len(self._by_coord)

    def shared_coord_stats(self) -> dict:
        """1座標に複数ノードが載る度合い。移行時の回帰確認に使う。"""
        sizes = [len(v) for v in self._by_coord.values()]
        multi = [s for s in sizes if s > 1]
        return {
            "n_nodes": len(self.nodes),
            "n_coords": len(sizes),
            "n_shared_coords": len(multi),
            "n_nodes_on_shared": int(sum(multi)),
            "max_per_coord": max(sizes) if sizes else 0,
            # 座標→単一IDに潰した場合に消えるノード数（この実装が防いでいる分）
            "n_would_be_lost": int(sum(multi) - len(multi)),
        }
