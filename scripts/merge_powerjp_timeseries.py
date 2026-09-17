#!/usr/bin/env python3
"""24時刻UC潮流(flows_ts_*.json)を flow_map の flows_*.geojson へ結合する.

uc_to_pf_built --dump-line-flows の出力(全line行・in_serviceフラグつき)を、
export_flow_map_data の geojson(in_service線のみ・同一build順)へ
名前照合つきで p24/ld24 として埋め込む。照合不一致は警告して該当線をスキップ
(黙って混ぜない)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TS = ROOT / "docs/data/powerjp"
FM = ROOT / "docs/data/flow_map"


def main() -> int:
    for isl in ("hokkaido", "east", "west", "okinawa"):
        tsf = TS / f"flows_ts_{isl}.json"
        gjf = FM / f"flows_{isl}.geojson"
        if not tsf.exists() or not gjf.exists():
            print(f"skip {isl}(入力なし)")
            continue
        ts = json.loads(tsf.read_text())
        gj = json.loads(gjf.read_text())
        rows = [(nm, p, ld) for nm, ins, p, ld in
                zip(ts["names"], ts["in_service"], ts["p_mw"], ts["loading"])
                if ins]
        feats = gj["features"]
        if len(rows) != len(feats):
            print(f"! {isl}: 行数不一致 ts={len(rows)} geojson={len(feats)} — "
                  f"名前照合で可能な範囲のみ結合")
        n_ok = n_ng = 0
        for i, f in enumerate(feats):
            if i < len(rows) and rows[i][0] == f["properties"].get("name"):
                p24 = [None if x is None else round(x, 1) for x in rows[i][1]]
                ld24 = [None if x is None else round(x, 1) for x in rows[i][2]]
                f["properties"]["p24"] = p24
                f["properties"]["ld24"] = ld24
                n_ok += 1
            else:
                n_ng += 1
        gjf.write_text(json.dumps(gj, ensure_ascii=False,
                                  separators=(",", ":")))
        print(f"{isl}: 結合{n_ok} / 不一致{n_ng} -> {gjf.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
