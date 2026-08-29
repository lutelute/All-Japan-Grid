"""領土ベースのzone再属性 — bbox重なり汚染の修正(A案, 2026-07-07採用).

背景(docs/reports/phantom_tie_zone_contamination_2026-07-07.md):
  builtノードの region は「どの地域bbox抽出ファイル由来か」であり、bboxの
  重なり帯(山口・徳島・岐阜・三重・青函ほか)では領土と食い違う。その結果、
  幻tie(kyushu↔shikoku)・実tie不可視化(本四)・需要の地理誤配置・UC注入の
  zone誤帰属が起きていた。

本モジュールは **物理接続(OSM由来)には一切触れず**、ノードの region 属性のみを
「座標→都道府県→一般送配電エリア」で再割当する(=現実の回復)。

県→エリア対応(供給区域の県ベース近似):
  - 静岡県のみ富士川で東西分割(lon >= 138.62 → tokyo / それ以外 chubu)
  - 未処理の細部(開示): 三重県熊野地方の一部=関西、岐阜県飛騨の一部(神岡等)=北陸、
    兵庫県赤穂の一部=中国、新潟県妙高の一部=中部。いずれも県単位の主エリアに寄せる

県ポリゴン: data/reference/japan_prefectures_simplified.geojson
  (国土地理院 Global Map Japan v2 由来 dataofjapan/land を簡略化・出典はファイル内_meta)
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

PREF_GEOJSON = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "data", "reference", "japan_prefectures_simplified.geojson")

# 県 → 一般送配電エリア(静岡は富士川splitで別処理)
PREF_AREA = {
    "北海道": "hokkaido",
    "青森県": "tohoku", "岩手県": "tohoku", "宮城県": "tohoku",
    "秋田県": "tohoku", "山形県": "tohoku", "福島県": "tohoku",
    "新潟県": "tohoku",
    "茨城県": "tokyo", "栃木県": "tokyo", "群馬県": "tokyo",
    "埼玉県": "tokyo", "千葉県": "tokyo", "東京都": "tokyo",
    "神奈川県": "tokyo", "山梨県": "tokyo",
    "愛知県": "chubu", "岐阜県": "chubu", "三重県": "chubu", "長野県": "chubu",
    "富山県": "hokuriku", "石川県": "hokuriku", "福井県": "hokuriku",
    "滋賀県": "kansai", "京都府": "kansai", "大阪府": "kansai",
    "兵庫県": "kansai", "奈良県": "kansai", "和歌山県": "kansai",
    "鳥取県": "chugoku", "島根県": "chugoku", "岡山県": "chugoku",
    "広島県": "chugoku", "山口県": "chugoku",
    "徳島県": "shikoku", "香川県": "shikoku", "愛媛県": "shikoku",
    "高知県": "shikoku",
    "福岡県": "kyushu", "佐賀県": "kyushu", "長崎県": "kyushu",
    "熊本県": "kyushu", "大分県": "kyushu", "宮崎県": "kyushu",
    "鹿児島県": "kyushu",
    "沖縄県": "okinawa",
}

FUJIKAWA_LON = 138.62   # 静岡の周波数境界(富士川)の経度近似

# エリア→(同期島, 周波数)。**周波数を跨ぐ再属性は禁止**するためのガード。
# 理由: 供給区域の県近似は50/60Hz境界で実態と乖離する — 新信濃変換所(東京電力
# 50Hz・長野県)や佐久・軽井沢(東京電力エリア in 長野県)を「長野→chubu」で
# west島に移すと、eastの実在50Hz幹線(安曇幹線等)が切れて新たな破壊になる。
# 同一周波数内の誤属性(山口・徳島・岐阜・青函等)だけを直し、周波数境界の
# 帰属は抽出元ラベル(=OSMトレースの連続性)を保持する。
AREA_FREQ = {"hokkaido": 50, "tohoku": 50, "tokyo": 50,
             "chubu": 60, "hokuriku": 60, "kansai": 60,
             "chugoku": 60, "shikoku": 60, "kyushu": 60, "okinawa": 60}

# 介入#38 (2026-08-30): 周波数跨ぎガードの精緻化。
# 上のガードの動機は「混在県(長野・新潟・静岡)の飛び地・越境幹線の保護」で
# あって、周波数が県内で一意な県への抽出こぼれ(例: 群馬・埼玉座標なのに
# region=chubu)まで保護するのは過剰だった — westのAC発散の一因として恒久
# 残留していた(docs/reports/west_ac_onset_full_2026-08-30.json、
# 神保原/嬬恋の関東設備がwest島に混入)。座標の県の周波数が一意で、是正先
# エリアの周波数がそれと一致する場合に限り、跨ぎ再属性を許可する。
# 混在県は従来どおりガード(長野=東信の一部50Hz、新潟=60Hz飛び地、静岡=富士川)。
UNIFORM_FREQ_PREFS = {
    "北海道": 50, "青森県": 50, "岩手県": 50, "宮城県": 50, "秋田県": 50,
    "山形県": 50, "福島県": 50,
    "茨城県": 50, "栃木県": 50, "群馬県": 50, "埼玉県": 50, "千葉県": 50,
    "東京都": 50, "神奈川県": 50, "山梨県": 50,
    "愛知県": 60, "岐阜県": 60, "三重県": 60,
    "富山県": 60, "石川県": 60, "福井県": 60,
    "滋賀県": 60, "京都府": 60, "大阪府": 60, "兵庫県": 60, "奈良県": 60,
    "和歌山県": 60,
    "鳥取県": 60, "島根県": 60, "岡山県": 60, "広島県": 60, "山口県": 60,
    "徳島県": 60, "香川県": 60, "愛媛県": 60, "高知県": 60,
    "福岡県": 60, "佐賀県": 60, "長崎県": 60, "熊本県": 60, "大分県": 60,
    "宮崎県": 60, "鹿児島県": 60, "沖縄県": 60,
}


@lru_cache(maxsize=1)
def _pref_index():
    """(STRtree, geoms, names) を遅延構築する。"""
    from shapely.geometry import shape
    from shapely.strtree import STRtree

    with open(os.path.abspath(PREF_GEOJSON), encoding="utf-8") as f:
        d = json.load(f)
    geoms, names = [], []
    for feat in d["features"]:
        geoms.append(shape(feat["geometry"]))
        names.append(feat["properties"]["pref_ja"])
    return STRtree(geoms), geoms, names


def prefecture_of(lat: float, lon: float) -> Optional[str]:
    """座標の都道府県名。ポリゴン外(沖合・簡略化誤差)は最近傍県へフォールバック。"""
    from shapely.geometry import Point

    tree, geoms, names = _pref_index()
    p = Point(lon, lat)
    for i in tree.query(p, predicate="covers"):
        return names[int(i)]
    # 沖合・海峡上・簡略化で欠けた縁 → 最近傍県(全国どこでも高々数kmの想定)
    best, best_d = None, float("inf")
    for i in tree.query(p.buffer(0.5)):   # ~50km探索窓
        d = geoms[int(i)].distance(p)
        if d < best_d:
            best, best_d = names[int(i)], d
    if best is None:                       # 完全に離れた点(想定外) — 全件走査
        for g, nm in zip(geoms, names):
            d = g.distance(p)
            if d < best_d:
                best, best_d = nm, d
    return best


def area_of_coord(lat: float, lon: float) -> Optional[str]:
    """座標の一般送配電エリア(hokkaido..okinawa)。"""
    pref = prefecture_of(lat, lon)
    if pref is None:
        return None
    if pref == "静岡県":
        return "tokyo" if lon >= FUJIKAWA_LON else "chubu"
    return PREF_AREA.get(pref)


def reattribute_node_regions(nodes: List[dict], freq_fix: bool = True) -> Dict:
    """ノード列の region を領土ベースで再割当する(in-place)。

    - 元のラベルは region_src に退避(初回のみ・監査用)
    - **周波数を跨ぐ移動は原則スキップ**(AREA_FREQ参照 — 50/60Hz境界の県近似は
      実態と乖離するため。skipped_freq に計上して開示)
    - freq_fix=True(既定・介入#38 2026-08-30): 座標の県の周波数が一意
      (UNIFORM_FREQ_PREFS)で是正先エリアの周波数と一致する場合に限り、
      跨ぎ再属性を実行する(freq_fixed に計上して開示)。False=旧挙動(回帰比較用)
    - Returns: {"n_nodes", "n_changed", "changes": {"from->to": count},
                "skipped_freq": {...}, "freq_fixed": {...}}
    """
    n_changed = 0
    changes: Dict[str, int] = {}
    skipped: Dict[str, int] = {}
    fixed: Dict[str, int] = {}
    for n in nodes:
        src = n.get("region")
        if "region_src" not in n:
            n["region_src"] = src
        area = area_of_coord(float(n["lat"]), float(n["lon"]))
        if not area or area == src:
            continue
        key = f"{src}->{area}"
        if (src in AREA_FREQ and AREA_FREQ.get(area) is not None
                and AREA_FREQ[src] != AREA_FREQ[area]):
            pref = prefecture_of(float(n["lat"]), float(n["lon"]))
            if not (freq_fix and
                    UNIFORM_FREQ_PREFS.get(pref) == AREA_FREQ[area]):
                skipped[key] = skipped.get(key, 0) + 1
                continue
            fixed[key] = fixed.get(key, 0) + 1   # 介入#38: 一意周波数県は是正
        changes[key] = changes.get(key, 0) + 1
        n["region"] = area
        n_changed += 1
    return {"n_nodes": len(nodes), "n_changed": n_changed,
            "changes": dict(sorted(changes.items(), key=lambda kv: -kv[1])),
            "skipped_freq": dict(sorted(skipped.items(),
                                        key=lambda kv: -kv[1])),
            "freq_fixed": dict(sorted(fixed.items(),
                                      key=lambda kv: -kv[1]))}
