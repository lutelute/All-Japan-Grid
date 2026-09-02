#!/usr/bin/env python3
"""出典必須DB(generator_capacity_sources.jsonl)の容量を発電所geojsonに反映(出典付き)。

    PYTHONPATH=. python scripts/apply_capacity_sources.py

オーナー方針「嘘をつかず必ず引用」を**表示まで貫く**: 出典DBの検証済み容量を
docs/data の plants_*/generators.geojson に
  capacity_mw_sourced / capacity_source_url / capacity_source_type /
  capacity_source_conf / capacity_source_note
として付与し、grid_map の popup/CSV が「公式容量 X MW [出典リンク]」を出せるようにする。
**元の capacity_mw(OSM/P03)は保持**(比較用=OSM過小値が出典で正される様子が見える)。

突合(2経路・混線しない):
  1. 名前照合 — plant_key が "geo:" 以外のレコード。発電所名の完全一致 + 正規化一致
     (「発電所/株式会社/空白」のみ除去。火力/水力/原子力/第一/第二は温存)。同名は
     confidence 高(official>wikipedia>) を優先。
  2. 座標キー照合 — plant_key = "geo:<region>:<lon.4f>,<lat.4f>" のレコード。
     発電所名が全国で非一意(「〇〇市発電所」等の自動命名)な場合の安定キー。
     D層Pointの4桁丸め座標+_regionと完全一致で照合。**geoレコードは名前索引に入れない**
     (名前が曖昧だからgeoキーにしている)し、ファイル内で同一キーを持つfeatureが複数
     ある場合(隣接ソーラー分割片等)はどれにも適用しない(誤反映防止)。
両経路が同一featureで競合した場合の優先: 名前レコードのplant_keyが座標を内包
("p03:名前:lat,lon"等)しそれが当該featureを指し(±0.005°)かつconfidenceが同等以上なら
名前レコード(=公式出典の格を維持)。それ以外は**feature特定的に裁定済みのgeoが勝つ**。
実例: 「相浦火力発電所」は同名2feature(廃止油火力跡 + P03遺物名のメガソーラー)があり、
名前照合だけだと廃止0MWがソーラー側にも塗られる(誤反映)。geo優先でこれを防ぐ。
出典DBに無い発電所は一切触らない(捏造しない)。
base extract(data/直下のOSM生抽出)は触らない。本スクリプトは docs/data の D層のみ更新。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from capacity_provenance import load_records  # noqa: E402

DATA = os.path.join(ROOT, "docs", "data")
TARGETS = ["generators.geojson", "plants_all.geojson", "plants_utility.geojson", "plants_ipp.geojson"]
CONF_RANK = {"high": 2, "medium": 1, "low": 0}

SOURCED_FIELDS = [
    "capacity_mw_sourced", "capacity_source_url", "capacity_source_type",
    "capacity_source_conf", "capacity_source_note",
]


def norm(s):
    # 火力/水力/原子力/第一/第二 は **除去しない**(広野火力≠広野水力、姫路第一≠第二、
    # 知多火力≠知多 等の混同=別発電所への誤反映を防ぐ)。空白と「発電所/株式会社」のみ除去。
    return re.sub(r"[\s　]|発電所|株式会社", "", s or "")


def geo_key(region, lon, lat):
    """座標キー。D層Point(4桁丸め)とレコード生成側で同一の書式を使う。"""
    return f"geo:{region}:{lon:.4f},{lat:.4f}"


def feature_geo_key(ft):
    """featureの座標キー(Point以外・_region無しは None=照合対象外)。"""
    g = ft.get("geometry") or {}
    p = ft.get("properties") or {}
    if g.get("type") != "Point" or not p.get("_region"):
        return None
    lon, lat = g["coordinates"]
    return geo_key(p["_region"], lon, lat)


LEGACY_KEY_COORD_RE = re.compile(r":(-?\d{1,3}\.\d+),(-?\d{1,3}\.\d+)$")


def legacy_key_latlon(rec):
    """レガシーplant_key("p03:名前:lat,lon"/"osm:名前:lat,lon")の内包座標。無ければNone。"""
    m = LEGACY_KEY_COORD_RE.search(str(rec.get("plant_key", "")))
    if not m:
        return None
    a, b = float(m.group(1)), float(m.group(2))
    return (a, b) if abs(a) <= 90 else None  # lat,lon 順のみ許容


# ── 燃料種の整合ゲート(2026-09-02) ──────────────────────────────────────
# 名前照合は「同名の別設備」を区別できない。実例: 高崎市の太陽光「高浜発電所」(25MW×4
# 地物)に関電 高浜発電所(原子力 3,392MW)の公式容量が塗られ、PF の出典付き容量経路
# (sourced_capacity_index)で east に 13,569MW の幻の太陽光が立った。姫路第二(gas 4,119)
# の隣接ソーラー、松浦火力の隣接ソーラーも同型。
# 規則: 名前レコードは feature の fuel_type と整合するときだけ適用する。レコードに
# fuel_type があれば完全一致、無ければ「IBR(太陽光/風力/蓄電)の feature には IBR を指す
# 語を含むレコードだけ」。**不整合でも例外的に許すのは「レコードの
# 値が OSM 値以下(=容量を増やさない)」場合のみ** — 大間・浪江小高の
# ように OSM が計画原子力の敷地を solar と誤タグした feature を、公式の「運転容量 0」で
# 是正する経路を残すため(容量を増やす方向の不整合適用=幻の電源は決して作らない)。
# geo: レコード(feature 特定的に裁定済み)はゲートを通さない。
IBR_FUELS = {"solar", "photovoltaic", "wind", "battery"}
IBR_WORDS = ("太陽光", "ソーラー", "風力", "蓄電", "solar", "wind", "battery", "pv")


def fuel_compatible(rec, ft) -> bool:
    """名前レコードを feature に適用してよいか(燃料種の整合)。"""
    p = ft.get("properties") or {}
    fuel = str(p.get("fuel_type") or "").strip().lower()
    rf = str(rec.get("fuel_type") or "").strip().lower()
    if rf:
        ok = rf == fuel
    elif fuel in IBR_FUELS:
        text = " ".join(str(rec.get(k) or "") for k in
                        ("name", "note", "source_title", "quote")).lower()
        ok = any(w in text for w in IBR_WORDS)
    else:
        ok = True
    if ok:
        return True
    # 例外: 容量を増やさない(是正方向のみ)。OSM 値が既知(>=0)で レコード値 <= OSM 値。
    # 幻の電源は決して作らない一方、公式の「運転容量 0」で誤タグ敷地を消す経路は残す。
    osm = p.get("capacity_mw")
    try:
        return (isinstance(osm, (int, float)) and osm >= 0
                and float(rec.get("value", 0)) <= float(osm))
    except (TypeError, ValueError):
        return False


def choose_record(name_rec, geo_rec, ft):
    """名前照合とgeoキー照合が同一featureで競合したときの優先規則。"""
    if not geo_rec:
        return name_rec
    if not name_rec:
        return geo_rec
    ll = legacy_key_latlon(name_rec)
    if ll and CONF_RANK[name_rec["confidence"]] >= CONF_RANK[geo_rec["confidence"]]:
        g = ft.get("geometry") or {}
        if g.get("type") == "Point":
            lon, lat = g["coordinates"]
            if abs(ll[0] - lat) <= 0.005 and abs(ll[1] - lon) <= 0.005:
                return name_rec  # 名前レコードが座標でこのfeatureを確証している
    return geo_rec  # feature特定的に裁定済みのgeoが勝つ


def main(data_dir=DATA, records=None):
    src = load_records() if records is None else records
    geo_recs = [r for r in src if str(r.get("plant_key", "")).startswith("geo:")]
    name_recs = [r for r in src if not str(r.get("plant_key", "")).startswith("geo:")]
    by_name, by_norm, by_key = {}, {}, {}
    for r in name_recs:
        n = r["name"]
        if n not in by_name or CONF_RANK[r["confidence"]] > CONF_RANK[by_name[n]["confidence"]]:
            by_name[n] = r
    for n, r in by_name.items():
        by_norm.setdefault(norm(n), r)
    for r in geo_recs:
        k = r["plant_key"]
        if k not in by_key or CONF_RANK[r["confidence"]] > CONF_RANK[by_key[k]["confidence"]]:
            by_key[k] = r
    print(f"出典DB: {len(src)} 行 / 名前照合 {len(by_name)} + 座標キー {len(by_key)} 発電所")

    for tgt in TARGETS:
        path = os.path.join(data_dir, tgt)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        applied = 0
        cleared = 0
        # ファイル内でキーが重複するfeature(分割片等)はどれにも適用しない
        key_count = {}
        for ft in d.get("features", []):
            k = feature_geo_key(ft)
            if k:
                key_count[k] = key_count.get(k, 0) + 1
        ambiguous = 0
        fuel_vetoed = []
        for ft in d.get("features", []):
            p = ft.get("properties") or {}
            name = (p.get("_display_name") or p.get("name") or "").strip()
            name_rec = by_name.get(name) or (by_norm.get(norm(name)) if name else None)
            geo_rec = None
            k = feature_geo_key(ft)
            if k and k in by_key:
                if key_count.get(k, 0) == 1:
                    geo_rec = by_key[k]
                else:
                    ambiguous += 1
            if name_rec and not fuel_compatible(name_rec, ft):
                fuel_vetoed.append((name, p.get("fuel_type"), name_rec["name"],
                                    name_rec["value"]))
                name_rec = None
            rec = choose_record(name_rec, geo_rec, ft)
            # 冪等性: 既存の sourced を一旦消してから(出典DB更新を反映)
            had = any(k in p for k in SOURCED_FIELDS)
            for k in SOURCED_FIELDS:
                p.pop(k, None)
            if rec:
                p["capacity_mw_sourced"] = rec["value"]
                p["capacity_source_url"] = rec["source_url"]
                p["capacity_source_type"] = rec["source_type"]
                p["capacity_source_conf"] = rec["confidence"]
                if rec.get("note"):
                    p["capacity_source_note"] = rec["note"]
                applied += 1
            elif had:
                cleared += 1
            ft["properties"] = p
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
        # OSM/P03 値と出典値の乖離サンプル
        difs = []
        for ft in d["features"]:
            p = ft["properties"]
            if "capacity_mw_sourced" in p and isinstance(p.get("capacity_mw"), (int, float)):
                o, s = p["capacity_mw"], p["capacity_mw_sourced"]
                den = max(o, s)
                if den > 0 and abs(o - s) / den > 0.1:
                    difs.append((p.get("_display_name") or p.get("name"), o, s))
        note_amb = f" 座標キー曖昧skip={ambiguous}" if ambiguous else ""
        note_fuel = f" 燃料種不整合veto={len(fuel_vetoed)}" if fuel_vetoed else ""
        print(f"  {tgt}: applied={applied} (cleared stale={cleared}){note_amb}{note_fuel}")
        for nm, fuel, rn, val in fuel_vetoed[:6]:
            print(f"     veto {nm}({fuel}) ← レコード「{rn}」{val}MW")
        if tgt == "plants_all.geojson":
            led = os.path.join(ROOT, "docs", "reports", "capacity_source_fuel_veto.json")
            with open(led, "w", encoding="utf-8") as f:
                json.dump({"note": "名前照合の燃料種不整合で適用を拒否した(feature, fuel, record, MW)。"
                                   "幻の電源を作らないためのゲート(2026-09-02)",
                           "n": len(fuel_vetoed),
                           "vetoed": [{"feature": a, "fuel": b, "record": c, "value_mw": d}
                                      for a, b, c, d in fuel_vetoed]},
                          f, ensure_ascii=False, indent=1)
        for nm, o, s in difs[:4]:
            print(f"     乖離 {nm}: OSM/P03={o} → 出典={s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
