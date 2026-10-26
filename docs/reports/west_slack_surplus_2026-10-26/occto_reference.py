"""OCCTO の連系線の計画潮流(公表 kohyo_04)を、島の需要の合計(kohyo_02 のエリア需要)が
モデルと同じくらい(±3%)のコマだけで集計する。書き出すのは集計値(中央値・10/90 パーセンタイル)だけ。

    python docs/reports/west_slack_surplus_2026-10-26/occto_reference.py [data/external/occto]

モデルの需要は「各エリアのピーク × 負荷率 0.85」(config/regional_demand.yaml)で、特定の時刻ではない。
全コマの中央値だと需要の水準が違う時間帯が混ざるので、需要の合計が同じくらいのコマに絞って比べる。
符号は measure.py の zone_pairs と同じ「名前の辞書順で前のエリア → 後のエリア」を正にそろえる。
"""
import csv
import glob
import json
import os
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
D = sys.argv[1] if len(sys.argv) > 1 else str(HERE.parents[2] / "data/external/occto")
BAND = 0.03
AREA = {"中部": "chubu", "北陸": "hokuriku", "関西": "kansai", "中国": "chugoku", "四国": "shikoku",
        "九州": "kyushu", "東北": "tohoku", "東京": "tokyo"}
ISLANDS = {   # 島: (エリア, モデルの需要 MW = measure.py の load_mw)
    "west": (("中部", "北陸", "関西", "中国", "四国", "九州"), 73865.0),
    "east": (("東北", "東京"), 55250.0),
}
# 連系線: (モデルの組, OCCTO の順方向が組の向きと同じなら +1)。直流(阿南紀北・南福光)も受け渡しには数える
IC = {
    "三重東近江線": ("chubu->kansai", -1),          # OCCTO 順方向 = 関西→中部
    "越前嶺南線": ("hokuriku->kansai", +1),
    "関西-中国（東）": ("chugoku->kansai", -1),     # 順方向 = 関西→中国
    "関西-中国（西）": ("chugoku->kansai", -1),
    "本四連系線": ("chugoku->shikoku", +1),
    "関門連系線": ("chugoku->kyushu", +1),
    "阿南紀北直流幹線": ("kansai->shikoku", +1),
    "南福光連系所・南福光変電所の連系設備": ("chubu->hokuriku", +1),
    "相馬双葉幹線": ("tohoku->tokyo", +1),
}


def rows(pat):
    for f in sorted(glob.glob(os.path.join(D, pat))):
        with open(f, encoding="utf-8-sig") as fh:
            r = csv.reader(fh)
            next(r)
            head = next(r)
            for row in r:
                yield dict(zip(head, row))


demand = defaultdict(dict)
for r in rows("kohyo_02_*.csv"):
    if r["エリア名"] in AREA:
        demand[(r["対象年月日"], r["時刻"])][r["エリア名"]] = float(r["エリア需要(MW)"])
flow = defaultdict(lambda: defaultdict(float))
for r in rows("kohyo_04_*.csv"):
    spec = IC.get(r["連系線名"])
    if spec:
        try:
            flow[(r["対象年月日"], r["時刻"])][spec[0]] += spec[1] * float(r["順方向計画潮流(MW)"])
        except ValueError:
            pass


def q(xs, a):
    return xs[min(len(xs) - 1, int(a * len(xs)))]


out = {"source": "OCCTO 広域機関 公表 kohyo_02(エリア需要)・kohyo_04(連系線の計画潮流)", "band": BAND,
       "islands": {}, "area_export": {}}
for isl, (areas, load) in ISLANDS.items():
    keys = sorted(k for k in demand if all(a in demand[k] for a in areas) and k in flow)
    sel = [k for k in keys if abs(sum(demand[k][a] for a in areas) - load) <= BAND * load]
    names = {AREA[a] for a in areas}
    pairs = sorted({p for p, _ in IC.values() if set(p.split("->")) <= names})
    stats = {}
    for p in pairs:
        xs = sorted(flow[k][p] for k in sel if p in flow[k])
        if xs:
            stats[p] = {"median": round(st.median(xs), 1), "p10": round(q(xs, 0.1), 1), "p90": round(q(xs, 0.9), 1),
                        "share_positive": round(sum(x > 0 for x in xs) / len(xs), 3)}
    # エリアの受け渡しは、島の連系線が全部そろったコマだけで数える(欠けた線を 0 と数えると偏る。
    # 西では 708 コマのうち 183 コマで 3 本の行が無かった)
    full = [k for k in sel if all(p in flow[k] for p in pairs)]
    per = defaultdict(list)
    for k in full:
        e = defaultdict(float)
        for p in pairs:
            a, b = p.split("->")
            e[a] += flow[k].get(p, 0.0)
            e[b] -= flow[k].get(p, 0.0)
        for a, v in e.items():
            per[a].append(v)
    out["islands"][isl] = {"model_load_mw": load, "period": [keys[0][0], keys[-1][0]], "n_slots": len(keys),
                           "n_selected": len(sel), "n_selected_all_lines": len(full),
                           "missing_lines_in_selected": dict(sorted(Counter(
                               p for k in sel for p in pairs if p not in flow[k]).items())),
                           "pairs": stats}
    out["area_export"][isl] = {a: round(st.median(v), 1) for a, v in sorted(per.items())}
(HERE / "occto_reference.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(json.dumps(out, ensure_ascii=False)[:1500])
