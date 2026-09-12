"""地震動・津波の場。

- GMPEField: 近似震源域 + 司・翠川(1999) PGV/PGA + 藤本・翠川(2005) 計測震度
- MeshField: 実データ(J-SHIS / 内閣府 250mメッシュ)の最近傍参照。カバー外はGMPEへ退避
- TsunamiField: 国土数値情報 A40 浸水想定ポリゴン → 浸水深ランク/代表深
"""
from __future__ import annotations
import math, os
from dataclasses import dataclass
import numpy as np
import pandas as pd
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
NANKAI = os.path.abspath(os.path.join(HERE, "..", ".."))
CONFIG = os.path.join(NANKAI, "config")
DERIVED = os.path.join(NANKAI, "data", "derived")

JMA_CLASSES = [(0.5, "1"), (1.5, "2"), (2.5, "3"), (3.5, "4"), (4.5, "5弱"), (5.0, "5強"),
               (5.5, "6弱"), (6.0, "6強"), (6.5, "7")]


def jma_class(i: np.ndarray) -> np.ndarray:
    """計測震度 → 震度階級ラベル。"""
    i = np.asarray(i, float)
    out = np.full(i.shape, "0", dtype=object)
    for th, lab in JMA_CLASSES:
        out[i >= th] = lab
    return out


def pgv_to_intensity(pgv: np.ndarray) -> np.ndarray:
    """藤本・翠川(2005): I = 2.002 + 2.603 log10 PGV − 0.213 (log10 PGV)^2 (PGV: cm/s 地表)。"""
    lp = np.log10(np.maximum(np.asarray(pgv, float), 0.05))
    return np.clip(2.002 + 2.603 * lp - 0.213 * lp ** 2, 0.0, 7.0)


def intensity_to_pgv(i: np.ndarray) -> np.ndarray:
    """上式の逆(二次方程式の小さい方の根)。"""
    i = np.asarray(i, float)
    a, b, c = -0.213, 2.603, 2.002 - i
    disc = np.maximum(b * b - 4 * a * c, 0.0)
    lp = (-b + np.sqrt(disc)) / (2 * a)
    return 10 ** lp


def _aeqd(lat0=33.5, lon0=135.5):
    from pyproj import Transformer
    return Transformer.from_crs("EPSG:4326", f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +datum=WGS84 +units=km",
                                always_xy=True)


@dataclass
class HazardSample:
    """1サンプルの地震動(点ごと)。"""
    intensity: np.ndarray     # 計測震度
    pgv: np.ndarray           # cm/s 地表
    pga_g: np.ndarray         # g 地表
    rupture_km: np.ndarray    # 断層最短距離
    source: str


