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
import warnings
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
_ISLAND_OF = {"hokkaido": "hokkaido", "tohoku": "east", "tokyo": "east",
              "chubu": "west", "hokuriku": "west", "kansai": "west",
              "chugoku": "west", "shikoku": "west", "kyushu": "west",
              "okinawa": "okinawa"}

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


# 介入#42 (2026-09-02): 混在県個別化(B3)。
# #6/#38 のガードは混在県(長野・新潟・静岡)の周波数跨ぎ候補を**県単位で全部**
# 保持していた(ガード対象243ノード)。実際に守る必要があるのは
#   長野: 東信・大北・北信の一部=東京電力PG 50Hz 供給域(中部電力 50Hz 供給区域資料
#         + 国土数値情報 N03 市町村界)、新潟: 妙高・糸魚川の 60Hz 飛び地、
#   静岡: 富士川主流(国土数値情報 W05 河川)で東西を分ける
# だけで、それ以外の混在県ノードは領土(座標→県→エリア)で再属性してよい。
# 境界資産(全 feature 出典つき): data/reference/freq_boundary_mixed.geojson
# 越境幹線・FC 保護: data/reference/freq_corridor_whitelist.json
# 拒否の3段構え(全て開示・帳簿つき):
#   (A) 保護域ポリゴン内 / 富士川の東西判定と領土判定の不一致 → ガード維持
#   (B) ホワイトリスト: FC 名ノード・越境幹線エッジに接するノードは拒否
#   (C) 切断ガード(硬い保証): 仮適用で**新規の島跨ぎエッジ**が生じる限り、関与した
#       フリップを拒否して反復 — 収束時点で新規切断は構造的に 0
# 物理接続(OSM 由来)には不変更 — region ラベルのみの現実回復(#5/#38 の延長)。
# 無効化: reattribute_node_regions(mixed_pref=False) / apply_node_hygiene --no-mixed-pref /
#         docs/data/fragments/mixed_pref_ledger.json の逆再生 / all.json.pre_mixed.bak
MIXED_FREQ_PREFS = ("長野県", "新潟県", "静岡県")
MIXED_BOUNDARY_GEOJSON = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "data", "reference", "freq_boundary_mixed.geojson")
MIXED_CORRIDOR_WHITELIST = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "data", "reference", "freq_corridor_whitelist.json")
MIXED_PREF_MARK = "intervention42"

# 潮流ゲートで落ちたフリップの恒久拒否(2026-09-03)。
# #38 の正典化で近傍の島構成が変わり、この 2 ノードが構造ガード(新規島跨ぎ 0)を
# 通るようになった。しかし適用すると **west ピーク AC の slack/損失が +384MW 悪化**
# する(9,252→9,637MW・output/canonab の 3 状態 A/B で #38 単独は完全に不変と確認済み)。
# 構造ガードは「切れないこと」しか見ないので、潮流で落ちたものはここに明示的に残す。
# 解除するには west ピーク AC を取り直して悪化しないことを示すこと。
MIXED_PREF_PF_VETO = {
    "chubu_jct_35.1449:139.0341:77": "PFゲート不合格(2026-09-03): west slack +384MW",
    "chubu_jct_35.1097:138.9237:66": "PFゲート不合格(2026-09-03): west slack +384MW",
}
_MIXED_GUARD_ROUNDS = 20


@lru_cache(maxsize=1)
def _mixed_pref_assets():
    """(保護域prepared-geoms by pref, 富士川頂点(緯度順), 越境幹線pattern, FC pattern)."""
    from shapely.geometry import shape
    from shapely.prepared import prep

    with open(os.path.abspath(MIXED_BOUNDARY_GEOJSON), encoding="utf-8") as f:
        fc = json.load(f)
    prot: Dict[str, list] = {"長野県": [], "新潟県": []}
    river = None
    for feat in fc["features"]:
        props = feat["properties"]
        if str(props.get("role", "")).startswith("protected"):
            prot.setdefault(props["pref"], []).append(prep(shape(feat["geometry"])))
        elif props.get("role") == "boundary_river":
            river = shape(feat["geometry"])
    riv_pts: list = []
    if river is not None:
        for line in getattr(river, "geoms", [river]):
            riv_pts.extend(line.coords)
    riv_pts.sort(key=lambda xy: xy[1])          # 緯度順
    with open(os.path.abspath(MIXED_CORRIDOR_WHITELIST), encoding="utf-8") as f:
        wl = json.load(f)
    edge_pats = tuple(e["pattern"] for e in wl.get("edge_name_patterns", []))
    fc_pats = tuple(e["pattern"] for e in wl.get("fc_node_patterns", []))
    return prot, tuple(riv_pts), edge_pats, fc_pats


