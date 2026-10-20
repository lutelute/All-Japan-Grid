"""介入 #48(観測した変圧器の組で変電所内を結ぶ)の前後比較。

    PYTHONPATH=. .venv/bin/python scripts/run_full_powerflow_from_db.py --output-dir OFF
    PYTHONPATH=. .venv/bin/python scripts/run_full_powerflow_from_db.py --observed-trafos --output-dir ON
    python3 docs/reports/station_layers_2026-10-07/observed_trafos_ab.py OFF ON > observed_trafos_ab.json

島の指標(収束・電圧・最大負荷率・損失)と、結び直した変電所ごとの変圧器の潮流を並べる。
帳簿は介入 OFF でも候補として記録される(run_full_powerflow_from_db の observed_trafos)。
"""
import json
import sys

KEYS = ("ac_converged", "dc_converged", "ac_vm_min", "ac_vm_max", "ac_max_loading_pct",
        "dc_max_loading_pct", "ac_total_loss_mw", "n_trafo", "n_trafo_nameplate", "ac_error")


def main(off_dir, on_dir):
    off = json.load(open(f"{off_dir}/summary.json"))["islands"]
    on = json.load(open(f"{on_dir}/summary.json"))["islands"]
    out = {"islands": {}, "sites": []}
    for isl in off:
        out["islands"][isl] = {k: [off[isl].get(k), on[isl].get(k)] for k in KEYS}
        before = {r["site"]: r for r in off[isl].get("observed_trafos") or []}
        for r in on[isl].get("observed_trafos") or []:
            b = before.get(r["site"], {})
            out["sites"].append({"island": isl, "site": r["site"], "kv": r["kv"],
                                 "ladder": b.get("result"), "observed": r.get("result"),
                                 "linked": r["linked"]})
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:3])
