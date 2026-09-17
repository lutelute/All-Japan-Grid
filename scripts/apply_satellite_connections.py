#!/usr/bin/env python3
"""介入#36 — 衛星判読クラスの接続適用(1件ずつオーナー承認制).

根拠(①): docs/reports/satellite_photointerpretation_pilot_2026-08-20.md。
衛星写真(地理院シームレスフォト z17/z18)で送電回廊(鉄塔・導体・伐開帯)を
目視確認できた断片ギャップのみ、承認を得て接続する。第一波/第二波(OSM実線)と
違い**自動適用しない** — 本スクリプトの CONNECTIONS 表が承認台帳(②)を兼ね、
エントリ追加=オーナー承認の記録。status="approved" のみ適用し、
"hold" は理由つきで表示に留める。

無効化(③): recovery="satellite" マーカー。除去は当マーカーの枝を落とすだけ。

幾何は直線弦(衛星から鉄塔位置の座標トレースは未実施 — path先頭末尾=接続ノード)。
冪等: 既存ペアはskip。regen(STEPS)組込前提。

※報告書は衛星クラスを「介入#35」と仮番していたが、#35はノード衛生が先に
使用したため本介入は#36(2026-08-26)。

usage:
  PYTHONPATH=. python3 scripts/apply_satellite_connections.py           # 表示のみ
  PYTHONPATH=. python3 scripts/apply_satellite_connections.py --write   # 適用
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 承認台帳: 1エントリ=1接続。オーナー承認日・根拠図・判読所見を必ず記す。
CONNECTIONS = [
    {
        "id": "sat-001-ojiya66",
        "status": "approved",           # オーナー承認 2026-08-26(「進めて」)
        "island": "east", "kv": 66.0,
        "frag": (37.31093, 138.8236),   # 小千谷近郊断片の端(赤十字)
        "main": (37.30544, 138.82193),  # 本系統側junction(緑十字)
        "gap_km": 0.63,
        "evidence": ("z18_c3_ojiya66.png: 森上に導体(細い暗線)を直接視認・"
                     "断片端の伐開地に鉄塔2基・2回線ぶんの線条が本系統側の"
                     "施設方向へ連続。OSMに該当線なし(2km圏皆無)="
                     "衛星判読が唯一の証拠の第1号。66kV↔66kVでゲート適合"),
        "note": "OSM未記載の実在送電線=OSM貢献候補",
    },
    {
        "id": "sat-002-yuzawa",
        "status": "hold",               # 精査の結果保留 2026-08-26
        "island": "east", "kv": None,
        "frag": (36.92751, 138.81258),
        "main": (36.92354, 138.81998),  # 新湯沢変電所(275kV)
        "gap_km": 0.79,
        "evidence": ("z18_c4_yuzawa.png: ギャップ上に鉄塔視認・導体が新湯沢"
                     "方向へ連続(物理回廊は実在)"),
        "hold_reason": ("断片は全ノードkv=0(不明)で回廊は66kV系(土樽~越後湯沢線"
                        "66kV)に属する可能性が高いが、モデルの新湯沢変電所には"
                        "275kVバスしか無い(66kV側バス不存在)。275kV直結は電圧"
                        "整合ゲートが防いできた誤接続に相当。66kVバス+変圧器の"
                        "新設は証拠が無く捏造ゼロ原則に反するため、公表資料か"
                        "OSM精査で新湯沢の66kV設備の証拠が出るまで保留。"
                        "副産物: 新湯沢にchubu双子(143m)・275kV線のtokyo/chubu"
                        "二重抽出あり=lines側の衛生課題"),
    },
]


def k5(lat, lon):
    return (round(lat, 5), round(lon, 5))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    built = json.loads((ROOT / "docs/data/built/all.json").read_text())
    edges = built["edges"]
    existing = {frozenset((k5(*e["a"]), k5(*e["b"]))) for e in edges
                if e.get("a") and e.get("b")}

    applied = 0
    for c in CONNECTIONS:
        pair = frozenset((k5(*c["frag"]), k5(*c["main"])))
        if c["status"] != "approved":
            print(f"HOLD {c['id']}: {c.get('hold_reason', '')[:80]}…")
            continue
        if pair in existing:
            print(f"skip {c['id']}: 適用済み(冪等)")
            continue
        print(f"APPLY {c['id']}: gap={c['gap_km']}km kv={c['kv']}")
        if args.write:
            fa, ma = c["frag"], c["main"]
            edges.append({
                "a": [fa[0], fa[1]], "b": [ma[0], ma[1]], "main": True,
                "par": 1, "kv": float(c["kv"]),
                "name": f"衛星判読回収線 {c['id']}",
                "path": [[fa[0], fa[1]], [ma[0], ma[1]]],
                "disclosure": ("衛星判読(介入#36・オーナー承認制): "
                               f"{c['evidence']}"),
                "recovery": "satellite"})
            applied += 1

    if args.write and applied:
        (ROOT / "docs/data/built/all.json").write_text(
            json.dumps(built, ensure_ascii=False))
        print(f"★正典適用: {applied}本(介入#36・recovery=satellite)")
    elif not args.write:
        print("(表示のみ。適用は --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
