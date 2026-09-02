#!/usr/bin/env python3
"""断片解消キャンペーン第三波 — 継ぎ目緩和の OSM way 連鎖回収 + 同一敷地同定の提案(ドライラン専用).

第一波(hunt_fragment_osm_bridges: 1way・接触≤80m)・第二波(hunt_fragment_osm_chains:
複数way・継ぎ目≤60m)で 904→691 成分まで減った本系統外断片(介入#34)の残りに対し、

  (a) 継ぎ目(way端点⇔隣接way)の閾値を 60m → 120 / 200 / 300m へ段階的に緩めて
      **OSM に実在する線形の連鎖だけ**を辿る(直線ジャンプは構造的に発生しない)。
      創作を防ぐゲート: 電圧整合(判明kvが >25% 乖離なら棄却)・迂回係数
      (連鎖の実線長 / 端点直線距離 ≤ DETOUR_MAX: 並走・併架回廊を継ぎ目で乗り換えて
      遠回りする「偶然の連鎖」を棄却)・島跨ぎ双子(同座標に別島の本系統ノードがある
      断片=登録人工物の疑い → 回収でなく再属性へ回す)。
  (b) 同一敷地の同定(断片ノード名の基底 = 本系統ノード名の基底・300m 以内・電圧整合)
      を **承認待ち提案**として YAML に出す(config/isolated_verdict_overrides.yaml と
      同じ approved 制。適用は別介入)。
  (c)〜(e) 残存断片の分類(越境スライス双子 / 真の孤立の推定 / 開示台帳に名前がある候補)。

原則: **本スクリプトは既定で正典(docs/data/built/all.json)を書かない**。`--write` は
実装してあるが、親セッションがゲート(連結性・潮流)を確認してから明示的に実行する。

usage:
  PYTHONPATH=. python3 scripts/hunt_fragment_third_wave.py                 # ドライラン
  PYTHONPATH=. python3 scripts/hunt_fragment_third_wave.py --seam-m 200    # 適用段の指定
  PYTHONPATH=. python3 scripts/hunt_fragment_third_wave.py --seam-m 200 --write   # 正典適用(親のみ)
出力: docs/reports/fragment_third_wave_<date>.{json,md}
      docs/reports/same_site_proposals_<date>.yaml(approved: false の提案)
      --write 時: all.json 追記(recovery="osm_chain3"・バックアップ=all.json.pre_frag3.bak)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.hunt_fragment_osm_bridges import (  # noqa: E402
    ISLAND_OF, clip_path, dist_km, k5, min_dist_to_path, nearest_vertex_idx,
    norm_base)

BUILT = ROOT / "docs/data/built/all.json"
LINES = ROOT / "docs/data/lines_all.geojson"
REPORTS = ROOT / "docs/reports"

TH_NODE = 0.08                        # ノード⇔way 接触 km(第一波/第二波と同じ)
SEAM_STAGES_M = (60, 120, 200, 300)   # 継ぎ目の段階(60m=第二波の再現段)
MAX_WAYS = 6
DETOUR_MAX = 1.5                      # 実線長 / 直線距離
DETOUR_MIN_STRAIGHT_KM = 0.2          # これ未満の直線距離では迂回係数を見ない
KV_TOL = 0.25
SAME_SITE_KM = 0.3
CELL = 0.01                           # 索引セル(deg) — ±3セル ≈ 3.3km を候補探索
RAIL_RE = re.compile(r"(JR|鉄道|電鉄|き電|きでん|新幹線|軌道|モノレール|地下鉄|"
                     r"railway|Railway|交通局|市営交通)")
DECOM_RE = re.compile(r"(廃止|旧|跡|abandoned|disused)")

AREA_FREQ = {"hokkaido": 50, "tohoku": 50, "tokyo": 50,
             "chubu": 60, "hokuriku": 60, "kansai": 60,
             "chugoku": 60, "shikoku": 60, "kyushu": 60, "okinawa": 60}


# ── 幾何・索引 ────────────────────────────────────────────────────────────
def path_length_km(pts) -> float:
    return sum(dist_km(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def load_line_paths(lines):
    """lines_all の feature → [(feature_idx, path[(lat,lon)])] とセル索引。"""
    feat_paths, grid = [], defaultdict(list)
    for fi, f in enumerate(lines):
        g = f.get("geometry") or {}
        cc = g.get("coordinates") or []
        parts = [cc] if g.get("type") == "LineString" else cc
        for part in parts:
            path = [(c[1], c[0]) for c in part if isinstance(c, (list, tuple))]
            if len(path) < 2:
                continue
            pid = len(feat_paths)
            feat_paths.append((fi, path))
            for c in {(round(p[0], 2), round(p[1], 2)) for p in path}:
                grid[c].append(pid)
    return feat_paths, grid


def cand_pids(grid, p, r=3):
    out, c0 = set(), (round(p[0], 2), round(p[1], 2))
    for dla in range(-r, r + 1):
        for dlo in range(-r, r + 1):
            out |= set(grid.get((round(c0[0] + dla / 100.0, 2),
                                 round(c0[1] + dlo / 100.0, 2)), []))
    return out


def way_kv(lines, feat_paths, pid):
    v = lines[feat_paths[pid][0]].get("properties", {}).get("_voltage_kv")
    try:
        return float(v) if v else None
    except (TypeError, ValueError):
        return None


def kv_ok(a, b, tol=KV_TOL) -> bool:
    """判明している電圧同士が tol を超えて乖離しなければ整合(片方不明は整合)。"""
    try:
        a = float(a) if a else None
        b = float(b) if b else None
    except (TypeError, ValueError):
        return True
    if not a or not b:
        return True
    return abs(a - b) <= max(b, 1.0) * tol


def build_way_adjacency(feat_paths, grid, seam_km):
    """way⇔way の隣接(端点が相手 path に ≤seam_km)。gap は m 単位で保持する。"""
    adj = defaultdict(dict)
    for pid, (_, path) in enumerate(feat_paths):
        for ep in (path[0], path[-1]):
            for pid2 in cand_pids(grid, ep):
                if pid2 == pid or pid2 in adj[pid]:
                    continue
                p2 = feat_paths[pid2][1]
                d = min_dist_to_path(ep, p2)
                if d <= seam_km:
                    j = nearest_vertex_idx(ep, p2)
                    adj[pid][pid2] = (ep, p2[j], round(d * 1000))
                    adj[pid2][pid] = (p2[j], ep, round(d * 1000))
    return adj


# ── 成分 ──────────────────────────────────────────────────────────────────
def island_components(nodes, edges, island):
    """第一波/第二波と同一定義: 島内ノードを k5 キーで畳み、両端が島内の枝で成分分解。"""
    regs = {r for r, i in ISLAND_OF.items() if i == island}
    keys = {}
    for n in nodes:
        if n.get("region") in regs:
            keys.setdefault(k5(n["lat"], n["lon"]), n)
    adj = defaultdict(set)
    for e in edges:
        ka, kb = k5(*e["a"]), k5(*e["b"])
        if ka in keys and kb in keys:
            adj[ka].add(kb)
            adj[kb].add(ka)
    seen, comps = set(), []
    for k in keys:
        if k in seen:
            continue
        stack, comp = [k], set()
        while stack:
            c = stack.pop()
            if c in comp:
                continue
            comp.add(c)
            stack.extend(adj[c] - comp)
        seen |= comp
        comps.append(comp)
    comps.sort(key=len, reverse=True)
    return keys, comps


def island_key_sets(nodes):
    """k5 → その座標にノードを持つ島の集合(跨島双子の検出用)。"""
    out = defaultdict(set)
    for n in nodes:
        isl = ISLAND_OF.get(n.get("region"))
        if isl:
            out[k5(n["lat"], n["lon"])].add(isl)
    return out


def freq_crossing_edges(nodes, edges) -> int:
    """周波数を跨ぐ枝の数(監査 audit_mixed_pref_flip と同じ後勝ち索引)。"""
    by_xy = {}
    for n in nodes:
        by_xy[k5(n["lat"], n["lon"])] = n.get("region")
    n_cross = 0
    for e in edges:
        ra, rb = by_xy.get(k5(*e["a"])), by_xy.get(k5(*e["b"]))
        if ra and rb and AREA_FREQ.get(ra) != AREA_FREQ.get(rb):
            n_cross += 1
    return n_cross


# ── (a) 連鎖回収 ──────────────────────────────────────────────────────────
def find_chains(island, keys, comps, lines, feat_paths, grid, way_adj, existing,
                seam_km, twin_islands=None, detour_max=DETOUR_MAX,
                th_node=TH_NODE, max_ways=MAX_WAYS, min_ways=1):
    """継ぎ目 ≤seam_km の way 連鎖で断片→本系統。1 断片につき最良 1 本。

    Returns (chains, rejected: Counter)。chain は {fk, mk, n_ways, stitch_m, max_seam_m,
    path, detour, names, ...}。rejected は棄却理由の件数(kv / detour / twin / existing)。
    """
    main_set = comps[0]
    mgrid = defaultdict(list)
    for k in main_set:
        mgrid[(round(k[0], 1), round(k[1], 1))].append(k)

    def main_contact(path):
        best, bd = None, th_node
        cells = {(round(p[0], 1), round(p[1], 1)) for p in path}
        cand = set()
        for c in cells:
            for dla in (-1, 0, 1):
                for dlo in (-1, 0, 1):
                    cand |= set(mgrid.get((round(c[0] + dla / 10, 1),
                                           round(c[1] + dlo / 10, 1)), []))
        for m in cand:
            d = min_dist_to_path(m, path)
            if d < bd:
                best, bd = m, d
        return best, bd

    seam_m = seam_km * 1000 + 1e-6
    chains, rejected = [], Counter()
    for comp in comps[1:]:
        # 跨島双子(登録人工物の疑い): 断片ノードの過半が別島の座標にもある → 回収でなく再属性へ
        if twin_islands is not None:
            n_twin = sum(1 for fk in comp if len(twin_islands.get(fk, ())) > 1)
            if n_twin * 2 >= len(comp):
                rejected["twin_cross_island"] += 1
                continue
        best = None
        for fk in comp:
            fkv = keys[fk].get("kv")
            seeds = []
            for pid in cand_pids(grid, fk):
                d = min_dist_to_path(fk, feat_paths[pid][1])
                if d <= th_node and kv_ok(way_kv(lines, feat_paths, pid), fkv):
                    seeds.append((pid, d))
            if not seeds:
                continue
            q, visited = deque(), {}
            for pid, d in sorted(seeds, key=lambda x: x[1]):
                q.append((pid, [pid], 0.0, 0))
                visited[pid] = 0
            while q:
                pid, route, stitch, max_seam = q.popleft()
                if len(route) > max_ways:
                    continue
                mk, dmain = main_contact(feat_paths[pid][1])
                if mk is not None and frozenset((fk, mk)) not in existing \
                        and kv_ok(way_kv(lines, feat_paths, pid), keys[mk].get("kv")) \
                        and kv_ok(fkv, keys[mk].get("kv")):
                    cand = {"n_ways": len(route), "stitch_m": round(stitch * 1000),
                            "max_seam_m": max_seam, "route": route, "fk": fk, "mk": mk,
                            "d_frag_m": round(min_dist_to_path(
                                fk, feat_paths[route[0]][1]) * 1000),
                            "d_main_m": round(dmain * 1000)}
                    if best is None or (cand["n_ways"], cand["stitch_m"]) < \
                            (best["n_ways"], best["stitch_m"]):
                        best = cand
                    break
                for pid2, (a1, a2, gap) in way_adj.get(pid, {}).items():
                    if gap > seam_m or pid2 in visited:
                        continue
                    if not kv_ok(way_kv(lines, feat_paths, pid2), fkv):
                        continue
                    visited[pid2] = len(route)
                    q.append((pid2, route + [pid2], stitch + gap / 1000.0,
                              max(max_seam, gap)))
        if best is None:
            rejected["unreachable"] += 1
            continue
        if best["n_ways"] < min_ways:
            rejected["below_min_ways"] += 1
            continue
        # 端点に跨島双子(同座標に別島ノード)があると、座標キーの枝は相手島の索引にも
        # 載り「周波数跨ぎ枝」を増やす(実測: 静岡・山梨・長野境界帯で 99→101)。回収しない
        if twin_islands is not None and (len(twin_islands.get(best["fk"], ())) > 1 or
                                         len(twin_islands.get(best["mk"], ())) > 1):
            rejected["twin_endpoint"] += 1
            continue
        # 経路構築(接触点間の切り出し・第二波と同じ)
        fk, mk = best["fk"], best["mk"]
        pts, anchor = [], fk
        for i, pid in enumerate(best["route"]):
            path = feat_paths[pid][1]
            if i < len(best["route"]) - 1:
                nxt = way_adj[pid][best["route"][i + 1]][0]
            else:
                nxt = path[nearest_vertex_idx(mk, path)]
            pts.extend(clip_path(path, anchor, nxt))
            anchor = nxt
        full = [fk] + pts + [mk]
        straight = dist_km(fk, mk)
        length = path_length_km(full)
        detour = length / max(straight, DETOUR_MIN_STRAIGHT_KM)
        if straight >= DETOUR_MIN_STRAIGHT_KM and detour > detour_max:
            rejected["detour"] += 1
            continue
        names = [lines[feat_paths[p][0]]["properties"].get("_display_name")
                 for p in best["route"]]
        chains.append({**{k: v for k, v in best.items() if k != "route"},
                       "island": island, "names": names,
                       "frag_name": keys[fk].get("name"), "frag_kv": keys[fk].get("kv"),
                       "main_name": keys[mk].get("name"), "main_kv": keys[mk].get("kv"),
                       "n_frag_nodes": len(comp), "length_km": round(length, 3),
                       "straight_km": round(straight, 3), "detour": round(detour, 2),
                       "path": pts})
    return chains, rejected


# ── (b) 同一敷地同定 ──────────────────────────────────────────────────────
def same_site_candidates(island, keys, comps, same_site_km=SAME_SITE_KM, kv_tol=KV_TOL):
    main_set = comps[0]
    mnames = defaultdict(list)
    for k in main_set:
        b = norm_base(keys[k].get("name"))
        if b and "junction" not in b:
            mnames[b].append(k)
    out = []
    for comp in comps[1:]:
        for fk in comp:
            b = norm_base(keys[fk].get("name"))
            if not b or "junction" in b:
                continue
            for mk in mnames.get(b, []):
                d = dist_km(fk, mk)
                if d > same_site_km:
                    continue
                kvok = kv_ok(keys[fk].get("kv"), keys[mk].get("kv"), kv_tol)
                out.append({"island": island, "frag_name": keys[fk].get("name"),
                            "frag_region": keys[fk].get("region"),
                            "frag_kv": keys[fk].get("kv"), "frag_k": fk,
                            "main_name": keys[mk].get("name"),
                            "main_kv": keys[mk].get("kv"), "main_k": mk,
                            "dist_m": round(d * 1000), "kv_ok": kvok,
                            "n_frag_nodes": len(comp)})
    return out


# ── (c)〜(e) 分類 ─────────────────────────────────────────────────────────
def classify_residual(island, keys, comps, feat_paths, grid, twin_islands,
                      disclosure_names):
    main_set = comps[0]
    mgrid = defaultdict(list)
    for k in main_set:
        mgrid[(round(k[0], 1), round(k[1], 1))].append(k)
    cats, examples = Counter(), defaultdict(list)
    for comp in comps[1:]:
        names = [str(keys[k].get("name") or "") for k in comp]
        subs = [k for k in comp if keys[k].get("sub")]
        n_twin_main = sum(1 for k in comp if len(twin_islands.get(k, ())) > 1)
        if n_twin_main * 2 >= len(comp):
            cat = "c_cross_island_twin"
        elif any(RAIL_RE.search(n) for n in names):
            cat = "d_rail"
        elif any(DECOM_RE.search(n) for n in names):
            cat = "d_decommissioned"
        elif any(norm_base(n) in disclosure_names for n in names if n):
            cat = "e_named_in_disclosure"
        else:
            # OSM 線が 1km 以内に無く、本系統ノードも 5km 以内に無い → 遠隔/離島(回収対象外)
            near_line = any(min_dist_to_path(k, feat_paths[p][1]) <= 1.0
                            for k in comp for p in cand_pids(grid, k, r=1))
            near_main = False
            for k in comp:
                for dla in (-1, 0, 1):
                    for dlo in (-1, 0, 1):
                        for m in mgrid.get((round(k[0] + dla / 10, 1),
                                            round(k[1] + dlo / 10, 1)), []):
                            if dist_km(k, m) <= 5.0:
                                near_main = True
                                break
            if not near_line and not near_main:
                cat = "d_remote_or_island"
            elif all((keys[k].get("kv") or 0) < 60 for k in comp) and len(comp) == 1 and subs:
                cat = "d_distribution_kv_unknown"
            else:
                cat = "f_unclassified"
        cats[cat] += 1
        if cat == "f_unclassified":
            gap = min((dist_km(k, m) for k in comp
                       for dla in (-1, 0, 1) for dlo in (-1, 0, 1)
                       for m in mgrid.get((round(k[0] + dla / 10, 1),
                                           round(k[1] + dlo / 10, 1)), [])),
                      default=float("inf"))
            bucket = ("≤1km" if gap <= 1 else "1-3km" if gap <= 3 else
                      "3-10km" if gap <= 10 else ">10km")
            cats[f"f_unclassified_gap_{bucket}"] += 1
        if len(examples[cat]) < 3:
            k0 = next(iter(subs or comp))
            examples[cat].append({"name": keys[k0].get("name"), "kv": keys[k0].get("kv"),
                                  "lat": k0[0], "lon": k0[1], "n_nodes": len(comp)})
    return cats, examples


def load_disclosure_names():
    names = set()
    for p in (REPORTS / "disclosure_connection_worklist_v2.json",
              REPORTS / "tepco_connection_worklist.json"):
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        items = d.get("connections") or d.get("worklist") or []
        for it in items:
            for k in ("from_sub", "to_sub", "from", "to", "from_name", "to_name"):
                v = it.get(k)
                if isinstance(v, str) and v:
                    names.add(norm_base(v))
    sup = ROOT / "config" / "disclosure_supplement_nodes.yaml"
    if sup.exists():
        try:
            import yaml
            for n in (yaml.safe_load(sup.read_text(encoding="utf-8")) or {}).get("nodes", []):
                if n.get("name"):
                    names.add(norm_base(n["name"]))
        except Exception:      # noqa: BLE001 — 任意の補助入力
            pass
    return names


# ── ドライラン適用 ────────────────────────────────────────────────────────
def dry_run_union(comps, pairs):
    """候補枝 (fk, mk) を union-find で仮適用 → (成分数, 本系統へ合流したノード数)。"""
    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    comp_of = {}
    for ci, comp in enumerate(comps):
        for k in comp:
            comp_of[k] = ci
    for fk, mk in pairs:
        union(("c", comp_of[fk]), ("c", comp_of[mk]))
    roots = {find(("c", ci)) for ci in range(len(comps))}
    main_root = find(("c", 0))
    joined = sum(len(comps[ci]) for ci in range(1, len(comps))
                 if find(("c", ci)) == main_root)
    return len(roots), joined


def run(built, lines, seam_stages_m=SEAM_STAGES_M, detour_max=DETOUR_MAX,
        th_node=TH_NODE, max_ways=MAX_WAYS, disclosure_names=None, verbose=True):
    """全島のドライラン。純関数(ファイルを書かない)。"""
    nodes, edges = built["nodes"], built["edges"]
    feat_paths, grid = load_line_paths(lines)
    seam_max = max(seam_stages_m) / 1000.0
    if verbose:
        print(f"way {len(feat_paths)}本 / 継ぎ目索引 ≤{max(seam_stages_m)}m 構築中...", flush=True)
    way_adj = build_way_adjacency(feat_paths, grid, seam_max)
    existing = {frozenset((k5(*e["a"]), k5(*e["b"]))) for e in edges}
    twins = island_key_sets(nodes)
    disc = load_disclosure_names() if disclosure_names is None else disclosure_names
    n_cross0 = freq_crossing_edges(nodes, edges)

    report = {"stages_m": list(seam_stages_m), "detour_max": detour_max,
              "th_node_km": th_node, "max_ways": max_ways,
              "freq_crossing_edges_before": n_cross0, "islands": {},
              "chains": [], "same_site": []}
    for island in ("hokkaido", "east", "west", "okinawa"):
        keys, comps = island_components(nodes, edges, island)
        if not comps:
            continue
        frag = comps[1:]
        isl = {"n_keys": len(keys), "main": len(comps[0]), "fragments": len(frag),
               "frag_nodes": sum(len(c) for c in frag),
               "frag_subs": sum(1 for c in frag for k in c if keys[k].get("sub")),
               "stages": {}}
        found_at = {}                      # fk-comp id -> first stage
        prev = set()
        stage_chains = {}
        for st in seam_stages_m:
            chains, rej = find_chains(island, keys, comps, lines, feat_paths, grid,
                                      way_adj, existing, st / 1000.0, twins,
                                      detour_max, th_node, max_ways)
            ids = {c["fk"] for c in chains}
            new = ids - prev
            for c in chains:
                if c["fk"] in new:
                    found_at[c["fk"]] = st
            n_comp_after, joined = dry_run_union(comps, [(c["fk"], c["mk"]) for c in chains])
            isl["stages"][str(st)] = {
                "chains": len(chains), "new_at_stage": len(new),
                "rejected": dict(rej),
                "components_after": n_comp_after - 1, "nodes_joined": joined,
                "seam_hist_m": dict(Counter(min(s for s in seam_stages_m if s >= c["max_seam_m"])
                                            for c in chains)),
            }
            stage_chains[st] = chains
            prev = ids
            if verbose:
                print(f"[{island}] seam≤{st}m: 連鎖 {len(chains)}(新規 {len(new)}) "
                      f"→ 成分 {len(frag)}→{n_comp_after-1} / 合流 {joined}ノード / 棄却 {dict(rej)}",
                      flush=True)
        # 連鎖の記録は最大段のもの(各連鎖の max_seam_m で段が分かる)
        for c in stage_chains[max(seam_stages_m)]:
            report["chains"].append({k: v for k, v in c.items() if k != "path"} |
                                    {"first_stage_m": found_at.get(c["fk"])})
        ss = same_site_candidates(island, keys, comps)
        report["same_site"].extend(ss)
        cats, ex = classify_residual(island, keys, comps, feat_paths, grid, twins, disc)
        isl["same_site"] = len(ss)
        isl["residual_classes"] = dict(cats)
        isl["residual_examples"] = ex
        report["islands"][island] = isl
        report.setdefault("_paths", {})[island] = stage_chains
    return report


def write_proposals_yaml(same_site, path, date):
    lines = ["# 同一敷地同定の提案 — 第三波(" + date + ")・**承認待ち**(approved: false)",
             "# 様式は config/isolated_verdict_overrides.yaml と同じ運用: オーナーが approved: true を",
             "# 立てたものだけを別介入で適用する(断片ノードを本系統ノードへ同定=枝を張らない)。",
             "# 根拠=名前基底の一致(NFKC・末尾 _n / kV を除去)+距離 ≤300m。kv_ok=false は電圧不整合",
             "# (同名でも別階級の設備=同定不可の疑い)。",
             "proposals:"]
    for s in sorted(same_site, key=lambda s: (s["island"], s["dist_m"])):
        lines += [f"  - name: {json.dumps(s['frag_name'], ensure_ascii=False)}",
                  f"    region: {s['frag_region']}",
                  f"    island: {s['island']}",
                  "    verdict: same_site",
                  "    approved: false",
                  f"    target: {json.dumps(s['main_name'], ensure_ascii=False)}",
                  f"    frag_kv: {s['frag_kv']}",
                  f"    main_kv: {s['main_kv']}",
                  f"    kv_ok: {str(bool(s['kv_ok'])).lower()}",
                  f"    dist_m: {s['dist_m']}",
                  f"    frag_latlon: [{s['frag_k'][0]}, {s['frag_k'][1]}]",
                  f"    main_latlon: [{s['main_k'][0]}, {s['main_k'][1]}]",
                  f"    n_frag_nodes: {s['n_frag_nodes']}",
                  f"    evidence: \"名前基底一致・{s['dist_m']}m・"
                  f"{'kv整合' if s['kv_ok'] else 'kv不整合'}(第三波 {date} 機械抽出・判読未)\""]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_md(report, date, seam_apply_m):
    L = [f"# 断片解消キャンペーン第三波 — ドライラン({date})", "",
         "- 状態: **ドライラン(正典 all.json 不変)**。適用は親セッションがゲート確認後に "
         f"`--seam-m {seam_apply_m} --write` で行う",
         f"- ゲート: 電圧整合 ≤{int(KV_TOL*100)}% / 迂回係数 ≤{report['detour_max']} / "
         f"跨島双子(断片の過半・または端点)は回収せず再属性へ / 継ぎ目段階 {report['stages_m']} m / "
         f"ノード接触 ≤{int(report['th_node_km']*1000)}m / 最大 {report['max_ways']} way",
         f"- 周波数跨ぎ枝(前): {report['freq_crossing_edges_before']}"
         + (f" → 仮適用後: {report['freq_crossing_edges_after']}" if "freq_crossing_edges_after" in report else ""),
         "", "## 現状(介入#42 後・第一波/第二波と同じ定義=島内 k5 キー・stitch/タイ無し)", "",
         "| 島 | キー数 | 本系統 | 断片成分 | 断片ノード | 断片変電所 |", "|---|---:|---:|---:|---:|---:|"]
    for isl, d in report["islands"].items():
        L.append(f"| {isl} | {d['n_keys']:,} | {d['main']:,} | {d['fragments']} | {d['frag_nodes']} | {d['frag_subs']} |")
    L += ["", "## (a) 継ぎ目段階ごとの回収(累積)", "",
          "| 島 | 段 | 連鎖 | 新規 | 成分 after | 合流ノード | 棄却 |", "|---|---:|---:|---:|---:|---:|---|"]
    for isl, d in report["islands"].items():
        for st, s in d["stages"].items():
            L.append(f"| {isl} | ≤{st}m | {s['chains']} | {s['new_at_stage']} | "
                     f"{s['components_after']} | {s['nodes_joined']} | {s['rejected']} |")
    L += ["", "## (b) 同一敷地同定の提案(承認待ち)", ""]
    for isl, d in report["islands"].items():
        L.append(f"- {isl}: {d['same_site']} 件")
    L += ["", "## (c)〜(f) 残存断片の分類(成分単位・代表例)", ""]
    for isl, d in report["islands"].items():
        L.append(f"### {isl}")
        for cat, n in sorted(d["residual_classes"].items()):
            ex = "; ".join(f"{e['name']}({e['kv']}kV @{e['lat']:.4f},{e['lon']:.4f}・{e['n_nodes']}ノード)"
                           for e in d["residual_examples"].get(cat, []))
            L.append(f"- `{cat}`: {n} — {ex}")
        L.append("")
    L += ["## 読み方", "",
          "- `c_cross_island_twin`: 断片ノードの過半が別島にも同座標ノードを持つ=越境スライスの二重登録の疑い。"
          "枝を張らず region 再属性/同定で解く(screen_false_fragments と同じ判定)",
          "- `d_*`: 回収対象外の推定(鉄道き電・廃止・遠隔/離島・配電)。名前・距離ヒューリスティクスであり判読ではない",
          "- `e_named_in_disclosure`: 開示台帳(worklist v2 / TEPCO / 供給ノード)に名前があるのに本系統外=開示の再適用で繋がる候補",
          "- 連鎖の `max_seam_m` が段を決める。60m 段は第二波の再現(#42 の再属性で新たに生じた分のみ増える)"]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--built", default=str(BUILT))
    ap.add_argument("--lines", default=str(LINES))
    ap.add_argument("--out-dir", default=str(REPORTS))
    ap.add_argument("--date", default=_dt.date.today().isoformat())
    ap.add_argument("--seam-m", type=int, default=200,
                    help="--write で適用する継ぎ目段(m)。既定 200")
    ap.add_argument("--detour-max", type=float, default=DETOUR_MAX)
    ap.add_argument("--write", action="store_true",
                    help="正典へ適用(バックアップ all.json.pre_frag3.bak)。親セッション専用")
    ap.add_argument("--islands", nargs="*", default=None,
                    choices=["hokkaido", "east", "west", "okinawa"],
                    help="適用(と仮計上)を島で絞る。2026-09-02: east の 17 本を適用すると east "
                         "ピーク AC が dc_fallback に退行したため hokkaido/west のみ適用した")
    args = ap.parse_args(argv)

    built = json.loads(Path(args.built).read_text(encoding="utf-8"))
    lines = json.loads(Path(args.lines).read_text(encoding="utf-8"))["features"]
    rep = run(built, lines, detour_max=args.detour_max)
    paths = rep.pop("_paths")

    # 適用段の候補で周波数跨ぎ枝が増えないことを仮計上
    apply_chains = [c for isl in paths for c in paths[isl].get(args.seam_m, [])
                    if args.islands is None or isl in args.islands]
    rep["apply_islands"] = args.islands or ["hokkaido", "east", "west", "okinawa"]
    test_edges = built["edges"] + [{"a": list(c["fk"]), "b": list(c["mk"])} for c in apply_chains]
    rep["freq_crossing_edges_after"] = freq_crossing_edges(built["nodes"], test_edges)
    rep["apply_stage_m"] = args.seam_m
    rep["apply_candidates"] = len(apply_chains)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / f"fragment_third_wave_{args.date}.json"
    jp.write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=list), encoding="utf-8")
    (out_dir / f"fragment_third_wave_{args.date}.md").write_text(
        render_md(rep, args.date, args.seam_m), encoding="utf-8")
    write_proposals_yaml(rep["same_site"], out_dir / f"same_site_proposals_{args.date}.yaml", args.date)
    print(f"-> {jp.relative_to(ROOT) if jp.is_relative_to(ROOT) else jp}"
          f" (+ .md / same_site_proposals_{args.date}.yaml)")
    print(f"適用段 ≤{args.seam_m}m の候補 {len(apply_chains)} 本 / 周波数跨ぎ枝 "
          f"{rep['freq_crossing_edges_before']} → {rep['freq_crossing_edges_after']}")

    if args.write:
        if rep["freq_crossing_edges_after"] != rep["freq_crossing_edges_before"]:
            print("★中止: 周波数跨ぎ枝が増える候補が含まれる(構造上あり得ない — 調査せよ)")
            return 2
        bak = Path(args.built).with_name(Path(args.built).name + ".pre_frag3.bak")
        bak.write_text(json.dumps(built, ensure_ascii=False), encoding="utf-8")
        for c in apply_chains:
            fk, mk = c["fk"], c["mk"]
            kv = c["frag_kv"] or c["main_kv"] or 66.0
            path = [[fk[0], fk[1]]] + [[p[0], p[1]] for p in c["path"]] + [[mk[0], mk[1]]]
            nm = " / ".join(str(n) for n in c["names"] if n)[:60]
            built["edges"].append({
                "a": [fk[0], fk[1]], "b": [mk[0], mk[1]], "main": True, "par": 1,
                "kv": float(kv), "name": nm or "OSM連鎖回収線(第三波)", "path": path,
                "disclosure": (f"OSM実線連鎖回収(第三波 {args.date}): {c['n_ways']}way・"
                               f"継ぎ目最大{c['max_seam_m']}m/計{c['stitch_m']}m・"
                               f"接触{c['d_frag_m']}m/{c['d_main_m']}m・迂回{c['detour']}"),
                "recovery": "osm_chain3"})
        Path(args.built).write_text(json.dumps(built, ensure_ascii=False), encoding="utf-8")
        print(f"★正典適用: {len(apply_chains)}本(第三波・継ぎ目≤{args.seam_m}m) バックアップ={bak.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
