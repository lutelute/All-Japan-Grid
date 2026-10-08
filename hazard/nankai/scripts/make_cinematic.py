#!/usr/bin/env python3
"""「夜の日本の灯りが消えて戻る」シネマティック可視化 (MP4 + GIF)。

    PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/make_cinematic.py <run_dir> <out_base>   # out_base.mp4 / out_base.gif / out_base_still.png

描画: 暗い列島 + 送電網の淡い光(正典 OSM 線形) + 需要の灯り(bloom) → 衝撃波 → 灯りが消える → 津波が海を渡り A40 浸水想定域を水没させる → 引き波 → 日ごとに灯りが戻る。
津波の水面は A40(国土数値情報・最大クラス)のポリゴンを地図解像度にラスタ化したもの(視認性のため 2 px 太らせる)。
到達順はトラフ軸から「海の上だけを通る最短経路長」(skimage MCP_Geometric・陸は通さず、浸水域の陸上は 1/3 速)で決めた演出で、
瀬戸内海には豊後水道・紀伊水道から回り込む。水深による速度差(浅海で遅い)は入れていないので津波伝播計算ではない。
灯りの強さ = sqrt(需要MW) × 受電可能確率(モンテカルロ平均)。北海道・沖縄は解析外なので一定の灯り。
"""
from __future__ import annotations
import argparse, json, os, sys, subprocess, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import numpy as np, pandas as pd, yaml
from scipy.ndimage import gaussian_filter, distance_transform_edt, grey_dilation
from PIL import Image, ImageDraw, ImageFont
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from nankai.grid import GridCase
from nankai.aggregate import customers_per_mw, bus_prefecture, naikakufu_region_of

NANKAI = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.abspath(os.path.join(NANKAI, "..", ".."))
W, H = 1920, 1080
LON0, LON1, LAT0, LAT1 = 129.0, 142.6, 30.4, 39.6     # 地図領域(九州〜南東北; 左 1180px に収める)
MAPW = 1180
FONT_B = "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc"; FONT_R = "/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc"; FONT_M = "/System/Library/Fonts/Menlo.ttc"
LABELS = {0: "発災直後", 0.25: "6 時間後", 0.5: "12 時間後", 1: "1 日後", 2: "2 日後", 3: "3 日後", 4: "4 日後", 5: "5 日後", 7: "1 週間後", 10: "10 日後", 14: "2 週間後", 21: "3 週間後", 30: "1 か月後", 45: "45 日後", 60: "2 か月後", 90: "3 か月後"}


K_LAT = np.cos(np.radians(35.0))
SCALE = min(MAPW / (LON1 - LON0), (H - 40) * K_LAT / (LAT1 - LAT0))   # px/deg(lon)
XOFF = 20; YOFF = (H - (LAT1 - LAT0) / K_LAT * SCALE) / 2


def proj(lat, lon):
    x = XOFF + (np.asarray(lon) - LON0) * SCALE
    y = YOFF + (LAT1 - np.asarray(lat)) / K_LAT * SCALE
    return x, y


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.truetype("/System/Library/Fonts/Hiragino Sans GB.ttc", size)


def raster_base():
    """陸(暗)と送電網(淡い青)のベース画像 [H,W,3] float と陸マスク。"""
    g = json.load(open(os.path.join(ROOT, "data", "reference", "japan_prefectures_simplified.geojson"), encoding="utf-8"))
    polys = []
    for f in g["features"]:
        geom = f["geometry"]; rings = geom["coordinates"][:1] if geom["type"] == "Polygon" else [p[0] for p in geom["coordinates"]]
        for r in rings:
            r = np.array(r); x, y = proj(r[:, 1], r[:, 0]); polys.append(np.c_[x, y])
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100); ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off"); fig.patch.set_facecolor("#04060d"); ax.set_facecolor("#04060d")
    for p in polys:
        ax.fill(p[:, 0], p[:, 1], color="#0c1222", ec="#1b2842", lw=0.6)
    fig.canvas.draw(); land = np.asarray(fig.canvas.buffer_rgba())[:, :, :3].astype(np.float32) / 255; plt.close(fig)
    land_mask = land[:, :, 2] > 0.09          # 陸 #0c1222(B=0x22=0.13) / 海 #04060d(B=0x0d=0.05)
    # 送電網
    b = json.load(open(os.path.join(ROOT, "docs", "data", "built", "all.json")))
    segs = []
    for e in b["edges"]:
        p = e.get("path") or [e["a"], e["b"]]
        p = np.array(p); x, y = proj(p[:, 0], p[:, 1]); segs.append(np.c_[x, y])
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100); ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off"); fig.patch.set_facecolor("black"); ax.set_facecolor("black")
    ax.add_collection(LineCollection(segs, colors="#6fa8ff", linewidths=0.5, alpha=0.9))
    fig.canvas.draw(); lines = np.asarray(fig.canvas.buffer_rgba())[:, :, :3].astype(np.float32) / 255; plt.close(fig)
    lum = lines[:, :, 2]
    glow = gaussian_filter(lum, 1.0) * 0.55 + gaussian_filter(lum, 5.0) * 0.35
    base = land + np.stack([glow * 0.25, glow * 0.45, glow * 0.9], -1)
    return np.clip(base, 0, 1), land_mask


