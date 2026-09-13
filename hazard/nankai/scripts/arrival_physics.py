#!/usr/bin/env python3
"""地震と津波の「到達」を物理量として作る(可視化 make_arrival_variants.py の下ごしらえ)。

    PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/arrival_physics.py [--force]

作るもの(hazard/nankai/output/arrival_cache/ に npz でキャッシュ。追跡しない):
  seismic.npz  地図フレーム(1920x1080 の 1/2 解像度)上の
               t_rup[fault]  断層点ごとの破壊時刻 = 震源からの距離 / Vr
               t_p, t_s      P 波・S 波の到達時刻 = min_断層点 (破壊時刻 + 距離 / V)  (キネマティック近似)
               jma           J-SHIS AN177 の計測震度(250 m 点を地図画素に平均)
  tsunami.npz  ETOPO1(1 分角)格子上の
               eta_snap      線形長波方程式(浅水方程式の線形版)の水位スナップショット(1 分ごと、地図範囲に切り出し)
               t_arr_swe     初到達時刻(水位 > 閾値)
               t_arr_eik     走時(ホイヘンス: 速度 c = sqrt(g h) の最短走時。SWE とは原理の違う第二経路)
               eta0          初期水位

一次資料と仮定:
  - 破壊伝播速度 Vr = 2.7 km/s、S 波速度 3.82 km/s: 内閣府(2012)強震断層モデル編 表(Vr = 0.72 Vs)
  - 破壊開始点: 同資料「紀伊半島の南(中央防災会議 2003 と同様の場所)」。本コードは AN177 断層点のうち
    (33.30N, 135.90E) に最も近い深さ 10〜25 km の点を仮置き
  - P 波速度 = sqrt(3) Vs(ポアソン固体の仮定)。直線波線・均質半無限(仮定)
  - 初期水位: AN177 断層点の深さから作った簡易分布(浅部で隆起 最大 6 m・深部で沈降 最大 1.5 m)。
    Okada(1985)の弾性解でも内閣府の 11 ケースでもない(仮定)。振幅は定量ではなく、到達時刻の目安に使う
  - 水深: NOAA ETOPO1(1 分角)。沿岸の浅海・港湾は解像できない
"""
from __future__ import annotations
import argparse, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
from scipy.ndimage import gaussian_filter, distance_transform_edt, map_coordinates
from scipy.interpolate import griddata

import make_cinematic as mc

NANKAI = mc.NANKAI
CACHE = os.path.join(NANKAI, "output", "arrival_cache")
R_E = 6371.0e3; G = 9.81
VS = 3.82; VR = 0.72 * VS; VP = np.sqrt(3.0) * VS          # km/s
HYPO_NEAR = (33.30, 135.90)
DS = 2                                                      # 地図フレームの間引き(960x540)

# 到達を読む沿岸点(港・岬)。(名前, 緯度, 経度)
COAST_POINTS = [
    ("御前崎", 34.60, 138.22), ("浜松", 34.66, 137.70), ("名古屋港", 35.02, 136.85), ("鳥羽", 34.48, 136.87),
    ("尾鷲", 34.07, 136.22), ("串本", 33.47, 135.78), ("和歌山", 34.22, 135.12), ("大阪港", 34.64, 135.40),
    ("神戸港", 34.67, 135.21), ("徳島", 34.07, 134.60), ("室戸岬", 33.25, 134.18), ("高知", 33.49, 133.58),
    ("土佐清水", 32.77, 132.96), ("宮崎", 31.90, 131.46), ("大分", 33.26, 131.70), ("横浜", 35.44, 139.66),
]


def frame_lonlat(ds=DS):
    ys, xs = np.mgrid[0:mc.H:ds, 0:mc.W:ds].astype(np.float32)
    lon = mc.LON0 + (xs - mc.XOFF) / mc.SCALE
    lat = mc.LAT1 - (ys - mc.YOFF) * mc.K_LAT / mc.SCALE
    return lat, lon


def to_xyz(lat, lon, depth_km=0.0):
    """局所平面(km)。経度は 35 度の縮尺。"""
    lat = np.asarray(lat, np.float64); lon = np.asarray(lon, np.float64)
    dep = np.broadcast_to(np.asarray(depth_km, np.float64), lat.shape)
    return np.stack([(lon - 136.0) * 111.32 * np.cos(np.radians(35.0)), (lat - 33.5) * 110.57, -dep], -1)


