#!/usr/bin/env python3
"""SubSLD の Pages 機能化 — 全所コンパクトJSONの書き出し(オーナー指示 2026-08-27).

PNGギャラリー(5GB)は Pages に載らないため、構造DB+方向推定を1個の compact JSON
(目標 ≤8MB)に落とし、ブラウザ側(docs/subsld.html)で SLDPane を SVG 描画・
GeoPane は地理院タイルをその場合成する。データはD層(再生成可能・regen組込)。

出力: docs/data/subsld_pages.json
  sites[]: {i:site_id, n:name, r:region, ty:type, la, lo,
            pg:[[lat,lon]..]  簡略化した敷地リング(≤24点・無ければ省略),
            vl:[{k:kV, b:母線セクション数, thru:0/1,
                 g:[[線名, par, dir(0=in,1=out,2=⊥), lead(0/1), sec], ...]}],
            tr:[[hv_kV, lv_kV, n_parallel], ...]}

方向推定は render_figure と同じ規則(connections全regionマージ+name-evidence)。
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from scripts.build_substation_structure import _geom_key  # noqa: E402
from src.regions import REGIONS                            # noqa: E402


def norm(s):
    return unicodedata.normalize("NFKC", str(s or "")).replace(" ", "")


def main() -> int:
    # 方向推定索引(全region)
    conns, kvmax, namekv = defaultdict(list), {}, {}
    for r in REGIONS:
        d = json.load(open(f"data/structures/{r}.json"))
        for c in d.get("connections", []):
            conns[c["line_key"]].append(c)
        for st in d["structures"]:
            kvs = [v["nominal_kv"] for v in st.get("voltage_levels", [])
                   if v.get("nominal_kv")]
            if not kvs:
                continue
            for i in [st["site"]["site_id"]] + list(
                    st["site"].get("aliases") or []):
                kvmax[i] = max(kvmax.get(i, 0), max(kvs))
            nm = norm(st["site"].get("name"))
            if nm:
                namekv[nm] = max(namekv.get(nm, 0), max(kvs))

    # 敷地リング(簡略化): substations geojson の feature を site_id で対応付け
    rings = {}
    try:
        from shapely.geometry import shape
        for r in REGIONS:
            subs = json.load(open(f"data/{r}_substations.geojson"))
            for ft in subs["features"]:
                try:
                    poly = shape(ft["geometry"])
                    nm = (ft.get("properties") or {}).get("name") or ""
                    sid = (f"{r}_site_"
                           f"{_geom_key([[poly.centroid.x, poly.centroid.y]], nm)[2:]}")
                    if poly.geom_type == "Point":
                        continue
                    g = poly.simplify(0.00012)
                    if g.geom_type == "MultiPolygon":
                        g = max(g.geoms, key=lambda p: p.area)
                    ring = [[round(y, 5), round(x, 5)]
                            for x, y in g.exterior.coords][:24]
                    rings[sid] = ring
                except Exception:   # noqa: BLE001
                    continue
    except Exception as e:   # noqa: BLE001
        print(f"(敷地リング省略: {e})")

    sites, seen = [], set()
    for r in REGIONS:
        d = json.load(open(f"data/structures/{r}.json"))
        for st in d["structures"]:
            site = st["site"]
            gkey = site["site_id"].split("site_")[-1]
            if gkey in seen:        # 跨region重複はaliasesで統合
                continue
            seen.add(gkey)
            vls = {v["vl_id"]: v.get("nominal_kv") or 0
                   for v in st.get("voltage_levels", [])}
            top = max(vls.values()) if vls else 0
            bb_of_bay = {}
            bb_idx = defaultdict(dict)   # vl_id -> busbar_id -> section idx
            for b in st.get("busbars", []):
                bb_idx[b["vl_id"]].setdefault(
                    b["busbar_id"], len(bb_idx[b["vl_id"]]))
            for b in st.get("bays", []):
                bb_of_bay[b["bay_id"]] = (b["busbar_ids"][0]
                                          if b.get("busbar_ids") else None)
            _my = gkey
            mynm = norm(site.get("name"))
            groups = {}
            for t in st.get("terminals", []):
                key = (t["vl_id"], t.get("line_name") or t.get("line_key")
                       or "?")
                g = groups.setdefault(key, {"par": 1, "lead": True,
                                            "keys": set(), "bb": None})
                g["par"] = max(g["par"], t.get("par") or 1)
                if t.get("binding") != "leadin":
                    g["lead"] = False
                if t.get("line_key"):
                    g["keys"].add(t["line_key"])
                bb = (t["attach_id"] if t.get("attach_kind") == "busbar"
                      else bb_of_bay.get(t.get("attach_id"))
                      if t.get("attach_kind") == "bay" else None)
                if bb is not None and g["bb"] is None:
                    g["bb"] = bb_idx[t["vl_id"]].get(bb)
            vl_out = defaultdict(list)
            for (vl_id, nm), g in sorted(groups.items(),
                                         key=lambda kv_: str(kv_[0])):
                far = []
                for k in g["keys"]:
                    for c in conns.get(k, []):
                        for fs in (c["from_site"], c["to_site"]):
                            if fs.split("site_")[-1] == _my:
                                continue
                            if fs in kvmax:
                                far.append(kvmax[fs])
                if not far:
                    base = norm(nm)
                    base = base[:-1] if base.endswith("線") else base
                    for part in re.split(r"[~/・]", base):
                        part = part.strip()
                        part = part[:-1] if part.endswith("線") else part
                        part = part.replace("変電所", "").replace("開閉所", "")
                        if not part or part in mynm:
                            continue
                        for suf in ("変電所", "開閉所", ""):
                            if namekv.get(part + suf):
                                far.append(namekv[part + suf])
                                break
                kv = vls.get(vl_id, 0)
                if not far:
                    dr = 2
                elif max(far) > kv + 1e-6 or abs(kv - top) < 1e-6:
                    dr = 0
                else:
                    dr = 1
                label = nm if len(str(nm)) <= 22 else str(nm)[:21] + "…"
                vl_out[vl_id].append([label, min(g["par"], 8), dr,
                                      1 if g["lead"] else 0,
                                      g["bb"] if g["bb"] is not None else -1])
            tr_vls = set()
            trs = []
            for t in st.get("transformers", []):
                hv, lv = vls.get(t["hv_vl_id"], 0), vls.get(t["lv_vl_id"], 0)
                trs.append([round(hv), round(lv), t.get("n_parallel") or 1])
                tr_vls |= {t["hv_vl_id"], t["lv_vl_id"]}
            rec = {"i": site["site_id"], "n": site.get("name") or "",
                   "r": r, "la": site["lat"], "lo": site["lon"],
                   "kv": sorted({round(v) for v in vls.values() if v},
                                reverse=True),
                   "vl": [{"k": round(vls[vid]),
                           "b": max(len(bb_idx[vid]), 1),
                           "thru": 0 if vid in tr_vls else 1,
                           "g": gs}
                          for vid, gs in sorted(vl_out.items(),
                                                key=lambda x: -vls.get(x[0], 0))],
                   "tr": trs}
            if site.get("substation_type"):
                rec["ty"] = site["substation_type"]
            if site["site_id"] in rings:
                rec["pg"] = rings[site["site_id"]]
            sites.append(rec)

    out = {"note": ("SubSLD Pages データ(D層・OSM+構造DBから再生成可能)。"
                    "dir: 0=in 1=out 2=不明(推定・凡例明記)。"
                    "生成: scripts/export_subsld_pages.py"),
           "n_sites": len(sites), "sites": sites}
    dst = os.path.join("docs", "data", "subsld_pages.json")
    json.dump(out, open(dst, "w"), ensure_ascii=False,
              separators=(",", ":"))
    mb = os.path.getsize(dst) / 1e6
    print(f"-> {dst}  {len(sites)}所  {mb:.1f}MB  敷地リング{len(rings)}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
