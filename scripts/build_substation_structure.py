"""変電所内部構造(node-breaker)の実証ビルダー — GridStitch P2 プロトタイプ.

オーナー方針(2026-07-02): 「線は基本変電所に入る。変電所で電圧階級・タップ・回線・
導体を接続する。そこから負荷に分配供給されるからである。」
本スクリプトはその第一歩として、1変電所の OSM 実データ(busbar/bay/本線の頂点共有)から
node-breaker 構造(SubstationSite / VoltageLevel / BusbarSection / Bay / Terminal /
TransformerSpec)を抽出し、JSON(第一級データ) + 検証図を出力する。

方針(嶺南で実証→スキーマ確定→機械化, オーナー 2026-06-15/2026-07-02):
  - OSM=正: 接続は頂点共有・ポリゴン内包の実証拠のみ。捏造禁止。
  - 全 Terminal に binding(根拠)・confidence・source を刻む。
  - 電圧無タグは 0 のまま保持(@u)。推測で nominal_kv を埋めない。
  - 変圧器は「存在と両端」だけを構造として主張(source=structural)。
    電気定数・タップは出典付きデータが入るまで空欄(合成値は潮流層の責務)。

Usage:
    PYTHONPATH=. .venv/bin/python scripts/build_substation_structure.py \
        --region kansai --name 嶺南変電所 [--out data/structures] [--fig /tmp]
"""
import argparse
import hashlib
import json
import os
from collections import defaultdict
from dataclasses import asdict

from scripts.substation_scope import _font, _segments, _vclasses, load
from src.model.substation_structure import (
    Bay,
    BusbarSection,
    SubstationSite,
    SubstationStructure,
    Terminal,
    TransformerSpec,
    VoltageLevel,
)
from src.powerflow.snapped_topology import _parse_circuits

_VPREC = 6            # 頂点キー精度(~0.1m) — 構内 snap≈0.1m(GRIDSTITCH_PLAN U2)
_PAD_DEG = 0.01       # 線収集の bbox パディング
_LEADIN_DEG = 0.006   # ポリゴン外の lead-in 許容(~0.6km ≒ fallback_endpoint_km)


def _vk(c):
    return (round(c[0], _VPREC), round(c[1], _VPREC))


def _geom_key(coords, name=""):
    """way の安定キー(正規化ジオメトリ SHA1 先頭12桁)。db 幾何キーと同思想。"""
    norm = json.dumps([[round(x, 6), round(y, 6)] for x, y in coords])
    return "g:" + hashlib.sha1((norm + "|" + (name or "")).encode()).hexdigest()[:12]


class _UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def _pick_site(subs, name):
    """名前完全一致優先で変電所 feature を1つ選ぶ。"""
    exact, partial = [], []
    for ft in subs["features"]:
        n = (ft.get("properties") or {}).get("name") or ""
        if n == name:
            exact.append(ft)
        elif name in n:
            partial.append(ft)
    cands = exact or partial
    if not cands:
        raise ValueError(f"変電所 '{name}' が見つかりません")
    if len(cands) > 1:
        print(f"[warn] '{name}' 候補 {len(cands)} 件 → 先頭を採用")
    return cands[0]


def prepare_ways(lines):
    """lines GeoJSON を一括前処理(セグメント単位・bbox付き)。

    地域一括生成で変電所ごとの全走査を避けるため、coords/props/kind/key/bbox を
    1回だけ計算する。単発呼び出しも同じ経路を通る(挙動の単一の正)。
    """
    out = []
    for ft in lines["features"]:
        g = ft.get("geometry") or {}
        p = ft.get("properties") or {}
        kind = p.get("line")
        if kind not in ("busbar", "bay"):
            kind = "main"
        for seg in _segments(g):
            xs = [c[0] for c in seg]
            ys = [c[1] for c in seg]
            out.append({"coords": seg, "props": p, "kind": kind,
                        "key": _geom_key(seg, p.get("name")),
                        "bbox": (min(xs), min(ys), max(xs), max(ys))})
    return out


def _collect_ways(pways, bbox):
    """前処理済み ways から bbox に触れるものを収集(way-bbox プレフィルタ)。"""
    x0, y0, x1, y1 = bbox
    out = []
    for w in pways:
        wx0, wy0, wx1, wy1 = w["bbox"]
        if wx1 < x0 or wx0 > x1 or wy1 < y0 or wy0 > y1:
            continue
        if any(x0 <= x <= x1 and y0 <= y <= y1 for x, y in w["coords"]):
            out.append(w)
    return out


def _primary_kv(props):
    """way の主電圧クラス(kV int)。無タグは 0。"""
    cs = _vclasses(props.get("voltage"))
    return int(cs[0]) if cs else 0