def seismic():
    f = pd.read_parquet(os.path.join(NANKAI, "data", "derived", "jshis_an177_fault_points.parquet"))
    cand = f[(f.depth_km >= 10) & (f.depth_km <= 25)]
    k = int(np.argmin(np.hypot(cand.lat - HYPO_NEAR[0], (cand.lon - HYPO_NEAR[1]) * 0.83)))
    hypo = cand.iloc[k]
    P = to_xyz(f.lat.values, f.lon.values, f.depth_km.values).astype(np.float32)
    h = to_xyz(hypo.lat, hypo.lon, hypo.depth_km).astype(np.float32)
    t_rup = np.linalg.norm(P - h, axis=1) / VR
    lat, lon = frame_lonlat()
    X = to_xyz(lat.ravel(), lon.ravel()).astype(np.float32)
    sub = np.arange(0, len(P), 3)
    Ps, ts = P[sub], t_rup[sub]
    t_s = np.full(len(X), np.inf, np.float32); t_p = np.full(len(X), np.inf, np.float32)
    for a in range(0, len(X), 8000):
        d = np.linalg.norm(X[a:a + 8000, None, :] - Ps[None, :, :], axis=2)
        t_s[a:a + 8000] = (ts[None, :] + d / VS).min(1)
        t_p[a:a + 8000] = (ts[None, :] + d / VP).min(1)
    # 震度: J-SHIS 250 m 点を 1/2 解像度の地図画素へ平均
    j = pd.read_parquet(os.path.join(NANKAI, "data", "derived", "jshis_nankai_intensity.parquet"), columns=["lat", "lon", "jma_intensity"])
    x, y = mc.proj(j.lat.values, j.lon.values)
    xi = (x / DS).astype(int); yi = (y / DS).astype(int); Wd, Hd = mc.W // DS, mc.H // DS
    ok = (xi >= 0) & (xi < Wd) & (yi >= 0) & (yi < Hd)
    idx = yi[ok] * Wd + xi[ok]
    s = np.bincount(idx, j.jma_intensity.values[ok], Hd * Wd); n = np.bincount(idx, minlength=Hd * Wd)
    jma = np.where(n > 0, s / np.maximum(n, 1), np.nan).reshape(Hd, Wd)
    hole = np.isnan(jma); near = distance_transform_edt(hole, return_distances=True, return_indices=True)
    dist, (iy, ix) = near
    jma = np.where(hole & (dist <= 3), jma[iy, ix], jma)
    out = dict(t_s=t_s.reshape(Hd, Wd), t_p=t_p.reshape(Hd, Wd), jma=jma.astype(np.float32),
               fault_lat=f.lat.values.astype(np.float32), fault_lon=f.lon.values.astype(np.float32), fault_depth=f.depth_km.values.astype(np.float32),
               t_rup=t_rup.astype(np.float32), hypo=np.array([hypo.lat, hypo.lon, hypo.depth_km], np.float32))
    return out


def load_etopo():
    import xarray as xr
    e = xr.open_dataset(os.path.join(NANKAI, "data", "external", "bathymetry", "etopo1_nankai.nc"))
    alt = e.altitude.values.astype(np.float32)           # [lat 28→41, lon 127→146]
    return e.latitude.values.astype(np.float64), e.longitude.values.astype(np.float64), alt


def initial_eta(lat, lon, alt):
    f = pd.read_parquet(os.path.join(NANKAI, "data", "derived", "jshis_an177_fault_points.parquet"))
    LO, LA = np.meshgrid(lon, lat)
    dep = griddata(np.c_[f.lon.values, f.lat.values], f.depth_km.values, (LO, LA), method="linear")
    up = 6.0 * np.exp(-((dep - 6.0) / 7.0) ** 2) - 1.5 * np.exp(-((dep - 30.0) / 7.0) ** 2)
    up = np.nan_to_num(up, nan=0.0)
    up = gaussian_filter(up, 3.0)                           # 1 分角で 3 格子 ≒ 5 km のなまし(海面への伝達の平滑化)
    return np.where(alt < 0, up, 0.0).astype(np.float32)


