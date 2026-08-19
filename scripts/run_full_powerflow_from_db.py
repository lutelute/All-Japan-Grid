#!/usr/bin/env python3
"""Full-scale national power flow from the canonical built DB (docs/data/built).

Owner directive (2026-06-18, PLAN_NEXT "DB:" DB1-3): solve the power flow at
**full scale** — every node in ``all.json`` is a bus, every edge a branch — with
NO voltage-class reduction (reduction is deferred as DB5). The built physical
connectivity is treated as ground truth ("OSM で繋がっているものは極力繋がっている
ように計算"), so we solve **per connected component within each frequency island**.

Key modelling choices (stated, not fabricated):
  * Bus     = built node (lat/lon/kv/sub/region preserved; id is unique).
  * Branch  = built edge. R/X/C and ampacity come from the committed per-class
              reference table (config/line_types.yaml via line_parameters), at
              the island frequency (50 Hz east / 60 Hz west). ``par`` sets the
              number of parallel circuits. edge kv==0 inherits the max kv of its
              endpoints. Branch length = haversine over the stored polyline.
  * Transformer = a SITE that hosts >1 distinct voltage (co-located nodes of
              different kv). We connect the voltage levels with an ideal-ish
              pandapower 2-winding transformer instead of a zero-length line or
              a coord self-loop (the coarse-key trap the owner warned about).
              Rating = sum of the lower-side lines' thermal capacity (min 100 MVA).
  * Load    = allocated ONLY to substation buses (sub==1), per region, by the
              committed regional peak demand x load_factor, voltage-class
              weighted (config/regional_demand.yaml). Junction buses carry none
              (they are tap points on a line, not delivery points). This realises
              "負荷bus は変電所に接続".
  * Gen     = OSM plants (data/{region}_plants.geojson) attached to the nearest
              substation bus (<=20 km), capacity from OSM or class default.
  * Slack   = the largest-capacity generator bus in each solved component; a
              component with no generator gets an ext_grid at its highest-kv,
              highest-degree substation (so every component is solvable; flagged).

Each frequency island is assembled as ONE pandapower net (so the cross-region
AC ties inside an island transfer power), then solved per connected component:
AC (Newton, q-lims, with a DC-prune fallback ladder) first, DC as the honest
fallback when AC will not converge. Non-convergence is recorded, never faked.
Outputs go to a NEW dir (docs/data/powerflow_full) so the live powerflow tab
(docs/data/powerflow) is untouched. allow_nan=False on every dump.

Usage (heavy -> pws-160core):
  PYTHONPATH=. .venv/bin/python scripts/run_full_powerflow_from_db.py \
      --output-dir docs/data/powerflow_full
  ... --islands east            # subset
  ... --max-ac-buses 6000       # skip AC attempt for components bigger than this
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import sys
import time
import warnings
from collections import defaultdict

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import networkx as nx
import pandapower as pp

from src.converter.line_parameters import get_line_parameters_safe
from src.powerflow.load_estimator import load_demand_config
from src.powerflow.batch_solve import run_powerflow

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# AGJ_BUILT_PATH: 適用候補モデル(scratch)での影響測定用。正典を書かずに before/after を取る。
BUILT = os.environ.get("AGJ_BUILT_PATH",
                       os.path.join(ROOT, "docs", "data", "built", "all.json"))
OUT_DEFAULT = os.path.join(ROOT, "docs", "data", "powerflow_full")

# Synchronous AC islands (region -> island, freq). Mirrors src.powerflow.national
# ISLANDS exactly (east 50 Hz, west 60 Hz, hokkaido 50 Hz alone, okinawa 60 Hz).
ISLAND_OF = {
    "hokkaido": ("hokkaido", 50),
    "tohoku": ("east", 50), "tokyo": ("east", 50),
    "chubu": ("west", 60), "hokuriku": ("west", 60), "kansai": ("west", 60),
    "chugoku": ("west", 60), "shikoku": ("west", 60), "kyushu": ("west", 60),
    "okinawa": ("okinawa", 60),
}
ISLAND_FREQ = {"hokkaido": 50, "east": 50, "west": 60, "okinawa": 60}

VALID_KV = [66, 77, 110, 132, 154, 187, 220, 275, 500]
# 介入#25: `capacity_mw` 欠損を埋める燃料別既定容量＝**出典のない合成容量**。
# solar は 2026-08-10 に 10.0 → 0.10（OSM 実容量 600 件の中央値）へ是正した。
# 10.0 は中央値の 100 倍で、太陽光を 180GW＝実績ピークの 318% に膨らませ、
# `balance_by_zone` が容量比例で配分するため**そのままゾーン内の空間配分**になっていた
# （夕方17時の断面で east 注入の 45.9% が太陽光ノードに載る＝17時の太陽光出力はゼロ）。
# 合成率 48.3% → 20.1%。無効化は `--default-cap solar=10.0`。
# 出典と波及: `docs/reports/intervention25_impact_inventory_2026-08-10.md`
_DEFAULT_CAP = {"nuclear": 1000.0, "coal": 600.0, "gas": 400.0, "oil": 300.0,
                "hydro": 50.0, "solar": 0.10, "wind": 10.0, "biomass": 20.0}
_CAP_FALLBACK = 30.0


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _path_len_km(path):
    if not path or len(path) < 2:
        return 0.0
    return sum(_haversine_km(path[i][0], path[i][1], path[i + 1][0], path[i + 1][1])
               for i in range(len(path) - 1))


def _k5(la, lo):
    return (round(la, 5), round(lo, 5))


NOT_IN_SERVICE_PATH = os.path.join(ROOT, "data", "reference",
                                   "not_in_service_lines.json")


def _load_not_in_service():
    """介入#23: 未供用線リスト(出典URL+quote必須)。無ければ空。"""
    try:
        with open(NOT_IN_SERVICE_PATH, encoding="utf-8") as f:
            return json.load(f).get("lines", [])
    except FileNotFoundError:
        return []


def _nearest_kv(kv):
    if kv and kv > 0:
        return min(VALID_KV, key=lambda k: abs(k - kv))
    return 0.0


# ──────────────────────────────────────────────────────────────────────────
#  Build one frequency island as a pandapower net straight from built nodes/edges
# ──────────────────────────────────────────────────────────────────────────
STRUCTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "data", "structures")
_NAMEPLATES_CACHE = None


def _norm_site_name(s):
    """OSM表記ゆれ吸収(NFKC+空白除去)。transformer_provenance.normalize_site_key と同旨。"""
    import re as _re
    import unicodedata as _ud
    return _re.sub(r"\s+", "", _ud.normalize("NFKC", str(s)))


def _site_name_of_node(name):
    """built ノード名 '信貴変電所 500kV' から電圧サフィックスを外して正規化。"""
    import re as _re
    return _norm_site_name(_re.sub(r"\s*\d+(?:\.\d+)?\s*kV$", "", str(name)))


def load_nameplates(structures_dir=STRUCTURES_DIR):
    """構造DB(出典必須DB data/transformer_sources.jsonl から existing のみ伝播済み)の
    銘板 TransformerSpec を (region, 正規化サイト名) -> [spec...] で返す (Ybus v4)。

    正典の流れ: 出典DB --apply(existingのみ)--> 構造DB --本関数--> build_island_net。
    構造DBが無い環境では空 dict (従来のヒューリスティック容量にフォールバック)。
    """
    import glob as _glob
    out = {}
    for path in sorted(_glob.glob(os.path.join(structures_dir, "*.json"))):
        if os.path.basename(path) == "summary.json":
            continue
        try:
            with open(path) as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        region = d.get("region")
        for s in d.get("structures", []):
            plates = [t for t in s.get("transformers", [])
                      if t.get("source") == "nameplate" and t.get("sn_mva")]
            if not plates:
                continue

            def _kv(vl_id):
                try:
                    return float(str(vl_id).rsplit("@", 1)[1])
                except (IndexError, ValueError):
                    return None

            key = (region, _norm_site_name(s["site"]["name"]))
            out.setdefault(key, []).extend(
                {"hv_kv": _kv(t.get("hv_vl_id")), "lv_kv": _kv(t.get("lv_vl_id")),
                 "sn_mva": float(t["sn_mva"]),
                 "n_parallel": max(int(t.get("n_parallel") or 1), 1)}
                for t in plates)
    return out


def _get_nameplates():
    global _NAMEPLATES_CACHE
    if _NAMEPLATES_CACHE is None:
        _NAMEPLATES_CACHE = load_nameplates()
    return _NAMEPLATES_CACHE


# 介入#31: 通電のまま残す合成タイ(実線形が未完で連結を代表している断面のみ)。
# 東北東京=相馬双葉幹線の南いわき地点に340m切れ端未縫合(tie_duplication_audit)。
# 縫合が完了したらこの集合から外して除外に揃える。
KEEP_LIVE_TIES = {"東北東京間連系線"}

