"""Render the built grid as a single-image 系統図 (for LINE delivery).

    PYTHONPATH=. python scripts/render_grid_figure.py [--region tokyo]
        [--out /tmp/grid_tokyo.png] [--kpi docs/reports/external_flows_*.json]

Draws every branch on its real OSM route, coloured by voltage class
(cables dashed), substations as dots, with an honest KPI box (current
3-layer rho + attachment recall + model size). The loop sends the
output to LINE after每 model-changing iteration (PLAN_66KV 運転規則4).
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CLASS_STYLE = [  # (min_kv, color, width, zorder)
    (500, "#cc0000", 1.6, 7),
    (275, "#0044cc", 1.2, 6),
    (187, "#e6a000", 0.9, 5),
    (154, "#007733", 0.8, 5),
    (110, "#885500", 0.55, 4),
    (77,  "#660077", 0.45, 4),
    (66,  "#334455", 0.4, 3),
    (0,   "#999999", 0.3, 2),
]


def _style(kv):
    for mn, c, w, z in CLASS_STYLE:
        if kv >= mn:
            return c, w, z
    return CLASS_STYLE[-1][1:]


def render(region: str, out: str, kpi_json: str | None = None) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    from src.powerflow.snapped_topology import build_network_snapped

    if region == "national":
        return render_national(out)

    net = build_network_snapped(region)
    if net is None:
        raise SystemExit(f"no data for region {region}")

    fig, ax = plt.subplots(figsize=(14, 14), dpi=150)
    n_branch = 0
    cable_km = 0.0
    for ln in net.transmission_lines:
        if "_xfmr_" in ln.id or not ln.coordinates:
            continue
        kv = float(ln.voltage_kv or 0)
        c, w, z = _style(kv)
        xs = [lon for (_la, lon) in ln.coordinates]
        ys = [la for (la, _lo) in ln.coordinates]
        if len(xs) < 2:
            continue
        dash = (0, (2.5, 1.5)) if getattr(ln, "is_cable", False) else "solid"
        if getattr(ln, "is_cable", False):
            cable_km += float(ln.length_km or 0)
        ax.plot(xs, ys, color=c, linewidth=w, zorder=z, alpha=0.85,
                linestyle=dash, solid_capstyle="round")
        n_branch += 1

    n_sub = 0
    for s in net.substations:
        if "_jct_" in s.id:
            continue
        kv = float(s.voltage_kv or 0)
        c, _w, z = _style(kv)
        ax.plot(s.longitude, s.latitude, "o", ms=2.2 if kv >= 154 else 1.2,
                color=c, mec="white", mew=0.2, zorder=z + 3)
        n_sub += 1

    ax.set_aspect(1.0 / 0.82)        # ~Kanto latitude aspect
    ax.set_axis_off()

    kpi_lines = [f"All-Japan-Grid 系統図 — {region}",
                 f"branches {n_branch:,} / substations {n_sub:,} / "
                 f"cable {cable_km:,.0f} km"]
    if kpi_json:
        paths = sorted(glob.glob(kpi_json))
        if paths:
            m = json.load(open(paths[-1]))
            kpi_lines.append(
                f"flow ρ (vs TEPCO): interior {m.get('interior_spearman_rho')}"
                f" | trunk {m.get('trunk_spearman_rho')}"
                f" | 154kV {m.get('kv154_spearman_rho')}"
                f" | 66kV {m.get('kv66_spearman_rho')}")
            kpi_lines.append(os.path.basename(paths[-1]))
    ax.set_title("\n".join(kpi_lines), fontsize=11, family="Hiragino Sans",
                 loc="left")

    handles = [Line2D([], [], color=c, lw=max(w * 2, 1.2),
                      label=f"{mn}kV+" if mn else "unknown")
               for mn, c, w, _z in CLASS_STYLE]
    handles.append(Line2D([], [], color="#334455", lw=1.2,
                          linestyle=(0, (2.5, 1.5)), label="cable(地中)"))
    ax.legend(handles=handles, loc="lower right", fontsize=8, frameon=True)

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"figure -> {out}")
    return out


def render_national(out: str) -> str:
    """One-Japan figure: all 10 regions on real routes (the network that
    now solves AC on all four synchronous islands — ledger 63)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    from src.powerflow.snapped_topology import build_network_snapped
    from src.regions import REGIONS

    fig, ax = plt.subplots(figsize=(13, 15), dpi=150)
    n_branch = n_sub = 0
    for region in REGIONS:
        net = build_network_snapped(region)
        if net is None:
            continue
        for ln in net.transmission_lines:
            if "_xfmr_" in ln.id or not ln.coordinates or len(ln.coordinates) < 2:
                continue
            kv = float(ln.voltage_kv or 0)
            c, w, z = _style(kv)
            xs = [lon for (_la, lon) in ln.coordinates]
            ys = [la for (la, _lo) in ln.coordinates]
            dash = (0, (2.5, 1.5)) if getattr(ln, "is_cable", False) else "solid"
            ax.plot(xs, ys, color=c, linewidth=w * 0.8, zorder=z, alpha=0.8,
                    linestyle=dash, solid_capstyle="round")
            n_branch += 1
        for s in net.substations:
            if "_jct_" in s.id:
                continue
            kv = float(s.voltage_kv or 0)
            c, _w, z = _style(kv)
            ax.plot(s.longitude, s.latitude, "o",
                    ms=1.6 if kv >= 154 else 0.8, color=c,
                    mec="white", mew=0.15, zorder=z + 3)
            n_sub += 1
    ax.set_aspect(1.0 / 0.82)
    ax.set_xlim(127.0, 146.2)
    ax.set_ylim(26.0, 45.8)
    ax.set_axis_off()
    ax.set_title(
        "All-Japan-Grid — 日本一体の潮流計算可能系統 (全国10地域)\n"
        f"branches {n_branch:,} / substations {n_sub:,} | "
        "同期4島 (北海道・東50Hz・西60Hz・沖縄) すべて AC収束 (2026-06-12 台帳63)\n"
        "vm: 北海道[0.86,1.03] 東[0.89,1.06] 西[0.66,1.05] 沖縄[0.96,1.01]",
        fontsize=12, family="Hiragino Sans", loc="left")
    handles = [Line2D([], [], color=c, lw=max(w * 2, 1.2),
                      label=f"{mn}kV+" if mn else "unknown")
               for mn, c, w, _z in CLASS_STYLE]
    handles.append(Line2D([], [], color="#334455", lw=1.2,
                          linestyle=(0, (2.5, 1.5)), label="cable(地中)"))
    ax.legend(handles=handles, loc="lower right", fontsize=9, frameon=True)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"figure -> {out}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", default="tokyo")
    ap.add_argument("--out", default="/tmp/grid_figure.png")
    ap.add_argument("--kpi",
                    default="docs/reports/external_flows_tokyo_full_*.json",
                    help="glob; the newest scorecard annotates the figure")
    args = ap.parse_args(argv)
    render(args.region, args.out, args.kpi)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