def tsunami_raster():
    """A40 浸水想定域を地図ピクセルにラスタ化(値 = depth_rank 1..7, 0 = 浸水なし)。初回のみ rasterio で焼き、npy にキャッシュ。"""
    cache = os.path.join(NANKAI, "data", "derived", f"tsunami_A40_raster_{W}.npy")
    if os.path.exists(cache):
        return np.load(cache)
    import geopandas as gpd, rasterio
    from rasterio import features
    from affine import Affine
    g = gpd.read_file(os.path.join(NANKAI, "data", "derived", "tsunami_inundation_A40.gpkg"), layer="inundation", columns=["depth_rank"], bbox=(LON0, LAT0, LON1, LAT1))
    tr = Affine(1 / SCALE, 0, LON0 - XOFF / SCALE, 0, -K_LAT / SCALE, LAT1 + YOFF * K_LAT / SCALE)   # pixel(col,row) → (lon,lat); proj() の逆
    ras = features.rasterize(((geom, int(r)) for geom, r in zip(g.geometry.values, g.depth_rank.values)), out_shape=(H, W), transform=tr, fill=0, dtype="uint8", all_touched=True, merge_alg=rasterio.enums.MergeAlg.replace)
    np.save(cache, ras); return ras


def sea_travel(cost, start_mask, ds=2):
    """多始点 Dijkstra による到達距離場(px)。半解像度(min プーリングで海峡を閉じない)・16 近傍(桂馬跳び込み)で
    8 近傍の八角形の波面を円に近づける。scikit-image の MCP は近傍が 8 までなのでこちらを使う。"""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra
    from scipy.ndimage import zoom
    Hs, Ws = H // ds, W // ds
    c = cost[:Hs * ds, :Ws * ds].reshape(Hs, ds, Ws, ds).min(axis=(1, 3))
    st = start_mask[:Hs * ds, :Ws * ds].reshape(Hs, ds, Ws, ds).any(axis=(1, 3))
    idx = np.arange(Hs * Ws).reshape(Hs, Ws)
    rows = []; cols = []; wts = []
    for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1), (1, 2), (2, 1), (1, -2), (2, -1)):
        ln = float(np.hypot(dy, dx))
        y0, y1 = max(0, -dy), Hs - max(0, dy); x0, x1 = max(0, -dx), Ws - max(0, dx)
        a = idx[y0:y1, x0:x1]; b = idx[y0 + dy:y1 + dy, x0 + dx:x1 + dx]
        w = ln * 0.5 * (c[y0:y1, x0:x1] + c[y0 + dy:y1 + dy, x0 + dx:x1 + dx])
        rows.append(a.ravel()); cols.append(b.ravel()); wts.append(w.ravel())
    g = coo_matrix((np.concatenate(wts), (np.concatenate(rows), np.concatenate(cols))), shape=(Hs * Ws, Hs * Ws)).tocsr()
    d = dijkstra(g, directed=False, indices=np.flatnonzero(st.ravel()), min_only=True, limit=6000.0)
    d = np.minimum(np.nan_to_num(d, posinf=6000.0), 6000.0).reshape(Hs, Ws).astype(np.float32) * ds
    full = zoom(d, ds, order=1)
    out = np.full((H, W), 12000.0, np.float32); out[:full.shape[0], :full.shape[1]] = full
    return out


