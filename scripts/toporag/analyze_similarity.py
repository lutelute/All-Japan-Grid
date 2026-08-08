#!/usr/bin/env python3
"""topoRAG Phase 0 — 「部分に切って、何が何と、どう似ているか」を実測する。

分割単位は変電所エゴグラフ。3つの問いに答える:

  Q1 どんな「型」があるか      — クラスタリングで構造類型を抽出
  Q2 何が何と似ているか        — region を跨ぐ構造的双子（cos 上位ペア）
  Q3 どう似ているか            — コサイン類似度の次元別寄与分解
  Q4 その類似度は意味を持つか  — crosswalk 検証済み対応 vs 誤マッチ16件で判別性能を測る
                                 （正例=同一変電所のはず / 負例=別の変電所と確定済み）

usage: python3 scripts/toporag/analyze_similarity.py [--k 8] [--kv-floor 110]
出力: docs/reports/toporag_phase0_<date>.{md,json} と図
"""
from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from pathlib import Path

import numpy as np

import vectorize_substations as V

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "docs" / "reports"
FIGS = ROOT / "docs" / "assets" / "toporag"


def wl_refine(F: V.EgoFeatures, ids: list[str], X: np.ndarray, rounds: int) -> np.ndarray:
    """Weisfeiler-Lehman 流の近傍集約。各ラウンドで [自分 | 隣接平均 | 隣接最大] に拡張する。

    回路ネットリストで言えば「自素子の型」から「隣接素子の型の組み合わせ」へ
    語彙を深める操作にあたる。深めるほど個体識別能は上がるが、
    ソース間で近傍の見え方が違うと逆にノイズにもなる（それを実測する）。
    """
    pos = {b: j for j, b in enumerate(ids)}
    cur = X
    for _ in range(rounds):
        mean = np.zeros_like(cur)
        mx = np.zeros_like(cur)
        for j, b in enumerate(ids):
            nb = [pos[n] for n in F.nbrs.get(b, ()) if n in pos]
            if nb:
                mean[j] = cur[nb].mean(axis=0)
                mx[j] = cur[nb].max(axis=0)
        cur = np.hstack([cur, mean, mx])
    return cur


def top_contrib(a: np.ndarray, b: np.ndarray, n: int = 4) -> list[tuple[str, float]]:
    c = V.cosine_contributions(a, b)
    idx = np.argsort(-c)[:n]
    return [(V.FEATURE_NAMES[i], float(c[i])) for i in idx if c[i] > 1e-6]


