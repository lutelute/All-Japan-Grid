"""介入#45: 線路容量の運用容量較正（2026-09-02）.

本モデルの線路容量は電圧階級ごとの代表電流 `max_i_ka`（config/line_types.yaml）から
`√3·V·I` で機械的に振った理論値で、出典を持たない。送配電事業者が公表する線路別の
設備容量・運用容量との比較（scripts/capacity/calibrate_line_capacity.py）で、理論値は
運用容量の概ね 1.5〜2.5 倍（階級・エリアで 0.27〜0.95 の係数）と分かっている。

本モジュールは `config/line_capacity_calibration.yaml`（比だけ・生値なし）から
(エリア, 電圧階級) の係数を引き、PF ビルダーが線路の `max_i_ka` に乗じる。
フォールバックは 3 段: エリア×階級 → 全国中央値(階級) → 全体中央値。どの段で
引いたかを帳簿（`ledger`）に本数つきで残す。

較正は潮流を変えない（容量は制約側の数字）。較正で過負荷が増えるなら、それは
潮流側（需要配分・発電配分・降圧点）の歪みが露出したと読む。
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict, Optional

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..",
                           "config", "line_capacity_calibration.yaml")
KV_CLASSES = (66, 77, 110, 132, 154, 187, 220, 275, 500)


@lru_cache(maxsize=4)
def load_calibration(path: Optional[str] = None) -> dict:
    """yaml を読む。無ければ空（= 係数 1.0・帳簿に 'no_config'）。"""
    import yaml
    p = os.path.abspath(path or CONFIG_PATH)
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        d = yaml.safe_load(f) or {}
    return d


def nearest_class(kv: float) -> Optional[int]:
    if kv is None or kv <= 0:
        return None
    best = min(KV_CLASSES, key=lambda c: abs(c - kv))
    return best if abs(best - kv) / best <= 0.15 else None


def capacity_factor(kv: float, area: Optional[str], ledger: Optional[Dict] = None,
                    path: Optional[str] = None) -> float:
    """(kv, area) の較正係数。無ければフォールバックし、帳簿に段を記録する。

    ledger: {"by_source": {"area": n, "national": n, "overall": n, "none": n},
             "by_area_kv": {"kansai/154": ("area", 0.679), ...}}
    """
    cfg = load_calibration(path)
    cls = nearest_class(float(kv or 0))
    src, fac = "none", 1.0
    if cfg and cls is not None:
        a = (cfg.get("areas") or {}).get(area) or {}
        rec = a.get(cls) if isinstance(a, dict) else None
        if isinstance(rec, dict) and rec.get("factor"):
            src, fac = "area", float(rec["factor"])
        else:
            nat = (cfg.get("national") or {}).get(cls)
            if isinstance(nat, dict) and nat.get("median_factor"):
                src, fac = "national", float(nat["median_factor"])
            elif cfg.get("overall_median_factor"):
                src, fac = "overall", float(cfg["overall_median_factor"])
    elif not cfg:
        src = "no_config"
    if ledger is not None:
        bs = ledger.setdefault("by_source", {})
        bs[src] = bs.get(src, 0) + 1
        ledger.setdefault("by_area_kv", {})[f"{area}/{cls}"] = [src, round(fac, 3)]
    return fac


def describe(ledger: Dict) -> str:
    bs = ledger.get("by_source", {})
    return ("介入#45 線路容量較正: "
            + " ".join(f"{k}={v}" for k, v in sorted(bs.items()))
            + (f"（config {os.path.relpath(os.path.abspath(CONFIG_PATH))}）" if bs else ""))