def fujikawa_lon_at(lat: float) -> float:
    """富士川主流(W05)の当該緯度における経度(最近傍頂点・範囲外は端点)。

    #5 の定数 FUJIKAWA_LON(138.62) は河口付近の近似。介入#42 は実河道で東西を判定する。
    """
    _prot, riv_pts, _e, _f = _mixed_pref_assets()
    if not riv_pts:
        return FUJIKAWA_LON
    lo, hi = riv_pts[0], riv_pts[-1]
    if lat <= lo[1]:
        return lo[0]
    if lat >= hi[1]:
        return hi[0]
    best = min(riv_pts, key=lambda xy: abs(xy[1] - lat))
    return best[0]


def shizuoka_side(lat: float, lon: float) -> str:
    """静岡県内座標の富士川実河道による東西判定 → 'tokyo'(東・50Hz) / 'chubu'(西・60Hz)。"""
    return "tokyo" if lon >= fujikawa_lon_at(lat) else "chubu"


def in_protected_zone(pref: str, lat: float, lon: float) -> bool:
    """長野/新潟の保護域(他周波数の飛び地・供給域)ポリゴン内か。"""
    from shapely.geometry import Point

    prot, _r, _e, _f = _mixed_pref_assets()
    pt = Point(lon, lat)
    return any(g.covers(pt) for g in prot.get(pref, []))


def _k5(lat, lon):
    return (round(float(lat), 5), round(float(lon), 5))


