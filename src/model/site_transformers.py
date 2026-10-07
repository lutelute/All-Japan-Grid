"""変電所の中で、どの電圧階級どうしを変圧器で結ぶか。

構造 DB(``scripts/build_substation_structure.py``)も潮流モデル(``run_full_powerflow_from_db``)も、
変電所にある電圧階級を高い順に隣どうしで結ぶ「梯子」を仮定してきた。OSM に巻線電圧つきの実機が
描かれている変電所では、梯子が段を飛ばす実機(275/77 kV の直結など)を見落とす
(docs/reports/station_node_breaker_adoption_2026-10-07.md §5)。

:func:`link_levels` は次の順で組を決める(介入 #48)。

1. OSM で観測した組のうち、両端がその変電所の階級にあるものを全部張る(``osm``)。
2. それでもつながらない階級を、梯子の順に、別の成分どうしをつなぐときだけ張る(``ladder``)。

観測が無い変電所は従来の梯子とまったく同じ。観測は「描かれていない変圧器が無い」ことは示さないので、
観測で覆えない階級は梯子で残す(どの階級も孤立させない)。

観測した組は ``data/stations/observed_transformer_pairs.json``(``scripts/compare_station_layers.py`` が
node-breaker 観測層から書き出す。追跡しているので PBF が無くても再現できる)。
"""

from __future__ import annotations

import json
import os
from collections import defaultdict

OBSERVED_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                             "data", "stations", "observed_transformer_pairs.json")


def kv_class(kv) -> int:
    """構造 DB と同じ kV の切り捨て整数(6.6 kV → 6)。観測と階級の照合に使う。"""
    return int(float(kv) + 1e-9)


def link_levels(levels, observed=()) -> list:
    """変電所の階級 ``levels`` を結ぶ組 ``[(hv, lv, source)]``(source = ``osm`` | ``ladder``)。

    Args:
        levels: 変電所の電圧階級(kV。順不同・重複可)。返す hv/lv はこの値そのもの。
        observed: 観測した組 ``(hv_kv, lv_kv)``(kV。切り捨て整数で ``levels`` と照合する)。
    """
    lv_sorted = sorted({float(v) for v in levels if v and float(v) > 0}, reverse=True)
    by_class = {}
    for v in lv_sorted:
        by_class.setdefault(kv_class(v), v)
    parent = {v: v for v in lv_sorted}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    out, seen = [], set()
    for hv, lv in sorted({(kv_class(h), kv_class(l)) for h, l in observed}, reverse=True):
        a, b = by_class.get(hv), by_class.get(lv)
        if a is None or b is None or a <= b or (a, b) in seen:
            continue
        seen.add((a, b))
        out.append((a, b, "osm"))
        parent[find(a)] = find(b)
    for a, b in zip(lv_sorted, lv_sorted[1:]):
        if find(a) != find(b):
            out.append((a, b, "ladder"))
            parent[find(a)] = find(b)
    return out


def load_observed(path: str = OBSERVED_PATH) -> list:
    """観測した組の一覧(ファイルが無ければ空)。"""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)["sites"]


def by_structure_site(path: str = OBSERVED_PATH) -> dict:
    """構造 DB の site_id → 観測した組 ``[(hv, lv), ...]``。"""
    out = {}
    for s in load_observed(path):
        pairs = [tuple(p[:2]) for p in s["pairs"]]
        for sid in s["structure_sites"]:
            out[sid] = pairs
    return out


def by_region_name(norm, path: str = OBSERVED_PATH) -> dict:
    """(region, 正規化した変電所名) → ``[(lat, lon, pairs), ...]``(潮流モデル側の照合用)。

    ``norm`` は名前の正規化関数(潮流側の ``_site_name_of_node`` と同じものを渡す)。
    """
    out = defaultdict(list)
    for s in load_observed(path):
        pairs = [tuple(p[:2]) for p in s["pairs"]]
        for region in s["regions"]:
            out[(region, norm(s["name"]))].append((s["lat"], s["lon"], pairs))
    return dict(out)
