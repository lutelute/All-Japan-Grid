"""SubScope — GridStitch 変電所構造ビューア.

指定した変電所(名前部分一致)について、OSM実データから次の2図を生成する:
  (A) OSM実構造図(地図): 母線(busbar)/ベイ(bay)/本線を電圧で色分け。構内の結線と引込線の方向が一目で分かる。
  (B) 単線結線図(SLD・draft): 電圧階級ごとに1母線、隣接階級をカスケード変圧器で繋ぐ(500/77等の飛び越しは作らない)。
      これは点検用のドラフト(潮流の bus-branch ビューに対応)。複母線・区分は忠実層で後から展開できる。

設計方針(オーナー 2026-06-14〜15): OSM=正・電圧は接続先から辿って埋める・畳んでも展開余地を残す・捏造禁止。

Usage:
    PYTHONPATH=. python scripts/substation_scope.py --region kansai --name 嶺南
    PYTHONPATH=. python scripts/substation_scope.py --region tokyo  --name 沼津 --out /tmp
"""
import argparse
import collections
import json
import os

_VCOL = {"500": "#d62728", "275": "#ff7f0e", "154": "#9467bd",
         "110": "#1f77b4", "77": "#2ca02c", "66": "#17becf", "33": "#8c564b"}
_UNK = "#999999"


def _font():
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    for cand in ("Hiragino Sans", "Hiragino Maru Gothic Pro", "YuGothic",
                 "Arial Unicode MS", "AppleGothic", "Noto Sans CJK JP"):
        try:
            if fm.findfont(cand, fallback_to_default=False):
                plt.rcParams["font.family"] = cand
                break
        except Exception:   # noqa: BLE001
            continue
    plt.rcParams["axes.unicode_minus"] = False


def _vclasses(v):
    """voltage文字列 '500000;275000' -> ['500','275'](kV・降順)。"""
    out = []
    for tok in str(v or "").replace("／", ";").replace(",", ";").split(";"):
        tok = "".join(ch for ch in tok if ch.isdigit())
        if tok:
            kv = int(tok) // 1000
            if kv > 0:
                out.append(str(kv))
    return sorted(set(out), key=lambda s: -int(s))


def _vcol(v):
    cs = _vclasses(v)
    return _VCOL.get(cs[0], _UNK) if cs else _UNK


def _allpts(g):
    pts = []

    def w(a):
        if isinstance(a, (int, float)):
            return
        if len(a) >= 2 and isinstance(a[0], (int, float)):
            pts.append(a)
            return
        for x in a:
            w(x)
    w(g["coordinates"])
    return pts


def _segments(g):
    t = g.get("type")
    if t == "LineString":
        return [g["coordinates"]]
    if t == "MultiLineString":
        return g["coordinates"]
    return []


def load(region, data_dir="data"):
    subs = json.load(open(os.path.join(data_dir, f"{region}_substations.geojson"),
                          encoding="utf-8"))
    lines = json.load(open(os.path.join(data_dir, f"{region}_lines.geojson"),
                           encoding="utf-8"))
    return subs, lines


def find_sub(subs, name):
    return [f for f in subs["features"]
            if name in str((f.get("properties") or {}).get("name", ""))]


def _center(feats):
    P = []
    for f in feats:
        P += _allpts(f["geometry"])
    return sum(p[0] for p in P) / len(P), sum(p[1] for p in P) / len(P)


