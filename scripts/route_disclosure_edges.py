#!/usr/bin/env python3
"""実証接続(直線コード)をOSM実線形へ吸着する — 断片=公表線そのもの の場合のみ。

オーナー指摘(2026-08-16)「ちゃんと線があるものにおいては地形的に線を辿ってほしい。
これは全部に言えること」への恒久対応。[[feedback_osm_trust]]の
「吸着描画はOSM幾何を一次根拠に」を実証接続にも適用する。

方法:
  各disclosureコード(a—b直線)について、OSM抽出エッジ(合成でないもの)の頂点グラフを
  Dijkstraで辿り、a/b双方の近傍(≤2km)を結ぶ実経路を探す。経路が
  **宙に浮いた断片(off-main)を主体とする(比率≥0.7)** ときだけ、その断片が
  「公表線そのもの」だと判断し、コードを両端の取付スタブ2本に置換する
  （断片は次のmain再計算で本系統に合流=地形どおりの線形で繋がる）。

  経路が本系統の別線を迂回するだけの場合(off-main比率<0.3)は、公表線がOSM未収載
  ということなので**直線コードを維持**する(無い線形を捏造しない)。

冪等: 置換済みスタブ(stub:true)は対象外・再実行で変化なし。
可逆: BAK(all.json.pre_route.bak) / regenerate_all のSTEPSから外す / git。
台帳: 置換の全記録を docs/reports/routed_disclosure_edges.json に書く。
"""
from __future__ import annotations

import argparse
import heapq
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.powerflow.connectivity import compute_connectivity  # noqa: E402

BUILT = ROOT / "docs/data/built/all.json"
BAK = BUILT.with_suffix(".json.pre_route.bak")
REPORT = ROOT / "docs/reports/routed_disclosure_edges.json"

SYNTH_KEYS = ("disclosure", "conn_class", "tie", "same_site", "dc_tie")
R_STUB_KM = 2.0      # 取付スタブの最大長
MAX_RATIO = 2.0      # 経路/直線の迂回上限(断片主体なら実線形なので緩め)
OFF_SHARE_MIN = 0.7  # 経路のoff-main長比率がこれ以上=断片が公表線そのもの


