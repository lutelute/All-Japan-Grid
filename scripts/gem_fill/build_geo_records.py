#!/usr/bin/env python3
"""確定マッチのうち名前衝突でレコード化見送りになった分を座標キーで出典レコード化する.

build_gem_records.py の姉妹版(1-C残の回収)。名前が全国非一意な確定マッチに対し
plant_key = "geo:<region>:<lon.4f>,<lat.4f>"(D層Point 4桁丸めと同一書式)を発行する。

自己検証(全件必須・落ちたものは生成しない):
  - キーが docs/data/plants_all.geojson で**ちょうど1 feature**に一致
  - その feature の name が plant名と一致(名前は照合に使わないが同一性の証跡)
  - 生成レコード間でキー重複なし
  - GEMページ内の重複ユニット行(別トラッカー併載等)は合算不能として不採用
    (実例: 戸畑共同火力=「2: 156」と「Unit 2: 156.3」併存で二重計上になる)

使い方: python3 build_geo_records.py gem_japan_pages.jsonl confirmed.jsonl <repo> out.jsonl
"""
import json
import re
import sys
import unicodedata
import urllib.parse

RETRIEVED = "2026-07-11"
OPERATING = {"operating"}


def norm_plain(s):
    return re.sub(r"[\s　]", "", unicodedata.normalize("NFKC", str(s or "")))


def geo_key(region, lon, lat):
    return f"geo:{region}:{lon:.4f},{lat:.4f}"


def main():
    gem_path, confirmed_path, repo, out_path = sys.argv[1:5]
    gem_by_title = {}
    for line in open(gem_path, encoding="utf-8"):
        g = json.loads(line)
        gem_by_title[g["title"]] = g

    # 全国の発電所名の出現回数(=名前一意ならbuild_gem_records.py側で出荷済み)
    name_count = {}
    regions = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
               "kansai", "chugoku", "shikoku", "kyushu", "okinawa"]
    region_feats = {}
    for reg in regions:
        try:
            d = json.load(open(f"{repo}/data/{reg}_plants.geojson", encoding="utf-8"))
        except FileNotFoundError:
            continue
        region_feats[reg] = d["features"]
        for f in d["features"]:
            nm = norm_plain((f.get("properties") or {}).get("name"))
            if nm:
                name_count[nm] = name_count.get(nm, 0) + 1

    def dup_units(ops):
        """GEMページ内の重複ユニット行(別トラッカー併載等)を検出=合算不能。"""
        keys = [re.sub(r"[\s\-_#]|unit|phase|no\.?", "", str(u.get("name") or "").lower())
                for u in ops]
        named = [k for k in keys if k]
        return len(named) != len(set(named))

    rows, skipped = [], {"name_unique_already_shipped": 0, "no_operating": 0,
                         "missing_gem": 0, "no_coords": 0, "gem_page_dup_units": 0}
    for line in open(confirmed_path, encoding="utf-8"):
        rec = json.loads(line)
        pl, m = rec["plant"], rec["match"]
        nm = norm_plain(pl["name"])
        if nm and name_count.get(nm, 0) == 1:
            skipped["name_unique_already_shipped"] += 1
            continue
        g = gem_by_title.get(m["title"])
        if not g:
            skipped["missing_gem"] += 1
            continue
        # R層の全精度座標から座標キーを発行(Point前提)
        try:
            ft = region_feats[pl["region"]][pl["idx"]]
            lon, lat = ft["geometry"]["coordinates"]
        except Exception:
            skipped["no_coords"] += 1
            continue
        ops = [u for u in (g.get("units") or [])
               if u.get("cap_mw") and str(u.get("status", "")).strip().lower() in OPERATING]
        if not ops:
            skipped["no_operating"] += 1
            continue
        if dup_units(ops):
            skipped["gem_page_dup_units"] += 1
            print(f"  skip(ページ内重複unit行): {pl['name']} <- {g['title']}")
            continue
        total = round(sum(u["cap_mw"] for u in ops), 3)
        quote = "; ".join(
            f"{(u['name'] + ': ') if u['name'] else ''}{u['status']} — {u['cap_raw']}"
            for u in ops)[:500]
        url = "https://www.gem.wiki/" + urllib.parse.quote(g["title"].replace(" ", "_"))
        is_solar = g["category"] == "Solar farms in Japan"
        conv = " + ".join(u["cap_raw"] for u in ops)
        disp = pl["name"] or (ft.get("properties") or {}).get("_display_name") \
            or f"(無名){pl['region']}:{pl['idx']}"
        note = (f"Operating {len(ops)}基/フェーズの銘板合算: {conv} = {total} MW。"
                f"GEM(Global Energy Monitor)=集約DB(CC BY 4.0)・一次refはページ内引用を参照。"
                f"突合根拠: 座標{m.get('d','?')}m"
                + ("・和名一致" if m.get("name_eq") else "")
                + ("。太陽光の銘板はMWp/dc(直流ピーク)表記の場合あり" if is_solar else "")
                + (f"。裁定={rec.get('verdict_note')}" if rec.get("verdict_note") else "")
                + "。適用キー=座標4桁(発電所名が全国非一意のため名前照合は不使用)")
        rows.append({
            "plant_key": geo_key(pl["region"], lon, lat),
            "name": disp,
            "field": "capacity_mw",
            "value": total if total != int(total) else int(total),
            "unit": "MW",
            "source_type": "other",
            "source_url": url,
            "source_title": f"{g['title']} — Global Energy Monitor wiki "
                            f"(Global Integrated Power Tracker系列, CC BY 4.0)",
            "quote": quote,
            "retrieved_at": RETRIEVED,
            "confidence": "medium",
            "collected_by": "Claude Fable 5",
            "note": note,
        })

    # --- 自己検証: D層plants_allでキーがちょうど1 featureに一致し、名前も一致 ---
    da = json.load(open(f"{repo}/docs/data/plants_all.geojson", encoding="utf-8"))
    key_feats = {}
    for ft in da["features"]:
        g2 = ft.get("geometry") or {}
        p2 = ft.get("properties") or {}
        if g2.get("type") != "Point" or not p2.get("_region"):
            continue
        k = geo_key(p2["_region"], g2["coordinates"][0], g2["coordinates"][1])
        key_feats.setdefault(k, []).append(p2)
    seen_keys = {}
    for r in rows:
        seen_keys.setdefault(r["plant_key"], []).append(r)
    verified, dropped = [], []
    for r in rows:
        k = r["plant_key"]
        if len(seen_keys[k]) > 1:
            dropped.append((k, "record-key-duplicate"))
            continue
        hits = key_feats.get(k, [])
        if len(hits) != 1:
            dropped.append((k, f"d-layer-hits={len(hits)}"))
            continue
        fname = (hits[0].get("name") or "").strip()
        if norm_plain(fname) != norm_plain(r["name"]) and r["name"] != hits[0].get("_display_name"):
            dropped.append((k, f"name-mismatch: D={fname!r} rec={r['name']!r}"))
            continue
        verified.append(r)

    with open(out_path, "w", encoding="utf-8") as f:
        for r in verified:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"records={len(verified)} skipped={skipped} 検証落ち={len(dropped)}")
    for k, why in dropped:
        print(f"  drop {k}: {why}")


if __name__ == "__main__":
    main()
