#!/usr/bin/env python3
"""試験: #1 様式5変圧器定数の適用 / #3 アンテナ状末端の集約 — west AC収束への効果.

E0=基準 / E1=変圧器定数 / E3=アンテナ集約(<100kV・deg1を親へ畳む) / E13=両方
各変案で (a)素朴AC(フラットスタートrunpp=配布相当) (b)本体ladder(solve_island)
を計測する。1回のビルドをdeepcopyして変案を作る(公平比較)。
"""
import copy
import json
import re
import sys
import time
import unicodedata
import warnings
from collections import Counter, defaultdict
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid")
sys.path.insert(0, str(ROOT))

import pandapower as pp  # noqa: E402
import src.powerflow.point_demand as pdm  # noqa: E402
from scripts.run_full_powerflow_from_db import (  # noqa: E402
    add_per_component_slacks, allocate_loads, attach_generators,
    balance_by_zone, build_island_net, load_demand_config, solve_island)
from src.powerflow.pref_demand import pref_zone_gwh  # noqa: E402
from src.powerflow.pipeline import add_reactive_compensation  # noqa: E402

ISLAND = sys.argv[1] if len(sys.argv) > 1 else "west"
FREQ = {"west": 60, "east": 50, "hokkaido": 50, "okinawa": 60}[ISLAND]


def norm(s):
    return unicodedata.normalize("NFKC", str(s or "")).replace(" ", "")


# ---- 様式5変圧器の集約: (変電所base名, kv) -> {x_pct平均, base_mva, n台} ----
import csv
groups = defaultdict(list)
for r in csv.DictReader(open(ROOT / "data/external/system_disclosure/normalized/impedance_transformers.csv")):
    if not r.get("Xps_pct"):
        continue
    base = re.sub(r"\d+号変圧器.*$|変圧器.*$", "", norm(r["name"]))
    if not base:
        continue
    groups[(base, round(float(r["voltage_kv"]), 0))].append(
        (float(r["Xps_pct"]), float(r["base_mva"] or 0)))
TRAFO_DB = {}
for (base, kv), items in groups.items():
    xs = [x for x, _ in items]
    mv = [m for _, m in items if m > 0]
    TRAFO_DB[(base, kv)] = {"x_pct": sum(xs) / len(xs),
                            "sn": (sum(mv) / len(mv)) if mv else None,
                            "n": len(items)}
print(f"様式5変圧器: {len(TRAFO_DB)}サイト×電圧 ({sum(v['n'] for v in TRAFO_DB.values())}台)")


def apply_trafo_db(net):
    """hvバス名×hv電圧で照合し vk%/sn/parallel を実測へ。戻り=適用数."""
    n_hit = 0
    hits = []
    for ti in net.trafo.index:
        hb = int(net.trafo.at[ti, "hv_bus"])
        bname = norm(net.bus.at[hb, "name"])
        hv = round(float(net.trafo.at[ti, "vn_hv_kv"]), 0)
        for (base, kv), rec in TRAFO_DB.items():
            if kv == hv and base and base in bname:
                net.trafo.at[ti, "vk_percent"] = rec["x_pct"]
                if rec["sn"]:
                    net.trafo.at[ti, "sn_mva"] = rec["sn"]
                    net.trafo.at[ti, "parallel"] = max(rec["n"], 1)
                n_hit += 1
                hits.append((base, kv, rec["x_pct"]))
                break
    return n_hit, hits


