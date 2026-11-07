#!/usr/bin/env python3
"""系統図ビューアー(docs/map.html)の「重ねて見る」で使う小さな表を作る(2026-11-07).

出力(docs/data/overlays/):
  interconnectors.json  連系線ごとの運用容量(OCCTO 公表値の期間最大・中央値)と、
                        JEPX スポット市場で両側のエリアプライスが違った 30 分の割合(年度の集計)
  area_prices.json      エリアごとのエリアプライスの年度平均・中央値(JEPX)

どちらも observed(公表値)とその集計。AGJ のモデルの計算値(derived)は入れない。
docs/OBSERVED_VS_DERIVED.md の決まりどおり、計算の混み具合は別の層(flows_now_*.geojson を
ブラウザで読む)で、破線と別の色で描く。

入力:
  data/interconnector_capacity_sources.jsonl  OCCTO 系統情報公表(種別04・30 分値)から抽出済みの正本。
                                              利用条件は出典の明記(と加工したことの明記)で自由に利用可
                                              (https://www.occto.or.jp/chosakuken.html)
  data/reference/interconnections.yaml        連系線の端の変電所・変換所(位置の手がかり)
  docs/data/built/all.json                    変電所の座標(正典。読むだけ)
  JEPX spot_summary_<年度>.csv               data/external/jepx/ に置く(git に入れない)。
                                              https://www.jepx.jp/electricpower/market-data/spot/ の
                                              「スポット市場 取引結果」の年度ファイル。JEPX の免責事項・著作権
                                              (https://www.jepx.jp/disclaimer/)は「出所を明示した上で利用」。
                                              ここでは生の 30 分値は書き出さず、年度の集計値だけを出す。

使い方:
  python3 scripts/build_viewer_overlays.py --jepx data/external/jepx/spot_summary_2025.csv --fy 2025

印の位置は「その連系線の目印」であって経路ではない(地図にもそう書く)。位置の決め方は LINKS の
sites に書いた変電所・変換所の座標の平均。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import statistics
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CAP_JSONL = ROOT / "data/interconnector_capacity_sources.jsonl"
IC_YAML = ROOT / "data/reference/interconnections.yaml"
BUILT = ROOT / "docs/data/built/all.json"
OUT_DIR = ROOT / "docs/data/overlays"

AREAS = ["北海道", "東北", "東京", "中部", "北陸", "関西", "中国", "四国", "九州"]

# 連系線 → OCCTO の公表名・順方向の向き・JEPX の隣り合うエリア・目印の位置の手がかり。
# 順方向の向きは data/reference/interconnections.yaml の notes(介入#33 で正本化)から写した。
# sites は ("built", 正典のノード名) か ("yaml", 変換所名=yaml の location)。
LINKS = [
    {"id": "hokkaido-tohoku", "name": "北海道本州間連系設備", "kind": "直流",
     "occto": ["北海道・本州間電力連系設備"], "fwd": ("北海道", "東北"),
     "sites": [("yaml", "北斗変換所"), ("yaml", "今別変換所")],
     "site_note": "印は新北本(北斗変換所—今別変換所)の中ほど。旧北本(函館—上北)は函館変換所の位置が台帳に無い"},
    {"id": "tohoku-tokyo", "name": "東北東京間連系線", "kind": "交流",
     "occto": ["相馬双葉幹線"], "fwd": ("東北", "東京"),
     "sites": [("built", "南相馬変電所 500kV"), ("built", "新いわき開閉所")],
     "site_note": "印は南相馬変電所と新いわき開閉所の中ほど"},
    {"id": "tokyo-chubu", "name": "東京中部間連系設備(周波数変換)", "kind": "周波数変換",
     "occto": ["周波数変換設備"], "fwd": ("東京", "中部"),
     "sites": [("yaml", "新信濃変換所"), ("yaml", "佐久間周波数変換所"), ("yaml", "東清水変換所"), ("yaml", "飛騨変換所")],
     "site_note": "印は変換所 4 か所(新信濃・佐久間・東清水・飛騨)の位置の平均"},
    {"id": "chubu-kansai", "name": "中部関西間連系線", "kind": "交流",
     "occto": ["三重東近江線"], "fwd": ("関西", "中部"),
     "sites": [("built", "三重開閉所"), ("built", "東近江開閉所")],
     "site_note": "印は三重開閉所と東近江開閉所の中ほど"},
    {"id": "chubu-hokuriku", "name": "中部北陸間連系設備", "kind": "直流(BTB)",
     "occto": ["南福光連系所・南福光変電所の連系設備"], "fwd": ("中部", "北陸"),
     "sites": [("yaml", "南福光連系所")],
     "site_note": "印は南福光連系所",
     "cap_note": "期間の最大(順 1,310・逆 1,980 MW)は例外の状態の値。ふだんは中央値の 300 MW(BTB の定格)"
                 "として扱う(data/reference/interconnections.yaml の ic_005)"},
    {"id": "hokuriku-kansai", "name": "北陸関西間連系線", "kind": "交流",
     "occto": ["越前嶺南線"], "fwd": ("北陸", "関西"),
     "sites": [("built", "越前変電所 500kV"), ("built", "嶺南変電所 500kV")],
     "site_note": "印は越前変電所と嶺南変電所の中ほど"},
    {"id": "kansai-chugoku", "name": "関西中国間連系線", "kind": "交流",
     "occto": ["関西-中国（東）", "関西-中国（西）"], "fwd": ("関西", "中国"),
     "sites": [("built", "西播変電所 500kV"), ("built", "東岡山変電所 500kV")],
     "site_note": "OCCTO は(東)(西)の 2 つに分けて公表する(期間最大は同じ値)。印は西播変電所と東岡山変電所の中ほど"},
    {"id": "kansai-shikoku", "name": "関西四国間連系設備", "kind": "直流",
     "occto": ["阿南紀北直流幹線"], "fwd": ("関西", "四国"),
     "sites": [("yaml", "紀北変換所"), ("yaml", "阿南周波数変換所")],
     "site_note": "印は紀北変換所と阿南変換所の中ほど",
     "cap_note": "設備の設計は 1,400 MW(700 MW×2 極)だが、公表の運用容量はそれより小さい"
                 "(data/reference/interconnections.yaml の ic_007)"},
    {"id": "chugoku-shikoku", "name": "中国四国間連系線", "kind": "交流",
     "occto": ["本四連系線"], "fwd": ("中国", "四国"),
     "sites": [("built", "讃岐変電所 500kV")],
     "site_note": "印は四国側の端の讃岐変電所(台帳の中国側の端「東山口変電所」は位置が合わないので使っていない)"},
    {"id": "chugoku-kyushu", "name": "関門連系線", "kind": "交流",
     "occto": ["関門連系線"], "fwd": ("中国", "九州"),
     "sites": [("built", "新山口変電所 500kV"), ("built", "北九州変電所 500kV")],
     "site_note": "印は新山口変電所と北九州変電所の中ほど"},
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def yaml_locations() -> dict[str, tuple[float, float]]:
    ic = yaml.safe_load(IC_YAML.read_text(encoding="utf-8"))
    loc = {}
    for link in ic["interconnections"]:
        for key in ("converters", "frequency_converters"):
            for c in link.get(key) or []:
                if c.get("location"):
                    loc[c["name_ja"]] = (c["location"]["latitude"], c["location"]["longitude"])
    return loc


def built_locations(names: set[str]) -> dict[str, tuple[float, float]]:
    nodes = json.loads(BUILT.read_text(encoding="utf-8"))["nodes"]
    loc = {}
    for n in nodes:
        if n.get("name") in names and n["name"] not in loc:
            loc[n["name"]] = (n["lat"], n["lon"])
    return loc


def capacity_records() -> dict[tuple[str, str], dict]:
    recs = {}
    for line in CAP_JSONL.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            recs[(r["name"], r["direction"])] = r
    return recs


def read_jepx(path: Path):
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f)
        head = next(rd)
        col = {h: i for i, h in enumerate(head)}
        need = ["受渡日", "時刻コード", "システムプライス(円/kWh)"] + [f"エリアプライス{a}(円/kWh)" for a in AREAS]
        missing = [c for c in need if c not in col]
        if missing:
            sys.exit(f"JEPX の列が見つからない: {missing}")
        for r in rd:
            if not r or not r[0].strip():
                continue
            rows.append({
                "date": r[col["受渡日"]],
                "slot": int(r[col["時刻コード"]]),
                "sys": float(r[col["システムプライス(円/kWh)"]]),
                **{a: float(r[col[f"エリアプライス{a}(円/kWh)"]]) for a in AREAS},
            })
    return rows


def fy_bounds(rows, fy: int):
    start, end = dt.date(fy, 4, 1), dt.date(fy + 1, 3, 31)
    keep = [r for r in rows if start <= dt.datetime.strptime(r["date"], "%Y/%m/%d").date() <= end]
    days = {r["date"] for r in keep}
    return keep, start, end, len(days)


def split_stats(rows, a: str, b: str) -> dict:
    """隣り合うエリア a・b のエリアプライスが違った 30 分の割合。違う向きも数える。"""
    n = len(rows)
    a_hi = sum(1 for r in rows if r[a] - r[b] > 0.005)
    b_hi = sum(1 for r in rows if r[b] - r[a] > 0.005)
    diffs = [abs(r[a] - r[b]) for r in rows if abs(r[a] - r[b]) > 0.005]
    return {
        "areas": [a, b], "n_slots": n,
        "split_share": round((a_hi + b_hi) / n, 4) if n else None,
        "share_a_higher": round(a_hi / n, 4) if n else None,
        "share_b_higher": round(b_hi / n, 4) if n else None,
        "mean_abs_diff_when_split_yen": round(statistics.fmean(diffs), 2) if diffs else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--jepx", type=Path, help="JEPX spot_summary_<年度>.csv(無ければ価格の項目は作らない)")
    ap.add_argument("--fy", type=int, default=2025, help="集計する年度(4 月〜翌 3 月)")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    caps = capacity_records()
    yloc = yaml_locations()
    want_built = {name for L in LINKS for kind, name in L["sites"] if kind == "built"}
    bloc = built_locations(want_built)

    jepx_rows, jepx_meta = None, None
    if args.jepx:
        all_rows = read_jepx(args.jepx)
        jepx_rows, start, end, n_days = fy_bounds(all_rows, args.fy)
        jepx_meta = {
            "file": args.jepx.name, "sha256": sha256(args.jepx),
            "fiscal_year": args.fy, "from": start.isoformat(), "to": end.isoformat(),
            "n_days": n_days, "n_slots": len(jepx_rows),
        }
        if n_days < 365:
            print(f"注意: {args.fy} 年度は {n_days} 日分しかない(年度の途中のファイル)", file=sys.stderr)

    links = []
    for L in LINKS:
        pts = []
        for kind, name in L["sites"]:
            p = (yloc if kind == "yaml" else bloc).get(name)
            if p is None:
                sys.exit(f"位置が見つからない: {kind}:{name}")
            pts.append({"name": name, "lat": p[0], "lon": p[1]})
        lat = round(sum(p["lat"] for p in pts) / len(pts), 5)
        lon = round(sum(p["lon"] for p in pts) / len(pts), 5)
        occ = []
        for oname in L["occto"]:
            rec = {}
            for d, key in (("順方向", "fwd"), ("逆方向", "rev")):
                r = caps.get((oname, d))
                if r is None:
                    sys.exit(f"OCCTO の記録が無い: {oname} {d}")
                rec[key] = {"max_mw": r["max_mw"], "median_mw": r["median_mw"], "min_mw": r["min_mw"],
                            "observations": r["observations"]}
            rec["name"] = oname
            rec["source_url"] = caps[(oname, "順方向")]["source_url"]
            rec["source_title"] = caps[(oname, "順方向")]["source_title"]
            rec["retrieved_at"] = caps[(oname, "順方向")]["retrieved_at"]
            occ.append(rec)
        item = {
            "id": L["id"], "name": L["name"], "kind": L["kind"],
            "fwd": list(L["fwd"]), "rev": [L["fwd"][1], L["fwd"][0]],
            "lat": lat, "lon": lon, "sites": pts, "site_note": L["site_note"],
            "occto": occ,
        }
        if L.get("cap_note"):
            item["cap_note"] = L["cap_note"]
        if jepx_rows is not None:
            item["jepx_split"] = split_stats(jepx_rows, L["fwd"][0], L["fwd"][1])
        links.append(item)

    args.out.mkdir(parents=True, exist_ok=True)
    built_sha = sha256(BUILT)
    ic_out = {
        "_meta": {
            "made_by": "scripts/build_viewer_overlays.py",
            "made_at": dt.date.today().isoformat(),
            "layer": "observed(公表値とその集計)",
            "capacity_source": "OCCTO 系統情報公表 連系線関連情報(種別04・30 分値)。期間最大・中央値は AGJ が集計(加工)",
            "capacity_terms": "OCCTO: 出典を記載すれば自由に利用可。編集・加工したときはその旨を記載(https://www.occto.or.jp/chosakuken.html)",
            "capacity_jsonl_sha256": sha256(CAP_JSONL),
            "market_source": "JEPX スポット市場 取引結果(エリアプライス)。値差の割合は AGJ が年度で集計(加工)" if jepx_meta else None,
            "market_terms": "JEPX: 出所を明示した上で利用(https://www.jepx.jp/disclaimer/)" if jepx_meta else None,
            "jepx": jepx_meta,
            "positions": "印の位置は目印で経路ではない。built の変電所座標と interconnections.yaml の変換所の位置の平均",
            "built_sha256": built_sha,
            "not_drawn": "中部フェンス・北陸フェンス・関西フェンス(複数の連系線を合わせた断面)は 1 か所に置けないので描かない",
        },
        "links": links,
    }
    (args.out / "interconnectors.json").write_text(json.dumps(ic_out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"interconnectors.json: {len(links)} 本")

    if jepx_rows is not None:
        areas = []
        for a in AREAS:
            v = [r[a] for r in jepx_rows]
            areas.append({"area": a, "mean_yen": round(statistics.fmean(v), 2),
                          "median_yen": round(statistics.median(v), 2)})
        sysv = [r["sys"] for r in jepx_rows]
        ap_out = {
            "_meta": {
                "made_by": "scripts/build_viewer_overlays.py",
                "made_at": dt.date.today().isoformat(),
                "layer": "observed の集計(公表の 30 分値の年度平均・中央値。生の 30 分値は入れない)",
                "source": "JEPX スポット市場 取引結果(https://www.jepx.jp/electricpower/market-data/spot/)",
                "terms": "JEPX: 出所を明示した上で利用(https://www.jepx.jp/disclaimer/)。年度で集計したのは AGJ(加工)",
                "unit": "円/kWh",
                "jepx": jepx_meta,
                "system_price_mean_yen": round(statistics.fmean(sysv), 2),
                "system_price_median_yen": round(statistics.median(sysv), 2),
            },
            "areas": areas,
        }
        (args.out / "area_prices.json").write_text(json.dumps(ap_out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"area_prices.json: {len(areas)} エリア / {jepx_meta['n_days']} 日 / {jepx_meta['n_slots']} コマ")
        for a in areas:
            print(f"  {a['area']}: 平均 {a['mean_yen']} / 中央値 {a['median_yen']} 円/kWh")
        for L in links:
            s = L["jepx_split"]
            print(f"  {L['name']}: 値差 {100 * s['split_share']:.1f}% ({s['areas'][0]}高 {100 * s['share_a_higher']:.1f}% / "
                  f"{s['areas'][1]}高 {100 * s['share_b_higher']:.1f}%)")


if __name__ == "__main__":
    main()
