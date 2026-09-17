#!/usr/bin/env python3
"""SubSLD法の全所展開 — 実証ペア図PNGの地域一括生成(オーナー指示 2026-08-26).

手法: docs/SUBSLD_METHOD.md。1所の描画は build_substation_structure.render_figure
(単一の正)をそのまま使い、本スクリプトは走査・共有索引・再開・索引化だけを担う。

出力(**非追跡** — 構造DBの地域ファイルと同じ方針):
  data/subsld/{region}/{site_id}.png      実証ペア図
  data/subsld/{region}/index.json         地域索引(name/kv/png/エラー)
  data/subsld/index.html                  全国ギャラリー(--gallery で生成)

再開可能: 既存PNGはスキップ(--force で再描画)。
衛星タイルは data/cache/gsi_tiles 共有キャッシュ+礼儀スロットル。
SUBSLD_NO_SAT=1 で白背景モード(オフライン/高速検証用)。

usage:
  PYTHONPATH=. .venv/bin/python scripts/build_subsld_batch.py --region okinawa
  PYTHONPATH=. .venv/bin/python scripts/build_subsld_batch.py --region tokyo --limit 20
  PYTHONPATH=. .venv/bin/python scripts/build_subsld_batch.py --gallery   # 索引から全国HTML
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)   # render系は相対パス(data/...)前提

from scripts.build_substation_structure import (   # noqa: E402
    extract_structure,
    load,
    prepare_ways,
    render_figure,
)
from src.regions import REGIONS                    # noqa: E402

OUT_DIR = os.path.join("data", "subsld")


def load_indexes():
    """方向推定(全region connections+kvmax)と銘板(出典付きtrafo)の共有索引."""
    conns_by_key, site_kvmax, name_kvmax, trafo_by_site = {}, {}, {}, {}
    for r in REGIONS:
        p = os.path.join("data", "structures", f"{r}.json")
        if not os.path.exists(p):
            continue
        reg = json.load(open(p))
        for c in reg.get("connections", []):
            conns_by_key.setdefault(c["line_key"], []).append(c)
        for st in reg.get("structures", []):
            kvs = [v["nominal_kv"] for v in st.get("voltage_levels", [])
                   if v.get("nominal_kv")]
            sid = st["site"]["site_id"]
            if kvs:
                for i in [sid] + list(st["site"].get("aliases") or []):
                    site_kvmax[i] = max(site_kvmax.get(i, 0), max(kvs))
                snm = (st["site"].get("name") or "").replace(" ", "")
                if snm:
                    name_kvmax[snm] = max(name_kvmax.get(snm, 0), max(kvs))
            trs = {t["trafo_id"]: t for t in st.get("transformers", [])
                   if any(t.get(f) is not None
                          for f in ("sn_mva", "tap_min", "tap_max"))}
            if trs:
                trafo_by_site[sid] = trs
    return conns_by_key, site_kvmax, name_kvmax, trafo_by_site


def run_region(region, limit=None, force=False):
    conns, kvmax, nkvmax, trafos = load_indexes()
    subs, lines = load(region)
    pways = prepare_ways(lines)
    out_dir = os.path.join(OUT_DIR, region)
    os.makedirs(out_dir, exist_ok=True)
    idx_path = os.path.join(out_dir, "index.json")
    index = {"region": region, "sites": [], "errors": []}
    seen = set()
    feats = subs["features"]
    t0 = time.time()
    done = skipped = 0
    for fi, ft in enumerate(feats):
        if limit and (done + skipped) >= limit:
            break
        try:
            res = extract_structure(region, ft, pways)
            structure, ways, poly = res
            sid = structure.site.site_id
            if sid in seen:            # 同名同座標の重複feature(OSM品質)
                continue
            seen.add(sid)
            png = os.path.join(out_dir, f"{sid}.png")
            rec = {"site_id": sid, "name": structure.site.name,
                   "kv": sorted({round(v.nominal_kv)
                                 for v in structure.voltage_levels
                                 if v.nominal_kv}, reverse=True),
                   "n_lines": len({t.line_key for t in structure.terminals
                                   if t.line_key}),
                   "n_trafo": len(structure.transformers),
                   "png": os.path.basename(png)}
            if os.path.exists(png) and not force:
                skipped += 1
                index["sites"].append(rec)
                continue
            # 銘板(出典付き)の引き継ぎ
            for tr in structure.transformers:
                r_ = trafos.get(sid, {}).get(tr.trafo_id)
                if r_:
                    for f_ in ("sn_mva", "tap_min", "tap_max", "tap_neutral"):
                        if r_.get(f_) is not None:
                            setattr(tr, f_, r_[f_])
            render_figure(structure, ways, poly, png, conns, kvmax, nkvmax)
            index["sites"].append(rec)
            done += 1
            if done % 25 == 0:
                el = time.time() - t0
                print(f"[{region}] {done}描画+{skipped}skip / {len(feats)} "
                      f"({el:.0f}s, {el/max(done,1):.1f}s/所)", flush=True)
        except Exception as e:   # noqa: BLE001 — 1所の失敗で止めない
            index["errors"].append({
                "i": fi, "name": (ft.get("properties") or {}).get("name"),
                "err": f"{type(e).__name__}: {e}"})
            if len(index["errors"]) <= 3:
                traceback.print_exc()
        if (done + skipped) % 100 == 0:
            json.dump(index, open(idx_path, "w"), ensure_ascii=False)
    json.dump(index, open(idx_path, "w"), ensure_ascii=False)
    print(f"[{region}] 完了: 描画{done} skip{skipped} "
          f"エラー{len(index['errors'])} / {time.time()-t0:.0f}s -> {idx_path}",
          flush=True)


def build_gallery():
    """地域index.jsonを束ねて全国ギャラリーHTML(非追跡)を生成."""
    rows = []
    total = 0
    for r in REGIONS:
        p = os.path.join(OUT_DIR, r, "index.json")
        if not os.path.exists(p):
            continue
        idx = json.load(open(p))
        sites = sorted(idx["sites"], key=lambda s: (-max(s["kv"] or [0]),
                                                    -s["n_lines"]))
        total += len(sites)
        cards = "".join(
            f'<a class="c" href="{r}/{s["png"]}" data-name="{s["name"] or s["site_id"]}">'
            f'<img loading="lazy" src="{r}/{s["png"]}">'
            f'<div>{s["name"] or s["site_id"]}<span>'
            f'{"/".join(str(k) for k in s["kv"])}kV・{s["n_lines"]}線・'
            f'Tr{s["n_trafo"]}</span></div></a>'
            for s in sites)
        rows.append(f'<h2 id="{r}">{r} ({len(sites)}所)</h2>'
                    f'<div class="g">{cards}</div>')
    nav = " | ".join(f'<a href="#{r}">{r}</a>' for r in REGIONS)
    html = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<title>SubSLD 全国ギャラリー ({total}所)</title><style>
body{{font-family:"Hiragino Sans",sans-serif;margin:0;background:#16161a;color:#eee}}
header{{position:sticky;top:0;background:#16161aee;padding:12px 20px;border-bottom:1px solid #333}}
h1{{font-size:17px;margin:0}} nav{{font-size:12px;margin-top:4px}} nav a{{color:#7ab}}
input{{margin-top:6px;width:280px;background:#222;border:1px solid #444;color:#eee;padding:4px 8px;border-radius:4px}}
h2{{padding:14px 20px 0;font-size:15px}}
.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:10px;padding:10px 20px}}
.c{{background:#222;border-radius:6px;overflow:hidden;color:#eee;text-decoration:none}}
.c img{{width:100%;aspect-ratio:2640/1400;object-fit:cover;object-position:left}}
.c div{{padding:6px 10px;font-size:12px}} .c span{{color:#999;margin-left:6px;font-size:11px}}
</style></head><body>
<header><h1>SubSLD 全国ギャラリー — 実証ペア図 {total}所</h1>
<nav>{nav}</nav>
<input id="q" placeholder="変電所名で絞り込み" oninput="
const q=this.value; document.querySelectorAll('.c').forEach(c=>
c.style.display=(!q||c.dataset.name.includes(q))?'':'none')"></header>
{''.join(rows)}
</body></html>"""
    dst = os.path.join(OUT_DIR, "index.html")
    open(dst, "w").write(html)
    print(f"-> {dst} ({total}所)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--gallery", action="store_true")
    args = ap.parse_args()
    if args.gallery:
        build_gallery()
        return
    if not args.region:
        ap.error("--region か --gallery を指定")
    run_region(args.region, args.limit, args.force)


if __name__ == "__main__":
    main()
