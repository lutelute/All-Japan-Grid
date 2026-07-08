"""県別実需要による需要空間配分の細分化 (2026-07-09).

背景(docs/reports/a_plan_east_ac_regression_2026-07-08.md):
  allocate_loads の「zone内一様×電圧階級重み」は、県をまたいで需要密度が大きく
  違う現実を表現できない。zone領土再属性(A案)で zone が正しくなると、この粗さが
  露呈して east 全規模ACが破綻した(需要空間配分が単独犯と7変種プローブで確定)。

本モジュールは出典付きの県別電力需要実績(電力調査統計 3-(2)、FY2024年度計)から
「zone内の県別需要シェア」を作る。zone合計のアンカーは従来どおり
regional_peak_demand_mw(config)であり、本重みは**zone内部の配り方**だけを変える。

開示済みの割り切り:
  - 年間電力量シェア→ピーク需要シェアの近似(県別の負荷率差は無視)
  - 県が複数zoneにまたがる場合(静岡=富士川split のみ、territory=True時)は、
    その県の需要を「zone別のsub(変電所)ノード数」で按分する(内部構造proxy・帳簿化)
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

DATA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "data", "reference", "pref_demand_fy2024.json")


@lru_cache(maxsize=1)
def load_pref_demand() -> dict:
    """出典付き県別需要JSON(data/reference/pref_demand_fy2024.json)を読む。"""
    with open(os.path.abspath(DATA_PATH), encoding="utf-8") as f:
        return json.load(f)


def pref_zone_gwh(nodes: List[dict]) -> Tuple[Dict[Tuple[str, str], float], dict]:
    """built全ノードから {(zone, pref): 需要GWh} と帳簿を作る。

    zone は **A案再属性後の実ラベル**(reattribute_node_regions を先に適用・冪等)。
    領土エリアでなく実ラベルで数える理由: 周波数ガードの飛び地(新信濃FC周辺の
    東京電力50Hz設備=長野県内で zone=tokyo のまま等)が (zone,pref) ペアとして
    実在するため。県が複数zoneにまたがる場合(静岡の富士川split・上記飛び地)は
    その県の需要を zone別 sub==1 ノード数で按分する(帳簿化)。

    Returns: (weights, ledger)
      weights: {(zone, pref): gwh}
      ledger:  {"source": …, "fy": …, "split_prefs": {pref: {zone: {"n_sub", "share", "gwh"}}}}
    """
    from src.powerflow.region_attribution import (
        prefecture_of, reattribute_node_regions)

    data = load_pref_demand()
    demand = {p: rec["total_gwh"] for p, rec in data["prefectures"].items()}

    reattribute_node_regions(nodes)   # in-place・冪等(buildと同一処理の先行適用)

    # 県×zone(再属性後ラベル)の sub ノード数(全国)
    counts: Dict[str, Dict[str, int]] = {}
    for n in nodes:
        if n.get("sub") != 1:
            continue
        pref = prefecture_of(float(n["lat"]), float(n["lon"]))
        area = n.get("region")
        if not pref or not area:
            continue
        counts.setdefault(pref, {}).setdefault(area, 0)
        counts[pref][area] += 1

    weights: Dict[Tuple[str, str], float] = {}
    split_ledger: Dict[str, dict] = {}
    for pref, by_zone in counts.items():
        gwh = demand.get(pref)
        if gwh is None:
            continue  # 想定外の県名(データ側に無い) — 開示のうえ従来重みに落ちる
        total_n = sum(by_zone.values())
        if len(by_zone) == 1:
            (zone,) = by_zone
            weights[(zone, pref)] = gwh
        else:
            split_ledger[pref] = {}
            for zone, n_sub in by_zone.items():
                share = n_sub / total_n
                weights[(zone, pref)] = gwh * share
                split_ledger[pref][zone] = {
                    "n_sub": n_sub, "share": round(share, 4),
                    "gwh": round(gwh * share, 1)}

    ledger = {"source": data["_meta"]["source_url"],
              "title": data["_meta"]["title"],
              "fy": data.get("fy"),
              "n_pref_weighted": len({p for (_z, p) in weights}),
              "split_prefs": split_ledger}
    return weights, ledger