def light_layer(x, y, w, color, s_core=2.2, s_halo=9.0, gain=1.0):
    acc = np.zeros((H, W), np.float32)
    x = np.asarray(x); y = np.asarray(y); w = np.asarray(w)
    ok = (x >= 0) & (x < MAPW) & (y >= 0) & (y < H)          # 地図領域外(北東北以北など)は描かない
    xi = np.round(x[ok]).astype(int); yi = np.round(y[ok]).astype(int)
    np.add.at(acc, (yi, xi), w[ok])
    lay = gaussian_filter(acc, s_core) + 0.6 * gaussian_filter(acc, s_halo)
    lay = lay / max(np.percentile(lay[lay > 0], 99.5) if (lay > 0).any() else 1.0, 1e-9) * gain
    lay = 1 - np.exp(-lay)      # トーンマップ
    return lay[:, :, None] * np.array(color, np.float32)[None, None, :]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("run"); ap.add_argument("out"); ap.add_argument("--fps", type=int, default=12); a = ap.parse_args()
    rp = yaml.safe_load(open(os.path.join(NANKAI, "config", "restoration_default.yaml"))); T = [float(t) for t in rp["timeline_days"]]
    sc = yaml.safe_load(open(os.path.join(NANKAI, "config", "scenario_nankai.yaml")))
    tg = yaml.safe_load(open(os.path.join(NANKAI, "config", "calibration_targets.yaml")))["naikakufu_2025"]["outage_households"]["①東海_基本"]
    nk = {t: sum(tg[r][i] for r in ("tokai", "kinki", "sanyo", "shikoku", "kyushu")) for i, t in enumerate((0, 1, 4, 7))}
    # 解析母線
    parts = []; cust_all = []
    for isl in ("west", "east"):
        b = pd.read_parquet(os.path.join(a.run, isl, "bus_results.parquet")); case = GridCase.load(isl)
        cpm = customers_per_mw(b.groupby("zone").pd_mw.sum().to_dict()); c = b.pd_mw.to_numpy() * b.zone.map(cpm).fillna(0).to_numpy()
        reg = naikakufu_region_of(bus_prefecture(case)); b["five"] = np.isin(reg, ["tokai", "kinki", "sanyo", "shikoku", "kyushu"]); b["cust"] = c
        parts.append(b)
    bus = pd.concat(parts, ignore_index=True)
    # 解析外(北海道・沖縄)は一定の灯り
    built = json.load(open(os.path.join(ROOT, "docs", "data", "built", "all.json")))
    extra = [(n["lat"], n["lon"], n["region"]) for n in built["nodes"] if n["region"] in ("hokkaido", "okinawa") and n.get("sub") == 1]
    ex = pd.DataFrame(extra, columns=["lat", "lon", "region"]); ex["pd_mw"] = ex.region.map({"hokkaido": 3800 / max(1, (ex.region == "hokkaido").sum()), "okinawa": 900 / max(1, (ex.region == "okinawa").sum())})
    base, land_mask = raster_base()
    bx, by = proj(bus.lat.values, bus.lon.values); ex_x, ex_y = proj(ex.lat.values, ex.lon.values)
    wb = np.sqrt(np.clip(bus.pd_mw.values, 0.5, None)); we = np.sqrt(ex.pd_mw.values)
    junction = bus.is_junction.values; wb = np.where(junction, wb * 0.15, wb)
    # 衝撃波用: 断層多角形からの距離(ピクセル)
    poly = np.array(sc["trough_axis"] + sc["downdip_edge"][::-1]); px, py = proj(poly[:, 0], poly[:, 1])
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100); ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off"); fig.patch.set_facecolor("black")
    ax.fill(px, py, color="white"); fig.canvas.draw(); m = np.asarray(fig.canvas.buffer_rgba())[:, :, 0] > 128; plt.close(fig)
    dist = distance_transform_edt(~m)
    # 津波: 海(陸でも断層面でもない)・A40 浸水域ラスタ・到達順(断層面からの距離 + 陸上は 1/3 速)
    xs = np.arange(W)[None, :]
    axis = np.array(sc["trough_axis"]); ax_x, ax_y = proj(axis[:, 0], axis[:, 1])
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100); ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off"); fig.patch.set_facecolor("black")
    ax.plot(ax_x, ax_y, color="white", lw=2); fig.canvas.draw(); am = np.asarray(fig.canvas.buffer_rgba())[:, :, 0] > 128; plt.close(fig)
    sea = (~land_mask) & (xs < MAPW + 40)
    ras = tsunami_raster(); fl = grey_dilation(ras, size=(5, 5)).astype(np.float32)          # 2 px 太らせる(視認性)
    # 海の上だけを通る到達距離(px): 海=1, 浸水域の陸=3(内陸へは 1/3 速), その他の陸=事実上通行不可
    cost = np.where(sea, 1.0, np.where(fl > 0, 3.0, 1e4)).astype(np.float32)
    dist_axis = sea_travel(cost, am & (cost < 10))
    fl_alpha = np.where(fl > 0, 0.55 + 0.45 * np.clip(fl / 5.0, 0, 1), 0.0)                       # 深さランクで濃く
    d_inland = distance_transform_edt(land_mask)
    arrival = dist_axis                      # 内陸の減速(1/3 速)は経路コストに含めた
    water_col = np.array([0.06, 0.34, 0.80], np.float32); foam_col = np.array([0.85, 0.97, 1.0], np.float32)
    fb = font(FONT_B, 66); fm = font(FONT_B, 30); fs = font(FONT_R, 24); fnum = font(FONT_B, 120); fsmall = font(FONT_R, 20); fmono = font(FONT_M, 22)
    ts = bus.tsunami_rank.values > 0
    load_tot = bus.pd_mw.sum(); cust_tot = bus.cust.sum()

    def phys_at(t):
        """時刻 t(補間)での受電可能確率。"""
        if t <= T[0]:
            return bus[f"phys_t{T[0]:g}"].values
        for k in range(1, len(T)):
            if t <= T[k]:
                a0 = bus[f"phys_t{T[k-1]:g}"].values; a1 = bus[f"phys_t{T[k]:g}"].values; f = (t - T[k - 1]) / (T[k] - T[k - 1])
                return a0 + (a1 - a0) * f
        return bus[f"phys_t{T[-1]:g}"].values

    def compose(phys, title, sub, big=None, big_label=None, note=None, tline=None, shock_r=None, wave_r=None, flood_a=0.0, tint=0.0, ember=1.0, quake=False):
        """wave_r: 津波の先端半径(px, 断層面から)。flood_a: 浸水域の水面の濃さ(0..1)。tint: 引き波後に残す薄い浸水域の着色(0..1)。"""
        img = base.copy()
        lights = light_layer(np.r_[bx, ex_x], np.r_[by, ex_y], np.r_[wb * phys, we], (1.0, 0.93, 0.72), gain=1.6)
        img = np.clip(img + lights, 0, 1)
        if ember > 0:
            out = (1 - phys) * wb * (~junction)
            if out.sum() > 0:
                img = np.clip(img + light_layer(bx, by, out, (1.0, 0.28, 0.08), s_core=2.5, s_halo=8, gain=0.9) * ember, 0, 1)
        if wave_r is not None:
            # 海面のうねり: 先端の白い波頭 + 後続の 2 つの峰
            swell = np.zeros((H, W), np.float32)
            for k, (rr, amp, sg) in enumerate(((wave_r, 1.0, 7.0), (wave_r - 70, 0.55, 12.0), (wave_r - 150, 0.3, 18.0))):
                swell += amp * np.exp(-((dist_axis - rr) ** 2) / (2 * sg ** 2))
            swell *= sea * np.clip(1.0 - (dist_axis - 450.0) / 650.0, 0.2, 1.0)      # 遠方(回り込み先)は減衰
            img = np.clip(img + swell[:, :, None] * np.array([0.35, 0.75, 1.0], np.float32)[None, None, :] * 0.9, 0, 1)
            # 到達した浸水域を水面で覆う(灯り・熾火は水面の下に沈む)
            reach = np.clip((wave_r - arrival) / 6.0 + 0.5, 0, 1) * (fl > 0)
            a = (fl_alpha * reach * max(flood_a, 0.0))[:, :, None]
            img = img * (1 - 0.82 * a) + water_col[None, None, :] * 0.82 * a
            foam = np.exp(-((arrival - wave_r) ** 2) / (2 * 4.0 ** 2)) * (fl > 0) * flood_a
            foam = gaussian_filter(foam, 1.2)
            img = np.clip(img + foam[:, :, None] * foam_col[None, None, :], 0, 1)
        elif flood_a > 0:
            a = (fl_alpha * flood_a)[:, :, None]
            img = img * (1 - 0.9 * a) + water_col[None, None, :] * 0.9 * a
        if tint > 0:
            a = (fl_alpha * 0.35 * tint)[:, :, None]
            img = img * (1 - a) + water_col[None, None, :] * a
        if shock_r is not None:
            ring = np.exp(-((dist - shock_r) ** 2) / (2 * 28.0 ** 2)) * (dist > 0)
            img = np.clip(img + ring[:, :, None] * np.array([1.0, 0.55, 0.15])[None, None, :] * 0.85, 0, 1)
        pil = Image.fromarray((img * 255).astype(np.uint8)); d = ImageDraw.Draw(pil)
        # 右パネル
        X = MAPW + 40
        d.text((X, 70), title, font=fb, fill=(245, 240, 228))
        d.text((X, 160), sub, font=fs, fill=(170, 176, 190))
        if big is not None:
            d.text((X, 300), big, font=fnum, fill=(255, 120, 70))
            d.text((X, 440), big_label, font=fm, fill=(230, 226, 214))
        if note:
            y0 = 520
            for line in note.split("\n"):
                d.text((X, y0), line, font=fs, fill=(190, 196, 210)); y0 += 36
        # タイムライン
        if tline is not None:
            y = 900; x0 = X; x1 = W - 60
            d.line([(x0, y), (x1, y)], fill=(70, 80, 100), width=3)
            for tt, lab in ((0, "直後"), (1, "1日"), (7, "1週"), (30, "1月"), (90, "3月")):
                xx = x0 + (x1 - x0) * np.log10(1 + tt) / np.log10(91); d.line([(xx, y - 8), (xx, y + 8)], fill=(120, 130, 150), width=2); d.text((xx - 18, y + 16), lab, font=fsmall, fill=(150, 158, 175))
            xx = x0 + (x1 - x0) * np.log10(1 + tline) / np.log10(91); d.ellipse([xx - 11, y - 11, xx + 11, y + 11], fill=(255, 120, 70))
        d.text((X, H - 92), "All-Japan-Grid × 南海トラフ (J-SHIS Mw9.1 + A40)", font=fsmall, fill=(110, 118, 135))
        d.text((X, H - 64), "停電確率のモンテカルロ平均 N=200 ・ 灯り = √需要 × 受電可能確率", font=fsmall, fill=(110, 118, 135))
        d.text((30, H - 40), "光の網 = 正典の送電線(OSM 線形)  橙の熾火 = 停止中の変電所  青の水面 = A40 津波浸水想定域(視認性のため 2 px 太らせて描画)", font=fsmall, fill=(110, 118, 135))
        return pil

    frames = []; durs = []
    ones = np.ones(len(bus))
    def add(pil, sec): frames.append(pil); durs.append(sec)
    # 1 平時
    add(compose(ones, "ふだんの夜", "All-Japan-Grid 正典系統の灯り(九州〜関東)", note="灯りの明るさは需要(MW)の平方根。\n光の網は OSM 線形の送電線。", ember=0), 2.5)
    # 2 衝撃波
    for k in range(10):
        r = 40 + k * 95
        add(compose(ones, "南海トラフ Mw9.1", "地震動が広がる(J-SHIS 最大クラスの期待震度場)", shock_r=r, ember=0), 0.18)
    # 3 灯りが消える(補間)
    p0 = phys_at(0.0)
    for k in range(1, 7):
        f = k / 6; add(compose(ones * (1 - f) + p0 * f, "灯りが消える", "変電所の損傷・エリアの需給崩壊・上流孤立", ember=f), 0.22)
    # 4 津波: 海を渡って来る波 → 浸水域を水没 → 引き波(薄い着色を残す)
    n_ts = int(ts.sum())
    ts_note = f"浸水想定域の母線 {n_ts} 局(変電所は津波で 60 日級の復旧)\n揺れで既に消えた海岸の灯りと熾火を水面が覆う\nA40 は県公表の最大クラス想定(発生源を問わない包絡)"
    for k in range(22):
        r = 20 + k * 50
        add(compose(p0, "津波が押し寄せる", "国土数値情報 A40 浸水想定域(最大クラス・24 県)を水没", note=ts_note, wave_r=r, flood_a=1.0), 0.16)
    add(compose(p0, "津波が押し寄せる", "国土数値情報 A40 浸水想定域(最大クラス・24 県)を水没", note=ts_note, wave_r=20 + 21 * 50, flood_a=1.0), 1.2)
    for k in range(1, 7):
        f = k / 6
        add(compose(p0, "引き波", "浸水域の変電所は水に浸かったまま停止する", note=ts_note, flood_a=1.0 - f, tint=f), 0.18)
    # 5 時間経過
    def numbers(t, phys):
        out_all = float(((1 - phys) * bus.cust.values).sum()); out5 = float(((1 - phys) * bus.cust.values)[bus.five.values].sum())
        return out_all, out5
    steps = []
    for k in range(len(T) - 1):
        n = 8 if T[k + 1] <= 7 else 4
        for j in range(n):
            steps.append(T[k] + (T[k + 1] - T[k]) * j / n)
    steps.append(T[-1])
    for t in steps:
        phys = phys_at(t); out_all, out5 = numbers(t, phys)
        lab = LABELS.get(t) or (f"{t:g} 日後" if t >= 1 else f"{t*24:g} 時間後")
        if t not in LABELS:
            k = max([k for k in range(len(T)) if T[k] <= t]); lab = LABELS[T[k]] + " 〜"
        nkline = "".join(f"内閣府 2025 想定(五地域): {nk[tt]/1e4:,.0f} 万軒\n" for tt in (0, 1, 4, 7) if abs(t - tt) < 1e-9)
        note = f"うち五地域(東海・近畿・山陽・四国・九州) {out5/1e4:,.0f} 万軒\n{nkline}受電可能 {float((phys*bus.pd_mw.values).sum()/load_tot):.0%}"
        add(compose(phys, lab, "灯りが戻る — 系統モデルで計算した停電確率(平均)", big=f"{out_all/1e4:,.0f} 万軒", big_label="停電中の需要家(推定)", note=note, tline=t, tint=1.0), (1.6 if t in (0, 1, 4, 7, 30, 90) else 0.12))
    add(frames[-1], 3.0)
    # 出力
    tmp = tempfile.mkdtemp()
    for i, fr in enumerate(frames):
        fr.save(os.path.join(tmp, f"f{i:04d}.png"))
    lst = os.path.join(tmp, "l.txt")
    with open(lst, "w") as f:
        for i, dd in enumerate(durs):
            f.write(f"file '{os.path.join(tmp, f'f{i:04d}.png')}'\nduration {dd}\n")
        f.write(f"file '{os.path.join(tmp, f'f{len(durs)-1:04d}.png')}'\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-vf", f"scale={W}:{H},format=yuv420p", "-r", str(a.fps), "-c:v", "libx264", "-crf", "20", "-movflags", "+faststart", a.out + ".mp4"], check=True)
    # GIF(960px・間引き)
    import imageio.v2 as imageio
    sel = [(fr, dd) for fr, dd in zip(frames, durs)]
    gif_frames = []; gif_d = []
    acc = 0.0
    for fr, dd in sel:
        acc += dd
        if dd >= 1.0 or acc >= 0.3:
            gif_frames.append(np.asarray(fr.resize((960, 540), Image.LANCZOS))); gif_d.append(max(dd, 0.3) * 1000); acc = 0.0
    imageio.mimsave(a.out + ".gif", gif_frames, duration=gif_d, loop=0)
    frames[-1].save(a.out + "_still.png"); frames[0].save(a.out + "_night.png")
    print("frames", len(frames), "sec", round(sum(durs), 1), "mp4 MB", round(os.path.getsize(a.out + ".mp4") / 1e6, 1), "gif MB", round(os.path.getsize(a.out + ".gif") / 1e6, 1), "gif frames", len(gif_frames))


if __name__ == "__main__":
    main()
