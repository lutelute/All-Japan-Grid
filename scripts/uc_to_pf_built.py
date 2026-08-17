#!/usr/bin/env python3
"""UC 24h → built正典(v4銘板)全規模潮流 — 時間別ディスパッチの通年断面検証.

UC→潮流連携の第3経路(モデル別の役割分担):
  - scripts/uc_to_pf.py          : 単一地域 backbone(154kV縮約)。6月実績=24h全時刻AC収束
  - scripts/uc_to_pf_national.py : snapped島 before/after比較(merit vs UC注入)
  - 本スクリプト                  : **built正典・全規模・v4銘板入り**
    (run_full_powerflow_from_db と同一の build_island_net — Ybus v4 と同一モデル)
    で24時間のUCディスパッチを注入して解く。

解法(確定事項に従う):
  east(6,205バス)=AC — 全規模ACの収束実績 2026-07-04(v4銘板・vm 0.83-1.02pu)
  west(10,193バス)=DC — AC「収束」はfragmentationの見せかけと確定済み
                        (docs/WEST_AC_ANALYSIS.md)
  hokkaido/okinawa=AC

契約(docs/UC_HANDOFF.md): ybus_gate PASS の島にのみ注入する。

使い方:
    PYTHONPATH=. .venv/bin/python scripts/uc_to_pf_built.py --islands east --hours 0 11 19
    PYTHONPATH=. .venv/bin/python scripts/uc_to_pf_built.py \
        --islands hokkaido east west okinawa --all-hours

出力: docs/reports/uc_pf_built_<islands>_<hours>_<date>.json
"""
import argparse
import copy
import datetime as _dt
import json
import os
import subprocess
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandapower as pp

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from scripts.run_full_powerflow_from_db import (  # noqa: E402
    BUILT,
    ISLAND_OF,
    add_per_component_slacks,
    allocate_loads,
    attach_generators,
    GEN_ATTACH_DEFAULT,
    build_island_net,
)
from src.powerflow.load_estimator import load_demand_config  # noqa: E402
from src.powerflow.ybus_gate import ybus_gate  # noqa: E402
from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot  # noqa: E402
from src.uc.scenario import build_national_scenario  # noqa: E402
from src.uc.solver import solve_uc  # noqa: E402

ISLAND_FREQ = {"hokkaido": 50.0, "east": 50.0, "west": 60.0, "okinawa": 60.0}
ISLAND_MODE = {"hokkaido": "ac", "east": "ac", "west": "dc", "okinawa": "ac"}
BACKBONE_KV = 154.0

# ── 島境界の連系設備(東西FC・北本) ──────────────────────────────
# PF島モデルは島間連系を持たず、UCの島間融通がslackに落ちる
# (east +4.0% / west -3.3% — docs/reports/east_slack_decomposition_2026-07-07.md)。
# --boundary-injection は UCの連系フローを境界設備バスへ sgen 注入して
# この構造項を解消する。座標はbuiltノード(OSM実体)を名前で解決(捏造回避)。
# weight = 変換所定格MW(interconnections.yaml converters ほか公知:
#   新信濃600+飛騨信濃900(東端=新信濃)・佐久間300・東清水300 = FC計2,100 /
#   北本900 = 旧北本600(上北—函館)+新北本300(今別—北斗)。
#   west側は飛騨信濃の西端=飛騨変換所に900を配分。
#   hokkaido側は函館変換所ノードが無いため北斗へ集約(開示))
BOUNDARY_POINTS = {
    "east": [
        {"pair": ("chubu", "tokyo"), "name": "新信濃変電所", "weight": 1500},
        {"pair": ("chubu", "tokyo"), "name": "佐久間周波数変換所", "weight": 300},
        {"pair": ("chubu", "tokyo"), "name": "東清水変電所", "weight": 300},
        {"pair": ("hokkaido", "tohoku"), "name": "上北変電所", "weight": 600},
        {"pair": ("hokkaido", "tohoku"), "name": "今別変換所", "weight": 300},
    ],
    "west": [
        {"pair": ("chubu", "tokyo"), "name": "新信濃変電所", "weight": 600},
        {"pair": ("chubu", "tokyo"), "name": "飛騨変換所", "weight": 900},
        {"pair": ("chubu", "tokyo"), "name": "佐久間周波数変換所", "weight": 300},
        {"pair": ("chubu", "tokyo"), "name": "東清水変電所", "weight": 300},
    ],
    "hokkaido": [
        {"pair": ("hokkaido", "tohoku"), "name": "北斗変換所", "weight": 900},
    ],
    "okinawa": [],
}


