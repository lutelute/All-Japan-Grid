#!/usr/bin/env python3
"""確定マッチ(auto+裁定済み)から出典レコードを生成する(1-C GEM充填).

規約:
  - value = **Operating 状態のユニットのみ**の銘板容量合算(退役/計画/建設中は含めない)
  - quote = gem.wiki ページの逐語セル("<unit>: <Status> — <Nameplate capacity>")
  - source_url = 実在の gem.wiki ページURL / source_type = other(GEM=二次資料)
  - confidence = medium(GEM は集約DB。一次=high の既存規約と整合)
  - 全国で発電所名が衝突する場合は生成しない(apply が名前照合のため誤反映防止)

使い方: python3 build_gem_records.py gem_japan_pages.jsonl confirmed.jsonl <repo> out.jsonl
  confirmed.jsonl: {"plant": {...}, "match": {"j"?, "title", ...}} の行集合
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


def main():
    gem_path, confirmed_path, repo, out_path = sys.argv[1:5]
    gem_by_title = {}
    for line in open(gem_path, encoding="utf-8"):
        g = json.loads(line)
        gem_by_title[g["title"]] = g

    # 全国の発電所名の出現回数(名前照合applyの誤反映ガード)
    name_count = {}
    regions = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
               "kansai", "chugoku", "shikoku", "kyushu", "okinawa"]
    for reg in regions:
        try:
            d = json.load(open(f"{repo}/data/{reg}_plants.geojson", encoding="utf-8"))
        except FileNotFoundError:
            continue
        for f in d["features"]:
            nm = norm_plain((f.get("properties") or {}).get("name"))
            if nm:
                name_count[nm] = name_count.get(nm, 0) + 1

    rows, skipped = [], {"name_collision": 0, "no_operating": 0,
                         "no_units": 0, "missing_gem": 0}
    seen_names = set()
    for line in open(confirmed_path, encoding="utf-8"):
        rec = json.loads(line)
        pl, m = rec["plant"], rec["match"]
        g = gem_by_title.get(m["title"])
        if not g:
            skipped["missing_gem"] += 1
            continue
        nm = norm_plain(pl["name"])
        if not nm or name_count.get(nm, 0) != 1 or nm in seen_names:
            skipped["name_collision"] += 1
            continue
        units = [u for u in (g.get("units") or []) if u.get("cap_mw")]
        if not units:
            skipped["no_units"] += 1
            continue
        ops = [u for u in units
               if str(u.get("status", "")).strip().lower() in OPERATING]
        if not ops:
            skipped["no_operating"] += 1
            continue
        total = round(sum(u["cap_mw"] for u in ops), 3)
        quote = "; ".join(
            f"{(u['name'] + ': ') if u['name'] else ''}{u['status']} — {u['cap_raw']}"
            for u in ops)[:500]
        url = "https://www.gem.wiki/" + urllib.parse.quote(
            g["title"].replace(" ", "_"))
        is_solar = g["category"] == "Solar farms in Japan"
        conv = " + ".join(u["cap_raw"] for u in ops)
        note = (f"Operating {len(ops)}基/フェーズの銘板合算: {conv} = {total} MW。"
                f"GEM(Global Energy Monitor)=集約DB(CC BY 4.0)・一次refはページ内引用を参照。"
                f"突合根拠: 座標{m.get('d','?')}m"
                + ("・和名一致" if m.get("name_eq") else "")
                + ("。太陽光の銘板はMWp/dc(直流ピーク)表記の場合あり" if is_solar else "")
                + (f"。裁定={rec.get('verdict_note')}" if rec.get("verdict_note") else ""))
        rows.append({
            "plant_key": f"plant:{pl['name']}",
            "name": pl["name"],
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
        seen_names.add(nm)

    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"records={len(rows)} skipped={skipped}")


if __name__ == "__main__":
    main()