def swe(lat, lon, alt, eta0, t_end_min=200, snap_every_s=60.0, crop=None):
    """球面・Arakawa C 格子の線形長波方程式。陸は反射、外周はスポンジ。"""
    H0 = np.where(alt < 0, -alt, 0.0).astype(np.float32)
    H0 = np.where((H0 > 0) & (H0 < 10.0), 10.0, H0)
    wet = H0 > 0
    ny, nx = H0.shape
    dlam = np.radians(lon[1] - lon[0]); dphi = np.radians(lat[1] - lat[0])
    phi = np.radians(lat)[:, None].astype(np.float32)
    cos_c = np.cos(phi); cos_v = np.cos(phi + dphi / 2)     # v 面(j+1/2)
    dx_c = (R_E * cos_c * dlam).astype(np.float32); dy = np.float32(R_E * dphi)
    Hu = np.minimum(H0[:, :-1], H0[:, 1:]) * (wet[:, :-1] & wet[:, 1:])
    Hv = np.minimum(H0[:-1, :], H0[1:, :]) * (wet[:-1, :] & wet[1:, :])
    cmax = np.sqrt(G * H0.max()); dt = np.float32(0.45 * float(dx_c.min()) / cmax)
    eta = eta0.copy(); u = np.zeros((ny, nx - 1), np.float32); v = np.zeros((ny - 1, nx), np.float32)
    # スポンジ(外周 25 格子。陸側の縁は陸なので影響しない)
    ramp = np.ones((ny, nx), np.float32); nsp = 25
    for k in range(nsp):
        w = 1.0 - 0.02 * (1 - k / nsp) ** 2
        ramp[k, :] *= w; ramp[-1 - k, :] *= w; ramp[:, k] *= w; ramp[:, -1 - k] *= w
    nsteps = int(t_end_min * 60 / dt); snap_k = max(1, int(round(snap_every_s / dt)))
    snaps = []; t_arr = np.full((ny, nx), np.inf, np.float32); eta_max = np.zeros((ny, nx), np.float32)
    thr = 0.3
    t_arr[eta0 > thr] = 0.0                                  # 波源の直上(隆起域)は到達 0 分
    t0 = time.time()
    for n in range(nsteps + 1):
        if n % snap_k == 0:
            snaps.append((eta if crop is None else eta[crop]).astype(np.float16))
        # 連続式
        fu = Hu * u; fv = Hv * v * cos_v[:-1]
        div = np.zeros_like(eta)
        div[:, 1:-1] += (fu[:, 1:] - fu[:, :-1]) / dx_c
        div[1:-1, :] += (fv[1:, :] - fv[:-1, :]) / (dy * cos_c[1:-1])
        eta = (eta - dt * div) * wet
        # 運動量(前進後退)
        u = (u - dt * G * (eta[:, 1:] - eta[:, :-1]) / dx_c) * (Hu > 0)
        v = (v - dt * G * (eta[1:, :] - eta[:-1, :]) / dy) * (Hv > 0)
        eta *= ramp; u *= ramp[:, 1:]; v *= ramp[1:, :]
        tt = (n + 1) * dt
        hit = (eta > thr) & ~np.isfinite(t_arr)
        t_arr[hit] = tt
        np.maximum(eta_max, eta, out=eta_max)
    print(f"  SWE {nsteps} steps dt={dt:.2f}s  {time.time()-t0:.0f}s")
    return np.stack(snaps), t_arr, eta_max, float(dt) * snap_k


