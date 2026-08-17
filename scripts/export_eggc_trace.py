#!/usr/bin/env python3
"""EGGC(証拠ゲート付き系統コンフレーション)の適用過程を、教材用に**実データで**書き出す。

`route_disclosure_edges.py` は採否の結果だけを台帳に残す(置換12/直線維持78)。
本スクリプトは同じ判定を再走させ、教材が必要とする**過程**を足して出す:

  - 端点スナップの候補(なぜその頂点に付いたか)
  - Dijkstraが実際に通った**経路ポリライン**(OSM実線形そのもの)
  - 経路を構成する各エッジの main / off-main 内訳(=証拠ゲートの分母分子)
  - 周辺OSM線のジオメトリ(代表ケースのみ・before/after描画の背景)

出力: docs/data/eggc_trace.json (docs/tools/eggc_explainer.html が読む)
判定ロジックは本家と同一。パラメータも本家から取り込む(乖離したら教材が嘘になる)。
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

BUILT = ROOT / "docs/data/built/all.json"
LEDGER = ROOT / "docs/reports/routed_disclosure_edges.json"
OUT = ROOT / "docs/data/eggc_trace.json"

SYNTH_KEYS = ("disclosure", "conn_class", "tie", "same_site", "dc_tie")
R_STUB_KM = 2.0
MAX_RATIO = 2.0
OFF_SHARE_MIN = 0.7
OFF_SHARE_KEEP = 0.3   # レポートの「<0.3は別線迂回」記述に対応する分類境界

MARGIN_KM = 6.0        # 代表ケースの背景として切り出す周辺エッジの余白


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


def r6(p):
    return [round(p[0], 6), round(p[1], 6)]


def route(adj, grid, A, B):
    """本家 route() と同じ探索。加えて **頂点列** と探索の広がりを返す。"""
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
        return None, {"starts": len(starts), "goals": len(goals), "settled": 0}
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
    diag = {"starts": len(starts), "goals": len(goals), "settled": len(dist)}
    if hit is None:
        return None, diag
    # 経路を頂点列とエッジ列で復元(本家は集合だけ)
    verts, used = [hit], []
    v = hit
    while prev.get(v) and prev[v][0] is not None:
        used.append(prev[v][1])
        v = prev[v][0]
        verts.append(v)
    verts.reverse()
    used.reverse()
    total = dist[hit] + gd[hit]
    return (total, used, verts, verts[0], hit, sd[verts[0]], gd[hit]), diag


def polyline(osm_edges, verts, used):
    """頂点列に沿ってエッジの実ジオメトリを向きを揃えて連結する。"""
    pts = []
    for i, ei in enumerate(used):
        e = osm_edges[ei]
        p = [list(x) for x in (e.get("path") or [e["a"], e["b"]])]
        # 進行方向 verts[i] -> verts[i+1] に合わせる
        if k5(p[0]) != k5(verts[i]):
            p.reverse()
        if pts and k5(pts[-1]) == k5(p[0]):
            p = p[1:]
        pts.extend(p)
    return [r6(p) for p in pts]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=int, default=10,
                    help="周辺ジオメトリを同梱する代表ケース数")
    ap.add_argument("--built", type=Path, default=None,
                    help="入力の正典。**EGGC適用前**のスナップショット"
                         "(all.json.pre_route.bak)を指すこと。省略時は現行正典"
                         "＝適用後なので、断片が既にmain化していて証拠ゲートは"
                         "ほぼ閉じる(冪等性の裏返し)")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    src = args.built or BUILT
    out_path = args.out or OUT
    pre = "pre_route" in src.name
    built = json.loads(src.read_text(encoding="utf-8"))
    nodes, edges = built["nodes"], built["edges"]
    print(f"入力: {src.name} ({'適用前' if pre else '適用後'})")

    osm_edges = [e for e in edges
                 if not any(kk in e for kk in SYNTH_KEYS) and not e.get("stub")]
    live = [e for e in edges
            if ("disclosure" in e or "conn_class" in e)
            and "same_site" not in e and "dc_tie" not in e
            and not e.get("stub") and hav(e["a"], e["b"]) > 0.05]
    if pre:
        targets = [dict(e) for e in live]      # 適用前＝コードはまだ全部直線
        print(f"対象コード {len(targets)} 本")
    else:
        # 適用後の正典には置換済みのコードが無いので台帳から書き戻す(参考再走用)
        ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        restored = [{"name": r["name"], "kv": r.get("kv"),
                     "conn_class": r.get("conn_class"), "a": r["a"], "b": r["b"]}
                    for r in ledger.get("replaced", [])]
        targets = restored + [dict(e) for e in live]
        print(f"対象コード {len(targets)} 本 (台帳復元 {len(restored)} + 現行 {len(live)})")

    adj = defaultdict(list)
    for i, e in enumerate(osm_edges):
        ka, kb = k5(e["a"]), k5(e["b"])
        w = edge_km(e)
        adj[ka].append((kb, w, i))
        adj[kb].append((ka, w, i))
    grid = defaultdict(list)
    for v in adj:
        grid[(int(v[0] / 0.02), int(v[1] / 0.02))].append(v)

    recs = []
    for t in targets:
        A, B = t["a"], t["b"]
        chord = hav(A, B)
        r, diag = route(adj, grid, A, B)
        rec = {"name": t.get("name") or "(無名)", "kv": t.get("kv"),
               "conn_class": t.get("conn_class"),
               "a": r6(A), "b": r6(B), "chord_km": round(chord, 2),
               "settled": diag["settled"], "n_start": diag["starts"],
               "n_goal": diag["goals"]}
        if r is None:
            rec.update(verdict="no_route", reason="OSM経路なし(未収載)")
            recs.append(rec)
            continue
        total, used, verts, vA, vB, stub_a, stub_b = r
        parts = []
        off = tot = 0.0
        for ei in used:
            e = osm_edges[ei]
            km = edge_km(e)
            is_main = bool(e.get("main"))
            tot += km
            if not is_main:
                off += km
            parts.append({"km": round(km, 2), "main": is_main,
                          "kv": e.get("kv"), "name": e.get("name")})
        share = off / (tot or 1e-9)
        ratio = total / max(chord, 0.1)
        if ratio > MAX_RATIO:
            verdict, reason = "kept_detour", f"迂回過大 x{ratio:.2f}"
        elif share < OFF_SHARE_MIN:
            verdict = "kept_detour"
            reason = (f"別線迂回(off-main比率{share:.2f})=公表線はOSM未収載"
                      if share < OFF_SHARE_KEEP
                      else f"証拠不足(off-main比率{share:.2f} < {OFF_SHARE_MIN})")
        else:
            verdict, reason = "replaced", f"断片=公表線(off-main比率{share:.2f})"
        rec.update(verdict=verdict, reason=reason,
                   route_km=round(total, 2), ratio=round(ratio, 3),
                   off_main_share=round(share, 3),
                   n_edges=len(used), n_off=sum(1 for p in parts if not p["main"]),
                   stub_a_km=round(stub_a, 3), stub_b_km=round(stub_b, 3),
                   vA=r6(vA), vB=r6(vB),
                   path=polyline(osm_edges, verts, used),
                   parts=parts)
        recs.append(rec)

    n_rep = sum(1 for r in recs if r["verdict"] == "replaced")
    n_det = sum(1 for r in recs if r["verdict"] == "kept_detour")
    n_non = sum(1 for r in recs if r["verdict"] == "no_route")
    print(f"  吸着 {n_rep} / 別線迂回 {n_det} / 経路なし {n_non}")

    # --- 代表ケース: 吸着の上位 + 迂回 + 経路なし を混ぜ、周辺線を同梱 ---
    # 吸着は全件(採用の実例が教材の主役)。棄却側は「経路は在るのに落ちた」例を選ぶ
    # ——n_edges=0 の棄却(両端が同じ頂点に寄っただけ)は絵にならないので除く
    reps = sorted([r for r in recs if r["verdict"] == "replaced"],
                  key=lambda r: (-r["off_main_share"], -r["chord_km"]))
    dets = sorted([r for r in recs
                   if r["verdict"] == "kept_detour" and r.get("n_edges", 0) >= 2],
                  key=lambda r: (-r["route_km"], r["off_main_share"]))
    nons = sorted([r for r in recs if r["verdict"] == "no_route"],
                  key=lambda r: -r["chord_km"])
    picked = reps[:args.cases] + dets[:3] + nons[:1]

    for rec in picked:
        pts = [rec["a"], rec["b"]] + rec.get("path", [])
        lat0 = sum(p[0] for p in pts) / len(pts)
        dlat = MARGIN_KM / 111.0
        dlon = MARGIN_KM / (111.0 * max(0.2, math.cos(math.radians(lat0))))
        la = [min(p[0] for p in pts) - dlat, max(p[0] for p in pts) + dlat]
        lo = [min(p[1] for p in pts) - dlon, max(p[1] for p in pts) + dlon]
        near_edges = []
        for e in osm_edges:
            p = e.get("path") or [e["a"], e["b"]]
            if not any(la[0] <= q[0] <= la[1] and lo[0] <= q[1] <= lo[1] for q in p):
                continue
            # 頂点キーは **本家と同じ e["a"]/e["b"] の k5** を文字列で持たせる。
            # path の端点で代用すると、path が a/b と厳密一致しないエッジで
            # グラフが切れる(ブラウザ側の探索が本家と違う答えを出す)。
            near_edges.append({"path": [r6(q) for q in p],
                               "ka": "{},{}".format(*k5(e["a"])),
                               "kb": "{},{}".format(*k5(e["b"])),
                               "pa": r6(e["a"]), "pb": r6(e["b"]),
                               "main": bool(e.get("main")),
                               "kv": e.get("kv"), "name": e.get("name")})
        near_nodes = [{"lat": round(n["lat"], 6), "lon": round(n["lon"], 6),
                       "name": n.get("name"), "kv": n.get("kv"),
                       "main": bool(n.get("main"))}
                      for n in nodes
                      if la[0] <= n["lat"] <= la[1] and lo[0] <= n["lon"] <= lo[1]]
        rec["scene"] = {"bbox": [la[0], lo[0], la[1], lo[1]],
                        "edges": near_edges, "nodes": near_nodes[:400]}
        print(f"  代表 {rec['name'][:22]:22} 周辺線 {len(near_edges):4d} / "
              f"ノード {len(near_nodes):3d}")

    # 全体の散布(証拠ゲートの効き)は軽い要約だけ持たせる
    summary = [{"name": r["name"], "kv": r.get("kv"),
                "chord_km": r["chord_km"], "verdict": r["verdict"],
                "off": r.get("off_main_share"), "ratio": r.get("ratio"),
                "route_km": r.get("route_km"),
                "a": r["a"], "b": r["b"]} for r in recs]

    slim = []
    for r in recs:
        d = dict(r)
        if "scene" not in d:
            d.pop("path", None)
            d.pop("parts", None)
        slim.append(d)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "note": "EGGC(証拠ゲート付き系統コンフレーション)の過程トレース。"
                "scene付き=代表ケース(周辺OSM線を同梱)。判定は route_disclosure_edges.py と同一",
        "source": src.name, "applied_state": "pre" if pre else "post",
        "params": {"stub_km": R_STUB_KM, "max_ratio": MAX_RATIO,
                   "off_share_min": OFF_SHARE_MIN, "off_share_keep": OFF_SHARE_KEEP},
        "stats": {"n_targets": len(recs), "n_replaced": n_rep,
                  "n_kept_detour": n_det, "n_no_route": n_non,
                  "n_cases": len(picked)},
        "cases": [r["name"] for r in picked],
        "summary": summary,
        "records": slim,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    mb = out_path.stat().st_size / 1e6
    print(f"出力: {out_path} ({mb:.1f} MB) 代表 {len(picked)} 件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
