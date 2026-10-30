"""stats.json と正典から sites.jpg を描く(写真なので JPEG)。4 機の構内の点の空中写真に、網の線・前と後の繋ぎ先を重ねる。

    python docs/reports/plant_sites_by_eye_2026-10-30/fig.py

空中写真は国土地理院のシームレス空中写真(タイル)をその場で取る(出典: 国土地理院)。
"""
import io
import json
import math
import re
import urllib.request
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
plt.rcParams["font.family"] = ["Hiragino Sans", "Noto Sans CJK JP", "IPAexGothic", "sans-serif"]
INK, MUTED, BEFORE, AFTER, LINE = "#1f2328", "#8c959f", "#d97706", "#2563eb", "#e11d48"
Z = 17
PANELS = [("西名古屋火力発電所", "西名古屋火力 2,376 MW · 154 kV"), ("敦賀火力発電所", "敦賀火力 1,200 MW · 275 kV"),
          ("坂出火力発電所", "坂出火力 1,385 MW · 187 kV"), ("京極発電所", "京極 400 MW · 275 kV")]
DIRS = "東 北東 北 北西 西 南西 南 南東".split()


def tile_xy(lat, lon):
    n = 2 ** Z
    return ((lon + 180) / 360 * n,
            (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)


def aerial(lat, lon):
    x, y = tile_xy(lat, lon)
    tx, ty = int(x), int(y)
    im = Image.new("RGB", (768, 768))
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            u = f"https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{Z}/{tx + dx}/{ty + dy}.jpg"
            req = urllib.request.Request(u, headers={"User-Agent": "AGJ-report"})
            im.paste(Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=30).read())).convert("RGB"),
                     ((dx + 1) * 256, (dy + 1) * 256))

    def px(la, lo):
        a, b = tile_xy(la, lo)
        return (a - tx + 1) * 256, (b - ty + 1) * 256
    return im, px


def main():
    st = json.loads((HERE / "stats.json").read_text(encoding="utf-8"))
    built = json.loads((ROOT / "docs/data/built/all.json").read_text(encoding="utf-8"))
    sites = {}
    for f in sorted((ROOT / "data").glob("*_plants.geojson")):
        for ft in json.loads(f.read_text(encoding="utf-8"))["features"]:
            n = ft["properties"].get("name")
            if ft["geometry"]["type"] == "Point":
                sites.setdefault(n, (ft["geometry"]["coordinates"][1], ft["geometry"]["coordinates"][0]))
    fig = plt.figure(figsize=(12, 12.6), dpi=80)
    for k, (name, title) in enumerate(PANELS):
        b, a = st["before"]["plants"][name], st["after"]["plants"][name]
        sl = sites[name]
        im, px = aerial((sl[0] + a["lat"]) / 2, (sl[1] + a["lon"]) / 2)      # 発電所と後の繋ぎ先の中間
        ax = fig.add_axes([0.02 + 0.49 * (k % 2), 0.52 - 0.47 * (k // 2), 0.47, 0.42])
        ax.imshow(im)
        for e in built["edges"]:
            if abs((e["kv"] or 0) - a["kv"]) > 0.5:
                continue
            p = [px(*c) for c in (e.get("path") or [e["a"], e["b"]])]
            if any(0 <= x <= 768 and 0 <= y <= 768 for x, y in p):
                ax.plot([x for x, _ in p], [y for _, y in p], color=LINE, lw=1.6, alpha=0.8)
        sx, sy = px(*sites[name])
        ax.plot([sx], [sy], marker="s", ms=10, mfc="none", mec="white", mew=2.4)
        ax.plot([px(a["lat"], a["lon"])[0]], [px(a["lat"], a["lon"])[1]], marker="o", ms=13, mfc="none",
                mec=AFTER, mew=3)
        bx, by = px(b["lat"], b["lon"])
        ang = math.degrees(math.atan2(-(by - sy), bx - sx)) % 360
        d = DIRS[int(((ang + 22.5) % 360) // 45)]
        ax.set_xlim(0, 768); ax.set_ylim(768, 0); ax.set_axis_off()
        ax.set_title(title, fontsize=12, color=INK, loc="left")
        ax.text(8, 742, f"前: {re.sub(r' \d+kV$', '', b['bus'])} {b['kv']:.0f} kV · {b['km']} km {d}", fontsize=10, color="white",
                bbox=dict(facecolor=BEFORE, edgecolor="none", pad=3))
        bus = "構内の点(網の分岐点)" if " junction " in a["bus"] else re.sub(r" \d+kV$", "", a["bus"])
        ax.text(8, 700, f"後: {bus} {a['kv']:.0f} kV · {a['km']} km", fontsize=10, color="white",
                bbox=dict(facecolor=AFTER, edgecolor="none", pad=3))
    fig.text(0.02, 0.012, "□ 発電所の点 / ○ 後の繋ぎ先(網のバス) / 赤線 網の線(その電圧)。"
             "空中写真: 国土地理院 シームレス空中写真(約 0.75 km 四方)", fontsize=9, color=MUTED)
    fig.savefig(HERE / "sites.jpg", pil_kwargs={"quality": 80})
    print("sites.jpg")


if __name__ == "__main__":
    main()
