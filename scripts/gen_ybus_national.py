"""
Generate fig_ybus_national.png: all-Japan combined Ybus sparsity + block structure.
Shows: (left) national Ybus block structure with region labels,
       (right) region-wise nnz/density bar chart.
"""

import json
import os
import platform
import math
import numpy as np
import scipy.sparse as spsp
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

if platform.system() == "Darwin":
    plt.rcParams["font.family"] = ["Hiragino Sans", "Apple SD Gothic Neo", "sans-serif"]
else:
    try:
        import japanize_matplotlib  # noqa
    except ImportError:
        pass

DATA_DIR, OUT_DIR = "data", "papers/figs"
os.makedirs(OUT_DIR, exist_ok=True)

REGIONS = [
    ("hokkaido","北海道"), ("tohoku","東北"), ("tokyo","東京"),
    ("chubu","中部"), ("hokuriku","北陸"), ("kansai","関西"),
    ("chugoku","中国"), ("shikoku","四国"), ("kyushu","九州"), ("okinawa","沖縄"),
]
REGION_COLORS = [
    "#e53935","#fb8c00","#fdd835","#43a047","#00acc1",
    "#1e88e5","#8e24aa","#d81b60","#546e7a","#6d4c41",
]


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    a = (math.sin(math.radians(lat2-lat1)/2)**2 +
         math.cos(math.radians(lat1))*math.cos(math.radians(lat2)) *
         math.sin(math.radians(lon2-lon1)/2)**2)
    return R * 2 * math.asin(math.sqrt(max(0, min(1, a))))


def get_centroid(geom):
    if geom["type"] == "Point":
        return geom["coordinates"][1], geom["coordinates"][0]
    elif geom["type"] == "Polygon":
        cs = geom["coordinates"][0]
        return np.mean([c[1] for c in cs]), np.mean([c[0] for c in cs])
    return None, None


def build_region_ybus(region):
    sp = f"{DATA_DIR}/{region}_substations.geojson"
    lp = f"{DATA_DIR}/{region}_lines.geojson"
    if not os.path.exists(sp) or not os.path.exists(lp):
        return None, 0
    subs = json.load(open(sp))["features"]
    lats, lons = [], []
    for feat in subs:
        la, lo = get_centroid(feat["geometry"])
        if la is None: continue
        lats.append(la); lons.append(lo)
    nb = len(lats)
    if nb < 2: return None, 0
    from scipy.spatial import cKDTree
    tree = cKDTree(list(zip(lats, lons)))
    lines = json.load(open(lp))["features"]
    edges = set()
    for feat in lines:
        g = feat["geometry"]
        if g["type"] == "LineString":
            coords = g["coordinates"]
            st, en = (coords[0][1], coords[0][0]), (coords[-1][1], coords[-1][0])
        elif g["type"] == "MultiLineString":
            parts = g["coordinates"]
            st = (parts[0][0][1], parts[0][0][0])
            en = (parts[-1][-1][1], parts[-1][-1][0])
        else:
            continue
        d1, i1 = tree.query(st, k=1)
        d2, i2 = tree.query(en, k=1)
        if d1 < 0.45 and d2 < 0.45 and i1 != i2:
            edges.add((min(i1, i2), max(i1, i2)))
    if not edges: return None, nb
    rows, cols, vals = [], [], []
    for i, j in edges:
        rows += [i,j,i,j]; cols += [j,i,i,j]; vals += [1,1,1,1]
    Y = spsp.csr_matrix((vals,(rows,cols)), shape=(nb,nb))
    return Y, nb