def hav(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    return 6371 * 2 * math.asin(math.sqrt(
        math.sin((la2 - la1) / 2) ** 2
        + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2))


def edge_km(e) -> float:
    p = e.get("path") or [e["a"], e["b"]]
    return sum(hav(p[i], p[i + 1]) for i in range(len(p) - 1))


def k5(p):
    return (round(p[0], 5), round(p[1], 5))


def route(adj, grid, osm_edges, A, B):
    """A近傍→B近傍の最短路。(総km, 経路エッジidx集合, vA, vB, stubA, stubB) or None"""
    def near(p):
        cx, cy = int(p[0] / 0.02), int(p[1] / 0.02)
        out = []
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                for v in grid.get((cx + dx, cy + dy), []):
                    dk = hav(p, v)
                    if dk <= R_STUB_KM:
                        out.append((dk, v))
        return sorted(out)[:16]

    starts, goals = near(A), near(B)
    if not starts or not goals:
        return None
    gd = {v: dk for dk, v in sorted(goals, reverse=True)}
    sd = {v: dk for dk, v in sorted(starts, reverse=True)}
    chord = hav(A, B)
    limit = max(chord * MAX_RATIO * 1.5, chord + 15)

    dist: dict = {}
    prev: dict = {}
    seq = 0
    pq = []
    for dk, v in starts:
        pq.append((dk, seq, v, None, None))
        seq += 1
    heapq.heapify(pq)
    hit = None
    while pq:
        dcur, _, v, pv, ei = heapq.heappop(pq)
        if v in dist:
            continue
        dist[v] = dcur
        prev[v] = (pv, ei)
        if dcur > limit:
            break
        if v in gd:
            hit = v
            break
        for w, wt, wi in adj[v]:
            if w not in dist:
                seq += 1
                heapq.heappush(pq, (dcur + wt, seq, w, v, wi))
    if hit is None:
        return None
    used = []
    v = hit
    while prev.get(v) and prev[v][0] is not None:
        used.append(prev[v][1])
        v = prev[v][0]
    v_start = v
    total = dist[hit] + gd[hit]
    return total, set(used), v_start, hit, sd[v_start], gd[hit]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="正典 all.json に適用（可逆）")
    args = ap.parse_args()

    built = json.loads(BUILT.read_text(encoding="utf-8"))
    nodes, edges = built["nodes"], built["edges"]

    osm_edges = [e for e in edges
                 if not any(kk in e for kk in SYNTH_KEYS) and not e.get("stub")]
    targets = [e for e in edges
               if ("disclosure" in e or "conn_class" in e)
               and "same_site" not in e and "dc_tie" not in e
               and not e.get("stub") and hav(e["a"], e["b"]) > 0.05]

    adj = defaultdict(list)
    for i, e in enumerate(osm_edges):
        ka, kb = k5(e["a"]), k5(e["b"])
        w = edge_km(e)
        adj[ka].append((kb, w, i))
        adj[kb].append((ka, w, i))
    grid = defaultdict(list)
    for v in adj:
        grid[(int(v[0] / 0.02), int(v[1] / 0.02))].append(v)

    replaced, kept = [], []
    new_stubs = []
    drop = set()
    for t in targets:
        A, B = t["a"], t["b"]
        chord = hav(A, B)
        r = route(adj, grid, osm_edges, A, B)
        reason = None
        if r is None:
            reason = "OSM経路なし(未収載)"
        else:
            total, used, vA, vB, stub_a, stub_b = r
            off = sum(edge_km(osm_edges[i]) for i in used if not osm_edges[i].get("main"))
            tot = sum(edge_km(osm_edges[i]) for i in used) or 1e-9
            share = off / tot
            ratio = total / max(chord, 0.1)
            if ratio > MAX_RATIO:
                reason = f"迂回過大 x{ratio:.2f}"
            elif share < OFF_SHARE_MIN:
                reason = f"別線迂回(off-main比率{share:.2f})=公表線はOSM未収載"
        if reason:
            kept.append({"name": t.get("name"), "chord_km": round(chord, 1),
                         "reason": reason})
            continue

        drop.add(id(t))
        rec = {"name": t.get("name"), "kv": t.get("kv"),
               "conn_class": t.get("conn_class"),
               "chord_km": round(chord, 1), "route_km": round(total, 1),
               "ratio": round(ratio, 2), "off_main_share": round(share, 2),
               "stub_a_km": round(stub_a, 2), "stub_b_km": round(stub_b, 2),
               "a": t["a"], "b": t["b"], "vA": list(vA), "vB": list(vB)}
        replaced.append(rec)
        for (p, v, skm) in ((A, vA, stub_a), (B, vB, stub_b)):
            if skm < 0.001:
                continue          # 端点が断片頂点そのもの=スタブ不要
            new_stubs.append({
                "path": [list(p), list(v)], "a": list(p), "b": list(v),
                "main": True, "par": t.get("par", 1), "kv": t.get("kv", 0),
                "name": f"{t.get('name')}〔取付〕",
                "disclosure": t.get("disclosure", ""),
                **({"conn_class": t["conn_class"]} if t.get("conn_class") else {}),
                "stub": True, "routed_line": t.get("name"),
            })

    print(f"対象 {len(targets)} → 置換 {len(replaced)} / 直線維持 {len(kept)}")
    for r in replaced:
        print(f"  吸着 {r['name'][:26]:26} chord={r['chord_km']:5.1f}km "
              f"→ 実線形 {r['route_km']:5.1f}km (off={r['off_main_share']})")

    # 置換0の再実行(適用済み状態)で台帳を空上書きしない
    # （disclosure帳簿の空上書き事故 2026-08-15 と同族の防波堤）
    if replaced or not REPORT.exists():
        REPORT.write_text(json.dumps({
            "note": "実証接続のOSM実線形吸着。replaced=コードをスタブ2本に置換(断片=公表線)。"
                    "kept=直線維持とその理由(未収載の線形は捏造しない)",
            "params": {"stub_km": R_STUB_KM, "max_ratio": MAX_RATIO,
                       "off_share_min": OFF_SHARE_MIN},
            "replaced": replaced, "kept": kept,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"台帳: {REPORT.relative_to(ROOT)}")
    else:
        print(f"台帳は保持（置換0のため上書きしない）: {REPORT.relative_to(ROOT)}")

    if not args.write:
        print("（正典は不変。適用するなら --write）")
        return 0
    if not replaced:
        print("置換対象なし")
        return 0
    if not BAK.exists():
        BAK.write_text(BUILT.read_text(encoding="utf-8"), encoding="utf-8")

    kept_edges = [e for e in edges if id(e) not in drop] + new_stubs
    cc = compute_connectivity(nodes, kept_edges)
    maink = cc["main_keys"]
    for n in nodes:
        n["main"] = k5((n["lat"], n["lon"])) in maink
    for e in kept_edges:
        e["main"] = k5(e["a"]) in maink and k5(e["b"]) in maink
    built["edges"] = kept_edges
    st = built.setdefault("stats", {})
    st["main_size"] = sum(1 for n in nodes if n["main"])
    st["n_island_nodes"] = sum(1 for n in nodes if not n["main"])
    st["n_components"] = sum(cc["meta"]["components"].values())
    built["routed_disclosure"] = {
        "n_replaced": len(replaced), "n_stubs": len(new_stubs),
        "report": str(REPORT.relative_to(ROOT)),
    }
    BUILT.write_text(json.dumps(built, ensure_ascii=False, separators=(",", ":")),
                     encoding="utf-8")
    print(f"★正典適用: コード{len(replaced)}本→スタブ{len(new_stubs)}本+実線形。"
          f"本系統外ノード={st['n_island_nodes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
