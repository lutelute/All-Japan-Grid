#!/usr/bin/env python3
"""電気機械モード帯の全島推定(G_DB第一歩の検証器・2026-08-17).

機械集約(src/dynamics/machine_agg)+内部ノードSchur縮約の古典モデルで、
各周波数島の動揺モード周波数帯を推定する。フラット運転点近似(帯の推定・
運転点込みは次段)。出力: docs/reports/swing_modes_<date>.json

実行: PYTHONPATH=. python3 scripts/gen_swing_modes.py
前提: dist/ybus/{island}.npz (gen_ybus_numeric出荷・pu×base格納 → /baseで正規化)
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np                     # noqa: E402
import scipy.sparse as sp              # noqa: E402

from scripts.run_full_powerflow_from_db import (  # noqa: E402
    build_island_net, attach_generators)
from src.dynamics.machine_agg import (  # noqa: E402
    aggregate_machines, build_classical_model)

ISLANDS = (("hokkaido", 50), ("east", 50), ("west", 60), ("okinawa", 60))
OUT = ROOT / "docs/reports/swing_modes_2026-08-17.json"


def main() -> int:
    built = json.loads((ROOT / "docs/data/built/all.json").read_text(encoding="utf-8"))
    nodes, edges = built["nodes"], built["edges"]
    res = {}
    for island, freq in ISLANDS:
        z = np.load(ROOT / f"dist/ybus/{island}.npz", allow_pickle=True)
        base = float(z["base_mva"])
        # 注意: npzは pu×base 格納(README表記と相違・×100バグとして記録済み)
        Y = (sp.csr_matrix((z["data"], z["indices"], z["indptr"]),
                           shape=tuple(z["shape"])) / base).tocsc()
        net, bus_of, _ = build_island_net(island, nodes, edges, freq, {})
        attach_generators(net, bus_of, nodes, island)
        pos = {b: i for i, b in enumerate(np.asarray(z["bus_pp"]))}
        agg = aggregate_machines(net)
        agg["sync"] = [dict(s, bus=pos[s["bus"]]) for s in agg["sync"]
                       if s["bus"] in pos]
        freqs, M, K, sync = build_classical_model(Y, agg, base, freq)
        st = agg["stats"]
        band = freqs[(freqs >= 0.2) & (freqs <= 2.5)]
        res[island] = {
            **st,
            "f_min_hz": round(float(freqs.min()), 3) if len(freqs) else None,
            "f_median_hz": round(float(np.median(freqs)), 3) if len(freqs) else None,
            "f_max_hz": round(float(freqs.max()), 3) if len(freqs) else None,
            "n_modes": int(len(freqs)),
            "n_electromech_band": int(len(band)),
        }
        print(f"{island}: 同期集約{st['n_sync_buses']}バス/IBR{st['S_ibr_mva']}MVA "
              f"モード {res[island]['f_min_hz']}〜{res[island]['f_max_hz']}Hz "
              f"(電気機械帯 {len(band)}/{len(freqs)})")
    OUT.write_text(json.dumps({
        "note": "古典モデル(機械集約・容量加重H・xd''並列合成・フラット近似)の"
                "モード周波数帯。inter-area最低モード: west 0.37Hz / east 0.57Hz",
        "typical_params": "IEEJ/教科書帯の型式別典型値(machine_agg.TYPE_PARAMS)",
        "islands": res,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