def main():
    region_ybus = []
    region_sizes = []
    print("Building per-region Ybus...")
    for (r, label) in REGIONS:
        Y, nb = build_region_ybus(r)
        region_ybus.append((r, label, Y, nb))
        region_sizes.append(nb)
        print(f"  {label}: {nb} buses, {Y.nnz if Y is not None else 0} nnz")

    total_buses = sum(region_sizes)
    print(f"Total buses (all regions): {total_buses:,}")

    # Build block-diagonal national Ybus
    blocks = [Y for _, _, Y, nb in region_ybus if Y is not None]
    if not blocks:
        print("No Ybus data available"); return

    Y_national = spsp.block_diag(blocks, format="csr")
    nb_nat = Y_national.shape[0]
    print(f"National Ybus: {nb_nat}x{nb_nat}, nnz={Y_national.nnz:,}")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6.5),
                                    facecolor="white",
                                    gridspec_kw={"width_ratios": [3, 1.2]})

    # ── Left: national Ybus spy plot ──────────────────────────────
    ax1.set_facecolor("white")
    Y_dense = Y_national.toarray()
    nzr, nzc = np.where(Y_dense > 0)

    # Color by region
    bus_region = []
    offset = 0
    region_offsets = []
    valid_regions = [(lbl, Y, nb, REGION_COLORS[idx])
                     for idx, (r, lbl, Y, nb) in enumerate(region_ybus)
                     if Y is not None]
    for lbl, Y, nb, col in valid_regions:
        region_offsets.append((offset, nb, lbl, col))
        bus_region.extend([col] * nb)
        offset += nb

    # Scatter by region color
    for off, nb, lbl, col in region_offsets:
        mask = (nzr >= off) & (nzr < off + nb)
        if mask.any():
            ax1.scatter(nzc[mask], nzr[mask], c=col, s=0.5, marker=",",
                        alpha=0.5, linewidths=0, rasterized=True)

    # Region boundary lines and labels
    offset = 0
    for off, nb, lbl, col in region_offsets:
        if off > 0:
            ax1.axhline(off, color="#aaa", lw=0.5, zorder=4)
            ax1.axvline(off, color="#aaa", lw=0.5, zorder=4)
        mid = off + nb // 2
        ax1.text(mid, off + 2, lbl, fontsize=6.5, color=col,
                 ha="center", va="top", fontweight="bold")
        offset += nb

    ax1.set_xlim(0, nb_nat)
    ax1.set_ylim(nb_nat, 0)
    density = Y_national.nnz / (nb_nat ** 2) * 100
    ax1.set_title(
        f"全国統合 $\\mathbf{{Y}}_{{\\mathrm{{bus}}}}$ スパイプロット\n"
        f"({nb_nat:,} バス, nnz={Y_national.nnz:,}, 充填率={density:.4f}%)",
        fontsize=10, pad=5, color="#222"
    )
    ax1.tick_params(labelsize=7)
    for sp_ in ax1.spines.values(): sp_.set_color("#ccc")
    ax1.set_xlabel("バス番号", fontsize=9)
    ax1.set_ylabel("バス番号", fontsize=9)

    # ── Right: region-wise density bar chart ──────────────────────
    ax2.set_facecolor("white")
    labels_ = [lbl for lbl, Y, nb, col in valid_regions]
    nnzs    = [Y.nnz for lbl, Y, nb, col in valid_regions]
    nbs     = [nb for lbl, Y, nb, col in valid_regions]
    densities = [nnz/(nb*nb)*100 for nnz, nb in zip(nnzs, nbs)]
    colors  = [col for lbl, Y, nb, col in valid_regions]

    y_pos = np.arange(len(labels_))
    ax2.barh(y_pos, densities, color=colors, alpha=0.85, height=0.6)
    ax2.set_yticks(y_pos)
    ax2.set_yticklabels(labels_, fontsize=8.5)
    ax2.set_xlabel("$Y_{\\mathrm{bus}}$ 充填率 (%)", fontsize=9)
    ax2.set_title("地域別 Ybus 充填率", fontsize=10, pad=5, color="#222")
    ax2.grid(axis="x", color="#ddd", lw=0.5)
    ax2.set_axisbelow(True)
    for sp_ in ax2.spines.values(): sp_.set_color("#ccc")

    # Add nnz/buses annotation
    for i, (nnz, nb, d) in enumerate(zip(nnzs, nbs, densities)):
        ax2.text(d + 0.005, i, f"{d:.3f}%", va="center", fontsize=7, color="#444")

    plt.suptitle(
        "母線アドミタンス行列 $\\mathbf{Y}_{\\mathrm{bus}}$——全国10地域ブロック対角構造",
        fontsize=12, y=1.01, color="#111"
    )
    plt.tight_layout()
    out = f"{OUT_DIR}/fig_ybus_national.png"
    plt.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
