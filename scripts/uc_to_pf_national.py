"""UC→全国ゾーナル潮流 — UC断面を同期島ネットへ地域別注入して検証する。

scripts/uc_to_pf.py（単一地域）の全国版。run_national_powerflow.py の島構築
チェーンを踏みつつ、merit-orderの balance_power_by_zone の代わりに
**UC断面のzone別ディスパッチ**（inject_dispatch_by_zone）を注入する —
UCが決めた地域間取引が、実網のtie線潮流として流れるかの検証。

島と解法（確定事項に従う）:
  - east (tohoku+tokyo, 50Hz): AC（prune_dc_infeasibleリトライ付き）
  - west (60Hz 6地域): **DC**（AC非収束の真因=下位網変圧器は確定済み、
    docs/WEST_AC_ANALYSIS.md — --try-ac で再試行は可能だが既定はDC）
  - hokkaido/okinawa: 単一地域なので scripts/uc_to_pf.py の管轄

検証ポイント:
  1. ybus_gate — FAILの島には注入しない（UC_HANDOFF契約）
  2. zone別注入（load=UC純需要スケール、gen=燃料別容量比例）
  3. tie線潮流（zone跨ぎline）を地域対で集計し、UCの連系線フローと比較

使い方:
    python scripts/uc_to_pf_national.py --islands east          # ローカル可
    python scripts/uc_to_pf_national.py --islands west          # サーバー推奨(~12kバス)
    python scripts/uc_to_pf_national.py --islands east west --hour 11

出力: docs/reports/uc_pf_national_<islands>_<date>.json
"""

import argparse
import copy
import datetime as _dt
import json
import math
import os
import subprocess
import sys
import time
import warnings

warnings.filterwarnings("ignore")

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from src.converter.pandapower_builder import PandapowerBuilder  # noqa: E402
from src.powerflow.batch_solve import run_powerflow  # noqa: E402
from src.powerflow.load_estimator import (  # noqa: E402
    estimate_loads,
    load_demand_config,
)
from src.powerflow.national import (  # noqa: E402
    ISLANDS,
    build_island_networks,
    load_interconnections,
)
from src.powerflow.transforms import (  # noqa: E402
    apply_voltage_setpoints,
    fix_topology,
    fix_zero_voltages,
    insert_transformers,
    prune_dc_infeasible,
    scale_line_ratings,
    select_slack_bus,
)
from src.powerflow.ybus_gate import ybus_gate  # noqa: E402
from src.reconstruction.config import ReconstructionConfig  # noqa: E402
from src.reconstruction.isolator import Isolator  # noqa: E402
from src.reconstruction.reconnector import Reconnector  # noqa: E402
from src.uc.pf_injection import inject_dispatch_by_zone, uc_snapshot  # noqa: E402
from src.uc.scenario import build_national_scenario  # noqa: E402
from src.uc.solver import solve_uc  # noqa: E402
from scripts.run_national_powerflow import add_reactive_compensation  # noqa: E402


def _git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return "unknown"


def build_island_base(isl, demand_cfg):
    """島ネットの共通base（builder→トポロジ→需要配置、配分前まで）。

    before/after比較は **このbaseのdeepcopy** から分岐する — 別々にbuildすると
    set走査順（ハッシュシード）で網構成が揺れ、差分が配分以外を拾ってしまう
    （ybus_gateゆらぎの教訓）。
    """
    net = PandapowerBuilder().build(isl["net"]).net
    fix_zero_voltages(net)
    insert_transformers(net)
    iso = Isolator().detect(net)
    Reconnector().reconnect(net, iso, ReconstructionConfig(
        mode="reconnect", max_reconnection_distance_km=5.0))
    fix_topology(net, multi_slack=True)
    select_slack_bus(net)
    estimate_loads(net, region="national", demand_config=demand_cfg)
    inactive = set(net.bus.index[~net.bus["in_service"]])
    if len(net.load) > 0:
        net.load.loc[net.load["bus"].isin(inactive), "in_service"] = False
    return net


