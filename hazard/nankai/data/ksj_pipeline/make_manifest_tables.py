#!/usr/bin/env python3
"""DATA_MANIFEST.md 用の表を summary JSON / external の zip から生成して標準出力に出す (手書き本文に貼る)."""
import glob, json, os, re, hashlib
import geopandas as gpd
HERE = os.path.dirname(os.path.abspath(__file__)); DATA = os.path.dirname(HERE)
EXT = os.path.join(DATA, "external"); DER = os.path.join(DATA, "derived")
PREF = {"08":"茨城県","12":"千葉県","13":"東京都","14":"神奈川県","22":"静岡県","23":"愛知県","24":"三重県","26":"京都府","27":"大阪府","28":"兵庫県","29":"奈良県","30":"和歌山県","33":"岡山県","34":"広島県","35":"山口県","36":"徳島県","37":"香川県","38":"愛媛県","39":"高知県","40":"福岡県","42":"長崎県","43":"熊本県","44":"大分県","45":"宮崎県","46":"鹿児島県","47":"沖縄県"}
YEAR = {16:"2016(H28)",17:"2017(H29)",18:"2018(H30)",20:"2020(R2)",21:"2021(R3)",22:"2022(R4)",23:"2023(R5)",24:"2024(R6)"}
def mb(p): return f"{os.path.getsize(p)/1e6:.1f}"
def sha(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda: f.read(1<<20), b""): h.update(b)
    return h.hexdigest()[:12]
S = json.load(open(os.path.join(DER, "tsunami_inundation_A40_summary.json")))
print("## A40 zip 一覧\n\n| 県 | zip | 年版 | サイズ(MB) | sha256(先頭12) | 採用 |\n|---|---|---|---|---|---|")
for z in sorted(glob.glob(os.path.join(EXT,"ksj_A40","A40-*_GML.zip"))):
    m=re.match(r"A40-(\d\d)_(\d\d)_GML\.zip",os.path.basename(z)); v,p=int(m.group(1)),m.group(2)
    used = f"A40-{v}" in S.get(p,{}).get("versions_used",[])
    print(f"| {p} {PREF[p]} | `{os.path.basename(z)}` | {YEAR[v]} | {mb(z)} | `{sha(z)}` | {'採用' if used else '未採用(比較のみ)'} |")
print("\n## A40 県別結果\n\n| 県 | 採用版 | 方式 | 行数 | 面積 km² | 不正形状修復 | 未解釈区分 | 原典の区分文字列 |\n|---|---|---|---|---|---|---|---|")
tot=0; rows=0
for p in sorted(k for k in S if not k.startswith("_")):
    s=S[p]; cl=sorted({c["depth_class_src"] for c in s["classes"]})
    tot+=s["area_km2"]; rows+=s["rows"]
    print(f"| {p} {PREF[p]} | {' + '.join(s['versions_used'])} | {s['mode']} | {s['rows']:,} | {s['area_km2']:.1f} | {s['invalid_fixed']} | {s['unparsed_rows']} | {', '.join(cl)} |")
print(f"| 合計 | | | {rows:,} | {tot:.1f} | | | |")
print("\n## 区分 → depth_rank 対応 (県別・原典文字列ごと)\n\n| 県 | 版 | 原典の区分 (A40_003) | depth_min_m | depth_max_m | depth_rank | 行数 | 面積 km² |\n|---|---|---|---|---|---|---|---|")
for p in sorted(k for k in S if not k.startswith("_")):
    for c in sorted(S[p]["classes"], key=lambda c:(c["source_version"], c["depth_min_m"] if c["depth_min_m"] is not None else 1e9)):
        print(f"| {p} | {c['source_version']} | {c['depth_class_src']} | {c['depth_min_m']} | {'' if c['depth_max_m'] is None else c['depth_max_m']} | {c['depth_rank']} | {c['rows']:,} | {c['area_km2']:.2f} |")
print("\n## N03 zip 一覧\n\n| 県 | zip | サイズ(MB) | sha256(先頭12) |\n|---|---|---|---|")
for z in sorted(glob.glob(os.path.join(EXT,"ksj_N03","N03-*_GML.zip"))):
    p=re.search(r"_(\d\d)_GML",z).group(1); print(f"| {p} {PREF[p]} | `{os.path.basename(z)}` | {mb(z)} | `{sha(z)}` |")
m=gpd.read_file(os.path.join(DER,"municipalities.gpkg"),layer="muni")
print("\n## N03 県別市区町村数\n\n| 県 | 市区町村数 |\n|---|---|")
for p,n in m.groupby("pref_code").size().items(): print(f"| {p} {PREF[p]} | {n} |")
print(f"| 合計 | {len(m)} |")
import subprocess
print("\n## 出力ファイル (このタスクで生成したもののみ)\n\n| ファイル | サイズ(MB) | sha256(先頭12) | git |\n|---|---|---|---|")
mine = ["municipalities.gpkg", "municipalities_simplified.geojson", "tsunami_inundation_A40.gpkg",
        "tsunami_inundation_A40_simplified.geojson", "tsunami_inundation_A40_web.geojson", "tsunami_inundation_A40_summary.json"]
for n in mine:
    f = os.path.join(DER, n)
    if not os.path.exists(f): print(f"| `derived/{n}` | (未生成) | | |"); continue
    ign = subprocess.run(["git", "check-ignore", "-q", f], cwd=DATA).returncode == 0
    print(f"| `derived/{n}` | {mb(f)} | `{sha(f)}` | {'無視 (.gitignore)' if ign else '追跡'} |")