class GMPEField:
    """近似震源域 + 司・翠川(1999)。points は (lat, lon) 配列。"""

    def __init__(self, scenario: dict | str | None = None):
        if scenario is None or isinstance(scenario, str):
            p = scenario or os.path.join(CONFIG, "scenario_nankai.yaml")
            scenario = yaml.safe_load(open(p, encoding="utf-8"))
        self.sc = scenario
        from shapely.geometry import Polygon, LineString
        tr = _aeqd()
        ax = [tr.transform(lon, lat) for lat, lon in scenario["trough_axis"]]
        dd = [tr.transform(lon, lat) for lat, lon in scenario["downdip_edge"]]
        self.tr = tr
        self.axis = LineString(ax)
        self.downdip = LineString(dd)
        self.poly = Polygon(ax + dd[::-1])
        self.mw = float(scenario.get("gmpe_effective_mw", scenario["magnitude_mw"]))
        self.D = float(scenario.get("fault_centroid_depth_km", 20.0))
        self.ztop = float(scenario.get("fault_top_depth_km", 8.0))
        self.zbot = float(scenario.get("fault_bottom_depth_km", 35.0))
        g = scenario.get("gmpe", {})
        self.amp_pgv = float(g.get("pgv_site_amplification", 1.6))
        self.amp_pga = float(g.get("pga_site_amplification", 1.2))
        self.s_inter = float(g.get("sigma_inter_log10", 0.12))
        self.s_intra = float(g.get("sigma_intra_log10", 0.20))
        self.corr_km = float(g.get("intra_correlation_km", 25.0))
        self._amp_lookup = None

    def set_amplification_mesh(self, df: pd.DataFrame):
        """J-SHIS 地盤増幅率メッシュ [lat, lon, amp] を最近傍で使う(任意)。"""
        from scipy.spatial import cKDTree
        self._amp_lookup = (cKDTree(np.c_[df.lat.values, df.lon.values]), df.amp.to_numpy(float))

    def rupture_distance(self, lat, lon) -> np.ndarray:
        from shapely.geometry import Point
        from shapely import distance as shp_distance, points as shp_points
        x, y = self.tr.transform(np.asarray(lon, float), np.asarray(lat, float))
        pts = shp_points(np.c_[x, y])
        dh = shp_distance(pts, self.poly)              # 0 if inside
        da = shp_distance(pts, self.axis)
        dd = shp_distance(pts, self.downdip)
        frac = np.clip(da / np.maximum(da + dd, 1e-6), 0, 1)
        z = self.ztop + (self.zbot - self.ztop) * frac    # 断層面の深さ(直下)
        inside = dh <= 1e-9
        z_eff = np.where(inside, z, np.minimum(z, self.zbot))
        return np.sqrt(dh ** 2 + z_eff ** 2)

    def median(self, lat, lon):
        """中央値(ばらつき無し)の PGV(地表, cm/s), PGA(地表, g), 距離。"""
        X = self.rupture_distance(lat, lon)
        mw, D = self.mw, self.D
        lpgv = 0.58 * mw + 0.0038 * D - 1.29 - np.log10(X + 0.0028 * 10 ** (0.5 * mw)) - 0.002 * X
        lpga = 0.50 * mw + 0.0043 * D + 0.61 - np.log10(X + 0.0055 * 10 ** (0.5 * mw)) - 0.003 * X
        amp = np.full(len(X), self.amp_pgv)
        if self._amp_lookup is not None:
            tree, vals = self._amp_lookup
            d, k = tree.query(np.c_[np.asarray(lat, float), np.asarray(lon, float)], distance_upper_bound=0.02)
            ok = np.isfinite(d)
            amp[ok] = vals[k[ok]]
        pgv = 10 ** lpgv * amp
        pga = 10 ** lpga * self.amp_pga / 980.665
        return pgv, pga, X

    def sample(self, lat, lon, rng: np.random.Generator | None = None, randomize: bool = True) -> HazardSample:
        lat = np.asarray(lat, float); lon = np.asarray(lon, float)
        pgv, pga, X = self.median(lat, lon)
        if randomize and rng is not None:
            eps = rng.normal(0, self.s_inter)
            eta = correlated_noise(lat, lon, self.corr_km, rng) * self.s_intra
            f = 10 ** (eps + eta)
            pgv = pgv * f
            pga = pga * f ** 0.8   # PGA は PGV よりばらつきが小さいと仮定
        return HazardSample(pgv_to_intensity(pgv), pgv, pga, X, "gmpe")


def correlated_noise(lat, lon, corr_km: float, rng: np.random.Generator) -> np.ndarray:
    """粗格子上のガウス乱数を平滑化→補間した空間相関ノイズ(分散1に正規化)。"""
    from scipy.ndimage import gaussian_filter
    from scipy.interpolate import RegularGridInterpolator
    km_lat = 111.0; km_lon = 111.0 * math.cos(math.radians(float(np.mean(lat))))
    cell = max(corr_km / 2.0, 2.0)
    la0, la1 = lat.min() - 1, lat.max() + 1
    lo0, lo1 = lon.min() - 1, lon.max() + 1
    ny = int((la1 - la0) * km_lat / cell) + 2
    nx = int((lo1 - lo0) * km_lon / cell) + 2
    z = rng.normal(size=(ny, nx))
    s = corr_km / cell / 2.0
    z = gaussian_filter(z, s, mode="reflect")
    z = (z - z.mean()) / max(z.std(), 1e-9)
    ys = la0 + np.arange(ny) * cell / km_lat
    xs = lo0 + np.arange(nx) * cell / km_lon
    f = RegularGridInterpolator((ys, xs), z, bounds_error=False, fill_value=0.0)
    return f(np.c_[lat, lon])


