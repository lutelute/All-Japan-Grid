"""解析用系統ケース(hazard/nankai/data/derived/grid_<island>_*.parquet)の読み込み。"""
from __future__ import annotations
import json, os
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
NANKAI = os.path.abspath(os.path.join(HERE, "..", ".."))
DERIVED = os.path.join(NANKAI, "data", "derived")

THERMAL = {"gas", "coal", "oil", "lng", "thermal", "biomass", "waste", "mixed"}


def classify_fuel(name: str, fuel: str | None) -> str:
    """燃料ラベルを名前で補正する(正典の solar 重複ラベル等を火力/原子力へ戻す)。"""
    n = str(name or "")
    f = (fuel or "unknown").lower()
    if "原子力" in n or "原発" in n:
        return "nuclear"
    if "火力" in n or "発電所" in n and any(k in n for k in ("火力", "LNG", "石炭", "ガス")):
        return "thermal"
    if "水力" in n or "ダム" in n or "揚水" in n:
        return "hydro"
    if "太陽" in n or "ソーラー" in n or "メガソーラー" in n:
        return "solar"
    if "風力" in n or "ウインド" in n:
        return "wind"
    if "地熱" in n:
        return "geothermal"
    if f in THERMAL:
        return "thermal"
    if f in ("nuclear", "hydro", "solar", "wind", "geothermal"):
        return f
    return "unknown"


@dataclass
class GridCase:
    island: str
    bus: pd.DataFrame
    branch: pd.DataFrame
    gen: pd.DataFrame
    meta: dict = field(default_factory=dict)

    @property
    def n_bus(self) -> int:
        return len(self.bus)

    @classmethod
    def load(cls, island: str, derived: str = DERIVED) -> "GridCase":
        bus = pd.read_parquet(f"{derived}/grid_{island}_bus.parquet")
        br = pd.read_parquet(f"{derived}/grid_{island}_branch.parquet")
        gen = pd.read_parquet(f"{derived}/grid_{island}_gen.parquet")
        meta = {}
        mp = f"{derived}/grid_meta.json"
        if os.path.exists(mp):
            meta = json.load(open(mp)).get("islands", {}).get(island, {})
        # 連番化: bus_id → 0..n-1 の内部添字
        bus = bus.reset_index(drop=True)
        idx = pd.Series(np.arange(len(bus)), index=bus.bus_id.values)
        br = br[br.in_service].reset_index(drop=True)
        br["f"] = idx.loc[br.f_bus].values
        br["t"] = idx.loc[br.t_bus].values
        # 座標欠損: 隣接母線の座標で補完(無ければ zone 重心)
        miss = bus.lat.isna() | bus.lon.isna()
        if miss.any():
            nb = {}
            for f_, t_ in zip(br.f, br.t):
                nb.setdefault(f_, []).append(t_); nb.setdefault(t_, []).append(f_)
            for i in np.where(miss)[0]:
                cand = [j for j in nb.get(i, []) if not miss.iloc[j]]
                if cand:
                    bus.loc[i, ["lat", "lon"]] = bus.loc[cand[0], ["lat", "lon"]].values
                else:
                    z = bus[(bus.zone == bus.zone.iloc[i]) & ~miss]
                    bus.loc[i, ["lat", "lon"]] = [z.lat.mean(), z.lon.mean()]
        gen = gen[gen.in_service].reset_index(drop=True)
        gen["b"] = idx.loc[gen.bus_id].values
        fuelcol = "fuel" if "fuel" in gen.columns else ("type" if "type" in gen.columns else None)
        gen["cls"] = [classify_fuel(n, (gen[fuelcol].iloc[i] if fuelcol else None)) if k == "gen" else "slack"
                      for i, (n, k) in enumerate(zip(gen.name, gen.kind))]
        # 変電所サイト: 同名(電圧サフィックス除去)かつ近接(<1.5km)を同一サイトとみなす
        bus["site_id"] = _site_ids(bus)
        return cls(island, bus, br, gen, meta)

    def bus_xy(self):
        return self.bus.lat.to_numpy(float), self.bus.lon.to_numpy(float)


def _site_ids(bus: pd.DataFrame) -> np.ndarray:
    """同一サイト判定。名前一致 + 1.5km 以内。junction は各自1サイト。"""
    site = np.arange(len(bus))
    groups: dict = {}
    lat = bus.lat.to_numpy(float); lon = bus.lon.to_numpy(float)
    for i, (s, j) in enumerate(zip(bus.site, bus.is_junction)):
        if j:
            continue
        lst = groups.setdefault(s, [])
        for k in lst:
            if abs(lat[i] - lat[k]) < 0.0135 and abs(lon[i] - lon[k]) < 0.0165:
                site[i] = site[k]
                break
        else:
            lst.append(i)
    return site