def island_boundary_flows(uc, scn, island_regions):
    """島境界を跨ぐUC連系フローを {pairキー: [24h 正味輸入MW]} で返す。"""
    out = {}
    for fr in getattr(uc, "interconnection_flows", []) or []:
        ic = next((i for i in scn.interconnections
                   if i.id == fr.interconnection_id), None)
        if ic is None:
            continue
        inbound = ic.to_region in island_regions
        outbound = ic.from_region in island_regions
        if inbound == outbound:
            continue          # 島境界を跨がない
        key = tuple(sorted((ic.from_region, ic.to_region)))
        sign = 1.0 if inbound else -1.0
        out[key] = [sign * float(v) for v in fr.flow_mw]
    return out


def setup_boundary_sgens(net, island):
    """境界設備バスを名前で解決し sgen(p=0) を用意する。

    Returns: [{name, pair, share, sgen, bus_name}] (解決不能な点は同pair内で
    重みを再配分し、ledger用に dropped を返す)
    """
    points = BOUNDARY_POINTS.get(island, [])
    resolved, dropped = [], []
    for pt in points:
        mask = net.bus.name.astype(str).str.contains(pt["name"], regex=False)
        mask &= net.bus.in_service
        if not mask.any():
            dropped.append(pt["name"])
            continue
        b = net.bus.loc[mask, "vn_kv"].idxmax()
        resolved.append({**pt, "bus": int(b),
                         "bus_name": str(net.bus.at[b, "name"])})
    for pt in resolved:
        pair_w = sum(p["weight"] for p in resolved if p["pair"] == pt["pair"])
        pt["share"] = pt["weight"] / pair_w if pair_w else 0.0
        pt["sgen"] = int(pp.create_sgen(
            net, bus=pt["bus"], p_mw=0.0, q_mvar=0.0,
            name=f"boundary_{pt['name']}"))
    return resolved, dropped