def dispatch_uc(net, regions, scn, uc, t, calib):
    """after断面: 容量橋渡し+UC断面のzone別注入。"""
    bridge_rep = None
    zone_override = None
    if calib is not None:
        from src.uc.capacity_bridge import apply_to_net
        bridge_rep = apply_to_net(net, calib)
        zone_override = bridge_rep["zone_override"] or None
    fuel_by_zone = {r: uc_snapshot(uc, scn.generators, t, region=r)
                    for r in regions}
    demand_by_zone = {r: float(scn.net_demand_r[r][t]) for r in regions}
    inj = inject_dispatch_by_zone(net, fuel_by_zone, demand_by_zone,
                                  gen_zone_override=zone_override)
    return inj, bridge_rep


def dispatch_merit(net, regions, scn, t, demand_cfg):
    """before断面: 同一需要（UC断面の地域純需要）でmerit-order配分。

    loadをUC断面へスケールしてから balance_power_by_zone を呼ぶことで、
    before/afterは「同一網・同一需要・配分のみ差」になる。
    """
    from src.powerflow.transforms import balance_power_by_zone
    from src.uc.pf_injection import scale_loads_to

    zone_of_bus = net.bus["zone"]
    load_zone = net.load["bus"].map(zone_of_bus)
    for r in regions:
        scale_loads_to(net, float(scn.net_demand_r[r][t]),
                       load_mask=(load_zone == r))
    balance_power_by_zone(net, demand_cfg)


def finalize_island(net, reactive):
    """配分後の共通仕上げ（ratings→無効電力補償→電圧初期値）。"""
    scale_line_ratings(net)
    n_shunt = add_reactive_compensation(net, reactive)
    net.bus["vm_pu"] = 1.0
    apply_voltage_setpoints(net)
    return n_shunt


def solve_island_mode(net, mode):
    """島をAC（pruneリトライ45/30/20）またはDCで解く。

    Returns: (net_solved, result, prune_threshold or None)
    """
    if mode == "ac":
        res = {"converged": False}
        net_s = None
        for thr in (45.0, 30.0, 20.0):
            net_s = copy.deepcopy(net)
            if prune_dc_infeasible(net_s, angle_threshold=thr) > 0:
                fix_topology(net_s, multi_slack=True)
                select_slack_bus(net_s)
                scale_line_ratings(net_s)
            res = run_powerflow(net_s, "ac")
            if res["converged"]:
                return net_s, res, thr
        return net_s, res, None
    net_s = copy.deepcopy(net)
    return net_s, run_powerflow(net_s, "dc"), None