# 介入#32(2026-08-19): 南福光BTBのAC素通し切断。中部北陸間は南福光連系所の
# BTB(back-to-back DC・非同期)による連系で、交流の直通は実在しない。モデルは
# 中部側(越美幹線)と北陸側(加賀福光線・能越幹線)が同一バスに合流し、実績断面
# 575MW・UC断面1,210MWがAC素通しになっていた(運用容量の中央値300MWの2〜4倍)。
# バスを中部側/北陸側に分割し、指定線名の枝を中部側バスへ付け替える。
# 根拠=OCCTO連系設備定義(interconnections.yaml ic_005・正本jsonl)。
# 帳簿=build統計 n_btb_split。無効化=--no-btb-split。
BTB_SPLITS = [
    {"bus_name": "南福光連系所",
     "move_lines_containing": ["越美幹線"],
     "new_zone": "chubu",
     "source": "OCCTO 中部北陸間連系設備=南福光BTB(非同期・中央値300MW)"},
]


def build_island_net(island, nodes, edges, freq, geom_out, nameplates="auto",
                     territory=True, dedup_nodes=True, site_trafos=False,
                     deenergize_unbuilt=False, synthetic_ties_live=False,
                     btb_split=True):
    """Return (net, bus_of_nodeidx, stats). One bus per node, one line per edge,
    transformers between co-located voltage levels. No reduction.

    nameplates: "auto"(既定)=構造DBの銘板(existing出典のみ)を該当サイトの trafo
    sn_mva/parallel に適用(v4)。None=従来ヒューリスティック容量のみ(回帰比較用)。
    territory: True(既定)=ノードregionを領土(座標→県→エリア)で再属性してから
    バス化する(A案 2026-07-07採用)。bbox重なり由来のzone誤属性(幻tie・実tie不可視化・
    需要/UC注入の誤帰属)を修正する。物理接続は不変。False=旧挙動(回帰比較用)。
    dedup_nodes: True(既定・2026-07-10 介入#21既定化)=同一座標(6桁≈0.1m)+同一電圧の
    重複ノードを1バスに畳む(bbox重なりで同一OSMオブジェクトが別regionに二重抽出
    された分=B案 2026-07-09)。座標はOSM幾何由来ゆえ完全一致は同一物理点=除去で
    あって接続の追加ではない(docs/reports/west_fragmentation_rootcause_2026-07-09.md)。
    False=従来挙動(回帰比較用・CLIは --no-dedup-nodes)。既定化判断=
    docs/reports/default_on_decision_2026-07-10.md
    site_trafos: True=介入#22 サイト内変圧器リンク。同名変電所(電圧サフィックス・
    _N複製サフィックス除去後の正規化名一致+空間クラスタ0.6km以内)の異電圧階級バスを
    2巻線変圧器で連結する。従来は同一座標(_k5≈1m)のみで、同一サイトでも数十m離れた
    電圧階級ヤードが未連結だった(west T-gap 57%・東京城南チェーン低電圧の主因)。
    既定OFF(正典比較性)。
    deenergize_unbuilt: True=介入#23 未供用線の正直化。建設済みだが供用前の送電線
    (data/reference/not_in_service_lines.json・出典必須)を in_service=False で建てる。
    初例=大間幹線(大間原発 運転開始未定・J-POWER一次)。無負荷EHV線のフェランチ
    過電圧アーティファクトを除く。既定OFF。"""
    if nameplates == "auto":
        nameplates = _get_nameplates()
    rstats = None
    if territory:
        from src.powerflow.region_attribution import reattribute_node_regions
        rstats = reattribute_node_regions(nodes)   # in-place・冪等
    net = pp.create_empty_network(name=f"full_{island}", f_hz=freq)

    # candidate buses = nodes whose region maps to this island
    isl_nodes = [(i, n) for i, n in enumerate(nodes)
                 if ISLAND_OF.get(n.get("region"), (None, None))[0] == island]
    bus_of = {}
    dedup_key = {}          # (lat6,lon6,kv1) -> bus (B案: 重複ノードを畳む)
    n_dedup_merged = 0
    for i, n in isl_nodes:
        vn = float(n.get("kv") or 0.0)
        if vn <= 0:
            vn = 66.0  # unknown -> lowest transmission class (kept solvable)
        if dedup_nodes:
            key = (round(float(n["lat"]), 6), round(float(n["lon"]), 6),
                   round(vn, 1))
            if key in dedup_key:
                bus_of[i] = dedup_key[key]   # 同一物理点の二重抽出 -> 既存バスへ
                n_dedup_merged += 1
                continue
        b = pp.create_bus(net, vn_kv=vn, name=str(n.get("name") or n["id"]),
                          type="b" if n.get("sub") == 1 else "n",
                          geodata=(n["lon"], n["lat"]))
        net.bus.at[b, "zone"] = n.get("region")
        bus_of[i] = b
        if dedup_nodes:
            dedup_key[key] = b

    # coord -> node indices in this island (for edge endpoint resolution + trafos)
    coord_nodes = defaultdict(list)
    for i, n in isl_nodes:
        coord_nodes[_k5(n["lat"], n["lon"])].append(i)

    # ---- lines from edges (skip a leg if its two endpoints differ in kv at the
    #      SAME coordinate — that is a transformer, handled below) ----
    n_line = 0
    n_edge_skipped = 0
    n_edge_dup = 0
    n_deenergized = 0
    n_tie_nis = 0
    nis_rules = _load_not_in_service() if deenergize_unbuilt else []
    seen_edges = {}         # (min bus, max bus, kv, path署名) -> line idx(B案 エッジ側)
    for e in edges:
        ka, kb = _k5(*e["a"]), _k5(*e["b"])
        ca, cb = coord_nodes.get(ka), coord_nodes.get(kb)
        if not ca or not cb:
            continue  # edge not in this island
        ekv = float(e.get("kv") or 0.0)
        # endpoint node: prefer the one whose kv matches the edge kv, else first
        def pick(cands):
            if ekv > 0:
                for j in cands:
                    if abs(float(nodes[j].get("kv") or 0) - ekv) < 0.5:
                        return j
            return cands[0]
        ja, jb = pick(ca), pick(cb)
        if ja == jb:
            n_edge_skipped += 1
            continue
        fa, ta = bus_of[ja], bus_of[jb]
        kv = ekv or max(float(nodes[ja].get("kv") or 0),
                        float(nodes[jb].get("kv") or 0)) or 66.0
        if dedup_nodes:
            # エッジ側の二重抽出除去(B案): 同一バス対+同一電圧階級+同一経路の線は
            # 同一OSM wayがbbox重なりで二重抽出されたもの(実測99.6%が経路完全一致)。
            # 本物の並列回線は built では par>1 の単一エッジなのでここに掛からない。
            # 経路が異なる別ルートは別署名になり残す(下北線・鉄道等の稀少例)。
            ppath = e.get("path") or [e["a"], e["b"]]
            psig = tuple((round(p[0], 5), round(p[1], 5)) for p in ppath)
            esig = (min(fa, ta), max(fa, ta), _nearest_kv(kv) or round(kv, 0),
                    min(psig, tuple(reversed(psig))))
            if esig in seen_edges:
                # 二重抽出: 既存線を残し、回線数(par)は大きい方を採用(過少計上防止)
                kept = seen_edges[esig]
                net.line.at[kept, "parallel"] = max(
                    int(net.line.at[kept, "parallel"]),
                    max(int(e.get("par") or 1), 1))
                n_edge_dup += 1
                continue
        # AGJ_CALIBRATED_LINES=1 で line_types.yaml の calibrated 値（介入#27:
        # 187kV r=0.060 等・既定OFF）を使う。影響測定・採否判断用のスイッチ。
        params = get_line_parameters_safe(
            _nearest_kv(kv) or kv, freq,
            calibrated=os.environ.get("AGJ_CALIBRATED_LINES", "") == "1")
        if params is None:
            n_edge_skipped += 1
            continue
        length = _path_len_km(e.get("path") or [e["a"], e["b"]])
        if length <= 0:
            length = max(_haversine_km(*e["a"], *e["b"]), 0.05)
        x = params["x_ohm_per_km"] or 0.001
        # 介入#31(2026-08-17 オーナー承認): 合成連系タイ(tie)とDC連系枝(dc_tie/dc)は
        # in_service=False で建てる。実連系線の実線形が既にあり二重計上(タイは直線・
        # kv=0が500継承で低Z並列路)、DCは交流ループを形成してはならない。
        # 例外=東北東京間連系線: 相馬双葉幹線の南いわき地点に340mの切れ端未縫合が
        # あり実線形が未完のため、縫合完了まで通電のまま残す(台帳に記録)。
        synthetic = bool(e.get("tie") or e.get("dc_tie") or e.get("dc"))
        keep_live = str(e.get("name") or "") in KEEP_LIVE_TIES
        li = pp.create_line_from_parameters(
            net, from_bus=fa, to_bus=ta, length_km=length,
            r_ohm_per_km=params["r_ohm_per_km"], x_ohm_per_km=x,
            c_nf_per_km=params["c_nf_per_km"], max_i_ka=params["max_i_ka"],
            name=str(e.get("name") or f"line_{n_line}"),
            parallel=max(int(e.get("par") or 1), 1),
            in_service=(not synthetic) or keep_live or synthetic_ties_live)
        if synthetic and not (keep_live or synthetic_ties_live):
            n_tie_nis += 1
        if dedup_nodes:
            seen_edges[esig] = li
        if nis_rules:
            enm = str(e.get("name") or "")
            for rule in nis_rules:
                m = rule.get("match", {})
                if m.get("name_contains") and m["name_contains"] in enm \
                        and abs(float(m.get("kv", kv)) - kv) < 0.5:
                    net.line.at[li, "in_service"] = False
                    n_deenergized += 1
                    break
        n_line += 1
        # geometry for export (key by endpoint bus coords, both directions)
        a5 = (_k5(nodes[ja]["lat"], nodes[ja]["lon"]))
        b5 = (_k5(nodes[jb]["lat"], nodes[jb]["lon"]))
        path = e.get("path") or [e["a"], e["b"]]
        coords = [[p[1], p[0]] for p in path]
        geom_out[(a5, b5)] = coords
        geom_out[(b5, a5)] = list(reversed(coords))

    # ---- transformers between co-located voltage levels (a real substation
    #      that steps voltage). For each site, chain adjacent distinct-kv buses
    #      (high->low) with a 2-winding transformer sized to the lower side. ----
    n_trafo = 0
    n_trafo_nameplate = 0
    for coord, idxs in coord_nodes.items():
        if len(idxs) < 2:
            continue
        # distinct voltage levels at this site -> representative bus each
        by_kv = {}
        for j in idxs:
            vn = float(net.bus.at[bus_of[j], "vn_kv"])
            by_kv.setdefault(round(vn, 1), bus_of[j])
        kvs = sorted(by_kv.keys(), reverse=True)
        # site nameplates (structure DB, existing provenance only): built nodes and
        # the structure DB share the same OSM name source, so a normalized
        # (region, site-name) lookup addresses the same physical substation (v4)
        plates = []
        if nameplates:
            seen_site = set()
            for j in idxs:
                nm = nodes[j].get("name")
                if not nm:
                    continue
                key = (nodes[j].get("region"), _site_name_of_node(nm))
                if key not in seen_site:
                    seen_site.add(key)
                    plates.extend(nameplates.get(key, ()))
        for hv_kv, lv_kv in zip(kvs, kvs[1:]):
            hb, lb = by_kv[hv_kv], by_kv[lv_kv]
            if hv_kv <= lv_kv:
                continue
            # rating: nameplate (provenance-backed, exact voltage-pair match) wins;
            # else cover the lower side's typical line capacity, >=100 MVA
            sn = max(100.0, math.sqrt(3) * lv_kv
                     * (get_line_parameters_safe(_nearest_kv(lv_kv) or lv_kv, freq) or
                        {"max_i_ka": 1.0})["max_i_ka"])
            par, tag = 1, ""
            for p in plates:
                if p["hv_kv"] is None or abs(p["hv_kv"] - hv_kv) > 0.5:
                    continue
                if p["lv_kv"] is None or abs(p["lv_kv"] - lv_kv) > 0.5:
                    continue
                sn, par, tag = p["sn_mva"], p["n_parallel"], "@nameplate"
                break
            try:
                pp.create_transformer_from_parameters(
                    net, hv_bus=hb, lv_bus=lb, sn_mva=sn,
                    vn_hv_kv=hv_kv, vn_lv_kv=lv_kv,
                    vkr_percent=0.5, vk_percent=12.0,   # typical large power trafo
                    pfe_kw=0.0, i0_percent=0.0, parallel=par,
                    name=f"trafo_{hv_kv:.0f}/{lv_kv:.0f}kV{tag}")
                n_trafo += 1
                if tag:
                    n_trafo_nameplate += 1
            except (ValueError, TypeError):
                pass

    # ---- 介入#22: サイト内変圧器リンク(opt-in) — 同名変電所の異電圧階級を連結。
    #      従来の _k5(≈1m)同一座標条件では、同一サイトでも電圧階級ヤードが数十m
    #      離れていると変圧器が張られない(west T-gap 57%・東京城南チェーンの主因)。
    #      同名(電圧/_N複製サフィックス除去)+0.6km空間クラスタ=同一物理変電所とみなす。
    #      接続の「追加」だが根拠は実在変電所の定義そのもの(複数電圧階級を持つ
    #      変電所は変圧器で階級間を結んでいる)。sub=1ノードのみ・既存連結はスキップ。 ----
    n_site_trafo = 0
    if site_trafos:
        import re as _re22
        by_site = defaultdict(list)
        for i, n in isl_nodes:
            if n.get("sub") != 1:
                continue
            nm = n.get("name") or ""
            if not nm:
                continue
            base = _re22.sub(r"_\d+$", "", _site_name_of_node(nm))
            if base:
                by_site[base].append(i)
        linked = {frozenset((int(r["hv_bus"]), int(r["lv_bus"])))
                  for _, r in net.trafo.iterrows()}
        R_KM = 0.6
        for base, idxs in sorted(by_site.items()):
            if len(idxs) < 2:
                continue
            # 空間クラスタ(単リンク・R_KM): 同名でも離れたサイトは別物として扱う
            clusters = []
            for j in idxs:
                placed = False
                for cl in clusters:
                    if any(_haversine_km(nodes[j]["lat"], nodes[j]["lon"],
                                         nodes[k]["lat"], nodes[k]["lon"]) <= R_KM
                           for k in cl):
                        cl.append(j)
                        placed = True
                        break
                if not placed:
                    clusters.append([j])
            for cl in clusters:
                by_kv2 = {}
                for j in cl:
                    vn = round(float(net.bus.at[bus_of[j], "vn_kv"]), 1)
                    cur = by_kv2.get(vn)
                    if cur is None or (nodes[j].get("deg") or 0) > \
                            (nodes[cur].get("deg") or 0):
                        by_kv2[vn] = j
                kvs2 = sorted(by_kv2.keys(), reverse=True)
                if len(kvs2) < 2:
                    continue
                plates = []
                if nameplates:
                    seen_site = set()
                    for j in cl:
                        key = (nodes[j].get("region"),
                               _site_name_of_node(nodes[j].get("name") or ""))
                        if key not in seen_site:
                            seen_site.add(key)
                            plates.extend(nameplates.get(key, ()))
                for hv_kv, lv_kv in zip(kvs2, kvs2[1:]):
                    hb, lb = bus_of[by_kv2[hv_kv]], bus_of[by_kv2[lv_kv]]
                    if hb == lb or frozenset((hb, lb)) in linked:
                        continue
                    sn = max(100.0, math.sqrt(3) * lv_kv
                             * (get_line_parameters_safe(
                                 _nearest_kv(lv_kv) or lv_kv, freq) or
                                {"max_i_ka": 1.0})["max_i_ka"])
                    par, tag = 1, ""
                    for p in plates:
                        if p["hv_kv"] is None or abs(p["hv_kv"] - hv_kv) > 0.5:
                            continue
                        if p["lv_kv"] is None or abs(p["lv_kv"] - lv_kv) > 0.5:
                            continue
                        sn, par, tag = p["sn_mva"], p["n_parallel"], "@nameplate"
                        break
                    try:
                        pp.create_transformer_from_parameters(
                            net, hv_bus=hb, lv_bus=lb, sn_mva=sn,
                            vn_hv_kv=hv_kv, vn_lv_kv=lv_kv,
                            vkr_percent=0.5, vk_percent=12.0,
                            pfe_kw=0.0, i0_percent=0.0, parallel=par,
                            name=f"site_trafo_{hv_kv:.0f}/{lv_kv:.0f}kV{tag}")
                        linked.add(frozenset((hb, lb)))
                        n_site_trafo += 1
                        n_trafo += 1
                        if tag:
                            n_trafo_nameplate += 1
                    except (ValueError, TypeError):
                        pass

    # ---- 介入#32: BTB連系所のAC素通し切断(既定ON) — BTB_SPLITS参照。
    #      同名バスを設備の両側に分割し、指定線名の枝のみ新バスへ付け替える。
    #      変圧器・負荷・発電機は元バス(北陸側)に残る。 ----
    n_btb_split = 0
    if btb_split:
        for spec in BTB_SPLITS:
            hits = net.bus.index[net.bus.name.astype(str) == spec["bus_name"]]
            for b in hits:
                mask = ((net.line.from_bus == b) | (net.line.to_bus == b)) & \
                    net.line.name.astype(str).str.contains(
                        "|".join(spec["move_lines_containing"]), regex=True)
                if not mask.any():
                    continue
                try:
                    gd = net.bus_geodata.loc[b]
                    geodata = (float(gd["x"]), float(gd["y"]))
                except (AttributeError, KeyError):
                    geodata = None
                # type="n"(junction)が重要: allocate_loads は type!="n" のバスへ
                # 需要を配るため、"b"で作ると(chubu,富山県)の県別需要がこの
                # 1バスに集中する(診断で1,556MW集中を実測)。BTB端子は無負荷。
                nb = pp.create_bus(
                    net, vn_kv=float(net.bus.at[b, "vn_kv"]),
                    name=f"{spec['bus_name']}(中部側)", type="n",
                    geodata=geodata)
                net.bus.at[nb, "zone"] = spec.get("new_zone")
                for li in net.line.index[mask]:
                    if int(net.line.at[li, "from_bus"]) == int(b):
                        net.line.at[li, "from_bus"] = nb
                    if int(net.line.at[li, "to_bus"]) == int(b):
                        net.line.at[li, "to_bus"] = nb
                    n_btb_split += 1

    return net, bus_of, {"n_bus": len(net.bus), "n_line": n_line,
                         "n_trafo": n_trafo, "n_trafo_nameplate": n_trafo_nameplate,
                         "n_edge_skipped": n_edge_skipped,
                         "n_dedup_merged": n_dedup_merged,
                         "n_edge_dup_removed": n_edge_dup,
                         "n_site_trafo": n_site_trafo,
                         "n_deenergized": n_deenergized,
                         "n_tie_nis": n_tie_nis,
                         "n_btb_split": n_btb_split,
                         "region_reattribution": rstats}


