"""潮流計算の網の発電機の一覧(名前・付いたバス・座標・元の地物)を書き出す(#163 の佐久の水力と小諸の太陽光、先生の問い 2026-11-09)。

    python3 gens_dump.py <コードの根> <all.json> <east|west> <出力.json>

前 = main の f54ac357 の正典(git show f54ac357:docs/data/built/all.json)、後 = この PR の正典。網を作るコードは
同じ(この PR は潮流のコードを変えていない)。出力は大きいのでコミットしない(saku.py が要るところだけ saku.json にまとめる)。
"""
import json, sys
from pathlib import Path
root, built, island = Path(sys.argv[1]), Path(sys.argv[2]).resolve(), sys.argv[3]
outp = Path(sys.argv[4]).resolve()
sys.path.insert(0, str(root)); sys.path.insert(0, str(root / "scripts" / "sensitivity"))
import n1_screening as ns  # noqa
from src.powerflow.pref_demand import pref_zone_gwh  # noqa
d = json.load(open(built, encoding="utf-8"))
cfg = ns.load_demand_config(); pref_gwh, _ = pref_zone_gwh(d["nodes"])
net = ns.production_net(island, d["nodes"], d["edges"], cfg, pref_gwh, cap_calib=None)
rows = []
for g in net.gen.index:
    b = int(net.gen.at[g, "bus"]); lo, la = ns._bus_lonlat(net, b)
    rows.append({"name": str(net.gen.at[g, "name"]), "p": float(net.gen.at[g, "p_mw"]),
                 "src": str(net.gen.at[g, "src_feature"]) if "src_feature" in net.gen else None,
                 "bus": str(net.bus.at[b, "name"]), "kv": float(net.bus.at[b, "vn_kv"]), "lat": la, "lon": lo,
                 "in_service": bool(net.gen.at[g, "in_service"])})
json.dump({"n_gen": len(rows), "p": sum(r["p"] for r in rows), "gens": rows}, open(outp, "w"), ensure_ascii=False)
print(island, len(rows), round(sum(r["p"] for r in rows), 1))