def export_before_after(net_before, net_after, regions, geom, island_id,
                        mode, outdir):
    """before(merit-order)/after(UC注入)の地域別GeoJSON+差分を出力する。

    両netは同一baseのdeepcopy由来 — bus/line indexの対応が保証されるので、
    after側featureに dvm（vm_after-vm_before）/ dloading を焼き込む。
    ACのprune段数差でin_service集合が僅かに違いうるため、差分は両断面に
    結果がある要素のみ（無い側はnull=マップで灰色）。
    """
    from scripts.export_powerflow_pages import _parse_bus_coords

    os.makedirs(outdir, exist_ok=True)
    written = []
    vm_b = (net_before.res_bus["vm_pu"]
            if "vm_pu" in getattr(net_before, "res_bus", {}) else None)
    ld_b = (net_before.res_line["loading_percent"]
            if "loading_percent" in getattr(net_before, "res_line", {})
            else None)

    def _bus_fc(net, with_diff):
        feats = []
        for idx in net.bus.index:
            if not net.bus.at[idx, "in_service"] or idx not in net.res_bus.index:
                continue
            lon, lat = _parse_bus_coords(net, idx)
            if lon is None or (lon == 0 and lat == 0):
                continue
            vm = float(net.res_bus.at[idx, "vm_pu"])
            if not math.isfinite(vm):
                continue
            props = {
                "name": str(net.bus.at[idx, "name"])[:40],
                "zone": str(net.bus.at[idx, "zone"]),
                "vn_kv": round(float(net.bus.at[idx, "vn_kv"]), 1),
                "vm_pu": round(vm, 4),
            }
            if with_diff:
                props["dvm"] = (
                    round(vm - float(vm_b.at[idx]), 4)
                    if vm_b is not None and idx in vm_b.index
                    and math.isfinite(float(vm_b.at[idx])) else None)
            feats.append({"type": "Feature",
                          "geometry": {"type": "Point",
                                       "coordinates": [lon, lat]},
                          "properties": props})
        return {"type": "FeatureCollection", "features": feats}

    def _line_fc(net, with_diff):
        zone = net.bus["zone"]
        feats = []
        for idx in net.line.index:
            if not net.line.at[idx, "in_service"] or idx not in net.res_line.index:
                continue
            fb = net.line.at[idx, "from_bus"]
            tb = net.line.at[idx, "to_bus"]
            flon, flat = _parse_bus_coords(net, fb)
            tlon, tlat = _parse_bus_coords(net, tb)
            if flon is None or tlon is None:
                continue
            ld = float(net.res_line.at[idx, "loading_percent"])
            p = float(net.res_line.at[idx, "p_from_mw"])
            if not math.isfinite(ld):
                ld = 0.0
            if not math.isfinite(p):
                p = 0.0
            name = str(net.line.at[idx, "name"])
            coords = geom.get(((round(flat, 5), round(flon, 5)),
                               (round(tlat, 5), round(tlon, 5))))
            if not coords:
                coords = [[flon, flat], [tlon, tlat]]
            else:
                # 端点をバス代表座標へ吸着 — バス点はスナップクラスタの
                # 代表座標でOSM実形状の端点から数kmズレうる（大田原で
                # 実測3km、浮きバス問題の真因。オーナー指摘 2026-06-12）。
                # 中間形状はOSMのまま、端点だけ繋いで接続を可視化する
                coords = [[flon, flat]] + list(coords)[1:-1] + [[tlon, tlat]]
            zf, zt = zone.get(fb), zone.get(tb)
            props = {
                "name": name[:60],
                "loading_pct": round(min(ld, 300), 1),
                "p_mw": round(p, 1),
                "tie": bool(isinstance(zf, str) and isinstance(zt, str)
                            and zf != zt),
                "synthetic": name.startswith("recon_line"),
            }
            if with_diff:
                props["dloading"] = (
                    round(ld - float(ld_b.at[idx]), 1)
                    if ld_b is not None and idx in ld_b.index
                    and math.isfinite(float(ld_b.at[idx])) else None)
            feats.append({"type": "Feature",
                          "geometry": {"type": "LineString",
                                       "coordinates": coords},
                          "properties": props})
        # 変圧器も線として描く — insert_transformers は異電圧バス間の
        # OSM線をtrafoに置換（線は削除）するため、描かないと下位網バスが
        # 「浮いて」見える（east 375/west 438バス、8割が66-110kV帯。
        # オーナー指摘 2026-06-12）。電気的接続の可視化として必須
        ldt_b = (net_before.res_trafo["loading_percent"]
                 if hasattr(net_before, "res_trafo")
                 and "loading_percent" in getattr(net_before, "res_trafo", {})
                 else None)
        for idx in net.trafo.index:
            if not net.trafo.at[idx, "in_service"]:
                continue
            hb = net.trafo.at[idx, "hv_bus"]
            lb = net.trafo.at[idx, "lv_bus"]
            hlon, hlat = _parse_bus_coords(net, hb)
            llon, llat = _parse_bus_coords(net, lb)
            if hlon is None or llon is None:
                continue
            if abs(hlon - llon) < 1e-6 and abs(hlat - llat) < 1e-6:
                continue  # 同一座標（構内trafo）は描いても見えない
            ld = 0.0
            if (hasattr(net, "res_trafo") and idx in net.res_trafo.index
                    and "loading_percent" in net.res_trafo.columns):
                v = float(net.res_trafo.at[idx, "loading_percent"])
                ld = v if math.isfinite(v) else 0.0
            props = {
                "name": (f"trafo {net.bus.at[hb, 'vn_kv']:.0f}/"
                         f"{net.bus.at[lb, 'vn_kv']:.0f}kV"),
                "loading_pct": round(min(ld, 300), 1),
                "p_mw": 0.0,
                "tie": False, "synthetic": False, "trafo": True,
            }
            if with_diff:
                props["dloading"] = (
                    round(ld - float(ldt_b.at[idx]), 1)
                    if ldt_b is not None and idx in ldt_b.index
                    and math.isfinite(float(ldt_b.at[idx])) else None)
            feats.append({"type": "Feature",
                          "geometry": {"type": "LineString",
                                       "coordinates": [[hlon, hlat],
                                                       [llon, llat]]},
                          "properties": props})
        return {"type": "FeatureCollection", "features": feats}

    for tag, net in (("before", net_before), ("after", net_after)):
        with_diff = tag == "after"
        for kind, fc in (("buses", _bus_fc(net, with_diff)),
                         ("lines", _line_fc(net, with_diff))):
            path = os.path.join(outdir, f"{island_id}_{tag}_{kind}.geojson")
            with open(path, "w") as f:
                json.dump(fc, f, ensure_ascii=False)
            written.append(os.path.basename(path))
    return written