def eikonal(lat, lon, alt, eta0):
    """ホイヘンス型の最短走時(分)。c = sqrt(g h)、16 近傍、始点 = 初期水位が 0.5 m 以上隆起した海(沈降域は始点にしない)。"""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra
    H0 = np.where(alt < 0, np.maximum(-alt, 10.0), 0.0)
    wet = H0 > 0; ny, nx = H0.shape
    c = np.sqrt(G * H0)
    dphi = np.radians(lat[1] - lat[0]); dlam = np.radians(lon[1] - lon[0])
    dx = R_E * np.cos(np.radians(lat))[:, None] * dlam * np.ones((1, nx)); dy = R_E * dphi
    idx = np.arange(ny * nx).reshape(ny, nx)
    rows = []; cols = []; wts = []
    for oy, ox in ((0, 1), (1, 0), (1, 1), (1, -1), (1, 2), (2, 1), (1, -2), (2, -1)):
        y0, y1 = 0, ny - oy; x0, x1 = max(0, -ox), nx - max(0, ox)
        a = idx[y0:y1, x0:x1]; b = idx[y0 + oy:y1 + oy, x0 + ox:x1 + ox]
        ok = wet[y0:y1, x0:x1] & wet[y0 + oy:y1 + oy, x0 + ox:x1 + ox]
        L = np.hypot(ox * dx[y0:y1, x0:x1], oy * dy)
        ca = c[y0:y1, x0:x1]; cb = c[y0 + oy:y1 + oy, x0 + ox:x1 + ox]
        w = L * 0.5 * (1 / np.maximum(ca, 1e-3) + 1 / np.maximum(cb, 1e-3))
        rows.append(a[ok]); cols.append(b[ok]); wts.append(w[ok])
    g = coo_matrix((np.concatenate(wts), (np.concatenate(rows), np.concatenate(cols))), shape=(ny * nx, ny * nx)).tocsr()
    src = np.flatnonzero((eta0 > 0.5).ravel() & wet.ravel())
    d = dijkstra(g, directed=False, indices=src, min_only=True)
    return (d.reshape(ny, nx) / 60.0).astype(np.float32)


def coast_cell(lat, lon, alt, la, lo, min_depth=5.0):
    wet = alt < -min_depth
    yy, xx = np.nonzero(wet)
    j = int(np.argmin((lat[yy] - la) ** 2 + ((lon[xx] - lo) * np.cos(np.radians(la))) ** 2))
    return yy[j], xx[j]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--force", action="store_true"); a = ap.parse_args()
    os.makedirs(CACHE, exist_ok=True)
    fs = os.path.join(CACHE, "seismic.npz")
    if a.force or not os.path.exists(fs):
        t0 = time.time(); s = seismic(); np.savez_compressed(fs, **s)
        print(f"seismic: hypo {s['hypo']}  S 到達 max {np.nanmax(s['t_s']):.0f}s  {time.time()-t0:.0f}s")
    ft = os.path.join(CACHE, "tsunami.npz")
    if a.force or not os.path.exists(ft):
        lat, lon, alt = load_etopo()
        eta0 = initial_eta(lat, lon, alt)
        print(f"eta0: max {eta0.max():.2f} m min {eta0.min():.2f} m  海域セル {(np.abs(eta0)>0.5).sum()}")
        jy = (lat >= mc.LAT0 - 0.2) & (lat <= mc.LAT1 + 0.2); ix = (lon >= mc.LON0 - 0.2) & (lon <= mc.LON1 + 0.2)
        crop = (slice(int(np.argmax(jy)), int(len(jy) - np.argmax(jy[::-1]))), slice(int(np.argmax(ix)), int(len(ix) - np.argmax(ix[::-1]))))
        snaps, t_swe, eta_max, snap_dt = swe(lat, lon, alt, eta0, crop=crop)
        t0 = time.time(); t_eik = eikonal(lat, lon, alt, eta0); print(f"  eikonal {time.time()-t0:.0f}s")
        np.savez_compressed(ft, eta_snap=snaps, snap_dt=snap_dt, t_arr_swe=(t_swe / 60).astype(np.float32), t_arr_eik=t_eik, eta_max=eta_max,
                            eta0=eta0, alt=alt, lat=lat, lon=lon, crop_lat=lat[crop[0]], crop_lon=lon[crop[1]])
    d = np.load(ft)
    lat, lon, alt = d["lat"], d["lon"], d["alt"]
    print(f"\n{'地点':<8}{'SWE 初到達(分)':>14}{'走時(分)':>10}{'最大水位(m)':>12}")
    for name, la, lo in COAST_POINTS:
        j, i = coast_cell(lat, lon, alt, la, lo)
        print(f"{name:<8}{d['t_arr_swe'][j, i]:>14.1f}{d['t_arr_eik'][j, i]:>10.1f}{d['eta_max'][j, i]:>12.2f}")


if __name__ == "__main__":
    main()