def _components(ways, uf_key):
    """頂点共有 union-find → 成分ごとの way リスト。決定的順序。"""
    uf = _UF()
    vown = defaultdict(list)
    for w in ways:
        uf.find(w["key"])
        for c in w["coords"]:
            vown[uf_key(c)].append(w["key"])
    for keys in vown.values():
        for k2 in keys[1:]:
            uf.union(keys[0], k2)
    comp = defaultdict(list)
    bykey = {w["key"]: w for w in ways}
    for w in sorted(ways, key=lambda w: w["key"]):
        comp[uf.find(w["key"])].append(bykey[w["key"]])
    return [comp[r] for r in sorted(comp)]


def _outline_coords(geom):
    """幾何の外形座標列(Polygon/MultiPolygon/Point いずれも安全)。"""
    t = geom.geom_type
    if t == "Polygon":
        return list(geom.exterior.coords)
    if t == "MultiPolygon":
        return list(list(geom.geoms)[0].exterior.coords)
    return [(geom.centroid.x, geom.centroid.y)]   # Point 等


def build_structure(region, name, data_dir="data"):
    """1変電所の node-breaker 構造を OSM 実データから抽出する(単発用)。"""
    subs, lines = load(region, data_dir)
    ft = _pick_site(subs, name)
    return extract_structure(region, ft, prepare_ways(lines))


