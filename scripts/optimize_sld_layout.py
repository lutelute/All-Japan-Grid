"""SLD 配置最適化 — Barycenter反復法による交差最小化.

sld_data.json の buses に sld_rank (int) フィールドを追加する。
sld.js の _getLayout() はこの rank を使って x 位置を決定する。

アルゴリズム:
  1. 各電圧層を経度順に初期化
  2. 隣接層間のBaryCenter (平均隣接位置) sweep を反復
  3. 2-opt SA でローカル改善

Usage:
    python scripts/optimize_sld_layout.py [--iters N] [--verbose]
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

ROOT     = Path(__file__).parent.parent
SLD_DATA = ROOT / "docs/data/powerflow/sld_data.json"

# Voltage tier order (top → bottom in SLD)
TIERS = [500, 275, 154, 110, 77, 66]


# ── Utility ──────────────────────────────────────────────────────────────────

def count_crossings(order_a: list[int], order_b: list[int],
                    edges_ab: list[tuple[int, int]]) -> int:
    """Count edge crossings between two adjacent tiers.

    order_a/b: bus_id list in draw order (position = index)
    edges_ab: list of (id_in_a, id_in_b)
    """
    pos_a = {bid: i for i, bid in enumerate(order_a)}
    pos_b = {bid: i for i, bid in enumerate(order_b)}
    edge_pairs = [(pos_a[a], pos_b[b]) for a, b in edges_ab
                  if a in pos_a and b in pos_b]
    edge_pairs.sort()
    return _merge_sort_count(edge_pairs)


def _merge_sort_count(pairs: list[tuple[int, int]]) -> int:
    if len(pairs) <= 1:
        return 0
    mid = len(pairs) // 2
    left, right = pairs[:mid], pairs[mid:]
    cnt = _merge_sort_count(left) + _merge_sort_count(right)
    i = j = k = 0
    while i < len(left) and j < len(right):
        if left[i][1] <= right[j][1]:
            pairs[k] = left[i]; i += 1
        else:
            pairs[k] = right[j]; j += 1
            cnt += len(left) - i
        k += 1
    while i < len(left): pairs[k] = left[i]; i += 1; k += 1
    while j < len(right): pairs[k] = right[j]; j += 1; k += 1
    return cnt


def barycenter_order(fixed_order: list[int], mobile_ids: list[int],
                     edges: list[tuple[int, int]],
                     fixed_is_a: bool) -> list[int]:
    """Reorder mobile_ids to minimize crossings with fixed_order via barycenter."""
    fixed_pos = {bid: i for i, bid in enumerate(fixed_order)}

    # Compute barycenter for each mobile node
    scores: dict[int, float] = {bid: float("inf") for bid in mobile_ids}
    neighbour_sum: dict[int, float] = {bid: 0.0 for bid in mobile_ids}
    neighbour_cnt: dict[int, int]   = {bid: 0    for bid in mobile_ids}

    for a, b in edges:
        mob, fix = (b, a) if fixed_is_a else (a, b)
        if mob in neighbour_cnt and fix in fixed_pos:
            neighbour_sum[mob] += fixed_pos[fix]
            neighbour_cnt[mob] += 1

    for bid in mobile_ids:
        if neighbour_cnt[bid] > 0:
            scores[bid] = neighbour_sum[bid] / neighbour_cnt[bid]

    # Keep relative longitude order for nodes without neighbours
    lon_order = {bid: i for i, bid in enumerate(mobile_ids)}
    return sorted(mobile_ids,
                  key=lambda bid: (scores[bid], lon_order.get(bid, 0)))


def two_opt_sa(order: list[int], fixed_order: list[int],
               edges: list[tuple[int, int]], fixed_is_a: bool,
               max_iter: int = 2000, T0: float = 5.0) -> list[int]:
    """Local SA with swap-adjacent moves to reduce crossings."""
    best = list(order)
    best_cost = count_crossings(
        fixed_order, best, edges) if fixed_is_a else count_crossings(
        best, fixed_order, edges)
    cur = list(best)
    cur_cost = best_cost
    T = T0

    for i in range(max_iter):
        T *= 0.997
        if len(cur) < 2:
            break
        j = random.randrange(len(cur) - 1)
        nxt = list(cur)
        nxt[j], nxt[j + 1] = nxt[j + 1], nxt[j]
        nxt_cost = count_crossings(
            fixed_order, nxt, edges) if fixed_is_a else count_crossings(
            nxt, fixed_order, edges)
        delta = nxt_cost - cur_cost
        if delta < 0 or (T > 0 and random.random() < math.exp(-delta / T)):
            cur, cur_cost = nxt, nxt_cost
            if cur_cost < best_cost:
                best, best_cost = list(cur), cur_cost

    return best


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iters",   type=int, default=30)
    parser.add_argument("--sa",      action="store_true", default=True,
                        help="Run SA 2-opt after barycenter (default: on)")
    parser.add_argument("--no-sa",   dest="sa", action="store_false")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    with open(SLD_DATA) as f:
        data = json.load(f)

    buses    = data["buses"]
    branches = data["branches"]

    # Map bus id → properties
    bus_map: dict[int, dict] = {b["id"]: b for b in buses}

    # Tier membership
    tier_buses: dict[int, list[int]] = {kv: [] for kv in TIERS}
    for b in buses:
        kv = round(b["kv"])
        if kv in tier_buses:
            tier_buses[kv].append(b["id"])

    # Initial order: sort by longitude
    for kv in TIERS:
        tier_buses[kv].sort(key=lambda bid: bus_map[bid]["lon"])

    # Cross-tier edges: (a_id, b_id) where a is in upper tier, b in lower
    def edges_between(kv_upper: int, kv_lower: int) -> list[tuple[int, int]]:
        upper = set(tier_buses[kv_upper])
        lower = set(tier_buses[kv_lower])
        result = []
        for br in branches:
            f, t = br["from"], br["to"]
            if f in upper and t in lower:
                result.append((f, t))
            elif t in upper and f in lower:
                result.append((t, f))
        return result

    # Precompute edges for each adjacent tier pair
    adjacent_edges: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for i in range(len(TIERS) - 1):
        pair = (TIERS[i], TIERS[i + 1])
        adjacent_edges[pair] = edges_between(*pair)

    # ── Count initial crossings ──
    def total_crossings(orders: dict[int, list[int]]) -> int:
        total = 0
        for pair, edges in adjacent_edges.items():
            kv_u, kv_l = pair
            total += count_crossings(orders[kv_u], orders[kv_l], edges)
        return total

    orders = {kv: list(tier_buses[kv]) for kv in TIERS}
    initial = total_crossings(orders)
    if args.verbose:
        print(f"Initial crossings: {initial}")

    # ── Barycenter sweep ──
    for iteration in range(args.iters):
        changed = False

        # Top-down: fix upper, reorder lower
        for i in range(len(TIERS) - 1):
            kv_u, kv_l = TIERS[i], TIERS[i + 1]
            edges = adjacent_edges[(kv_u, kv_l)]
            if not edges:
                continue
            new_order = barycenter_order(
                orders[kv_u], orders[kv_l], edges, fixed_is_a=True)
            if new_order != orders[kv_l]:
                orders[kv_l] = new_order
                changed = True

        # Bottom-up: fix lower, reorder upper
        for i in range(len(TIERS) - 2, -1, -1):
            kv_u, kv_l = TIERS[i], TIERS[i + 1]
            edges = adjacent_edges[(kv_u, kv_l)]
            if not edges:
                continue
            new_order = barycenter_order(
                orders[kv_l], orders[kv_u], edges, fixed_is_a=False)
            if new_order != orders[kv_u]:
                orders[kv_u] = new_order
                changed = True

        if args.verbose and (iteration + 1) % 5 == 0:
            print(f"  iter {iteration+1}: crossings = {total_crossings(orders)}")

        if not changed:
            if args.verbose:
                print(f"  Converged at iter {iteration+1}")
            break

    after_bc = total_crossings(orders)

    # ── SA 2-opt refinement ──
    if args.sa:
        for i in range(len(TIERS) - 1):
            kv_u, kv_l = TIERS[i], TIERS[i + 1]
            edges = adjacent_edges[(kv_u, kv_l)]
            if not edges or len(orders[kv_l]) < 3:
                continue
            orders[kv_l] = two_opt_sa(
                orders[kv_l], orders[kv_u], edges, fixed_is_a=True,
                max_iter=min(3000, len(orders[kv_l]) * 20))

        after_sa = total_crossings(orders)
        if args.verbose:
            print(f"SA improvement: {after_bc} → {after_sa}")
    else:
        after_sa = after_bc

    print(f"Crossings: {initial} → {after_bc} (barycenter) → {after_sa} (SA)")
    print(f"Reduction: {(1 - after_sa / max(initial, 1)) * 100:.1f}%")

    # ── Write sld_rank back ──
    rank_map: dict[int, int] = {}
    for kv in TIERS:
        for rank, bid in enumerate(orders[kv]):
            rank_map[bid] = rank

    for b in buses:
        b["sld_rank"] = rank_map.get(b["id"], 0)

    with open(SLD_DATA, "w") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    print(f"Updated sld_rank in {SLD_DATA}")


if __name__ == "__main__":
    main()
