#!/usr/bin/env python3
"""SubSLDフリップブックGIF — 読み方ガイド+全国機械生成の流し(2026-08-30).

素材=data/subsld/{region}/*.png(実証ペア図・build_subsld_batchの実出力)。
前半: 代表1所に読み方の注釈を重ねる3段 / 後半: 各地域の実例を流す。

出力: docs/slides/ajg/assets/subsld_flipbook.gif (subsldデッキと共用)
"""
import json, os
os.chdir("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid")
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 1600, 900
BG = (10, 13, 26)
FONT = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
def font(sz):
    try: return ImageFont.truetype(FONT, sz)
    except Exception: return ImageFont.load_default()

def _content_bbox(a, x0, x1):
    """列範囲[x0,x1)の非白画素の外接矩形。"""
    sub = a[:, x0:x1]
    ys, xs = np.where(sub)
    if len(xs) == 0:
        return None
    return (x0 + int(xs.min()), int(ys.min()),
            x0 + int(xs.max()) + 1, int(ys.max()) + 1)


def split_panels(im):
    """実証ペア図を [左=構内幾何, 右=単線結線図] に分割し、各々の余白を除去.

    元図は左右2パネル+大量の白余白で、そのまま16:9に嵌めると縦が律速して
    横幅の6割しか使えず図中ラベルが読めなかった(監査指摘)。パネルごとに
    外接矩形で切り出し、同じ高さに揃えて並べる。
    """
    a = (np.asarray(im).astype(int).sum(axis=2) < 720)   # 非白マスク
    colfrac = a.mean(axis=0)
    ink = np.where(colfrac >= 0.005)[0]
    if len(ink) == 0:
        return [im]
    lo, hi = int(ink.min()), int(ink.max()) + 1
    # 内側で最も広い白ガター = パネル境界
    blank, runs, cur = colfrac[lo:hi] < 0.005, [], None
    for i, v in enumerate(blank):
        if v and cur is None:
            cur = i
        elif not v and cur is not None:
            runs.append((cur, i)); cur = None
    runs = [r for r in runs if r[1] - r[0] > 25]
    def _drop_top_band(a, bb):
        """図の共通タイトル帯(左右に跨る1行)とその下の白余白を落とす。"""
        x0, y0, x1, y1 = bb
        rows = a[y0:y1, x0:x1].mean(axis=1)
        blank, run0 = rows < 0.004, None
        for i, v in enumerate(blank):
            if v and run0 is None:
                run0 = i
            elif not v and run0 is not None:
                if i - run0 >= 40 and run0 <= 0.45 * len(rows):
                    return (x0, y0 + i, x1, y1)     # 白帯の直後から採用
                run0 = None
        return bb

    # 中央寄りのガターだけを採用する。図の右端にある変圧器列との隙間を
    # 拾うと「細い帯」が独立パネルになって破綻するため(小曽根で実際に発生)
    span = hi - lo
    runs = [r for r in runs
            if 0.25 <= ((r[0] + r[1]) / 2) / span <= 0.75]
    panels = []
    if runs:
        g = min(runs, key=lambda r: abs((r[0] + r[1]) / 2 - span / 2))
        cut = lo + (g[0] + g[1]) // 2
        for x0, x1 in ((lo, cut), (cut, hi)):
            bb = _content_bbox(a, x0, x1)
            if bb:
                bb = _drop_top_band(a, bb)
                sub = _content_bbox(a[bb[1]:bb[3]], bb[0], bb[2])
                if sub:                      # subのyは相対 → 絶対へ戻す
                    panels.append(im.crop((sub[0], bb[1] + sub[1],
                                           sub[2], bb[1] + sub[3])))
    if not panels:
        bb = _content_bbox(a, lo, hi)
        if bb:
            bb = _drop_top_band(a, bb)
            sub = _content_bbox(a[bb[1]:bb[3]], bb[0], bb[2])
            bb = (sub[0], bb[1] + sub[1], sub[2], bb[1] + sub[3]) if sub else bb
            panels = [im.crop(bb)]
        else:
            panels = [im]
    return panels