def extract_structure(region, ft, pways):
    """変電所 feature 1件から node-breaker 構造を抽出する(一括生成の実体)。

    Args:
        region: 地域 id。
        ft: substations GeoJSON の feature。
        pways: :func:`prepare_ways` の結果(地域全体で共有)。
    """
    from shapely.geometry import Point, shape

    props = ft.get("properties") or {}
    poly = shape(ft["geometry"])
    cx, cy = poly.centroid.x, poly.centroid.y
    # ID は実名(props)から導出する。検索クエリ name を使うと同一変電所でも
    # 検索語ごとに別 site_id になり、第一級データの同一性が壊れる(検証で発覚)。
    canon_name = props.get("name") or ""
    site_id = f"{region}_site_{_geom_key([[cx, cy]], canon_name)[2:]}"
    site = SubstationSite(
        site_id=site_id, name=canon_name, region=region,
        operator=props.get("operator"), substation_type=props.get("substation"),
        osm_keys=[_geom_key(_outline_coords(poly), canon_name)],
        lat=round(cy, 6), lon=round(cx, 6))

    x0, y0, x1, y1 = poly.bounds
    ways = _collect_ways(pways, (x0 - _PAD_DEG, y0 - _PAD_DEG,
                                 x1 + _PAD_DEG, y1 + _PAD_DEG))
    busbars_w = [w for w in ways if w["kind"] == "busbar"]
    bays_w = [w for w in ways if w["kind"] == "bay"]
    mains_w = [w for w in ways if w["kind"] == "main"]

    # --- VoltageLevel: ポリゴンタグ ∪ 構内線タグ ---
    kvs = {int(c) for c in _vclasses(props.get("voltage"))}
    for w in busbars_w + bays_w:
        kv = _primary_kv(w["props"])
        if kv:
            kvs.add(kv)
    vls = {}
    for kv in sorted(kvs, reverse=True):
        vls[kv] = VoltageLevel(vl_id=f"{site_id}@{kv}", site_id=site_id,
                               nominal_kv=float(kv), kv_source="tag")

    def _vl_u():
        """@u VoltageLevel の遅延生成(未推定の無印成分がある場合のみ)。"""
        if 0 not in vls:
            vls[0] = VoltageLevel(vl_id=f"{site_id}@u", site_id=site_id,
                                  nominal_kv=0.0, kv_source="unknown")
        return vls[0]

    def _vl_for(kv, source):
        """kv の VoltageLevel を返す(無ければ遅延生成)。kv=0 は @u。

        束縛された引込線のタグ電圧で VL を立てる = オーナー規則「電圧は接続先
        から辿って埋める」。線が実際にこの変電所へ束縛された事実が根拠なので
        kv_source に由来(line-tag 等)を刻む。
        """
        if not kv:
            return _vl_u()
        if kv not in vls:
            vls[kv] = VoltageLevel(vl_id=f"{site_id}@{kv}", site_id=site_id,
                                   nominal_kv=float(kv), kv_source=source)
        return vls[kv]

    # 隣接電圧証拠: bay/本線の頂点 → (kv, kind)
    adj_kv = defaultdict(set)
    for w in bays_w + mains_w:
        kv = _primary_kv(w["props"])
        if not kv:
            continue
        for c in w["coords"]:
            adj_kv[_vk(c)].add((kv, w["kind"]))

    # --- BusbarSection: 電圧クラス別に頂点共有成分化 ---
    # 無印(@u)成分は隣接 bay/本線の電圧から導出を試みる(オーナー規則:
    # 「電圧は接続先から辿って埋める=推測でなく接続」)。支配クラス(2/3以上)
    # があれば該当 VL に所属させ kv_inferred/kv_evidence に証拠を刻む。
    structure = SubstationStructure(site=site, voltage_levels=[])
    bb_of_vertex = {}
    by_kv = defaultdict(list)
    for w in busbars_w:
        by_kv[_primary_kv(w["props"])].append(w)
    bb_seq = defaultdict(int)
    for kv in sorted(by_kv, reverse=True):
        for comp in _components(by_kv[kv], _vk):
            inferred = evidence = None
            vkv = kv
            if kv == 0:
                seen = defaultdict(int)
                for w in comp:
                    for c in w["coords"]:
                        for akv, kind in adj_kv.get(_vk(c), ()):
                            seen[(akv, kind)] += 1
                total = sum(seen.values())
                if total:
                    evidence = ",".join(f"{kind}:{akv}x{n}" for (akv, kind), n
                                        in sorted(seen.items(), key=lambda x: -x[1]))
                    best_kv = max({a for a, _ in seen},
                                  key=lambda a: sum(n for (ak, _), n
                                                    in seen.items() if ak == a))
                    share = sum(n for (ak, _), n in seen.items()
                                if ak == best_kv) / total
                    if share >= 2 / 3:
                        inferred, vkv = float(best_kv), best_kv
            vl = vls.get(vkv) if vkv else None
            if vl is None:
                vl = _vl_u()
            bb_seq[vl.vl_id] += 1
            bb = BusbarSection(busbar_id=f"{vl.vl_id}/bb{bb_seq[vl.vl_id]}",
                               vl_id=vl.vl_id,
                               osm_way_keys=[w["key"] for w in comp],
                               kv_inferred=inferred, kv_evidence=evidence)
            structure.busbars.append(bb)
            for w in comp:
                for c in w["coords"]:
                    bb_of_vertex[_vk(c)] = bb.busbar_id

    # --- Bay: 電圧クラス別成分化 + 触れる母線を記録 ---
    bay_of_vertex = {}
    by_kv_bay = defaultdict(list)
    for w in bays_w:
        by_kv_bay[_primary_kv(w["props"])].append(w)
    for kv in sorted(by_kv_bay, reverse=True):
        vl = _vl_for(kv, "tag")
        for i, comp in enumerate(_components(by_kv_bay[kv], _vk), 1):
            touched = sorted({bb_of_vertex[_vk(c)] for w in comp
                              for c in w["coords"] if _vk(c) in bb_of_vertex})
            bay = Bay(bay_id=f"{vl.vl_id}/bay{i}", vl_id=vl.vl_id,
                      osm_way_keys=[w["key"] for w in comp], busbar_ids=touched)
            structure.bays.append(bay)
            for w in comp:
                for c in w["coords"]:
                    bay_of_vertex.setdefault(_vk(c), bay.bay_id)

    # --- Terminal: 本線端点の束縛(証拠の強い順) ---
    tno = 0
    for w in sorted(mains_w, key=lambda w: w["key"]):
        p = w["props"]
        kv = _primary_kv(p)
        par, par_src = _parse_circuits(p)
        for endc in (w["coords"][0], w["coords"][-1]):
            key = _vk(endc)
            pt = Point(endc[0], endc[1])
            if key in bay_of_vertex:
                attach_kind, attach_id = "bay", bay_of_vertex[key]
                binding, conf = "vertex-shared", 1.0
            elif key in bb_of_vertex:
                attach_kind, attach_id = "busbar", bb_of_vertex[key]
                binding, conf = "vertex-shared", 1.0
            elif poly.covers(pt):
                vl = _vl_for(kv, "line-tag")
                attach_kind, attach_id = "voltage_level", vl.vl_id
                binding, conf = "polygon", 0.9
            elif poly.distance(pt) <= _LEADIN_DEG:
                vl = _vl_for(kv, "line-tag")
                attach_kind, attach_id = "voltage_level", vl.vl_id
                binding, conf = "leadin", 0.7
            else:
                continue
            tno += 1
            vl_id = (attach_id.split("/")[0] if attach_kind != "voltage_level"
                     else attach_id)
            structure.terminals.append(Terminal(
                terminal_id=f"{site_id}/t{tno}", site_id=site_id, vl_id=vl_id,
                attach_kind=attach_kind, attach_id=attach_id,
                line_key=w["key"], line_name=p.get("name"),
                circuit_ref=p.get("ref"), par=par,
                par_source=par_src, binding=binding, confidence=conf))

    # --- TransformerSpec: 既知電圧クラスのラダー隣接対(structural) ---
    ladder = sorted((kv for kv in vls if kv > 0), reverse=True)
    for i, (hv, lv) in enumerate(zip(ladder, ladder[1:]), 1):
        structure.transformers.append(TransformerSpec(
            trafo_id=f"{site_id}/tr{i}", site_id=site_id,
            hv_vl_id=vls[hv].vl_id, lv_vl_id=vls[lv].vl_id))

    # VoltageLevel の確定は全段階の後(bay/terminal が @u を遅延生成しうるため。
    # busbar 直後に確定すると terminals の vl_id が dangling になる)。
    structure.voltage_levels = [vls[k] for k in sorted(vls, reverse=True)]
    return structure, ways, poly


