"""stats.json と正典から sites.png を描く。左: 名古屋港の周りの繋ぎ先の前後。右: 構内の点などの空中写真。

    python docs/reports/nagoya_port_sites_2026-10-29/fig.py

空中写真は国土地理院のシームレス空中写真(タイル)をその場で取る(出典: 国土地理院)。
"""
import io
import json
import math
import urllib.request
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
plt.rcParams["font.family"] = ["Hiragino Sans", "Noto Sans CJK JP", "IPAexGothic", "sans-serif"]
BOX = (34.78, 35.10, 136.78, 137.22)
INK, MUTED, BEFORE, AFTER = "#1f2328", "#8c959f", "#d97706", "#2563eb"
SITES = [("知多火力 構内の点(275kV)", (34.98810, 136.84663)), ("武豊 構内の点(154kV)", (34.82429, 136.92118)),
         ("碧南変電所 = 川口町五丁目(275kV)", (34.84124, 136.96482)), ("東海町六丁目(275kV・東海変電所と推定)", (35.05332, 136.89965))]


def aerial(lat, lon, z=17):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    tx, ty = int(x), int(y)
    im = Image.new("RGB", (768, 768))
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            u = f"https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{tx + dx}/{ty + dy}.jpg"
            req = urllib.request.Request(u, headers={"User-Agent": "AGJ-report"})
            im.paste(Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=30).read())).convert("RGB"),
                     ((dx + 1) * 256, (dy + 1) * 256))
    return im, (x - tx + 1) * 256, (y - ty + 1) * 256


def main():
    st = json.loads((HERE / "stats.json").read_text(encoding="utf-8"))
    built = json.loads((ROOT / "docs/data/built/all.json").read_text(encoding="utf-8"))
    fig = plt.figure(figsize=(14, 7.6), dpi=80)
    ax = fig.add_axes([0.03, 0.06, 0.50, 0.86])
    for e in built["edges"]:
        if (e["kv"] or 0) < 154 or not all(BOX[0] < c[0] < BOX[1] and BOX[2] < c[1] < BOX[3]
                                           for c in (e["a"], e["b"])):
            continue
        p = e.get("path") or [e["a"], e["b"]]
        ax.plot([c[1] for c in p], [c[0] for c in p], color=MUTED if e["kv"] < 275 else "#57606a",
                lw=0.6 if e["kv"] < 275 else 1.3, zorder=1)
    plants = json.loads((ROOT / "data/chubu_plants.geojson").read_text(encoding="utf-8"))["features"]
    at = {f["properties"].get("name"): f["geometry"]["coordinates"][:2] for f in plants
          if f["geometry"]["type"] == "Point"}
    for name, b in st["before"]["plants"].items():
        a = st["after"]["plants"][name]
        if not (BOX[2] < at[name][0] < BOX[3]):          # 川越は範囲の外(三重)
            continue
        lon, lat = at[name]
        ax.plot([lon, b["lon"]], [lat, b["lat"]], color=BEFORE, lw=1.6, ls="--", zorder=2)
        ax.plot([lon, a["lon"]], [lat, a["lat"]], color=AFTER, lw=2.2, zorder=3)
        ax.scatter([lon], [lat], marker="s", s=40, color=INK, zorder=4)
        ax.annotate(f"{name.replace('発電所', '')} {b['mw']:,} MW", (lon, lat), xytext=(4, 4),
                    textcoords="offset points", fontsize=8, color=INK)
    ax.plot([], [], color=BEFORE, ls="--", label="前(main の台帳)")
    ax.plot([], [], color=AFTER, label="後(構内の点・公表の相手)")
    ax.legend(loc="lower right", fontsize=9, frameon=False)
    ax.set_xlim(BOX[2], BOX[3]); ax.set_ylim(BOX[0], BOX[1])
    ax.set_aspect(1 / math.cos(math.radians(35.0)))
    ax.tick_params(labelsize=7, colors=MUTED)
    ax.set_title("発電所(■)から繋ぎ先のバスへ。灰色は 154kV(細)・275kV 以上(太)の網", fontsize=10, color=INK)
    for k, (title, (lat, lon)) in enumerate(SITES):
        im, px, py = aerial(lat, lon)
        a2 = fig.add_axes([0.55 + 0.225 * (k % 2), 0.50 - 0.45 * (k // 2), 0.21, 0.40])
        a2.imshow(im)
        a2.add_patch(plt.Circle((px, py), 22, fill=False, color="#e11d48", lw=2))
        a2.set_axis_off()
        a2.set_title(title, fontsize=9, color=INK)
    fig.text(0.55, 0.02, "空中写真: 国土地理院 シームレス空中写真(約 0.9 km 四方・赤丸が網のバスの位置)",
             fontsize=8, color=MUTED)
    fig.savefig(HERE / "sites.png")
    print("sites.png")


if __name__ == "__main__":
    main()
