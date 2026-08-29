"""End-to-end reconstruction power-flow pipeline.

``build_and_solve(region, demand_cfg, ...)`` is the orchestrator that ties
the promoted pieces together: build the topology (legacy nearest-substation
or snapped vertex-graph), convert to pandapower, apply the net transforms
(voltage repair, transformers, slack, topology fix, demand/generation
balance, rating scaling, reactive compensation), then solve DC and AC
(pruning extreme-angle branches until AC converges). Returns
``(net_dc, dc_result, net_ac, ac_result, build_info, snap_geom)``.

Promoted from ``scripts/export_powerflow_pages`` (Phase C pipeline
promotion): this was the last reverse dependency where a script imported
the pipeline from ``examples/``. With it in src, the dependency flows
src <- scripts/examples and the CIM / CPF / N-1 / MATPOWER entry points
import ``build_and_solve`` from here (the script re-exports it for
back-compat).
"""

from __future__ import annotations

import copy

import pandapower as pp

from src.converter.pandapower_builder import PandapowerBuilder
from src.powerflow.batch_solve import run_powerflow
from src.powerflow.legacy_build import build_network_from_geojson
from src.powerflow.load_estimator import estimate_loads
from src.powerflow.snapped_topology import build_network_snapped
from src.powerflow.transforms import (
    apply_voltage_setpoints,
    balance_power,
    fix_topology,
    fix_zero_voltages,
    insert_transformers,
    prune_dc_infeasible,
    reduce_to_backbone,
    scale_line_ratings,
    select_slack_bus,
)
from src.reconstruction.config import ReconstructionConfig
from src.reconstruction.isolator import Isolator
from src.reconstruction.reconnector import Reconnector

# The mainland backbone cut (>=154 kV) does not transfer to every region:
# hokkaido's grid has only 11 branches at 154 kV — its regional
# connectivity layer IS the 66 kV network (591 branches; classes 275/187
# above it), so a 154 kV cut leaves a skeleton (154 buses, ~18% loading).
# Per-region floors apply when the caller asks for the DEFAULT cut; an
# explicit non-default --backbone value is honoured as given.
DEFAULT_BACKBONE_KV = 154.0
REGION_BACKBONE_FLOOR = {"hokkaido": 66.0}


def add_reactive_compensation(net, factor=0.6):
    """Add capacitive shunts at load buses to counter undervoltage.

    factor = fraction of each load bus's reactive demand supplied locally by a
    shunt capacitor (q_mvar < 0 injects Q). Models the reactive compensation
    (capacitor banks / SVC) that real grids deploy but OSM omits, so solved
    voltages are not artificially depressed.
    """
    if factor <= 0 or len(net.load) == 0:
        return 0
    by_bus = net.load[net.load["in_service"]].groupby("bus")["q_mvar"].sum()
    n = 0
    for bus, q in by_bus.items():
        if q > 0:
            pp.create_shunt(net, bus=int(bus), q_mvar=-factor * float(q), p_mw=0.0)
            n += 1
    return n


