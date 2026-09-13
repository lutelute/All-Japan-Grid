#!/usr/bin/env python3
"""地震と津波の「到達」表現 3 段階(既存 make_cinematic.py は残す)。

    PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/arrival_physics.py      # 先に物理を作る(キャッシュ)
    PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/make_arrival_variants.py --level 1 <run_dir> <out_base>

L1「物理の時計」  破壊が断層面を 2.7 km/s で走り、P 波・S 波の波面が実時間で広がる。S 波が通った所に J-SHIS の震度が焼き付き、
                  灯りが揺れてから消える。津波は √(gh) の走時で 10 分ごとの到達線を刻み、沿岸の浸水域は到達時刻に満ちる。
L2「海面を解く」  L1 の地震に地面の揺れ(波列)を重ね、津波は線形長波方程式の水位そのものを海に描く(海底地形の陰影つき)。
                  右に沿岸 4 点の水位変化(形のみ)を描き足す。
L3「カメラ」      L2 の物理を斜め上からの 2.5D にし、カメラが太平洋から紀伊水道・大阪湾へ寄っていく。

時間: 地震は発震から 300 秒を約 10 秒で、津波は 5〜180 分を約 17 秒で見せる(画面の時計は実時間)。
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
from scipy.ndimage import gaussian_filter, distance_transform_edt, map_coordinates, zoom, grey_dilation
from PIL import Image, ImageDraw

import make_cinematic as mc
import arrival_physics as ap
from nankai.grid import GridCase

W, H, MAPW = mc.W, mc.H, mc.MAPW
FPS = 12
JMA_COLORS = [(4.5, (1.00, 0.90, 0.25)), (5.0, (1.00, 0.62, 0.08)), (5.5, (1.00, 0.30, 0.06)), (6.0, (0.78, 0.05, 0.12)), (6.5, (0.55, 0.05, 0.38))]
JMA_LABELS = [("5弱", 0), ("5強", 1), ("6弱", 2), ("6強", 3), ("7", 4)]


def jma_rgb(j):
    rgb = np.zeros(j.shape + (3,), np.float32); a = np.zeros(j.shape, np.float32)
    for th, col in JMA_COLORS:
        m = j >= th
        rgb[m] = col; a[m] = 0.30
    return rgb, a


def glow(acc, s1=2.2, s2=9.0):
    return gaussian_filter(acc, s1) + 0.6 * gaussian_filter(acc, s2)


def splat(x, y, w):
    acc = np.zeros((H, W), np.float32)
    ok = (x >= 0) & (x < W) & (y >= 0) & (y < H)
    np.add.at(acc, (np.round(y[ok]).astype(int), np.round(x[ok]).astype(int)), w[ok])
    return acc


class Scene:
    def __init__(self, run):
        self.base, self.land = mc.raster_base()
        sc = np.load(os.path.join(ap.CACHE, "seismic.npz")); ts = np.load(os.path.join(ap.CACHE, "tsunami.npz"))
        up = lambda a: zoom(a, ap.DS, order=1)[:H, :W]
        self.t_s = up(sc["t_s"]); self.t_p = up(sc["t_p"])
        jm = sc["jma"]; self.jma = up(np.nan_to_num(jm, nan=0.0)); self.jma_rgb, self.jma_a = jma_rgb(self.jma); self.jma_a *= self.land
        fx, fy = mc.proj(sc["fault_lat"], sc["fault_lon"]); self.fx, self.fy, self.t_rup = fx, fy, sc["t_rup"]
        self.hypo = sc["hypo"]; self.hx, self.hy = [float(v) for v in mc.proj(self.hypo[0], self.hypo[1])]
        # フレーム画素 → ETOPO 格子
        ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
        lon = mc.LON0 + (xs - mc.XOFF) / mc.SCALE; lat = mc.LAT1 - (ys - mc.YOFF) * mc.K_LAT / mc.SCALE
        la, lo, alt = ts["lat"], ts["lon"], ts["alt"]
        self.er = (lat - la[0]) / (la[1] - la[0]); self.ec = (lon - lo[0]) / (lo[1] - lo[0])
        wet = alt < 0
        _, (iy, ix) = distance_transform_edt(~wet, return_indices=True)
        def fill(a):
            a = np.where(np.isfinite(a), a, 999.0).astype(np.float32); return a[iy, ix]
        samp = lambda a, order=1: map_coordinates(a, [self.er.ravel(), self.ec.ravel()], order=order, mode="nearest").reshape(H, W).astype(np.float32)
        self.t_eik = samp(fill(ts["t_arr_eik"])); self.t_swe = samp(fill(ts["t_arr_swe"]))
        self.alt = samp(alt)
        # 水位スナップショット(切り出し格子) → フレームへの座標
        cla, clo = ts["crop_lat"], ts["crop_lon"]
        self.cr = (lat - cla[0]) / (cla[1] - cla[0]); self.cc = (lon - clo[0]) / (clo[1] - clo[0])
        self.eta = ts["eta_snap"]; self.snap_min = float(ts["snap_dt"]) / 60.0
        self.mapm = np.zeros((H, W), np.float32); self.mapm[:, :MAPW + 10] = 1.0
        self.mapm[:, MAPW - 40:MAPW + 10] *= np.linspace(1, 0, 50)[None, :]
        self.mapm_wide = np.clip((mc.XOFF + (mc.LON1 + 0.18 - mc.LON0) * mc.SCALE - np.arange(W, dtype=np.float32)) / 90.0, 0, 1)[None, :] * np.ones((H, 1), np.float32)
        in_etopo = (self.ec >= 0) & (self.ec <= len(lo) - 1) & (self.er >= 0) & (self.er <= len(la) - 1)
        self.sea = ((~self.land) & in_etopo).astype(np.float32) * self.mapm
        # 浸水域(A40)
        ras = mc.tsunami_raster(); self.fl = grey_dilation(ras, size=(3, 3)).astype(np.float32)
        self.fl_alpha = np.where(self.fl > 0, 0.5 + 0.5 * np.clip(self.fl / 5.0, 0, 1), 0.0).astype(np.float32)
        d_in = distance_transform_edt(self.land)
        self.t_fl_eik = self.t_eik + d_in * 1.29 / 0.6      # 陸上は 0.6 km/分(36 km/h)で奥へ進む演出。1 px ≒ 1.29 km
        self.t_fl_swe = self.t_swe + d_in * 1.29 / 0.6
        # 灯り(母線)
        parts = []
        for isl in ("west", "east"):
            b = pd.read_parquet(os.path.join(run, isl, "bus_results.parquet"), columns=["lat", "lon", "pd_mw", "is_junction", "phys_t0"]); parts.append(b)
        bus = pd.concat(parts, ignore_index=True)
        built = json.load(open(os.path.join(mc.ROOT, "docs", "data", "built", "all.json")))
        ex = pd.DataFrame([(n["lat"], n["lon"], n["region"]) for n in built["nodes"] if n["region"] in ("hokkaido", "okinawa") and n.get("sub") == 1], columns=["lat", "lon", "region"])
        bx, by = mc.proj(bus.lat.values, bus.lon.values); ex_x, ex_y = mc.proj(ex.lat.values, ex.lon.values)
        wb = np.sqrt(np.clip(bus.pd_mw.values, 0.5, None)); wb = np.where(bus.is_junction.values, wb * 0.15, wb)
        self.bx, self.by, self.wb, self.p0 = bx, by, wb.astype(np.float32), bus.phys_t0.values.astype(np.float32)
        self.ex_x, self.ex_y = ex_x, ex_y
        # 母線ごとの S 波到達時刻(時間ビンでまとめて灯りを前計算)
        xi = np.clip(np.round(bx).astype(int), 0, W - 1); yi = np.clip(np.round(by).astype(int), 0, H - 1)
        self.bus_ts = self.t_s[yi, xi]; self.bus_j = self.jma[yi, xi]
        self.bins = np.linspace(0, 300, 21)
        k = np.clip(np.digitize(self.bus_ts, self.bins) - 1, 0, len(self.bins) - 2)
        self.lay_on = []; self.lay_t0 = []; self.lay_emb = []
        for b in range(len(self.bins) - 1):
            m = k == b
            self.lay_on.append(glow(splat(bx[m], by[m], wb[m])))
            self.lay_t0.append(glow(splat(bx[m], by[m], wb[m] * self.p0[m])))
            self.lay_emb.append(glow(splat(bx[m], by[m], (1 - self.p0[m]) * wb[m] * (~bus.is_junction.values[m])), 2.5, 8.0))
        self.lay_ex = glow(splat(ex_x, ex_y, np.sqrt(np.full(len(ex), 60.0, np.float32))))
        tot = sum(self.lay_on) + self.lay_ex
        self.norm = float(np.percentile(tot[tot > 0], 99.5)) / 1.6
        emb = sum(self.lay_emb); self.norm_e = float(np.percentile(emb[emb > 0], 99.5)) / 0.9 if (emb > 0).any() else 1.0
        self.bin_mid = 0.5 * (self.bins[:-1] + self.bins[1:])
        self.bin_j = np.array([float(np.nanmean(self.bus_j[k == b])) if (k == b).any() else 0 for b in range(len(self.bins) - 1)])
        self.rng = np.random.default_rng(7)
        # 海底地形の陰影(L2/L3)
        dep = np.clip(-self.alt, 0, 7000)
        gx = np.gradient(gaussian_filter(self.alt, 1.5), axis=1); gy = np.gradient(gaussian_filter(self.alt, 1.5), axis=0)
        shade = np.clip(0.5 + (-gx * 0.7 + -gy * 0.7) / 600.0, 0, 1)
        t = np.clip(dep / 6000.0, 0, 1) ** 0.6
        ocean = (1 - t)[..., None] * np.array([0.05, 0.16, 0.24]) + t[..., None] * np.array([0.01, 0.03, 0.08])
        ocean = ocean * (0.65 + 0.7 * shade[..., None])
        self.ocean = np.clip(ocean, 0, 1).astype(np.float32)
        # 沿岸点
        self.points = []
        for name, la_, lo_ in ap.COAST_POINTS:
            j, i = ap.coast_cell(la, lo, alt, la_, lo_)
            self.points.append(dict(name=name, lat=la_, lon=lo_, t_swe=float(ts["t_arr_swe"][j, i]), t_eik=float(ts["t_arr_eik"][j, i]),
                                    cj=int(np.argmin(np.abs(cla - la[j]))), ci=int(np.argmin(np.abs(clo - lo[i])))))
        self.city_s = [(n, float(self.t_s[int(np.clip(mc.proj(la_, lo_)[1], 0, H - 1)), int(np.clip(mc.proj(la_, lo_)[0], 0, W - 1))])) for n, la_, lo_ in
                       (("串本", 33.47, 135.78), ("高知", 33.56, 133.53), ("大阪", 34.69, 135.50), ("名古屋", 35.18, 136.91), ("静岡", 34.98, 138.38), ("福岡", 33.59, 130.40), ("東京", 35.68, 139.77))]

    # ---- 灯り ----
    def lights(self, t, shake=True):
        acc = self.lay_ex.copy(); emb = np.zeros((H, W), np.float32)
        for b in range(len(self.bin_mid)):
            ts_b = self.bin_mid[b]
            if t < ts_b:
                acc += self.lay_on[b]; continue
            dt = t - ts_b
            f = np.clip((dt - 8.0) / 25.0, 0, 1)                    # 揺れ始めて 8 秒後から 25 秒で落ちる
            fl = 1.0
            if shake and dt < 30:
                fl = 1.0 + 0.45 * np.clip((self.bin_j[b] - 4.5) / 2.0, 0, 1) * np.sin(dt * 9.0 + b) * np.exp(-dt / 15)
            acc += (self.lay_on[b] * (1 - f) + self.lay_t0[b] * f) * fl
            emb += self.lay_emb[b] * f
        lit = 1 - np.exp(-acc / self.norm)
        ember = 1 - np.exp(-emb / self.norm_e)
        return lit[..., None] * np.array([1.0, 0.93, 0.72], np.float32) + ember[..., None] * np.array([1.0, 0.28, 0.08], np.float32)

    def lights_final(self):
        if not hasattr(self, "_lf"):
            self._lf = self.lights(1e9, shake=False)
        return self._lf

    # ---- 地震 ----
    def stamp(self, img, t):
        """震度の焼き付け(S 波の通過後 10 秒で出る)。灯りの前に呼ぶ。"""
        a = self.jma_a * np.clip((t - self.t_s) / 10.0, 0, 1)
        return img * (1 - a[..., None]) + self.jma_rgb * a[..., None]

    def seismic_layers(self, img, t, ripple=False):
        if ripple:
            dt = t - self.t_s
            amp = np.clip((self.jma - 3.5) / 3.0, 0, 1) * self.land
            env = np.where(dt > 0, np.exp(-dt / (12.0 + 0.03 * np.maximum(self.t_s, 0))), 0.0)
            wave = np.cos(2 * np.pi * dt / 6.0) * env * amp
            img = img + (np.clip(wave, 0, 1) * 0.35)[..., None] * np.array([1.0, 0.85, 0.6], np.float32)
        # P 波(細い寒色)と S 波(暖色)の波面
        pf = np.exp(-((t - self.t_p) / 1.6) ** 2) * (t < 330) * self.mapm
        sf = np.exp(-((t - self.t_s) / 2.6) ** 2) * (t < 330) * self.mapm
        img = img + pf[..., None] * np.array([0.55, 0.75, 1.0], np.float32) * 0.35 + sf[..., None] * np.array([1.0, 0.72, 0.35], np.float32) * 0.8
        # 破壊の進行(断層点)
        dtr = t - self.t_rup
        flash = np.where(dtr >= 0, np.exp(-dtr / 6.0), 0.0).astype(np.float32)          # 破壊の先端だけが光る
        done = (dtr >= 0).astype(np.float32)
        if done.sum() > 0:
            if not hasattr(self, "_rup_norm"):
                self._rup_norm = float(np.percentile(glow(splat(self.fx, self.fy, np.ones_like(self.fx, dtype=np.float32)), 3.2, 8.0), 99.7))
            fl = glow(splat(self.fx, self.fy, flash), 3.2, 8.0) / self._rup_norm
            dn = gaussian_filter(splat(self.fx, self.fy, done), 4.0) / self._rup_norm
            img = img + (1 - np.exp(-fl * 2.5))[..., None] * np.array([1.0, 0.8, 0.5], np.float32) + (1 - np.exp(-dn * 0.25))[..., None] * np.array([0.6, 0.22, 0.08], np.float32)
        return img

    # ---- 津波 ----
    def eta_at(self, tmin):
        k = tmin / self.snap_min; k0 = int(np.clip(np.floor(k), 0, len(self.eta) - 1)); k1 = min(k0 + 1, len(self.eta) - 1); f = float(np.clip(k - k0, 0, 1))
        e = self.eta[k0].astype(np.float32) * (1 - f) + self.eta[k1].astype(np.float32) * f
        return map_coordinates(e, [self.cr.ravel(), self.cc.ravel()], order=1, mode="constant", cval=0.0).reshape(H, W) * self.sea

    def flood(self, img, tmin, t_fl):
        a = self.fl_alpha * np.clip((tmin - t_fl) / 6.0, 0, 1) * 0.85
        water = np.array([0.10, 0.45, 0.85], np.float32)
        img = img * (1 - a[..., None]) + water * a[..., None]
        edge = np.exp(-((tmin - t_fl) / 1.2) ** 2) * (self.fl > 0)
        return img + gaussian_filter(edge, 1.0)[..., None] * np.array([0.8, 0.95, 1.0], np.float32) * 0.8


def sea_surface(img, e):
    """水位 e[m] を海に描く。上昇 = 赤橙の発光、下降 = 暗くして青み。10 cm 未満は描かない。
    濃さは log(1 + (|e|-0.1)/0.3) を 8 m で 1 とする。津波伝播図の慣例(上昇=暖色・下降=寒色)に合わせた配色。"""
    mag = np.clip(np.log1p(np.maximum(np.abs(e) - 0.1, 0) / 0.3) / np.log1p(8.0 / 0.3), 0, 1)
    up = (e > 0).astype(np.float32)[..., None]
    k = mag[..., None]
    hot = np.array([1.0, 0.36, 0.10], np.float32) * (1 - k ** 2) + np.array([1.0, 0.9, 0.7], np.float32) * k ** 2
    cold = np.array([0.10, 0.35, 0.95], np.float32) * (1 - k ** 2) + np.array([0.6, 0.85, 1.0], np.float32) * k ** 2
    a = k ** 1.2
    out = img * (1 - 0.45 * a * (1 - up)) + up * hot * a * 0.95 + (1 - up) * cold * a * 0.55
    gx = np.gradient(gaussian_filter(e, 1.0), axis=1); gy = np.gradient(gaussian_filter(e, 1.0), axis=0)
    sheen = np.clip((-gx - gy) * 0.8, 0, 1) * mag
    return out + sheen[..., None] * 0.2


def text_panel(d, title, sub, lines=(), clock=None, x=None):
    x = x if x is not None else MAPW + 40
    fb = mc.font(mc.FONT_B, 64); fs = mc.font(mc.FONT_R, 24); fm = mc.font(mc.FONT_M, 76); fsm = mc.font(mc.FONT_R, 20)
    if clock:
        d.text((x, 60), clock, font=fm, fill=(255, 214, 150))
    d.text((x, 170), title, font=fb, fill=(245, 240, 228))
    d.text((x, 256), sub, font=fs, fill=(170, 176, 190))
    return fs, fsm


def fmt_clock(tsec):
    tsec = max(0, int(tsec)); h, r = divmod(tsec, 3600); m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}"


def render(level, run, out, probe=None):
    S = Scene(run)
    if level == 3:                                        # 斜め視点ではパネルが無いので、海面は計算範囲の端までぼかして描く
        land_ok = (S.sea > 0) | (S.mapm == 0)
        S.sea = ((~S.land) & (S.er >= 0) & (S.ec >= 0)).astype(np.float32) * S.mapm_wide
        S.mapm = S.mapm_wide
    fs = mc.font(mc.FONT_R, 24); fsm = mc.font(mc.FONT_R, 20); fmid = mc.font(mc.FONT_B, 30)
    frames_seis = np.r_[np.zeros(14), np.linspace(0, 300, 120)]               # 静止 1.2 秒 → 300 秒を 10 秒
    tsu = np.linspace(5, 180, 205)                                              # 5〜180 分を 17 秒
    writer = None if probe else subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                               "-vf", "format=yuv420p", "-c:v", "libx264", "-crf", "20", "-movflags", "+faststart", out + ".mp4"], stdin=subprocess.PIPE)
    gif = []; n_frame = [0]
    cam = Camera() if level == 3 else None

    def emit(img, force_gif=False):
        pil = Image.fromarray(np.clip(img * 255, 0, 255).astype(np.uint8)) if isinstance(img, np.ndarray) else img
        if probe:
            pil.save(f"{out}_probe_{n_frame[0]:04d}.png"); n_frame[0] += 1
            return pil
        writer.stdin.write(pil.tobytes())
        if n_frame[0] % 3 == 0 or force_gif:
            gif.append(pil.resize((960, 540), Image.LANCZOS))
        n_frame[0] += 1
        return pil

    footer = {1: "地震: キネマティック近似(破壊 2.7 km/s・S 波 3.82 km/s は内閣府 2012 強震断層モデル・破壊開始点は紀伊半島の南に仮置き)  震度: J-SHIS AN177   津波: √(gh) の最短走時(ETOPO1 1 分角)",
              2: "地震: キネマティック近似 + 震度で振幅を付けた波列(演出)   津波: 線形長波方程式(ETOPO1 1 分角・簡易波源)。振幅は定性、到達時刻の目安",
              3: "線形長波方程式(ETOPO1 1 分角・簡易波源)と J-SHIS AN177。高さは誇張。振幅は定性、到達時刻の目安"}[level]
    base_ocean = np.where(S.land[..., None], S.base, S.ocean) if level >= 2 else S.base
    still = None
    # ---------------- 地震 ----------------
    for i, t in enumerate(frames_seis):
        if probe and n_frame[0] not in probe:
            n_frame[0] += 1; continue
        img = S.stamp(base_ocean.copy(), t) + S.lights(t)
        img = S.seismic_layers(img, t, ripple=(level >= 2))
        img = np.clip(img, 0, 1)
        if level == 3:
            pil = cam.view(img, S, phase="seis", u=i / len(frames_seis), tsec=t)
            d = ImageDraw.Draw(pil); cam.ui(d, fmt_clock(t), "地震", "破壊が断層面を走り、揺れが広がる", footer)
        else:
            pil = Image.fromarray((img * 255).astype(np.uint8)); d = ImageDraw.Draw(pil)
            text_panel(d, "地震", "破壊が 2.7 km/s で断層面を走る" if t < 140 else "S 波が通った所に震度が焼き付く", clock=fmt_clock(t))
            y = 330
            d.text((MAPW + 40, y), "揺れ(S 波)が届くまで", font=fmid, fill=(230, 226, 214)); y += 50
            for name, tt in S.city_s:
                col = (255, 176, 90) if t >= tt else (120, 128, 145)
                d.text((MAPW + 60, y), f"{name}", font=fs, fill=col); d.text((MAPW + 250, y), f"{tt:4.0f} 秒", font=fs, fill=col); y += 38
            y += 20
            for lab, k in JMA_LABELS:
                c = tuple(int(255 * v) for v in JMA_COLORS[k][1]); d.rectangle([MAPW + 60 + k * 110, y, MAPW + 100 + k * 110, y + 22], fill=c); d.text((MAPW + 106 + k * 110, y - 2), lab, font=fsm, fill=(200, 204, 214))
            d.text((MAPW + 40, H - 150), "星 = 破壊開始点  橙の帯 = 破壊が進んだ断層面", font=fsm, fill=(150, 158, 175))
            d.text((MAPW + 40, H - 122), "細い青線 = P 波  太い橙線 = S 波", font=fsm, fill=(150, 158, 175))
            _star(d, S.hx, S.hy, t)
            _footer(d, footer)
        emit(pil)
    # ---------------- 津波 ----------------
    lit_f = S.lights_final()
    jma_final = S.jma_a[..., None] * 0.35                                                 # 震度は薄く残す
    base_t = (base_ocean if level >= 2 else S.base) * (1 - jma_final) + S.jma_rgb * jma_final
    base_t = np.clip(base_t + lit_f, 0, 1)
    marea = {p["name"]: p for p in S.points}
    gauges = ["串本", "高知", "大阪港", "名古屋港"]
    series = {g: S.eta[:, marea[g]["cj"], marea[g]["ci"]].astype(np.float32) for g in gauges}
    for i, tmin in enumerate(tsu):
        if probe and n_frame[0] not in probe:
            n_frame[0] += 1; continue
        if level == 1:
            img = base_t.copy()
            front = np.exp(-((tmin - S.t_eik) / 0.9) ** 2) * S.sea * (S.t_eik < 185)
            iso = np.exp(-(((S.t_eik + 5) % 10 - 5) / 0.28) ** 2) * (S.t_eik <= tmin) * S.sea * (S.t_eik > 1) * (S.t_eik < 185)
            wash = np.clip((tmin - S.t_eik) / 30.0, 0, 1) * np.exp(-np.maximum(tmin - S.t_eik, 0) / 90.0) * S.sea
            img = img + wash[..., None] * np.array([0.02, 0.12, 0.2], np.float32) + iso[..., None] * np.array([0.25, 0.6, 0.9], np.float32) * 0.55
            img = img + gaussian_filter(front, 2.0)[..., None] * np.array([0.5, 0.95, 1.0], np.float32) * 1.3
            img = S.flood(img, tmin, S.t_fl_eik)
        else:
            e = S.eta_at(tmin) * S.sea
            img = base_t.copy()
            img = sea_surface(img, e)
            img = S.flood(img, tmin, S.t_fl_swe)
        img = np.clip(img, 0, 1)
        if level == 3:
            he = S.eta_at(tmin) if level >= 2 else None
            pil = cam.view(img, S, phase="tsu", u=i / len(tsu), tsec=tmin * 60, eta=he)
            d = ImageDraw.Draw(pil); cam.ui(d, fmt_clock(tmin * 60), "津波", "海面の高まりが陸棚で遅れ、湾に回り込む", footer)
            _gauges(d, series, S.snap_min, tmin, x0=W - 540, y0=H - 380, w=470, h=52, box=True)
        else:
            pil = Image.fromarray((img * 255).astype(np.uint8)); d = ImageDraw.Draw(pil)
            text_panel(d, "津波", "√(gh) の走時: 深い海ほど速い" if level == 1 else "線形長波方程式で海面を解く", clock=fmt_clock(tmin * 60))
            y = 320
            d.text((MAPW + 40, y), "沿岸への到達(水位 0.3 m・目安)", font=fmid, fill=(230, 226, 214)); y += 48
            pts = sorted(S.points, key=lambda p: p["t_swe"])
            if level == 2:
                keep = ("串本", "尾鷲", "高知", "宮崎", "徳島", "和歌山", "名古屋港", "大阪港")
                pts = [p for p in pts if p["name"] in keep]
            for p in pts:
                tt = p["t_swe"] if level >= 2 else p["t_eik"]
                col = (120, 220, 255) if tmin >= tt else (110, 118, 135)
                lab = "0 分(波源の真上)" if tt < 0.5 else f"{tt:5.0f} 分"
                d.text((MAPW + 60, y), p["name"], font=fsm, fill=col); d.text((MAPW + 220, y), lab, font=fsm, fill=col); y += 29
            if level == 2:
                _gauges(d, series, S.snap_min, tmin, x0=MAPW + 40, y0=y + 50, w=620, h=56)
                d.text((MAPW + 40, H - 92), "赤 = 海面が上がる  青 = 下がる  白い縁 = 浸水域に水が届いた瞬間", font=fsm, fill=(150, 158, 175))
            else:
                d.text((MAPW + 40, H - 150), "細い線 = 10 分ごとの到達線  明るい線 = いまの波面", font=fsm, fill=(150, 158, 175))
                d.text((MAPW + 40, H - 122), "青 = A40 浸水想定域(到達時刻に満ちる)", font=fsm, fill=(150, 158, 175))
            _footer(d, footer)
        still = emit(pil)
        if abs(tmin - 110) < 0.45:
            still.save(out + "_still.png")
    if probe:
        print("probe done"); return
    for _ in range(int(2.5 * FPS)):
        emit(still, force_gif=False)
    writer.stdin.close(); writer.wait()
    import imageio.v2 as imageio
    imageio.mimsave(out + ".gif", [np.asarray(g) for g in gif], duration=[250] * len(gif), loop=0)
    print("level", level, "frames", n_frame[0], "sec", round(n_frame[0] / FPS, 1), "mp4 MB", round(os.path.getsize(out + ".mp4") / 1e6, 1), "gif MB", round(os.path.getsize(out + ".gif") / 1e6, 1))


def _star(d, x, y, t):
    r = 16 + 6 * np.sin(t * 0.8)
    pts = []
    for k in range(10):
        ang = -np.pi / 2 + k * np.pi / 5; rr = r if k % 2 == 0 else r * 0.45
        pts.append((x + rr * np.cos(ang), y + rr * np.sin(ang)))
    d.polygon(pts, fill=(255, 245, 210), outline=(255, 160, 60))


def _footer(d, text):
    fsm = mc.font(mc.FONT_R, 18)
    d.text((30, H - 34), text, font=fsm, fill=(120, 128, 145))


def _gauges(d, series, snap_min, tmin, x0, y0, w, h, box=False):
    fsm = mc.font(mc.FONT_R, 18)
    if box:
        d.rectangle([x0 - 16, y0 - 40, x0 + w + 16, y0 + len(series) * (h + 14) + 4], fill=(4, 8, 16))
    d.text((x0, y0 - 30), "水位の変化(形のみ・振幅は定性)", font=fsm, fill=(170, 176, 190))
    tt = np.arange(len(next(iter(series.values())))) * snap_min
    for k, (name, s) in enumerate(series.items()):
        yy = y0 + k * (h + 14)
        d.rectangle([x0, yy, x0 + w, yy + h], outline=(50, 60, 80))
        d.text((x0 + 6, yy + 2), name, font=fsm, fill=(150, 158, 175))
        m = tt <= tmin
        if m.sum() > 1:
            sc = max(float(np.abs(s).max()), 1e-3)
            xs = x0 + tt[m] / 180.0 * w; ys = yy + h / 2 - s[m] / sc * (h / 2 - 4)
            d.line(list(zip(xs.tolist(), ys.tolist())), fill=(120, 220, 255), width=2)


class Camera:
    """上から見た画像を斜め上からの眺めに変換する(射影変換 + 高さの視差 + 空と霞)。"""
    # (u_phase, 中心x, 中心y, 横幅px, 傾き) のキーフレーム
    KEYS = {"seis": [(0.0, 600, 560, 1300, 0.30), (1.0, 640, 600, 1150, 0.42)],
            "tsu": [(0.0, 640, 640, 1150, 0.45), (0.35, 560, 640, 900, 0.55), (0.7, 560, 560, 620, 0.62), (1.0, 700, 560, 1250, 0.45)]}

    def params(self, phase, u):
        ks = self.KEYS[phase]
        for a, b in zip(ks[:-1], ks[1:]):
            if a[0] <= u <= b[0]:
                f = (u - a[0]) / max(b[0] - a[0], 1e-9); f = f * f * (3 - 2 * f)
                return [a[i] + (b[i] - a[i]) * f for i in range(1, 5)]
        return list(ks[-1][1:])

    def view(self, img, S, phase, u, tsec, eta=None):
        cx, cy, span, tilt = self.params(phase, u)
        # 高さの視差: 陸の標高と海面(誇張)で上にずらす
        hgt = np.clip(S.alt, 0, 3000) / 3000.0 * 18.0
        if eta is not None:
            hgt = hgt + np.clip(eta, -3, 3) * 9.0
        ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
        src = np.stack([map_coordinates(img[..., c], [ys + hgt, xs], order=1, mode="nearest") for c in range(3)], -1)
        P = 900
        far = np.array([0.012, 0.03, 0.07], np.float32)
        if not hasattr(self, "_feather"):
            ey = np.minimum(np.arange(H), H - 1 - np.arange(H))[:, None]; ex = np.minimum(np.arange(W), W - 1 - np.arange(W))[None, :]
            ex = np.where(np.arange(W)[None, :] > MAPW, np.minimum(ex, np.maximum(0, W - 1 - np.arange(W)[None, :])), ex)
            self._feather = np.clip(np.minimum(ey, ex) / 220.0, 0, 1).astype(np.float32)[..., None]
        canvas = np.empty((H + 2 * P, W + 2 * P, 3), np.float32); canvas[:] = far
        canvas[P:P + H, P:P + W] = src * self._feather + far * (1 - self._feather)
        pil = Image.fromarray((np.clip(canvas, 0, 1) * 255).astype(np.uint8))
        cx += P; cy += P
        # 射影: 出力の四隅 ← 入力の台形
        near_w = span; far_w = span * (1 + 1.6 * tilt); depth = span * 0.62 * (1 + tilt)
        yb = cy + depth * 0.35; yt = cy - depth * 0.65
        quad_src = [(cx - far_w / 2, yt), (cx + far_w / 2, yt), (cx + near_w / 2, yb), (cx - near_w / 2, yb)]
        horizon = int(H * (0.10 + 0.25 * tilt))
        quad_dst = [(0, horizon), (W, horizon), (W, H), (0, H)]
        coeffs = _perspective_coeffs(quad_dst, quad_src)
        out = pil.transform((W, H), Image.PERSPECTIVE, coeffs, Image.BILINEAR)
        arr = np.asarray(out).astype(np.float32) / 255
        # 空と霞
        rows = np.arange(H, dtype=np.float32)[:, None]
        haze = np.clip(1 - (rows - horizon) / (H - horizon), 0, 1) ** 2.2
        sky = np.clip((horizon - rows) / max(horizon, 1), 0, 1)
        skycol = np.array([0.01, 0.02, 0.05], np.float32) * (1 - sky[..., None]) + np.array([0.0, 0.0, 0.01], np.float32) * sky[..., None]
        glowline = np.array([0.10, 0.16, 0.26], np.float32) * np.exp(-np.abs(horizon - rows[..., None]) / 22.0)
        arr = np.where(rows[..., None] < horizon, skycol, arr) + glowline
        arr = arr * (1 - 0.6 * haze[..., None]) + np.array([0.03, 0.06, 0.11], np.float32) * 0.6 * haze[..., None]
        # ビネットとレターボックス
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        vig = 1 - 0.35 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
        arr = arr * vig[..., None]
        bar = int(H * 0.09); arr[:bar] = 0; arr[H - bar:] = 0
        return Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8))

    def ui(self, d, clock, title, sub, footer):
        bar = int(H * 0.09)
        d.text((60, bar + 24), clock, font=mc.font(mc.FONT_M, 64), fill=(255, 214, 150))
        d.text((60, bar + 104), title, font=mc.font(mc.FONT_B, 52), fill=(245, 240, 228))
        d.text((60, bar + 176), sub, font=mc.font(mc.FONT_R, 26), fill=(190, 196, 210))
        d.text((60, H - bar + 30), footer, font=mc.font(mc.FONT_R, 18), fill=(130, 138, 155))


def _perspective_coeffs(dst, src):
    """PIL の PERSPECTIVE 係数(出力座標 → 入力座標)。"""
    A = []; B = []
    for (x, y), (X, Y) in zip(dst, src):
        A.append([x, y, 1, 0, 0, 0, -X * x, -X * y]); B.append(X)
        A.append([0, 0, 0, x, y, 1, -Y * x, -Y * y]); B.append(Y)
    return np.linalg.solve(np.array(A, float), np.array(B, float)).tolist()


def main():
    a = argparse.ArgumentParser(); a.add_argument("--level", type=int, choices=(1, 2, 3), required=True); a.add_argument("--probe", default="", help="確認用: このコマ番号だけ PNG に書く(例 40,90,200)")
    a.add_argument("run"); a.add_argument("out"); args = a.parse_args()
    render(args.level, args.run, args.out, probe={int(v) for v in args.probe.split(",") if v} or None)


if __name__ == "__main__":
    main()
