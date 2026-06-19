#!/usr/bin/env python3
"""系統図/エリアタブの地図タイルを **DB更新済み建造モデル** から再生成する (idempotent)。

    PYTHONPATH=. python scripts/export_map_tiers_from_built.py

背景 (なぜ作るか)
-----------------
`docs/js/grid_map.js` が描く線/変電所レイヤは
`docs/data/lines_{tier}.geojson` / `docs/data/subs_{tier}.geojson` を fetch する。
これらは 2026-04-23 の古いOSM生抽出由来で、正典(DB更新済み建造モデル)を反映して
いなかった (例: 東京の変電所が 1726 件 ← 建造モデルは 4215 ノード/2232 変電所)。
Ybus が最近傍近似でDB非反映だったのと同型の欠陥。本スクリプトは唯一の正典である
`docs/data/built/all.json`(2026-06-17, ノードに region 付き)から tier geojson を
機械的に再生成し、stale を解消する。

入力 (読み取り専用)
-------------------
docs/data/built/all.json  : {nodes:[{id,lat,lon,kv,main,deg,sub,name,region}],
                             edges:[{a:[lat,lon],b:[lat,lon],kv,par,path:[[lat,lon]...]}]}
                             sub=1 が変電所 / sub=0 が接続点(junction)。
                             ※ built の座標は [lat, lon] 順。GeoJSON は [lon, lat] 順。
docs/data/regions.json    : 既存の region メタ(list)。frequency_hz を保持する。
docs/data/substations.geojson : 変電所の **キュレーション属性**(operator/category_ja/
                             voltage_source 等)の供給元(旧基底OSM由来の C層相当)。built は
                             幾何+表示名4フィールドのみなので、ここから属性を結合して焼き込む。

出力 (上書き)
-------------
docs/data/subs_275kv.geojson   docs/data/lines_275kv.geojson
docs/data/subs_154kv.geojson   docs/data/lines_154kv.geojson
docs/data/subs_all.geojson     docs/data/lines_all.geojson
docs/data/regions.json         (substations/lines 件数 + bbox を built から再計算、
                                frequency_hz/name_* は既存値を保持)

フィールド契約 (grid_map.js を精読して確定)
-------------------------------------------
- tier ファイル命名: subs_{suffix}.geojson / lines_{suffix}.geojson、suffix∈{275kv,154kv,all}。
  grid_map.js voltageTier(minKv): 500↑→275kv(clientFilter500) / 275↑→275kv / 154↑→154kv /
  それ未満→all(clientFilter 110/66/0)。すなわち suffix ファイルは「閾値以上を全部含む」帯。
    275kv = kv>=275 を全部 / 154kv = kv>=154 を全部 / all = 全件(kv<154 と null/不明 も含む)。
- feature プロパティ (lines/subs 共通、これだけ読まれる):
    _region      : 英語 region (filterByRegion / REGION_COLORS のキー)
    _region_ja   : 日本語 region (ポップアップ/ツールチップ/リスト表示)
    _display_name: 表示名 (subs=node.name / lines=建造edgeに名前が無いので "")
    _voltage_kv  : 電圧(数値 or null)。filterByVoltage / voltageColor / voltageKvToBracket。
  geometry: subs=Point(変電所のみ) / lines=LineString。座標は [lon, lat]。
- subs の追加属性(属性結合・grid_map.js buildSubPopup が読む): name/operator/operator_en/
  region_ja/voltage_kv/voltage_source/voltage_label/frequency_hz/rating/category_ja/
  substation_type/gas_insulated/ref/addr_city/website。値があるキーのみ焼く。
  `_attr_source`∈{coord,name}=属性の突合方法(出所明示)。属性が引けないノードは _attr_source 無し
  (旧 substations.geojson に存在しない=供給元不在。捏造で埋めない)。これにより grid_map.js の
  別fetch(substations.geojson)+4桁座標突合(当たり≈8%)を、export時の名前優先+座標(≈56%)へ一元化。
- 異常/欠損電圧: grid_map.js は kv<=0 や kv>1100 を「不明」とし高電圧ビューから除外する。
  建造モデルの不明電圧は kv==0.0。本スクリプトは捏造防止のため _voltage_kv=null とし、
  偽の 500kV を作らない。null/不明は 'all' タイルにのみ載る(帯閾値を満たさないため)。

base extract(data/ 直下のOSM生抽出)・okinawa補完(data/okinawa_*)・
generators.geojson は触らない。
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILT_ALL = os.path.join(ROOT, "docs", "data", "built", "all.json")
DATA_DIR = os.path.join(ROOT, "docs", "data")
REGIONS_JSON = os.path.join(DATA_DIR, "regions.json")

# 座標精度: 既存タイル / slim_geojson.py に合わせ 4 桁 (≈11m、可視化に十分)。
COORD_PRECISION = 4

# 日本に実在する最高電圧は 500kV。これを超える値は OSM 多値タグの連結パースミス。
# grid_map.js KV_MAX_REAL と一致させ、捏造防止のため不明(null)化する。
KV_MAX_REAL = 1100.0

# 属性結合の供給元(C層相当=旧 substations.geojson)と、grid_map.js buildSubPopup が読むキー集合。
SUBS_ENRICH = os.path.join(DATA_DIR, "substations.geojson")
POPUP_FIELDS = [
    "name", "operator", "operator_en", "region_ja", "voltage_kv", "voltage_source",
    "voltage_label", "frequency_hz", "rating", "category_ja", "substation_type",
    "gas_insulated", "ref", "addr_city", "website",
]
# 名前一致で属性を結合する際、座標がこの距離(km)を超えたら別物として捨てる(誤接続防止)。
ATTR_NAME_MAX_KM = 2.0

# region 英 → 日 (grid_map.js REGION_NAMES_JA と一致)
REGION_JA = {
    "hokkaido": "北海道", "tohoku": "東北", "tokyo": "東京",
    "chubu": "中部", "hokuriku": "北陸", "kansai": "関西",
    "chugoku": "中国", "shikoku": "四国", "kyushu": "九州",
    "okinawa": "沖縄",
}

# tier suffix と、その帯に含める下限 kv。grid_map.js voltageTier の選択先と一致。
# suffix ファイルは「下限以上を全部含む」累積帯。'all' は閾値 0 = 全件(null/不明含む)。
TIER_SUFFIXES = ["275kv", "154kv", "all"]
TIER_MIN_KV = {"275kv": 275.0, "154kv": 154.0, "all": 0.0}


def clean_kv(kv):
    """建造モデルの kv を grid_map.js の電圧契約に合わせて正規化。

    不明/欠損/異常(<=0 または >1100)は捏造防止のため None を返す(偽 500kV を作らない)。
    正常値は float で返す。
    """
    if kv is None:
        return None
    try:
        v = float(kv)
    except (TypeError, ValueError):
        return None
    if not (v > 0) or v > KV_MAX_REAL:
        return None
    return v


def r(x):
    return round(float(x), COORD_PRECISION)


def kv_in_tier(kv, suffix):
    """この feature(電圧 kv, None 可)が suffix タイルに載るか。

    grid_map.js: suffix ファイルは下限以上を累積で含む。
    null/不明(kv None)は閾値を満たせないので 'all'(下限0)にのみ載る。
    """
    floor = TIER_MIN_KV[suffix]
    if kv is None:
        return floor <= 0.0          # all のみ
    return kv >= floor


def _haversine_km(lat1, lon1, lat2, lon2):
    """2点間の距離(km)。名前一致属性の座標妥当性チェック用(誤接続防止)。"""
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(a)))


def load_attr_sources():
    """旧 substations.geojson から属性を読み、座標index(4桁)と名前indexを作る。

    返り値 (by_coord, by_name):
      by_coord: {(lat4,lon4): props}             厳密座標一致用
      by_name : {name: [(props, lat, lon), ...]} 名前一致用(同名は座標で最寄りを選ぶ)
    ファイルが無ければ (None, None)=属性結合なし(従来どおり幾何のみで安全に縮退)。
    """
    if not os.path.exists(SUBS_ENRICH):
        print(f"  (no attr source {SUBS_ENRICH}; emitting geometry-only subs)")
        return None, None
    with open(SUBS_ENRICH, encoding="utf-8") as f:
        feats = json.load(f).get("features", [])
    by_coord, by_name = {}, {}
    for ft in feats:
        g = ft.get("geometry") or {}
        c = g.get("coordinates")
        if not c or len(c) < 2 or c[0] is None or c[1] is None:
            continue
        lon, lat = float(c[0]), float(c[1])        # GeoJSON は [lon,lat]
        props = ft.get("properties") or {}
        by_coord.setdefault((round(lat, COORD_PRECISION), round(lon, COORD_PRECISION)), props)
        nm = (props.get("name") or "").strip()
        if nm:
            by_name.setdefault(nm, []).append((props, lat, lon))
    print(f"  attr source: {len(feats)} features "
          f"({len(by_coord)} coord keys, {len(by_name)} unique names)")
    return by_coord, by_name


def match_attr(node, by_coord, by_name):
    """built ノードに旧属性を突合する。戻り値 (props|None, source|None)。

    優先順: (1) 4桁座標厳密一致='coord'(最も確実)、(2) 名前完全一致='name'
    (ただし座標が ATTR_NAME_MAX_KM を超える同名は別物として捨てる=誤接続防止)。
    どちらも当たらなければ (None, None)=供給元に存在しない(捏造で埋めない)。
    """
    lat, lon = float(node["lat"]), float(node["lon"])
    hit = by_coord.get((round(lat, COORD_PRECISION), round(lon, COORD_PRECISION)))
    if hit is not None:
        return hit, "coord"
    nm = (node.get("name") or "").strip()
    if nm and nm in by_name:
        best, best_d = None, 1e9
        for props, plat, plon in by_name[nm]:
            d = _haversine_km(lat, lon, plat, plon)
            if d < best_d:
                best_d, best = d, props
        if best is not None and best_d <= ATTR_NAME_MAX_KM:
            return best, "name"
    return None, None


def build_sub_features(nodes, by_coord=None, by_name=None):
    """sub==1 のノードを Point feature 化(座標 [lon,lat]、4桁丸め)。

    建造モデルでは同一物理変電所が電圧別に複数ノードへ分かれる(例 "X 154kV"/"X 66kV"、
    同一 lat/lon)。これは旧 geojson が電圧別 Point を持っていたのと同じ粒度なので
    そのまま 1 ノード=1 feature とする(=捏造でない・潰さない)。

    by_coord/by_name が与えられれば、旧 substations.geojson の属性を結合して焼き込む
    (POPUP_FIELDS のうち値があるキーのみ + _attr_source)。供給元に無いノードは幾何のみ。
    """
    feats = []
    n_coord = n_name = n_none = 0
    for n in nodes:
        if n.get("sub") != 1:
            continue
        lat, lon = n.get("lat"), n.get("lon")
        if lat is None or lon is None:
            continue
        region = n.get("region") or ""
        props = {
            "_region": region,
            "_region_ja": REGION_JA.get(region, ""),
            "_display_name": n.get("name") or "",
            "_voltage_kv": clean_kv(n.get("kv")),
        }
        if by_coord is not None:
            attrs, src = match_attr(n, by_coord, by_name)
            if attrs:
                for k in POPUP_FIELDS:
                    v = attrs.get(k)
                    if v is not None and v != "":
                        props[k] = v
                props["_attr_source"] = src
                if src == "coord":
                    n_coord += 1
                else:
                    n_name += 1
            else:
                n_none += 1
        feats.append({
            "type": "Feature",
            "properties": props,
            "geometry": {
                "type": "Point",
                "coordinates": [r(lon), r(lat)],
            },
        })
    if by_coord is not None:
        tot = n_coord + n_name + n_none
        cov = 100 * (n_coord + n_name) // max(tot, 1)
        print(f"  attr join: coord={n_coord} name={n_name} none={n_none} "
              f"-> covered {cov}% of {tot} subs")
    return feats


def _edge_region(edge, nodes_by_coord):
    """edge には region が無いので、端点(a)に最も近い実ノードの region を引く。

    a/b/path は [lat,lon]。座標を 4桁丸めキーで突き合わせる(ノードと同じ座標格子)。
    引けない場合は path[0] でも試し、最後は "" を返す(捏造しない)。
    """
    for pt in (edge.get("a"), (edge.get("path") or [None])[0], edge.get("b")):
        if not pt:
            continue
        key = (round(float(pt[0]), COORD_PRECISION), round(float(pt[1]), COORD_PRECISION))
        reg = nodes_by_coord.get(key)
        if reg:
            return reg
    return ""


def build_line_features(edges, nodes_by_coord):
    """edge を LineString feature 化。

    geometry は path(実ルート、[lat,lon])を [lon,lat] へ反転して採用。
    path が無い edge(stitch/tie 等、約 1/4)は端点 [a,b] の 2 点線にフォールバック。
    _display_name は built edge の name(OSM線名。build_editor_data が付与)を採用。
    名前が無い edge は ""(JS側で "Unnamed" 表示)。捏造はしない。
    """
    feats = []
    for e in edges:
        path = e.get("path")
        if not path or len(path) < 2:
            a, b = e.get("a"), e.get("b")
            if not a or not b:
                continue
            path = [a, b]
        coords = [[r(lon), r(lat)] for (lat, lon) in path]
        if len(coords) < 2:
            continue
        region = _edge_region(e, nodes_by_coord)
        feats.append({
            "type": "Feature",
            "properties": {
                "_region": region,
                "_region_ja": REGION_JA.get(region, ""),
                "_display_name": e.get("name") or "",
                "_voltage_kv": clean_kv(e.get("kv")),
            },
            "geometry": {
                "type": "LineString",
                "coordinates": coords,
            },
        })
    return feats


def write_geojson(path, features):
    fc = {"type": "FeatureCollection", "features": features}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False, separators=(",", ":"))


def recompute_regions(sub_feats, line_feats):
    """regions.json を built 由来の件数 + bbox で更新。frequency_hz/name_* は保持。"""
    with open(REGIONS_JSON, encoding="utf-8") as f:
        regions = json.load(f)

    # built 由来の per-region 件数 (subs = sub feature 数、lines = line feature 数)
    sub_count, line_count = {}, {}
    # bbox は built ノード/線の全 feature 座標から
    bbox = {}  # region -> [lat_min, lat_max, lon_min, lon_max]

    def acc(region, lat, lon):
        if region not in bbox:
            bbox[region] = [lat, lat, lon, lon]
        else:
            b = bbox[region]
            b[0] = min(b[0], lat); b[1] = max(b[1], lat)
            b[2] = min(b[2], lon); b[3] = max(b[3], lon)

    for fe in sub_feats:
        reg = fe["properties"]["_region"]
        sub_count[reg] = sub_count.get(reg, 0) + 1
        lon, lat = fe["geometry"]["coordinates"]
        if reg:
            acc(reg, lat, lon)
    for fe in line_feats:
        reg = fe["properties"]["_region"]
        line_count[reg] = line_count.get(reg, 0) + 1
        if reg:
            for lon, lat in fe["geometry"]["coordinates"]:
                acc(reg, lat, lon)

    for rentry in regions:
        rid = rentry["id"]
        rentry["substations"] = sub_count.get(rid, 0)
        rentry["lines"] = line_count.get(rid, 0)
        # bbox は built 実データがある region だけ更新(無ければ既存値を残す=捏造しない)。
        # frequency_hz / name_en / name_ja / plants は一切触らない。
        if rid in bbox:
            b = bbox[rid]
            rentry["bounding_box"] = {
                "lat_min": round(b[0], 3), "lat_max": round(b[1], 3),
                "lon_min": round(b[2], 3), "lon_max": round(b[3], 3),
            }

    with open(REGIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(regions, f, ensure_ascii=False, indent=2)
    return regions


def count_old(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return len(json.load(f).get("features", []))
    except Exception:
        return None


def main():
    if not os.path.exists(BUILT_ALL):
        print(f"ERROR: built model not found: {BUILT_ALL}", file=sys.stderr)
        return 1

    with open(BUILT_ALL, encoding="utf-8") as f:
        built = json.load(f)
    nodes = built.get("nodes", [])
    edges = built.get("edges", [])
    print(f"built/all.json: {len(nodes)} nodes, {len(edges)} edges "
          f"(model generated {built.get('generated')})")

    # 座標(4桁) -> region。edge の region 推定に使う(node と同じ格子)。
    nodes_by_coord = {}
    for n in nodes:
        lat, lon = n.get("lat"), n.get("lon")
        if lat is None or lon is None:
            continue
        nodes_by_coord[(round(float(lat), COORD_PRECISION),
                        round(float(lon), COORD_PRECISION))] = n.get("region") or ""

    print("\n=== attribute join from substations.geojson (C層属性を D層へ焼き込み) ===")
    by_coord, by_name = load_attr_sources()
    all_subs = build_sub_features(nodes, by_coord, by_name)
    all_lines = build_line_features(edges, nodes_by_coord)
    print(f"derived: {len(all_subs)} substation Points, {len(all_lines)} line LineStrings")

    # null/不明電圧の件数(捏造せず all タイルにのみ載るもの)
    null_sub = sum(1 for f in all_subs if f["properties"]["_voltage_kv"] is None)
    null_line = sum(1 for f in all_lines if f["properties"]["_voltage_kv"] is None)
    print(f"  unknown/null kv (kept as null, 'all' tile only): "
          f"{null_sub} subs, {null_line} lines")

    # tier ごとに分配して書き出し + old/new 比較
    print("\n=== tier file regeneration (old -> new feature counts) ===")
    print(f"{'file':<26}{'old':>8}{'new':>8}")
    summary = []
    for suffix in TIER_SUFFIXES:
        subs_t = [f for f in all_subs if kv_in_tier(f["properties"]["_voltage_kv"], suffix)]
        lines_t = [f for f in all_lines if kv_in_tier(f["properties"]["_voltage_kv"], suffix)]

        subs_path = os.path.join(DATA_DIR, f"subs_{suffix}.geojson")
        lines_path = os.path.join(DATA_DIR, f"lines_{suffix}.geojson")
        old_subs = count_old(subs_path)
        old_lines = count_old(lines_path)

        write_geojson(subs_path, subs_t)
        write_geojson(lines_path, lines_t)

        for name, old, new in [
            (f"subs_{suffix}.geojson", old_subs, len(subs_t)),
            (f"lines_{suffix}.geojson", old_lines, len(lines_t)),
        ]:
            print(f"{name:<26}{('-' if old is None else old):>8}{new:>8}")
            summary.append((name, old, new))

    # regions.json (件数 + bbox 更新、frequency_hz 保持)
    print("\n=== regions.json (built件数 + bbox 更新、frequency_hz は保持) ===")
    regions = recompute_regions(all_subs, all_lines)
    print(f"{'region':<10}{'subs':>7}{'lines':>8}{'freqHz':>8}")
    for re_ in regions:
        print(f"{re_['id']:<10}{re_['substations']:>7}{re_['lines']:>8}{re_['frequency_hz']:>8}")

    # JSON 妥当性検証(再読込) + サンプル feature
    print("\n=== validation: json.load round-trip + sample features ===")
    ok = True
    for suffix in TIER_SUFFIXES:
        for kind in ("subs", "lines"):
            p = os.path.join(DATA_DIR, f"{kind}_{suffix}.geojson")
            try:
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                assert d["type"] == "FeatureCollection"
                _ = d["features"]
            except Exception as exc:  # noqa: BLE001
                ok = False
                print(f"  INVALID {p}: {exc}")
    p = REGIONS_JSON
    try:
        with open(p, encoding="utf-8") as f:
            json.load(f)
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"  INVALID {p}: {exc}")
    print(f"  all JSON valid: {ok}")

    # サンプル feature(座標順 [lon,lat] の確認込み)
    def sample(path, n=1):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d["features"][:n]

    print("\n  sample subs_275kv.geojson feature:")
    for fe in sample(os.path.join(DATA_DIR, "subs_275kv.geojson")):
        print("   ", json.dumps(fe, ensure_ascii=False))
    print("  sample lines_275kv.geojson feature (coords truncated):")
    for fe in sample(os.path.join(DATA_DIR, "lines_275kv.geojson")):
        c = fe["geometry"]["coordinates"]
        fe2 = {**fe, "geometry": {"type": "LineString",
                                  "coordinates": c[:3] + (["..."] if len(c) > 3 else [])}}
        print("   ", json.dumps(fe2, ensure_ascii=False))
        # 座標順チェック: 日本は lon≈123..146 / lat≈24..46。先頭座標で [lon,lat] を確認。
        lon, lat = c[0][0], c[0][1]
        order_ok = (120 <= lon <= 150) and (20 <= lat <= 50)
        print(f"    coord-order check first=[{lon},{lat}] -> [lon,lat] plausible: {order_ok}")

    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
