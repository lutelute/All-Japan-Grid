#!/usr/bin/env python3
"""変電所を「構造だけ」で類型に分ける — エゴグラフ特徴空間の拡張とグルーピング。

## なぜ拡張するか

既存の `vectorize_substations.py` は 35 次元・5 ブロックで、**すべて 1 ホップの
トポロジ＋電圧**しか見ていない。あれは built ↔ keitouzu の**照合**用に
「両ソースが同じ軸を出せる」ことを優先した設計なので、keitouzu が持たない情報
（並列回線数・線路長・下位網）は入れられない。軸を揃える制約はそちらに残す。

本スクリプトは **built 専用**なので、その制約から自由になれる。照合ではなく
**グルーピング（類型発見）**が目的で、次の 6 ブロック 18 次元を足して 53 次元にする:

  A 並列度      par_sum / par_max / 2回線以上の割合
                ← `par` はこの系列で**5 回取り違えた**列。特徴に入れていなかった
  B 電気的容量  接続枝の合計/最大/中央 MVA（max_i_ka×kV×√3×par・モデルと同じ導体定数）
                ← 「どれだけ太い管か」。今日の接続規則 cap が使ったのと同じ量
  C 2ホップ     hop2 の変電所数と、その電圧構成（≥275 / ≥154 / ≤77 の割合）
                ← 1ホップだけでは「基幹に隣接する末端」と「末端に隣接する末端」が同じに見える
  D 役割        クラスタ係数・関節点か・接続枝のうち橋の数
                ← 冗長性。橋だらけの変電所は落ちると系統が割れる
  E 位置づけ    最大成分に載っているか・連系線に触れているか
  F 幾何由来    接続線路長の min/中央/max（**別ブロック**）
                ← 座標そのものではなく回転・平行移動に不変な量だが、幾何由来なので
                  「名前も座標も使わない」を厳密に保ちたいときは `--no-geometry` で外す

## 出すもの

k-means で類型に分け、各クラスタを**素の統計で**特徴づける（何次元目が大きい、では
人が読めない）。クラスタ数は silhouette で選ぶ。

usage:
    python3 scripts/toporag/cluster_substations.py
    python3 scripts/toporag/cluster_substations.py --no-geometry --k 8
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import networkx as nx
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
REPORTS = ROOT / "docs" / "reports"

from src.topology.coords import CoordIndex  # noqa: E402
from vectorize_substations import (  # noqa: E402
    BLOCKS, FEATURE_NAMES, from_built, kv_index, l2_normalize,
)

BUILT = ROOT / "docs" / "data" / "built" / "all.json"

RICH_NAMES = (
    ["par_sum", "par_max", "par_multi_share"]                       # A
    + ["mva_total", "mva_max", "mva_med"]                           # B
    + ["hop2_n", "hop2_share_ge275", "hop2_share_ge154", "hop2_share_le77"]  # C
    + ["clustering", "is_articulation", "n_bridge_incident"]        # D
    + ["on_main", "touches_tie"]                                    # E
    + ["len_min_km", "len_med_km", "len_max_km"]                    # F（幾何由来）
)
RICH_BLOCKS = {
    "並列度": (0, 3), "電気的容量": (3, 6), "2ホップ構造": (6, 10),
    "役割(冗長性)": (10, 13), "位置づけ": (13, 15), "線路長(幾何由来)": (15, 18),
}
GEOMETRY_BLOCK = "線路長(幾何由来)"


def _haversine_km(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def _path_km(e) -> float:
    p = e.get("path")
    if p and len(p) >= 2:
        return sum(_haversine_km(p[i], p[i + 1]) for i in range(len(p) - 1))
    return _haversine_km(e["a"], e["b"])


def _rated_mva(kv: float, par: int) -> float:
    """モデルと同じ導体定数から 1 区間の定格 MVA。`par` を必ず掛ける。"""
    from src.converter.line_parameters import get_line_parameters_safe
    prm = get_line_parameters_safe(kv, 50.0)
    if not prm:
        return 0.0
    return float(prm.get("max_i_ka", 0.0)) * kv * math.sqrt(3.0) * max(1, par)


def rich_features(ids: list[str]) -> np.ndarray:
    """built から拡張ブロックを作る。ids は from_built と同じ base id 並び。"""
    built = json.load(open(BUILT))
    nodes, edges = built["nodes"], built["edges"]
    ix = CoordIndex(nodes)
    base_of = {n["id"]: n["id"].split("@")[0] for n in nodes}
    node_main = {n["id"].split("@")[0]: int(n.get("main") or 0) for n in nodes}

    # 変電所グラフ（jct を潰して sub 同士を繋ぐ）と、枝ごとの属性
    g = nx.Graph()
    inc: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        kv = e.get("kv") or 0.0
        par = int(e.get("par") or 1)
        try:
            ea, eb = ix.endpoints(e["a"], kv), ix.endpoints(e["b"], kv)
        except Exception:  # noqa: BLE001
            continue
        km = _path_km(e)
        mva = _rated_mva(kv, par) if kv > 0 else 0.0
        for i in ea:
            for j in eb:
                bi, bj = base_of[nodes[i]["id"]], base_of[nodes[j]["id"]]
                if bi == bj:
                    continue
                g.add_edge(bi, bj)
                rec = {"kv": kv, "par": par, "km": km, "mva": mva,
                       "tie": bool(e.get("tie"))}
                inc[bi].append(rec)
                inc[bj].append(rec)

    bridges = set(nx.bridges(g)) if g.number_of_edges() else set()
    bridge_deg: dict[str, int] = defaultdict(int)
    for u, v in bridges:
        bridge_deg[u] += 1
        bridge_deg[v] += 1
    arts = set(nx.articulation_points(g)) if g.number_of_nodes() else set()
    clus = nx.clustering(g) if g.number_of_nodes() else {}
    maxkv: dict[str, float] = defaultdict(float)
    for n in nodes:
        b = base_of[n["id"]]
        maxkv[b] = max(maxkv[b], float(n.get("kv") or 0.0))

    rows = []
    for b in ids:
        E = inc.get(b, [])
        pars = [r["par"] for r in E] or [0]
        mvas = [r["mva"] for r in E] or [0.0]
        kms = [r["km"] for r in E] or [0.0]
        hop2 = set()
        for nb in g.neighbors(b) if b in g else ():
            hop2 |= set(g.neighbors(nb))
        hop2.discard(b)
        hop2 -= set(g.neighbors(b)) if b in g else set()
        h2 = [maxkv.get(x, 0.0) for x in hop2] or [0.0]
        n2 = max(len(hop2), 1)
        rows.append([
            math.log1p(sum(pars)), float(max(pars)),
            sum(1 for p in pars if p >= 2) / max(len(pars), 1),
            math.log1p(sum(mvas)), math.log1p(max(mvas)), math.log1p(float(np.median(mvas))),
            math.log1p(len(hop2)),
            sum(1 for k in h2 if k >= 275) / n2,
            sum(1 for k in h2 if k >= 154) / n2,
            sum(1 for k in h2 if 0 < k <= 77) / n2,
            float(clus.get(b, 0.0)), 1.0 if b in arts else 0.0,
            math.log1p(bridge_deg.get(b, 0)),
            float(node_main.get(b, 0)),
            1.0 if any(r["tie"] for r in E) else 0.0,
            math.log1p(min(kms)), math.log1p(float(np.median(kms))), math.log1p(max(kms)),
        ])
    return np.asarray(rows, dtype=float)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=0, help="0=silhouette で自動選択")
    ap.add_argument("--k-range", nargs=2, type=int, default=[4, 12])
    ap.add_argument("--no-geometry", action="store_true",
                    help="幾何由来ブロック（線路長）を外す")
    ap.add_argument("--no-voltage", action="store_true",
                    help="**電圧の身元**を外して形と役割だけで分ける。基本35次元のうち30次元が"
                         "電圧の one-hot/ヒストグラムなので、素のままだと類型が"
                         "「電圧階級ごとに1つ」に潰れる。外すと階級を跨いだ類型が出る")
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                                       text=True).stdout.strip()

    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    F = from_built()
    ids, X0 = F.vectors()
    print(f"基本特徴 {X0.shape[1]} 次元 / {len(ids):,} 変電所", flush=True)
    X1 = rich_features(ids)
    names = list(FEATURE_NAMES) + list(RICH_NAMES)
    blocks = dict(BLOCKS)
    off = X0.shape[1]
    for k, (a, b) in RICH_BLOCKS.items():
        blocks[k] = (off + a, off + b)
    X = np.hstack([X0, X1])
    drop_blocks = []
    if args.no_geometry:
        drop_blocks.append(GEOMETRY_BLOCK)
    if args.no_voltage:
        # 電圧の身元そのもの（1/0・階級別次数・隣接の階級ヒスト）だけを落とす。
        # 「層数・規模」「隣接の次数」「2ホップの電圧**割合**」は形の情報なので残す。
        drop_blocks += ["電圧構成(1/0)", "階級別次数", "隣接変電所の電圧"]
    if drop_blocks:
        drop = set()
        for nm in drop_blocks:
            a, b = blocks.pop(nm)
            drop |= set(range(a, b))
        keep = [i for i in range(X.shape[1]) if i not in drop]
        # 残したブロックの添字を詰め直す
        remap = {old: new for new, old in enumerate(keep)}
        blocks = {k: (remap[a], remap[b - 1] + 1) for k, (a, b) in blocks.items()
                  if a in remap}
        X = X[:, keep]
        names = [names[i] for i in keep]
    print(f"拡張後 {X.shape[1]} 次元（ブロック: {', '.join(blocks)}）", flush=True)

    # 標準化（ブロック間でスケールが違うので z 化してから）
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    Z = (X - mu) / sd

    ks, scores = [], []
    if args.k:
        best_k = args.k
    else:
        sample = np.random.default_rng(0).choice(len(Z), size=min(4000, len(Z)),
                                                 replace=False)
        for k in range(args.k_range[0], args.k_range[1] + 1):
            km = KMeans(n_clusters=k, n_init=4, random_state=0).fit(Z)
            s = silhouette_score(Z[sample], km.labels_[sample])
            ks.append(k); scores.append(s)
            print(f"  k={k:2d} silhouette={s:.4f}", flush=True)
        best_k = ks[int(np.argmax(scores))]
    km = KMeans(n_clusters=best_k, n_init=10, random_state=0).fit(Z)
    lab = km.labels_
    print(f"→ k={best_k}", flush=True)

    # クラスタを**素の統計**で特徴づける（次元番号では人が読めない）
    raw = {"max_kv": np.array([F.max_kv.get(i, 0.0) for i in ids]),
           "n_layer": np.array([len(F.layers_kv[i]) for i in ids]),
           "deg": np.array([float(F.deg_kv[i].sum()) for i in ids]),
           "n_nbr": np.array([len(F.nbrs[i]) for i in ids])}
    ridx = {n: j for j, n in enumerate(RICH_NAMES)}
    for nm in ("mva_total", "par_max", "hop2_n", "n_bridge_incident",
               "is_articulation", "on_main", "touches_tie", "clustering"):
        raw[nm] = X1[:, ridx[nm]]

    out = []
    for c in range(best_k):
        m = lab == c
        rec = {"cluster": int(c), "n": int(m.sum()),
               "share": round(float(m.mean()), 4)}
        for nm, v in raw.items():
            rec[nm] = round(float(np.median(v[m])), 3)
        rec["regions"] = dict(sorted(
            {r: int(sum(1 for i, s in enumerate(ids)
                        if m[i] and F.region.get(s) == r))
             for r in set(F.region.values())}.items(),
            key=lambda x: -x[1])[:3])
        rec["examples"] = [F.name.get(ids[i], ids[i])
                           for i in np.where(m)[0][:4]]
        out.append(rec)
    out.sort(key=lambda r: -r["max_kv"])

    payload = {"date": date, "n_sub": len(ids), "n_feature": int(X.shape[1]),
               "blocks": {k: list(v) for k, v in blocks.items()},
               "geometry_included": not args.no_geometry,
               "k": best_k, "silhouette": dict(zip(map(str, ks), map(float, scores))),
               "clusters": out}
    (REPORTS / f"substation_clusters_{date}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    L = [f"# 変電所を構造だけで類型に分ける（{date}）", "",
         f"エゴグラフ特徴を **{X0.shape[1]} → {X.shape[1]} 次元**に拡張して "
         f"{len(ids):,} 変電所をクラスタリングした。",
         "既存の 35 次元は built ↔ keitouzu の**照合**用に軸を揃える制約があり、",
         "keitouzu が持たない情報（並列回線数・線路長・下位網）を入れられない。",
         "本レポートは **built 専用のグルーピング**なのでその制約から自由。", "",
         "## 足した特徴", "",
         "| ブロック | 中身 | なぜ |", "|---|---|---|",
         "| 並列度 | par の合計/最大/2回線以上の割合 | `par` はこの系列で**5 回取り違えた**列。特徴に入っていなかった |",
         "| 電気的容量 | 接続枝の合計/最大/中央 MVA | 「どれだけ太い管か」。接続規則 cap と同じ量 |",
         "| 2ホップ構造 | hop2 の変電所数と電圧構成 | 1ホップだけだと「基幹に隣接する末端」と「末端に隣接する末端」が同じに見える |",
         "| 役割(冗長性) | クラスタ係数・関節点・接続する橋の数 | 落ちると系統が割れる点を見分ける |",
         "| 位置づけ | 最大成分に載るか・連系線に触れるか | |",
         "| 線路長(幾何由来) | 接続線路長 min/中央/max | 回転・平行移動に不変だが幾何由来。`--no-geometry` で外せる |",
         "", f"（幾何ブロック: {'含む' if not args.no_geometry else '**外した**'}）", "",
         "## 見つかった類型", "",
         "| # | 件数 | 割合 | 最高電圧 | 層数 | 次数 | 隣接数 | 合計MVA | 最大par | hop2 | 橋 | 関節点 | 主成分 | 連系 | 例 |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for r in out:
        L.append(
            f"| {r['cluster']} | {r['n']:,} | {r['share']:.1%} | {r['max_kv']:.0f}kV | "
            f"{r['n_layer']:.0f} | {r['deg']:.0f} | {r['n_nbr']:.0f} | "
            f"{math.expm1(r['mva_total']):,.0f} | {r['par_max']:.0f} | "
            f"{math.expm1(r['hop2_n']):.0f} | {math.expm1(r['n_bridge_incident']):.1f} | "
            f"{r['is_articulation']:.0%} | {r['on_main']:.0%} | {r['touches_tie']:.0%} | "
            + "・".join(x for x in r["examples"][:2] if x) + " |")
    L += ["", "（数値はクラスタ内の**中央値**。MVA・hop2・橋は log1p を戻した値）", ""]

    # 類型 × 電圧 の交差表 — 「どの階級にどの型が居るか」が本題
    kvs = sorted({int(v) for v in raw["max_kv"] if v > 0}, reverse=True)
    L += ["## 類型 × 電圧階級", "",
          "電圧を特徴から外して分けたので、**同じ型が複数の階級に跨る**か、",
          "階級ごとに型が偏るかが読める。", "",
          "| 類型 | " + " | ".join(f"{k}kV" for k in kvs) + " | 電圧なし |",
          "|---|" + "---:|" * (len(kvs) + 1)]
    for r in out:
        c = r["cluster"]; m = lab == c
        cells = [int(((raw["max_kv"] == k) & m).sum()) for k in kvs]
        cells.append(int(((raw["max_kv"] == 0) & m).sum()))
        L.append(f"| {c} | " + " | ".join(f"{v:,}" if v else "—" for v in cells) + " |")
    # 交差表から自動で拾える「使いどころ」を名指しする
    art_c = [r["cluster"] for r in out if r["is_articulation"] >= 0.5]
    iso_c = [r["cluster"] for r in out if r["on_main"] < 0.5 and r["deg"] == 0]
    L += ["", "### ここから拾えるもの", ""]
    if art_c:
        mm = np.isin(lab, art_c) & (raw["max_kv"] >= 275)
        nm = [F.name.get(ids[i]) or ids[i] for i in np.where(mm)[0]]
        L += [f"- **基幹（≥275kV）の関節点 {int(mm.sum())} 箇所** — "
              "落ちると系統が割れる単一障害点。N-1 の優先対象:",
              "  " + "・".join(nm[:10]) + ("…" if len(nm) > 10 else ""), ""]
    if iso_c:
        mm = np.isin(lab, iso_c) & (raw["max_kv"] >= 275)
        nm = [F.name.get(ids[i]) or ids[i] for i in np.where(mm)[0]]
        L += [f"- **接続ゼロの高電圧変電所 {int(mm.sum())} 箇所（≥275kV）** — "
              "高電圧なのに枝が 1 本も無い＝**データ欠陥**。接続編集の優先対象:",
              "  " + "・".join(nm[:10]) + ("…" if len(nm) > 10 else ""), ""]
    L += ["", "## 類型 × 地域", "",
          "| 類型 | " + " | ".join(sorted(set(F.region.values()))) + " |",
          "|---|" + "---:|" * len(set(F.region.values()))]
    regs = sorted(set(F.region.values()))
    reg_arr = np.array([F.region.get(i, "") for i in ids])
    for r in out:
        m = lab == r["cluster"]
        L.append(f"| {r['cluster']} | " + " | ".join(
            (lambda v: f"{v:,}" if v else "—")(int(((reg_arr == g) & m).sum()))
            for g in regs) + " |")
    L += ["", "## クラスタ数の選び方", "",
          "silhouette 係数（4,000 件サンプル）で選んだ:", ""]
    for k, s in zip(ks, scores):
        L.append(f"- k={k}: {s:.4f}" + ("  ← 採用" if k == best_k else ""))
    L += ["", "---",
          "生成: `scripts/toporag/cluster_substations.py`（潮流は解かない）", ""]
    (REPORTS / f"substation_clusters_{date}.md").write_text("\n".join(L), encoding="utf-8")
    print(f"→ docs/reports/substation_clusters_{date}.md")


if __name__ == "__main__":
    main()
