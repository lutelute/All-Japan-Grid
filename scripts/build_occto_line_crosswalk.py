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
    s = re.sub(r"\s+", "", str(s or ""))
    m = re.fullmatch(r"(.+?)[（(](変換|開閉|変|開|発)[)）]", s)
    if m:
        return m.group(1) + PAREN_KIND[m.group(2)]
    for a, b in SUFFIX:
        if s.endswith(a):
            return s[: -len(a)] + b
    return s


def resolvable(util: str, name: str, cache: dict) -> str:
    """解決器が引ける形の名前にする。種別の無い名前(中部・東北の「三重」「岩手」)は語尾を足して試す。"""
    from scripts.match_impedance_to_model import load_model, resolve
    key = (util, name)
    if key in cache:
        return cache[key]
    idx = cache.get(("_idx", util)) or cache.setdefault(("_idx", util), load_model(util)[0])
    pick = name
    if resolve(name, idx)[0] in ("unknown", "empty") and not name.endswith(KIND_SUFFIXES):
        for suf in KIND_SUFFIXES:
            if resolve(name + suf, idx)[0] not in ("unknown", "empty"):
                pick = name + suf
                break
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
                    "from": fa, "to": fb, "direction": r["direction"]})
    built_path = ROOT / "docs/data/built/all.json"
    raw = built_path.read_bytes()
    built = json.loads(raw)
    matched, tally = match_all(obs, built)

    by_key = {(m["util"], m["name"], m["direction"]): m for m in matched}
    recs = []
    for o in obs:
        m = by_key.get((o["util"], o["name"], o["direction"]))
        rec = {"area": o["util"], "line": o["name"], "kv": o["kv"], "direction": o["direction"],
               "from": o["from"], "to": o["to"], "conf": m["conf"] if m else None}
        if m:
            rec.update({k: m[k] for k in ("island", "segs", "path_km", "straight_km", "single_ended",
                                          "n_circ_obs") if k in m})
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


if __name__ == "__main__":
    sys.exit(main())