# ---------------------------------------------------------------- 検証図


def render_figure(structure, ways, poly, out_png):
    """左=構内幾何(成分色分け) / 右=node-breaker 構造図 の検証ペア図。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _font()

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(20, 11))
    _VC = {500: "#d62728", 275: "#ff7f0e", 220: "#e377c2", 187: "#bcbd22",
           154: "#9467bd", 110: "#1f77b4", 77: "#2ca02c", 66: "#17becf",
           0: "#999999"}

    # --- 左: 構内幾何 ---
    if poly.geom_type == "MultiPolygon":
        rings = [list(g.exterior.coords) for g in poly.geoms]
    elif poly.geom_type == "Polygon":
        rings = [list(poly.exterior.coords)]
    else:                       # Point 変電所は敷地輪郭なし=マーカーのみ
        rings = []
        ax1.plot(poly.centroid.x, poly.centroid.y, "*", color="#4444aa",
                 ms=14, zorder=5)
    for r in rings:
        ax1.plot([c[0] for c in r], [c[1] for c in r], color="#4444aa",
                 lw=1.2, alpha=0.8, zorder=2)
    bykey = {w["key"]: w for w in ways}
    for bb in structure.busbars:
        kv = int(next(vl.nominal_kv for vl in structure.voltage_levels
                      if vl.vl_id == bb.vl_id))
        for k in bb.osm_way_keys:
            cs = bykey[k]["coords"]
            ax1.plot([c[0] for c in cs], [c[1] for c in cs],
                     color=_VC.get(kv, "#999"), lw=3.5, zorder=4)
    for bay in structure.bays:
        kv = int(next(vl.nominal_kv for vl in structure.voltage_levels
                      if vl.vl_id == bay.vl_id))
        for k in bay.osm_way_keys:
            cs = bykey[k]["coords"]
            ax1.plot([c[0] for c in cs], [c[1] for c in cs],
                     color=_VC.get(kv, "#999"), lw=1.2, ls="--", zorder=3)
    seen_lines = set()
    for t in structure.terminals:
        if t.line_key in bykey and t.line_key not in seen_lines:
            seen_lines.add(t.line_key)
            cs = bykey[t.line_key]["coords"]
            ax1.plot([c[0] for c in cs], [c[1] for c in cs], color="#333",
                     lw=0.9, alpha=0.6, zorder=2)
    mk = {"vertex-shared": ("o", "#d62728"), "polygon": ("s", "#1f77b4"),
          "leadin": ("^", "#ff7f0e")}
    for t in structure.terminals:
        if t.line_key not in bykey:
            continue
        cs = bykey[t.line_key]["coords"]
        for endc in (cs[0], cs[-1]):
            m, col = mk[t.binding]
            ax1.plot(endc[0], endc[1], m, color=col, ms=5, zorder=6)
    x0, y0, x1, y1 = poly.bounds
    ax1.set_xlim(x0 - 0.002, x1 + 0.002)
    ax1.set_ylim(y0 - 0.002, y1 + 0.002)
    ax1.set_title(f"{structure.site.name} 構内幾何(太=母線/破線=ベイ/●=vertex ■=polygon ▲=leadin)",
                  fontsize=11)
    ax1.set_aspect("equal")

    # --- 右: node-breaker 構造図 ---
    lv_order = sorted(structure.voltage_levels, key=lambda v: -v.nominal_kv)
    ypos = {vl.vl_id: -i * 3.0 for i, vl in enumerate(lv_order)}
    for vl in lv_order:
        y = ypos[vl.vl_id]
        bbs = [b for b in structure.busbars if b.vl_id == vl.vl_id]
        kv = int(vl.nominal_kv)
        col = _VC.get(kv, "#999")
        label = f"{kv}kV" if kv else "無印(@u)"
        ax2.text(-0.5, y, f"{label} 母線×{len(bbs)}", ha="right", va="center",
                 fontsize=12, color=col, fontweight="bold")
        n = max(len(bbs), 1)
        for i, bb in enumerate(bbs):
            xa, xb = 10.0 * i / n, 10.0 * (i + 0.92) / n
            ax2.plot([xa, xb], [y, y], color=col, lw=4, zorder=3)
            if n <= 8:
                nb = len([b for b in structure.bays
                          if bb.busbar_id in b.busbar_ids])
                tag = f"bb{i+1}(way{len(bb.osm_way_keys)}/bay{nb})"
                if bb.kv_inferred:
                    tag += f" 推定{int(bb.kv_inferred)}kV"
                ax2.text((xa + xb) / 2, y + 0.25, tag,
                         ha="center", fontsize=7, color=col)
        bays = [b for b in structure.bays if b.vl_id == vl.vl_id]
        if bays:
            ax2.text(10.6, y, f"ベイ成分×{len(bays)}", fontsize=9,
                     color=col, va="center")
        terms = [t for t in structure.terminals if t.vl_id == vl.vl_id]
        named = sorted({(t.line_name or "?") for t in terms})
        for j, nm in enumerate(named[:12]):
            ts = [t for t in terms if (t.line_name or "?") == nm]
            bind = ts[0].binding
            parmax = max(t.par for t in ts)
            ax2.text(0.2 + (j % 3) * 3.4, y - 0.55 - (j // 3) * 0.42,
                     f"{nm}[{len(ts)}端子/par{parmax}/{bind}]",
                     fontsize=7, color="#333")
    for tr in structure.transformers:
        ya, yb = ypos[tr.hv_vl_id], ypos[tr.lv_vl_id]
        ax2.plot([10.9, 10.9], [ya, yb], color="#555", lw=1.5, zorder=2)
        ym = (ya + yb) / 2
        ax2.add_patch(plt.Circle((10.9, ym + 0.12), 0.11, fill=False,
                                 color="#555", lw=1.5))
        ax2.add_patch(plt.Circle((10.9, ym - 0.12), 0.11, fill=False,
                                 color="#555", lw=1.5))
        ax2.text(11.15, ym, tr.trafo_id.split("/")[-1] + "(structural)",
                 fontsize=8, color="#555", va="center")
    if not ypos:                # 無タグ・孤立(VL ゼロ)でも空図で成立させる
        ax2.text(5.0, -1.5, "電圧階級なし(voltage 無タグ・構内線/引込なし)",
                 ha="center", fontsize=11, color="#888")
    ax2.set_xlim(-3.2, 13.5)
    ax2.set_ylim(min(ypos.values(), default=-3.0) - 2.5, 1.5)
    ax2.axis("off")
    s = structure.summary()
    ax2.set_title(
        f"node-breaker 構造: VL{len(structure.voltage_levels)} 母線{s['n_busbars']} "
        f"ベイ{s['n_bays']} 端子{s['n_terminals']} 変圧器{s['n_transformers']}(structural)",
        fontsize=11)
    fig.suptitle(f"{structure.site.name} 内部構造 実証抽出 (OSM=正・全端子に根拠付き)",
                 fontsize=13)
    fig.tight_layout()
    fig.savefig(out_png, dpi=110)
    plt.close(fig)
    return out_png


def main():
    ap = argparse.ArgumentParser(description="変電所 node-breaker 構造の実証抽出")
    ap.add_argument("--region", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out", default="data/structures")
    ap.add_argument("--fig", default="/tmp")
    args = ap.parse_args()

    structure, ways, poly = build_structure(args.region, args.name,
                                            args.data_dir)
    os.makedirs(args.out, exist_ok=True)
    slug = structure.site.site_id
    out_json = os.path.join(args.out, f"{slug}.json")
    with open(out_json, "w") as f:
        json.dump(asdict(structure), f, ensure_ascii=False, indent=1)
    out_png = os.path.join(args.fig, f"structure_{args.region}_{args.name}_nb.png")
    render_figure(structure, ways, poly, out_png)

    print("構造JSON:", out_json)
    print("検証図  :", out_png)
    print(json.dumps(structure.summary(), ensure_ascii=False, indent=1))
    bind_counts = defaultdict(int)
    for t in structure.terminals:
        bind_counts[t.binding] += 1
    print("Terminal binding 内訳:", dict(bind_counts))


if __name__ == "__main__":
    main()