# ──────────────────────────────────────────────────────────────────────────
#  Generators from OSM plants (nearest substation bus)
# ──────────────────────────────────────────────────────────────────────────
ATTACH_MODES = ("nearest", "site", "cap", "kvfit")


# 出典付き容量を潮流へ届ける（2026-08-10）。既定 ON・無効化は `--no-sourced-capacity`。
USE_SOURCED_CAPACITY = True
_SOURCED_CAP_CACHE = None


def sourced_capacity_index():
    """D層 `docs/data/plants_all.geojson` の `capacity_mw_sourced` を座標キーで引ける形に。

    潮流が読むのは R層 `data/<region>_plants.geojson`（OSM 生抽出）で、出典付き容量は
    D層にしか無い。2026-08-09 の監査（`capacity_provenance_reach_2026-08-09.md`）が
    「CIM が読む plants geojson で `capacity_mw_sourced` を持つのは 0 件」と指摘した穴。
    **R層は書き換えない**（層の分離を守る）— 読む側がD層を引く。

    キーは `apply_capacity_sources.py` と同じ規約（region + 4桁丸め座標）。
    実測で 350/350 が一致し重複キーは 0（kyushu 191・okinawa 10 を含む 227,093MW）。
    """
    global _SOURCED_CAP_CACHE
    if _SOURCED_CAP_CACHE is not None:
        return _SOURCED_CAP_CACHE
    from src.capacity_sources import sourced_capacity_index as _idx
    _SOURCED_CAP_CACHE = {k: float(v["capacity_mw_sourced"])
                          for k, v in _idx().items()
                          if "capacity_mw_sourced" in v}
    return _SOURCED_CAP_CACHE


