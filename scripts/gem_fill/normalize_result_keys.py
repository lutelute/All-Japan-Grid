#!/usr/bin/env python3
"""wf_result.json の plant キーを正規化する(組立前の必須前処理).

捜索系エージェントは plant フィールドに「key+名前」("kyushu:225 諸塚水力発電所" 等)を
混ぜることがあり、そのままだと assemble_confirmed.py が無言スキップする(07-12に
ヒット2/3件を取りこぼしかけた実績)。先頭の region:idx を抽出して上書きする。
キーが取れない行(名前のみ)は gem_title が null のミス行であることを確認して残す。

使い方: python3 normalize_result_keys.py wf_result.json
"""
import json
import re
import sys

KEY = re.compile(r"^((?:hokkaido|tohoku|tokyo|chubu|hokuriku|kansai|chugoku|shikoku|"
                 r"kyushu|okinawa):\d+)\b")

path = sys.argv[1]
wf = json.load(open(path, encoding="utf-8"))
fixed, bad = 0, []
for sect in ("verdicts", "spots", "autoVer", "searches", "searchSpots"):
    for r in wf.get(sect, []):
        m = KEY.match(str(r.get("plant", "")))
        if not m:
            bad.append((sect, r.get("plant"), r.get("gem_title")))
            continue
        if m.group(1) != r["plant"]:
            r["plant"] = m.group(1)
            fixed += 1
json.dump(wf, open(path, "w"), ensure_ascii=False)
print("fixed keys:", fixed)
hit_bad = [b for b in bad if b[2]]
print("キー不能:", len(bad), "件(うちヒットあり=要手当:", len(hit_bad), ")")
for b in hit_bad:
    print("  REQUIRES FIX:", b)
