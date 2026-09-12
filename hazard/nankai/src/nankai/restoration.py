"""復旧モデル: 損傷要素ごとの修理時間 + 作業班制約 + 優先順位 → 要素の復旧時刻。"""
from __future__ import annotations
import heapq
import numpy as np
import yaml, os

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.abspath(os.path.join(HERE, "..", "..", "config"))


def load_restoration_params() -> dict:
    from .fragility import _deep_update
    base = yaml.safe_load(open(os.path.join(CONFIG, "restoration_default.yaml"), encoding="utf-8"))
    p = os.path.join(CONFIG, "restoration.yaml")
    if os.path.exists(p):
        try:
            over = yaml.safe_load(open(p, encoding="utf-8")) or {}
            if over.get("schema") == "nankai-restoration-v1":
                _deep_update(base, {k: v for k, v in over.items() if k in base})
        except Exception:
            pass
    return base


def lognormal_days(median_d: float, beta: float, rng, size=None):
    return np.exp(np.log(median_d) + beta * rng.normal(size=size))


class RestorationModel:
    def __init__(self, params: dict | None = None):
        self.p = params or load_restoration_params()

    def repair_time_days(self, kind: str, ds: int, cause: int, rng) -> float:
        prm = self.p[kind]
        if cause == 2 and f"tsunami_ds{ds}" in prm:
            r = prm[f"tsunami_ds{ds}"]
        else:
            tbl = prm["ds"]
            r = tbl.get(ds) or tbl.get(str(ds)) or tbl[max(tbl.keys(), key=lambda k: int(k))]
        return float(lognormal_days(r["median_d"], r["beta"], rng))

    def schedule(self, jobs: list[dict], rng) -> dict:
        """jobs: {id, zone, kv, load_mw, duration_d}. 作業班制約付きの優先順スケジューリング。
        戻り: id → 復旧完了日"""
        crews = dict(self.p["crews"]["base"])
        aid_f = float(self.p["crews"].get("mutual_aid_factor", 1.0))
        aid_t = float(self.p["crews"].get("mutual_aid_start_d", 1e9))
        done = {}
        by_zone: dict[str, list] = {}
        for j in jobs:
            by_zone.setdefault(j.get("zone") or "other", []).append(j)
        for zone, js in by_zone.items():
            js.sort(key=lambda j: (-float(j.get("kv", 0)), -float(j.get("load_mw", 0))))
            c = int(crews.get(zone, 10))
            # 稼働班の空き時刻ヒープ(応援後は班数増)
            free = [0.0] * c
            heapq.heapify(free)
            aid_added = False
            for j in js:
                t0 = heapq.heappop(free)
                if not aid_added and t0 >= aid_t:
                    extra = int(c * (aid_f - 1.0))
                    for _ in range(extra):
                        heapq.heappush(free, aid_t)
                    aid_added = True
                    heapq.heappush(free, t0)
                    t0 = heapq.heappop(free)
                tend = t0 + float(j["duration_d"])
                done[j["id"]] = tend
                heapq.heappush(free, tend)
        return done
