"""Record a real branch-and-bound on a toy UC, for the search-tree animation.

Toy: N units x T hours, binary commitment u only (start-up v and output p are continuous),
so branching on u alone is a complete branch-and-bound. Each node solves the LP relaxation
with HiGHS; nodes are explored best-bound first. Every node event is written in order:
created (with its LP bound), pruned by bound, infeasible, or integral (a full plan). The
optimum is cross-checked against HiGHS solving the same MILP directly.

    python -m scripts.uc_bnb_trace --units 5 --hours 4 --out bnb.json
"""

import argparse
import heapq
import json
import math
from pathlib import Path
import random

import highspy
import numpy as np


def toy(units, hours, seed):
    rng = random.Random(seed)
    gens = []
    for i in range(units):
        cap = rng.choice([100, 150, 200, 250])
        gens.append({"cap": cap, "pmin": 0.5 * cap, "noload": cap * rng.uniform(8, 14),
                     "mc": rng.uniform(10, 30), "su": cap * rng.uniform(20, 40), "mut": 2})
    total = sum(g["cap"] for g in gens)
    demand = [round(total * f, 1) for f in [0.35, 0.6, 0.75, 0.5, 0.65, 0.4][:hours]]
    return gens, demand


def build(gens, demand, integer):
    """Columns: u[g,t], p[g,t], v[g,t]. Returns Highs and the index of u[g,t]."""
    G, T = len(gens), len(demand)
    U = lambda g, t: g * T + t
    P = lambda g, t: G * T + g * T + t
    V = lambda g, t: 2 * G * T + g * T + t
    n = 3 * G * T
    cost, lo, hi = np.zeros(n), np.zeros(n), np.zeros(n)
    for g, d in enumerate(gens):
        for t in range(T):
            cost[U(g, t)], hi[U(g, t)] = d["noload"], 1
            cost[P(g, t)], hi[P(g, t)] = d["mc"], d["cap"]
            cost[V(g, t)], hi[V(g, t)] = d["su"], 1
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("threads", 1)
    h.addVars(n, lo, hi)
    h.changeColsCost(n, np.arange(n, dtype=np.int32), cost)
    row = lambda lb, ub, idx, val: h.addRow(lb, ub, len(idx), np.array(idx, dtype=np.int32), np.array(val, dtype=float))
    for t in range(T):
        row(demand[t], demand[t], [P(g, t) for g in range(G)], [1.0] * G)                       # balance
        row(1.1 * demand[t], math.inf, [U(g, t) for g in range(G)], [d["cap"] for d in gens])  # reserve
    for g, d in enumerate(gens):
        for t in range(T):
            row(-math.inf, 0, [P(g, t), U(g, t)], [1, -d["cap"]])          # p <= cap u
            row(0, math.inf, [P(g, t), U(g, t)], [1, -d["pmin"]])          # p >= pmin u
            prev = [U(g, t - 1)] if t else []
            row(0, math.inf, [V(g, t), U(g, t)] + prev, [1, -1] + ([1] * len(prev)))   # v >= u_t - u_{t-1}
            window = [V(g, s) for s in range(max(0, t - d["mut"] + 1), t + 1)]
            row(-math.inf, 0, window + [U(g, t)], [1] * len(window) + [-1])            # min up time
    if integer:
        idx = np.array([U(g, t) for g in range(G) for t in range(T)], dtype=np.int32)
        h.changeColsIntegrality(len(idx), idx, np.ones(len(idx), dtype=np.uint8))
    return h, U, lo, hi


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--units", type=int, default=5)
    ap.add_argument("--hours", type=int, default=4)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--max-nodes", type=int, default=20000)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    gens, demand = toy(args.units, args.hours, args.seed)
    G, T = len(gens), len(demand)
    h, U, lo, hi = build(gens, demand, integer=False)
    uvars = [(g, t) for g in range(G) for t in range(T)]

    def solve(fix):
        cols = np.array([U(g, t) for (g, t) in uvars], dtype=np.int32)
        l = np.array([fix.get(k, 0.0) for k in uvars], dtype=float)
        u = np.array([fix.get(k, 1.0) for k in uvars], dtype=float)
        h.changeColsBounds(len(cols), cols, l, u)
        h.run()
        if h.getModelStatus() != highspy.HighsModelStatus.kOptimal:
            return None, None
        x = h.getSolution().col_value
        return h.getInfo().objective_function_value, {k: x[U(*k)] for k in uvars}

    events, nodes = [], []
    incumbent, best_plan = math.inf, None
    heap = []

    def create(fix, parent, var, side):
        nonlocal incumbent, best_plan
        nid = len(nodes)
        bound, x = solve(fix)
        node = {"id": nid, "parent": parent, "depth": len(fix), "var": var, "side": side, "bound": bound}
        if bound is None:
            node["status"] = "infeasible"
        elif bound >= incumbent - 1e-6:
            node["status"] = "pruned"
        else:
            frac = [(abs(x[k] - round(x[k])), k) for k in uvars if k not in fix and 1e-6 < x[k] < 1 - 1e-6]
            if not frac:
                node["status"] = "integral"
                incumbent, best_plan = bound, {f"{g},{t}": round(x[(g, t)]) for (g, t) in uvars}
            else:
                node["status"] = "open"
                node["branch"] = max(frac)[1]
                heapq.heappush(heap, (bound, nid, fix))
        nodes.append(node)
        events.append({"e": "create", "id": nid, "status": node["status"], "incumbent": None if incumbent == math.inf else incumbent})
        return node

    create({}, None, None, None)
    while heap and len(nodes) < args.max_nodes:
        bound, nid, fix = heapq.heappop(heap)
        if bound >= incumbent - 1e-6:
            nodes[nid]["status"] = "pruned_late"
            events.append({"e": "prune", "id": nid, "incumbent": incumbent})
            continue
        var = nodes[nid]["branch"]
        nodes[nid]["status"] = "branched"
        events.append({"e": "branch", "id": nid, "lower": min([bound] + [b for b, _, _ in heap])})
        for side in (0, 1):
            create({**fix, var: float(side)}, nid, list(var), side)
    for b, nid, _ in heap:
        nodes[nid]["status"] = "unexplored"

    m, _, _, _ = build(gens, demand, integer=True)
    m.setOptionValue("mip_rel_gap", 0.0)
    m.run()
    check = m.getInfo().objective_function_value
    out = {"schema_version": 1, "kind": "bnb_trace", "toy": {"units": G, "hours": T, "seed": args.seed, "gens": gens, "demand": demand},
           "binaries": G * T, "combinations": 2 ** (G * T), "nodes": nodes, "events": events,
           "optimum": incumbent, "highs_mip_optimum": check, "best_plan": best_plan,
           "complete": not heap}
    args.out.write_text(json.dumps(out, separators=(",", ":")) + "\n")
    print(json.dumps({"binaries": G * T, "nodes": len(nodes), "optimum": incumbent, "highs": check,
                      "match": abs(incumbent - check) < 1e-6 * max(1, abs(check)), "complete": not heap}))


if __name__ == "__main__":
    main()