def build_backbone_net(base, threshold_kv=BACKBONE_KV):
    """built全規模net → backbone計算モデルへの明示的変換(縮約の帳簿つき)。

    オーナー方針(2026-07-05)「計算は縮約も辿るが、リアリティを失わない」の実装:
      - データ資産(built)は触らない。これは計算モデルへの**変換**である
      - backboneバス = vn_kv >= threshold(島の最高階級が閾値未満なら最高階級=okinawa 132)
      - 非backboneバスの load/gen は「同一成分内の最寄り(hop)backboneバス」へ集約
      - backboneを持たない成分(断片)の load/gen は「地理的最寄りbackboneバス」へ集約し
        from_fragment として帳簿に記録 — 断片上の実在電源(磯子・奥清津等)は現実には
        繋がっているため、これは現実の回復であって捏造ではない(帳簿で透明化)
      - 残す枝 = 両端backboneの line/trafo(v4銘板 500/275・275/154 等は温存)
      - 注意: ネット側backboneはトポロジ切断(154kV未満経由の経路は落ちる)。
        回路論的に厳密な縮約は dist/ybus の Kron backbone(別物)

    Returns (net_bb, ledger)
    """
    from collections import deque

    import networkx as nx
    import pandapower.topology as ptop

    from scripts.run_full_powerflow_from_db import _bus_lonlat, _haversine_km

    net = copy.deepcopy(base)
    kvs = net.bus.vn_kv
    thr = threshold_kv
    if not (kvs >= thr).any():
        thr = float(kvs.max())
    bb = set(net.bus.index[(kvs >= thr) & net.bus.in_service])

    g = ptop.create_nxgraph(net, respect_switches=False,
                            include_out_of_service=False)
    # 多源BFS: 各バスに「最も近い(hop) backboneバス」を割り当てる
    owner = {b: b for b in bb if b in g}
    dq = deque(owner)
    while dq:
        u = dq.popleft()
        for v in g[u]:
            if v not in owner:
                owner[v] = owner[u]
                dq.append(v)

    # 断片(backbone無し成分)用: 地理的最寄りbackboneバス
    bb_pos = [(b, *(_bus_lonlat(net, b))) for b in bb]
    bb_pos = [(b, lon, lat) for b, lon, lat in bb_pos
              if lon is not None and lat is not None]

    def geo_nearest(bus):
        lon, lat = _bus_lonlat(net, bus)
        if lon is None or not bb_pos:
            return next(iter(bb)), float("nan")
        best = min(bb_pos, key=lambda p: _haversine_km(lat, lon, p[2], p[1]))
        return best[0], _haversine_km(lat, lon, best[2], best[1])

    ledger = {"threshold_kv": thr, "n_bus_full": int(len(net.bus)),
              "n_backbone_bus": len(bb),
              "loads": {"moved": 0, "moved_mw": 0.0,
                        "from_fragment": 0, "from_fragment_mw": 0.0},
              "gens": {"moved": 0, "moved_mw": 0.0,
                       "from_fragment": 0, "from_fragment_mw": 0.0},
              "cross_zone_moves": 0,
              "fragment_geo_km_max": 0.0}

    zone = net.bus["zone"]
    for elm, key, pcol in (("load", "loads", "p_mw"),
                           ("gen", "gens", "max_p_mw")):
        df = getattr(net, elm)
        for i in df.index:
            b = int(df.at[i, "bus"])
            if b in bb:
                continue
            tgt = owner.get(b)
            frag = tgt is None
            dist_km = 0.0
            if frag:
                tgt, dist_km = geo_nearest(b)
                ledger["fragment_geo_km_max"] = max(
                    ledger["fragment_geo_km_max"],
                    0.0 if dist_km != dist_km else dist_km)
            df.at[i, "bus"] = tgt
            mw = float(df.at[i, pcol] or 0.0)
            ledger[key]["moved"] += 1
            ledger[key]["moved_mw"] += mw
            if frag:
                ledger[key]["from_fragment"] += 1
                ledger[key]["from_fragment_mw"] += mw
            if str(zone.get(b)) != str(zone.get(tgt)):
                ledger["cross_zone_moves"] += 1

    for k in ("loads", "gens"):
        ledger[k]["moved_mw"] = round(ledger[k]["moved_mw"], 1)
        ledger[k]["from_fragment_mw"] = round(ledger[k]["from_fragment_mw"], 1)
    ledger["fragment_geo_km_max"] = round(ledger["fragment_geo_km_max"], 1)

    drop = [int(b) for b in net.bus.index if int(b) not in bb]
    pp.drop_buses(net, drop)          # 参照要素(線/変圧器/旧slack)ごと落ちる
    if len(net.ext_grid):
        net.ext_grid.drop(net.ext_grid.index, inplace=True)

    g2 = ptop.create_nxgraph(net, respect_switches=False,
                             include_out_of_service=False)
    ledger["n_bus_backbone_net"] = int(len(net.bus))
    ledger["n_components_backbone"] = int(
        nx.number_connected_components(g2)) if len(net.bus) else 0
    ledger["n_trafo_kept"] = int(len(net.trafo))
    ledger["n_trafo_nameplate_kept"] = int(
        net.trafo.name.str.contains("@nameplate").sum()) if len(net.trafo) else 0
    return net, ledger


def _git_head():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return "unknown"


def tie_flows_by_pair(net):
    """zone跨ぎ線の潮流を地域対で集計(MW, from側)。"""
    zone = net.bus["zone"]
    out = {}
    if "p_from_mw" not in getattr(net, "res_line", {}):
        return out
    for li in net.line.index:
        if not net.line.at[li, "in_service"] or li not in net.res_line.index:
            continue
        za = zone.get(int(net.line.at[li, "from_bus"]))
        zb = zone.get(int(net.line.at[li, "to_bus"]))
        if not za or not zb or za == zb:
            continue
        key = "->".join(sorted((str(za), str(zb))))
        p = float(net.res_line.at[li, "p_from_mw"])
        if str(za) > str(zb):          # 集計方向を辞書順に正規化
            p = -p
        out[key] = out.get(key, 0.0) + p
    return {k: round(v, 1) for k, v in sorted(out.items())}


