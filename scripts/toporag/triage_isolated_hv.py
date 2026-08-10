#!/usr/bin/env python3
"""接続ゼロの高電圧変電所を三分類する — 「繋ぐべきもの」はほとんど無い。

`cluster_substations.py` が構造だけから「接続ゼロの ≥275kV 変電所」を名指しした。
高電圧なのに枝が 1 本も無いのは明白な欠陥に見えるが、**中身を見ると大半は
繋ぐ話ではない**。オーナー観察（2026-06-16）「島の変電所の多くは鉄道き電用・
配電用・地下変電所など**別系統**であって送電網の連系欠落ではない」の高電圧版。

三分類（機械的に判定できるところまでを機械がやる）:

  A 重複コピー   同名または ~0km に**枝を持つ別レコード**がある
                 → 接続ではなく **dedup**。介入#21（重複除去）と同型で、
                    「除去であって接続を作るのではない」から捏造にならない
  B1 都心地中    **東京**で、最寄りの接続済み同等電圧まで数 km だが OSM に線が無い
                 → 2026-06 の 66kV プログラムが証明した天井（都心地中ケーブル未収載）
                    と一致する。出典が無いので繋げない。開示して残す
  B2 近いが未説明 東京以外で同じ形。**都心地中では説明できない**ので要調査
                 （距離だけで「地中」と断定しない — 由良開閉所は和歌山の海岸、
                   脇田は鹿児島で、いずれも都心ではない）
  C 要調査       上のどれでもない（遠い・単独）

**自動接続はしない**（`feedback_lever_candidates_human_judgment`）。
機械はスクリーニングと根拠提示まで、採否は人間。

usage: python3 scripts/toporag/triage_isolated_hv.py [--kv-floor 275]
出力: docs/reports/isolated_hv_triage_<date>.{json,md}
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
REPORTS = ROOT / "docs" / "reports"
BUILT = ROOT / "docs" / "data" / "built" / "all.json"

from src.topology.coords import CoordIndex  # noqa: E402

DUP_KM = 0.5          # これ以内に枝を持つ同名/近傍があれば重複コピー
URBAN_KM = 12.0       # これ以内に接続済み同等電圧があるのに線が無い＝地中の疑い


def _hav(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def _norm(s: str) -> str:
    """`_2` 等の複製サフィックスと電圧表記を落とした比較用の名前。"""
    s = re.sub(r"_\d+$", "", s or "")
    s = re.sub(r"\s*\d+\s*kV", "", s, flags=re.I)
    return re.sub(r"[\s　]|変電所|開閉所|株式会社", "", s)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kv-floor", type=float, default=275.0)
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                                       text=True).stdout.strip()

    built = json.load(open(BUILT, encoding="utf-8"))
    nodes, edges = built["nodes"], built["edges"]
    ix = CoordIndex(nodes)
    base = lambda i: i.split("@")[0]                                  # noqa: E731

    inc: dict[str, int] = defaultdict(int)
    for e in edges:
        kv = e.get("kv") or 0.0
        try:
            for i in ix.endpoints(e["a"], kv):
                inc[base(nodes[i]["id"])] += 1
            for j in ix.endpoints(e["b"], kv):
                inc[base(nodes[j]["id"])] += 1
        except Exception:  # noqa: BLE001
            continue

    maxkv: dict[str, float] = defaultdict(float)
    name: dict[str, str] = {}
    region: dict[str, str] = {}
    pos: dict[str, tuple] = {}
    for n in nodes:
        if n.get("sub") != 1:
            continue
        b = base(n["id"])
        maxkv[b] = max(maxkv[b], float(n.get("kv") or 0.0))
        name.setdefault(b, n.get("name") or "")
        region.setdefault(b, n.get("region") or b.split("_")[0])
        pos.setdefault(b, (n["lat"], n["lon"]))

    connected = [(b, pos[b], maxkv[b], name[b], region[b])
                 for b in maxkv if inc.get(b, 0) > 0]
    iso = [b for b in maxkv if maxkv[b] >= args.kv_floor and inc.get(b, 0) == 0]

    out = []
    for b in sorted(iso, key=lambda x: (-maxkv[x], name[x])):
        p, kv = pos[b], maxkv[b]
        near = sorted(((_hav(p, q), bb, kk, nn, rr)
                       for bb, q, kk, nn, rr in connected), key=lambda t: t[0])
        # A: ~0km に枝を持つレコード（同名でなくてもよい＝別名の重複コピーも拾う）
        dup = next((t for t in near if t[0] <= DUP_KM), None)
        same_name = next((t for t in near if _norm(t[3]) == _norm(name[b])), None)
        d0, b0, kv0, n0, r0 = near[0] if near else (float("nan"), "", 0, "", "")
        if dup is not None:
            cls, why = "A_重複コピー", (
                f"{dup[0]:.2f}km に枝を持つレコード「{dup[3]}」({dup[4]}) がある"
                + ("・同名" if same_name is not None and same_name[0] <= DUP_KM else ""))
        elif d0 <= URBAN_KM:
            # **原因を距離から断定しない。** 東京の都心地中ケーブル未収載は
            # 2026-06 に証明された天井だが、由良開閉所(和歌山の海岸)や脇田(鹿児島)は
            # 都心ではない。地域で言い分けて、根拠のない一般化をしない。
            if region[b] == "tokyo":
                cls, why = "B1_都心地中の疑い", (
                    f"最寄りの接続済み同等以上電圧「{n0}」まで {d0:.1f}km なのに線が無い。"
                    "東京都心の地中ケーブルは OSM 未収載＝2026-06 の 66kV プログラムが"
                    "証明した天井と一致する")
            else:
                cls, why = "B2_近いが未説明", (
                    f"最寄りの接続済み同等以上電圧「{n0}」まで {d0:.1f}km なのに線が無い。"
                    f"{region[b]} は都心ではないので**地中ケーブルでは説明できない** — "
                    "要調査（別名の重複か、OSM の線が単に欠けているか）")
        else:
            cls, why = "C_要調査", f"最寄り接続先まで {d0:.1f}km と遠い"
        out.append({"id": b, "name": name[b], "region": region[b], "kv": kv,
                    "class": cls, "why": why,
                    "nearest_name": n0, "nearest_km": round(d0, 2),
                    "nearest_kv": kv0, "nearest_region": r0})

    counts: dict[str, int] = defaultdict(int)
    for r in out:
        counts[r["class"]] += 1
    for r in out:
        print(f"[{r['class']:12s}] {r['name'][:26]:28s} {r['region']:8s} "
              f"{r['kv']:5.0f}kV  {r['why']}", flush=True)
    print(f"\n合計 {len(out)} 件: " + " / ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    payload = {"date": date, "kv_floor": args.kv_floor, "dup_km": DUP_KM,
               "urban_km": URBAN_KM, "counts": dict(counts), "items": out}
    (REPORTS / f"isolated_hv_triage_{date}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    L = [f"# 接続ゼロの高電圧変電所を三分類する（{date}）", "",
         f"`cluster_substations.py` が構造だけから「接続ゼロの ≥{args.kv_floor:.0f}kV 変電所」を",
         "名指しした。高電圧なのに枝が 1 本も無いのは明白な欠陥に見えるが、",
         "**中身を見ると大半は繋ぐ話ではない**。", "",
         "| 分類 | 件数 | 意味 | 打ち手 |", "|---|---:|---|---|",
         f"| A 重複コピー | {counts.get('A_重複コピー', 0)} | {DUP_KM}km 以内に枝を持つ別レコードがある | "
         "**dedup**（介入#21 と同型・除去であって接続を作らない） |",
         f"| B1 都心地中の疑い | {counts.get('B1_都心地中の疑い', 0)} | 東京。最寄りまで数 km なのに線が無い | "
         "**繋げない**。2026-06 に証明された天井（都心地中ケーブル未収載）と一致。開示して残す |",
         f"| B2 近いが未説明 | {counts.get('B2_近いが未説明', 0)} | 東京以外。地中では説明できない | "
         "**要調査**。別名の重複か OSM の線の欠落か |",
         f"| C 要調査 | {counts.get('C_要調査', 0)} | 上のどちらでもない | 個別調査 |", "",
         "## 一覧", "",
         "| 分類 | 変電所 | 地域 | kV | 最寄の接続済み | 距離 | 根拠 |",
         "|---|---|---|---:|---|---:|---|"]
    for r in out:
        L.append(f"| {r['class']} | {r['name']} | {r['region']} | {r['kv']:.0f} | "
                 f"{r['nearest_name']}（{r['nearest_region']}） | {r['nearest_km']:.1f}km | "
                 f"{r['why']} |")
    L += ["", "---",
          "**自動接続はしない**（`feedback_lever_candidates_human_judgment`: "
          "機械はスクリーニングと根拠提示まで、採否は人間）。",
          "A は接続を作らない除去なので比較的安全だが、それでも人間が確認してから。", "",
          "生成: `scripts/toporag/triage_isolated_hv.py`", ""]
    (REPORTS / f"isolated_hv_triage_{date}.md").write_text("\n".join(L), encoding="utf-8")
    print(f"→ docs/reports/isolated_hv_triage_{date}.md")


if __name__ == "__main__":
    main()
