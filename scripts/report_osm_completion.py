#!/usr/bin/env python3
"""鉄塔・番号・回線数の補完の前と後を地域ごとに比べる報告を書く(2026-11-07)。

    PYTHONPATH=. python scripts/report_osm_completion.py \\
        --before <取り直す前の docs/data/osm_routes/meta.json> --after docs/data/osm_routes/meta.json \\
        --out docs/reports/osm_completion_2026-11-07.md

meta.json の completion(scripts/export_osm_routes.py が書く)を使う。あわせて
  - 地図の線(正典の枝)の回線数と、OSM の回線数が食い違う線の一覧(OSM と正典の値だけ。公表値は出さない)
  - 電力会社の公表の回線数(data/reference/circuit_counts.jsonl)との一致率(集計だけ。NOTICE のとおり値は出さない)
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGIONS = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku", "kansai", "chugoku", "shikoku", "kyushu", "okinawa"]
JA = {"hokkaido": "北海道", "tohoku": "東北", "tokyo": "東京", "chubu": "中部", "hokuriku": "北陸", "kansai": "関西",
      "chugoku": "中国", "shikoku": "四国", "kyushu": "九州", "okinawa": "沖縄"}


def n(x):
    return f"{x:,}"


def pct(a, b):
    return f"{100.0 * a / b:.0f}%" if b else "—"


def single_int(v):
    v = str(v or "").strip()
    return int(v) if re.fullmatch(r"\d+", v) else None


def cir_est(p):
    cab = single_int(p.get("_cab"))
    if cab is None:
        return None
    if str(p.get("_freq") or "").strip() == "0":
        return cab // 2 if cab >= 2 else None
    return cab // 3 if cab >= 3 and cab % 3 == 0 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    b = json.load(open(args.before, encoding="utf-8"))
    a = json.load(open(args.after, encoding="utf-8"))
    cb, ca = b["completion"], a["completion"]
    L = ["# 鉄塔・番号・回線数の補完 — 前と後（2026-11-07）\n"]
    L.append(f"前: OSM {b['source']['osm_base_max'][:10]} 取得（{b['source']['files']} ファイル）。"
             f"後: OSM {a['source']['osm_base_max'][:10]} 取得（{a['source']['files']} ファイル、`scripts/fetch_osm_power.py`。"
             f"送電線・鉄塔と route=power の relation {a.get('relations', 0):,} 本を、タグを全部付けて取り直した）。"
             "数えたのは `scripts/export_osm_routes.py`（docs/OSM_ROUTES.md）。\n")
    L.append("推定で埋めたものは、地図のカードで必ず「推定」と書き、本物の番号・回線数に見せない。\n")
    L.append("- 番号の推定: 同じ線の上で前後に番号のある鉄塔があり、間の基数が番号の差と合うときだけ埋める。"
             "路線によって違う番号になる鉄塔（併架など）は埋めない")
    L.append("- 「〇〇線の n 基目」: 番号も推定も無い鉄塔で、路線が一筆書きにたどれるときだけ、北の端から数えた順を出す（OSM に番号なしと明記）")
    L.append("- 線の折れ点: 架空線の途中の点で鉄塔のタグが無いもの。鉄塔の位置であることが多いので、別の印（推定）で出す")
    L.append("- 回線数の推定: OSM に回線数の無い線で、交流は導体数 ÷ 3（3 の倍数のときだけ）、直流は導体数 ÷ 2、"
             "それも無ければこの線を通る route=power の relation の数\n")

    def tower_table(title, c):
        L.append(f"### {title}\n")
        L.append("| 地域 | 鉄塔 | 番号か名前（OSM） | 番号（推定） | n 基目だけ（推定） | どれも無い | 線の折れ点（推定の鉄塔） |")
        L.append("|---|---:|---:|---:|---:|---:|---:|")
        tot = collections.Counter()
        for r in REGIONS:
            x = c.get(r, {})
            tot.update(x)
            L.append(f"| {JA[r]} | {n(x.get('towers', 0))} | {n(x.get('ref_or_name_osm', 0))}（{pct(x.get('ref_or_name_osm', 0), x.get('towers', 0))}） | "
                     f"{n(x.get('ref_est', 0))} | {n(x.get('ordinal_only', 0))} | {n(x.get('nothing', 0))} | {n(x.get('bends', 0))} |")
        L.append(f"| **計** | **{n(tot['towers'])}** | **{n(tot['ref_or_name_osm'])}**（{pct(tot['ref_or_name_osm'], tot['towers'])}） | "
                 f"**{n(tot['ref_est'])}** | **{n(tot['ordinal_only'])}** | **{n(tot['nothing'])}** | **{n(tot['bends'])}** |\n")
        return tot

    def line_table(title, c):
        L.append(f"### {title}\n")
        L.append("| 地域 | OSM の線（line・cable） | 回線数あり（OSM） | 推定（導体数 ÷ 3） | 推定（直流） | 推定（route=power） | 不明 |")
        L.append("|---|---:|---:|---:|---:|---:|---:|")
        tot = collections.Counter()
        for r in REGIONS:
            x = c.get(r, {})
            tot.update(x)
            L.append(f"| {JA[r]} | {n(x.get('lines', 0))} | {n(x.get('cir_osm', 0))}（{pct(x.get('cir_osm', 0), x.get('lines', 0))}） | "
                     f"{n(x.get('cir_est_cables', 0))} | {n(x.get('cir_est_cables_dc', 0))} | {n(x.get('cir_est_relations', 0))} | {n(x.get('cir_none', 0))} |")
        L.append(f"| **計** | **{n(tot['lines'])}** | **{n(tot['cir_osm'])}**（{pct(tot['cir_osm'], tot['lines'])}） | **{n(tot['cir_est_cables'])}** | "
                 f"**{n(tot['cir_est_cables_dc'])}** | **{n(tot['cir_est_relations'])}** | **{n(tot['cir_none'])}** |\n")
        return tot

    L.append("## 鉄塔\n")
    tb = tower_table("前（取り直す前）", cb)
    ta = tower_table("後（取り直し・補完のあと）", ca)
    L.append(f"鉄塔は {n(tb['towers'])} → {n(ta['towers'])} 基（{ta['towers'] - tb['towers']:+,}）。"
             f"番号か名前のある鉄塔は OSM で {n(tb['ref_or_name_osm'])} → {n(ta['ref_or_name_osm'])}、推定の番号 {n(ta['ref_est'])}、"
             f"n 基目だけ {n(ta['ordinal_only'])}。番号・名前・推定・n 基目のどれも無いのは {n(tb['nothing'])} → {n(ta['nothing'])}。\n")
    L.append("## 回線数（OSM の線）\n")
    lb = line_table("前", cb)
    la = line_table("後", ca)
    est_b = lb["cir_est_cables"] + lb["cir_est_cables_dc"] + lb["cir_est_relations"]
    est_a = la["cir_est_cables"] + la["cir_est_cables_dc"] + la["cir_est_relations"]
    L.append(f"回線数のある線は OSM で {n(lb['cir_osm'])} → {n(la['cir_osm'])}、推定 {n(est_b)} → {n(est_a)}。"
             f"どちらも無いのは {n(lb['cir_none'])} → {n(la['cir_none'])}。\n")

    # ── 地図の線(正典の枝): 正典の回線数と OSM の回線数 ──
    feats = json.load(open(os.path.join(ROOT, "docs", "data", "map", "lines_all.geojson"), encoding="utf-8"))["features"]
    cnt = collections.Counter()
    mism = []
    for f in feats:
        p = f["properties"]
        osm = single_int(p.get("_cir"))
        par = p.get("_par")
        if p.get("_cir"):
            cnt["osm"] += 1
        elif cir_est(p):
            cnt["est"] += 1
        else:
            cnt["none"] += 1
        if osm is not None and par and osm != par:
            mism.append((p.get("_region") or "", -(p.get("_voltage_kv") or 0), p.get("_display_name") or "", osm, par, (p.get("_osm") or [None])[0]))
    L.append("## 地図の線（正典の枝）の回線数\n")
    L.append(f"地図の線 {n(len(feats))} 本のうち、回線数が OSM にある {n(cnt['osm'])} 本・導体数からの推定 {n(cnt['est'])} 本・不明 {n(cnt['none'])} 本。\n")
    L.append(f"### 正典の回線数（計算に使う値）と OSM の回線数が食い違う線: {n(len(mism))} 本\n")
    L.append("OSM の回線数が 1 つの値の線だけを比べた。正典の回線数は台帳・公表値・推定から決めていて（docs/MODEL_INTERVENTIONS.md）、"
             "どちらが正しいかはこの表だけでは決めない。2 回線の線を正典で 1 回線にしている所は、潮流の重さに効く。\n")
    by = collections.Counter((m[3], m[4]) for m in mism)
    L.append("組み合わせ（OSM → 正典）: " + "・".join(f"{o} → {q} 回線 {c} 本" for (o, q), c in by.most_common(8)) + "\n")
    L.append("| 地域 | 電圧 | 線 | OSM の回線数 | 正典の回線数 | OSM |")
    L.append("|---|---:|---|---:|---:|---|")
    for reg, kv, name, osm, par, way in sorted(mism):
        L.append(f"| {JA.get(reg, reg)} | {-kv:g} kV | {name or '名前なし'} | {osm} | {par} | "
                 + (f"[way {way}](https://www.openstreetmap.org/way/{way})" if way else "—") + " |")
    L.append("")

    # ── 公表値との一致率(集計だけ) ──
    pub = {}
    path = os.path.join(ROOT, "data", "reference", "circuit_counts.jsonl")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            if r.get("source_type") != "official" or not r.get("n_circuits"):
                continue
            for nm in r.get("model_edge_names") or []:
                pub.setdefault((r.get("region"), nm), r["n_circuits"])
    agree = collections.Counter()
    for f in feats:
        p = f["properties"]
        k = (p.get("_region"), p.get("_display_name"))
        if k not in pub:
            continue
        v = pub[k]
        agree["matched"] += 1
        osm = single_int(p.get("_cir"))
        if osm is not None:
            agree["osm_n"] += 1
            agree["osm_ok"] += osm == v
        e = None if p.get("_cir") else cir_est(p)
        if e is not None:
            agree["est_n"] += 1
            agree["est_ok"] += e == v
        if p.get("_par"):
            agree["par_n"] += 1
            agree["par_ok"] += p["_par"] == v
    L.append("## 電力会社の公表の回線数との一致（集計だけ）\n")
    L.append("公表値（`data/reference/circuit_counts.jsonl`、各社の系統情報の公表）は検証にだけ使い、ここには一致の割合だけを書く"
             "（線ごとの公表値は載せない。NOTICE・docs/VALIDATION_SOURCES.md）。地図の線の名前と地域で突き合わせた。\n")
    L.append("| 比べたもの | 比べた線 | 一致 | 一致率 |")
    L.append("|---|---:|---:|---:|")
    L.append(f"| OSM の回線数 | {n(agree['osm_n'])} | {n(agree['osm_ok'])} | {pct(agree['osm_ok'], agree['osm_n'])} |")
    L.append(f"| 推定の回線数（導体数 ÷ 3 など） | {n(agree['est_n'])} | {n(agree['est_ok'])} | {pct(agree['est_ok'], agree['est_n'])} |")
    L.append(f"| 正典の回線数 | {n(agree['par_n'])} | {n(agree['par_ok'])} | {pct(agree['par_ok'], agree['par_n'])} |")
    L.append(f"\n公表値と名前で突き合わせられた地図の線は {n(agree['matched'])} 本。名前だけで突き合わせているので、"
             "同じ名前で区間によって回線数の違う線（途中で 1 回線になる線など）は、正しくても不一致に数えている。"
             "一致率は目安で、どの線が違うかは公表値を見て線ごとに確かめる（その結果も値は載せない）。\n")
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print(f"鉄塔 {tb['towers']:,} → {ta['towers']:,}・番号/名前(OSM) {tb['ref_or_name_osm']:,} → {ta['ref_or_name_osm']:,}・推定番号 {ta['ref_est']:,}・"
          f"n 基目 {ta['ordinal_only']:,}・回線数(OSM) {lb['cir_osm']:,} → {la['cir_osm']:,}・推定 {est_b:,} → {est_a:,}・"
          f"食い違い {len(mism)}・公表との一致 OSM {pct(agree['osm_ok'], agree['osm_n'])} 推定 {pct(agree['est_ok'], agree['est_n'])} 正典 {pct(agree['par_ok'], agree['par_n'])}")


if __name__ == "__main__":
    main()
