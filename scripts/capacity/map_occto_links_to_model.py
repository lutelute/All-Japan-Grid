#!/usr/bin/env python3
"""OCCTO の連系線名を、モデルの枝に対応づける候補を作る（スクリーニング）。

OCCTO の運用容量は「連系線名」で公表されるが（`相馬双葉幹線` `三重東近江線` …）、
本モデルの枝名は OSM 由来で**端点の変電所名から機械生成**されていることが多い
（`東近江開閉所~三重開閉所線`）。名前で突合すると設備が無いように見えるが、
実際には存在する — 2026-08-09 の突合で `三重東近江線` は
`東近江開閉所~三重開閉所線` として実在することを地理的に確認した。

そこで、連系線名を**端点の地名に分解**して枝名を探し、さらに地理的な近傍でも
裏を取る。出力は候補であって確定ではない（採用は人間判断＋介入台帳記帳）。

usage: python3 scripts/capacity/map_occto_links_to_model.py
出力: docs/reports/occto_link_mapping_<date>.{md,json}
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

BUILT = ROOT / "docs" / "data" / "built" / "all.json"
SOURCES = ROOT / "data" / "interconnector_capacity_sources.jsonl"
REPORTS = ROOT / "docs" / "reports"

MIN_KV = 154.0        # 連系線は基幹系。これ未満は候補にしない
NEAR_KM = 20.0        # 地理的裏取りの半径

# 連系線名 → (端点の地名ヒント, 代表座標, 備考)
# 座標は公表資料・地理的事実にもとづく設備の所在。名前照合の裏取りに使う。
LINKS = {
    "北海道・本州間電力連系設備": {
        "endpoints": [["函館", "北斗", "上磯"], ["今別", "青森", "本州"]],
        "spots": [(41.79, 140.64), (41.17, 140.49)],
        "note": "北本 HVDC。海底ケーブルは OSM に載りにくい",
    },
    "相馬双葉幹線": {
        "endpoints": [["相馬", "新地", "今泉"], ["双葉", "大熊", "新福島"]],
        "spots": [(37.80, 140.95), (37.45, 141.00)],
        "note": "東北↔東京の最大連系。500kV",
    },
    "周波数変換設備": {
        "endpoints": [["佐久間"], ["新信濃"], ["東清水"], ["飛騨"]],
        "spots": [(35.09, 137.80), (36.48, 138.02), (35.05, 138.50)],
        "note": "東西 FC。3〜4 か所の変換所の合計",
    },
    "南福光連系所・南福光変電所の連系設備": {
        "endpoints": [["南福光"]],
        "spots": [(36.55, 136.90)],
        "note": "北陸↔中部 BTB",
    },
    "越前嶺南線": {
        "endpoints": [["越前"], ["嶺南", "西浅井", "塩津"]],
        "spots": [(35.90, 136.20), (35.55, 136.05)],
        "note": "北陸↔関西 500kV",
    },
    "三重東近江線": {
        "endpoints": [["三重"], ["東近江"]],
        "spots": [(34.95, 136.35), (35.10, 136.25)],
        "note": "中部↔関西 500kV",
    },
    "関西-中国（東）": {
        "endpoints": [["西播", "上郡"], ["山崎"]],
        "spots": [(34.87, 134.35)],
        "note": "関西↔中国 東ルート",
    },
    "関西-中国（西）": {
        "endpoints": [["日野"], ["新岡山", "岡山"]],
        "spots": [(35.30, 133.40)],
        "note": "関西↔中国 西ルート",
    },
    "本四連系線": {
        "endpoints": [["讃岐", "香川", "高松"], ["瀬戸", "阪神", "西播"]],
        "spots": [(34.25, 134.05), (34.35, 133.95)],
        "note": "中国↔四国",
    },
    "阿南紀北直流幹線": {
        "endpoints": [["阿南"], ["紀北", "紀の川", "橋本"]],
        "spots": [(33.95, 134.60), (34.20, 135.15)],
        "note": "四国↔関西 HVDC（紀伊水道）",
    },
    "関門連系線": {
        "endpoints": [["関門", "北九州", "下関"]],
        "spots": [(33.95, 130.95)],
        "note": "中国↔九州",
    },
    # フェンスは個別設備でなく断面の集約概念なので対応づけない
    "北陸フェンス": {"endpoints": [], "spots": [], "note": "断面の集約概念（個別設備ではない）"},
    "中部フェンス": {"endpoints": [], "spots": [], "note": "断面の集約概念（個別設備ではない）"},
    "関西フェンス": {"endpoints": [], "spots": [], "note": "断面の集約概念（個別設備ではない）"},
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                                       text=True).stdout.strip()

    built = json.load(open(BUILT))
    edges = [e for e in built["edges"] if (e.get("kv") or 0) >= MIN_KV]
    caps = {}
    if SOURCES.exists():
        for line in open(SOURCES, encoding="utf-8"):
            r = json.loads(line)
            caps.setdefault(r["name"], {})[r["direction"]] = r["value"]

    out = []
    for name, spec in LINKS.items():
        # ① 名前での候補: 端点ヒントの**両側**を含む枝名（片側だけは弱い）
        by_name = []
        for e in edges:
            nm = e.get("name") or ""
            if not nm:
                continue
            groups_hit = sum(1 for grp in spec["endpoints"] if any(h in nm for h in grp))
            if spec["endpoints"] and groups_hit >= min(2, len(spec["endpoints"])):
                by_name.append({"name": nm, "kv": e.get("kv"), "groups_hit": groups_hit})
        # 重複線名を畳む
        seen, uniq = set(), []
        for c in sorted(by_name, key=lambda x: (-x["groups_hit"], -(x["kv"] or 0))):
            if c["name"] in seen:
                continue
            seen.add(c["name"])
            uniq.append(c)

        # ② 地理での裏取り: 代表座標の近傍に基幹系の枝があるか
        geo = []
        for (la, lo) in spec["spots"]:
            best = None
            for e in edges:
                for pt in (e["a"], e["b"]):
                    d = math.dist((pt[0], pt[1]), (la, lo)) * 111
                    if d <= NEAR_KM and (best is None or d < best[0]):
                        best = (round(d, 1), e.get("kv"), e.get("name") or "(無名)")
                    break
            geo.append({"spot": [la, lo], "nearest": best})

        cap = caps.get(name, {})
        out.append({
            "occto_name": name,
            "note": spec["note"],
            "capacity_fwd_mw": cap.get("順方向"),
            "capacity_rev_mw": cap.get("逆方向"),
            "name_candidates": uniq[:5],
            "geo_evidence": geo,
            "verdict": ("集約概念（対応づけ対象外）" if not spec["endpoints"]
                        else "名前候補あり" if uniq
                        else "名前候補なし・地理のみ"),
        })

    json.dump({"date": date, "min_kv": MIN_KV, "near_km": NEAR_KM, "links": out},
              open(REPORTS / f"occto_link_mapping_{date}.json", "w"),
              ensure_ascii=False, indent=1)

    L = [
        f"# OCCTO 連系線 → モデルの枝 の対応候補（{date}）",
        "",
        "OCCTO の運用容量は連系線名（`三重東近江線` など）で公表されるが、本モデルの枝名は",
        "OSM 由来で**端点の変電所名から機械生成**されていることが多い（`東近江開閉所~三重開閉所線`）。",
        "そのため名前で突合すると設備が無いように見える。**実際には存在する。**",
        "",
        "そこで連系線名を端点の地名に分解して枝名を探し、代表座標の近傍でも裏を取った。",
        "**これは候補であって確定ではない。** 採用は人間判断＋`docs/MODEL_INTERVENTIONS.md` 記帳。",
        "",
        "| OCCTO 連系線 | 順/逆 運用容量 | モデル内の候補 | 地理の裏取り |",
        "|---|---:|---|---|",
    ]
    for r in out:
        cap = (f"{r['capacity_fwd_mw']:,.0f} / {r['capacity_rev_mw']:,.0f} MW"
               if r["capacity_fwd_mw"] else "—")
        cands = "<br>".join(f"{c['kv']:.0f}kV {c['name'][:30]}" for c in r["name_candidates"][:2]) or "—"
        geo = "; ".join(f"{g['nearest'][0]}km {g['nearest'][1]:.0f}kV" if g["nearest"] else "近傍なし"
                        for g in r["geo_evidence"]) or "—"
        L.append(f"| {r['occto_name']} | {cap} | {cands} | {geo} |")
    L += [
        "",
        "## 読み方",
        "",
        "- **名前候補あり**: 端点の地名が両側とも枝名に現れた。対応の確度が高い",
        "- **名前候補なし・地理のみ**: 枝名からは辿れないが、代表座標の近傍に基幹系の枝がある。",
        "  設備が無いのではなく、名前が端点由来になっているか、OSM に線名が入っていない",
        "- **集約概念**: フェンス（北陸・中部・関西）は断面の集約で個別設備ではないため対応づけない",
        "",
        "**裁定時の注意 — 電圧を必ず見ること。** 端点の地名が合っていても電圧が違えば別設備である。",
        "例えば相馬双葉幹線は 500kV だが、本表の候補には 275kV の枝が上位に来ている。",
        "地名の一致だけで採ると、同じ地点を通る別電圧の線を掴む。",
        "",
        "海底ケーブル（北本 HVDC・紀伊水道 HVDC）は OSM に載りにくく、",
        "地理の裏取りも陸上の端点近傍にとどまる点に注意。",
        "",
        "---",
        "生成: `scripts/capacity/map_occto_links_to_model.py`",
        "",
    ]
    (REPORTS / f"occto_link_mapping_{date}.md").write_text("\n".join(L), encoding="utf-8")

    named = sum(1 for r in out if r["verdict"] == "名前候補あり")
    geo_only = sum(1 for r in out if r["verdict"] == "名前候補なし・地理のみ")
    agg = sum(1 for r in out if "集約" in r["verdict"])
    print(f"連系線 {len(out)} 本: 名前候補あり {named} / 地理のみ {geo_only} / 集約概念 {agg}")
    for r in out:
        if r["name_candidates"]:
            c = r["name_candidates"][0]
            print(f"  ○ {r['occto_name']:28s} → {c['kv']:.0f}kV {c['name'][:40]}")
        elif r["verdict"] != "集約概念（対応づけ対象外）":
            g = [x for x in r["geo_evidence"] if x["nearest"]]
            near = f"{g[0]['nearest'][0]}km {g[0]['nearest'][2][:28]}" if g else "近傍なし"
            print(f"  △ {r['occto_name']:28s} → 名前一致なし（地理: {near}）")
    print(f"→ docs/reports/occto_link_mapping_{date}.md")


if __name__ == "__main__":
    main()
