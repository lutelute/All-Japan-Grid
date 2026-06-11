"""UC→潮流 ディスパッチ注入層 — UC_HANDOFF契約の消費側（タスク#6）。

設計（docs/UC_HANDOFF.md の契約に従う）:
1. **解く前に ybus_gate** — FAILした島の上では注入も再ソルブもしない
2. **地域×燃料の集計レベルで注入**（v1）— UC側発電機（GeoJSON plants由来の
   シナリオ機集合）とPF側発電機（GridNetwork→pandapower）は別実体で、
   機別1:1対応は存在しない。時刻断面の燃料別合計MWを、PF側の同燃料
   グループへ**容量比例**で配分する。
3. mainの potencia pipeline は変更しない — ``build_and_solve`` が返す
   解き済みnetの ``gen.p_mw`` を上書きして再ソルブする事後注入方式
   （並行開発の衝突回避と、merit-order初期解との比較可能性のため）。

整合性の限界（開示）: UC側の需要（OCCTOエリアピーク×形状）とPF側の需要
（実測ピン+合成残差）は独立に作られている。検証ドライバは PF側 load を
UC断面の地域純需要へスケールして需給を揃え、残差は slack に現れる —
slackの大きさが「UC運用断面とPF網の整合度」のKPIになる。
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from src.model.generator import Generator
from src.uc.models import UCResult
from src.uc.scenario import FUEL_MAP
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


def normalize_fuel(fuel_type: Optional[str]) -> str:
    """UC側・PF側双方の燃料語彙を共通正規形（lng等）へ揃える。"""
    rf = (fuel_type or "").lower()
    return FUEL_MAP.get(rf, rf or "unknown")


def uc_snapshot(
    uc_result: UCResult,
    generators: List[Generator],
    t: int,
    region: Optional[str] = None,
) -> Dict[str, float]:
    """UC解の時刻断面 t を {正規化燃料: MW} に集計する。

    storageの充電（負値）は発電側には計上しない（需要側に現れるべき量
    だが、v1の単一地域検証では正味発電のみを注入対象とする）。
    """
    gen_map = {g.id: g for g in generators}
    out: Dict[str, float] = {}
    for sched in uc_result.schedules:
        g = gen_map.get(sched.generator_id)
        if g is None or (region and g.region != region):
            continue
        if t >= len(sched.power_output_mw):
            continue
        p = float(sched.power_output_mw[t])
        if p <= 0:
            continue
        fuel = normalize_fuel(g.fuel_type)
        out[fuel] = out.get(fuel, 0.0) + p
    return out


def inject_dispatch(net, fuel_mw: Dict[str, float], gen_mask=None) -> Dict:
    """燃料別MWをPF側genへ容量比例で注入する（slack機は対象外）。

    Args:
        gen_mask: net.gen に対するbooleanマスク（多地域島でzone別に注入する
            場合に対象genを絞る）。Noneなら全gen。

    Returns:
        report dict:
        - injected_mw: 実際に gen.p_mw へ載った合計
        - requested_mw: UC断面の要求合計
        - clipped: {fuel: 超過MW} — PF側容量が要求より小さい燃料
        - unmatched: {fuel: MW} — PF側に該当燃料の発電機がない
        - zeroed_gens: 要求に現れない燃料の稼働genを0化した台数
          （UCでOFFの燃料はPF側でも止める — コミットメントの反映）
    """
    gen = net.gen
    is_slack = (gen["slack"].fillna(False).astype(bool)
                if "slack" in gen.columns else
                np.zeros(len(gen), dtype=bool))
    active = gen["in_service"].astype(bool) & ~is_slack
    if gen_mask is not None:
        active &= gen_mask.reindex(gen.index, fill_value=False).astype(bool)
    fuels_pf = gen["type"].map(normalize_fuel)

    report = {"requested_mw": round(sum(fuel_mw.values()), 1),
              "injected_mw": 0.0, "clipped": {}, "unmatched": {},
              "zeroed_gens": 0}

    # UC断面に現れない燃料の非slack機は0へ（コミットメントOFFの反映）
    for fuel in set(fuels_pf[active]) - set(fuel_mw):
        mask = active & (fuels_pf == fuel)
        n_on = int((gen.loc[mask, "p_mw"] > 0).sum())
        if n_on:
            net.gen.loc[mask, "p_mw"] = 0.0
            report["zeroed_gens"] += n_on

    for fuel, mw in fuel_mw.items():
        mask = active & (fuels_pf == fuel)
        cap = float(gen.loc[mask, "max_p_mw"].sum())
        if cap <= 0:
            report["unmatched"][fuel] = round(mw, 1)
            continue
        take = min(mw, cap)
        if mw > cap:
            report["clipped"][fuel] = round(mw - cap, 1)
        net.gen.loc[mask, "p_mw"] = (
            gen.loc[mask, "max_p_mw"] / cap * take
        )
        report["injected_mw"] += take
    report["injected_mw"] = round(report["injected_mw"], 1)
    logger.info("UC dispatch injected: %s", report)
    return report


def scale_loads_to(net, target_mw: float, load_mask=None) -> float:
    """PF側の有効負荷合計をUC断面の地域純需要へスケールする。

    Args:
        load_mask: net.load に対するbooleanマスク（多地域島でzone別に
            スケールする場合）。Noneなら全load。

    Returns: 適用した倍率。
    """
    active = net.load["in_service"].astype(bool)
    if load_mask is not None:
        active &= load_mask.reindex(net.load.index, fill_value=False).astype(bool)
    cur = float(net.load.loc[active, "p_mw"].sum())
    if cur <= 0 or target_mw <= 0:
        return 1.0
    ratio = target_mw / cur
    net.load.loc[active, "p_mw"] *= ratio
    net.load.loc[active, "q_mvar"] *= ratio
    return ratio


def inject_dispatch_by_zone(
    net,
    fuel_mw_by_zone: Dict[str, Dict[str, float]],
    zone_demand_mw: Dict[str, float],
) -> Dict[str, Dict]:
    """多地域同期島ネット（bus 'zone'=地域名）へ地域別にUC断面を注入する。

    地域ごとに load をUC純需要へスケールし、gen へ容量比例注入する。
    指定地域に属さないバスの load/gen は触らない。zone列が無い島ネットは
    対象外（build_island_networks 由来であることが前提）。

    Returns: {region: {"load_scale": 倍率, "injection": inject_dispatchのreport}}
    """
    # pandapowerはbusに既定でzone列を持つ（None埋め）— 値の実在で判定する
    if "zone" not in net.bus.columns or net.bus["zone"].isna().all():
        raise ValueError(
            "net.bus の zone が未設定 — build_island_networks 由来の"
            "多地域島ネットにのみ適用できる")
    zone_of_bus = net.bus["zone"]
    gen_zone = net.gen["bus"].map(zone_of_bus)
    load_zone = net.load["bus"].map(zone_of_bus)
    out: Dict[str, Dict] = {}
    for region, fuel_mw in fuel_mw_by_zone.items():
        ratio = scale_loads_to(
            net, float(zone_demand_mw.get(region, 0.0)),
            load_mask=(load_zone == region))
        rep = inject_dispatch(net, fuel_mw, gen_mask=(gen_zone == region))
        out[region] = {"load_scale": round(ratio, 4), "injection": rep}
    return out