def plan_mixed_pref_flips(nodes: List[dict], edges: List[dict],
                          max_rounds: int = _MIXED_GUARD_ROUNDS) -> Dict:
    """混在県ノードの再属性計画をドライランで作る(nodes/edges は不変更)。

    Returns:
      guarded:  [(idx, pref, src_region, territory_area)]  #6 ガード対象(混在県の跨ぎ候補)
      plan:     {idx: to_region}                              最終フリップ
      veto_whitelist: {idx: why}   (B) FC 名 / 越境幹線に接する
      veto_crossing:  {idx: edge}  (C) 仮適用で新規の島跨ぎを生むため拒否
      kept:     {idx: reason}      (A) protected_zone / river_side_mismatch
      pre_cross_edges: int         既存の周波数跨ぎエッジ数(pre-existing・触らない)
      new_cross_edges: int         最終計画での新規跨ぎ(構造的に 0 が合格)
    """
    prot, _riv, edge_pats, fc_pats = _mixed_pref_assets()

    # 座標→ノード索引。同一座標の重複ノード(境界スライスの二重登録)は後勝ち —
    # 監査(2026-09-02)と同じ規約。重複座標の島判定は connectivity.py の島別キー集合が正で、
    # ここでは「ラベル変更が新規の跨ぎを生まないか」の保守的判定にのみ使う
    by_xy: Dict[tuple, int] = {}
    for i, n in enumerate(nodes):
        by_xy[_k5(n["lat"], n["lon"])] = i
    inc: Dict[int, List[int]] = {}
    ends: List[Optional[tuple]] = []
    for j, e in enumerate(edges):
        a, b = e.get("a"), e.get("b")
        if not a or not b:
            ends.append(None)
            continue
        ia, ib = by_xy.get(_k5(*a)), by_xy.get(_k5(*b))
        ends.append((ia, ib))
        for i in (ia, ib):
            if i is not None:
                inc.setdefault(i, []).append(j)

    guarded, plan, kept = [], {}, {}
    for i, n in enumerate(nodes):
        src = n.get("region")
        lat, lon = float(n["lat"]), float(n["lon"])
        area = area_of_coord(lat, lon)
        if not area or area == src:
            continue
        if not (src in AREA_FREQ and AREA_FREQ.get(area) is not None
                and AREA_FREQ[src] != AREA_FREQ[area]):
            continue
        pref = prefecture_of(lat, lon)
        if UNIFORM_FREQ_PREFS.get(pref) == AREA_FREQ[area]:
            continue                            # 介入#38 の群(一意周波数県)
        if pref not in MIXED_FREQ_PREFS:
            continue                            # 想定外(県ポリゴン外など)は触らない
        guarded.append((i, pref, src, area))
        if pref in ("長野県", "新潟県"):
            if in_protected_zone(pref, lat, lon):
                kept[i] = "protected_zone"
                continue
            plan[i] = area
        else:                                   # 静岡県: 富士川実河道
            want = shizuoka_side(lat, lon)
            if want == area and want != src:
                plan[i] = want
            else:
                kept[i] = "river_side_mismatch"

    # (B) ホワイトリスト
    veto_wl: Dict[int, str] = {}
    for i in list(plan):
        nm = nodes[i].get("name") or ""
        if any(p in nm for p in fc_pats):
            veto_wl[i] = f"FC固定: {nm[:20]}"
            del plan[i]
            continue
        for j in inc.get(i, []):
            en = edges[j].get("name") or ""
            if any(p in en for p in edge_pats):
                veto_wl[i] = f"越境幹線: {en[:26]}"
                del plan[i]
                break

    # (C) 島跨ぎ切断ガード(反復)
    def freq_of(region):
        return AREA_FREQ.get(region)

    pre_cross = set()
    for j, pair in enumerate(ends):
        if not pair or pair[0] is None or pair[1] is None:
            continue
        fa, fb = freq_of(nodes[pair[0]]["region"]), freq_of(nodes[pair[1]]["region"])
        if fa and fb and fa != fb:
            pre_cross.add(j)

    def new_cross_edges(eff):
        out = []
        for j, pair in enumerate(ends):
            if j in pre_cross or not pair or pair[0] is None or pair[1] is None:
                continue
            ia, ib = pair
            fa = freq_of(eff.get(ia, nodes[ia]["region"]))
            fb = freq_of(eff.get(ib, nodes[ib]["region"]))
            if fa and fb and fa != fb:
                out.append((j, ia, ib))
        return out

    veto_cross: Dict[int, str] = {}
    for _round in range(max_rounds):
        nc = new_cross_edges(plan)
        if not nc:
            break
        for j, ia, ib in nc:
            for i in (ia, ib):
                if i in plan:
                    veto_cross[i] = (edges[j].get("name") or "")[:30]
                    del plan[i]
    residual = len(new_cross_edges(plan))       # 検収(収束していれば 0)
    # (D) 潮流ゲートで落ちたフリップの恒久拒否(2026-09-03・MIXED_PREF_PF_VETO)。
    # 構造ガード(C)は「島が切れないこと」しか見ない。実際に west ピーク AC を
    # 悪化させたものはここで落とし、理由を veto_pf に残す。
    veto_pf: Dict[int, str] = {}
    for i in list(plan):
        why = MIXED_PREF_PF_VETO.get(str(nodes[i].get("id")))
        if why:
            veto_pf[i] = why
            del plan[i]

    return {"guarded": guarded, "plan": plan, "veto_whitelist": veto_wl,
            "veto_crossing": veto_cross, "veto_pf": veto_pf, "kept": kept,
            "pre_cross_edges": len(pre_cross), "new_cross_edges": residual}


