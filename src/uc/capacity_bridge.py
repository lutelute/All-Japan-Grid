"""UC容量較正のPF側適用 — 容量の正の一元化（容量二重管理の解消層）。

UC改善⑫で定量化した問題: UC側の容量較正（capacity_patches・nuclear_status、
DBの uc_scenario_generators にingest済み）がPF側のOSM由来netに届かず、
UC→PF注入で受け皿不足（hokuriku -77% / kyushu -31% / shikoku -52%）になる。

この層はDB（正本はdata/reference/*.yaml）から較正を読み、pandapower
net.gen へ適用する。west島診断（2026-06-12）の実態に基づく4ステップ:

1. **dedup** — bbox重複GeoJSONコピー由来の同(name, bus, 容量)重複行を停止
   （west島で橘湾が2組4行=2,800MWの二重計上になっていた）
2. **capacity_patches** — name部分一致でサイト公称容量へ補正。PF側は
   GridNetworkローダーが欠損(-1.0)を燃料別デフォルトに置換済みで「欠損」が
   観測できないため、パッチは常時適用（出典付き公称値を正とする）。
   capacity_mw=0 は廃止 → 停止。fuel キーは type 列を補正（注入の燃料照合）
3. **nuclear_status** — 稼働炉リストにmatchした炉はsite容量、リスト外の
   nuclear は停止。UC側 apply_nuclear_status_reference と同じ断面意味論
4. **zone override** — region キー付きパッチ（敦賀火力→hokuriku、
   橘湾火力→shikoku）の帰属表を返す。bus.zone は需要配分に使われるため
   書き換えず、inject_dispatch_by_zone が gen単位で上書きする

mainのビルダー/enrich層は無改変（解き済みnetへの事後適用 — マージ時に
curate層へ昇格する受け皿）。DB接続はベストエフォート（YAMLフォールバック）。
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

import yaml

from src.utils.logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_DB = os.path.join("data", "grid.db")


def load_pf_calibration(scenario_id: str = "fy2023r2",
                        db_path: str = DEFAULT_DB) -> Dict[str, List[dict]]:
    """容量パッチ+稼働炉リストをDBから読む（不可ならYAML正本へ）。

    Returns: {"patches": [...], "nuclear": [...]}
    """
    patches: List[dict] = []
    nuclear: List[dict] = []
    try:
        from src.db.grid_db import GridDatabase

        db = GridDatabase(db_path)
        rows = db.list_uc_scenario_generators(scenario_id)
        patches = [json.loads(r.payload_json) for r in rows
                   if r.kind == "capacity_patches"]
        nuclear = [json.loads(r.payload_json) for r in rows
                   if r.kind == "nuclear_status"]
        if patches or nuclear:
            logger.info("PF calibration from DB: %d patches, %d reactors "
                        "(scenario=%s)", len(patches), len(nuclear),
                        scenario_id)
    except Exception as exc:
        logger.warning("DB読込不可 (%s) — YAML正本へフォールバック", exc)

    if not patches or not nuclear:
        from src.uc.scenario import load_scenario_config

        cfg = load_scenario_config(scenario_id)
        if not patches:
            path = cfg.reference_path("capacity_patches")
            if path and os.path.exists(path):
                with open(path) as f:
                    patches = (yaml.safe_load(f) or {}).get("patches", [])
        if not nuclear:
            path = cfg.reference_path("nuclear_status")
            if path and os.path.exists(path):
                with open(path) as f:
                    nuclear = (yaml.safe_load(f) or {}).get("operational", [])
        logger.info("PF calibration from YAML: %d patches, %d reactors",
                    len(patches), len(nuclear))
    return {"patches": patches, "nuclear": nuclear}


def apply_to_net(net, calib: Dict[str, List[dict]]) -> Dict:
    """net.gen へ較正を適用し、適用レポートを返す（in-place）。

    Returns:
        report:
        - dedup_disabled: 停止した重複行数
        - patched / retired / fuel_fixed: パッチ適用件数
        - nuclear_set / nuclear_stopped: 稼働炉の容量設定・リスト外停止数
        - zone_override: {gen_idx: region} 注入側で使う帰属表
        - mw_delta: max_p_mw の正味増減（稼働genのみ）
        - unmatched_patches: PF側に見つからなかったmatch文字列（開示）
    """
    gen = net.gen
    report: Dict = {"dedup_disabled": 0, "patched": 0, "retired": 0,
                    "fuel_fixed": 0, "nuclear_set": 0, "nuclear_stopped": 0,
                    "zone_override": {}, "mw_delta": 0.0,
                    "unmatched_patches": []}
    before_mw = float(
        gen.loc[gen["in_service"].astype(bool), "max_p_mw"].clip(lower=0).sum())

    # ── 1. dedup: 同(name, bus, max_p_mw) の2行目以降を停止 ──
    # 大型機限定: bbox重複コピーの実害は大型火力の二重計上（west島の橘湾
    # 2,100MW×2組）。小型の同名・同容量は正規の別実体が普通（同名ソーラー
    # 区画群・水力ユニット）で、無差別dedupはeast島で4,492行/−59GWを誤停止
    # し ybus_gate FAIL を招いた（2026-06-12計測）。
    DEDUP_MIN_MW = 100.0
    active = gen["in_service"].astype(bool)
    names = gen["name"].astype(str)
    seen: set = set()
    for idx in gen.index[active]:
        cap0 = float(gen.at[idx, "max_p_mw"])
        if cap0 < DEDUP_MIN_MW:
            continue
        key = (names.at[idx], int(gen.at[idx, "bus"]), round(cap0, 1))
        if key in seen and key[0] not in ("", "None", "nan"):
            net.gen.at[idx, "in_service"] = False
            report["dedup_disabled"] += 1
        else:
            seen.add(key)

    active = net.gen["in_service"].astype(bool)

    # ── 2. capacity_patches（常時適用 — 出典付き公称値が正） ──
    for patch in calib.get("patches", []):
        match = str(patch.get("match", ""))
        if not match:
            continue
        mask = active & names.str.contains(match, regex=False, na=False)
        if not mask.any():
            report["unmatched_patches"].append(match)
            continue
        cap_raw = patch.get("capacity_mw")  # 無し=帰属/燃料のみのパッチ
        for idx in net.gen.index[mask]:
            if patch.get("fuel"):
                if net.gen.at[idx, "type"] != patch["fuel"]:
                    net.gen.at[idx, "type"] = patch["fuel"]
                    report["fuel_fixed"] += 1
            if cap_raw is not None:
                cap = float(cap_raw)
                if cap <= 0:  # 廃止・除外
                    net.gen.at[idx, "in_service"] = False
                    report["retired"] += 1
                    continue
                net.gen.at[idx, "max_p_mw"] = cap
                net.gen.at[idx, "max_q_mvar"] = 0.5 * cap
                net.gen.at[idx, "min_q_mvar"] = -0.3 * cap
                report["patched"] += 1
            if patch.get("region"):
                report["zone_override"][int(idx)] = patch["region"]

    active = net.gen["in_service"].astype(bool)

    # ── 3. nuclear_status: 稼働炉=site容量 / リスト外=停止 ──
    nuc_mask = active & (net.gen["type"].astype(str) == "nuclear")
    sites = calib.get("nuclear", [])
    claimed: set = set()
    for idx in net.gen.index[nuc_mask]:
        name = names.at[idx]
        site = next((s for s in sites
                     if str(s.get("name", "")) and str(s["name"]) in name),
                    None)
        if site is None:
            net.gen.at[idx, "in_service"] = False
            report["nuclear_stopped"] += 1
            continue
        skey = str(site["name"])
        if skey in claimed:  # 同サイト2行目（dedup漏れ）は停止
            net.gen.at[idx, "in_service"] = False
            report["nuclear_stopped"] += 1
            continue
        claimed.add(skey)
        cap = float(site.get("capacity_mw", 0.0))
        net.gen.at[idx, "max_p_mw"] = cap
        net.gen.at[idx, "max_q_mvar"] = 0.5 * cap
        net.gen.at[idx, "min_q_mvar"] = -0.3 * cap
        report["nuclear_set"] += 1

    after_mw = float(
        net.gen.loc[net.gen["in_service"].astype(bool), "max_p_mw"]
        .clip(lower=0).sum())
    report["mw_delta"] = round(after_mw - before_mw, 1)
    logger.info("capacity bridge applied: %s", report)
    return report
