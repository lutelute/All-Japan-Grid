#!/usr/bin/env python3
"""全国基幹概観(電圧帯別)を **正典 powerflow_full** から再生成する (idempotent)。

    PYTHONPATH=. python scripts/gen_national_overview_from_full.py

背景 (なぜ作るか)
-----------------
潮流タブの「全国基幹」= `runPFNational()` は psdat 縮約 **2,189 バス**
(docs/data/powerflow/all_ac_buses + routes_*.geojson + backbone_ring)を見せていた。
DB 更新前の旧縮約モデルで、per-region/"all" が正典(17,333 バス全規模 AC)なのに
"national_backbone" だけ旧縮約、という 3 世代同居がオーナー指摘の違和感だった。

本スクリプトは **再 solve せず**(全規模 AC は powerflow_full に既にある)、その既存結果を
集計して全国概観を生成する。`powerflow.js` の `ROUTE_TIERS`(電圧帯別レイヤ)が読む
ファイル名に合わせて **電圧帯ごとに分割出力** するので、tier UI(下位電圧の on-demand
表示)をそのまま温存したまま、データソースだけを旧縮約→正典に差し替えられる。
各 line への kv 付与: 端点 → bus vn_kv 突合(実測 99%)主 + built edge 名 → kv(100%)フォールバック。

入力 (読み取り専用)
-------------------
docs/data/powerflow_full/{region}_ac_buses.geojson : {name, vn_kv, vm_pu, va_deg}
docs/data/powerflow_full/{region}_ac_lines.geojson : {name, loading_pct, p_mw, tie}
docs/data/built/all.json                           : edge 名 → kv フォールバック表

出力 (上書き) — powerflow.js ROUTE_TIERS の file 名と一致させる
-------------
docs/data/powerflow_full/national_overview_{500,275,154,110,77,66}kv.geojson
    line feature {name, kv, loading_pct, p_mw, tie, region}  (電圧帯別)
docs/data/powerflow_full/national_overview_buses.geojson
    bus  feature {name, vn_kv, vm_pu, region}  (vn_kv>=154 の幹線バス)

捏造防止: kv が付かない線・vm_pu/loading が無いものは null のまま(偽値で埋めない)。
リング構造(backbone_ring)は縮約モデル特有で正典に対応物が無いため出力しない(UI 側で廃止)。
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FULL = os.path.join(ROOT, "docs", "data", "powerflow_full")
BUILT_ALL = os.path.join(ROOT, "docs", "data", "built", "all.json")

COORD_PRECISION = 4
BUS_MIN_KV = 154.0   # busLayer は 154kV 以上の幹線バス(全 17,333 は重いので概観に絞る)

# 電圧帯: (帯ラベル kv, lo<=kv<hi)。powerflow.js ROUTE_TIERS の kv と一致。
# hi=None は上限なし(500kV+)。66 帯は <77 を全部(66kV 概観)。
TIER_BANDS = [
    (500, 500.0, None),
    (275, 275.0, 500.0),
    (154, 154.0, 275.0),
    (110, 110.0, 154.0),
    (77,  77.0, 110.0),
    (66,  0.0,  77.0),
]


def r(x):
    return round(float(x), COORD_PRECISION)


def band_of(kv):
    for label, lo, hi in TIER_BANDS:
        if kv >= lo and (hi is None or kv < hi):
            return label
    return None


def load_builtedge_kv():
    if not os.path.exists(BUILT_ALL):
        return {}
    with open(BUILT_ALL, encoding="utf-8") as f:
        built = json.load(f)
    m = {}
    for e in built.get("edges", []):
        nm = (e.get("name") or "").strip()
        kv = e.get("kv")
        if nm and kv:
            m.setdefault(nm, float(kv))
    return m


def main():
    if not os.path.isdir(FULL):
        print(f"ERROR: {FULL} not found", file=sys.stderr)
        return 1
    edge_kv = load_builtedge_kv()
    print(f"built edge name->kv fallback: {len(edge_kv)} names")

    regions = sorted({
        os.path.basename(f).split("_ac_buses")[0]
        for f in glob.glob(os.path.join(FULL, "*_ac_buses.geojson"))
    })

    out_buses = []
    band_feats = {label: [] for label, _, _ in TIER_BANDS}
    n_total = n_end = n_name = n_nokv = 0

    for reg in regions:
        bf = os.path.join(FULL, f"{reg}_ac_buses.geojson")
        lf = os.path.join(FULL, f"{reg}_ac_lines.geojson")
        if not (os.path.exists(bf) and os.path.exists(lf)):
            continue
        with open(bf, encoding="utf-8") as f:
            buses = json.load(f)["features"]
        bidx = {}
        for b in buses:
            c = (b.get("geometry") or {}).get("coordinates")
            if not c or len(c) < 2:
                continue
            vn = b["properties"].get("vn_kv")
            bidx[(r(c[0]), r(c[1]))] = vn
            if vn is not None and float(vn) >= BUS_MIN_KV:
                p = b["properties"]
                out_buses.append({
                    "type": "Feature",
                    "properties": {"name": p.get("name"), "vn_kv": vn,
                                   "vm_pu": p.get("vm_pu"), "region": reg},
                    "geometry": b["geometry"],
                })
        with open(lf, encoding="utf-8") as f:
            lines = json.load(f)["features"]
        for l in lines:
            n_total += 1
            c = (l.get("geometry") or {}).get("coordinates")
            if not c or len(c) < 2:
                continue
            kv = None
            for e in (c[0], c[-1]):
                k = bidx.get((r(e[0]), r(e[1])))
                if k is not None:
                    kv = max(kv or 0.0, float(k))
            if kv is not None:
                n_end += 1
            else:
                kv = edge_kv.get((l["properties"].get("name") or "").strip())
                if kv is not None:
                    n_name += 1
            if kv is None:
                n_nokv += 1
                continue
            band = band_of(kv)
            if band is None:
                continue
            p = l["properties"]
            band_feats[band].append({
                "type": "Feature",
                "properties": {"name": p.get("name"), "kv": kv,
                               "loading_pct": p.get("loading_pct"), "p_mw": p.get("p_mw"),
                               "tie": p.get("tie", False), "region": reg},
                "geometry": l["geometry"],
            })

    # write per-band line files + buses
    def write(path, feats):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"type": "FeatureCollection", "features": feats},
                      f, ensure_ascii=False, separators=(",", ":"))

    print("\n=== national overview (正典 powerflow_full 由来, 再solveなし) ===")
    print(f"line kv assign: end={n_end} name={n_name} nokv={n_nokv} / total={n_total}")
    for label, _, _ in TIER_BANDS:
        path = os.path.join(FULL, f"national_overview_{label}kv.geojson")
        write(path, band_feats[label])
        print(f"  national_overview_{label}kv.geojson: {len(band_feats[label])} lines")
    buses_path = os.path.join(FULL, "national_overview_buses.geojson")
    write(buses_path, out_buses)
    print(f"  national_overview_buses.geojson: {len(out_buses)} buses (vn_kv>={int(BUS_MIN_KV)})")

    # JSON 妥当性
    ok = True
    paths = [os.path.join(FULL, f"national_overview_{l}kv.geojson") for l, _, _ in TIER_BANDS]
    paths.append(buses_path)
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                assert json.load(f)["type"] == "FeatureCollection"
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"  INVALID {p}: {exc}")
    print(f"  all JSON valid: {ok}")
    if band_feats[500]:
        print("  sample 500kv line:", json.dumps(band_feats[500][0]["properties"], ensure_ascii=False))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