class MeshField:
    """実データメッシュ(parquet: lat, lon, jma_intensity[, pgv_cm_s]) の最近傍参照。"""

    def __init__(self, path: str, fallback: GMPEField | None = None, max_dist_deg: float = 0.004,
                 sigma_intra_log10: float = 0.12, corr_km: float = 25.0):
        from scipy.spatial import cKDTree
        df = pd.read_parquet(path) if path.endswith(".parquet") else pd.read_csv(path)
        self.df = df
        self.tree = cKDTree(np.c_[df.lat.values, df.lon.values])
        self.I = df.jma_intensity.to_numpy(float)
        self.pgv = df.pgv_cm_s.to_numpy(float) if "pgv_cm_s" in df else intensity_to_pgv(self.I)
        self.fallback = fallback
        self.max_dist = max_dist_deg
        self.s_intra = sigma_intra_log10
        self.corr_km = corr_km
        self.name = os.path.basename(path)

    def sample(self, lat, lon, rng=None, randomize=True) -> HazardSample:
        lat = np.asarray(lat, float); lon = np.asarray(lon, float)
        d, k = self.tree.query(np.c_[lat, lon], distance_upper_bound=self.max_dist)
        ok = np.isfinite(d)
        pgv = np.full(len(lat), np.nan); X = np.full(len(lat), np.nan)
        pgv[ok] = self.pgv[k[ok]]
        if (~ok).any():
            if self.fallback is None:
                pgv[~ok] = 0.5
            else:
                fb = self.fallback.median(lat[~ok], lon[~ok])
                pgv[~ok] = fb[0]; X[~ok] = fb[2]
        if self.fallback is not None:
            X = self.fallback.rupture_distance(lat, lon)
        if randomize and rng is not None:
            eta = correlated_noise(lat, lon, self.corr_km, rng) * self.s_intra
            pgv = pgv * 10 ** eta
        I = pgv_to_intensity(pgv)
        pga = pgv_to_pga_g(pgv)
        return HazardSample(I, pgv, pga, X, f"mesh:{self.name}")


def pgv_to_pga_g(pgv):
    """PGV(地表 cm/s) → PGA(g) の粗い換算。M9 海溝型の遠方記録では PGA/PGV ≈ 8〜12 (1/s)。
    近傍で比が下がる傾向を PGV 依存で表す(仮定・confidence low)。"""
    pgv = np.maximum(np.asarray(pgv, float), 0.05)
    ratio = np.clip(14.0 - 3.0 * np.log10(pgv), 6.0, 14.0)
    return pgv * ratio / 980.665


class TsunamiField:
    """A40 浸水想定ポリゴン → 点の浸水深ランク(0=浸水なし)と代表深(m)。"""
    RANK_DEPTH = {0: 0.0, 1: 0.15, 2: 0.65, 3: 1.5, 4: 3.5, 5: 7.5, 6: 15.0, 7: 25.0}

    def __init__(self, path: str | None = None, layer: str = "inundation"):
        path = path or os.path.join(DERIVED, "tsunami_inundation_A40.gpkg")
        self.available = os.path.exists(path)
        self.path = path; self.layer = layer
        self.gdf = None

    def load(self):
        """遅延読込(1GB超)。Simulator はキャッシュがあれば呼ばない。"""
        if self.gdf is not None or not self.available:
            return
        import geopandas as gpd
        g = gpd.read_file(self.path, layer=self.layer)
        g = g[g.geometry.notna()]
        self.gdf = g.reset_index(drop=True)
        self.sindex = self.gdf.sindex
        self.rank = self.gdf.depth_rank.to_numpy(int)

    def depth_rank(self, lat, lon) -> np.ndarray:
        lat = np.asarray(lat, float); lon = np.asarray(lon, float)
        out = np.zeros(len(lat), int)
        if not self.available:
            return out
        self.load()
        import geopandas as gpd
        from shapely import points as shp_points
        pts = gpd.GeoSeries(shp_points(np.c_[lon, lat]), crs="EPSG:4326")
        hits = self.sindex.query(pts, predicate="within")   # (2, n): [point_idx, poly_idx]
        if hits.size:
            pi, gi = hits
            r = self.rank[gi]
            np.maximum.at(out, pi, r)
        return out

    def depth_m(self, lat, lon) -> np.ndarray:
        r = self.depth_rank(lat, lon)
        return np.vectorize(self.RANK_DEPTH.get)(r).astype(float)


def default_field(prefer_mesh: bool = True):
    """data/derived にメッシュ実データがあればそれ、無ければ GMPE 合成場。"""
    gm = GMPEField()
    amp = os.path.join(DERIVED, "jshis_amp_vs400.parquet")
    if os.path.exists(amp):
        try:
            gm.set_amplification_mesh(pd.read_parquet(amp))
        except Exception:
            pass
    mesh = os.path.join(DERIVED, "jshis_nankai_intensity.parquet")
    if prefer_mesh and os.path.exists(mesh):
        return MeshField(mesh, fallback=gm)
    return gm
