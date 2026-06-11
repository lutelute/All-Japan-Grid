"""Rolling horizon UC — 年間8760h時系列を窓分割で解く（ROADMAP P5）。

設計（旧 TimeWindowDecomposer の境界問題をここで解消）:
- 窓長 ``window_h``（既定48h）を ``step_h``（既定24h）ずつ前進。
  各窓の先頭 ``step_h`` のみ確定し、残り（lookahead）は翌窓で再決定する。
- **窓間の状態引き継ぎ**:
  - SOC: 確定末尾のSOCを次窓の ``initial_soc_fraction`` へ（揚水・蓄電池の
    日跨ぎ運用が連続する）
  - コミットメント: 確定末尾の u を ``UCParameters.initial_commitment`` へ
    （窓頭の幻の起動費を防ぐ）
  - min up/down: 確定部分末尾の連続ON/OFF時間を ``initial_history_h`` へ
    （窓境界で最小運転/停止時間が破られない）
- warm start: 前窓解を ``step_h`` シフトして次窓のMIP startに注入
  （root LP支配の窓では効果が薄いが、分枝が出るタイトな窓の保険）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional

import numpy as np

from src.model.generator import Generator
from src.uc.models import (
    DemandProfile,
    GeneratorSchedule,
    Interconnection,
    TimeHorizon,
    UCParameters,
    UCResult,
)
from src.uc.solver import solve_uc
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class RollingUCConfig:
    """rolling horizon の実行設定。"""

    window_h: int = 48
    step_h: int = 24
    reserve_margin: float = 0.05
    mip_gap: float = 0.01
    solver_name: str = "highs"
    warm_start: bool = True
    # 非Optimal時のリトライ: mip_gapを順に緩めて再試行
    retry_gaps: tuple = (0.03, 0.1)


@dataclass
class RollingUCResult:
    """rolling horizon の年間結果（確定部分の連結）。"""

    status: str = "Not Solved"          # "Optimal" = 全窓Optimal
    hours: int = 0
    n_windows: int = 0
    n_retried: int = 0
    failed_window: Optional[int] = None  # 最初に失敗した窓index（Noneなら完走）
    schedules: Dict[str, GeneratorSchedule] = field(default_factory=dict)
    total_cost: float = 0.0             # 確定部分の再計算コスト（fuel+no_load+startup）
    solve_time_s: float = 0.0
    window_times_s: List[float] = field(default_factory=list)
    window_statuses: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def is_optimal(self) -> bool:
        return self.status == "Optimal"


def _commit_segment(
    acc: Dict[str, GeneratorSchedule],
    result: UCResult,
    n_commit: int,
) -> None:
    """窓解の先頭 n_commit 期間を年間スケジュールに連結する。"""
    for sched in result.schedules:
        dst = acc.setdefault(
            sched.generator_id,
            GeneratorSchedule(generator_id=sched.generator_id),
        )
        dst.commitment.extend(sched.commitment[:n_commit])
        dst.power_output_mw.extend(sched.power_output_mw[:n_commit])
        if sched.soc_mwh:
            dst.soc_mwh.extend(sched.soc_mwh[:n_commit])
            dst.charge_mw.extend(sched.charge_mw[:n_commit])
            dst.discharge_mw.extend(sched.discharge_mw[:n_commit])


def _update_history(
    history: Dict[str, int],
    result: UCResult,
    n_commit: int,
) -> Dict[str, int]:
    """確定部分のコミットメントから連続ON/OFF時間（符号付き）を更新する。"""
    new_hist = dict(history)
    for sched in result.schedules:
        seg = sched.commitment[:n_commit]
        if not seg:
            continue
        last = seg[-1]
        run = 0
        for c in reversed(seg):
            if c == last:
                run += 1
            else:
                break
        if run == len(seg):
            # 確定部分全体が同一状態 → 前史と連結
            prev = history.get(sched.generator_id, 0)
            if last == 1:
                run += max(0, prev)
            else:
                run += max(0, -prev)
        new_hist[sched.generator_id] = run if last == 1 else -run
    return new_hist


def _slice_maintenance(
    windows: List[tuple],
    w0: int,
    w1: int,
) -> List[tuple]:
    """年間絶対時間のメンテ窓を rolling 窓ローカル index に変換する。

    ``add_maintenance_constraints`` は窓ローカルの timestep と比較するため、
    各窓の構築時に (start_h, end_h) を [w0, w1) と交差・平行移動する。
    """
    out = []
    for s, e in windows:
        ls, le = max(int(s) - w0, 0), min(int(e) - w0, w1 - w0)
        if ls < le:
            out.append((ls, le))
    return out


def _shift_schedules(
    schedules: List[GeneratorSchedule],
    shift: int,
) -> List[GeneratorSchedule]:
    """前窓解を shift 期間ずらして次窓のwarm start素材にする。"""
    out = []
    for s in schedules:
        out.append(GeneratorSchedule(
            generator_id=s.generator_id,
            commitment=list(s.commitment[shift:]),
            power_output_mw=list(s.power_output_mw[shift:]),
            soc_mwh=list(s.soc_mwh[shift:]),
            charge_mw=list(s.charge_mw[shift:]),
            discharge_mw=list(s.discharge_mw[shift:]),
        ))
    return out


def _recompute_cost(
    acc: Dict[str, GeneratorSchedule],
    generators: List[Generator],
    skip_h: int = 0,
) -> float:
    """確定スケジュールからコストを再計算する。

    窓のobjective合計はlookahead重複を含むため使えない。fuel + no_load/labor
    + 起動費（0→1遷移×hot_start相当）で再構成する。3-state起動の厳密な
    warm/cold判定は行わない（hotで近似の概算）。

    Args:
        skip_h: 先頭から除外する期間数（チャンク並列のwarmup）。起動判定の
            直前状態には ``commitment[skip_h-1]`` を使い、warmup境界での
            幻の起動費を発生させない。
    """
    gen_map = {g.id: g for g in generators}
    total = 0.0
    for gid, sched in acc.items():
        g = gen_map.get(gid)
        if g is None:
            continue
        power = np.asarray(sched.power_output_mw[skip_h:])
        commit = np.asarray(sched.commitment[skip_h:], dtype=int)
        total += float(power.clip(min=0).sum()) * g.fuel_cost_per_mwh
        total += float(commit.sum()) * (g.no_load_cost + g.labor_cost_per_h)
        if len(commit):
            prev = (
                int(sched.commitment[skip_h - 1]) if skip_h > 0
                and len(sched.commitment) >= skip_h else 0
            )
            starts = int(np.maximum(np.diff(commit, prepend=prev), 0).sum())
            startup_cost = g.hot_start_cost or g.startup_cost
            total += starts * startup_cost
            stops = int(np.maximum(-np.diff(commit, prepend=prev), 0).sum())
            total += stops * g.shutdown_cost
    return total


def solve_rolling_uc(
    generators: List[Generator],
    demand: np.ndarray,
    regional_demands: Optional[Dict[str, np.ndarray]],
    interconnections: List[Interconnection],
    config: Optional[RollingUCConfig] = None,
    progress: bool = True,
) -> RollingUCResult:
    """年間（任意長）時系列をrolling horizonで解く。

    Args:
        generators: 発電機リスト（storageの initial_soc_fraction は窓ごとに
            上書きされる）。
        demand: 全期間の系統需要 (hours,)。
        regional_demands: 地域別需要 {region: (hours,)}（ノーダルバランス用、
            Noneならシステム一本needs）。
        interconnections: 連系線（regional_demands とセットで使用）。
        config: 窓長・前進幅・ソルバー設定。
        progress: 窓ごとの進捗printを出すか。
    """
    cfg = config or RollingUCConfig()
    T = len(demand)
    res = RollingUCResult(hours=T)
    t_start = time.monotonic()

    # 初期状態: 全機「min_downを満たすだけOFFしていた」= 自由スタート
    history: Dict[str, int] = {
        g.id: -int(g.min_down_time_h) for g in generators
    }
    soc_state: Dict[str, float] = {
        g.id: g.initial_soc_fraction for g in generators if g.is_storage
    }
    prev_solution: Optional[List[GeneratorSchedule]] = None

    window_starts = list(range(0, T, cfg.step_h))
    res.n_windows = len(window_starts)

    for wi, w0 in enumerate(window_starts):
        w1 = min(w0 + cfg.window_h, T)
        n_commit = min(cfg.step_h, T - w0)

        gens_w = []
        for g in generators:
            kw = {}
            if g.id in soc_state:
                kw["initial_soc_fraction"] = soc_state[g.id]
            if g.maintenance_windows:
                kw["maintenance_windows"] = _slice_maintenance(
                    g.maintenance_windows, w0, w1,
                )
            gens_w.append(replace(g, **kw) if kw else g)
        params = UCParameters(
            generators=gens_w,
            demand=DemandProfile(demands=[float(x) for x in demand[w0:w1]]),
            time_horizon=TimeHorizon(num_periods=w1 - w0),
            reserve_margin=cfg.reserve_margin,
            solver_name=cfg.solver_name,
            mip_gap=cfg.mip_gap,
            interconnections=interconnections,
            regional_demands=(
                {r: [float(x) for x in d[w0:w1]]
                 for r, d in regional_demands.items()}
                if regional_demands else None
            ),
            initial_commitment={
                gid: 1 if h > 0 else 0 for gid, h in history.items()
            },
            initial_history_h=history,
            warm_start_schedules=(
                prev_solution if cfg.warm_start else None
            ),
        )

        t0 = time.monotonic()
        result = solve_uc(params)
        # 非Optimalならgapを緩めてリトライ
        for retry_gap in cfg.retry_gaps:
            if result.status == "Optimal":
                break
            res.n_retried += 1
            params.mip_gap = retry_gap
            result = solve_uc(params)
        dt = time.monotonic() - t0
        res.window_times_s.append(round(dt, 2))
        res.window_statuses.append(result.status)

        if progress:
            day = w0 // 24
            print(f"  [window {wi + 1}/{len(window_starts)} day{day:3d}] "
                  f"{result.status} {dt:.1f}s", flush=True)

        if result.status != "Optimal":
            res.failed_window = wi
            res.warnings.extend(result.warnings)
            res.status = result.status
            break

        _commit_segment(res.schedules, result, n_commit)
        history = _update_history(history, result, n_commit)
        # SOC引き継ぎ: 確定末尾のSOC（fraction化）
        for sched in result.schedules:
            if sched.soc_mwh and sched.generator_id in soc_state:
                g = next(g for g in generators if g.id == sched.generator_id)
                idx = min(n_commit, len(sched.soc_mwh)) - 1
                soc_state[sched.generator_id] = min(
                    1.0, max(0.0, sched.soc_mwh[idx] / g.storage_capacity_mwh)
                )
        prev_solution = _shift_schedules(result.schedules, cfg.step_h)
    else:
        res.status = "Optimal"

    res.total_cost = _recompute_cost(res.schedules, generators)
    res.solve_time_s = round(time.monotonic() - t_start, 1)
    return res