def _operator_region():
    """operator → 管内 の表。**単一出典は `src/uc/scenario.OPERATOR_REGION`**。

    ここで写しを作ると `_DEFAULT_CAP` が 4 箇所に散った二の舞になるので import する。
    """
    from src.uc.scenario import OPERATOR_REGION
    return OPERATOR_REGION

# ── 介入#24 の**モデル既定**（2026-08-09 オーナー承認で既定ON化・第1段）─────────
# `docs/reports/repair_adoption_decision_2026-08-09.md`。4島すべてで最大負荷率が
# 悪化しない（hokkaido 90.2→86.0% / east 1,668→1,595% / west 1,894→708% /
# okinawa 165.0%据置）。無効化は `--gen-attach nearest`。
#
# **関数 `attach_generators` の引数既定は "nearest" のまま**にしてある。
# what-if 群（whatif_solar_default / whatif_stepdown / overload_vs_topology /
# repair_search の base）は「現行＝最寄り」を**比較のベースライン**として
# 引数なしで呼んでいるので、関数側を動かすと公表済み診断の base が黙って cap に化ける。
# モデルを組む側だけがこの定数を明示的に渡す。
GEN_ATTACH_DEFAULT = "cap"

# ── 介入#26 の**モデル既定**（2026-08-10 オーナー承認で既定ON）─────────────
# 発電機の計上エリアを OSM の operator タグで決める。座標 zone のままだと嶺南原発群
# （大飯4,494MW/高浜3,392MW）と舞鶴火力1,800MW が hokuriku 計上になり出力が1/3になる
# （`docs/reports/zone_attribution_dispatch_2026-08-10.md`）。無効化は `--no-gen-zone-by-operator`。
# **関数 `balance_by_zone` の引数既定は False のまま** — what-if 群は引数なしで呼び、
# 旧挙動を比較のベースラインにしている（#24 と同じ理由）。モデルを組む側だけが渡す。
GEN_ZONE_BY_OPERATOR = True


def bus_incident_mva(net):
    """各バスに集まる枝の合計容量(MVA)。そのバスが受けられる出力の上限を決める。"""
    cap = defaultdict(float)
    for _li, r in net.line.iterrows():
        if not r["in_service"]:
            continue
        kv = float(net.bus.at[int(r["from_bus"]), "vn_kv"])
        mva = float(r["max_i_ka"]) * kv * math.sqrt(3.0) * max(1, int(r.get("parallel") or 1))
        cap[int(r["from_bus"])] += mva
        cap[int(r["to_bus"])] += mva
    for _ti, r in net.trafo.iterrows():
        if not r["in_service"]:
            continue
        s = float(r["sn_mva"]) * max(1, int(r.get("parallel") or 1))
        cap[int(r["hv_bus"])] += s
        cap[int(r["lv_bus"])] += s
    return cap