def apply_mixed_pref_flips(nodes: List[dict], edges: List[dict]) -> Dict:
    """計画を立てて適用(in-place・冪等)。新規跨ぎが残る計画は**適用しない**。

    Returns: {"fixed": {"from->to": n}, "vetoed": {reason: n}, "applied": bool,
              "plan": <plan_mixed_pref_flips の戻り値>, "flips": [ {id,name,pref,from,to,lat,lon} ]}
    """
    mp = plan_mixed_pref_flips(nodes, edges)
    fixed: Dict[str, int] = {}
    flips = []
    vetoed = {"whitelist": len(mp["veto_whitelist"]),
              "crossing_guard": len(mp["veto_crossing"]),
              "pf_gate": len(mp.get("veto_pf", {}))}
    for r in mp["kept"].values():
        vetoed[r] = vetoed.get(r, 0) + 1
    applied = mp["new_cross_edges"] == 0
    if applied:
        for i, to in sorted(mp["plan"].items()):
            n = nodes[i]
            src = n.get("region")
            key = f"{src}->{to}"
            fixed[key] = fixed.get(key, 0) + 1
            if "region_src" not in n:
                n["region_src"] = src
            flips.append({"id": n.get("id"), "name": n.get("name"), "sub": n.get("sub"),
                          "pref": prefecture_of(float(n["lat"]), float(n["lon"])),
                          "from": src, "to": to, "lat": n["lat"], "lon": n["lon"]})
            n["region"] = to
            n["mixed_pref"] = MIXED_PREF_MARK
    return {"fixed": dict(sorted(fixed.items(), key=lambda kv: -kv[1])),
            "vetoed": vetoed, "applied": applied, "plan": mp, "flips": flips}


# ── 介入#38 の正典化(2026-09-03) ────────────────────────────────────────
# #38(周波数跨ぎ再属性の精緻化)は **潮流を組むときだけ** 効いていて、正典
# docs/data/built/all.json のラベルは古いままだった(実測 253 ノード: 群馬 132・
# 山梨 56・神奈川 33・埼玉 27・愛知 3・栃木 1・東京 1)。地図・エディタ・輸出は
# 正典を直接読むので、群馬の設備が「中部」と着色される等の実害が残っていた。
# #42(混在県)と同じく、**正典に焼く**のがここ。混在県は #42 の担当なので触らない。
UNIFORM_FREQ_MARK = "intervention38"


def plan_uniform_freq_flips(nodes: List[dict], edges: List[dict]) -> Dict:
    """一意周波数県の跨ぎ再属性を正典へ焼く計画(nodes/edges は不変更)。

    対象は「座標の県の周波数が一意(UNIFORM_FREQ_PREFS)で、領土エリアの周波数と
    一致する」ノードだけ — 混在県(長野・新潟・静岡)は #42 の担当で触らない。
    #42 と同じ切断ガードの考え方で、**島跨ぎエッジが増えないこと**を検算する
    (実測では 103 → 64 と減る: 幻の跨ぎが消えるため)。

    Returns: {plan: {idx: to_region}, by_dir: {"from->to": n},
              cross_edges_before: int, cross_edges_after: int}
    """
    plan: Dict[int, str] = {}
    by_dir: Dict[str, int] = {}
    for i, n in enumerate(nodes):
        src = n.get("region")
        if src not in AREA_FREQ:
            continue
        lat, lon = float(n["lat"]), float(n["lon"])
        area = area_of_coord(lat, lon)
        if not area or area == src or AREA_FREQ.get(area) is None:
            continue
        if AREA_FREQ[src] == AREA_FREQ[area]:
            continue                     # 同一周波数の territory 補正は #5 の担当
        if UNIFORM_FREQ_PREFS.get(prefecture_of(lat, lon)) != AREA_FREQ[area]:
            continue                     # 混在県 → #42 / ガード維持
        plan[i] = area
        key = f"{src}->{area}"
        by_dir[key] = by_dir.get(key, 0) + 1

    def _cross(overrides: Dict[int, str]) -> int:
        idx = {}
        for j, m in enumerate(nodes):
            reg = overrides.get(j, m.get("region"))
            idx[(round(float(m["lat"]), 5), round(float(m["lon"]), 5))] = \
                _ISLAND_OF.get(reg)
        c = 0
        for e in edges:
            ia = idx.get((round(e["a"][0], 5), round(e["a"][1], 5)))
            ib = idx.get((round(e["b"][0], 5), round(e["b"][1], 5)))
            if ia and ib and ia != ib:
                c += 1
        return c

    return {"plan": plan,
            "by_dir": dict(sorted(by_dir.items(), key=lambda kv: -kv[1])),
            "cross_edges_before": _cross({}),
            "cross_edges_after": _cross(plan)}