# 有界ACチェーン: run_powerflow の緩トレランス長反復フォールバック
# (max_iteration 200-300 / tolerance 0.1-10) は、発散状態で反復を続けると
# macOS Accelerate の cblas_dgemv abort でプロセスごと落ちる
# (west backbone t=13 で決定的に再現・プローブで特定 2026-07-05)。
# 物理的にも緩トレランス解は意味が薄いため、厳トレランス・100反復までに有界化する。
_BOUNDED_AC = [
    {"algorithm": "nr", "init": "dc", "max_iteration": 100,
     "tolerance_mva": 1e-2, "enforce_q_lims": True},
    {"algorithm": "nr", "init": "flat", "max_iteration": 100,
     "tolerance_mva": 1e-2, "enforce_q_lims": True},
    {"algorithm": "nr", "init": "dc", "max_iteration": 100,
     "tolerance_mva": 1e-2},
]


def _bounded_ac(net):
    for so in _BOUNDED_AC:
        try:
            pp.runpp(net, numba=True, **so)
        except Exception:
            continue
        if net.converged:
            return True
    return False


def solve_hour(base, mode):
    """1時刻断面を解く — prune ladder(正典と同じ閾値列)+有界ACチェーン。
    AC不成立は正直に dc_fallback と記録する。

    給電率ガード(ハマり⑩ 2026-07-07): pruneが網の大半を切断しても残片だけで
    「収束」と報告される見せかけAC解(east fullで served 6.2/57.4GW を実測)を
    却下する。served < 95% のAC解は採用せず次の段へ(=silent truncation禁止)。"""
    pre_load = float(base.load.loc[base.load.in_service, "p_mw"].sum())
    if mode == "ac":
        from src.powerflow.transforms import prune_dc_infeasible
        for thr in (None, 45.0, 30.0, 20.0):
            net = copy.deepcopy(base)
            if thr is not None:
                try:
                    prune_dc_infeasible(net, angle_threshold=thr)
                except Exception:
                    pass
            if _bounded_ac(net):
                served = float(net.res_load.p_mw.sum())
                if pre_load <= 0 or served >= 0.95 * pre_load:
                    return net, "ac"
                continue  # 見せかけAC(大半が切断) — 却下して次の段へ
        net = copy.deepcopy(base)
        pp.rundcpp(net)
        return net, "dc_fallback"
    net = copy.deepcopy(base)
    pp.rundcpp(net)
    return net, "dc"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--islands", nargs="+", default=["east"])
    ap.add_argument("--scenario", default="fy2023r2")
    ap.add_argument("--all-hours", action="store_true")
    ap.add_argument("--dump-line-flows", default=None, metavar="DIR",
                    help="各時刻の全線潮流(p_from_mw/loading)をDIRへダンプ"
                         "(powerjp系タイムスライダー用・flows_ts_<island>.json)")
    ap.add_argument("--hours", nargs="*", type=int, default=None,
                    help="解く時刻(0-23)。省略時=島純需要ピーク時刻のみ")
    ap.add_argument("--model", choices=["full", "backbone"], default="full",
                    help="full=全規模(既定) / backbone=縮約計算モデル"
                         "(≥154kV・load/gen集約の帳簿つき・v4銘板温存・全島AC再挑戦)")
    ap.add_argument("--inject-main-comp-only", action="store_true",
                    help="主成分(最大連結成分)外の発電機を in_service=False にして"
                         "から注入する。断片上の発電は物理的に主成分へ送電できない"
                         "ため、容量比例注入が断片に落ちる分(east実測~17GW/59GW)を"
                         "排除する。断片の負荷は synthetic slack 供給のまま"
                         "(=fragment_unserved としてレポート)")
    ap.add_argument("--boundary-injection", action="store_true",
                    help="UCの島間連系フロー(東西FC・北本)を境界設備バスへ"
                         "sgen注入する。PF島が表現できない島間融通の構造項"
                         "(east +4.0%% / west -3.3%%)を解消(2026-07-07)")
    ap.add_argument("--bridge", action="store_true",
                    help="capacity_bridge(容量較正: dedup・出典付き容量パッチ・"
                         "稼働炉リスト)をPF側netへ適用する。UC側は常に同じ"
                         "capacity_patchesを読むため、双方の燃料別容量が一致し"
                         "注入clipが減る(okinawa燃料フリート較正 2026-07-07)。"
                         "既定OFF=07-05正典結果との比較可能性を保つ")
    ap.add_argument("--pref-demand", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="需要空間配分の細分化: zone内を県別実需要シェア"
                         "(電力調査統計FY2024・出典付き)で配ってから電圧重み。"
                         "既定ON(2026-07-10 介入#19既定化)。--no-pref-demand="
                         "従来のzone一様(回帰比較用)。A案の需要地理"
                         "回帰への中期対応(a) "
                         "(docs/reports/a_plan_east_ac_regression_2026-07-08.md)")
    ap.add_argument("--reactive-comp", nargs="?", type=float, const=-1.0,
                    default=-1.0, metavar="FACTOR",
                    help="負荷バスに容量性シャント(コンデンサバンク)を付与して"
                         "無効電力を局所供給する。実配電用変電所のコンデンサを"
                         "モデル化(OSM欠落)。FACTOR=各負荷の無効需要の局所供給率"
                         "(省略時=config reactive_compensation_factor)。"
                         "既定ON(2026-07-10 介入#20既定化)。"
                         "east full ACの非収束(電圧崩壊)を解消 "
                         "(docs/reports/east_network_reactive_2026-07-09.md)")
    ap.add_argument("--no-reactive-comp", action="store_const", const=None,
                    dest="reactive_comp",
                    help="無効電力補償を無効化(従来挙動・回帰比較用)")
    ap.add_argument("--dedup-nodes", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="bbox重なりの二重抽出を除去(B案): ①同一座標+同一電圧の"
                         "重複ノードを1バスに畳む ②同一バス対+同一経路の重複エッジを"
                         "1本に(回線数parはmax保存・本物の複線=par>1単一エッジは不変)。"
                         "座標/経路一致は同一物理点ゆえ除去であって接続追加でない。"
                         "既定ON(2026-07-10 介入#21既定化)。--no-dedup-nodes=従来挙動"
                         "(回帰比較用)。west断片化2531→544成分・線の二重計上を是正 "
                         "(docs/reports/west_fragmentation_rootcause_2026-07-09.md)")
    ap.add_argument("--site-trafos", action=argparse.BooleanOptionalAction,
                    default=False,
                    help="介入#22 サイト内変圧器リンク(同名変電所+0.6km以内の"
                         "異電圧階級を連結)。既定OFF(正典比較性)")
    ap.add_argument("--deenergize-unbuilt", action=argparse.BooleanOptionalAction,
                    default=False,
                    help="介入#23 未供用線の正直化(出典必須リストの線を"
                         "in_service=False)。初例=大間幹線。既定OFF")
    ap.add_argument("--hourly-shunts", action=argparse.BooleanOptionalAction,
                    default=False,
                    help="介入#20の精緻化: 補償シャントを時刻別の地域負荷スケールに"
                         "追従させる(コンデンサバンクの投入/開放運用のモデル化)。"
                         "従来はbase断面で固定張りのため軽負荷時刻に過補償過電圧"
                         "(t=3 vm 2.99)を生んでいた。既定OFF(正典比較性)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    print(f"UC求解中... ({args.scenario})")
    scn = build_national_scenario(scenario=args.scenario)
    uc = solve_uc(scn.to_uc_parameters())
    print(f"  {uc.status}")
    if not uc.is_optimal:
        print("UCがOptimalでないため中止")
        return 1

    built = json.load(open(BUILT))
    cfg = load_demand_config()
    pref_gwh = None
    if args.pref_demand:
        from src.powerflow.pref_demand import pref_zone_gwh
        pref_gwh, pw_ledger = pref_zone_gwh(built["nodes"])
        print(f"県別需要重み: {pw_ledger['title']} "
              f"({pw_ledger['n_pref_weighted']}県, "
              f"split={list(pw_ledger['split_prefs'])})")

    report = {"meta": {"date": _dt.date.today().isoformat(),
                       "git_head": _git_head(), "scenario": args.scenario,
                       "model": "built_full_v4_nameplate",
                       "bridge": bool(args.bridge),
                       "boundary_injection": bool(args.boundary_injection),
                       "pref_demand": bool(args.pref_demand),
                       "reactive_comp": (args.reactive_comp is not None),
                       "dedup_nodes": bool(args.dedup_nodes),
                       "site_trafos": bool(args.site_trafos),
                       "deenergize_unbuilt": bool(args.deenergize_unbuilt),
                       "hourly_shunts": bool(args.hourly_shunts),
                       "builder": "run_full_powerflow_from_db.build_island_net"},
              "islands": {}}
    rc = 0
    for island in args.islands:
        regions = sorted(r for r, (isl, _f) in ISLAND_OF.items() if isl == island)
        mode = "ac" if args.model == "backbone" else ISLAND_MODE[island]
        net_dem = sum(np.asarray(scn.net_demand_r[r]) for r in regions)
        if args.all_hours:
            hours = list(range(24))
        elif args.hours:
            hours = args.hours
        else:
            hours = [int(np.argmax(net_dem))]

        print(f"\n== {island} ({'+'.join(regions)}) mode={mode} "
              f"hours={hours[0]}..{hours[-1]} ({len(hours)}断面) ==")
        t0 = time.monotonic()
        geom = {}
        base, bus_of, bstats = build_island_net(
            island, built["nodes"], built["edges"], ISLAND_FREQ[island], geom,
            dedup_nodes=args.dedup_nodes, site_trafos=args.site_trafos,
            deenergize_unbuilt=args.deenergize_unbuilt)
        if args.site_trafos or args.deenergize_unbuilt:
            print(f"  介入#22/#23: site_trafo={bstats['n_site_trafo']} "
                  f"deenergized={bstats['n_deenergized']}")
        attach_generators(base, bus_of, built["nodes"], island,
                          attach_mode=GEN_ATTACH_DEFAULT)
        bridge_rep = None
        gen_zone_override = None
        if args.bridge:
            from src.uc.capacity_bridge import apply_to_net, load_pf_calibration
            calib = load_pf_calibration(scenario_id=args.scenario)
            bridge_rep = apply_to_net(base, calib)
            gen_zone_override = {int(k): v for k, v
                                 in bridge_rep["zone_override"].items()}
            print(f"  bridge: patched={bridge_rep['patched']} "
                  f"dedup={bridge_rep['dedup_disabled']} "
                  f"retired={bridge_rep['retired']} "
                  f"nuclear={bridge_rep['nuclear_set']}set/"
                  f"{bridge_rep['nuclear_stopped']}stop "
                  f"Δ{bridge_rep['mw_delta']:+,.0f}MW")
        allocate_loads(base, cfg, pref_gwh=pref_gwh)
        pref_ledger = getattr(base, "_pref_demand_ledger", None) if pref_gwh else None
        reactive_rep = None
        if args.reactive_comp is not None:
            from src.powerflow.pipeline import add_reactive_compensation
            rfac = (cfg.get("reactive_compensation_factor", 0.6)
                    if args.reactive_comp == -1.0 else args.reactive_comp)
            n_shunt = add_reactive_compensation(base, factor=rfac)
            q_comp = float(-base.shunt.q_mvar.sum()) if len(base.shunt) else 0.0
            reactive_rep = {"factor": rfac, "n_shunt": n_shunt,
                            "q_comp_mvar": round(q_comp, 1)}
            print(f"  reactive-comp: factor={rfac} shunt={n_shunt} "
                  f"q_comp={q_comp:,.0f}MVar")
        ledger = None
        if args.model == "backbone":
            base, ledger = build_backbone_net(base)
            print(f"  backbone変換: {ledger['n_bus_full']}→"
                  f"{ledger['n_bus_backbone_net']}バス(≥{ledger['threshold_kv']:.0f}kV) "
                  f"load集約{ledger['loads']['moved']}件"
                  f"(断片から{ledger['loads']['from_fragment_mw']:,.0f}MW) "
                  f"gen集約{ledger['gens']['moved']}件"
                  f"(断片から{ledger['gens']['from_fragment_mw']:,.0f}MW) "
                  f"銘板残{ledger['n_trafo_nameplate_kept']}")
        add_per_component_slacks(base)
        boundary_pts, boundary_flows = [], {}
        if args.boundary_injection:
            boundary_pts, bdropped = setup_boundary_sgens(base, island)
            boundary_flows = island_boundary_flows(
                uc, scn, set(regions))
            for pt in boundary_pts:
                print(f"  boundary: {pt['name']} -> {pt['bus_name']} "
                      f"(share {pt['share']:.2f})")
            if bdropped:
                print(f"  boundary: 未解決(重み再配分) {bdropped}")
        print(f"  built: {len(base.bus)}バス trafo={len(base.trafo)} "
              f"(銘板{bstats['n_trafo_nameplate']}) {time.monotonic()-t0:.0f}s")

        n_gen_off = 0
        fragment_load_mw = 0.0
        if args.inject_main_comp_only:
            import networkx as nx
            import pandapower.topology as ptop
            g = ptop.create_nxgraph(base, respect_switches=False,
                                    include_out_of_service=False)
            main = max(nx.connected_components(g), key=len)
            gen_out = ~base.gen.bus.isin(main)
            n_gen_off = int(gen_out.sum())
            base.gen.loc[gen_out, "in_service"] = False
            frag_loads = base.load[~base.load.bus.isin(main)
                                   & base.load.in_service]
            fragment_load_mw = float(frag_loads.p_mw.sum())
            print(f"  主成分限定注入: 断片gen {n_gen_off}台を停止・"
                  f"断片負荷 {fragment_load_mw:,.0f}MW は slack供給のまま"
                  f"(fragment_unserved)")

        gate = ybus_gate(base)
        isl_rep = {"mode": mode, "regions": regions,
                   "model": args.model,
                   "n_bus": int(len(base.bus)),
                   "n_trafo_nameplate": bstats["n_trafo_nameplate"],
                   "backbone_ledger": ledger,
                   "pref_demand_ledger": pref_ledger,
                   "reactive_comp": reactive_rep,
                   "bridge": ({k: v for k, v in bridge_rep.items()
                               if k != "zone_override"}
                              if bridge_rep else None),
                   "boundary_injection": ([
                       {"name": p["name"], "bus": p["bus_name"],
                        "pair": list(p["pair"]),
                        "share": round(p["share"], 3)}
                       for p in boundary_pts] if boundary_pts else None),
                   "inject_main_comp_only": bool(args.inject_main_comp_only),
                   "n_fragment_gen_off": n_gen_off,
                   "fragment_unserved_load_mw": round(fragment_load_mw, 1),
                   "gate": {"pass": bool(gate["pass"]),
                            "cond_max": gate["cond_max"]},
                   "hours": {}}
        report["islands"][island] = isl_rep
        if not gate["pass"]:
            print(f"  × ybus_gate FAIL (cond={gate['cond_max']:.2e}) — "
                  f"契約により注入しない")
            rc = 1
            continue

        n_ok = 0
        ts_dump = {"hours": list(hours), "p_mw": None, "loading": None}             if args.dump_line_flows else None
        for t in hours:
            th = time.monotonic()
            net_t = copy.deepcopy(base)
            fuel_by_zone = {r: uc_snapshot(uc, scn.generators, t, region=r)
                            for r in regions}
            demand = {r: float(scn.net_demand_r[r][t]) for r in regions}
            inj = inject_dispatch_by_zone(net_t, fuel_by_zone, demand,
                                          gen_zone_override=gen_zone_override)
            if args.hourly_shunts and len(net_t.shunt):
                # 介入#20精緻化: シャント(コンデンサバンク)を時刻別の地域負荷
                # スケールに追従(実運用の投入/開放)。base固定張りだと軽負荷時刻に
                # 過補償→過電圧(factor×Q_load(t)の本来意図に合わせる)
                zb = net_t.bus["zone"]
                for si in net_t.shunt.index:
                    z = zb.at[int(net_t.shunt.at[si, "bus"])]
                    sc = inj.get(z, {}).get("load_scale")
                    if sc:
                        net_t.shunt.at[si, "q_mvar"] = \
                            float(net_t.shunt.at[si, "q_mvar"]) * float(sc)
            bnd_mw = {}
            for pt in boundary_pts:
                series = boundary_flows.get(tuple(sorted(pt["pair"])))
                if series is None or t >= len(series):
                    continue
                p_pt = float(series[t]) * pt["share"]
                net_t.sgen.at[pt["sgen"], "p_mw"] = p_pt
                bnd_mw[pt["name"]] = round(p_pt, 1)
            net_s, used = solve_hour(net_t, mode)
            conv = bool(net_s.converged)
            n_ok += int(conv)
            slack = (float(net_s.res_ext_grid.p_mw.sum())
                     if conv and len(net_s.res_ext_grid) else None)
            served = (float(net_s.res_load.p_mw.sum())
                      if conv and len(net_s.res_load) else None)
            pre = float(net_t.load.loc[net_t.load.in_service, "p_mw"].sum())
            hrep = {"solver": used, "converged": conv,
                    "net_demand_mw": round(float(net_dem[t]), 1),
                    "load_scale": {r: inj[r]["load_scale"] for r in regions},
                    "served_load_mw": round(served, 1) if served is not None else None,
                    "served_frac": (round(served / pre, 4)
                                    if served is not None and pre > 0 else None),
                    "slack_abs_mw": round(slack, 1) if slack is not None else None,
                    "solve_s": round(time.monotonic() - th, 1)}
            if bnd_mw:
                hrep["boundary_mw"] = bnd_mw
            inj_issues = {r: {k: v for k, v in
                              (("clipped", inj[r]["injection"]["clipped"]),
                               ("unmatched", inj[r]["injection"]["unmatched"]))
                              if v}
                          for r in regions}
            inj_issues = {r: d for r, d in inj_issues.items() if d}
            if inj_issues:
                hrep["injection_issues"] = inj_issues
            if conv and used == "ac":
                vm = net_s.res_bus.vm_pu
                hrep["vm_min"] = round(float(vm.min()), 4)
                hrep["vm_max"] = round(float(vm.max()), 4)
                hrep["loss_mw"] = round(
                    float(net_s.res_line.pl_mw.sum()
                          + net_s.res_trafo.pl_mw.sum()), 1)
            if conv:
                hrep["tie_mw"] = tie_flows_by_pair(net_s)
            if ts_dump is not None and conv:
                pf = net_s.res_line.p_from_mw.round(1)
                ld = net_s.res_line.loading_percent.round(1)
                if ts_dump["p_mw"] is None:
                    n = len(net_s.line)
                    ts_dump["p_mw"] = [[None]*len(hours) for _ in range(n)]
                    ts_dump["loading"] = [[None]*len(hours) for _ in range(n)]
                    ts_dump["names"] = [str(x) for x in net_s.line.name]
                    ts_dump["in_service"] = [bool(x) for x in net_s.line.in_service]
                hi = list(hours).index(t)
                for li, (pv, lv) in enumerate(zip(pf, ld)):
                    ts_dump["p_mw"][li][hi] = None if pv != pv else float(pv)
                    ts_dump["loading"][li][hi] = None if lv != lv else float(lv)
            isl_rep["hours"][str(t)] = hrep
            print(f"  t={t:2d} {used:12s} conv={conv} "
                  f"demand={float(net_dem[t]):8,.0f}MW "
                  f"slack={hrep['slack_abs_mw']} {hrep['solve_s']}s", flush=True)

        if ts_dump is not None and ts_dump["p_mw"] is not None:
            dd = Path(args.dump_line_flows)
            dd.mkdir(parents=True, exist_ok=True)
            (dd / f"flows_ts_{island}.json").write_text(json.dumps(
                ts_dump, ensure_ascii=False, separators=(",", ":")))
            print(f"  線潮流ダンプ -> {dd}/flows_ts_{island}.json "
                  f"({len(ts_dump['p_mw'])}線×{len(hours)}時刻)")
        isl_rep["n_hours"] = len(hours)
        isl_rep["n_converged"] = n_ok
        isl_rep["all_converged"] = (n_ok == len(hours))
        if not isl_rep["all_converged"]:
            rc = 1

    hours_tag = "allhours" if args.all_hours else "sel"
    out = args.out or (f"docs/reports/uc_pf_built_{'_'.join(args.islands)}_"
                       f"{hours_tag}_{_dt.date.today().isoformat()}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"\n-> {out}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
