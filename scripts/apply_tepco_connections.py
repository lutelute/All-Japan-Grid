#!/usr/bin/env python3
"""TEPCO公表で解決した孤立変電所の接続を、正典を壊さず検証・worklist化する。

reconcile_isolated_tepco.py が出した★解決(孤立変電所→線→本系統変電所)を、
built/all.json に足したら「本系統外」が幾つ減るかを**ドライラン**で確かめる
(docs/data/built/ は書き換えない)。既存の reconnector.py は最寄りbus合成接続=
幾何ヒューリスティック(=無理に繋ぐ)なので使わず、**TEPCO公表という独立一次源の
接続**を明示的に足す。

出力:
  - stdout: 適用前後の本系統外ノード数(=何件が合流したか)
  - docs/reports/tepco_connection_worklist.json: 適用可能な接続(座標つき)。
    ビルドの手動接続入力や接続編集ツールが後で読める。介入台帳(帳簿)の実体。

介入台帳(docs/MODEL_INTERVENTIONS.md)に別途登録: ①根拠=TEPCO系統情報公表の線名
②帳簿=このworklist ③無効化=worklistを外せば元に戻る(正典は不変)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.powerflow.connectivity import compute_connectivity  # noqa: E402

BUILT = ROOT / "docs" / "data" / "built" / "all.json"
RECON = ROOT / "docs" / "reports" / "isolated_tepco_reconcile.json"
VIZ = ROOT / "data" / "external" / "system_disclosure" / "viz"
OUT = ROOT / "docs" / "reports" / "tepco_connection_worklist.json"


def main() -> int:
    built = json.loads(BUILT.read_text(encoding="utf-8"))
    nodes = built["nodes"]
    edges = built["edges"]
    rec = json.loads(RECON.read_text(encoding="utf-8"))

    # 名前→座標(built の実ノード)。audit と同じ座標系。
    name_pt = {}
    for n in nodes:
        if n.get("name") and n.get("lat") is not None:
            name_pt.setdefault(n["name"], [n["lat"], n["lon"]])

    # ★解決の接続を (孤立座標, 本系統座標) の枝にする
    worklist = []
    for r in rec.get("resolved", []):
        iso = r["name"]
        if iso not in name_pt:
            continue
        for tgt in r.get("connects_to_main", [])[:1]:   # 代表1本(最優先)
            if tgt not in name_pt:
                continue
            worklist.append({
                "from_sub": iso, "to_sub": tgt,
                "from_pt": name_pt[iso], "to_pt": name_pt[tgt],
                "kv": r.get("kv"), "lines": r.get("lines", []),
                "evidence": "TEPCO系統情報公表(潮流実績CSV 変電所×線路名)",
                "source_type": "independent_primary",
            })

    # Wikipedia/J-POWER(独立二次)で解決した非東京の名指し接続を足す。
    # 繋ぎ先はモデルの実ノード名(変異名で実在)。同一島でなければ
    # compute_connectivity が枝を無視するので、ドライランで実合流可否が正直に出る。
    WIKI = [
        {"from_model": "由良開閉所", "to_model": "紀北変換所",
         "line": "阿南紀北直流幹線(DC連系)", "dc": True,
         "src": "ja.wikipedia.org/wiki/紀伊水道直流連系設備"},
        {"from_model": "上ノ国町変電所", "to_model": "江差変電所 66kV",
         "line": "上ノ国ウインドファーム連系", "dc": False,
         "src": "ja.wikipedia.org/wiki/上ノ国ウインドファーム"},
        {"from_model": "大間町変電所_3 500kV", "to_model": "上北変電所 500kV",
         "line": "大間幹線→むつ幹線", "dc": False,
         "src": "aec.go.jp J-POWER 大間幹線資料 / wikipedia 東通原子力発電所"},
    ]
    for w in WIKI:
        if w["from_model"] in name_pt and w["to_model"] in name_pt:
            worklist.append({
                "from_sub": w["from_model"], "to_sub": w["to_model"],
                "from_pt": name_pt[w["from_model"]], "to_pt": name_pt[w["to_model"]],
                "kv": None, "lines": [w["line"]],
                "evidence": f"独立二次(Wikipedia/J-POWER): {w['src']}",
                "source_type": "independent_secondary",
                "dc_tie": w["dc"],
            })

    # region誤タグの是正(接続の前提)。大間町は青森県下北半島=tohoku(east島)だが
    # hokkaidoタグ。calibrate_islands は operator無で検出できないが、地理と
    # 近隣(佐井/大畑/東通=tohoku是正済)とJ-POWER大間幹線→上北から tohoku が正。
    import copy
    REGION_FIX = [{"match": "大間町変電所", "from": "hokkaido", "to": "tohoku",
                   "evidence": "地理(下北半島=青森)・近隣佐井/大畑/東通がtohoku(calibrate_islands)・J-POWER大間幹線→上北"}]
    nodes_fixed = copy.deepcopy(nodes)
    n_relabel = 0
    for n in nodes_fixed:
        for rf in REGION_FIX:
            if n.get("name") and rf["match"] in n["name"] and n.get("region") == rf["from"]:
                n["region"] = rf["to"]; n_relabel += 1

    # 連結性: 適用前
    cc0 = compute_connectivity(nodes, edges)
    off0 = sum(1 for n in nodes if _k5(n["lat"], n["lon"]) not in cc0["main_keys"])

    # 適用後(region是正＋枝を足してドライラン再計算・正典は書かない)
    new_edges = edges + [{"a": w["from_pt"], "b": w["to_pt"]} for w in worklist]
    cc1 = compute_connectivity(nodes_fixed, new_edges)
    off1 = sum(1 for n in nodes_fixed if _k5(n["lat"], n["lon"]) not in cc1["main_keys"])

    # 対象の孤立変電所が実際に合流したか
    joined = []
    for w in worklist:
        k = _k5(w["from_pt"][0], w["from_pt"][1])
        if k not in cc0["main_keys"] and k in cc1["main_keys"]:
            joined.append(w["from_sub"])

    print(f"適用worklist {len(worklist)} 本(独立実証: TEPCO公表＋Wikipedia/J-POWER)")
    print(f"region是正 {n_relabel}ノード(大間町 hokkaido→tohoku・接続の前提)")
    print(f"本系統外ノード: 適用前 {off0} → 適用後 {off1}  （{off0-off1} 減）")
    print(f"合流した孤立変電所 {len(joined)}: " + "、".join(joined))
    print("\n--- worklist(孤立→本系統) ---")
    for w in worklist:
        kv = f"{w['kv']:>5.0f}kV" if w.get("kv") else "  —  "
        tag = " [DC]" if w.get("dc_tie") else ""
        src = "TEPCO" if w.get("source_type") == "independent_primary" else "Wiki"
        print(f"  {kv} {w['from_sub']:<18} → {w['to_sub']}  [{('・'.join(w['lines'][:1]))}]{tag} ({src})")

    OUT.write_text(json.dumps({
        "note": ("TEPCO公表(独立一次源)で解決した孤立変電所の接続worklist。"
                 "正典built/all.jsonは不変=これを外せば元に戻る(③無効化)。"
                 "座標は接続端点の位置情報のみ、生の潮流値は非収録。"),
        "evidence": "TEPCO PG 系統情報公表 潮流実績CSV(変電所×線路名)",
        "region_fix": REGION_FIX, "region_fix_nodes": n_relabel,
        "dryrun_off_main_before": off0, "dryrun_off_main_after": off1,
        "joined_subs": joined,
        "worklist": worklist,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n保存: {OUT.relative_to(ROOT)}")
    return 0


def _k5(la, lo):
    return (round(la, 5), round(lo, 5))


if __name__ == "__main__":
    raise SystemExit(main())
