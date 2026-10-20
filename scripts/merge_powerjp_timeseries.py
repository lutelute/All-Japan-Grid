#!/usr/bin/env python3
"""24時刻UC潮流(flows_ts_*.json)を flow_map の flows_*.geojson へ結合する.

uc_to_pf_built --dump-line-flows の出力を、export_flow_map_data の geojson へ
p24/ld24 として埋め込む。両方に線の鍵(keys / properties.k = 両端座標・電圧・向き)が
あれば鍵で結合する(並び順に頼らない)。鍵の無い古い出力のときだけ、従来どおり
並び順+線名で照合する。照合できない線は空欄にし、件数を出す(黙って混ぜない)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TS = ROOT / "docs/data/powerjp"
FM = ROOT / "docs/data/flow_map"


def _r(xs):
    return [None if x is None else round(x, 1) for x in xs]


def main() -> int:
    for isl in ("hokkaido", "east", "west", "okinawa"):
        tsf = TS / f"flows_ts_{isl}.json"
        gjf = FM / f"flows_{isl}.geojson"
        if not tsf.exists() or not gjf.exists():
            print(f"skip {isl}(入力なし)")
            continue
        ts = json.loads(tsf.read_text())
        gj = json.loads(gjf.read_text())
        feats = gj["features"]
        n_ok = n_ng = 0
        if ts.get("keys") and any(f["properties"].get("k") for f in feats):
            by_key = {k: (p, ld) for k, ins, p, ld in
                      zip(ts["keys"], ts["in_service"], ts["p_mw"], ts["loading"])
                      if ins and k}
            for f in feats:
                hit = by_key.get(f["properties"].get("k"))
                if hit:
                    f["properties"]["p24"], f["properties"]["ld24"] = _r(hit[0]), _r(hit[1])
                    n_ok += 1
                else:
                    f["properties"].pop("p24", None)
                    f["properties"].pop("ld24", None)
                    n_ng += 1
            how = "鍵"
        else:
            rows = [(nm, p, ld) for nm, ins, p, ld in
                    zip(ts["names"], ts["in_service"], ts["p_mw"], ts["loading"]) if ins]
            if len(rows) != len(feats):
                print(f"! {isl}: 行数不一致 ts={len(rows)} geojson={len(feats)} — "
                      f"名前照合で可能な範囲のみ結合")
            for i, f in enumerate(feats):
                if i < len(rows) and rows[i][0] == f["properties"].get("name"):
                    f["properties"]["p24"], f["properties"]["ld24"] = _r(rows[i][1]), _r(rows[i][2])
                    n_ok += 1
                else:
                    n_ng += 1
            how = "並び順+線名(鍵なしの旧出力)"
        gjf.write_text(json.dumps(gj, ensure_ascii=False, separators=(",", ":")))
        print(f"{isl}: {how}で結合 {n_ok} / 対応なし {n_ng} -> {gjf.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
