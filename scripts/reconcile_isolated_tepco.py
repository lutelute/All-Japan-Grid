#!/usr/bin/env python3
"""監査の東京「孤立変電所(A=繋ぐべき)」を、TEPCOの公表接続で突合する。

連結性監査(scripts/build_connectivity_audit.py + classify_isolated_subs.py)が出した
「本系統に載らない変電所のうち A=繋ぐべき」を、**TEPCO潮流実績CSVの列名から取れる
接続事実(変電所×線路)**に当てて、「TEPCOはこの孤立変電所が どの線で どの本系統
変電所に繋がっていると言っているか」を機械的に回収する。無理に近接で繋ぐのではなく、
**独立一次源(法定の系統情報公表)の接続事実**で繋ぐための候補出し。

TEPCO CSVは転載禁止(data/external/tepco/・gitignore)。ここで扱うのは私的検証で、
出力する docs/reports/*.json は**接続事実(どの変電所とどの変電所が同じ線に載るか)という
派生の位置情報のみ**で、生の潮流値・CSVは載せない。([[reference_utility_data_licensing]])

使い方: python scripts/reconcile_isolated_tepco.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.validation.external_tepco import parse_tepco_headers_banded  # noqa: E402

VIZ = ROOT / "data" / "external" / "system_disclosure" / "viz"
TEP = ROOT / "data" / "external" / "tepco"
OUT = ROOT / "docs" / "reports" / "isolated_tepco_reconcile.json"

_STRIP = re.compile(r"(変電所|開閉所|発電所|変電|開閉|\(変\)|\(開\)|\(開閉所\))")
_TAIL = re.compile(r"[_\s　]*\d+(\.\d+)?kV$|_\d+$")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = _TAIL.sub("", s)
    s = _STRIP.sub("", s)
    s = re.sub(r"[\s　]", "", s)
    return s


def main() -> int:
    nf = VIZ / "audit_nodes.geojson"
    if not nf.exists():
        print("audit_nodes.geojson が無い。先に build_connectivity_audit.py を実行")
        return 1
    feats = json.loads(nf.read_text(encoding="utf-8"))["features"]

    # 本系統の変電所名(=繋ぎ先候補) と 東京の孤立A変電所
    main_subs = {}   # norm名 -> 代表名
    for f in feats:
        p = f["properties"]
        if p.get("cls") == "main" and p.get("sub") and p.get("name"):
            main_subs.setdefault(norm(p["name"]), p["name"])
    iso_a = [f["properties"] for f in feats
             if f["properties"].get("cls") == "isolated_sub"
             and f["properties"].get("verdict") == "A"
             and f["properties"].get("region") == "tokyo"]

    # TEPCO 接続事実: line -> {sub, ...}
    truth = parse_tepco_headers_banded(
        csv_path=str(TEP / "jisseki_kikan.csv"),
        csv154=str(TEP / "jisseki_154kV*.csv"),
        csv66=[str(TEP / "jisseki_tokyo_23_*.csv"), str(TEP / "jisseki_tokyo_tama*.csv"),
               str(TEP / "jisseki_chiba*.csv"), str(TEP / "jisseki_saitama*.csv"),
               str(TEP / "jisseki_gunma*.csv"), str(TEP / "jisseki_tochigi*.csv"),
               str(TEP / "jisseki_ibaraki*.csv"), str(TEP / "jisseki_kanagawa*.csv"),
               str(TEP / "jisseki_yamanasi*.csv")])
    line_subs = defaultdict(set)   # line -> set(TEPCO sub raw)
    tep_sub_norm = {}              # norm -> raw
    for (sub, line), floor in truth["pairs"].items():
        line_subs[line].add(sub)
        tep_sub_norm.setdefault(norm(sub), sub)

    # 各孤立A変電所を TEPCO subに突合 → 同じ線の相手変電所を分類
    resolved, partial, notfound = [], [], []
    for p in iso_a:
        nm = p.get("name") or ""
        key = norm(nm)
        tep = tep_sub_norm.get(key)
        if not tep:
            notfound.append({"name": nm, "kv": p.get("kv"), "reason": "TEPCO列に該当変電所名なし"})
            continue
        # この変電所が載る線と、その線の相手変電所
        conns = []
        for line, subs in line_subs.items():
            if tep not in subs:
                continue
            for other in subs:
                if other == tep:
                    continue
                on = norm(other)
                tgt = main_subs.get(on)
                conns.append({"line": line, "other": other,
                              "other_in_main": bool(tgt), "target_main": tgt})
        main_targets = sorted({c["target_main"] for c in conns if c["other_in_main"]})
        rec = {"name": nm, "kv": p.get("kv"), "tepco_sub": tep,
               "lines": sorted({c["line"] for c in conns}),
               "connects_to_main": main_targets,
               "all_neighbors": sorted({c["other"] for c in conns})}
        if main_targets:
            resolved.append(rec)
        elif conns:
            partial.append(rec)   # 線はあるが相手が本系統に居ない(相手も孤立)
        else:
            notfound.append({"name": nm, "kv": p.get("kv"),
                             "reason": "TEPCOに変電所名はあるが接続線が取れない"})

    print(f"東京の孤立A変電所 {len(iso_a)} 件をTEPCO公表接続に突合:")
    print(f"  ★解決 {len(resolved)}: TEPCOが本系統変電所への接続線を明示")
    print(f"  △部分 {len(partial)}: 接続線はあるが相手も本系統外(連鎖で解ける可能性)")
    print(f"  ×不明 {len(notfound)}: TEPCO列に無い/接続線取れず")
    print("\n--- ★解決した接続(孤立変電所 → 線 → 本系統変電所) ---")
    for r in sorted(resolved, key=lambda x: -(x["kv"] or 0)):
        tgt = "、".join(r["connects_to_main"][:3])
        ln = "、".join(r["lines"][:2])
        print(f"  {r['kv']:>5.0f}kV {r['name']:<16} →[{ln}]→ {tgt}")

    OUT.write_text(json.dumps({
        "note": ("東京の孤立A変電所をTEPCO公表接続(法定・系統情報公表)で突合。"
                 "生CSV・潮流値は非収録(転載禁止)。ここは接続事実の派生のみ。"),
        "source": "TEPCO PG 潮流実績CSV 列名 (jisseki_kikan/154kV/県別) の変電所×線路",
        "n_isolated_A_tokyo": len(iso_a),
        "n_resolved": len(resolved), "n_partial": len(partial), "n_notfound": len(notfound),
        "resolved": resolved, "partial": partial, "notfound": notfound,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n保存: {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
