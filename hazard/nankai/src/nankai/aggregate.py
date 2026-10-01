"""母線結果を自治体(N03)へ集約する。需要(MW)加重の供給率・停電確率、概算停電軒数。"""
from __future__ import annotations
import os
import numpy as np
import pandas as pd
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
NANKAI = os.path.abspath(os.path.join(HERE, "..", ".."))
MUNI = os.path.join(NANKAI, "data", "derived", "municipalities.gpkg")
CUSTOMERS = os.path.join(NANKAI, "config", "customers.yaml")


def customers_per_mw(zone_load: dict) -> dict:
    """zone → 軒/MW。config/customers.yaml の契約口数 ÷ ケースの zone 負荷。"""
    if not os.path.exists(CUSTOMERS):
        return {}
    c = yaml.safe_load(open(CUSTOMERS, encoding="utf-8")).get("contracts_thousand", {})
    return {z: (c[z] * 1000.0 / zone_load[z]) if z in c and zone_load.get(z, 0) > 0 else np.nan for z in zone_load}


def to_municipalities(bus: pd.DataFrame, timeline, muni_path: str = MUNI):
    if not os.path.exists(muni_path):
        return None
    import geopandas as gpd
    from shapely import points as shp_points
    muni = gpd.read_file(muni_path, layer="muni")
    pts = gpd.GeoDataFrame(bus.copy(), geometry=shp_points(np.c_[bus.lon.values, bus.lat.values]), crs="EPSG:4326")
    j = gpd.sjoin(pts, muni[["muni_code", "pref_name", "muni_name", "geometry"]], how="left", predicate="within")
    j = j[~j.index.duplicated()]
    zl = bus.groupby("zone").pd_mw.sum().to_dict()
    cpm = customers_per_mw(zl)
    j["customers"] = j.pd_mw * j.zone.map(cpm).fillna(0.0)
    cols = {f"served_t{t:g}": "wmean" for t in timeline}
    rows = []
    for code, d in j.groupby("muni_code"):
        L = d.pd_mw.sum()
        r = {"muni_code": code, "pref_name": d.pref_name.iloc[0], "muni_name": d.muni_name.iloc[0], "n_bus": len(d), "load_mw": L,
             "customers": float(d.customers.sum()), "intensity_mean": float(d.intensity_mean.mean()),
             "expected_outage_days": float((d.expected_outage_days * d.pd_mw).sum() / L) if L > 0 else float(d.expected_outage_days.mean())}
        for t in timeline:
            sv = d[f"served_t{t:g}"]
            r[f"served_t{t:g}"] = float((sv * d.pd_mw).sum() / L) if L > 0 else float(sv.mean())
            r[f"outage_customers_t{t:g}"] = float(((1 - sv) * d.customers).sum())
            if f"phys_t{t:g}" in d:
                pv = d[f"phys_t{t:g}"]
                r[f"phys_t{t:g}"] = float((pv * d.pd_mw).sum() / L) if L > 0 else float(pv.mean())
                r[f"outage_customers_phys_t{t:g}"] = float(((1 - pv) * d.customers).sum())
        rows.append(r)
    out = pd.DataFrame(rows).drop(columns=["pref_name", "muni_name"])
    res = muni.merge(out, on="muni_code", how="inner")
    # 出力サイズ対策: 行政界は簡略化(≈100m)して返す(N03 原寸は west で 200MB 超)
    res["geometry"] = res.geometry.simplify(0.001, preserve_topology=True)
    return res


PREF_GEOJSON = os.path.join(os.path.dirname(NANKAI), "..", "data", "reference", "japan_prefectures_simplified.geojson")
NAIKAKUFU_REGIONS = {"tokai": ["静岡県", "愛知県", "三重県"], "kinki": ["和歌山県", "大阪府", "兵庫県"], "sanyo": ["岡山県", "広島県", "山口県"],
                     "shikoku": ["徳島県", "香川県", "高知県", "愛媛県"], "kyushu": ["大分県", "宮崎県"]}


def bus_prefecture(case) -> np.ndarray:
    """母線 → 都道府県名(簡略県境ポリゴンで空間結合・parquet キャッシュ)。"""
    from .grid import DERIVED
    cp = os.path.join(DERIVED, f"bus_pref_{case.island}.parquet")
    if os.path.exists(cp):
        c = pd.read_parquet(cp)
        if len(c) == case.n_bus and (c.bus_id.values == case.bus.bus_id.values).all():
            return c.pref.to_numpy()
    import geopandas as gpd
    from shapely import points as shp_points
    pref = gpd.read_file(os.path.abspath(PREF_GEOJSON))
    pts = gpd.GeoDataFrame({"bus_id": case.bus.bus_id.values}, geometry=shp_points(np.c_[case.bus.lon.values, case.bus.lat.values]), crs="EPSG:4326")
    j = gpd.sjoin(pts, pref[["pref_ja", "geometry"]], how="left", predicate="within")
    j = j[~j.index.duplicated()]
    miss = j.pref_ja.isna()
    if miss.any():   # 海上・県境の取りこぼしは最近傍ポリゴン
        near = gpd.sjoin_nearest(pts[miss.values], pref[["pref_ja", "geometry"]], how="left")
        near = near[~near.index.duplicated()]
        j.loc[miss, "pref_ja"] = near.pref_ja.values
    out = j.pref_ja.fillna("不明").to_numpy()
    pd.DataFrame({"bus_id": case.bus.bus_id.values, "pref": out}).to_parquet(cp, index=False)
    return out


def naikakufu_region_of(pref: np.ndarray) -> np.ndarray:
    m = {p: r for r, ps in NAIKAKUFU_REGIONS.items() for p in ps}
    return np.array([m.get(p, "other") for p in pref])
