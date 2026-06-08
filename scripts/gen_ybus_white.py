"""
Regenerate fig_ybus_all.png with WHITE background.
Builds Ybus sparsity pattern directly from GeoJSON topology.
"""

import json
import os
import sys
import platform
import math
import numpy as np
import scipy.sparse as sp
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

if platform.system() == "Darwin":
    plt.rcParams["font.family"] = ["Hiragino Sans", "Apple SD Gothic Neo", "sans-serif"]
else:
    try:
        import japanize_matplotlib  # noqa
    except ImportError:
        pass

DATA_DIR = "data"
OUT_DIR = "papers/figs"
os.makedirs(OUT_DIR, exist_ok=True)

REGIONS = [
    ("hokkaido", "北海道"),
    ("tohoku",   "東北"),
    ("tokyo",    "東京"),
    ("chubu",    "中部"),
    ("hokuriku", "北陸"),
    ("kansai",   "関西"),
    ("chugoku",  "中国"),
    ("shikoku",  "四国"),
    ("kyushu",   "九州"),
    ("okinawa",  "沖縄"),
]


def haversine_km(lat1, lon1, lat2, lon2):
    # Canonical impl in src.utils.geo_utils (same (lat, lon) order).
    from src.utils.geo_utils import haversine_distance
    return haversine_distance(lat1, lon1, lat2, lon2)


def get_centroid(geom):
    if geom["type"] == "Point":
        return geom["coordinates"][1], geom["coordinates"][0]
    elif geom["type"] in ("Polygon", "MultiPolygon"):
        if geom["type"] == "Polygon":
            coords = geom["coordinates"][0]
        else:
            coords = geom["coordinates"][0][0]
        lat = np.mean([c[1] for c in coords])
        lon = np.mean([c[0] for c in coords])
        return lat, lon
    return None, None


def get_line_endpoints(geom):
    if geom["type"] == "LineString":
        coords = geom["coordinates"]
        return (coords[0][1], coords[0][0]), (coords[-1][1], coords[-1][0])
    elif geom["type"] == "MultiLineString":
        parts = geom["coordinates"]
        start = parts[0][0]
        end = parts[-1][-1]
        return (start[1], start[0]), (end[1], end[0])
    return None, None


def build_ybus_sparsity(region):
    """Build approximate Ybus connectivity from GeoJSON substations+lines."""
    sub_path = f"{DATA_DIR}/{region}_substations.geojson"
    line_path = f"{DATA_DIR}/{region}_lines.geojson"
    if not os.path.exists(sub_path) or not os.path.exists(line_path):
        return None, 0, 0

    # Load substations
    with open(sub_path) as f:
        subs = json.load(f)["features"]
    bus_lats, bus_lons = [], []
    for feat in subs:
        lat, lon = get_centroid(feat["geometry"])
        if lat is None:
            continue
        bus_lats.append(lat)
        bus_lons.append(lon)
    nb = len(bus_lats)
    if nb < 2:
        return None, nb, 0

    # Build k-d tree for endpoint matching
    from scipy.spatial import cKDTree
    bus_arr = np.column_stack([bus_lats, bus_lons])
    tree = cKDTree(bus_arr)

    # Load lines and match endpoints to nearest bus
    with open(line_path) as f:
        lines = json.load(f)["features"]
    edges = set()
    for feat in lines:
        ep = get_line_endpoints(feat["geometry"])
        if ep[0] is None:
            continue
        start, end = ep
        d1, i1 = tree.query(start, k=1)
        d2, i2 = tree.query(end, k=1)
        # threshold ~50km
        if d1 < 0.45 and d2 < 0.45 and i1 != i2:
            edges.add((min(i1, i2), max(i1, i2)))

    nnz = len(edges)
    if nnz == 0:
        return None, nb, 0

    # Build sparse symmetric matrix (connectivity = Ybus sparsity)
    rows, cols, vals = [], [], []
    for i, j in edges:
        rows += [i, j, i, j]
        cols += [j, i, i, j]
        vals += [1.0, 1.0, 1.0, 1.0]
    Y = sp.csr_matrix((vals, (rows, cols)), shape=(nb, nb))
    return Y, nb, nnz


def main():
    fig, axes = plt.subplots(2, 5, figsize=(18, 7), facecolor="white")
    axes = axes.flatten()

    for idx, (region, label) in enumerate(REGIONS):
        ax = axes[idx]
        ax.set_facecolor("white")
        print(f"  Building Ybus for {label}...")
        Y, nb, nnz = build_ybus_sparsity(region)

        if Y is not None and nb > 0:
            Y_dense = Y.toarray()
            nzr, nzc = np.where(Y_dense > 0)
            ax.scatter(nzc, nzr, c="#cc0000", s=0.6, marker=",",
                       alpha=0.55, linewidths=0, rasterized=True)
            ax.set_xlim(0, nb)
            ax.set_ylim(nb, 0)
            density = nnz / (nb * nb) * 100 if nb > 0 else 0
            ax.text(0.97, 0.03,
                    f"nnz={nnz:,}\n{density:.3f}%",
                    transform=ax.transAxes, fontsize=6,
                    ha="right", va="bottom", color="#555",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white",
                              ec="#ccc", alpha=0.85))
        else:
            ax.text(0.5, 0.5, "N/A", ha="center", va="center",
                    transform=ax.transAxes, fontsize=10, color="#aaa")

        ax.set_title(f"{label}\n({nb} バス)", fontsize=8, pad=3, color="#222")
        ax.tick_params(labelsize=5.5)
        for sp_ in ax.spines.values():
            sp_.set_color("#ccc")

    plt.suptitle(
        "全10地域  母線アドミタンス行列 $\\mathbf{Y}_{\\mathrm{bus}}$ スパイプロット（充填率 $<$ 0.01\\%）",
        fontsize=12, y=1.01, color="#222"
    )
    plt.tight_layout()
    plt.subplots_adjust(wspace=0.3, hspace=0.55)
    out = f"{OUT_DIR}/fig_ybus_all.png"
    plt.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
