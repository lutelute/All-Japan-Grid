#!/usr/bin/env python3
"""介入#51 — 一次資料で誤りと分かった OSM の電圧タグを、正典モデルで直す(1 件ずつ台帳で承認).

根拠(①): 各社の空容量・予想潮流一覧(変圧器と送電線の一覧)。変電所の変圧器が持たない電圧の線・母線は、
OSM のタグの誤り。下の CORRECTIONS 表が承認台帳(②)を兼ね、根拠・推論・確かめられないことを書く。
status="approved" だけ当てる。

直し方: 指定した変電所の節点から、誤った電圧(from_kv)の枝だけをたどった連結成分の節点と枝を、正しい電圧
(to_kv)に置き換える。成分が max_nodes を超えたら当てない(誤りが別の系統に広がっていないことの確認)。
節点の ID・名前の電圧の部分も置き換え、`kv_corrected` に元の電圧と台帳 ID を残す。

無効化(③): `--revert` で `kv_corrected` の付いた節点と枝を元の電圧に戻す。冪等(当て済みなら何もしない)。

usage:
  PYTHONPATH=. python3 scripts/apply_voltage_corrections.py           # 表示のみ
  PYTHONPATH=. python3 scripts/apply_voltage_corrections.py --write   # 適用
  PYTHONPATH=. python3 scripts/apply_voltage_corrections.py --revert --write
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILT = ROOT / "docs/data/built/all.json"

CORRECTIONS = [
    {
        "id": "vc-001-nishishimane",
        "status": "approved",           # オーナー「進めて」2026-10-08(判断待ち 2 の承認)
        "region": "chugoku", "site": "西島根変電所", "from_kv": 275.0, "to_kv": 220.0, "max_nodes": 4,
        "evidence": ("中国電力NW 空容量・予想潮流一覧(2026-09-28 更新): 西島根の変圧器は 500/220 kV(3 台)と "
                     "220/110 kV(2 台)だけ。中国電力の公表一覧(変圧器 1,700 行余り)に 275 kV の階級は無い。"
                     "出典 DB(data/transformer_sources.jsonl)の既設の銘板も 500/220 kV"),
        "inference": ("275 kV と描かれた線は西島根~三隅町岡見(三隅発電所の方向)の 1 本。公表の送電線一覧で西島根に"
                      "出る線は 500 kV 3 本と 110 kV 2 本で、220 kV 側の相手は公表の線に無い = 発電所側の電源線と"
                      "考えるのが自然(500/220 kV の 3 台の容量も三隅発電所 2 基分に見合う)。よって 220 kV とした。"
                      "「275 kV ではない」は確か、「220 kV である」は推論"),
        "osm_note": "OSM の該当 way の voltage=275000 は 220000 の誤りの可能性が高い(OSM への修正候補)",
    },
]


def kv_tag(kv: float) -> str:
    return f"{kv:g}"


def component(nodes, edges, start_idx, kv):
    """start から kv の枝だけでたどれる節点(座標キー)と枝の添字。"""
    key = lambda lat, lon: (round(lat, 5), round(lon, 5))          # noqa: E731
    adj = defaultdict(list)
    for ei, e in enumerate(edges):
        if abs(float(e.get("kv") or 0) - kv) > 0.5:
            continue
        a, b = key(*e["a"]), key(*e["b"])
        adj[a].append((b, ei))
        adj[b].append((a, ei))
    s = key(nodes[start_idx]["lat"], nodes[start_idx]["lon"])
    seen, ed, stack = {s}, set(), [s]
    while stack:
        u = stack.pop()
        for v, ei in adj[u]:
            ed.add(ei)
            if v not in seen:
                seen.add(v)
                stack.append(v)
    return seen, ed


def apply(built, write_log=print):
    nodes, edges = built["nodes"], built["edges"]
    ids = {n["id"] for n in nodes}
    n_nodes = n_edges = 0
    for c in CORRECTIONS:
        if c["status"] != "approved":
            write_log(f"  [hold] {c['id']}")
            continue
        start = [i for i, n in enumerate(nodes)
                 if n.get("region") == c["region"] and c["site"] in (n.get("name") or "")
                 and abs(float(n.get("kv") or 0) - c["from_kv"]) < 0.5]
        if not start:
            write_log(f"  [skip] {c['id']}: {c['site']} の {kv_tag(c['from_kv'])} kV 節点が無い(当て済みか、モデルが変わった)")
            continue
        comp, eds = component(nodes, edges, start[0], c["from_kv"])
        targets = [i for i, n in enumerate(nodes) if (round(n["lat"], 5), round(n["lon"], 5)) in comp
                   and abs(float(n.get("kv") or 0) - c["from_kv"]) < 0.5]
        if len(targets) > c["max_nodes"]:
            write_log(f"  [stop] {c['id']}: {kv_tag(c['from_kv'])} kV の成分が {len(targets)} 節点(上限 {c['max_nodes']})")
            continue
        old, new = f"@{kv_tag(c['from_kv'])}", f"@{kv_tag(c['to_kv'])}"
        for i in targets:
            n = nodes[i]
            nid = n["id"].replace(old, new) if n["id"].endswith(old) else n["id"]
            if nid != n["id"] and nid in ids:
                write_log(f"  [stop] {c['id']}: ID {nid} が既にある")
                break
            ids.discard(n["id"])
            ids.add(nid)
            n.update({"id": nid, "kv": c["to_kv"],
                      "name": re.sub(rf"\b{kv_tag(c['from_kv'])}kV\b", f"{kv_tag(c['to_kv'])}kV", n.get("name") or ""),
                      "kv_corrected": {"from_kv": c["from_kv"], "by": c["id"]}})
            n_nodes += 1
        for ei in eds:
            e = edges[ei]
            e.update({"kv": c["to_kv"],
                      "name": (e.get("name") or "").replace(f"{kv_tag(c['from_kv'])}kV", f"{kv_tag(c['to_kv'])}kV"),
                      "kv_corrected": {"from_kv": c["from_kv"], "by": c["id"]}})
            n_edges += 1
        write_log(f"  [apply] {c['id']}: {c['site']} {kv_tag(c['from_kv'])}→{kv_tag(c['to_kv'])} kV "
                  f"節点 {len(targets)}・枝 {len(eds)}")
    return n_nodes, n_edges


def revert(built, write_log=print):
    n = 0
    for x in built["nodes"] + built["edges"]:
        kc = x.pop("kv_corrected", None)
        if not kc:
            continue
        to, frm = float(x["kv"]), kc["from_kv"]
        x["kv"] = frm
        if "id" in x and x["id"].endswith(f"@{kv_tag(to)}"):
            x["id"] = x["id"][: -len(f"@{kv_tag(to)}")] + f"@{kv_tag(frm)}"
        x["name"] = (x.get("name") or "").replace(f"{kv_tag(to)}kV", f"{kv_tag(frm)}kV")
        n += 1
    write_log(f"  [revert] {n} 件を元の電圧に戻した")
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()
    built = json.loads(BUILT.read_text())
    if a.revert:
        revert(built)
    else:
        n_nodes, n_edges = apply(built)
        print(f"介入#51 voltage-corrections: 節点 {n_nodes}・枝 {n_edges} の電圧を直す")
    if a.write:
        BUILT.write_text(json.dumps(built, ensure_ascii=False))
        print(f"-> {BUILT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
