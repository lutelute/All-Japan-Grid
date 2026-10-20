"""介入 #50: 変電所内の変圧器の容量を、従来の推定(下位側の線路容量)と、組ごとの公表容量の中央値のどちらが
実際(各社の公表一覧の変電所ごとの容量)に近いかを数える。値は非公開なので、比の集計だけを出す。

    PYTHONPATH=. .venv/bin/python docs/reports/station_layers_2026-10-07/pair_capacity_check.py <transformer_registry.csv>
"""
import csv, json, math, statistics, sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.run_full_powerflow_from_db import _nearest_kv, get_line_parameters_safe  # noqa: E402
from scripts.score_transformer_topology import kvc, site_norm  # noqa: E402

reg = sys.argv[1]
actual = defaultdict(float)
for r in csv.DictReader(open(reg, encoding="utf-8")):
    hv, lv = kvc(r.get("hv_kv")), kvc(r.get("lv_kv"))
    try:
        cap = float(str(r.get("capacity_value") or "").replace(",", ""))
    except ValueError:
        continue
    if hv and lv and cap > 0:
        actual[(r["agj_region"], site_norm(r.get("substation_norm") or r["substation_raw"]), hv, lv)] += cap
med = {tuple(int(x) for x in k.split("/")): v["median_mva"] for k, v in
       json.load(open(ROOT / "config/transformer_capacity_by_pair.json"))["pairs"].items()}


def old_rule(lv):            # run_full_powerflow_from_db の従来の推定(50 Hz の線路の定格で代表)
    p = get_line_parameters_safe(_nearest_kv(lv) or lv, 50.0) or {"max_i_ka": 1.0}
    return max(100.0, math.sqrt(3) * lv * p["max_i_ka"])


err = {"old": [], "pairmed": []}
for (region, site, hv, lv), cap in actual.items():
    if (hv, lv) not in med or hv < 100:
        continue
    err["old"].append(abs(math.log2(old_rule(lv) / cap)))
    err["pairmed"].append(abs(math.log2(med[(hv, lv)] / cap)))


def summ(xs):
    xs = sorted(xs)
    return {"n": len(xs), "median_abs_log2": round(statistics.median(xs), 3),
            "within_x2": round(sum(1 for x in xs if x <= 1) / len(xs), 3)}


print(json.dumps({k: summ(v) for k, v in err.items()}, ensure_ascii=False))