def anatomy_fig(region, name, feats, lines, out, radius=0.02):
    """(A) OSM実構造図。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.lines as ml
    _font()
    clon, clat = _center(feats)
    fig, ax = plt.subplots(figsize=(11, 10), dpi=120)
    for f in feats:
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            ring = poly[0]
            ax.fill([c[0] for c in ring], [c[1] for c in ring], color="#e8e8f0",
                    alpha=0.5, zorder=1)
            ax.plot([c[0] for c in ring], [c[1] for c in ring], color="#5555aa",
                    lw=1, zorder=2)
    for f in lines["features"]:
        g = f["geometry"]
        if not any(abs(x[0] - clon) < radius and abs(x[1] - clat) < radius
                   for x in _allpts(g)):
            continue
        p = f.get("properties") or {}
        lt = p.get("line")
        col = _vcol(p.get("voltage"))
        for seg in _segments(g):
            if len(seg) < 2:
                continue
            xs = [c[0] for c in seg]
            ys = [c[1] for c in seg]
            if lt == "busbar":
                ax.plot(xs, ys, color=col, lw=3.5, zorder=5, solid_capstyle="round")
            elif lt == "bay":
                ax.plot(xs, ys, color=col, lw=1.0, ls=(0, (3, 2)), alpha=0.7, zorder=4)
            elif lt in ("substation", "internal"):
                ax.plot(xs, ys, color=col, lw=1.0, alpha=0.5, zorder=3)
            else:
                ax.plot(xs, ys, color=col, lw=2.0, zorder=4)
    seen = set()
    for f in lines["features"]:
        p = f.get("properties") or {}
        if p.get("line") is not None:
            continue
        nm = p.get("name")
        if not nm or nm in seen or name not in nm:
            continue
        far, fd = None, 0.0
        for x in _allpts(f["geometry"]):
            d = (x[0] - clon) ** 2 + (x[1] - clat) ** 2
            if fd < d < radius * radius:
                fd, far = d, x
        if far:
            seen.add(nm)
            ax.annotate(nm.replace("変電所", "").replace("~", "-"), (far[0], far[1]),
                        fontsize=7, color=_vcol(p.get("voltage")), zorder=6)
    ax.set_xlim(clon - radius, clon + radius)
    ax.set_ylim(clat - radius, clat + radius)
    ax.set_title(f"{name}変電所 OSM実構造  (太=母線 破=ベイ 中=本線・色=電圧)", fontsize=11)
    ax.set_xlabel("lon")
    ax.set_ylabel("lat")
    ax.grid(True, alpha=0.2)
    handles = [ml.Line2D([], [], color=_VCOL[k], lw=3, label=f"{k}kV")
               for k in ("500", "275", "154", "110", "77", "66") if k in _VCOL]
    handles += [ml.Line2D([], [], color=_UNK, lw=3, label="無印"),
                ml.Line2D([], [], color="k", lw=3.5, label="母線"),
                ml.Line2D([], [], color="k", lw=1, ls="--", label="ベイ"),
                ml.Line2D([], [], color="k", lw=2, label="本線")]
    ax.legend(handles=handles, loc="upper left", fontsize=8, ncol=2)
    plt.tight_layout()
    path = os.path.join(out, f"subscope_{region}_{name}_osm.png")
    plt.savefig(path, bbox_inches="tight")
    plt.close()
    return path


def derive_model(name, feats, lines, radius=0.02):
    """OSM接続から SLD用モデル(draft)を導出: 電圧階級 + 各階級の引込線名。"""
    clon, clat = _center(feats)
    levels = collections.OrderedDict()   # kv(str) -> list[line name]
    # 敷地ポリゴンの電圧タグも階級として種にする
    poly_kv = set()
    for f in feats:
        poly_kv |= set(_vclasses((f.get("properties") or {}).get("voltage")))
    for f in lines["features"]:
        p = f.get("properties") or {}
        if p.get("line") is not None:   # busbar/bay/substation は内部=骨格には出さない
            continue
        g = f["geometry"]
        if not any(abs(x[0] - clon) < radius and abs(x[1] - clat) < radius
                   for x in _allpts(g)):
            continue
        for kv in _vclasses(p.get("voltage")):
            levels.setdefault(kv, [])
            nm = p.get("name")
            if nm and name in nm:
                short = nm.replace("変電所", "").replace(f"{name}", "").replace("~", "").strip()
                if short and short not in levels[kv]:
                    levels[kv].append(short)
    for kv in poly_kv:
        levels.setdefault(kv, [])
    ordered = collections.OrderedDict(
        sorted(levels.items(), key=lambda kv: -int(kv[0])))
    return ordered


def sld_fig(region, name, model, out):
    """(B) 単線結線図(draft)。電圧階級ごとに1母線・隣接をカスケード変圧器で接続。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle
    _font()
    kvs = list(model.keys())
    n = len(kvs)
    fig, ax = plt.subplots(figsize=(10, max(5, 2.4 * n + 2)), dpi=120)
    ax.set_xlim(0, 10)
    top = 2.4 * n + 1
    ax.set_ylim(0, top + 1.5)
    ax.axis("off")
    ys = {kv: top - 0.4 - 2.4 * i for i, kv in enumerate(kvs)}
    for kv in kvs:
        y = ys[kv]
        col = _VCOL.get(kv, _UNK)
        ax.plot([1.5, 7.5], [y, y], color=col, lw=7, solid_capstyle="round", zorder=3)
        ax.text(1.3, y, f"{kv}kV 母線", ha="right", va="center", fontsize=12,
                color=col, fontweight="bold")
        feeders = model[kv][:6]
        if feeders:
            xs = [2.2 + 0.9 * j for j in range(len(feeders))]
            for x, fn in zip(xs, feeders):
                ax.plot([x, x], [y, y + 0.9], color=col, lw=2, zorder=2)
                ax.plot(x, y + 0.9, "o", color=col, ms=6, zorder=2)
                ax.text(x, y + 1.05, fn, ha="center", va="bottom", fontsize=8, color=col)
    # カスケード変圧器(隣接階級のみ・飛び越し無し)
    for i in range(n - 1):
        y1, y2 = ys[kvs[i]], ys[kvs[i + 1]]
        ym = (y1 + y2) / 2
        ax.add_patch(Circle((6.7, ym + 0.22), 0.30, fill=False, ec="#333", lw=2, zorder=4))
        ax.add_patch(Circle((6.7, ym - 0.22), 0.30, fill=False, ec="#333", lw=2, zorder=4))
        ax.plot([6.7, 6.7], [y1, ym + 0.5], color="#333", lw=1.5, zorder=2)
        ax.plot([6.7, 6.7], [ym - 0.5, y2], color="#333", lw=1.5, zorder=2)
        ax.text(7.15, ym, f"T  {kvs[i]}/{kvs[i+1]}\n1次={kvs[i]}(HV)/2次={kvs[i+1]}(LV)",
                ha="left", va="center", fontsize=9, color="#333")
    ax.text(5, top + 0.9, f"{name}変電所 単線結線図(SubScope draft)",
            ha="center", fontsize=14, fontweight="bold")
    ax.text(5, 0.4,
            "潮流層: 各電圧=1バス・単位法・カスケード変圧器(飛び越し無し)\n"
            "忠実層: 母線/ベイ/端点を保持 → 複母線・区分へ展開可。電圧は接続先から辿って確定。",
            ha="center", va="center", fontsize=9, color="#444",
            bbox=dict(boxstyle="round", fc="#f4f4f8", ec="#ccc"))
    plt.tight_layout()
    path = os.path.join(out, f"subscope_{region}_{name}_sld.png")
    plt.savefig(path, bbox_inches="tight")
    plt.close()
    return path


def scope(region, name, out="/tmp", data_dir="data"):
    subs, lines = load(region, data_dir)
    feats = find_sub(subs, name)
    if not feats:
        raise SystemExit(f"変電所 '{name}' が {region} に見つかりません")
    os.makedirs(out, exist_ok=True)
    a = anatomy_fig(region, name, feats, lines, out)
    model = derive_model(name, feats, lines)
    b = sld_fig(region, name, model, out)
    return a, b, model


def main():
    ap = argparse.ArgumentParser(description="SubScope — 変電所構造ビューア(OSM実構造+単線結線図)")
    ap.add_argument("--region", required=True)
    ap.add_argument("--name", required=True, help="変電所名(部分一致)")
    ap.add_argument("--out", default="/tmp")
    args = ap.parse_args()
    a, b, model = scope(args.region, args.name, args.out)
    print("OSM実構造図:", a)
    print("単線結線図  :", b)
    print("導出モデル(電圧→引込線):")
    for kv, fs in model.items():
        print(f"  {kv}kV: {fs}")


if __name__ == "__main__":
    main()