def apply_uniform_freq_flips(nodes: List[dict], edges: List[dict]) -> Dict:
    """計画を適用(in-place・冪等)。**島跨ぎエッジが増える計画は適用しない**。"""
    up = plan_uniform_freq_flips(nodes, edges)
    applied = up["cross_edges_after"] <= up["cross_edges_before"]
    flips = []
    if applied:
        for i, area in up["plan"].items():
            n = nodes[i]
            if "region_src" not in n:
                n["region_src"] = n.get("region")
            flips.append({"id": n.get("id"), "name": n.get("name"),
                          "pref": prefecture_of(float(n["lat"]), float(n["lon"])),
                          "from": n.get("region"), "to": area,
                          "lat": n["lat"], "lon": n["lon"]})
            n["region"] = area
            n["freq_fix"] = UNIFORM_FREQ_MARK
    return {"applied": applied, "plan": up, "flips": flips}


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


def reattribute_node_regions(nodes: List[dict], freq_fix: bool = True,
                             mixed_pref: bool = False,
                             edges: Optional[List[dict]] = None) -> Dict:
    """ノード列の region を領土ベースで再割当する(in-place)。

    - 元のラベルは region_src に退避(初回のみ・監査用)
    - **周波数を跨ぐ移動は原則スキップ**(AREA_FREQ参照 — 50/60Hz境界の県近似は
      実態と乖離するため。skipped_freq に計上して開示)
    - freq_fix=True(既定・介入#38 2026-08-30): 座標の県の周波数が一意
      (UNIFORM_FREQ_PREFS)で是正先エリアの周波数と一致する場合に限り、
      跨ぎ再属性を実行する(freq_fixed に計上して開示)。False=旧挙動(回帰比較用)
    - mixed_pref=True(介入#42 2026-09-02・既定OFF=正典側で適用済みのため): 混在県
      (長野・新潟・静岡)の跨ぎ候補を境界資産+ホワイトリスト+切断ガードで再属性する。
      **edges が無いと切断ガード(C)を実行できないので無効化して警告する**
      (黙ってガード無しで適用しない)。mixed_pref_fixed / mixed_pref_vetoed で開示
    - Returns: {"n_nodes", "n_changed", "changes": {"from->to": count},
                "skipped_freq": {...}, "freq_fixed": {...},
                "mixed_pref_fixed": {...}, "mixed_pref_vetoed": {reason: n},
                "mixed_pref_note": str|None}
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

    # 介入#42: 混在県個別化(#6 ガードで skipped に残った群の一部を境界資産で是正)
    mp_fixed: Dict[str, int] = {}
    mp_vetoed: Dict[str, int] = {}
    mp_note: Optional[str] = None
    if mixed_pref:
        if edges is None:
            mp_note = ("disabled: edges=None — 切断ガード(C)を実行できないため"
                       "混在県個別化を無効化した(ガード無しでは適用しない)")
            warnings.warn("reattribute_node_regions(mixed_pref=True) には edges が必要。"
                          "切断ガードを実行できないので混在県個別化を無効化した",
                          RuntimeWarning, stacklevel=2)
        else:
            res = apply_mixed_pref_flips(nodes, edges)
            mp_fixed, mp_vetoed = res["fixed"], res["vetoed"]
            if not res["applied"]:
                mp_note = (f"not applied: 切断ガードが収束せず新規跨ぎ "
                           f"{res['plan']['new_cross_edges']} 本が残った")
            for key, cnt in mp_fixed.items():
                changes[key] = changes.get(key, 0) + cnt
                skipped[key] = max(skipped.get(key, 0) - cnt, 0)
                n_changed += cnt
            skipped = {k: v for k, v in skipped.items() if v}
    return {"n_nodes": len(nodes), "n_changed": n_changed,
            "changes": dict(sorted(changes.items(), key=lambda kv: -kv[1])),
            "skipped_freq": dict(sorted(skipped.items(),
                                        key=lambda kv: -kv[1])),
            "freq_fixed": dict(sorted(fixed.items(),
                                      key=lambda kv: -kv[1])),
            "mixed_pref_fixed": mp_fixed,
            "mixed_pref_vetoed": mp_vetoed,
            "mixed_pref_note": mp_note}
