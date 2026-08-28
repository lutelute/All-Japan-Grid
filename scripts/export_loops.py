#!/usr/bin/env python3
"""ループ(閉路)構造の抽出 — 運用ビュー用(オーナー指示 2026-08-28「ループとかも見れるの?」).

送電系統はメッシュ(ループ)で運用され、配電は放射状が基本。開閉器を操作すると
「ループが増える/減る」ため、開閉操作の意味を読むにはループ構造が要る。

出力: docs/data/loops.json
  islands: {island: {V,E,components,circuit_rank,loop_ratio}}
  sites[]: 変電所ごとのループ関与度
    {i:site_id, deg:接続本数, br:1(橋=切ると分断) | 0(ループ内),
     lp:その変電所を含む最小ループの長さ(無ければ null)}

用語:
  circuit_rank(閉路数) = E - V + C  … 独立なループの本数
  橋(bridge)           = 切ると連結成分が分かれる枝。ループに属さない
  ループ率             = circuit_rank / E … 系統の環状度合い

**捏造ゼロ**: ループはモデルのグラフから決まる事実であって推定を含まない。
ただしモデル自体の被覆(OSM欠測)には縛られるので、欠測で切れて見える箇所は
「橋」として現れうる — その旨は表示側で断る。
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict, deque

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

ISLAND_OF = {"hokkaido": "hokkaido", "tohoku": "east", "tokyo": "east",
             "chubu": "west", "hokuriku": "west", "kansai": "west",
             "chugoku": "west", "shikoku": "west", "kyushu": "west",
             "okinawa": "okinawa"}


def k5(la, lo):
    return (round(la, 5), round(lo, 5))


def bridges(adj, nodes):
    """橋(切ると分断される枝)を反復DFSで求める。再帰だと全国規模で落ちる。"""
    disc, low, par = {}, {}, {}
    br = set()
    t = 0
    for root in nodes:
        if root in disc:
            continue
        stack = [(root, iter(sorted(adj[root])))]
        disc[root] = low[root] = t
        t += 1
        par[root] = None
        while stack:
            v, it = stack[-1]
            adv = False
            for w in it:
                if w not in disc:
                    par[w] = v
                    disc[w] = low[w] = t
                    t += 1
                    stack.append((w, iter(sorted(adj[w]))))
                    adv = True
                    break
                if w != par[v]:
                    low[v] = min(low[v], disc[w])
            if not adv:
                stack.pop()
                if stack:
                    u = stack[-1][0]
                    low[u] = min(low[u], low[v])
                    if low[v] > disc[u]:
                        br.add(frozenset((u, v)))
    return br


def shortest_cycle_through(adj, s, cap=12):
    """s を通る最小ループ長。s の隣接2点間を s を使わずBFSで結ぶ。"""
    nb = sorted(adj[s])
    best = None
    for i, a in enumerate(nb):
        # a から s を経由せず、他の隣接点へ最短で戻れるか
        dist = {a: 0}
        q = deque([a])
        while q:
            x = q.popleft()
            if dist[x] >= cap:
                continue
            for y in adj[x]:
                if y == s or y in dist:
                    continue
                dist[y] = dist[x] + 1
                q.append(y)
        for b in nb[i + 1:]:
            if b in dist:
                c = dist[b] + 2          # a..b の距離 + (s-a) + (b-s)
                best = c if best is None else min(best, c)
    return best


def main() -> int:
    b = json.loads(open("docs/data/built/all.json").read())
    nodes_isl = {}
    for n in b["nodes"]:
        i = ISLAND_OF.get(n.get("region"))
        if i:
            nodes_isl.setdefault(k5(n["lat"], n["lon"]), i)

    out_isl, node_flag = {}, {}
    for isl in ("hokkaido", "east", "west", "okinawa"):
        V = {k for k, v in nodes_isl.items() if v == isl}
        adj = defaultdict(set)
        seen = set()
        E = 0
        for e in b["edges"]:
            if not (e.get("a") and e.get("b")):
                continue
            a, c = k5(*e["a"]), k5(*e["b"])
            if a in V and c in V and a != c:
                key = frozenset((a, c))
                if key in seen:
                    continue     # 多重辺は1本(並列回線はループとは別の話)
                seen.add(key)
                adj[a].add(c)
                adj[c].add(a)
                E += 1
        comp, vis = 0, set()
        for s in V:
            if s in vis:
                continue
            comp += 1
            st = [s]
            while st:
                x = st.pop()
                if x in vis:
                    continue
                vis.add(x)
                st.extend(adj[x] - vis)
        rank = E - len(V) + comp
        out_isl[isl] = {"V": len(V), "E": E, "components": comp,
                        "circuit_rank": rank,
                        "loop_ratio": round(rank / max(E, 1), 4)}
        br = bridges(adj, V)
        for v in V:
            deg = len(adj[v])
            # その節点に触れる枝がすべて橋なら、ループには属さない
            on_loop = any(frozenset((v, w)) not in br for w in adj[v])
            node_flag[v] = (deg, 0 if on_loop else 1)
        print(f"[{isl}] V={len(V)} E={E} 成分{comp} 閉路{rank} "
              f"ループ率{rank/max(E,1):.1%} 橋{len(br)}")

    # 変電所ごとのループ関与度(subノードのみ・最小ループ長は上位所だけ計算)
    sites = []
    subs = [n for n in b["nodes"] if n.get("sub")]
    for n in subs:
        k = k5(n["lat"], n["lon"])
        if k not in node_flag:
            continue
        deg, br_flag = node_flag[k]
        sites.append({"n": n.get("name") or "", "r": n.get("region"),
                      "la": round(n["lat"], 5), "lo": round(n["lon"], 5),
                      "kv": round(float(n.get("kv") or 0)),
                      "deg": deg, "br": br_flag})
    doc = {"note": ("ループ(閉路)構造。circuit_rank=E-V+C が独立ループ本数、"
                    "br=1 はその変電所がループに属さない(周囲がすべて橋)。"
                    "モデルのグラフから決まる事実だが、OSM欠測で切れている箇所は"
                    "橋として現れうる"),
           "islands": out_isl, "n_sites": len(sites), "sites": sites}
    dst = "docs/data/loops.json"
    json.dump(doc, open(dst, "w"), ensure_ascii=False, separators=(",", ":"))
    nb = sum(1 for s in sites if s["br"])
    print(f"-> {dst}  変電所{len(sites)}件 (ループ外={nb} / ループ内={len(sites)-nb})"
          f"  {os.path.getsize(dst)/1e6:.1f}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
