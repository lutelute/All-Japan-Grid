#!/usr/bin/env python3
"""Ybus 可視化を **DB更新済みの建造モデル** から生成する(正典ソース)。

入力 = `docs/data/built/{region}.json` / `all.json`(build_editor_data 由来・
日付刻印つき)。各ノード=変電所/接続点(lat/lon/kv/sub/region/deg)、各エッジ=
実座標(a↔b)で接続された送電線。**最近傍近似(旧 build_ybus_sparsity)ではなく、
実際の接続グラフ**を用いる。

従来の gen_ybus_interactive.py / gen_ybus_app_dark.py は raw GeoJSON を最近傍
マッチした近似(block_diag・エリア間結合ゼロ)で、DB更新やエリア間連系線を反映
していなかった。本スクリプトがそれを置換する。

出力(docs/assets/analysis/ 配下、暗テーマ・#ybus-panel整合):
    ybus/{region}.png      地域別 spy(DBモデル)
    ybus/stats.json        地域別統計(DBモデル: n_buses/n_edges/n_sub/density/deg)
    ybus_national.png      全国 2パネル(地域色スパイ+エリア間連系線を強調 / 充填率バー)
    ybus_spy.png           全国スパイ(連系線を強調)
    ybus_per_region.png    2x5 ギャラリー
    gif/ybus_build.gif      組立アニメ(地域ブロックが対角に並ぶ + 連系線が入る)

Usage:
    PYTHONPATH=. python scripts/gen_ybus_from_db.py          # 静止図 + stats
    PYTHONPATH=. python scripts/gen_ybus_from_db.py --build  # 組立アニメframe
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import platform

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

if platform.system() == "Darwin":
    plt.rcParams["font.family"] = ["Hiragino Sans", "Apple SD Gothic Neo",
                                   "sans-serif"]
else:
    try:
        import japanize_matplotlib  # noqa
    except ImportError:
        pass

BUILT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "data", "built")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "assets",
                       "analysis")
GIF_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "assets", "gif")

REGIONS = [
    ("hokkaido", "北海道"), ("tohoku", "東北"), ("tokyo", "東京"),
    ("chubu", "中部"), ("hokuriku", "北陸"), ("kansai", "関西"),
    ("chugoku", "中国"), ("shikoku", "四国"), ("kyushu", "九州"),
    ("okinawa", "沖縄"),
]
REGION_COLORS = [
    "#ff6b6b", "#ffa94d", "#ffd43b", "#69db7c", "#38d9a9",
    "#4dabf7", "#9775fa", "#f783ac", "#adb5bd", "#d4a373",
]

# ダークパレット (#ybus-panel に整合)
DK_FIG, DK_AX = "#0f1419", "#0c1014"
DK_DOT, DK_DIAG = "#5dade2", "#f5b041"
DK_TIE = "#ff3b6b"   # エリア間連系線(off-block)を鮮烈に強調
DK_TITLE, DK_SUB = "#e6e6e6", "#9fb3c8"
DK_GRID, DK_SPINE = "#1e2b38", "#2c3e50"


def _ckey(lat, lon):
    return (round(lat, 5), round(lon, 5))


def _style_dark(ax):
    ax.set_facecolor(DK_AX)
    ax.tick_params(colors=DK_SUB, labelsize=7)
    for sp_ in ax.spines.values():
        sp_.set_edgecolor(DK_SPINE)


def load_graph(path):
    """建造モデルJSON -> (nodes, pairs).  pairs=実エッジの (i,j) ノード索引対。

    1つの座標には複数ノードが載る（多層変電所の各電圧層は座標を完全に共有し、
    地域抽出bboxの重なりで跨region重複コピーも生じる）。座標→単一索引に潰すと
    **層間リンク=変圧器ブランチ 2,180 本が ia==ib で全滅**し、スパイ図が実際の
    Ybus より疎に見える（2026-08-08 に検出）。座標には索引の**群**を持たせ、
    端点どうしの全組み合わせを結ぶ。同一座標のエッジはその地点の層間を結ぶ
    ＝変圧器の非対角要素になる。
    """
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    nodes = d["nodes"]
    edges = d["edges"]
    idx = {}
    for i, n in enumerate(nodes):
        idx.setdefault(_ckey(n["lat"], n["lon"]), []).append(i)

    def ends(pt, kv):
        """端点の解決。線路はその電圧の層に着く（全層に着けると過剰結線になる）。"""
        cand = idx.get(_ckey(*pt), ())
        if kv is not None:
            m = [i for i in cand
                 if nodes[i].get("kv") is not None and abs(nodes[i]["kv"] - kv) < 0.5]
            if m:
                return m
        return list(cand)

    pairs = []
    for e in edges:                       # 線路: 同電圧の層どうしを結ぶ
        kv = e.get("kv")
        for i in ends(e["a"], kv):
            for j in ends(e["b"], kv):
                if i != j:
                    pairs.append((i, j))
    for group in idx.values():            # 変圧器: 同一地点の電圧層どうしを結ぶ
        for a in range(len(group)):
            for b in range(a + 1, len(group)):
                pairs.append((group[a], group[b]))
    # スパイ図は非対角要素の有無だけを見るので並行分は畳む。
    # なお本図は **dedup 前の built モデル**（跨region重複ノードを含む）を描く。
    # 実際に解かれる行列は gen_ybus_numeric.py が潮流と同一の dedup 済みモデルから出す。
    pairs = sorted({(min(i, j), max(i, j)) for i, j in pairs})
    return nodes, pairs, d.get("stats", {})


# ──────────────────────────────────────────────────────────────────
#  地域別 spy + stats.json
# ──────────────────────────────────────────────────────────────────
def render_region(region, label):
    path = os.path.join(BUILT_DIR, f"{region}.json")
    if not os.path.exists(path):
        return None
    nodes, pairs, _ = load_graph(path)
    nb = len(nodes)
    if nb == 0:
        return None
    ii = np.array([p[0] for p in pairs], dtype=int)
    jj = np.array([p[1] for p in pairs], dtype=int)
    # 対称化(無向): 両側 + 対角
    deg = np.array([n.get("deg", 0) for n in nodes])
    has_diag = np.where(deg >= 1)[0]

    fig, ax = plt.subplots(figsize=(6.4, 6.4), facecolor=DK_FIG)
    ax.set_facecolor(DK_AX)
    if len(ii):
        xs = np.concatenate([jj, ii])
        ys = np.concatenate([ii, jj])
        ax.scatter(xs, ys, c=DK_DOT, s=0.8, marker=",", alpha=0.85,
                   linewidths=0, rasterized=True, label="バス間結合(送電線)")
    ax.scatter(has_diag, has_diag, c=DK_DIAG, s=0.8, marker=",", alpha=0.9,
               linewidths=0, rasterized=True, label="対角(自己)")
    ax.set_xlim(0, nb)
    ax.set_ylim(nb, 0)
    ax.set_aspect("equal")
    n_sub = sum(1 for n in nodes if n.get("sub") == 1)
    density = len(pairs) / (nb * nb) * 100 if nb else 0.0
    ax.set_title(f"{label}  Ybus（DBモデル）\n"
                 f"({nb:,} ノード / 変電所{n_sub:,} / 結線{len(pairs):,}, "
                 f"density={density:.3f}%)",
                 fontsize=10.5, pad=8, color=DK_TITLE)
    ax.set_xlabel("ノード番号", color=DK_SUB)
    ax.set_ylabel("ノード番号", color=DK_SUB)
    ax.tick_params(colors=DK_SUB, labelsize=8)
    ax.grid(True, color=DK_GRID, lw=0.4)
    for sp_ in ax.spines.values():
        sp_.set_edgecolor(DK_SPINE)
    ax.legend(loc="upper right", fontsize=7, framealpha=0.0,
              labelcolor=DK_SUB, markerscale=6, handletextpad=0.3)
    os.makedirs(os.path.join(OUT_DIR, "ybus"), exist_ok=True)
    fig.savefig(os.path.join(OUT_DIR, "ybus", f"{region}.png"), dpi=130,
                bbox_inches="tight", facecolor=DK_FIG)
    plt.close(fig)
    return {
        "name_ja": label, "n_buses": int(nb), "n_sub": int(n_sub),
        "nnz": int(len(pairs)), "density_pct": round(density, 4),
        "degree_max": int(deg.max()) if len(deg) else 0,
        "degree_avg": round(float(deg[deg >= 1].mean()), 2) if (deg >= 1).any() else 0.0,
    }


# ──────────────────────────────────────────────────────────────────
#  全国: region順に並べ、intra(地域色)/inter(連系線)を分離
# ──────────────────────────────────────────────────────────────────
def load_national():
    path = os.path.join(BUILT_DIR, "all.json")
    nodes, pairs, stats = load_graph(path)
    order_map = {r: k for k, (r, _) in enumerate(REGIONS)}
    # region順 → 元index を並べ替え
    perm = sorted(range(len(nodes)),
                  key=lambda i: (order_map.get(nodes[i].get("region"), 99), i))
    new_of = np.empty(len(nodes), dtype=int)
    for new_i, old_i in enumerate(perm):
        new_of[old_i] = new_i
    nodes_ord = [nodes[i] for i in perm]
    # region境界(offset)
    offsets = {}
    off = 0
    sizes = {}
    for r, _ in REGIONS:
        cnt = sum(1 for n in nodes_ord if n.get("region") == r)
        offsets[r] = off
        sizes[r] = cnt
        off += cnt
    nb = len(nodes_ord)
    # intra/inter エッジ(新index)
    intra = {r: [] for r, _ in REGIONS}
    inter = []
    for ia, ib in pairs:
        na, nb_ = new_of[ia], new_of[ib]
        ra, rb = nodes[ia].get("region"), nodes[ib].get("region")
        if ra == rb:
            intra[ra].append((na, nb_))
        else:
            inter.append((na, nb_))
    deg = np.array([n.get("deg", 0) for n in nodes_ord])
    return nodes_ord, nb, offsets, sizes, intra, inter, deg, stats


def _scatter_pairs(ax, pairs, color, s=0.6, alpha=0.8, label=None):
    if not pairs:
        return
    a = np.array([p[0] for p in pairs]); b = np.array([p[1] for p in pairs])
    xs = np.concatenate([b, a]); ys = np.concatenate([a, b])
    ax.scatter(xs, ys, c=color, s=s, marker=",", alpha=alpha, linewidths=0,
               rasterized=True, label=label)


def render_national(nat):
    nodes_ord, nb, offsets, sizes, intra, inter, deg, _ = nat
    has_diag = np.where(deg >= 1)[0]
    n_inter = len(inter)
    n_intra = sum(len(v) for v in intra.values())

    # ── ybus_spy.png : 全国スパイ(連系線強調) ──
    fig, ax = plt.subplots(figsize=(7.0, 7.0), facecolor=DK_FIG)
    _style_dark(ax)
    for k, (r, _) in enumerate(REGIONS):
        _scatter_pairs(ax, intra[r], REGION_COLORS[k], s=0.5, alpha=0.7)
    ax.scatter(has_diag, has_diag, c=DK_DIAG, s=0.5, marker=",", alpha=0.85,
               linewidths=0, rasterized=True)
    _scatter_pairs(ax, inter, DK_TIE, s=2.2, alpha=0.95,
                   label=f"エリア間連系線 {n_inter}")
    for r, _ in REGIONS:
        o = offsets[r]
        if o > 0:
            ax.axhline(o, color=DK_SPINE, lw=0.4, zorder=4)
            ax.axvline(o, color=DK_SPINE, lw=0.4, zorder=4)
    ax.set_xlim(0, nb); ax.set_ylim(nb, 0); ax.set_aspect("equal")
    ax.set_title(f"全国 Ybus スパイ（DB更新モデル）— 連系線を強調\n"
                 f"({nb:,} ノード, 結線{n_intra + n_inter:,}, "
                 f"うちエリア間{n_inter})",
                 fontsize=10.5, color=DK_TITLE, pad=8)
    ax.set_xlabel("ノード番号", color=DK_SUB)
    ax.set_ylabel("ノード番号", color=DK_SUB)
    ax.legend(loc="lower left", fontsize=8, framealpha=0.0, labelcolor=DK_TIE,
              markerscale=4)
    fig.savefig(os.path.join(OUT_DIR, "ybus_spy.png"), dpi=140,
                bbox_inches="tight", facecolor=DK_FIG)
    plt.close(fig)
    print("  -> ybus_spy.png", flush=True)

    # ── ybus_national.png : 2パネル ──
    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(13.5, 6.7), facecolor=DK_FIG,
        gridspec_kw={"width_ratios": [3, 1.25]})
    _style_dark(ax1)
    for k, (r, lbl) in enumerate(REGIONS):
        _scatter_pairs(ax1, intra[r], REGION_COLORS[k], s=0.5, alpha=0.7)
        o, sz = offsets[r], sizes[r]
        if sz:
            ax1.text(o + sz / 2, o + 2, lbl, fontsize=6.5,
                     color=REGION_COLORS[k], ha="center", va="top",
                     fontweight="bold")
    ax1.scatter(has_diag, has_diag, c=DK_DIAG, s=0.5, marker=",", alpha=0.85,
                linewidths=0, rasterized=True)
    _scatter_pairs(ax1, inter, DK_TIE, s=2.4, alpha=0.95,
                   label=f"エリア間連系線 {n_inter}本")
    for r, _ in REGIONS:
        o = offsets[r]
        if o > 0:
            ax1.axhline(o, color=DK_SPINE, lw=0.4, zorder=4)
            ax1.axvline(o, color=DK_SPINE, lw=0.4, zorder=4)
    ax1.set_xlim(0, nb); ax1.set_ylim(nb, 0); ax1.set_aspect("equal")
    ax1.set_title(f"全国統合 Ybus（DB更新モデル・地域ブロック対角＋連系線）\n"
                  f"({nb:,} ノード, 結線{n_intra + n_inter:,}, "
                  f"エリア間{n_inter})",
                  fontsize=10, color=DK_TITLE, pad=6)
    ax1.set_xlabel("ノード番号", color=DK_SUB)
    ax1.set_ylabel("ノード番号", color=DK_SUB)
    ax1.legend(loc="lower left", fontsize=8, framealpha=0.0, labelcolor=DK_TIE,
               markerscale=4)

    _style_dark(ax2)
    labels = [lbl for _, lbl in REGIONS]
    densities = []
    for r, _ in REGIONS:
        sz = sizes[r]
        densities.append(len(intra[r]) / (sz * sz) * 100 if sz else 0.0)
    y = np.arange(len(labels))
    ax2.barh(y, densities, color=REGION_COLORS, alpha=0.9, height=0.62)
    ax2.set_yticks(y); ax2.set_yticklabels(labels, fontsize=8, color=DK_SUB)
    ax2.invert_yaxis()
    ax2.set_xlabel("地域内 充填率 (%)", color=DK_SUB)
    ax2.set_title("地域別 充填率(DBモデル)", fontsize=10, color=DK_TITLE, pad=6)
    ax2.grid(axis="x", color=DK_GRID, lw=0.5); ax2.set_axisbelow(True)
    for i, dd in enumerate(densities):
        ax2.text(dd, i, f" {dd:.3f}%", va="center", fontsize=7, color=DK_SUB)
    plt.suptitle("母線アドミタンス行列 Ybus — DB更新モデル(全国10地域+連系線)",
                 fontsize=12, y=1.00, color=DK_TITLE)
    plt.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "ybus_national.png"), dpi=140,
                bbox_inches="tight", facecolor=DK_FIG)
    plt.close(fig)
    print("  -> ybus_national.png", flush=True)


def render_gallery():
    fig, axes = plt.subplots(2, 5, figsize=(17, 6.8), facecolor=DK_FIG)
    for ax, (region, label) in zip(axes.flat, REGIONS):
        _style_dark(ax)
        path = os.path.join(BUILT_DIR, f"{region}.json")
        if not os.path.exists(path):
            ax.text(0.5, 0.5, f"{label}\n(なし)", ha="center", va="center",
                    transform=ax.transAxes, color=DK_SUB)
            ax.set_xticks([]); ax.set_yticks([]); continue
        nodes, pairs, _ = load_graph(path)
        nb = len(nodes)
        deg = np.array([n.get("deg", 0) for n in nodes])
        hd = np.where(deg >= 1)[0]
        _scatter_pairs(ax, pairs, DK_DOT, s=0.5, alpha=0.8)
        ax.scatter(hd, hd, c=DK_DIAG, s=0.5, marker=",", alpha=0.85,
                   linewidths=0, rasterized=True)
        ax.set_xlim(0, nb); ax.set_ylim(nb, 0); ax.set_aspect("equal")
        ax.set_title(f"{label} ({nb:,} ノード)", fontsize=8.5, color=DK_TITLE,
                     pad=3)
        ax.set_xticks([]); ax.set_yticks([])
    plt.suptitle("地域別 Ybus 一覧（DB更新モデル）— シアン:結線 / 橙:自己",
                 fontsize=12, y=1.01, color=DK_TITLE)
    plt.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "ybus_per_region.png"), dpi=130,
                bbox_inches="tight", facecolor=DK_FIG)
    plt.close(fig)
    print("  -> ybus_per_region.png", flush=True)


def build_anim(nat):
    """全国Ybusが地域ごとに組み上がる組立アニメ(連系線が入る瞬間も見える)。"""
    nodes_ord, nb, offsets, sizes, intra, inter, deg, _ = nat
    frames_dir = os.path.join(GIF_DIR, "_build_frames")
    os.makedirs(frames_dir, exist_ok=True)
    for f in os.listdir(frames_dir):
        if f.startswith("frame_"):
            os.remove(os.path.join(frames_dir, f))
    has_diag = np.where(deg >= 1)[0]
    # 各interエッジが「両端の地域が揃う」最初のregion index
    reg_idx = {r: k for k, (r, _) in enumerate(REGIONS)}
    # interエッジの所属(後から入る側のregion)を判定するため、新indexがどの地域かを引く
    bound = []  # region境界(累積)
    acc = 0
    for r, _ in REGIONS:
        acc += sizes[r]; bound.append(acc)
    def region_of(newidx):
        for k, b in enumerate(bound):
            if newidx < b:
                return k
        return len(bound) - 1
    inter_appear = []  # (k_required, (a,b))
    for a, b in inter:
        k = max(region_of(a), region_of(b))
        inter_appear.append((k, (a, b)))
    state = {"f": 0}

    def emit(kmax, title, rep=1):
        fig, ax = plt.subplots(figsize=(7.2, 7.6), facecolor=DK_FIG)
        fig.subplots_adjust(left=0.10, right=0.97, top=0.90, bottom=0.09)
        _style_dark(ax)
        for k in range(kmax):
            r = REGIONS[k][0]
            _scatter_pairs(ax, intra[r], REGION_COLORS[k], s=0.6, alpha=0.8)
            o, sz = offsets[r], sizes[r]
            if sz:
                ax.text(o + sz / 2, o + 2, REGIONS[k][1], fontsize=7,
                        color=REGION_COLORS[k], ha="center", va="top",
                        fontweight="bold")
        # この時点までに両端が揃ったinterエッジ
        shown = [e for (kk, e) in inter_appear if kk < kmax]
        # diag(描画済み地域のノードのみ)
        lim = bound[kmax - 1] if kmax > 0 else 0
        hd = has_diag[has_diag < lim]
        ax.scatter(hd, hd, c=DK_DIAG, s=0.6, marker=",", alpha=0.85,
                   linewidths=0, rasterized=True)
        _scatter_pairs(ax, shown, DK_TIE, s=2.4, alpha=0.95)
        ax.set_xlim(0, nb); ax.set_ylim(nb, 0); ax.set_aspect("equal")
        ax.set_title(title, fontsize=12, color=DK_TITLE, pad=10)
        ax.set_xlabel("ノード番号", color=DK_SUB)
        ax.set_ylabel("ノード番号", color=DK_SUB)
        for _ in range(rep):
            fig.savefig(os.path.join(frames_dir, f"frame_{state['f']:03d}.png"),
                        dpi=110, facecolor=DK_FIG)
            state["f"] += 1
        plt.close(fig)

    n_reg = len(REGIONS)
    emit(0, "全国 Ybus を10地域ごとに組み上げる →（赤=エリア間連系線）", rep=2)
    cum_n = 0
    for k in range(1, n_reg + 1):
        r, lbl = REGIONS[k - 1]
        cum_n += sizes[r]
        n_tie = sum(1 for (kk, _) in inter_appear if kk < k)
        emit(k, f"構築 {k}/{n_reg}  ＋{lbl}   "
                f"({cum_n:,} ノード, 連系線{n_tie})", rep=3)
    n_tie_all = len(inter)
    emit(n_reg, f"全国 Ybus 完成   ({nb:,} ノード, エリア間連系線{n_tie_all}本)",
         rep=7)
    print(f"  -> {state['f']} frames in {frames_dir}", flush=True)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("地域別(DBモデル)を描画...", flush=True)
    stats = {}
    for region, label in REGIONS:
        s = render_region(region, label)
        if s:
            stats[region] = s
            print(f"  {label}: {s['n_buses']:,}ノード/変電所{s['n_sub']:,}/"
                  f"結線{s['nnz']:,} density={s['density_pct']}%", flush=True)
    print("全国(DBモデル・連系線)を描画...", flush=True)
    nat = load_national()
    nodes_ord, nb, offsets, sizes, intra, inter, deg, nstats = nat
    n_intra = sum(len(v) for v in intra.values())
    print(f"  全国: {nb:,}ノード, intra={n_intra:,}, inter(連系線)={len(inter)}",
          flush=True)
    # 全国サマリを stats.json に同梱(HTMLが連系線数等を動的表示するため)
    stats["_national"] = {
        "n_nodes": int(nb),
        "n_sub": int(sum(v.get("n_sub", 0) for k, v in stats.items()
                         if not k.startswith("_"))),
        "n_intra": int(n_intra),
        "n_inter": int(len(inter)),
        "n_edges_model": int(nstats.get("n_edges", n_intra + len(inter))),
    }
    with open(os.path.join(OUT_DIR, "ybus", "stats.json"), "w",
              encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    render_national(nat)
    render_gallery()


if __name__ == "__main__":
    if "--build" in sys.argv:
        build_anim(load_national())
    else:
        main()