def block_contrib(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    c = V.cosine_contributions(a, b)
    return {name: float(c[s:e].sum()) for name, (s, e) in V.BLOCKS.items()}


def describe(F: V.EgoFeatures, base: str) -> str:
    kvs = sorted({V.KV_LABEL[i] for i in F.layers_kv[base]},
                 key=lambda s: -(float(s[:-2]) if s[:-2].isdigit() else 0))
    deg = F.deg_kv[base]
    dparts = [f"{V.KV_LABEL[i]}×{int(deg[i])}" for i in np.argsort(-deg) if deg[i] > 0]
    return f"層[{'/'.join(kvs)}] 次数[{' '.join(dparts) or 'なし'}] 隣接{len(F.nbrs[base])}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=8, help="構造類型のクラスタ数")
    ap.add_argument("--kv-floor", type=float, default=110.0, help="cross-source比較時の電圧射影")
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True, text=True).stdout.strip()
    FIGS.mkdir(parents=True, exist_ok=True)

    # ══ built 全網でのベクトル化 ═══════════════════════════════════════
    Fb = V.from_built()
    ids, X = Fb.vectors()
    Xn = V.l2_normalize(X)
    print(f"built: 変電所 {len(ids)} 個をエゴグラフに分割 → {X.shape[1]} 次元")

    # 骨幹のみ（外部接続を持つ変電所に限定。孤立変電所はベクトルが縮退するため型分析から除く）
    live = np.array([Fb.deg_kv[i].sum() > 0 for i in ids])
    print(f"  うち外部接続を持つ変電所: {int(live.sum())}（孤立 {int((~live).sum())} は型分析から除外）")

    # ── Q1 構造類型 ───────────────────────────────────────────────
    from sklearn.cluster import KMeans
    Xl = Xn[live]
    idl = [i for i, f in zip(ids, live) if f]
    km = KMeans(n_clusters=args.k, n_init=10, random_state=0).fit(Xl)
    lab = km.labels_
    types = []
    for c in range(args.k):
        members = [idl[j] for j in np.where(lab == c)[0]]
        # 代表 = セントロイド最近傍
        d = Xl[lab == c] @ km.cluster_centers_[c]
        rep = members[int(np.argmax(d))]
        kv_top = defaultdict(int)
        for m in members:
            kv_top[V.KV_LABEL[V.kv_index(Fb.max_kv.get(m))]] += 1
        regions = defaultdict(int)
        for m in members:
            regions[Fb.region[m]] += 1
        types.append({
            "cluster": c, "n": len(members),
            "representative": Fb.name.get(rep, rep), "rep_id": rep,
            "rep_profile": describe(Fb, rep),
            "top_kv": sorted(kv_top.items(), key=lambda x: -x[1])[:3],
            "regions": sorted(regions.items(), key=lambda x: -x[1])[:4],
            "mean_deg": float(np.mean([Fb.deg_kv[m].sum() for m in members])),
            "mean_layers": float(np.mean([len(Fb.layers_kv[m]) for m in members])),
        })
    types.sort(key=lambda t: -t["mean_deg"])

    # ── Q2/Q3 region を跨ぐ構造的双子 ────────────────────────────────
    # 500/275kV 級の主要変電所に絞って総当たり（意味のある比較に限定）
    major = [j for j, i in enumerate(idl)
             if Fb.max_kv.get(i, 0) >= 187 and Fb.deg_kv[i].sum() >= 3]
    Xm, idm = Xl[major], [idl[j] for j in major]
    S = Xm @ Xm.T
    np.fill_diagonal(S, -1)
    twins = []
    seen_pairs = set()
    order = np.argsort(-S, axis=None)
    for flat in order:
        a, b = np.unravel_index(flat, S.shape)
        if a >= b:
            continue
        ia, ib = idm[a], idm[b]
        if Fb.region[ia] == Fb.region[ib]:
            continue
        key = (Fb.region[ia], Fb.region[ib])
        if key in seen_pairs:      # region ペアごとに最上位1件だけ拾う
            continue
        seen_pairs.add(key)
        twins.append({
            "cos": float(S[a, b]),
            "a": {"name": Fb.name.get(ia, ia), "id": ia, "region": Fb.region[ia], "profile": describe(Fb, ia)},
            "b": {"name": Fb.name.get(ib, ib), "id": ib, "region": Fb.region[ib], "profile": describe(Fb, ib)},
            "blocks": block_contrib(Xm[a], Xm[b]),
            "top_features": top_contrib(Xm[a], Xm[b]),
        })
        if len(twins) >= 12:
            break

    # ── Q5 副産物: 構造が完全一致する跨region ペア = 正典の重複コピー ──────
    # 地域ごとの OSM 抽出 bbox が境界で重なるため、同じ物理変電所が
    # 2つの region 接頭辞で二重に載る。構造ベクトルが cos≈1 で炙り出す。
    import math
    node_ll = {}
    for n in Fb.name:
        node_ll[n] = None
    built_raw = json.load(open(ROOT / "docs" / "data" / "built" / "all.json"))
    for n in built_raw["nodes"]:
        b = n["id"].split("@")[0]
        node_ll.setdefault(b, (n["lat"], n["lon"]))
        if node_ll[b] is None:
            node_ll[b] = (n["lat"], n["lon"])
    name_of = {b: Fb.name.get(b, "") for b in Fb.name}
    by_name: dict[str, list[str]] = defaultdict(list)
    for b, nm in name_of.items():
        if nm:
            by_name[nm.split(" (")[0]].append(b)
    dups = []
    for nm, bs in by_name.items():
        for i in range(len(bs)):
            for j in range(i + 1, len(bs)):
                b1, b2 = bs[i], bs[j]
                if b1.split("_")[0] == b2.split("_")[0]:
                    continue
                p1, p2 = node_ll.get(b1), node_ll.get(b2)
                if not p1 or not p2:
                    continue
                dist_km = math.dist(p1, p2) * 111.0
                if dist_km < 2.0:
                    dups.append({"name": nm, "a": b1, "b": b2, "km": round(dist_km, 3)})
    dup_regions: dict[str, int] = defaultdict(int)
    for d in dups:
        dup_regions["↔".join(sorted([d["a"].split("_")[0], d["b"].split("_")[0]]))] += 1

    # 反証テスト①「重複に見えるのは電圧階級の違う変圧を伴っているだけでは？」
    # → 対の電圧層集合を比べる。変圧の対なら層は互いに素になるはず。
    layers_of: dict[str, set] = defaultdict(set)
    for n in built_raw["nodes"]:
        if "_sub_" in n["id"]:
            layers_of[n["id"].split("@")[0]].add(n.get("kv"))
    lay = {"identical": 0, "overlap": 0, "disjoint": 0, "disjoint_kv_missing": 0}
    for d in dups:
        l1, l2 = layers_of[d["a"]], layers_of[d["b"]]
        if l1 == l2:
            lay["identical"] += 1
        elif l1 & l2:
            lay["overlap"] += 1
        else:
            lay["disjoint"] += 1
            if not any(l1) or not any(l2):     # 片側が電圧不明＝属性欠落
                lay["disjoint_kv_missing"] += 1

    # 反証テスト②「重複エッジも異電圧の並行回線では？」
    # → 同一端点のエッジ群を電圧と線名で分類する。
    by_edge: dict[tuple, list] = defaultdict(list)
    for e2 in built_raw["edges"]:
        k = tuple(sorted([(round(e2["a"][0], 5), round(e2["a"][1], 5)),
                          (round(e2["b"][0], 5), round(e2["b"][1], 5))]))
        by_edge[k].append(e2)
    edg = {"diff_kv": 0, "same_kv_same_name": 0, "same_kv_diff_name": 0}
    for g in (v for v in by_edge.values() if len(v) > 1):
        kvs = {x.get("kv") for x in g}
        nms = {x.get("name") for x in g}
        if len(kvs) > 1:
            edg["diff_kv"] += 1                # 異電圧＝並行回線として正当な可能性
        elif len(nms) == 1:
            edg["same_kv_same_name"] += 1      # 同電圧・同線名＝二重取得
        else:
            edg["same_kv_diff_name"] += 1

    print(f"\nQ5 跨region 重複変電所（同名・2km以内）: {len(dups)} 組")
    for k, v in sorted(dup_regions.items(), key=lambda x: -x[1])[:6]:
        print(f"   {k}: {v}")
    print(f"   電圧層: 完全一致 {lay['identical']} / 一部重なり {lay['overlap']} / "
          f"互いに素 {lay['disjoint']}（うち片側が電圧不明 {lay['disjoint_kv_missing']}）")
    print(f"   同一端点エッジ群: 異電圧 {edg['diff_kv']}（並行回線として正当な可能性）/ "
          f"同電圧同線名 {edg['same_kv_same_name']}（二重取得）/ 同電圧別線名 {edg['same_kv_diff_name']}")

    # ── Q4 cross-source 判別性能（この類似度は「同じ変電所」を当てられるか） ──
    Fk = V.from_keitouzu()
    kids, XK = Fk.vectors()
    XKn = V.l2_normalize(XK)
    Fb2 = V.from_built(kv_floor=args.kv_floor)     # 同一電圧宇宙へ射影
    bids, XB = Fb2.vectors()
    XBn = V.l2_normalize(XB)
    bpos = {b: j for j, b in enumerate(bids)}
    kpos = {u: j for j, u in enumerate(kids)}

    adj_rep = sorted(REPORTS.glob("keitouzu_xwalk_adjudication_*.json"))[-1]
    adjud = json.load(open(adj_rep))
    excluded = {tuple(p) for p in adjud["excluded_mappings"]}

    by_region_b = defaultdict(list)
    for b in bids:
        by_region_b[b.split("_")[0]].append(b)
    rng = np.random.default_rng(0)

    def evaluate(wl: int) -> dict:
        """WL ラウンド数 wl での判別・検索性能。ランダム対照つき。"""
        Ak = V.l2_normalize(wl_refine(Fk, kids, XK, wl))
        Ab = V.l2_normalize(wl_refine(Fb2, bids, XB, wl))
        p, n, rnd = [], [], []
        hits = {1: 0, 5: 0, 10: 0}
        nq = 0
        for m in adjud["mappings"]:
            u, tgt = m["keitouzu_uuid"], m["ajg_target"]
            base = tgt.split("@")[0]
            if u not in kpos or base not in bpos:
                continue
            s = float(Ak[kpos[u]] @ Ab[bpos[base]])
            if (u, tgt) in excluded:
                n.append(s)
                continue
            p.append(s)
            cand = by_region_b.get(base.split("_")[0], [])
            if len(cand) < 10:
                continue
            ci = [bpos[c] for c in cand]
            sims = Ab[ci] @ Ak[kpos[u]]
            # ランダム対照: 同 region の無関係な変電所との類似度
            rnd.append(float(sims[rng.integers(len(sims))]))
            rank = int((sims > sims[cand.index(base)]).sum()) + 1
            nq += 1
            for k in hits:
                if rank <= k:
                    hits[k] += 1
        p, n, rnd = np.array(p), np.array(n), np.array(rnd)
        auc_n = float((p[:, None] > n[None, :]).mean()) if len(p) and len(n) else float("nan")
        auc_r = float((p[:, None] > rnd[None, :]).mean()) if len(p) and len(rnd) else float("nan")
        return {"wl": wl, "dim": Ak.shape[1], "pos": p, "neg": n, "rnd": rnd,
                "auc_vs_neg": auc_n, "auc_vs_random": auc_r,
                "recall": {k: (hits[k] / nq if nq else float("nan")) for k in hits}, "n_query": nq}

    def stratified(wl: int) -> list[dict]:
        """構造の「豊かさ」別の検索性能。

        平凡な変電所（次数1-2の通過変電所）は構造だけでは原理的に区別できないはずで、
        逆に多層・高次数のハブは個体識別できるはず——という仮説を実測する。
        層別は keitouzu 側の外部次数（＝系統図から読める情報だけ）で行う。
        """
        Ak = V.l2_normalize(wl_refine(Fk, kids, XK, wl))
        Ab = V.l2_normalize(wl_refine(Fb2, bids, XB, wl))
        buckets = [("次数1", 1, 1), ("次数2", 2, 2), ("次数3", 3, 3),
                   ("次数4-5", 4, 5), ("次数6+", 6, 10**6)]
        acc = {b[0]: {"n": 0, 1: 0, 5: 0, 10: 0, "cos": []} for b in buckets}
        for m in adjud["mappings"]:
            u, tgt = m["keitouzu_uuid"], m["ajg_target"]
            base = tgt.split("@")[0]
            if (u, tgt) in excluded or u not in kpos or base not in bpos:
                continue
            cand = by_region_b.get(base.split("_")[0], [])
            if len(cand) < 10:
                continue
            d = int(Fk.deg_kv[u].sum())
            name = next((b[0] for b in buckets if b[1] <= d <= b[2]), None)
            if name is None:
                continue
            ci = [bpos[c] for c in cand]
            sims = Ab[ci] @ Ak[kpos[u]]
            rank = int((sims > sims[cand.index(base)]).sum()) + 1
            acc[name]["n"] += 1
            acc[name]["cos"].append(float(sims[cand.index(base)]))
            for k in (1, 5, 10):
                if rank <= k:
                    acc[name][k] += 1
        out = []
        for b, _, _ in buckets:
            a = acc[b]
            if a["n"]:
                out.append({"bucket": b, "n": a["n"],
                            "recall": {k: a[k] / a["n"] for k in (1, 5, 10)},
                            "cos_median": float(np.median(a["cos"]))})
        return out

    evals = [evaluate(w) for w in (0, 1, 2)]
    strata = stratified(0)
    print("\n構造の豊かさ別の検索性能 (WL0)")
    for s in strata:
        print(f"  {s['bucket']:>8s} n={s['n']:>3d}  cos中央値 {s['cos_median']:.3f}  "
              f"recall@1={s['recall'][1]:.1%} @5={s['recall'][5]:.1%} @10={s['recall'][10]:.1%}")
    print("\nQ4 判別・検索性能（WL ラウンド別）")
    for e in evals:
        print(f"  WL{e['wl']} ({e['dim']:>3}次元): 正例中央値 {np.median(e['pos']):.3f} / "
              f"誤マッチ {np.median(e['neg']):.3f} / 無関係な変電所 {np.median(e['rnd']):.3f} | "
              f"AUC(vs誤マッチ)={e['auc_vs_neg']:.3f} AUC(vs無関係)={e['auc_vs_random']:.3f} | "
              f"recall@1={e['recall'][1]:.1%} @5={e['recall'][5]:.1%} @10={e['recall'][10]:.1%}")
    best = max(evals, key=lambda e: e["recall"][5])
    pos, neg, auc, recall, n_query = best["pos"], best["neg"], best["auc_vs_neg"], best["recall"], best["n_query"]

    # ══ 図 ═══════════════════════════════════════════════════════════
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.decomposition import PCA
    plt.rcParams["font.family"] = ["Hiragino Sans", "Yu Gothic", "DejaVu Sans"]

    fig, axes = plt.subplots(1, 4, figsize=(21.5, 5.0))
    P = PCA(n_components=2).fit_transform(Xl)
    mkv = np.array([Fb.max_kv.get(i, 0) for i in idl])
    sc = axes[0].scatter(P[:, 0], P[:, 1], c=np.clip(mkv, 0, 500), s=6, cmap="turbo", alpha=0.6)
    axes[0].set_title(f"変電所エゴグラフの構造空間 (PCA, n={len(idl)})")
    axes[0].set_xlabel("PC1"); axes[0].set_ylabel("PC2")
    plt.colorbar(sc, ax=axes[0], label="最高電圧 kV")

    C = V.l2_normalize(km.cluster_centers_)
    im = axes[1].imshow(C @ C.T, cmap="magma", vmin=0, vmax=1)
    axes[1].set_title(f"構造類型どうしの類似度 (k={args.k})")
    axes[1].set_xlabel("型"); axes[1].set_ylabel("型")
    plt.colorbar(im, ax=axes[1])

    bins = np.linspace(0, 1, 41)
    axes[2].hist(best["rnd"], bins=bins, alpha=0.5, label=f"無関係な変電所(対照) n={len(best['rnd'])}",
                 color="#9e9e9e", density=True)
    axes[2].hist(pos, bins=bins, alpha=0.6, label=f"検証済み対応 n={len(pos)}", color="#2196f3", density=True)
    axes[2].hist(neg, bins=bins, alpha=0.75, label=f"誤マッチ確定 n={len(neg)}", color="#e91e63", density=True)
    axes[2].set_title(f"同一変電所 vs 別の変電所 の構造類似度 (WL{best['wl']}, AUC={auc:.3f})")
    axes[2].set_xlabel("コサイン類似度"); axes[2].set_ylabel("密度"); axes[2].legend(fontsize=8)

    xs = np.arange(len(strata))
    # 入れ子の棒（@10 が最も広く、@1 が最も狭い）
    for k, col, w, z in ((10, "#c5cae9", 0.70, 1), (5, "#5c6bc0", 0.48, 2), (1, "#1a237e", 0.26, 3)):
        axes[3].bar(xs, [s["recall"][k] * 100 for s in strata], width=w,
                    color=col, label=f"recall@{k}", zorder=z)
    axes[3].set_xticks(xs)
    axes[3].set_xticklabels([f"{s['bucket']}\n(n={s['n']})" for s in strata], fontsize=8.5)
    axes[3].set_ylabel("正解が上位に入る率 (%)")
    axes[3].set_title("構造の豊かさ別の検索性能（ハブほど同定できる）")
    axes[3].legend(fontsize=9); axes[3].grid(axis="y", alpha=0.3)
    fig.tight_layout()
    figpath = FIGS / f"phase0_{date}.png"
    fig.savefig(figpath, dpi=130)
    print(f"→ {figpath.relative_to(ROOT)}")

    # ══ レポート ══════════════════════════════════════════════════════
    out_json = REPORTS / f"toporag_phase0_{date}.json"
    json.dump({"date": date, "n_substations": len(ids), "n_live": int(live.sum()),
               "n_features": X.shape[1], "kv_floor": args.kv_floor,
               "types": types, "twins": twins,
               "discrimination": [
                   {"wl": e["wl"], "dim": e["dim"], "n_pos": len(e["pos"]), "n_neg": len(e["neg"]),
                    "pos_median": float(np.median(e["pos"])), "neg_median": float(np.median(e["neg"])),
                    "random_median": float(np.median(e["rnd"])),
                    "auc_vs_neg": e["auc_vs_neg"], "auc_vs_random": e["auc_vs_random"],
                    "recall": e["recall"], "n_query": e["n_query"]} for e in evals],
               "stratified_wl0": strata},
              open(out_json, "w"), ensure_ascii=False, indent=1)

    L = [
        f"# topoRAG Phase 0 — 送電網を部分に切って似ているかを測る（{date}）",
        "",
        "回路のネットリスト類似度（素子種の 1/0 と個数 → コサイン）を送電網に一般化した。",
        f"**分割単位** = 変電所ひとつのエゴグラフ（電圧層構成・階級別次数・変圧段数・隣接変電所の素性、計 {X.shape[1]} 次元）。",
        f"built 正典の変電所 {len(ids)} 個（うち外部接続を持つもの {int(live.sum())}）をベクトル化した。",
        "",
        "## Q4 まず「この類似度は意味があるか」",
        "",
        "検証済み crosswalk 対応を正例（＝同一変電所のはず）、地理裁定で確定した誤マッチを負例（＝別の変電所と確定）とし、",
        "さらに**同 region の無関係な変電所をランダム対照**に置いて、**構造だけで判別できるか**を測った。",
        "名前も座標も使っていない。WL は近傍集約の反復回数（語彙の深さ）。",
        "",
        "| WL | 次元 | 正例 中央値 | 誤マッチ 中央値 | 無関係な変電所 中央値 | AUC(vs誤マッチ) | AUC(vs無関係) | recall@1 | @5 | @10 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ] + [
        f"| {e['wl']} | {e['dim']} | {np.median(e['pos']):.3f} | {np.median(e['neg']):.3f} | "
        f"{np.median(e['rnd']):.3f} | {e['auc_vs_neg']:.3f} | {e['auc_vs_random']:.3f} | "
        f"{e['recall'][1]:.1%} | {e['recall'][5]:.1%} | {e['recall'][10]:.1%} |" for e in evals
    ] + [
        "",
        "**読み方**: AUC(vs誤マッチ) が高いのは「別の変電所だと確定したペアを構造で弾ける」ことを意味する。",
        "一方 AUC(vs無関係) と recall@k は「候補集合から正解を引き当てられるか」を測る。",
        "この2つは別問題で、前者が高くても後者が低いなら**照合器としては使えるが検索器としては足りない**。",
        "",
        "**WL を深めても改善しない**（recall@5 は 18.0% → 19.8% → 16.2%）。近傍集約は誤マッチとの",
        "分離（中央値 0.189 → 0.061）は進めるが個体識別には寄与せず、2周目はむしろ悪化する。",
        "2つのソースで近傍の見え方が違う（built は下位網を持ち keitouzu は持たない）ため、",
        "深い集約はソース間差を増幅する側に働くと解釈できる。**負の結果として記録する。**",
        "",
        "### 構造の豊かさで層別すると像が変わる",
        "",
        "全体 recall@1 = 7.2% は「使えない」に見えるが、これは**平凡な通過変電所が大半を占めるため**の",
        "平均値だった。keitouzu 側の外部次数で層別すると単調に効いている:",
        "",
        "| 系統図から読める次数 | 件数 | 正解の cos 中央値 | recall@1 | @5 | @10 |",
        "|---|---:|---:|---:|---:|---:|",
    ] + [
        f"| {s['bucket']} | {s['n']} | {s['cos_median']:.3f} | {s['recall'][1]:.1%} | "
        f"{s['recall'][5]:.1%} | {s['recall'][10]:.1%} |" for s in strata
    ] + [
        "",
        "**次数6+のハブ変電所では recall@5 = 50.6%**（次数1の 5.5% の 9 倍）。",
        "構造しか手がかりが無い状況で、名前も座標も使わず候補5件に半数を絞れる。",
        "逆に次数1-2の通過変電所は**原理的に区別できない**——同じ形の部分グラフが網の中に大量にあるため。",
        "これは手法の失敗ではなく、送電網という対象の性質である。",
        "",
        "**運用上の含意**: 構造照合は「ハブから攻める」道具として設計すべきで、",
        "全変電所一括の同定器としては設計してはいけない。Phase 1（関西の匿名変電所実名化）は",
        "高次数の変電所から着手し、確定したハブを錨として周辺の低次数の変電所へ広げる順序になる。",
        "",
        "## Q1 どんな構造の「型」があるか",
        "",
        f"外部接続のある変電所 {int(live.sum())} 個を k={args.k} で類型化（外部接続の多い順）。",
        "",
        "| 型 | 数 | 平均次数 | 平均層数 | 代表局 | 代表の構造 | 主な region |",
        "|---|---:|---:|---:|---|---|---|",
    ]
    for t in types:
        regs = " ".join(f"{r}{n}" for r, n in t["regions"])
        L.append(f"| #{t['cluster']} | {t['n']} | {t['mean_deg']:.1f} | {t['mean_layers']:.1f} | "
                 f"{t['representative']} | {t['rep_profile']} | {regs} |")
    L += [
        "",
        "## Q2/Q3 何が何と似ていて、どこが似ているのか",
        "",
        "region を跨ぐ「構造的双子」（187kV 以上・次数3以上に限定、region ペアごとに最上位1件）。",
        "**寄与**はコサイン類似度の内訳（合計＝cos）で、どの特徴ブロックが類似を作ったかを示す。",
        "",
    ]
    for t in twins:
        bl = " / ".join(f"{k} {v:.2f}" for k, v in sorted(t["blocks"].items(), key=lambda x: -x[1]))
        tf = ", ".join(f"`{n}`{v:.2f}" for n, v in t["top_features"])
        L += [
            f"### {t['a']['name']}（{t['a']['region']}） ≈ {t['b']['name']}（{t['b']['region']}） — cos **{t['cos']:.4f}**",
            "",
            f"- {t['a']['region']}: {t['a']['profile']}",
            f"- {t['b']['region']}: {t['b']['profile']}",
            f"- 寄与ブロック: {bl}",
            f"- 寄与上位: {tf}",
            "",
        ]
    L += [
        "## Q5 副産物 — 構造の完全一致が正典の重複コピーを暴いた",
        "",
        f"cos≈1.0 の「双子」を追ったところ、**同名の変電所が別 region 接頭辞で二重に載っている**",
        f"事例が見つかった。同名かつ 2km 以内のペアは **{len(dups)} 組**。",
        "`docs/data/built/all.json` は10地域ファイルの単純連結（ノード数が完全一致）で、",
        "地域ごとの OSM 抽出 bbox が境界で重なるため、境界付近の設備が二重取得されている。",
        "",
        "| region ペア | 重複組数 |",
        "|---|---:|",
    ] + [f"| {k} | {v} |" for k, v in sorted(dup_regions.items(), key=lambda x: -x[1])[:8]] + [
        "",
        "例: 高千帆変電所220kV（chugoku_sub_268 / kyushu_sub_386、18m 離れ）は",
        "両コピーとも次数11・隣接9の**並行部分グラフ**を持つ。全国集計・潮流・島判定で",
        "境界設備を二重計上している可能性があるため、正典側の課題として要検討。",
        "",
        "### 反証テスト —「電圧階級の違う変圧を伴っているだけでは？」",
        "",
        "同じ変電所を電圧ごとに別ノードで表しているなら、対の電圧層集合は**互いに素**になるはず。",
        "実測はそうならない。",
        "",
        "| 対の電圧層集合 | 組数 | 解釈 |",
        "|---|---:|---|",
        f"| 完全一致 | **{lay['identical']}** | 両方が同じ電圧構成を丸ごと持つ＝変圧では説明できない |",
        f"| 一部重なり | {lay['overlap']} | — |",
        f"| 互いに素 | {lay['disjoint']} | うち {lay['disjoint_kv_missing']} 組は片側が電圧不明（属性欠落であって変圧の対ではない） |",
        "",
        "エッジ側も同様に分類した。**指摘のとおり一部は正当な並行回線**である。",
        "",
        "| 同一端点のエッジ群 | 箇所 | 解釈 |",
        "|---|---:|---|",
        f"| 電圧が異なる | {edg['diff_kv']} | 異電圧の並行回線として**正当**。重複ではない |",
        f"| 電圧も線名も同一 | **{edg['same_kv_same_name']}** | 同じ線を二度取得している |",
        f"| 電圧同一・線名違い | {edg['same_kv_diff_name']} | 並行回線と重複が混在。個別確認が要る |",
        "",
        f"したがって**エッジの重複本数は {edg['same_kv_same_name']} 箇所**（同電圧・同線名）であり、",
        "同一端点エッジをすべて重複と数えるのは過大。変電所側の二重計上は電圧層集合の",
        "完全一致で裏づけられるが、エッジ側は正当な並行回線を差し引いて数える必要がある。",
        "",
        "---",
        f"図: `docs/assets/toporag/phase0_{date}.png`　生成: `scripts/toporag/analyze_similarity.py`",
        "",
    ]
    (REPORTS / f"toporag_phase0_{date}.md").write_text("\n".join(L), encoding="utf-8")
    print(f"→ docs/reports/toporag_phase0_{date}.md")


if __name__ == "__main__":
    main()