def add_provisional_infeed(net, min_load_mw=100.0, max_dist_km=40.0):
    """介入#37: 都心給電の必然接続(仮) — オーナー承認 2026-08-30.

    「良い。仮が事実でないかもしれないなら、それを明記しておけば正典として
    良い」(オーナー) — 本関数が作る変圧器は名前に **(仮)・実経路未確認** を
    刻み、全件を台帳(戻り値)に出す。無効化フラグあり。

    背景: 上位系(≥275kV)への変圧器を持たない同階級線クラスタが実負荷を
    抱えるとACの解が存在しない(西の非収束の根因 — 大阪都心154kVクラスタ、
    docs/reports/west_ac_probe2_2026-08-30.md)。関西の開示系統図は実名匿名化
    (転載禁止)で出典つき回復が不可能。論法は推定母線と同じ:
    **負荷が現に供給されている以上、上位系からの給電経路の存在は電気的必然。
    存在のみを主張し、経路・パラメータは(仮)と明記する**。

    検出: 同一電圧階級(60≤kv<275)の線連結クラスタで、(a)どのバスも上位への
    変圧器を持たず (b)クラスタ負荷合計≥min_load_mw のもの。
    接続: クラスタ最大負荷バス → 地理的最近傍の≥275kVバスへ変圧器1台
    (sn=負荷×1.5・vk12%=階級典型値)。**実在の経路が判明したら置換される暫定**。
    max_dist_km(2026-08-30追加): 最近傍がこれより遠い場合は縫合せず台帳のみ
    (capped=True)。動機=誤帰属ノード同士の遠距離縫合の検出面化(神保原104MWが
    誤region由来の榛名へ44km縫合された事例 — 介入#38で帰属自体は是正済みだが、
    将来の同型を電気接続でなく台帳に浮かせる)。

    Returns: ledger list(dict) — kv/load_mw/n_bus/cluster_names/to_upper/
    upper_kv/dist_km/sn_mva。呼び出し側は結果JSONへ全件保存すること。
    """
    import json as _json
    import math as _math
    import networkx as _nx
    from collections import defaultdict

    def _geo(b):
        try:
            g = _json.loads(net.bus.at[b, "geo"])
            return float(g["coordinates"][0]), float(g["coordinates"][1])
        except Exception:  # noqa: BLE001
            return None

    g = _nx.Graph()
    for _, r in net.line[net.line.in_service].iterrows():
        fb, tb = int(r.from_bus), int(r.to_bus)
        if abs(net.bus.at[fb, "vn_kv"] - net.bus.at[tb, "vn_kv"]) < 0.5:
            g.add_edge(fb, tb)
    has_up = {int(r.lv_bus) for _, r in
              net.trafo[net.trafo.in_service].iterrows()}
    load_at = defaultdict(float)
    for _, r in net.load[net.load.in_service].iterrows():
        load_at[int(r.bus)] += float(r.p_mw)
    clusters = []
    for comp in _nx.connected_components(g):
        kv = float(net.bus.at[next(iter(comp)), "vn_kv"])
        if kv < 60 or kv >= 275 or any(b in has_up for b in comp):
            continue
        load = sum(load_at.get(b, 0.0) for b in comp)
        if load < min_load_mw:
            continue
        big = max(comp, key=lambda b: load_at.get(b, 0.0))
        names = sorted({str(net.bus.at[b, "name"])[:14] for b in comp
                        if load_at.get(b, 0) > 0})[:4]
        clusters.append(dict(kv=kv, n_bus=len(comp),
                             load_mw=round(load, 1), anchor_bus=int(big),
                             names=names))
    ups = [(b, _geo(b)) for b in net.bus.index
           if net.bus.at[b, "in_service"] and net.bus.at[b, "vn_kv"] >= 275]
    ups = [(b, gg) for b, gg in ups if gg]
    ledger = []
    for c in sorted(clusters, key=lambda c: -c["load_mw"]):
        ga = _geo(c["anchor_bus"])
        if not ga or not ups:
            continue
        ub, ug = min(ups, key=lambda bg: (bg[1][0]-ga[0])**2 +
                     (bg[1][1]-ga[1])**2)
        dist_km = _math.hypot((ug[0]-ga[0])*91, (ug[1]-ga[1])*111)
        if dist_km > max_dist_km:
            ledger.append(dict(
                kv=c["kv"], load_mw=c["load_mw"], n_bus=c["n_bus"],
                cluster_names=c["names"],
                to_upper=str(net.bus.at[ub, "name"])[:20],
                upper_kv=float(net.bus.at[ub, "vn_kv"]),
                dist_km=round(dist_km, 1), sn_mva=0.0, capped=True))
            continue
        sn = max(300.0, 1.5 * c["load_mw"])
        pp.create_transformer_from_parameters(
            net, hv_bus=int(ub), lv_bus=int(c["anchor_bus"]), sn_mva=sn,
            vn_hv_kv=float(net.bus.at[ub, "vn_kv"]), vn_lv_kv=c["kv"],
            vkr_percent=0.5, vk_percent=12.0, pfe_kw=0.0, i0_percent=0.0,
            name=f"(仮)都心給電#37 {c['kv']:.0f}kV 実経路未確認")
        ledger.append(dict(
            kv=c["kv"], load_mw=c["load_mw"], n_bus=c["n_bus"],
            cluster_names=c["names"],
            to_upper=str(net.bus.at[ub, "name"])[:20],
            upper_kv=float(net.bus.at[ub, "vn_kv"]),
            dist_km=round(_math.hypot((ug[0]-ga[0])*91,
                                      (ug[1]-ga[1])*111), 1),
            sn_mva=round(sn, 0)))
    return ledger