def tie_flows_by_pair(net) -> dict:
    """zone跨ぎ稼働lineの潮流を「from_zone->to_zone」地域対で合算する。"""
    zone = net.bus["zone"]
    out: dict = {}
    if "p_from_mw" not in getattr(net, "res_line", {}):
        return out
    li = net.line[net.line["in_service"]]
    for idx in li.index:
        zf = zone.get(li.at[idx, "from_bus"])
        zt = zone.get(li.at[idx, "to_bus"])
        if not isinstance(zf, str) or not isinstance(zt, str) or zf == zt:
            continue
        if idx not in net.res_line.index:
            continue
        p = float(net.res_line.at[idx, "p_from_mw"])
        if not np.isfinite(p):
            continue
        # 方向を辞書順の対に正規化（A->B 正、B->A は符号反転して合算）
        key = f"{zf}->{zt}" if zf < zt else f"{zt}->{zf}"
        out[key] = out.get(key, 0.0) + (p if zf < zt else -p)
    return {k: round(v, 1) for k, v in out.items()}


def uc_flows_by_pair(uc, t) -> dict:
    """UC連系線フロー[t]を同じ「地域対（辞書順）」キーへ合算する。"""
    ac_ties, _ = load_interconnections()
    meta = {ic["id"]: ic for ic in ac_ties}
    out: dict = {}
    for icf in uc.interconnection_flows:
        ic = meta.get(icf.interconnection_id)
        if ic is None:  # async (HVDC/FC) は島内tieに現れない
            continue
        if t >= len(icf.flow_mw):
            continue
        p = float(icf.flow_mw[t])
        a, b = ic["from_region"], ic["to_region"]
        key = f"{a}->{b}" if a < b else f"{b}->{a}"
        out[key] = out.get(key, 0.0) + (p if a < b else -p)
    return {k: round(v, 1) for k, v in out.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--islands", nargs="*", default=["east"],
                    help="対象島 (east west)。hokkaido/okinawaはuc_to_pf.pyで")
    ap.add_argument("--scenario", default="fy2023r2")
    ap.add_argument("--hour", type=int, default=None,
                    help="注入時刻 (0-23)。省略時=島内純需要合計ピーク")
    ap.add_argument("--reactive", type=float, default=0.6)
    ap.add_argument("--try-ac", action="store_true",
                    help="westでもACを試す（既定はDC=確定事項）")
    ap.add_argument("--no-bridge", action="store_true",
                    help="容量橋渡し（UC較正のPF側適用）を無効化（比較用）")
    ap.add_argument("--export", action="store_true",
                    help="before(merit-order)/after(UC注入)の地域別GeoJSON+"
                         "差分(dvm/dloading)を docs/data/uc_powerflow/ へ出力")
    ap.add_argument("--export-dir", default="docs/data/uc_powerflow")
    ap.add_argument("--gate-retries", type=int, default=0,
                    help="ybus_gate FAIL時に島網を作り直して再試行する回数。"
                         "west島は同一入力でも構築のハッシュ順により cond が"
                         "4.84e8(PASS)/1.13e9(FAIL)の二値で振れる（台帳⑮⑯）")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    # ── 1. UC ──
    print(f"UC求解中... ({args.scenario})")
    scn = build_national_scenario(scenario=args.scenario)
    uc = solve_uc(scn.to_uc_parameters())
    print(f"  {uc.status}")
    if not uc.is_optimal:
        print("UCがOptimalでないため中止")
        return 1

    # ── 2. 島構築 ──
    print("島ネット構築中...")
    t0 = time.monotonic()
    islands, _async = build_island_networks()
    print(f"  built in {time.monotonic() - t0:.0f}s")
    demand_cfg = load_demand_config()

    calib = None
    if not args.no_bridge:
        from src.uc.capacity_bridge import load_pf_calibration
        calib = load_pf_calibration(scenario_id=args.scenario)

    report = {
        "meta": {
            "date": _dt.date.today().isoformat(),
            "git_head": _git_head(),
            "scenario": args.scenario,
            "reactive": args.reactive,
            "capacity_bridge": not args.no_bridge,
        },
        "islands": {},
    }
    overall_ok = True

    for iid in args.islands:
        if iid not in islands:
            print(f"× 未知の島: {iid}")
            continue
        isl = islands[iid]
        regions = isl["regions"]
        net_dem = sum(np.asarray(scn.net_demand_r[r]) for r in regions)
        t = args.hour if args.hour is not None else int(np.argmax(net_dem))
        print(f"\n== {iid} ({'+'.join(regions)}) t={t} "
              f"純需要 {float(net_dem[t]):,.0f} MW ==")

        # base網は1回だけ構築し、before/afterはdeepcopyで分岐（網構成の
        # ハッシュ順ゆらぎを差分に混ぜないため）。gate FAIL時は島網ごと
        # 作り直してリトライ（cond は構築のハッシュ順で二値に振れる）
        attempt = 0
        while True:
            net_base = build_island_base(isl, demand_cfg)
            net = copy.deepcopy(net_base) if args.export else net_base
            inj, bridge_rep = dispatch_uc(net, regions, scn, uc, t, calib)
            n_shunt = finalize_island(net, args.reactive)
            gate = ybus_gate(net)            # 契約: 流す前に必ず
            if gate["pass"] or attempt >= args.gate_retries:
                break
            attempt += 1
            print(f"  ybus_gate FAIL (cond={gate['cond_max']:.2e}) — "
                  f"島網を再構築してリトライ {attempt}/{args.gate_retries}")
            islands, _async = build_island_networks()
            isl = islands[iid]
        if bridge_rep:
            print(f"  bridge: dedup {bridge_rep['dedup_disabled']}, "
                  f"patched {bridge_rep['patched']}, "
                  f"nuclear {bridge_rep['nuclear_set']}set/"
                  f"{bridge_rep['nuclear_stopped']}stop, "
                  f"Δ{bridge_rep['mw_delta']:+,.0f} MW, "
                  f"zone_override {len(bridge_rep['zone_override'])}")
        tot_inj = sum(x["injection"]["injected_mw"] for x in inj.values())
        print(f"  {len(net.bus)} buses, 注入 {tot_inj:,.0f} MW, "
              f"shunt {n_shunt}")
        for r, x in sorted(inj.items()):
            rep = x["injection"]
            print(f"    {r:9s} inj {rep['injected_mw']:8,.0f} MW "
                  f"(req {rep['requested_mw']:,.0f}, load×{x['load_scale']})")
        print(f"  ybus_gate: {'PASS' if gate['pass'] else 'FAIL'} "
              f"(cond_max={gate['cond_max']:.2e}"
              + (f", retries {attempt}" if attempt else "") + ")")
        isl_rep = {
            "regions": regions, "hour": t,
            "net_demand_mw": round(float(net_dem[t]), 1),
            "n_buses": int(len(net.bus)),
            "capacity_bridge": (
                {k: v for k, v in bridge_rep.items() if k != "zone_override"}
                | {"zone_override_n": len(bridge_rep["zone_override"])}
                if bridge_rep else None),
            "injection": inj,
            "gate": {"pass": gate["pass"], "cond_max": gate["cond_max"]},
        }
        if not gate["pass"]:
            isl_rep["skipped"] = "ybus_gate FAIL — 契約により注入断面を解かない"
            report["islands"][iid] = isl_rep
            overall_ok = False
            continue

        # ── 4. ソルブ（east=AC / west=DC既定） ──
        mode = "ac" if (iid != "west" or args.try_ac) else "dc"
        net_s, res, prune_thr = solve_island_mode(net, mode)
        if prune_thr is not None:
            isl_rep["prune_threshold"] = prune_thr
        isl_rep["mode"] = mode
        isl_rep["converged"] = bool(res["converged"])

        if res["converged"]:
            if mode == "ac":
                zone = net_s.bus["zone"]
                vm_by_zone = {}
                for r in regions:
                    bidx = [i for i in net_s.res_bus.index
                            if zone.get(i) == r
                            and net_s.bus.at[i, "in_service"]]
                    if bidx:
                        vms = net_s.res_bus.loc[bidx, "vm_pu"]
                        vm_by_zone[r] = [round(float(vms.min()), 3),
                                         round(float(vms.max()), 3)]
                isl_rep["vm_by_zone"] = vm_by_zone
                print(f"  AC: converged, vm zone別 {vm_by_zone}")
            else:
                ld = net_s.res_line["loading_percent"]
                isl_rep["line_loading_p95"] = round(
                    float(np.nanpercentile(ld, 95)), 1)
                print(f"  DC: converged, loading p95 "
                      f"{isl_rep['line_loading_p95']}%")
            # ── 5. tie線潮流 vs UC連系線フロー（地域対） ──
            pf_ties = tie_flows_by_pair(net_s)
            uc_ties = {k: v for k, v in uc_flows_by_pair(uc, t).items()
                       if k in pf_ties
                       or all(r in regions for r in k.split("->"))}
            isl_rep["tie_flow_mw"] = {"pf": pf_ties, "uc": uc_ties}
            print("  tie潮流 (PF / UC):")
            for k in sorted(set(pf_ties) | set(uc_ties)):
                print(f"    {k:22s} {pf_ties.get(k, float('nan')):9,.1f} / "
                      f"{uc_ties.get(k, float('nan')):9,.1f} MW")

            # ── 6. before/after エクスポート（--export時） ──
            if args.export:
                print("  before断面 (merit-order, 同一需要) を求解中...")
                dispatch_merit(net_base, regions, scn, t, demand_cfg)
                finalize_island(net_base, args.reactive)
                net_bs, res_b, _thr_b = solve_island_mode(net_base, mode)
                isl_rep["before_converged"] = bool(res_b["converged"])
                if res_b["converged"]:
                    files = export_before_after(
                        net_bs, net_s, regions, isl["geom"], iid, mode,
                        args.export_dir)
                    isl_rep["export"] = files
                    print(f"  exported: {len(files)} files -> "
                          f"{args.export_dir}/")
                else:
                    print("  before断面が非収束 — exportスキップ（after断面"
                          "のレポートは有効）")
        else:
            isl_rep["error"] = str(res.get("error", ""))[:120]
            print(f"  {mode.upper()}: FAILED ({isl_rep['error'][:60]})")
            overall_ok = False
        report["islands"][iid] = isl_rep

    out = args.out or (
        f"docs/reports/uc_pf_national_{'_'.join(args.islands)}_"
        f"{report['meta']['date']}.json")
    with open(out, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {out}")

    # ── マップ用 summary（uc_map.html が読むインデックス） ──
    if args.export:
        spath = os.path.join(args.export_dir, "summary.json")
        prev = {}
        if os.path.exists(spath):  # 島別実行の積み上げに対応
            try:
                with open(spath) as f:
                    prev = json.load(f).get("islands", {})
            except (json.JSONDecodeError, OSError):
                prev = {}
        summary = {
            "meta": report["meta"],
            "islands": prev | {
                iid: {
                    "regions": isl_rep["regions"],
                    "hour": isl_rep["hour"],
                    "mode": isl_rep.get("mode"),
                    "converged": isl_rep.get("converged"),
                    "before_converged": isl_rep.get("before_converged"),
                    "files": isl_rep.get("export", []),
                    "vm_by_zone": isl_rep.get("vm_by_zone"),
                }
                for iid, isl_rep in report["islands"].items()
                if isl_rep.get("export")
            },
        }
        with open(spath, "w") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"Saved: {spath}")

    # uc_runs 索引へベストエフォート記録（正本は上のJSON）
    from src.uc.run_recorder import record_run
    record_run(
        out, kind="pf_national", run_date=report["meta"]["date"],
        git_head=report["meta"]["git_head"], scenario_id=args.scenario,
        status="converged" if overall_ok else "failed",
        summary_json=json.dumps(
            {iid: {"mode": isl.get("mode"),
                   "converged": isl.get("converged"),
                   "n_buses": isl.get("n_buses")}
             for iid, isl in report["islands"].items()},
            ensure_ascii=False),
    )
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