def class_branch_mva(net):
    """電圧階級ごとの「1回線あたり容量の中央値」を**モデル自身の導体定数から**測る。

    外部の接続電圧表を持ち込まずに「この出力はこの階級では運べない」と言うための基準。
    並列回線は1回線あたりに戻して数える。
    """
    per = defaultdict(list)
    for _li, r in net.line.iterrows():
        if not r["in_service"]:
            continue
        kv = round(float(net.bus.at[int(r["from_bus"]), "vn_kv"]), 1)
        per[kv].append(float(r["max_i_ka"]) * kv * math.sqrt(3.0))
    out = {}
    for kv, v in per.items():
        v.sort()
        out[kv] = v[len(v) // 2]
    return out


def required_kv(p_mw, ladder):
    """その出力を1回線で運べる最下位の電圧階級。無ければ最上位。"""
    for kv, mva in ladder:
        if mva >= p_mw:
            return kv
    return ladder[-1][0] if ladder else 0.0


def attach_generators(net, bus_of, nodes, island, territory=True,
                      attach_mode="nearest", site_km=1.5, kvfit_km=25.0,
                      stats=False, use_sourced=USE_SOURCED_CAPACITY):
    """Attach OSM plants to an in-island substation bus (<=20 km).

    territory: True(既定)=同一 osm_id が複数地域ファイルに存在する場合
    (bbox重なりのスピルオーバー)、1回だけ採用し、領土地域(座標→県→エリア)の
    コピーを優先する。旧挙動は同一発電所を二重付与していた(zone汚染レポート⑤:
    下関火力がkyushu既定容量+chugoku 575MWの二重など、west同名重複750件超)。

    attach_mode: **介入#24**（`docs/MODEL_INTERVENTIONS.md`）。繋ぎ先の選び方。
      nearest 現行既定。最寄りの変電所バス。66kV変電所が桁違いに多いので最寄りは
              ほぼ66kVになり、east は発電容量の53.2%(99GW)が66kVバスに載る
              （姉崎火力3,600MW・川崎火力3,420MWまで66kV接続）。
      site    半径 site_km 以内に複数階級があれば最高電圧へ。
      cap     バスに集まる枝の合計容量がその発電所の出力以上になる最寄りのバスへ。
      kvfit   出力を1回線で運べる最下位の階級を必要階級とし、kvfit_km 以内で
              必要階級以上の最寄りバスへ。
    いずれも**判定基準はモデル自身のデータだけ**から作る（外部の接続電圧表を
    持ち込むと捏造になる）。評価は `docs/reports/repair_search_2026-08-09.md`。

    stats=True で件数だけでなく繋ぎ替え内訳を dict で返す（既定は従来どおり n_gen）。
    """
    import glob
    if attach_mode not in ATTACH_MODES:
        raise ValueError(f"attach_mode は {ATTACH_MODES} のいずれか: {attach_mode!r}")
    # substation bus coords for nearest search
    sub_bus = [(i, bus_of[i], nodes[i]["lat"], nodes[i]["lon"])
               for i in bus_of if nodes[i].get("sub") == 1]
    if not sub_bus:
        return 0
    regions = [r for r, (isl, _f) in ISLAND_OF.items() if isl == island]
    feats = []          # (region, feat) 収集
    for region in regions:
        path = os.path.join(ROOT, "data", f"{region}_plants.geojson")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for feat in data.get("features", []):
            feats.append((region, feat))
    if territory:
        from src.powerflow.region_attribution import area_of_coord
        chosen, extra = {}, []
        for region, feat in feats:
            g = feat.get("geometry") or {}
            oid = (feat.get("properties") or {}).get("osm_id")
            if oid is None or g.get("type") != "Point":
                extra.append((region, feat))
                continue
            cur = chosen.get(oid)
            if cur is None:
                chosen[oid] = (region, feat)
            else:  # 重複コピー: 領土地域のファイル由来を優先(自エリアの整備が最良)
                lon, lat = g["coordinates"][0], g["coordinates"][1]
                home = area_of_coord(lat, lon)
                if region == home and cur[0] != home:
                    chosen[oid] = (region, feat)
        n_dup = len(feats) - len(chosen) - len(extra)
        if n_dup:
            print(f"  plants dedup: 重複コピー{n_dup}件を1回採用に統合"
                  f"(領土地域優先)")
        feats = list(chosen.values()) + extra

    incident = bus_incident_mva(net) if attach_mode == "cap" else {}
    ladder = sorted(class_branch_mva(net).items()) if attach_mode == "kvfit" else []
    # kvfit だけは大型機の引込線に相当する分だけ探索半径を伸ばす（比較の基準は 20km のまま）
    max_km = max(20.0, kvfit_km) if attach_mode == "kvfit" else 20.0

    n_gen = 0
    n_moved = 0
    moved_mw = 0.0
    kv_hist = defaultdict(float)
    zone_src: dict[int, str] = {}
    sourced = sourced_capacity_index() if use_sourced else {}
    n_sourced = 0
    sourced_mw = 0.0
    for k, (region, feat) in enumerate(feats):
        g = feat.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        lon, lat = g["coordinates"][0], g["coordinates"][1]
        props = feat.get("properties", {})
        try:
            cap = float(props.get("capacity_mw"))
        except (TypeError, ValueError):
            cap = None
        fuel = props.get("fuel_type") or props.get("plant:source") or "unknown"
        if not isinstance(fuel, str) or fuel.startswith("http"):
            fuel = "unknown"
        # 出典付き容量があればそれを正とする（0 も「発電していない」という出典値として
        # 尊重する — 大間原発の 0MW 等。既定値へフォールバックさせない）
        srcd = sourced.get(f"{region}:{lon:.4f},{lat:.4f}") if sourced else None
        if srcd is not None:
            cap = srcd
            n_sourced += 1
            sourced_mw += cap
        elif cap is None or cap <= 0:
            cap = _DEFAULT_CAP.get(fuel, _CAP_FALLBACK)

        cands = sorted(((_haversine_km(lat, lon, s[2], s[3]), s) for s in sub_bus),
                       key=lambda t: t[0])
        near = [(d, s) for d, s in cands if d <= max_km]
        # 現行の繋ぎ先＝20km 以内の最寄り。ここに繋がらない発電所はどのモードでも入れない
        base_near = [(d, s) for d, s in near if d <= 20.0]
        if not base_near:
            continue
        base_pick = base_near[0][1][1]
        pick = base_pick
        if attach_mode == "site":
            same_site = [(d, s) for d, s in near if d <= site_km]
            if same_site:            # 同一サイト内で最高電圧、同点なら近い方
                pick = max(same_site,
                           key=lambda t: (float(net.bus.at[t[1][1], "vn_kv"]), -t[0]))[1][1]
        elif attach_mode == "cap":
            ok = next((s for d, s in near if incident.get(s[1], 0.0) >= cap), None)
            pick = ok[1] if ok is not None else \
                max(near, key=lambda t: incident.get(t[1][1], 0.0))[1][1]
        elif attach_mode == "kvfit":
            need = required_kv(cap, ladder)
            ok = next((s for d, s in near
                       if float(net.bus.at[s[1], "vn_kv"]) >= need - 0.5), None)
            pick = ok[1] if ok is not None else \
                max(near, key=lambda t: (float(net.bus.at[t[1][1], "vn_kv"]), -t[0]))[1][1]
        if pick != base_pick:
            n_moved += 1
            moved_mw += cap
        kv_hist[round(float(net.bus.at[pick, "vn_kv"]), 1)] += cap
        try:
            gi = pp.create_gen(net, bus=int(pick), p_mw=cap, vm_pu=1.0,
                               name=str(props.get("name") or f"{region}_gen_{k}"),
                               type=fuel, max_p_mw=cap, min_p_mw=0.0,
                               max_q_mvar=0.5 * cap, min_q_mvar=-0.3 * cap)
            n_gen += 1
            # 介入#26 の材料: operator タグから管内を引いて持たせる（使うかは別判断）。
            # 嶺南原発群(大飯/高浜)は立地=福井(hokuriku)だが関西電力の電源。
            # 表は src/uc/scenario.OPERATOR_REGION（既存の単一出典）。
            op = props.get("operator")
            if isinstance(op, str) and op:
                for k_op, reg in _operator_region().items():
                    if k_op in op:
                        zone_src[gi] = reg
                        break
        except (ValueError, TypeError):
            pass
    if zone_src:
        net.gen["zone_src"] = net.gen.index.map(lambda i: zone_src.get(int(i)))
    if not stats:
        return n_gen
    tot = sum(kv_hist.values()) or 1.0
    return {"n_gen": n_gen, "n_moved": n_moved, "moved_mw": round(moved_mw, 1),
            "attach_mode": attach_mode,
            "n_sourced_cap": n_sourced, "sourced_cap_mw": round(sourced_mw, 1),
            "ladder_note": (" / ".join(f"{kv:.0f}kV {mva:,.0f}MVA" for kv, mva in ladder)
                            if ladder else None),
            "kv_share": {str(k): round(v / tot, 4) for k, v in sorted(kv_hist.items())},
            "share_at_or_below_110kv": round(
                sum(v for k, v in kv_hist.items() if k <= 110.0) / tot, 4)}


# ──────────────────────────────────────────────────────────────────────────
#  Load allocation: substation buses only, per region, voltage-class weighted
# ──────────────────────────────────────────────────────────────────────────
def allocate_loads(net, cfg, pref_gwh=None, point_demand=None):
    """zone別ピーク需要をバスへ空間配分する。

    pref_gwh: None(既定)=従来のzone一様×電圧階級重み(正典比較性維持)。
      {(zone, pref): 年間需要GWh}(src.powerflow.pref_demand.pref_zone_gwh)を
      渡すと、zone内をまず県別実需要シェアで配り、県内を電圧重みで配る
      (需要空間配分の細分化 2026-07-09 —
       docs/reports/a_plan_east_ac_regression_2026-07-08.md の中期対応(a))。
      zone合計は従来どおり regional_peak_demand_mw がアンカー。
      帳簿は net._pref_demand_ledger に残す。

    point_demand: **介入#30(L_DBハイブリッド 2026-08-17)**。{bus: 観測平均MW}
      (src.powerflow.point_demand.match_buses の出力)。観測地点はその実測値で
      ピン留めし、zone残余(target−Σpinned)を非ピンバスへ従来重みで配る。
      zone合計アンカーは不変。None=従来(③無効化)。帳簿=net._point_demand_ledger。
    """
    peak = cfg["regional_peak_demand_mw"]
    lf = cfg.get("load_factor", 0.85)
    pf = cfg.get("power_factor", 0.95)
    vw = cfg.get("voltage_weights", {})
    tan_phi = math.tan(math.acos(pf))
    total = 0.0
    is_sub = net.bus["type"] != "n"

    pinned = dict(point_demand or {})
    pinned_by_zone: dict = {}
    if pinned:
        for b, p in pinned.items():
            z = net.bus.at[b, "zone"]
            pinned_by_zone[z] = pinned_by_zone.get(z, 0.0) + p
            pp.create_load(net, bus=b, p_mw=p, q_mvar=p * tan_phi,
                           name=f"load_obs_{b}")
            total += p
        net._point_demand_ledger = {
            "n_pinned": len(pinned),
            "pinned_mw": round(sum(pinned.values()), 1),
            "by_zone": {z: round(v, 1) for z, v in pinned_by_zone.items()},
        }

    def _vweight(b):
        vn = float(net.bus.at[b, "vn_kv"])
        key = int(round(vn))
        return vw.get(key) or vw.get(min(
            [k for k in vw if isinstance(k, (int, float)) and k > 0] or [0],
            key=lambda k: abs(k - vn)), 0.5)

    def _spread(idxs, target):
        nonlocal total
        weights = [_vweight(b) for b in idxs]
        tw = sum(weights) or len(idxs)
        for b, w in zip(idxs, weights):
            p = target * (w / tw)
            pp.create_load(net, bus=b, p_mw=p, q_mvar=p * tan_phi,
                           name=f"load_{b}")
            total += p

    pref_of_bus = None
    ledger = None
    if pref_gwh is not None:
        from src.powerflow.pref_demand import load_pref_demand
        from src.powerflow.region_attribution import prefecture_of
        _pref_cache = {}

        def pref_of_bus(b):
            lon, lat = _bus_lonlat(net, b)
            if lon is None:
                return None
            key = (round(lat, 4), round(lon, 4))
            if key not in _pref_cache:
                _pref_cache[key] = prefecture_of(lat, lon)
            return _pref_cache[key]

        _national = {p: rec["total_gwh"]
                     for p, rec in load_pref_demand()["prefectures"].items()}
        ledger = {"mode": "pref_demand_fy2024", "zones": {}}

    for zone, grp in net.bus.groupby("zone"):
        target = peak.get(zone, 0) * lf
        if target <= 0:
            continue
        # 介入#30: 観測ピン留め分をzone目標から控除(アンカー不変)。
        # 観測合計が目標を超えたら残余0(超過は帳簿で開示・ピン値は削らない)
        if pinned_by_zone.get(zone):
            target = max(target - pinned_by_zone[zone], 0.0)
            if target == 0.0:
                continue
        idxs = [b for b in grp.index if is_sub.get(b, False) and b not in pinned]
        if not idxs:
            idxs = [b for b in grp.index if b not in pinned] or list(grp.index)
        if pref_gwh is None:
            _spread(idxs, target)
            continue
        # --- 県別実需要シェアで zone 内を配る ---
        by_pref = {}
        for b in idxs:
            by_pref.setdefault(pref_of_bus(b), []).append(b)
        gwh_of = {}
        for pref in by_pref:
            if pref is None:
                gwh_of[pref] = 0.0  # 座標欠損(想定外) — 後段でzone平均を充当
            else:
                # (zone,pref) 実需要。表に無いペア(旧zoneラベル等)は県全体値で代用(開示)
                gwh_of[pref] = pref_gwh.get((zone, pref),
                                            _national.get(pref, 0.0))
        pos = [v for v in gwh_of.values() if v > 0]
        fill = (sum(pos) / len(pos)) if pos else 1.0
        gwh_of = {p: (v if v > 0 else fill) for p, v in gwh_of.items()}
        tg = sum(gwh_of.values())
        zl = {}
        for pref, buses in by_pref.items():
            t_pref = target * (gwh_of[pref] / tg)
            _spread(buses, t_pref)
            zl[str(pref)] = {"n_bus": len(buses),
                             "gwh": round(gwh_of[pref], 1),
                             "target_mw": round(t_pref, 1)}
        ledger["zones"][zone] = zl
    if ledger is not None:
        net._pref_demand_ledger = ledger
    return total


# ──────────────────────────────────────────────────────────────────────────
#  Per-component slack + balance, then solve
# ──────────────────────────────────────────────────────────────────────────
def add_per_component_slacks(net):
    """Every connected component (over in-service lines+trafos) needs a slack.
    Prefer the bus carrying the largest generator; else the highest-kv,
    highest-degree substation. Returns (n_components, n_slack, n_synth_slack)."""
    g = nx.Graph()
    g.add_nodes_from(net.bus.index)
    for _, r in net.line.iterrows():
        if r["in_service"]:
            g.add_edge(int(r["from_bus"]), int(r["to_bus"]))
    for _, r in net.trafo.iterrows():
        if r["in_service"]:
            g.add_edge(int(r["hv_bus"]), int(r["lv_bus"]))
    gen_bus = set(net.gen["bus"].tolist())
    gen_cap = net.gen.groupby("bus")["max_p_mw"].sum().to_dict()
    deg = dict(g.degree())
    n_slack = n_synth = 0
    comps = list(nx.connected_components(g))
    for comp in comps:
        gens_here = [b for b in comp if b in gen_bus]
        if gens_here:
            slack = max(gens_here, key=lambda b: gen_cap.get(b, 0))
        else:
            # synthetic slack: a real substation, highest kv then highest degree
            subs = [b for b in comp if net.bus.at[b, "type"] != "n"] or list(comp)
            slack = max(subs, key=lambda b: (float(net.bus.at[b, "vn_kv"]),
                                             deg.get(b, 0)))
            n_synth += 1
        pp.create_ext_grid(net, bus=int(slack), vm_pu=1.0,
                           name=f"slack_{slack}")
        n_slack += 1
    return len(comps), n_slack, n_synth


def balance_by_zone(net, cfg, use_zone_src=False):
    """Scale each zone's generation toward its load so the slacks don't carry
    the whole region (keeps the AC solution physical). ext_grid absorbs residual.

    use_zone_src: **介入#26**。発電機の計上エリアを、バスの座標 zone ではなく
    `attach_generators` が operator タグから引いた `zone_src` 列で決める。
    嶺南原発群(大飯4,494MW/高浜3,392MW)は立地=福井県(hokuriku)だが関西電力の電源で、
    座標 zone のままだと hokuriku の容量として数えられ scale=0.20 で**出力が1/3**になる
    (`docs/reports/zone_attribution_dispatch_2026-08-10.md`)。
    `capacity_bridge` が UC 経路向けに同じ上書きを既に行っており(その docstring に
    嶺南の事情が明記されている)、こちらは銘板経路をそれに揃えるもの。
    **需要側の bus.zone は動かさない**（capacity_bridge の設計意図どおり）。
    """
    load_by_zone = defaultdict(float)
    for _, r in net.load.iterrows():
        z = net.bus.at[int(r["bus"]), "zone"]
        load_by_zone[z] += float(r["p_mw"])
    has_src = use_zone_src and "zone_src" in net.gen.columns
    gens_by_zone = defaultdict(list)
    for gi, r in net.gen.iterrows():
        z = net.bus.at[int(r["bus"]), "zone"]
        if has_src:
            src = r.get("zone_src")
            if isinstance(src, str) and src:
                z = src
        gens_by_zone[z].append(gi)
    reserve = 1.0 + cfg.get("reserve_margin", 0.05)
    for z, gis in gens_by_zone.items():
        cap = sum(float(net.gen.at[gi, "max_p_mw"]) for gi in gis)
        if cap <= 0:
            continue
        target = load_by_zone.get(z, 0.0) * reserve
        scale = min(target / cap, 1.0)
        for gi in gis:
            net.gen.at[gi, "p_mw"] = float(net.gen.at[gi, "max_p_mw"]) * scale


def solve_island(net, max_ac_buses):
    """DC always; AC with a prune ladder unless the island exceeds max_ac_buses.

    給電率ガード(ハマり⑩ 2026-07-07): pruneが網の大半を切断した残片の収束を
    「AC成功」と報告する見せかけAC解(east+territoryで served 10.8% を実測)を
    却下する。served < 95% のAC解は採用せず次の段へ。served_frac を ac に記録。"""
    net.bus["vm_pu"] = 1.0
    pre_load = float(net.load.loc[net.load.in_service, "p_mw"].sum())
    net_dc = copy.deepcopy(net)
    dc = run_powerflow(net_dc, "dc")
    ac = {"mode": "ac", "converged": False}
    net_ac = None
    if len(net.bus) <= max_ac_buses:
        for thr in (None, 45.0, 30.0, 20.0):
            net_ac = copy.deepcopy(net)
            if thr is not None:
                from src.powerflow.transforms import prune_dc_infeasible
                try:
                    prune_dc_infeasible(net_ac, angle_threshold=thr)
                except Exception:
                    pass
            ac = run_powerflow(net_ac, "ac")
            if ac["converged"]:
                served = (float(net_ac.res_load.p_mw.sum())
                          if len(net_ac.res_load) else 0.0)
                frac = served / pre_load if pre_load > 0 else 1.0
                ac["served_load_mw"] = round(served, 1)
                ac["served_frac"] = round(frac, 4)
                if frac >= 0.95:
                    break
                ac = {"mode": "ac", "converged": False,
                      "rejected": f"fake_ac served_frac={frac:.3f} thr={thr}"}
    else:
        ac["error"] = f"island too large for AC ({len(net.bus)} > {max_ac_buses}); DC only"
    return net_dc, dc, net_ac, ac


# ──────────────────────────────────────────────────────────────────────────
#  Export per-region GeoJSON slices + summary
# ──────────────────────────────────────────────────────────────────────────
def _bus_lonlat(net, b):
    """(lon, lat) from pandapower 3.x GeoJSON 'geo' column; (None, None) if absent."""
    g = net.bus.at[b, "geo"] if "geo" in net.bus.columns else None
    if not g:
        return None, None
    try:
        coords = json.loads(g)["coordinates"]
        return float(coords[0]), float(coords[1])
    except (ValueError, KeyError, IndexError, TypeError):
        return None, None


def export_region(net, region, geom, mode, out_dir):
    buses = []
    region_bus = set()
    for b in net.bus.index:
        if not net.bus.at[b, "in_service"] or net.bus.at[b, "zone"] != region:
            continue
        x, y = _bus_lonlat(net, b)
        if x is None or (x == 0 and y == 0):
            continue
        region_bus.add(b)
        vm = float(net.res_bus.at[b, "vm_pu"]) if b in net.res_bus.index else float("nan")
        va = float(net.res_bus.at[b, "va_degree"]) if b in net.res_bus.index else float("nan")
        if not (math.isfinite(vm) and math.isfinite(va)):
            continue
        buses.append({"type": "Feature",
                      "geometry": {"type": "Point", "coordinates": [x, y]},
                      "properties": {"name": str(net.bus.at[b, "name"]),
                                     "vn_kv": round(float(net.bus.at[b, "vn_kv"]), 1),
                                     "vm_pu": round(vm, 4), "va_deg": round(va, 2)}})
    lines = []
    for li in net.line.index:
        if not net.line.at[li, "in_service"]:
            continue
        fb, tb = int(net.line.at[li, "from_bus"]), int(net.line.at[li, "to_bus"])
        zf, zt = net.bus.at[fb, "zone"], net.bus.at[tb, "zone"]
        if region not in (zf, zt):
            continue
        fx, fy = _bus_lonlat(net, fb); tx, ty = _bus_lonlat(net, tb)
        if fx is None or tx is None:
            continue
        load = float(net.res_line.at[li, "loading_percent"]) if li in net.res_line.index and "loading_percent" in net.res_line.columns else 0.0
        p = float(net.res_line.at[li, "p_from_mw"]) if li in net.res_line.index and "p_from_mw" in net.res_line.columns else 0.0
        load = load if math.isfinite(load) else 0.0
        p = p if math.isfinite(p) else 0.0
        coords = geom.get((_k5(fy, fx), _k5(ty, tx))) or [[fx, fy], [tx, ty]]
        coords = [[fx, fy]] + list(coords)[1:-1] + [[tx, ty]] if len(coords) > 2 else [[fx, fy], [tx, ty]]
        lines.append({"type": "Feature",
                      "geometry": {"type": "LineString", "coordinates": coords},
                      "properties": {"name": str(net.line.at[li, "name"]),
                                     "loading_pct": round(min(load, 200), 1),
                                     "p_mw": round(p, 1),
                                     "tie": zf != zt}})
    # transformers as short links (so stepped sites don't look 'floating')
    for ti in net.trafo.index:
        if not net.trafo.at[ti, "in_service"]:
            continue
        hb, lb = int(net.trafo.at[ti, "hv_bus"]), int(net.trafo.at[ti, "lv_bus"])
        if region not in (net.bus.at[hb, "zone"], net.bus.at[lb, "zone"]):
            continue
        hx, hy = _bus_lonlat(net, hb); lx, ly = _bus_lonlat(net, lb)
        if hx is None or lx is None or (abs(hx - lx) < 1e-6 and abs(hy - ly) < 1e-6):
            continue
        ld = float(net.res_trafo.at[ti, "loading_percent"]) if ti in net.res_trafo.index and "loading_percent" in net.res_trafo.columns else 0.0
        ld = ld if math.isfinite(ld) else 0.0
        lines.append({"type": "Feature",
                      "geometry": {"type": "LineString", "coordinates": [[hx, hy], [lx, ly]]},
                      "properties": {"name": str(net.trafo.at[ti, "name"]),
                                     "loading_pct": round(min(ld, 200), 1),
                                     "p_mw": 0.0, "tie": False, "trafo": True}})
    tag = mode
    json.dump({"type": "FeatureCollection", "features": buses},
              open(f"{out_dir}/{region}_{tag}_buses.geojson", "w"),
              separators=(",", ":"), allow_nan=False)
    json.dump({"type": "FeatureCollection", "features": lines},
              open(f"{out_dir}/{region}_{tag}_lines.geojson", "w"),
              separators=(",", ":"), allow_nan=False)
    return len(buses), len(lines)


def region_vm(net, region):
    idx = [b for b in net.bus.index if net.bus.at[b, "in_service"]
           and net.bus.at[b, "zone"] == region and b in net.res_bus.index]
    vm = [float(net.res_bus.at[b, "vm_pu"]) for b in idx
          if math.isfinite(float(net.res_bus.at[b, "vm_pu"]))]
    if not vm:
        return {}
    return {"vm_min": round(min(vm), 4), "vm_max": round(max(vm), 4), "n": len(vm)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="*", default=None)
    ap.add_argument("--output-dir", default=OUT_DEFAULT)
    ap.add_argument("--max-ac-buses", type=int, default=7000,
                    help="skip AC attempt for islands larger than this (DC only). "
                         "既定7000: east(6205バス)は全規模ACが収束する実績"
                         "(2026-07-04, v4銘板入り・vm 0.83-1.02pu)。west(10193)は"
                         "AC『収束』が fragmentation による見せかけと確定済みのため"
                         "(docs/WEST_AC_ANALYSIS.md)意図的に閾値の外=誠実にDC")
    ap.add_argument("--gen-attach", choices=ATTACH_MODES, default=GEN_ATTACH_DEFAULT,
                    help="発電機の繋ぎ先の選び方(**介入#24**)。**既定 cap**"
                         "(2026-08-09 既定ON化)=バスに集まる枝の合計容量がその発電所の"
                         "出力以上になる最寄りのバスへ。旧既定 nearest は最寄りの変電所"
                         "バスで、66kV変電所が桁違いに多いため east は発電容量の"
                         "53.2%%(99GW)が66kVバスに載り姉崎火力3,600MWまで66kV接続だった。"
                         "kvfit=出力を1回線で運べる階級以上の最寄り、site=同一サイトの"
                         "最高電圧。判定基準はモデル自身の導体定数だけから作る。"
                         "評価=docs/reports/repair_search_2026-08-09.md・判断="
                         "repair_adoption_decision_2026-08-09.md。"
                         "**無効化=--gen-attach nearest**")
    ap.add_argument("--sourced-capacity", action=argparse.BooleanOptionalAction,
                    default=USE_SOURCED_CAPACITY,
                    help="出典付き容量(D層 docs/data/plants_all.geojson の "
                         "`capacity_mw_sourced`)を OSM 生値・既定値より優先する(**既定ON**)。"
                         "2026-08-09 の監査で「出典DBの値が潮流/CIM に届いていない」"
                         "穴が見つかったのを塞ぐもの。R層は書き換えず読む側がD層を引く。"
                         "実測 350/350 一致・west 247件110GW / east 62件87GW。"
                         "出典値 0(大間原発=運転開始未定 等)は 0 のまま尊重する。"
                         "無効化=--no-sourced-capacity")
    ap.add_argument("--gen-zone-by-operator", action=argparse.BooleanOptionalAction,
                    default=GEN_ZONE_BY_OPERATOR,
                    help="発電機の計上エリアを operator タグで決める(**介入#26**・"
                         "**既定ON**/2026-08-10)。"
                         "既定はバスの座標zoneなので、嶺南原発群(大飯4,494MW/高浜3,392MW)は"
                         "立地=福井(hokuriku)として数えられ scale=0.20 で**出力が1/3**になる。"
                         "表は src/uc/scenario.OPERATOR_REGION(既存の単一出典)。"
                         "需要側の bus.zone は動かさない。"
                         "評価=docs/reports/zone_attribution_dispatch_2026-08-10.md。"
                         "**無効化=--no-gen-zone-by-operator**")
    ap.add_argument("--default-cap", nargs="*", metavar="FUEL=MW", default=None,
                    help="燃料別の既定容量を上書き(**介入#25**)。`capacity_mw` が無い"
                         "発電所はこの値で埋まる=**出典のない合成容量**。既定は "
                         "solar=10.0 だが OSM 実容量の中央値は 0.10MW で 100倍の水増し"
                         "(太陽光180GW=実績ピークの318%%)。`balance_by_zone` は容量比例で"
                         "配分するので、この既定値が**そのままゾーン内の空間配分**になる。"
                         "例: --default-cap solar=0.10。評価="
                         "docs/reports/repair_search_2026-08-09.md。無効化=本引数を省略")
    ap.add_argument("--pref-demand", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="需要空間配分の細分化: zone内を県別実需要シェア"
                         "(電力調査統計FY2024・出典付き)で配ってから電圧重み。"
                         "既定ON(2026-07-10 介入#19既定化)。--no-pref-demand="
                         "従来のzone一様(回帰比較用)。"
                         "A案(territory=True)とセットで需要地理が閉じる "
                         "(docs/reports/a_plan_east_ac_regression_2026-07-08.md)")
    ap.add_argument("--reactive-comp", nargs="?", type=float, const=-1.0,
                    default=-1.0, metavar="FACTOR",
                    help="負荷バスに容量性シャント(コンデンサバンク)を付与し無効"
                         "電力を局所供給(実配電用変電所のコンデンサをモデル化)。"
                         "FACTOR=局所供給率(省略時=config)。"
                         "既定ON(2026-07-10 介入#20既定化)。east full ACの"
                         "非収束(電圧崩壊)を解消 "
                         "(docs/reports/east_network_reactive_2026-07-09.md)")
    ap.add_argument("--no-reactive-comp", action="store_const", const=None,
                    dest="reactive_comp",
                    help="無効電力補償を無効化(従来挙動・回帰比較用)")
    ap.add_argument("--dedup-nodes", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="bbox重なりの二重抽出を除去(B案): 重複ノード(同一座標+kv)を"
                         "1バスへ+重複エッジ(同一バス対+同一経路)を1本へ(parはmax保存)。"
                         "除去であって接続追加でない。既定ON(2026-07-10 介入#21既定化)。"
                         "--no-dedup-nodes=従来挙動(回帰比較用)。west断片化2531→544成分・"
                         "線の二重計上を是正 "
                         "(docs/reports/west_fragmentation_rootcause_2026-07-09.md)")
    ap.add_argument("--point-demand", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="介入#30 L_DB地点需要ピン留め: 観測地点(変圧器バンク潮流実績の"
                         "需要ビュー・src/powerflow/point_demand)の年平均MWをバスに"
                         "ピン留めし、zone残余を従来配分(アンカー不変)。"
                         "**既定ON(2026-08-17 オーナー承認)**。マッチャー第2ラウンドで"
                         "カバレッジMW比68%%(30バス)・再A/Bで害なし+沖縄微改善"
                         "(point_demand_ab_round2_2026-08-17.json)。"
                         "無効化=--no-point-demand")
    ap.add_argument("--synthetic-ties-live", action=argparse.BooleanOptionalAction,
                    default=False,
                    help="介入#31(2026-08-17 オーナー承認・既定=非通電): 合成連系タイ"
                         "(OCCTO直線タイ7本)とDC連系枝(阿南紀北)を in_service=False で"
                         "建てる。実連系線の実線形と二重計上(kv=0が500kV継承の低Z並列路)"
                         "だったため。A/B=tie_duplication_ab_2026-08-17.json(観測整合は"
                         "不変・潮流は実線へ転流)。東北東京のみ切れ端未縫合のため通電維持"
                         "(KEEP_LIVE_TIES)。本引数=Trueで従来挙動(回帰比較用)")
    ap.add_argument("--btb-split", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="介入#32(2026-08-19・既定ON): 南福光BTBのAC素通し切断。"
                         "中部北陸間はBTB(非同期)連系で交流直通は実在しないが、"
                         "モデルは南福光連系所バスで越美幹線(中部)と加賀福光線・"
                         "能越幹線(北陸)が合流しAC素通し(実績断面575MW・UC断面"
                         "1,210MW vs 運用容量中央値300MW)だった。バスを両側に分割"
                         "する。無効化=--no-btb-split(回帰比較用)")
    ap.add_argument("--site-trafos", action=argparse.BooleanOptionalAction,
                    default=False,
                    help="介入#22 サイト内変圧器リンク: 同名変電所(正規化名一致+"
                         "0.6km以内)の異電圧階級を変圧器で連結。従来は同一座標(≈1m)"
                         "のみで同一サイトの階級ヤードが未連結だった(東京城南チェーン"
                         "低電圧・west T-gapの主因)。既定OFF(正典比較性)")
    ap.add_argument("--deenergize-unbuilt", action=argparse.BooleanOptionalAction,
                    default=False,
                    help="介入#23 未供用線の正直化: 建設済み・供用開始前の線"
                         "(data/reference/not_in_service_lines.json・出典必須)を"
                         "in_service=Falseで建てる。初例=大間幹線(運転開始未定)。"
                         "既定OFF")
    args = ap.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    for spec in (args.default_cap or []):
        fuel, _, val = spec.partition("=")
        if not _ or not fuel:
            raise SystemExit(f"--default-cap は FUEL=MW 形式: {spec!r}")
        old = _DEFAULT_CAP.get(fuel, _CAP_FALLBACK)
        _DEFAULT_CAP[fuel] = float(val)
        # 介入#25 の帳簿: 既定値を動かしたら必ず出す（合成容量の量が変わる）
        print(f"  介入#25 default-cap: {fuel} {old} → {float(val)} MW")

    with open(BUILT, encoding="utf-8") as f:
        db = json.load(f)
    nodes, edges = db["nodes"], db["edges"]
    cfg = load_demand_config()
    pref_gwh = None
    if args.pref_demand:
        from src.powerflow.pref_demand import pref_zone_gwh
        pref_gwh, pw_ledger = pref_zone_gwh(nodes)
        print(f"県別需要重み: {pw_ledger['title']} "
              f"({pw_ledger['n_pref_weighted']}県, split={list(pw_ledger['split_prefs'])})")

    targets = args.islands or ["hokkaido", "east", "west", "okinawa"]
    summary = {"_meta": {"source": "docs/data/built/all.json",
                         "n_nodes": len(nodes), "n_edges": len(edges),
                         "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
                         "scale": "full (no voltage-class reduction)"},
               "islands": {}, "regions": {}}

    for island in targets:
        t0 = time.time()
        freq = ISLAND_FREQ[island]
        geom = {}
        net, bus_of, bstats = build_island_net(
            island, nodes, edges, freq, geom, dedup_nodes=args.dedup_nodes,
            site_trafos=args.site_trafos,
            deenergize_unbuilt=args.deenergize_unbuilt,
            synthetic_ties_live=args.synthetic_ties_live,
            btb_split=args.btb_split)
        if bstats.get("n_tie_nis"):
            # 介入#31 の帳簿: 何本の合成タイ/DC枝を非通電化したかを必ず出す
            print(f"  介入#31 synthetic-ties: {bstats['n_tie_nis']}本を非通電で建てた"
                  f"(通電維持={sorted(KEEP_LIVE_TIES)})")
        if bstats.get("n_btb_split"):
            # 介入#32 の帳簿: BTB切断で付け替えた枝数を必ず出す
            print(f"  介入#32 btb-split: 南福光BTBを分割"
                  f"(中部側へ{bstats['n_btb_split']}本付け替え)")
        if args.site_trafos or args.deenergize_unbuilt:
            print(f"  介入#22/#23: site_trafo={bstats['n_site_trafo']} "
                  f"deenergized={bstats['n_deenergized']}")
        gstats = attach_generators(net, bus_of, nodes, island,
                                   attach_mode=args.gen_attach, stats=True,
                                   use_sourced=args.sourced_capacity)
        n_gen = gstats["n_gen"]
        if gstats.get("n_sourced_cap"):
            print(f"  出典付き容量: {gstats['n_sourced_cap']:,}件 / "
                  f"{gstats['sourced_cap_mw']:,.0f}MW を出典値で置換")
        if args.gen_attach != "nearest":
            # 介入#24 の帳簿: 何機・何MW を最寄り以外へ繋いだかを必ず出す（既定でも出す）
            print(f"  介入#24 gen-attach={args.gen_attach}: 繋ぎ替え "
                  f"{gstats['n_moved']:,}機/{gstats['moved_mw']:,.0f}MW "
                  f"110kV以下に載る容量 {gstats['share_at_or_below_110kv']:.1%}")
        pinned = None
        if args.point_demand:
            from src.powerflow.point_demand import load_point_demand, match_buses
            pinned, pd_ledger = match_buses(net, load_point_demand())
            # 介入#30 の帳簿: 何地点・何MWをピン留めしたかを必ず出す
            print(f"  介入#30 point-demand: ピン留め {pd_ledger['n_pinned_buses']}バス"
                  f"/{pd_ledger['pinned_mw']}MW (未突合{pd_ledger['n_unmatched']}地点)")
        total_load = allocate_loads(net, cfg, pref_gwh=pref_gwh,
                                    point_demand=pinned)
        if args.reactive_comp is not None:
            from src.powerflow.pipeline import add_reactive_compensation
            rfac = (cfg.get("reactive_compensation_factor", 0.6)
                    if args.reactive_comp == -1.0 else args.reactive_comp)
            n_shunt = add_reactive_compensation(net, factor=rfac)
            print(f"  reactive-comp: factor={rfac} shunt={n_shunt}")
        n_comp, n_slack, n_synth = add_per_component_slacks(net)
        balance_by_zone(net, cfg, use_zone_src=args.gen_zone_by_operator)
        if args.gen_zone_by_operator and "zone_src" in net.gen.columns:
            n_ov = int((net.gen["zone_src"].notna()
                        & (net.gen["zone_src"] != net.gen["bus"].map(net.bus["zone"]))).sum())
            mw_ov = float(net.gen.loc[
                net.gen["zone_src"].notna()
                & (net.gen["zone_src"] != net.gen["bus"].map(net.bus["zone"])),
                "max_p_mw"].sum())
            print(f"  介入#26 gen-zone-by-operator: 計上エリアを変えた "
                  f"{n_ov:,}機 / {mw_ov:,.0f}MW")
        net_dc, dc, net_ac, ac = solve_island(net, args.max_ac_buses)
        net_used = net_ac if ac.get("converged") else net_dc
        mode = "ac" if ac.get("converged") else "dc"

        regions = sorted({r for r, (isl, _f) in ISLAND_OF.items() if isl == island})
        for region in regions:
            nb, nl = export_region(net_used, region, geom, mode, args.output_dir)
            vm = region_vm(net_used, region)
            summary["regions"][region] = {
                "island": island, "solved_mode": mode,
                "ac_converged": bool(ac.get("converged")),
                "dc_converged": bool(dc.get("converged")),
                "vm_min": vm.get("vm_min"), "vm_max": vm.get("vm_max"),
                "n_buses": vm.get("n"), "n_buses_exported": nb, "n_lines_exported": nl,
            }
        summary["islands"][island] = {
            "frequency_hz": freq, **bstats, "n_gen": n_gen,
            "total_load_mw": round(total_load, 1),
            "n_components": n_comp, "n_slack": n_slack, "n_synthetic_slack": n_synth,
            "ac_converged": bool(ac.get("converged")),
            "ac_solver": ac.get("solver"), "ac_error": ac.get("error"),
            "dc_converged": bool(dc.get("converged")),
            "ac_vm_min": ac.get("vm_pu_min"), "ac_vm_max": ac.get("vm_pu_max"),
            "ac_max_loading_pct": ac.get("max_loading_pct"),
            "dc_max_loading_pct": dc.get("max_loading_pct"),
            "ac_total_loss_mw": ac.get("total_loss_mw"),
            "solve_seconds": round(time.time() - t0, 1),
        }
        print(f"[{island:9s}] f={freq} buses={bstats['n_bus']} lines={bstats['n_line']} "
              f"trafo={bstats['n_trafo']} gen={n_gen} comps={n_comp} "
              f"AC={'OK' if ac.get('converged') else 'FAIL'} DC={'OK' if dc.get('converged') else 'FAIL'} "
              f"vm=[{ac.get('vm_pu_min')},{ac.get('vm_pu_max')}] "
              f"maxload={ac.get('max_loading_pct')} {time.time()-t0:.0f}s", flush=True)

    with open(f"{args.output_dir}/summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"done -> {args.output_dir}")


if __name__ == "__main__":
    main()