def build_and_solve(region, demand_cfg, topology="snapped", reconnect=False, reactive=0.6,
                    snap_km=1.5, vertex_prec=4, backbone_kv=None,
                    load_spatial="none", boundary_imports=True,
                    boundary_util=None, db=None, boundary_stats=None,
                    measured_loads="auto", radialize_band_kv=None,
                    corridor_calib=None, expand_mixed_voltage=True,
                    join_untagged_tips=False):
    """Build network, solve DC+AC, return (net_dc, dc_result, net_ac, ac_result, build_info, snap_geom).

    Args:
        topology: "snapped" (vertex-graph + tolerance snap; the default and
            recommended builder) or "legacy" (nearest-substation endpoint
            match — kept for A/B comparison only; it drops the majority of
            lines and swallows cross-voltage lines into transformers).
        reconnect: when True, bridge the residual isolated components with
            labelled synthetic lines (recon_line_*) via the reconstruction
            module before solving, so the solved network is fully connected
            instead of silently disabling islands.
        backbone_kv: when set (e.g. 154.0), aggregate the sub-transmission
            layer onto the >= backbone_kv backbone before load allocation
            (see transforms.reduce_to_backbone) — the AC-solvable backbone
            model that sidesteps the proven ill-conditioned OSM sub-grid.
        boundary_imports: inject the OCCTO interconnections' typical flows
            at the region's boundary substations (a regional slice is not
            an electrical island; see src.powerflow.boundary). Local
            dispatch then covers load minus imports.
    """
    snap_geom = None
    if topology == "snapped":
        network, snap_geom = build_network_snapped(
            region, snap_km=snap_km, vertex_prec=vertex_prec, return_geom=True,
            db=db, expand_mixed_voltage=expand_mixed_voltage,
            join_untagged_tips=join_untagged_tips)
    else:
        network = build_network_from_geojson(region)
    if not network or not network.has_elements:
        return None

    builder = PandapowerBuilder()
    build_result = builder.build(network)
    net = build_result.net

    fix_zero_voltages(net)
    n_trafos = insert_transformers(net)

    backbone_info = None
    if backbone_kv:
        eff_kv = (REGION_BACKBONE_FLOOR.get(region, backbone_kv)
                  if backbone_kv == DEFAULT_BACKBONE_KV else backbone_kv)
        backbone_info = reduce_to_backbone(net, min_kv=eff_kv)

    # Residual reconnection: bridge genuine gaps with labelled synthetic lines
    # (named recon_line_*) instead of letting fix_topology disable the islands.
    n_synthetic = 0
    if reconnect:
        iso = Isolator().detect(net)
        # Only bridge tiny same-landmass gaps (OSM digitisation breaks). Larger
        # separations (sea straits, real gaps) are NOT fabricated; they stay as
        # separate components solved in place via multi_slack below.
        rec = Reconnector().reconnect(net, iso, ReconstructionConfig(
            mode="reconnect", max_reconnection_distance_km=5.0))
        n_synthetic = rec.lines_created

    radial_info = None
    if radialize_band_kv:
        from src.powerflow.transforms import radialize_band
        radial_info = radialize_band(net, lo_kv=float(radialize_band_kv))

    diag = fix_topology(net, multi_slack=True)
    select_slack_bus(net)

    # Measured demand placement (M3): DB-first — name-matched substations
    # are pinned to their disclosed busbar statistic when a calibrated DB
    # is present (scripts/db/calibrate.py); regions without rows get the
    # synthetic rule unchanged. Pass measured_loads=None to disable.
    mbl = None
    if measured_loads == "auto":
        from src.db.calibration import load_measured_bus_loads
        mbl = load_measured_bus_loads(region=region)
    elif isinstance(measured_loads, dict):
        mbl = measured_loads
    total_load = estimate_loads(net, region=region, demand_config=demand_cfg,
                                spatial=load_spatial, measured_bus_loads=mbl)
    inactive_buses = set(net.bus.index[~net.bus["in_service"]])
    if len(net.load) > 0:
        mask = net.load["bus"].isin(inactive_buses)
        net.load.loc[mask, "in_service"] = False
        total_load = net.load[net.load["in_service"]]["p_mw"].sum()

    boundary_info = None
    if boundary_imports:
        from src.powerflow.boundary import apply_boundary_imports
        if boundary_stats is None:
            # DB-first: corridor medians from measured_line_stats when a
            # calibrated DB is present (scripts/db/calibrate.py); regions
            # without calibration get None -> equal-split, as before.
            from src.db.calibration import boundary_stats_from_db
            boundary_stats = boundary_stats_from_db(region=region)
        boundary_info = apply_boundary_imports(net, region,
                                               utilisation=boundary_util,
                                               corridor_stats=boundary_stats)

    # measured per-fuel dispatch bands (F6): clamp the synthetic merit
    # order into the annual measured band where calibrated data exists
    # (gas swings as Japan's marginal fuel); fail-soft None elsewhere
    from src.db.calibration import fuel_bands_from_db
    fuel_bands = fuel_bands_from_db(region=region)
    balance_power(net, demand_cfg, fuel_bands=fuel_bands)

    # Corridor-flow demand state estimation (ledger 48/49): measured
    # corridor flows reshape the demand vector — names locate corridors,
    # the yards below them need none. v2 fits ALL corridors at once via
    # PTDF least squares (loops included); runs on the balanced net and
    # the dispatch is rebalanced to the calibrated demand afterwards.
    # Opt-in: pass {corridor key: MW} (the validator passes its train split).
    calib_info = None
    if corridor_calib:
        from src.powerflow.flow_calibration import ptdf_demand_estimation
        calib_info = ptdf_demand_estimation(net, dict(corridor_calib))
        total_load = float(net.load[net.load["in_service"]]["p_mw"].sum())
        balance_power(net, demand_cfg)

    scale_line_ratings(net)
    n_shunt = add_reactive_compensation(net, factor=reactive)
    net.bus["vm_pu"] = 1.0
    # AVR-style class schedule (EHV slightly above nominal) instead of a
    # flat 1.00 — together with the builder's Q-limits this replaces the
    # "infinite flat VAr source" generator model.
    apply_voltage_setpoints(net)

    # DC
    net_dc = copy.deepcopy(net)
    dc_result = run_powerflow(net_dc, "dc")

    # AC with pruning. The 12-degree rung exists for the OSM-faithful
    # binding (ledger 85): the de-fused west island carries longer honest
    # radials whose DC angles exceed 20 degrees; legacy builds converge at
    # >=20 so the extra rung is dormant for them.
    ac_result = {"mode": "ac", "converged": False}
    net_ac = None
    for threshold in [45.0, 30.0, 20.0, 12.0]:
        net_ac = copy.deepcopy(net)
        n_pruned = prune_dc_infeasible(net_ac, angle_threshold=threshold)
        if n_pruned > 0:
            fix_topology(net_ac, multi_slack=True)
            select_slack_bus(net_ac)
            scale_line_ratings(net_ac)
        ac_result = run_powerflow(net_ac, "ac")
        if ac_result["converged"]:
            break

    build_info = {
        "n_buses": len(net.bus),
        "n_lines": len(net.line),
        "n_gens": len(net.gen),
        "n_trafos": n_trafos,
        "n_active_buses": diag["n_active_buses"],
        "n_components": diag["n_components"],
        "n_synthetic_lines": n_synthetic,
        "n_shunt_comp": n_shunt,
        "topology": topology,
        "backbone": backbone_info,
        "boundary": boundary_info,
        "radialized": radial_info,
        "corridor_calib": calib_info,
        "total_load_mw": float(total_load),
        "total_gen_mw": float(net.gen[net.gen["in_service"]]["p_mw"].sum()) if len(net.gen) > 0 else 0,
    }

    return net_dc, dc_result, net_ac, ac_result, build_info, snap_geom
