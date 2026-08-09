#!/usr/bin/env python3
"""過負荷は「給電のせい」か「網の欠損のせい」かを切り分ける。

ここまでで分かっていること:
  - 需要は無罪（水準 ×1.43/×0.80、空間シェアは実績と ±1.1pt）
  - 線路容量は理論値が運用容量の 1.87〜2.11 倍 → 較正しても過負荷は**増える**
  - 太陽光の既定値 10MW は実容量中央値の 100 倍だが、下げると過負荷は**増える**
    （`whatif_solar_default`: 膨らんだ太陽光は分散電源として過負荷を**隠していた**）

三つとも「発電・需要側をいくら正しても過負荷は減らない」と言っている。
残る容疑者は**網**。そこで過負荷を網の形と突き合わせる。

**結論（先に書く）**: 過負荷は網の欠損ではなく、**電圧階級の取り違え**だった。
east の過負荷 602 本のうち 521 本（86.5%）が 66kV、500kV は **0 本**。
最悪の線は 66kV で 1,144〜2,188 MW を流している。66kV 線が GW 級を流すはずがない。
原因は `attach_generators` が発電所を**電圧を見ずに最寄りの変電所バス**へ繋いでいること
（66kV 変電所は数が桁違いに多いので最寄りはほぼ 66kV になる）。結果、east は
**発電容量の 53.1%（99GW）が 66kV バスに載っている** — 姉崎火力 3,600MW、
川崎火力 3,420MW、横浜火力 2,800MW まで 66kV 接続。実系統ではいずれも 500/275kV 接続。

橋は networkx の位相的定義で数える（LODF が未定義な枝と一致する。行列を読む必要がない）。
並行回線は多重辺として扱うので、2 回線ある区間は橋にならない — これが要点で、
「1 本しか拾えていない区間」だけが橋になる。pandapower が 2 回線を 1 行の
`parallel` 列に畳んでいる点に注意（`branch_graph` の説明を見よ）。

usage:
    python3 scripts/capacity/overload_vs_topology.py --islands hokkaido okinawa
    python3 scripts/capacity/overload_vs_topology.py           # 全4島（DC・約3分）
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
REPORTS = ROOT / "docs" / "reports"


def load_pf():
    path = ROOT / "scripts" / "run_full_powerflow_from_db.py"
    spec = importlib.util.spec_from_file_location("pf_full", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pf_full"] = mod
    spec.loader.exec_module(mod)
    return mod


def branch_graph(net) -> nx.MultiGraph:
    """在役の線・変圧器から多重グラフを作る。

    **要点**: pandapower は同一鉄塔の 2 回線を別の行にせず、1 行の `parallel` 列に
    畳む（インピーダンスを 1/n、容量を n 倍する）。行数だけで数えると 2 回線区間が
    「1 本しかない＝橋」と誤判定される。east は 6,122 行のうち **4,410 行が
    parallel≥2**（3,112 行が 2 回線）なので、この取り違えは橋の数を倍近く水増しする。
    座標潰し・エッジ潰しに続いて**同じ型の誤り（多重度の潰し）を四度目**に踏んだ箇所。
    """
    g = nx.MultiGraph()
    g.add_nodes_from(int(b) for b in net.bus.index)
    for li, r in net.line.iterrows():
        if not r["in_service"]:
            continue
        n_par = max(1, int(r.get("parallel") or 1))
        for c in range(n_par):
            g.add_edge(int(r["from_bus"]), int(r["to_bus"]), key=("line", int(li), c))
    for ti, r in net.trafo.iterrows():
        if not r["in_service"]:
            continue
        n_par = max(1, int(r.get("parallel") or 1))
        for c in range(n_par):
            g.add_edge(int(r["hv_bus"]), int(r["lv_bus"]), key=("trafo", int(ti), c))
    return g


def analyze(pf, island: str, nodes, edges, cfg, pref_gwh,
            site_trafos: bool = False) -> dict:
    t0 = time.time()
    geom: dict = {}
    net, bus_of, bstats = pf.build_island_net(
        island, nodes, edges, pf.ISLAND_FREQ[island], geom,
        dedup_nodes=True, site_trafos=site_trafos, deenergize_unbuilt=False)
    pf.attach_generators(net, bus_of, nodes, island)
    pf.allocate_loads(net, cfg, pref_gwh=pref_gwh)
    from src.powerflow.pipeline import add_reactive_compensation
    add_reactive_compensation(net, factor=cfg.get("reactive_compensation_factor", 0.6))
    pf.add_per_component_slacks(net)
    pf.balance_by_zone(net, cfg)
    net_dc, dc, _a, _b = pf.solve_island(net, max_ac_buses=0)

    g = branch_graph(net_dc)
    bridge_keys = set()
    # nx.bridges は MultiGraph 非対応なので、成分ごとに単純グラフへ落として判定し、
    # 「その端点対に枝が1本しかない」ものだけを橋とする（並行回線は橋でない）。
    pair_count: Counter = Counter()
    for u, v, k in g.edges(keys=True):
        pair_count[(min(u, v), max(u, v))] += 1
    simple = nx.Graph()
    simple.add_nodes_from(g.nodes())
    simple.add_edges_from((u, v) for (u, v), c in pair_count.items() if u != v)
    for u, v in nx.bridges(simple):
        if pair_count[(min(u, v), max(u, v))] == 1:
            bridge_keys.add((min(u, v), max(u, v)))

    # 橋の**重大度**: 取り除いたとき小さい側に何バス残るか。
    # 末端1変電所への引込線も位相上は橋だが、それは実系統にも普通にある。
    # 疑うべきは「網を大きく二分する橋」＝並行ルートが欠けている疑いのある区間。
    #
    # 橋は必ず DFS 木の辺なので、部分木サイズを一度数えれば全橋の分断規模が出る
    # （橋ごとにグラフを複製すると east の 2,287 橋で数分かかる）。
    n_bus_total = simple.number_of_nodes()
    minor_side: dict[tuple[int, int], int] = {}
    for comp in nx.connected_components(simple):
        csize = len(comp)
        root = next(iter(comp))
        parent = {root: None}
        order = []
        stack = [root]
        seen = {root}
        while stack:                       # 反復DFS（再帰は深さで落ちる）
            x = stack.pop()
            order.append(x)
            for y in simple.neighbors(x):
                if y not in seen:
                    seen.add(y)
                    parent[y] = x
                    stack.append(y)
        sub = dict.fromkeys(order, 1)
        for x in reversed(order):          # 葉から根へ足し上げる
            p = parent[x]
            if p is not None:
                sub[p] += sub[x]
        for x in order:
            p = parent[x]
            if p is None:
                continue
            pair = (min(p, x), max(p, x))
            if pair in bridge_keys:
                minor_side[pair] = min(sub[x], csize - sub[x])

    deg = dict(simple.degree())
    rows = []
    for li, r in net_dc.line.iterrows():
        if not r["in_service"] or li not in net_dc.res_line.index:
            continue
        lp = net_dc.res_line.at[li, "loading_percent"]
        if lp != lp:                      # NaN
            continue
        u, v = int(r["from_bus"]), int(r["to_bus"])
        pair = (min(u, v), max(u, v))
        is_br = pair in bridge_keys
        rows.append({
            "idx": int(li), "name": str(r.get("name") or ""),
            "kv": round(float(net_dc.bus.at[u, "vn_kv"]), 1),
            "loading_pct": round(float(lp), 1),
            "p_mw": round(abs(float(net_dc.res_line.at[li, "p_from_mw"])), 1),
            "is_bridge": is_br,
            "minor_side": minor_side.get(pair, 0) if is_br else None,
            "min_deg": min(deg.get(u, 0), deg.get(v, 0)),
            "len_km": round(float(r.get("length_km") or 0), 1),
            "u": u, "v": v,
        })

    # 過負荷線の**迂回路の長さ**: その線を外したとき端点間が何ホップ回り道になるか。
    # 迂回が長い＝並行ルートが実質無い＝その線が単独の回廊になっている。
    #
    # 注意: `simple` は並行回線を 1 本に潰しているので、そのまま辺を外すと
    # **同じ鉄塔の 2 回線目まで一緒に消える**。多重度が 2 以上なら迂回は 1 ホップ
    # （隣に残っている回線）と数える。
    for r in rows:
        if r["loading_pct"] <= 100.0:
            continue
        if r["is_bridge"]:
            r["detour_hops"] = None       # 迂回路そのものが無い
            continue
        if pair_count[(min(r["u"], r["v"]), max(r["u"], r["v"]))] > 1:
            r["detour_hops"] = 1          # 並行回線が同じ区間に残っている
            continue
        had = simple.has_edge(r["u"], r["v"])
        if had:
            simple.remove_edge(r["u"], r["v"])    # 複製せず一時的に外す
        try:
            r["detour_hops"] = nx.shortest_path_length(simple, r["u"], r["v"])
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            r["detour_hops"] = None
        if had:
            simple.add_edge(r["u"], r["v"])

    over = [r for r in rows if r["loading_pct"] > 100.0]
    br = [r for r in rows if r["is_bridge"]]
    me = [r for r in rows if not r["is_bridge"]]
    # 主要橋 = 小さい側が全バスの5%以上、かつ最低10バス（末端引込ではなく網を二分する橋）。
    # 下限を置かないと、沖縄(98バス)では5%=5バスとなり普通の枝葉まで主要橋に入る。
    major_thr = max(0.05 * n_bus_total, 10)
    major = [r for r in br if (r["minor_side"] or 0) >= major_thr]

    def rate(xs):
        return round(sum(1 for x in xs if x["loading_pct"] > 100.0) / len(xs), 4) if xs else 0.0

    by_kv: dict[float, dict] = defaultdict(lambda: {"n": 0, "n_over": 0, "n_bridge": 0})
    for r in rows:
        k = by_kv[r["kv"]]
        k["n"] += 1
        k["n_over"] += r["loading_pct"] > 100.0
        k["n_bridge"] += r["is_bridge"]

    # 発電機がどの電圧階級のバスに載っているか。過負荷の電圧分布と突き合わせる。
    gen_by_kv: dict[float, dict] = defaultdict(lambda: {"n": 0, "mw": 0.0})
    misplaced = []          # 110kV以下に載った 300MW 超の機（実系統ではありえない接続）
    for _gi, gr in net_dc.gen.iterrows():
        kv = round(float(net_dc.bus.at[int(gr["bus"]), "vn_kv"]), 1)
        p = float(gr["max_p_mw"])
        gen_by_kv[kv]["n"] += 1
        gen_by_kv[kv]["mw"] += p
        if p >= 300.0 and kv <= 110.0:
            misplaced.append({"mw": round(p, 1), "kv": kv,
                              "name": str(gr["name"])[:40], "fuel": str(gr["type"])})
    gen_total = sum(v["mw"] for v in gen_by_kv.values()) or 1.0
    misplaced.sort(key=lambda x: -x["mw"])

    hops = [r["detour_hops"] for r in over if r["detour_hops"] is not None]
    return {
        "gen_by_kv": {str(k): {"n": v["n"], "mw": round(v["mw"], 1),
                               "share": round(v["mw"] / gen_total, 4)}
                      for k, v in sorted(gen_by_kv.items())},
        "gen_mw_at_or_below_110kv_share": round(
            sum(v["mw"] for k, v in gen_by_kv.items() if k <= 110.0) / gen_total, 4),
        "n_misplaced_big_gen": len(misplaced),
        "misplaced_big_gen_mw": round(sum(m["mw"] for m in misplaced), 1),
        "misplaced_big_gen": misplaced[:20],
        "island": island, "site_trafos": site_trafos,
        "seconds": round(time.time() - t0, 1),
        "n_bus": bstats["n_bus"], "dc_converged": bool(dc.get("converged")),
        "n_site_trafo": bstats.get("n_site_trafo", 0),
        "median_detour_hops": (sorted(hops)[len(hops) // 2] if hops else None),
        "max_loading_pct": max((r["loading_pct"] for r in rows), default=None),
        "n_line": len(rows), "n_over": len(over),
        "n_bridge": len(br), "bridge_share": round(len(br) / len(rows), 4) if rows else 0,
        "n_major_bridge": len(major),
        "overload_rate_bridge": rate(br),
        "overload_rate_major_bridge": rate(major),
        "overload_rate_meshed": rate(me),
        "over_that_are_bridges": round(
            sum(1 for r in over if r["is_bridge"]) / len(over), 4) if over else 0.0,
        "radial_stub_over": sum(1 for r in over if r["min_deg"] <= 1),
        "detour_hist": dict(Counter(
            ("bridge/迂回なし" if r["detour_hops"] is None else
             "1(並行回線)" if r["detour_hops"] == 1 else
             "2" if r["detour_hops"] == 2 else
             "3-4" if r["detour_hops"] <= 4 else
             "5-9" if r["detour_hops"] <= 9 else "10+")
            for r in over)),
        "by_kv": {str(k): dict(v) for k, v in sorted(by_kv.items())},
        "worst": sorted(over, key=lambda r: -r["loading_pct"])[:15],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="*",
                    default=["hokkaido", "east", "west", "okinawa"])
    ap.add_argument("--with-site-trafos", action="store_true",
                    help="介入#22（同名変電所のヤード連結）を入れた場合も測り、"
                         "迂回の長さと過負荷がどう動くか比較する")
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                                       text=True).stdout.strip()

    pf = load_pf()
    with open(pf.BUILT, encoding="utf-8") as f:
        db = json.load(f)
    nodes, edges = db["nodes"], db["edges"]
    cfg = pf.load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(nodes)

    res = []
    variants = [False, True] if args.with_site_trafos else [False]
    for island in args.islands:
        for st in variants:
            r = analyze(pf, island, nodes, edges, cfg, pref_gwh, site_trafos=st)
            tag = "＋#22" if st else "既定  "
            print(f"[{island:9s}]{tag} 線 {r['n_line']:,} / 橋 {r['n_bridge']:,} "
                  f"({r['bridge_share']:.1%}, うち主要 {r['n_major_bridge']})  "
                  f"過負荷 {r['n_over']:,}  最大 {r['max_loading_pct']}%  "
                  f"迂回中央値 {r['median_detour_hops']}  "
                  f"過負荷率 橋 {r['overload_rate_bridge']:.2%} vs "
                  f"メッシュ {r['overload_rate_meshed']:.2%}  {r['seconds']:.0f}s", flush=True)
            res.append(r)

    (REPORTS / f"overload_vs_topology_{date}.json").write_text(
        json.dumps({"date": date, "islands": res}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    base = [r for r in res if not r["site_trafos"]]
    L = [f"# 過負荷の正体は電圧階級の取り違えだった（{date}）", "",
         "需要は無罪、容量較正では減らず、太陽光を正すと**増える** — ここまでの三つの計測は",
         "どれも「発電・需要側をいくら正しても過負荷は減らない」と言っていた。",
         "残る容疑者の**網**を、過負荷と網の形の突き合わせで検証したところ、",
         "欠損ではなく**繋ぎ先の電圧が違う**ことが分かった。", "",
         "## 結論", "",
         "| 島 | 過負荷 | うち66/77kV | 500kV | 発電容量のうち110kV以下に接続 | 110kV以下の300MW超機 |",
         "|---|---:|---:|---:|---:|---:|"]
    for r in base:
        low = sum(v["n_over"] for k, v in r["by_kv"].items() if float(k) <= 77.0)
        hi = sum(v["n_over"] for k, v in r["by_kv"].items() if float(k) >= 500.0)
        L.append(f"| {r['island']} | {r['n_over']:,} | {low:,} "
                 f"({low / r['n_over']:.0%}) | {hi} | "
                 f"{r['gen_mw_at_or_below_110kv_share']:.1%} | "
                 f"{r['n_misplaced_big_gen']} 台 / {r['misplaced_big_gen_mw']:,.0f} MW |"
                 if r["n_over"] else
                 f"| {r['island']} | 0 | — | — | "
                 f"{r['gen_mw_at_or_below_110kv_share']:.1%} | "
                 f"{r['n_misplaced_big_gen']} 台 / {r['misplaced_big_gen_mw']:,.0f} MW |")
    L += ["",
          "`attach_generators` は発電所を **電圧を見ずに最寄りの変電所バス**へ繋いでいる",
          "（`best = min(sub_bus, key=距離)`）。66kV 変電所は数が桁違いに多いので、",
          "最寄りはほぼ 66kV になる。結果、GW 級の火力・原子力が 66kV 母線に載り、",
          "66kV 線が 1,000MW 超を流すという物理的にありえない潮流が立つ。", "",
          "実系統ではありえない接続の例:", "",
          "| 島 | 発電所 | 出力 | モデルの接続電圧 | 燃料 |", "|---|---|---:|---:|---|"]
    for r in base:
        for m in r["misplaced_big_gen"][:8]:
            L.append(f"| {r['island']} | {m['name']} | {m['mw']:,.0f} MW | "
                     f"{m['kv']} kV | {m['fuel']} |")
    L += ["", "## 発電機の接続バス電圧", "",
          "| 島 | kV | 台数 | 容量 | 割合 |", "|---|---:|---:|---:|---:|"]
    for r in base:
        for kv, v in r["gen_by_kv"].items():
            L.append(f"| {r['island']} | {kv} | {v['n']:,} | {v['mw']:,.0f} MW | "
                     f"{v['share']:.1%} |")
    L += ["", "## 過負荷率: 橋 vs メッシュ", "",
          "念のため網の欠損側も測った。判定軸は **橋** — 取り除くと網が二つに割れる枝。",
          "並行回線は多重辺として扱うので、**1 本しか拾えていない区間だけ**が橋になる。",
          "結果は「過負荷はメッシュ側に偏る」（east 11.4% vs 橋 1.1%）で、",
          "**網が足りないのではない**ことを裏づけた。", "",
          "「主要橋」は取り除くと全バスの 5% 以上が切り離される枝。",
          "末端 1 変電所への引込線も位相上は橋だが、それは実系統にも普通にある。", "",
          "| 島 | 構成 | 線 | 橋 | 主要橋 | 過負荷 | 過負荷率(橋) | 過負荷率(メッシュ) |",
          "|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in res:
        L.append(f"| {r['island']} | {'＋介入#22' if r['site_trafos'] else '既定'} | "
                 f"{r['n_line']:,} | {r['n_bridge']:,} "
                 f"({r['bridge_share']:.1%}) | {r['n_major_bridge']:,} | {r['n_over']:,} | "
                 f"{r['overload_rate_bridge']:.2%} | {r['overload_rate_meshed']:.2%} |")
    L += ["", "## 過負荷線の迂回路の長さ", "",
          "その線を外したとき端点間が何ホップ回り道になるか。2 ホップ＝すぐ隣に並行ルートがある",
          "（＝網は足りていて、潮流の大きさの問題）。長い／無い＝単独の回廊（＝網の欠損）。", "",
          "| 島 | 構成 | 中央値 | " + " | ".join(["bridge/迂回なし", "1(並行回線)", "2", "3-4", "5-9", "10+"]) + " |",
          "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in res:
        h = r["detour_hist"]
        L.append(f"| {r['island']} | {'＋介入#22' if r['site_trafos'] else '既定'} | "
                 f"{r['median_detour_hops']} | " +
                 " | ".join(str(h.get(k, 0)) for k in
                            ["bridge/迂回なし", "1(並行回線)", "2", "3-4", "5-9", "10+"]) + " |")
    L += ["", "## 電圧階級別", "",
          "| 島 | kV | 線 | 橋 | 過負荷 |", "|---|---:|---:|---:|---:|"]
    for r in res:
        if r["site_trafos"]:
            continue
        for kv, v in r["by_kv"].items():
            if v["n"] >= 20:
                L.append(f"| {r['island']} | {kv} | {v['n']:,} | {v['n_bridge']:,} | "
                         f"{v['n_over']:,} |")
    L += ["", "## 最も重い過負荷（島ごと上位）", ""]
    for r in res:
        if not r["worst"] or r["site_trafos"]:
            continue
        L += [f"### {r['island']}", "",
              "| 線 | kV | 負荷率 | 潮流 | 橋 | 端点最小次数 |", "|---|---:|---:|---:|:-:|---:|"]
        for w in r["worst"][:10]:
            L.append(f"| {w['name'][:44]} | {w['kv']} | {w['loading_pct']}% | "
                     f"{w['p_mw']:,.0f} MW | {'✔' if w['is_bridge'] else ''} | {w['min_deg']} |")
        L.append("")
    L += ["---", "生成: `scripts/capacity/overload_vs_topology.py`（DC・介入#19/#20/#21 既定ON相当）", ""]
    (REPORTS / f"overload_vs_topology_{date}.md").write_text("\n".join(L), encoding="utf-8")
    print(f"→ docs/reports/overload_vs_topology_{date}.md")


if __name__ == "__main__":
    main()
