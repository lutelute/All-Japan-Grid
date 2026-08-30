#!/usr/bin/env python3
"""SubSLDフリップブックGIF — 読み方ガイド+全国機械生成の流し(2026-08-30).

素材=data/subsld/{region}/*.png(実証ペア図・build_subsld_batchの実出力)。
前半: 代表1所に読み方の注釈を重ねる3段 / 後半: 各地域の実例を流す。

出力: docs/slides/ajg/assets/subsld_flipbook.gif (subsldデッキと共用)
"""
import json, os
os.chdir("/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid")
from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
BG = (10, 13, 26)
FONT = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
def font(sz):
    try: return ImageFont.truetype(FONT, sz)
    except Exception: return ImageFont.load_default()

def base_frame(png_path, name, reg):
    im = Image.open(png_path).convert("RGB")
    r = min((W - 40) / im.width, (H - 120) / im.height)
    im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
    fr = Image.new("RGB", (W, H), BG)
    fr.paste(im, ((W - im.width) // 2, 96))
    d = ImageDraw.Draw(fr)
    d.text((28, 16), name, font=font(30), fill=(255, 255, 255))
    d.text((28, 58), f"SubSLD法 — 構造DB+OSMタグのみで機械生成({reg})",
           font=font(17), fill=(142, 150, 184))
    return fr

def caption(fr, lines, color=(255, 214, 10)):
    fr = fr.copy(); d = ImageDraw.Draw(fr)
    y = H - 34 - 30 * len(lines)
    d.rectangle([16, y - 10, W - 16, H - 14], fill=(17, 21, 42))
    for i, t in enumerate(lines):
        d.text((30, y + 30 * i - 2), t, font=font(20), fill=color)
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
