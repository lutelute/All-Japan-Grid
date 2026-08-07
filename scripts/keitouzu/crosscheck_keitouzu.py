#!/usr/bin/env python3
"""open-keitouzu（公式系統図の論理トポロジ）× AGJ built 正典の突合検証。

やること（スクリーニングのみ・モデルへの自動反映はしない）:
  1. crosswalk の ajg 対応 ID が built ノードへ解決できる率
  2. keitouzu の各辺（active）が built の変電所レベルグラフで再現されるか
     - hop=1        : 直接隣接として一致
     - hop=2..4     : 中間変電所を挟む粒度差（実質整合）
     - >4 / 断絶    : 食い違い候補 → 人間判断のスクリーニング対象
  3. 食い違い候補を keitouzu 側の判読根拠（notes の ev:）付きで一覧化

方針（家訓）:
  - 候補の自動採用はしない。採用は人間判断＋docs/MODEL_INTERVENTIONS.md 記帳が必須。
  - keitouzu 自体も人手 review を経ていない（confidence=extracted が大半）。
    「食い違い＝どちらかが誤っている」ことしか言えない。

usage: python3 scripts/keitouzu/crosscheck_keitouzu.py [--date YYYY-MM-DD]
出力: docs/reports/keitouzu_crosscheck_<date>.md / .json
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
from collections import defaultdict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KZ = ROOT / "data" / "external" / "keitouzu"
BUILT = ROOT / "docs" / "data" / "built" / "all.json"
REPORTS = ROOT / "docs" / "reports"

GRANULARITY_MAX_HOPS = 4  # これ以内なら「中間変電所を挟む粒度差」とみなす


def load_csv(name: str) -> list[dict]:
    with open(KZ / f"{name}.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_sub_graph(built: dict) -> tuple[set[str], dict[str, set[str]], dict[str, set[str]]]:
    """built の nodes/edges から変電所レベル隣接グラフを作る。

    エッジ端は座標で表現されているため、ノード座標(5桁丸め)で ID に解決する。
    変電所レベル隣接 = sub ノードから jct のみを経由して届く別の sub（基底ID同士）。
    """
    nodes, edges = built["nodes"], built["edges"]
    node_ids = {n["id"] for n in nodes}
    base_ids: dict[str, set[str]] = defaultdict(set)
    coord2id: dict[tuple[float, float], str] = {}
    for n in nodes:
        base_ids[n["id"].split("@")[0]].add(n["id"])
        coord2id[(round(n["lat"], 5), round(n["lon"], 5))] = n["id"]

    adj: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        ia = coord2id.get((round(e["a"][0], 5), round(e["a"][1], 5)))
        ib = coord2id.get((round(e["b"][0], 5), round(e["b"][1], 5)))
        if ia is None or ib is None:
            continue
        adj[ia].add(ib)
        adj[ib].add(ia)

    sub_adj: dict[str, set[str]] = defaultdict(set)
    for n in nodes:
        nid = n["id"]
        if "_sub_" not in nid:
            continue
        start = nid.split("@")[0]
        seen, stack = {nid}, [nid]
        while stack:
            for nb in adj[stack.pop()]:
                if nb in seen:
                    continue
                seen.add(nb)
                if "_sub_" in nb:
                    b = nb.split("@")[0]
                    if b != start:
                        sub_adj[start].add(b)
                else:
                    stack.append(nb)
    return node_ids, dict(base_ids), dict(sub_adj)


def min_hops(sub_adj: dict[str, set[str]], srcs: set[str], dsts: set[str], maxd: int) -> int | None:
    best = None
    for s in srcs:
        dist = {s: 0}
        q = deque([s])
        while q:
            cur = q.popleft()
            if dist[cur] >= maxd:
                continue
            for nb in sub_adj.get(cur, ()):
                if nb not in dist:
                    dist[nb] = dist[cur] + 1
                    q.append(nb)
        for d in dsts:
            if d in dist and (best is None or dist[d] < best):
                best = dist[d]
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="レポート日付 (YYYY-MM-DD)。省略時は今日")
    args = ap.parse_args()
    date = args.date or subprocess.run(
        ["date", "+%Y-%m-%d"], capture_output=True, text=True
    ).stdout.strip()

    built = json.load(open(BUILT))
    node_ids, base_ids, sub_adj = build_sub_graph(built)

    xw = load_csv("crosswalk")
    routes = load_csv("routes")
    subs = {r["uuid"]: r for r in load_csv("substations")}
    aliases = defaultdict(list)
    for a in load_csv("aliases"):
        aliases[a["uuid"]].append(a["alias"])

    ajg_map: dict[str, list[str]] = defaultdict(list)
    for r in xw:
        if r["target_system"] == "ajg":
            ajg_map[r["uuid"]].append(r["target_id"])

    # 1) ID 解決
    total = sum(len(v) for v in ajg_map.values())
    exact = sum(1 for v in ajg_map.values() for t in v if t in node_ids)

    # 2) 辺の分類
    active = [r for r in routes if r["status"] == "active"]
    counts = {"hop1": 0, "hop2_4": 0, "divergent": 0, "unmappable": 0}
    by_region: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    candidates = []
    for r in active:
        fu, tu = r["from_substation"], r["to_substation"]
        fb = {t.split("@")[0] for t in ajg_map.get(fu, ()) if t.split("@")[0] in base_ids}
        tb = {t.split("@")[0] for t in ajg_map.get(tu, ()) if t.split("@")[0] in base_ids}
        reg = r["region"]
        if not fb or not tb:
            counts["unmappable"] += 1
            by_region[reg]["unmappable"] += 1
            continue
        h = min_hops(sub_adj, fb, tb, GRANULARITY_MAX_HOPS)
        if h == 1:
            key = "hop1"
        elif h is not None:
            key = "hop2_4"
        else:
            key = "divergent"
            fname = subs.get(fu, {}).get("name_official", "?")
            tname = subs.get(tu, {}).get("name_official", "?")
            candidates.append({
                "keitouzu_uuid": r["uuid"],
                "line": r.get("name_official", ""),
                "voltage_kv": r["voltage_kv"],
                "region": reg,
                "from": {"name": fname, "aliases": aliases.get(fu, []), "ajg": sorted(ajg_map[fu])},
                "to": {"name": tname, "aliases": aliases.get(tu, []), "ajg": sorted(ajg_map[tu])},
                "confidence": r["confidence"],
                "source_ref": r["source_ref"],
                "evidence": r.get("notes", ""),
            })
        counts[key] += 1
        by_region[reg][key] += 1

    mapped = counts["hop1"] + counts["hop2_4"] + counts["divergent"]
    compatible = counts["hop1"] + counts["hop2_4"]

    out_json = REPORTS / f"keitouzu_crosscheck_{date}.json"
    out_md = REPORTS / f"keitouzu_crosscheck_{date}.md"
    json.dump(
        {
            "date": date,
            "upstream": "https://github.com/ibarapascal/open-keitouzu",
            "pinned_commit": "db1c6c6597e7210195b692a15fff4ad7de32a6db",
            "built_nodes": len(built["nodes"]),
            "crosswalk_ajg": {"total": total, "resolved_exact": exact},
            "edges": {"active": len(active), **counts},
            "by_region": {k: dict(v) for k, v in sorted(by_region.items())},
            "divergent_candidates": candidates,
        },
        open(out_json, "w"),
        ensure_ascii=False,
        indent=1,
    )

    lines = [
        f"# open-keitouzu × built 正典 突合検証 — {date}",
        "",
        "公式系統図PDF由来の論理トポロジ [open-keitouzu](https://github.com/ibarapascal/open-keitouzu)",
        "(CC BY 4.0, pinned `db1c6c6`) を、AGJ built 正典 (`docs/data/built/all.json`) と突合した。",
        "**スクリーニングのみ。候補の採用は人間判断＋`docs/MODEL_INTERVENTIONS.md` 記帳が必須。**",
        "",
        "## サマリ",
        "",
        f"- crosswalk の ajg 対応 **{total} 件が {exact/total:.1%} built ノード ID に完全解決**（先方が v1.6.0 データセットに突合済み）",
        f"- keitouzu active 辺 {len(active)} 本のうち両端解決 {mapped} 本:",
        f"  - 直接隣接一致 (hop=1): **{counts['hop1']}** ({counts['hop1']/mapped:.1%})",
        f"  - 粒度差整合 (hop=2..{GRANULARITY_MAX_HOPS}): **{counts['hop2_4']}** ({counts['hop2_4']/mapped:.1%}) — builtが中間変電所で区間分割",
        f"  - **食い違い候補: {counts['divergent']}** ({counts['divergent']/mapped:.1%}) — 公式図は接続を主張、builtで再現されず",
        f"- 両端未解決（crosswalk 未対応の站を含む辺）: {counts['unmappable']} 本 — 将来の充填候補",
        "",
        "## region 別",
        "",
        "| region | hop=1 | hop=2..4 | 食い違い | 未解決 |",
        "|---|---:|---:|---:|---:|",
    ]
    for reg, c in sorted(by_region.items(), key=lambda x: -sum(x[1].values())):
        lines.append(
            f"| {reg} | {c.get('hop1',0)} | {c.get('hop2_4',0)} | {c.get('divergent',0)} | {c.get('unmappable',0)} |"
        )
    lines += [
        "",
        "## 食い違い候補（人間判断待ちのスクリーニング一覧）",
        "",
        "keitouzu 側の判読根拠（`ev:`）付き。keitouzu も人手 review を経ていないため、",
        "**「どちらかが誤っている」ことしか言えない**。地中線の多い都市部は built（OSM由来）が",
        "構造的に見えない領域であることに留意。",
        "",
        "| kV | 線名 | from | to | region | conf | 根拠(抜粋) |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in candidates:
        ev = c["evidence"].replace("|", "／").replace("\n", " ")
        if len(ev) > 80:
            ev = ev[:80] + "…"
        lines.append(
            f"| {c['voltage_kv']} | {c['line']} | {c['from']['name']} | {c['to']['name']} | {c['region']} | {c['confidence']} | {ev} |"
        )
    lines += [
        "",
        f"全候補の機械可読版（ajg ノード ID・別名・source_ref 込み）: `{out_json.name}`",
        "",
        "---",
        "生成: `scripts/keitouzu/crosscheck_keitouzu.py`（fetch は `fetch_keitouzu.py`）",
        "",
    ]
    out_md.write_text("\n".join(lines), encoding="utf-8")

    print(f"[1] crosswalk ajg: {exact}/{total} 完全解決 ({exact/total:.1%})")
    print(f"[2] 辺分類: hop1={counts['hop1']} hop2-4={counts['hop2_4']} "
          f"食い違い={counts['divergent']} 未解決={counts['unmappable']} (整合率 {compatible/mapped:.1%})")
    print(f"→ {out_md.relative_to(ROOT)}")
    print(f"→ {out_json.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