def base_frame(png_path, name, reg):
    im = Image.open(png_path).convert("RGB")
    panels = split_panels(im)
    top, bot, gap, pad = 104, 118, 26, 10          # 見出し / 字幕 / パネル間
    ch = H - top - bot
    # 各パネルを同じ高さに揃える(横は成り行き)→ 中央寄せで並べる
    scaled = []
    for q in panels:
        r = (ch - 2 * pad) / q.height
        scaled.append(q.resize((max(1, int(q.width * r)),
                                max(1, int(q.height * r))), Image.LANCZOS))
    tw = sum(q.width for q in scaled) + gap * (len(scaled) - 1) + 2 * pad * len(scaled)
    if tw > W - 32:                                 # 幅が溢れる場合だけ縮める
        k = (W - 32) / tw
        scaled = [q.resize((max(1, int(q.width * k)), max(1, int(q.height * k))),
                           Image.LANCZOS) for q in scaled]
        tw = sum(q.width for q in scaled) + gap * (len(scaled) - 1) + 2 * pad * len(scaled)
    fr = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(fr)
    x = (W - tw) // 2
    for q in scaled:
        card = (x, top + (ch - q.height) // 2 - pad,
                x + q.width + 2 * pad, top + (ch + q.height) // 2 + pad)
        d.rectangle(card, fill=(255, 255, 255))
        fr.paste(q, (x + pad, top + (ch - q.height) // 2))
        x += q.width + 2 * pad + gap
    d.text((30, 18), name, font=font(34), fill=(255, 255, 255))
    d.text((30, 64), f"SubSLD法 — 構造DB+OSMタグのみで機械生成({reg})",
           font=font(19), fill=(142, 150, 184))
    return fr

def caption(fr, lines, color=(255, 214, 10)):
    fr = fr.copy(); d = ImageDraw.Draw(fr)
    y = H - 30 - 34 * len(lines)
    d.rectangle([16, y - 12, W - 16, H - 12], fill=(17, 21, 42))
    for i, t in enumerate(lines):
        d.text((32, y + 34 * i - 2), t, font=font(23), fill=color)
    return fr

SHOW = ("kansai", "新生駒変電所 500/275/154/77kV — 母線9・ベイ27・変圧器3",
        "data/subsld/kansai/kansai_site_81537a63e186.png")
FLIP = [
    ("kansai", "新奈良変電所(5階級)", "data/subsld/kansai/kansai_site_3c0fe6a96c0c.png"),
    ("tohoku", "新庄変電所 275/154/66", "data/subsld/tohoku/tohoku_site_974f25bb3e1f.png"),
    ("tokyo",  "西東京変電所 275/154", "data/subsld/tokyo/tokyo_site_1d18838708d5.png"),
    ("kansai", "小曽根電力所 275/154/77", "data/subsld/kansai/kansai_site_ff3251c9a1e0.png"),
    ("chubu",  "西名古屋変電所 275/154/77", "data/subsld/chubu/chubu_site_0bb01c8e2e01.png"),
]
F = []; D = []
b = base_frame(SHOW[2], SHOW[1], SHOW[0])
F.append(caption(b, ["読み方① 左=構内幾何 — 衛星写真の上に敷地・母線way・ベイ(実OSM要素)"])); D.append(3200)
F.append(caption(b, ["読み方② 右=単線結線図 — 横の太線=母線 / 縦ストローク=出線(本数=回線数)",
                     "二重円=変圧器 / 破線=leadin根拠 / BT=バスタイ"])); D.append(3800)
F.append(caption(b, ["読み方③ 全要素が構造DB(node-breaker)+OSM線タグ由来 — 捏造ゼロ",
                     "根拠が無い要素は描かれない(欠測は欠測のまま見せる)"],
                 color=(105, 240, 174))); D.append(3200)
for reg, name, p in FLIP:
    if os.path.exists(p):
        F.append(caption(base_frame(p, name, reg),
                         ["同じ手順が全国406所で機械生成済み(5地域・ギャラリー化)"],
                         color=(167, 176, 203))); D.append(1500)
out = "docs/slides/ajg/assets/subsld_flipbook.gif"
F[0].save(out, save_all=True, append_images=F[1:], duration=D, loop=0,
          optimize=True)
print(f"-> {out} ({len(F)}フレーム, {os.path.getsize(out)/1e6:.1f}MB)")
