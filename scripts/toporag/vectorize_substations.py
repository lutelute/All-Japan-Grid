#!/usr/bin/env python3
"""topoRAG 方式の送電網ベクトル化 — 変電所エゴグラフを 1/0・個数でベクトル化する。

回路のネットリスト類似度（素子種の 1/0 と個数 → コサイン類似度）を送電網へ一般化する。
「部分」= 変電所ひとつのエゴグラフ（その変電所の電圧層構成 + 外部接続 + 隣接変電所の素性）。

built 正典と keitouzu の両方から**同一の特徴軸**でベクトルを作れるようにしてある
（keitouzu 側は座標も下位網も持たないため、比較時は同一電圧宇宙へ射影する）。

このモジュールは特徴抽出のみ。分析は analyze_similarity.py。
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict, deque
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT))
from src.topology.coords import CoordIndex
BUILT = ROOT / "docs" / "data" / "built" / "all.json"
KZ = ROOT / "data" / "external" / "keitouzu"

# 特徴軸として扱う電圧階級（これ以外は "other" に集約）
KV_AXES = [500.0, 275.0, 220.0, 187.0, 154.0, 132.0, 110.0, 77.0, 66.0]
KV_LABEL = [f"{int(k)}kV" for k in KV_AXES] + ["otherkV"]


def kv_index(kv: float | None) -> int:
    """電圧を特徴軸の添字へ。未知/欠損は other 枠。"""
    if kv is None:
        return len(KV_AXES)
    for i, k in enumerate(KV_AXES):
        if abs(kv - k) < 0.5:
            return i
    return len(KV_AXES)


FEATURE_NAMES = (
    [f"has_{l}" for l in KV_LABEL]           # 電圧階級の 1/0（素子種の有無に相当）
    + [f"deg_{l}" for l in KV_LABEL]         # 階級別の外部接続本数（個数）
    + ["n_layers", "deg_total"]              # 電圧層数（変圧段数の代理）・総次数
    + [f"nbr_{l}" for l in KV_LABEL]         # 隣接変電所の最高電圧ヒストグラム
    + ["nbr_deg_min", "nbr_deg_med", "nbr_deg_max"]  # 隣接変電所の次数分布
)
N_FEAT = len(FEATURE_NAMES)

# ブロック境界（可視化・寄与分解の集計用）
BLOCKS = {
    "電圧構成(1/0)": (0, 10),
    "階級別次数": (10, 20),
    "層数・規模": (20, 22),
    "隣接変電所の電圧": (22, 32),
    "隣接変電所の次数": (32, 35),
}


class EgoFeatures:
    """変電所 base id → 特徴ベクトルと素の統計。"""

    def __init__(self) -> None:
        self.layers_kv: dict[str, set[int]] = defaultdict(set)
        self.deg_kv: dict[str, np.ndarray] = defaultdict(lambda: np.zeros(len(KV_LABEL)))
        self.n_xfmr: dict[str, int] = defaultdict(int)
        self.nbrs: dict[str, set[str]] = defaultdict(set)
        self.max_kv: dict[str, float] = {}
        self.name: dict[str, str] = {}
        self.region: dict[str, str] = {}

    def vectors(self) -> tuple[list[str], np.ndarray]:
        ids = sorted(self.nbrs.keys() | self.layers_kv.keys())
        deg_tot = {i: float(self.deg_kv[i].sum()) for i in ids}
        rows = []
        for i in ids:
            has = np.zeros(len(KV_LABEL))
            for li in self.layers_kv[i]:
                has[li] = 1.0
            deg = self.deg_kv[i]
            nbr_hist = np.zeros(len(KV_LABEL))
            nbr_degs = []
            for nb in self.nbrs[i]:
                nbr_hist[kv_index(self.max_kv.get(nb))] += 1.0
                nbr_degs.append(deg_tot.get(nb, 0.0))
            nd = np.array(nbr_degs) if nbr_degs else np.zeros(1)
            rows.append(np.concatenate([
                has,
                np.log1p(deg),
                np.log1p([len(self.layers_kv[i]), deg_tot[i]]),
                np.log1p(nbr_hist),
                np.log1p([nd.min(), np.median(nd), nd.max()]),
            ]))
        return ids, np.vstack(rows)


def from_built(kv_floor: float | None = None) -> EgoFeatures:
    """built 正典からエゴ特徴を作る。kv_floor 指定でその電圧未満の網を無視（射影）。"""
    built = json.load(open(BUILT))
    nodes, edges = built["nodes"], built["edges"]


    # 座標の解決は src.topology.coords.CoordIndex に一本化
    # （1座標に複数ノードが載る性質と、潰したときに壊れる範囲はそちらの docstring）。
    ix = CoordIndex(nodes)
    adj: dict[str, set[tuple[str, float]]] = defaultdict(set)
    for i, j in ix.colocated_pairs():   # 同一地点＝同一物理サイト（層間・重複コピー）
        adj[nodes[i]["id"]].add((nodes[j]["id"], None))
        adj[nodes[j]["id"]].add((nodes[i]["id"], None))
    for e in edges:
        kv = e.get("kv")
        if kv_floor is not None and (kv is None or kv < kv_floor):
            continue
        for i in ix.endpoints(e["a"], kv):
            for j in ix.endpoints(e["b"], kv):
                if i != j:
                    adj[nodes[i]["id"]].add((nodes[j]["id"], kv))
                    adj[nodes[j]["id"]].add((nodes[i]["id"], kv))

    F = EgoFeatures()
    node_by_id = {n["id"]: n for n in nodes}
    for n in nodes:
        if "_sub_" not in n["id"]:
            continue
        base = n["id"].split("@")[0]
        F.layers_kv[base].add(kv_index(n.get("kv")))
        F.name.setdefault(base, n.get("name", ""))
        F.region.setdefault(base, base.split("_")[0])
        k = n.get("kv") or 0.0
        F.max_kv[base] = max(F.max_kv.get(base, 0.0), k)

    # 層間リンク（= 変圧器段）と外部接続（jct のみ経由して他の変電所へ）
    for n in nodes:
        nid = n["id"]
        if "_sub_" not in nid:
            continue
        base = nid.split("@")[0]
        seen, q = {nid}, deque([(nid, None)])
        while q:
            cur, first_kv = q.popleft()
            # sorted: 集合の走査順は実行ごとに変わる。BFS の到達順で
            # deg_kv に記録される「最初の辺の電圧」が揺れるため固定する。
            # key が要る: 同一座標ペアは kv=None で入るので、同じ隣接IDに None と
            # float が両方載ると素の tuple 比較が TypeError になる（潜在バグ）。
            for nb, kv in sorted(adj.get(cur, ()),
                                 key=lambda t: (t[0], -1.0 if t[1] is None else t[1])):
                if nb in seen:
                    continue
                seen.add(nb)
                fk = first_kv if first_kv is not None else kv
                if "_sub_" in nb:
                    nb_base = nb.split("@")[0]
                    if nb_base != base:
                        F.deg_kv[base][kv_index(fk)] += 1
                        F.nbrs[base].add(nb_base)
                else:
                    q.append((nb, fk))

    # 変圧段数 = 電圧層数 - 1。
    # built では多層変電所(1655件)の層ノードが座標を完全に共有するため、層間リンクを
    # 幾何から復元できない(同一座標エッジ2180本は層ペアを特定できない)。
    # keitouzu 側も同じ定義にして**ソース間で同一の特徴軸**を保つ。
    for b in F.layers_kv:
        F.n_xfmr[b] = max(len(F.layers_kv[b]) - 1, 0)
    return F


def from_keitouzu() -> EgoFeatures:
    """keitouzu CSV から同一軸のエゴ特徴を作る（座標・下位網なし）。"""
    subs = {r["uuid"]: r for r in csv.DictReader(open(KZ / "substations.csv"))
            if r["status"] == "active"}
    routes = [r for r in csv.DictReader(open(KZ / "routes.csv")) if r["status"] == "active"]
    aliases: dict[str, list[str]] = defaultdict(list)
    for a in csv.DictReader(open(KZ / "aliases.csv")):
        aliases[a["uuid"]].append(a["alias"])

    def parse_kv(v: str) -> float | None:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    F = EgoFeatures()
    for u, s in subs.items():
        F.name[u] = (aliases[u] or [s["name_official"]])[0]
        F.region[u] = s["region"]
        mk = parse_kv(s.get("voltage_max_kv", ""))
        F.max_kv[u] = mk or 0.0
        if mk is not None:
            F.layers_kv[u].add(kv_index(mk))
    for r in routes:
        fu, tu = r["from_substation"], r["to_substation"]
        if fu not in subs or tu not in subs:
            continue
        ki = kv_index(parse_kv(r["voltage_kv"]))
        for a, b in ((fu, tu), (tu, fu)):
            F.deg_kv[a][ki] += 1
            F.nbrs[a].add(b)
            F.layers_kv[a].add(ki)  # 接続線の電圧も層として数える
    for u in subs:
        F.n_xfmr[u] = max(len(F.layers_kv[u]) - 1, 0)  # 層数-1 を変圧段の代理に
    return F


def l2_normalize(X: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(X, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return X / n


def cosine_contributions(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """コサイン類似度の次元別寄与（総和 = cos）。「どう似ているか」の分解。"""
    na, nb = np.linalg.norm(a) or 1.0, np.linalg.norm(b) or 1.0
    return (a * b) / (na * nb)