def antenna_prune(net, kv_max=100.0):
    """deg-1の低圧バスを親へ畳む(負荷/発電を移設)。戻り=除去バス数."""
    removed = 0
    for _round in range(50):
        deg = Counter()
        nbr = {}
        for _, r in net.line.iterrows():
            if not r.in_service:
                continue
            a, b = int(r.from_bus), int(r.to_bus)
            deg[a] += 1
            deg[b] += 1
            nbr.setdefault(a, b)
            nbr.setdefault(b, a)
        for _, r in net.trafo.iterrows():
            if not r.in_service:
                continue
            a, b = int(r.hv_bus), int(r.lv_bus)
            deg[a] += 1
            deg[b] += 1
            nbr.setdefault(a, b)
            nbr.setdefault(b, a)
        protected = set(net.ext_grid.bus) | set(net.gen.bus)
        victims = [b for b in net.bus.index
                   if deg.get(int(b), 0) == 1
                   and float(net.bus.at[b, "vn_kv"]) < kv_max
                   and int(b) not in protected]
        if not victims:
            break
        vs = set(int(v) for v in victims)
        # 移設: load/sgen/shunt を隣へ
        for tbl in ("load", "sgen", "shunt"):
            df = getattr(net, tbl)
            for i in df.index:
                b = int(df.at[i, "bus"])
                if b in vs:
                    df.at[i, "bus"] = nbr[b]
        # 枝を落としてバスを消す
        for tbl in ("line",):
            df = net.line
            drop = [i for i in df.index
                    if int(df.at[i, "from_bus"]) in vs or int(df.at[i, "to_bus"]) in vs]
            df.drop(drop, inplace=True)
        drop_t = [i for i in net.trafo.index
                  if int(net.trafo.at[i, "hv_bus"]) in vs or int(net.trafo.at[i, "lv_bus"]) in vs]
        net.trafo.drop(drop_t, inplace=True)
        net.bus.drop(list(vs), inplace=True)
        removed += len(vs)
    return removed


def naive_ac(net):
    """配布相当: フラットスタートrunpp一発。"""
    n = copy.deepcopy(net)
    t0 = time.time()
    try:
        pp.runpp(n, init="flat", calculate_voltage_angles=True,
                 enforce_q_lims=False, numba=False, max_iteration=30)
        vm = n.res_bus.vm_pu
        return {"conv": True, "s": round(time.time() - t0, 1),
                "vm_min": round(float(vm.min()), 3), "vm_max": round(float(vm.max()), 3)}
    except Exception as ex:  # noqa: BLE001
        return {"conv": False, "s": round(time.time() - t0, 1), "err": type(ex).__name__}


def ladder(net):
    n = copy.deepcopy(net)
    t0 = time.time()
    net_dc, dc, net_ac, ac = solve_island(n, max_ac_buses=99999)
    out = {"dc": bool(dc.get("converged")), "ac": bool(ac.get("converged")),
           "s": round(time.time() - t0, 1)}
    if out["ac"]:
        out["vm_min"] = round(float(net_ac.res_bus.vm_pu.min()), 3)
        out["served"] = ac.get("served_frac")
        out["note"] = ac.get("note") or ac.get("pruned") or ""
    return out


# ---- ビルド(1回) ----
print(f"build {ISLAND} ...", flush=True)
built = json.loads((ROOT / "docs/data/built/all.json").read_text())
nodes, edges = built["nodes"], built["edges"]
cfg = load_demand_config()
pref_gwh, _ = pref_zone_gwh(nodes)
demand_pd = pdm.load_point_demand()
net0, bus_of, _ = build_island_net(ISLAND, nodes, edges, FREQ, {})
attach_generators(net0, bus_of, nodes, ISLAND, attach_mode="cap", stats=True)
pinned, _ = pdm.match_buses(net0, demand_pd)
allocate_loads(net0, cfg, pref_gwh=pref_gwh, point_demand=pinned)
add_reactive_compensation(net0, factor=cfg.get("reactive_compensation_factor", 0.6))
add_per_component_slacks(net0)
balance_by_zone(net0, cfg, use_zone_src=True)
print(f"built: {len(net0.bus)}バス {len(net0.trafo)}変圧器", flush=True)

results = {}
for tag in ("E0", "E1", "E3", "E13"):
    net = copy.deepcopy(net0)
    info = {}
    if tag in ("E1", "E13"):
        nh, hits = apply_trafo_db(net)
        info["trafo_applied"] = nh
        if tag == "E1":
            info["sample"] = hits[:6]
    if tag in ("E3", "E13"):
        info["antenna_removed"] = antenna_prune(net)
        info["bus_after"] = len(net.bus)
    print(f"[{tag}] {info}", flush=True)
    r_naive = naive_ac(net)
    print(f"[{tag}] naive: {r_naive}", flush=True)
    r_lad = ladder(net)
    print(f"[{tag}] ladder: {r_lad}", flush=True)
    results[tag] = {"info": info, "naive": r_naive, "ladder": r_lad}

out = Path(__file__).with_suffix(f".{ISLAND}.json")
out.write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str))
print("saved", out)
