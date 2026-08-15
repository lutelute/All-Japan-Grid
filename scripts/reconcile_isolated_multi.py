#!/usr/bin/env python3
"""東京でやった「孤立変電所×TEPCO公表接続の突合」を **関西・北海道・東北** に横展開する。

参考実装 scripts/reconcile_isolated_tepco.py は TEPCO 潮流CSVの独自列名
(`京浜(変) - 東京南線1･2L`)専用だった。他社は様式が違うので、from-to 接続事実の
**共通プール**を社差を吸収して作り、監査の孤立A変電所を本系統変電所へ突合する。

社差を吸収する from-to 源(いずれも法定「系統情報の公表」由来 or その正規化物):
  1. 様式5インピーダンスの「区間」列 = from-to 変電所ペア（最も直接的なトポロジ源）
     → 既に normalized/impedance_lines.csv の from_node/to_node に落ちている（7社）
  2. 潮流実績CSVの「潮流正方向」= `A変電所→B変電所`（関西・北海道の kikan で直接取れる）
     → scripts.build_line_observations.read_flow() が社差(ヘッダ行数・ラベルゆれ)を吸収
  3. 既構築の観測フロー viz/flow_lines.geojson の from/to（補助・6社ぶんの確定ペア）

これらを (from, to, line, kv, utility, src) の接続事実プールに畳み、孤立A変電所名を
プール端点に正規化突合 → 同じ線の相手端が本系統変電所なら「解決」。

ライセンス（[[reference_utility_data_licensing]]）: 生CSV/xlsxの中身（潮流値・R/X等）は
**出力・レポートに一切載せない**。ここで扱い・保存するのは接続事実（どの変電所がどの線で
どの変電所に載るか）という派生の位置情報のみ。名前正規化は TEPCO 版を流用（NFKC＋
変電所/開閉所/(変)除去）。

使い方:
    python scripts/reconcile_isolated_multi.py
    python scripts/reconcile_isolated_multi.py --regions kansai,hokkaido,tohoku
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 潮流実績CSVの社差（ヘッダ行数・ラベルゆれ・東京独自形式）はここが吸収済み。再実装しない。
from scripts.build_line_observations import read_flow  # noqa: E402

SD = ROOT / "data" / "external" / "system_disclosure"
VIZ = SD / "viz"
NORM = SD / "normalized"
OUT = ROOT / "docs" / "reports" / "isolated_multi_reconcile.json"

DEFAULT_REGIONS = ["kansai", "hokkaido", "tohoku"]

# 監査で「繋ぐべき(A)」と判定された、本タスクの名指しターゲット。
# (region, 名前の部分一致, 期待電圧kV, おおよその座標[lon,lat]) — 解決可否を個別に報告する。
TARGETS = [
    {"key": "由良開閉所", "region": "kansai", "kv": 500.0, "lonlat": (135.0892, 33.9769),
     "label": "関西 500kV 由良開閉所"},
    {"key": "上ノ国町変電所", "region": "hokkaido", "kv": 187.0, "lonlat": (140.1264, 41.7394),
     "label": "北海道 187kV 上ノ国町変電所"},
    {"key": "大間町変電所", "region": "tohoku", "kv": None, "lonlat": (140.8900, 41.4652),
     "label": "東北 大間町変電所（J-POWER 大間幹線）"},
]

# --- 名前正規化: TEPCO 版(reconcile_isolated_tepco.py)をそのまま流用 ---
_STRIP = re.compile(r"(変電所|開閉所|発電所|変電|開閉|\(変\)|\(開\)|\(開閉所\))")
_TAIL = re.compile(r"[_\s　]*\d+(\.\d+)?kV$|_\d+$")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = _TAIL.sub("", s)
    s = _STRIP.sub("", s)
    s = re.sub(r"[\s　]", "", s)
    return s


# `12T（西京都向町線）` `19T（南京都新八幡線）` = 変圧器バンク端点。線路名(#123)や空欄も端点でない。
_NOT_A_SUB = re.compile(r"^[0-9０-９]+\s*[TＴ][（(]|（#\d+）|\(#\d+\)")


def _endpoint_ok(name: str) -> bool:
    """変電所端点として使える名前か（変圧器バンク・線路継続点・空欄・匿名『発電所』は除外）。"""
    s = str(name or "").strip()
    if not s or s.lower() == "nan":
        return False
    if _NOT_A_SUB.search(s):
        return False
    return bool(norm(s))          # 『発電所』単体は norm 後に空 → 端点にしない


# ---------------------------------------------------------------------------
# from-to 接続事実プールの構築（社差を吸収）
# ---------------------------------------------------------------------------
def _latest_per_family(paths: list[Path]) -> list[Path]:
    """同一系統区分の年違いファイルは最新年だけ採る（from-toは年で変わらない）。

    族キーは **社ディレクトリ込み**。ファイル名だけだと jisseki_kikan01_line が
    東北と北陸で衝突し、年の新しい社が他社のファイルを丸ごと食う（実際に東北の
    解決4件が消えた）。
    """
    best: dict[str, tuple[str, Path]] = {}
    for p in paths:
        m = re.search(r"_(\d{4})_\d{2}\.csv$", p.name)
        year = m.group(1) if m else "0000"
        fam = str(p.parent) + "/" + re.sub(r"_\d{4}_\d{2}\.csv$", "", p.name)
        if fam not in best or year > best[fam][0]:
            best[fam] = (year, p)
    return [v[1] for v in best.values()]


def build_pool(regions: set[str]) -> tuple[list[dict], dict]:
    """(from, to, line, kv, utility, src) の接続事実プールと、社別カバレッジ内訳を返す。"""
    pool: list[dict] = []
    provenance = defaultdict(lambda: defaultdict(int))   # utility -> src -> n

    def add(util, frm, to, line, kv, src):
        if util not in regions:
            return
        # 東北kikan01等は名前が Excel引用符 `'中仙台変電所` で来る — 剥がす
        frm = str(frm or "").strip().lstrip("'’")
        to = str(to or "").strip().lstrip("'’")
        line = str(line or "").strip().lstrip("'’")
        if not (_endpoint_ok(frm) and _endpoint_ok(to)):
            return
        if norm(frm) == norm(to):
            return
        pool.append({"utility": util, "from": frm, "to": to,
                     "line": (line if line and line != "nan" else None),
                     "kv": kv, "src": src})
        provenance[util][src] += 1

    # 1) 様式5インピーダンス「区間」 = from-to（normalized 済み・7社）
    imp_csv = NORM / "impedance_lines.csv"
    if imp_csv.exists():
        imp = pd.read_csv(imp_csv)
        for _, r in imp.iterrows():
            add(r.get("utility"), r.get("from_node"), r.get("to_node"),
                r.get("name"), r.get("voltage_kv"), "impedance_section")

    # 2) 潮流実績CSV「潮流正方向」= A→B（read_flow が社差を吸収）
    flow_paths = []
    for util in regions:
        flow_paths += sorted((SD / util).glob("flow_actual/**/jisseki_*_line_*.csv"))
        flow_paths += sorted((SD / util).glob("flow_actual/jisseki_*_line_*.csv"))
    for path in _latest_per_family(sorted(set(flow_paths))):
        util = path.relative_to(SD).parts[0]
        try:
            meta, _ = read_flow(path)
        except Exception as exc:  # noqa: BLE001
            print(f"! 潮流CSV読めず {path.name}: {exc}")
            continue
        for _, m in meta.iterrows():
            add(util, m.get("flow_positive_from"), m.get("flow_positive_to"),
                m.get("name"), m.get("voltage_kv"), "flow_direction")

    # 2b) TEPCO 予想潮流CSV（系統構成マッピング付属・エリア別）:
    # 送電線行に from,→,to が**実名の別列**で入る（潮流実績CSVは相手端非公開だったが
    # こちらは両端公表）。csv_yosochoryu_{pref}_soudensen.csv (utf-8-sig・ヘッダ7行)。
    if "tokyo" in regions:
        for path in sorted((SD / "tokyo" / "yosochoryu_csv").glob("*/csv_yosochoryu_*_soudensen.csv")):
            txt = None
            for enc in ("utf-8-sig", "cp932"):   # 県によりUTF-8(BOM)とcp932が混在
                try:
                    txt = path.read_text(encoding=enc)
                    break
                except Exception:  # noqa: BLE001
                    continue
            if txt is None:
                print(f"! 予想潮流CSV読めず {path.name}")
                continue
            import csv as _csv
            for row in _csv.reader(txt.splitlines()):
                if len(row) < 11 or "→" not in (row[8] if len(row) > 8 else ""):
                    continue
                name, kv = row[1], row[2]
                frm, to = row[7], row[9]
                try:
                    kvf = float(kv)
                except Exception:  # noqa: BLE001
                    kvf = None
                add("tokyo", frm, to, name, kvf, "yosochoryu")

    # 3) 既構築の観測フロー geojson の from/to（補助）
    gj = VIZ / "flow_lines.geojson"
    if gj.exists():
        for f in json.loads(gj.read_text(encoding="utf-8"))["features"]:
            p = f["properties"]
            add(p.get("utility"), p.get("from"), p.get("to"),
                p.get("line"), p.get("kv"), "flow_lines_geojson")

    coverage = {}
    for util in sorted(regions):
        eps = {norm(x["from"]) for x in pool if x["utility"] == util}
        eps |= {norm(x["to"]) for x in pool if x["utility"] == util}
        coverage[util] = {"connections": sum(1 for x in pool if x["utility"] == util),
                          "distinct_endpoints": len(eps),
                          "by_source": dict(provenance[util])}
    return pool, coverage


# ---------------------------------------------------------------------------
# 突合
# ---------------------------------------------------------------------------
def reconcile(pool: list[dict], main_norm: dict, iso_by_region: dict) -> dict:
    # プール端点 -> それに触れる接続（同じ社に限定して他端を見る）
    ep_index: dict[tuple[str, str], list[tuple[str, dict]]] = defaultdict(list)
    pool_n_by_region: dict[str, int] = defaultdict(int)
    for x in pool:
        ep_index[(x["utility"], norm(x["from"]))].append(("to", x))
        ep_index[(x["utility"], norm(x["to"]))].append(("from", x))
        pool_n_by_region[x["utility"]] += 1

    results = {}
    for region, isos in iso_by_region.items():
        # 未突合の理由は region の from-to 源が空か否かで分ける（東北=データ未取得と、
        # 関西/北海道=基幹系のみ開示で局所系が無い、は原因が違う）。
        empty_reason = ("系統情報の公表データ未取得（当該regionの from-to 源が空）"
                        if pool_n_by_region.get(region, 0) == 0
                        else "公表 from-to に該当変電所名なし（当該社の開示は基幹系に限られる）")
        resolved, partial, notfound = [], [], []
        for p in isos:
            nm = p.get("name") or ""
            key = norm(nm)
            recs = ep_index.get((region, key), [])
            if not recs:
                notfound.append({"name": nm, "kv": p.get("kv"), "reason": empty_reason})
                continue
            conns = []
            for side, x in recs:
                other = x["to"] if side == "to" else x["from"]
                if norm(other) == key:
                    continue
                tgt = main_norm.get(norm(other))
                conns.append({"line": x["line"], "kv": x["kv"], "src": x["src"],
                              "other": other, "other_in_main": bool(tgt), "target_main": tgt})
            main_targets = sorted({c["target_main"] for c in conns if c["other_in_main"]})
            rec = {"name": nm, "kv": p.get("kv"),
                   "lines": sorted({c["line"] for c in conns if c["line"]}),
                   "connects_to_main": main_targets,
                   "all_neighbors": sorted({c["other"] for c in conns}),
                   "sources": sorted({c["src"] for c in conns})}
            if main_targets:
                resolved.append(rec)
            elif conns:
                partial.append(rec)              # 線はあるが相手も本系統外（連鎖で解ける可能性）
            else:
                notfound.append({"name": nm, "kv": p.get("kv"),
                                 "reason": "公表に名はあるが有効な相手端が取れない"})
        results[region] = {"n_isolated_A": len(isos), "resolved": resolved,
                           "partial": partial, "notfound": notfound}
    return results


def _find_target_status(t: dict, results: dict, iso_by_region: dict) -> dict:
    """名指しターゲット1件の状況（監査に在るか・解決区分・理由）を返す。"""
    region = t["region"]
    isos = iso_by_region.get(region, [])
    hit = None
    for p in isos:
        if t["key"] in (p.get("name") or ""):
            hit = p
            break
    if hit is None:
        # 監査に無い＝当該regionにその孤立Aが存在しない（データ未取得 or 別region分類）
        return {"target": t["label"], "in_audit": False,
                "status": "no_audit_node",
                "note": "当該regionの孤立A監査ノードに該当なし"
                        + ("（東北は系統情報公表データ未取得）" if region == "tohoku" else "")}
    res = results.get(region, {})
    for bucket in ("resolved", "partial"):
        for r in res.get(bucket, []):
            if t["key"] in r["name"]:
                return {"target": t["label"], "in_audit": True, "status": bucket,
                        "name": r["name"], "connects_to_main": r.get("connects_to_main"),
                        "lines": r.get("lines")}
    for r in res.get("notfound", []):
        if t["key"] in r["name"]:
            return {"target": t["label"], "in_audit": True, "status": "notfound",
                    "name": r["name"], "reason": r.get("reason")}
    return {"target": t["label"], "in_audit": True, "status": "unknown"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--regions", default=",".join(DEFAULT_REGIONS),
                    help="対象region（カンマ区切り）。既定: kansai,hokkaido,tohoku")
    args = ap.parse_args()
    regions = {r.strip() for r in args.regions.split(",") if r.strip()}

    nf = VIZ / "audit_nodes.geojson"
    if not nf.exists():
        print("audit_nodes.geojson が無い。先に build_connectivity_audit.py を実行")
        return 1
    feats = json.loads(nf.read_text(encoding="utf-8"))["features"]

    main_norm = {}
    for f in feats:
        p = f["properties"]
        if p.get("cls") == "main" and p.get("sub") and p.get("name"):
            main_norm.setdefault(norm(p["name"]), p["name"])
    iso_by_region = {r: [] for r in regions}
    for f in feats:
        p = f["properties"]
        if (p.get("cls") == "isolated_sub" and p.get("verdict") == "A"
                and p.get("region") in regions):
            iso_by_region[p["region"]].append(p)

    pool, coverage = build_pool(regions)
    results = reconcile(pool, main_norm, iso_by_region)
    targets = [_find_target_status(t, results, iso_by_region) for t in TARGETS]

    # ---- stdout ----
    print(f"from-to 接続事実プール: {len(pool)} 本（社差吸収済み）")
    for util in sorted(coverage):
        c = coverage[util]
        print(f"  {util:<9} 接続{c['connections']:>4} 端点{c['distinct_endpoints']:>4}  {c['by_source']}")
    print("\n地域別 孤立A変電所の突合:")
    for region in sorted(results):
        r = results[region]
        print(f"  {region:<9} A={r['n_isolated_A']:>3}  "
              f"★解決{len(r['resolved']):>3}  △部分{len(r['partial']):>3}  ×不明{len(r['notfound']):>3}")
    any_res = False
    for region in sorted(results):
        for r in sorted(results[region]["resolved"], key=lambda x: -(x["kv"] or 0)):
            any_res = True
            tgt = "、".join(r["connects_to_main"][:3])
            ln = "、".join(r["lines"][:2]) or "?"
            print(f"    [{region}] {(r['kv'] or 0):>5.0f}kV {r['name']:<16} →[{ln}]→ {tgt}")
    if not any_res:
        print("    （解決0件: 対象社の公表は基幹系に限られ、孤立Aの多くは66/154/187kVの局所系）")

    print("\n名指しターゲットの状況:")
    for t in targets:
        line = f"  {t['target']}: {t['status']}"
        if t.get("connects_to_main"):
            line += " → " + "、".join(t["connects_to_main"][:3])
        elif t.get("reason"):
            line += f" — {t['reason']}"
        elif t.get("note"):
            line += f" — {t['note']}"
        print(line)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "note": ("東京の孤立A×TEPCO突合を関西・北海道・東北へ横展開。from-to は法定"
                 "「系統情報の公表」（様式5区間・潮流正方向）とその正規化物由来。"
                 "生CSV/xlsxの中身（潮流値・R/X等）は非収録、接続事実の派生のみ。"),
        "sources": ["normalized/impedance_lines.csv の from_node/to_node（様式5『区間』）",
                    "各社 潮流実績CSV『潮流正方向』（A変電所→B変電所）",
                    "viz/flow_lines.geojson の from/to（既構築の観測フロー・補助）"],
        "regions": sorted(regions),
        "pool_connections": len(pool),
        "disclosure_coverage": coverage,
        "targets": targets,
        "by_region": {r: {"n_isolated_A": results[r]["n_isolated_A"],
                          "n_resolved": len(results[r]["resolved"]),
                          "n_partial": len(results[r]["partial"]),
                          "n_notfound": len(results[r]["notfound"]),
                          "resolved": results[r]["resolved"],
                          "partial": results[r]["partial"],
                          "notfound": results[r]["notfound"]} for r in sorted(results)},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n保存: {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
