#!/usr/bin/env python3
"""OCCTO の地内基幹送電線(潮流実績の線路)を、AGJ のモデルの線(鍵)に対応づける(潮流ビューアーの下ごしらえ).

OCCTO 系統情報サービスの潮流実績(統合 DB の occto_line_flow_30min、2026-11-06 から)は線路名と
「潮流方向(正方向)」(「北新得SS → 南早来SS」)だけを持ち、座標を持たない。地図に描くには、
両端の変電所をモデルの変電所に解決し、同じ電圧の線をたどる必要がある。

照合のやり方は scripts/export_obs_compare.py の match_all と同じ(各社の潮流実績で使っているもの):
両端の変電所名を解決 → 3 km 以内の同じ電圧の母線 → 同じ電圧の線の最短経路。経路の線名に OCCTO の
線名が入っていれば A、入っていなければ B(短い経路だけ)、片端と線名だけなら C(向きは判定しない)。

OCCTO の向きの書き方は社ごとに違うので、変電所名にそろえてから解決する:
  「北新得SS」→ 北新得変電所、「西双葉SWS」→ 西双葉開閉所、「北斗CS」→ 北斗変換所、「新三河」→ 新三河(そのまま)

入力は線路の一覧だけ(潮流の値は読まない): 統合 DB のビュー occto_lines、または同じ列の CSV。
出力: 線路ごとの照合(conf・経路の線の鍵と向き・回線数)と、エリア×照合の内訳。モデルの鍵は正典
(docs/data/built/all.json)を作り直すと替わるので、出力に正典の版(all.json の sha256 の頭)を書く。

使い方:
    PYTHONPATH=. python3 scripts/build_occto_line_crosswalk.py --db /mnt/nas03/db/pws.duckdb
    PYTHONPATH=. python3 scripts/build_occto_line_crosswalk.py --lines occto_lines.csv --out data/external/occto/occto_line_crosswalk.json
    # 統合 DB の台帳(occto_line_model_keys、線路×区間 1 行)も書く
    PYTHONPATH=. python3 scripts/build_occto_line_crosswalk.py --db /mnt/nas03/db/pws.duckdb \
        --parquet /mnt/nas03/db/parquet/occto_line_model_keys.parquet
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.export_obs_compare import match_all  # noqa: E402

DEFAULT_OUT = ROOT / "data" / "external" / "occto" / "occto_line_crosswalk.json"
# 向きの欄の略号 → 変電所名の語尾(長いものから当てる)
SUFFIX = [("SWS", "開閉所"), ("SS", "変電所"), ("CS", "変換所"), ("PS", "発電所"), ("S/S", "変電所")]


# 「日野（変）」「井原（開）」(中国)の括弧書きの種別
PAREN_KIND = {"変": "変電所", "開": "開閉所", "発": "発電所", "変換": "変換所", "開閉": "開閉所"}
KIND_SUFFIXES = ("変電所", "開閉所", "変換所", "発電所")


def station_name(s: str) -> str:
    import unicodedata
    s = re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(s or "")))
    s = re.sub(r"(sws|ss|cs|ps)$", lambda m: m.group(1).upper(), s)   # 九州は「中九州ss」と小文字
    m = re.fullmatch(r"(.+?)[（(](変換|開閉|変|開|発)[)）]", s)
    if m:
        return m.group(1) + PAREN_KIND[m.group(2)]
    for a, b in SUFFIX:
        if s.endswith(a):
            return s[: -len(a)] + b
    return s


# 解決の強さ(match_impedance_to_model.resolve の段階。左ほど強い)
LEVEL_RANK = {"exact": 0, "paren": 1, "suffix": 2, "contains": 3, "national": 4}
COMPANY = re.compile(r"(電力|\(株\)|（株）|株式会社)")


def is_branch(name: str) -> bool:
    """端が変電所でなく線や鉄塔のもの(T 分岐)。「山陰幹線」「新徳山幹線」「571T(西南多摩線)」"""
    n = re.sub(r"[（(][^）)]*[）)]", "", name)
    return bool(re.search(r"(線|幹線|支線|連絡線)$", n) or re.match(r"^\d+T", n))


def _stem(name: str) -> str:
    n = re.sub(r"[（(][^）)]*[）)]", "", str(name or ""))
    n = re.sub(r"\s*\d+(\.\d+)?\s*kV$", "", n).strip()
    n = re.sub(r"\s+", "", n)
    for suf in KIND_SUFFIXES:
        if n.endswith(suf):
            return n[: -len(suf)]
    return n


def _contains_ok(base: str, model_name: str) -> bool:
    """部分一致で拾ったモデルの名前が同じ所か。「岐阜」→「北岐阜」・「東栄」→「栄」・「名城」→「リニア… 名城」は弾く。
    「豊根」→「中部電力(株)豊根開閉所」のように頭に会社名が付くだけのものは採る"""
    for part in re.split(r"[;；/／]", str(model_name or "")):   # 「久留米変電所;久留米工務所」
        st = _stem(part)
        if st == base or (st.endswith(base) and COMPANY.search(st[: -len(base)])):
            return True
    return False


def resolvable(util: str, name: str, cache: dict) -> str:
    """解決器が正しく引ける名前にする。引けないとき(T 分岐・別の所しか当たらない)は空にする(片端の扱いになる)。

    OCCTO の向きの欄は社ごとに書き方が違う(「三重」は 三重開閉所、「豊根」は 豊根開閉所)。種別の語尾を
    付け替えた候補を全部試し、いちばん強く引けたものを採る(語尾の順で決めると「三重変電所」が別の地域の
    三重変電所に当たっていた)。部分一致(contains)は同じ所と言えるときだけ採る。
    """
    from scripts.match_impedance_to_model import load_model, resolve
    key = (util, name)
    if key in cache:
        return cache[key]
    if is_branch(name):
        cache[key] = ""
        return ""
    idx = cache.get(("_idx", util)) or cache.setdefault(("_idx", util), load_model(util)[0])
    base = _stem(name)
    cands = [name] + [base + suf for suf in KIND_SUFFIXES if base + suf != name]
    best = None
    for c in cands:
        lv, node = resolve(c, idx)
        if lv not in LEVEL_RANK:
            continue
        if lv == "contains" and not _contains_ok(base, (node or {}).get("name", "")):
            continue
        if best is None or LEVEL_RANK[lv] < best[0]:
            best = (LEVEL_RANK[lv], c)
    pick = best[1] if best else ""
    cache[key] = pick
    return pick


def split_direction(d: str) -> tuple[str, str] | None:
    parts = re.split(r"\s*(?:→|->|⇒|～|~)\s*", str(d or "").strip())
    if len(parts) != 2 or not all(parts):
        return None
    return station_name(parts[0]), station_name(parts[1])


def load_lines(args) -> list[dict]:
    if args.lines:
        with open(args.lines, encoding="utf-8") as f:
            return list(csv.DictReader(f))
    import duckdb
    con = duckdb.connect(str(args.db), read_only=True)
    cur = con.execute("SELECT area, voltage_kV, line, direction FROM occto_lines ORDER BY area, line")
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=Path("/mnt/nas03/db/pws.duckdb"))
    ap.add_argument("--lines", type=Path, help="occto_lines と同じ列の CSV(--db の代わり)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--parquet", type=Path, help="統合 DB の台帳 occto_line_model_keys の Parquet も書く")
    ap.add_argument("--report", type=Path, help="照合できなかった線路の理由の一覧(Markdown)も書く")
    a = ap.parse_args()

    lines = load_lines(a)
    obs, unparsed, cache = [], [], {}
    for r in lines:
        ends = split_direction(r["direction"])
        if not ends:
            unparsed.append(r)
            continue
        fa, fb = (resolvable(r["area"], e, cache) for e in ends)
        obs.append({"util": r["area"], "name": r["line"], "kv": float(r["voltage_kV"]),
                    "from": fa, "to": fb, "direction": r["direction"],
                    "from_occto": ends[0], "to_occto": ends[1]})
    built_path = ROOT / "docs/data/built/all.json"
    raw = built_path.read_bytes()
    built = json.loads(raw)
    matched, tally = match_all(obs, built)

    by_key = {(m["util"], m["name"], m["direction"]): m for m in matched}
    recs = []
    for o in obs:
        m = by_key.get((o["util"], o["name"], o["direction"]))
        rec = {"area": o["util"], "line": o["name"], "kv": o["kv"], "direction": o["direction"],
               "from": o["from_occto"], "to": o["to_occto"],
               "from_model_name": o["from"] or None, "to_model_name": o["to"] or None,
               "conf": m["conf"] if m else None}
        if m:
            rec.update({k: m[k] for k in ("island", "segs", "path_km", "straight_km", "single_ended",
                                          "n_circ_obs") if k in m})
        else:
            # 照合できなかった理由(export_obs_compare.match_all が残す)
            rec["why"] = o.get("_why")
            if o.get("_why_path"):
                rec["why_path"] = o["_why_path"]
            rec["diag"] = o.get("_diag")
        recs.append(rec)
    for r in unparsed:
        recs.append({"area": r["area"], "line": r["line"], "kv": float(r["voltage_kV"]),
                     "direction": r["direction"], "conf": None, "note": "向きの欄から両端を読めない"})

    area_n = Counter(r["area"] for r in recs)
    conf_n = defaultdict(Counter)
    for r in recs:
        conf_n[r["area"]][r["conf"] or "-"] += 1
    print(f"OCCTO の線路 {len(recs)} 本 → 照合 {len(matched)} 本(向きの欄が読めない {len(unparsed)} 本)")
    for ar in sorted(area_n):
        c = conf_n[ar]
        print(f"  {ar:9s} {area_n[ar]:3d} 本  A={c['A']:3d} B={c['B']:3d} C={c['C']:3d} 未={c['-']:3d}  "
              + " ".join(f"{k}={v}" for k, v in sorted(tally.get(ar, {}).items()) if not k.startswith("matched")))

    a.out.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "note": ("OCCTO 地内基幹送電線の潮流実績の線路 → AGJ のモデルの線の鍵。値(潮流)は含まない。"
                 "segs = 経路の区間ごとの [線の鍵, 向き(+1 はその線の from→to が OCCTO の正方向と同じ), 回線数]。"
                 "conf: A=名前と両端 B=両端のみ(短い経路) C=片端と線名(向きは判定しない) null=未照合"),
        "method": "scripts/build_occto_line_crosswalk.py(照合は scripts/export_obs_compare.py の match_all)",
        "built_sha256": hashlib.sha256(raw).hexdigest()[:12],
        "made_at": dt.datetime.now().isoformat(timespec="seconds"),
        "summary": {ar: dict(conf_n[ar]) for ar in sorted(conf_n)},
        "lines": recs,
    }
    a.out.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"-> {a.out}")
    if a.parquet:
        n = write_parquet(out, a.parquet)
        print(f"-> {a.parquet}({n} 行)")
    if a.report:
        write_report(out, built, a.report)
        print(f"-> {a.report}")
    return 0


def write_parquet(cw: dict, path: Path) -> int:
    """線路×区間 1 行にする(潮流と SQL でつなぐため)。未照合の線路も 1 行(model_key は空)で持つ。"""
    import os
    import tempfile

    import pandas as pd
    rows = []
    for r in cw["lines"]:
        base = {"area": r["area"], "line": r["line"], "voltage_kV": int(r["kv"]), "direction": r["direction"],
                "from_station": r.get("from"), "to_station": r.get("to"), "conf": r.get("conf"),
                "path_km": r.get("path_km"), "straight_km": r.get("straight_km"),
                "built_sha256": cw["built_sha256"], "made_at": cw["made_at"]}
        segs = r.get("segs") or []
        if not segs:
            rows.append({**base, "seg": None, "model_key": None, "sign": None, "circuits": None})
        for i, seg in enumerate(segs):
            for k, sign, par in seg:
                rows.append({**base, "seg": i, "model_key": k, "sign": int(sign), "circuits": int(par)})
    df = pd.DataFrame(rows)
    for c in ("seg", "sign", "circuits"):
        df[c] = df[c].astype("Int16")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".parquet")       # NAS へは手元で書いてから移す
    os.close(fd)
    df.to_parquet(tmp, index=False, compression="zstd")
    import shutil
    shutil.move(tmp, path)
    return len(df)



AREA_JA = {"hokkaido": "北海道", "tohoku": "東北", "tokyo": "東京", "chubu": "中部", "hokuriku": "北陸",
           "kansai": "関西", "chugoku": "中国", "shikoku": "四国", "kyushu": "九州", "okinawa": "沖縄"}
CATS = [
    ("okinawa", "沖縄(132 kV): 変電所の名前がモデルと合わない"),
    ("missing", "端の変電所・発電所がモデルに見つからない"),
    ("no_bus", "端の変電所はあるが、その電圧の母線がモデルに無い"),
    ("no_path", "両端はあるが、同じ電圧の線でつながらない"),
    ("path_rule", "経路は見つかったが、長すぎる・線名が合わないので採らなかった"),
]


def classify(r: dict) -> str:
    if r["area"] == "okinawa":
        return "okinawa"
    if not r.get("from_model_name") or not r.get("to_model_name") or r.get("why") == "unresolved_station":
        return "missing"
    if r.get("why") == "no_bus_at_voltage":
        return "no_bus"
    if r.get("why_path") in ("b_rejected_long", "detour_rejected", "ambiguous_name"):
        return "path_rule"
    return "no_path"


def write_report(cw: dict, built: dict, path: Path) -> None:
    """照合できなかった線路を、直す場所ごとに分けて書く(線路名と変電所名だけ。潮流の値は書かない)。"""
    un = [r for r in cw["lines"] if not r.get("conf")]
    groups = defaultdict(list)
    for r in un:
        groups[classify(r)].append(r)
    nodes = built["nodes"]

    def model_like(name: str) -> str:
        base = _stem(name)
        if len(base) < 2:
            return ""
        hits = sorted({(str(n.get("name")), int(n.get("kv") or 0), n.get("region")) for n in nodes
                       if base in str(n.get("name") or "")})[:3]
        return "、".join(f"{h[0]}({h[1]} kV・{AREA_JA.get(h[2], h[2])})" for h in hits)

    L = [f"# OCCTO の地内基幹送電線のうち、モデルの線に照合できないもの({cw['made_at'][:10]})", "",
         f"OCCTO の潮流実績に出てくる地内基幹送電線 {len(cw['lines'])} 本のうち {len(un)} 本は、両端の変電所から AGJ のモデルの線"
         "(正典 `docs/data/built/all.json`)にたどれないので、潮流マップに描けない。"
         f"照合は `scripts/build_occto_line_crosswalk.py`(正典の版 {cw['built_sha256']})。線路名と変電所名だけを載せ、潮流の値は載せない。", "",
         "| エリア | " + " | ".join(t for _, t in CATS) + " | 計 |", "|---|" + "---:|" * (len(CATS) + 1)]
    for ar in AREA_JA:
        row = [sum(1 for r in groups[k] if r["area"] == ar) for k, _ in CATS]
        if sum(row):
            L.append(f"| {AREA_JA[ar]} | " + " | ".join(str(x) for x in row) + f" | {sum(row)} |")
    L.append("| 計 | " + " | ".join(str(len(groups[k])) for k, _ in CATS) + f" | {len(un)} |")

    # 見つからない端(重複なし)
    ends = defaultdict(set)
    for r in groups["missing"]:
        for side in ("from", "to"):
            if not r.get(f"{side}_model_name"):
                ends[(r["area"], r[side])].add(r["line"])
    L += ["", "## 1. 端の変電所・発電所がモデルに見つからない", "",
          "「モデルで似た名前」は正典の全ノードを名前で探したもの(別の所のこともある)。"
          "空なら正典に無い。鉄塔番号(「571T」)や線名(「山陰幹線」)の端は分岐点で、変電所ではない。", "",
          "| エリア | OCCTO の端 | 種類 | この端を持つ線路 | モデルで似た名前 |", "|---|---|---|---|---|"]
    for (ar, nm), ls in sorted(ends.items(), key=lambda x: (list(AREA_JA).index(x[0][0]), x[0][1])):
        kind = "分岐点" if is_branch(nm) or "分岐" in nm else "変電所など"
        L.append(f"| {AREA_JA[ar]} | {nm} | {kind} | {'・'.join(sorted(ls))} | {model_like(nm) if kind != '分岐点' else ''} |")

    def table(rows, title, note):
        L.extend(["", title, "", note, "", "| エリア | 線路 | kV | OCCTO の向き | モデルの端 | 端の近く 3 km のモデルの母線の電圧 | 理由 |",
                  "|---|---|---:|---|---|---|---|"])
        for r in sorted(rows, key=lambda r: (list(AREA_JA).index(r["area"]), r["line"])):
            g = r.get("diag") or {}
            near = f"{g.get('from_kv_near', [])[:4]} / {g.get('to_kv_near', [])[:4]}"
            why = r.get("why_path") or r.get("why") or ""
            L.append(f"| {AREA_JA[r['area']]} | {r['line']} | {r['kv']:.0f} | {r['direction']} | "
                     f"{r.get('from_model_name') or '—'} / {r.get('to_model_name') or '—'} | {near} | {why} |")

    table(groups["no_bus"], "## 2. 端の変電所はあるが、その電圧の母線がモデルに無い",
          "モデルの変電所がその電圧を持っていない(低い電圧だけ)か、同じ名前の別の所に当たっている。")
    table(groups["no_path"], "## 3. 両端はあるが、同じ電圧の線でつながらない",
          "モデルの系統がその電圧で切れている(線が無い・別の電圧になっている)ことが多い。#38(OSM に無い送電線)と重なる。")
    table(groups["path_rule"], "## 4. 経路は見つかったが採らなかった",
          "線名の裏付けが無い経路が長すぎる(b_rejected_long・detour_rejected)、同じ名前の線が複数の向きにある(ambiguous_name)。"
          "照合の決まりを緩めるか、モデルの線名を足すかのどちらか。")
    table(groups["okinawa"], "## 5. 沖縄(132 kV)",
          "モデルの沖縄の変電所は OSM の位置から住所で名前を付けたもの(「牧港五丁目変電所」)が多く、OCCTO の名前(「牧港第一変電所」)と合わない。")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
