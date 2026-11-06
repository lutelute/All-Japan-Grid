#!/usr/bin/env python3
"""nas03 の公表データの保管庫が溜まり続けているかを確かめ、結果を保管庫に書く(2026-11-06).

scripts/nas_archive_cycle.sh daily の最後に呼ぶ(単独でも回せる)。見るもの:

  取得     OCCTO 一括ダウンロードの各種類が、どの日まで覆い終えたか(台帳 _manifest.json の to)。
           止まっていれば NG(当月を毎朝取り直す種類だけ。公開の終わりが今日より前の種類は数を出すだけ)
  書式     統合 DB に入れている種類の CSV の見出しが、最初のファイルと同じか(OCCTO が列を替えたら NG)
  統合DB   最新の月の CSV が、統合 DB(nas03-agent の日次ビルド、JST 08:00)の Parquet に入ったか
  公表API  occto_raw/kohyo/ の最新のファイルの日付
  10社     system_disclosure_raw/provenance.jsonl の最新の確認日(週次)
  空き     NAS の空き容量

結果は {NAS}/occto_raw/_status.txt(人が読む)と _status.json に書く。NG が 1 つでもあれば終了コード 1。
外部への通知はしない(研究室のサーバーに通知の仕組みが無いため。ログと _status を見る)。

使い方:
    python3 scripts/nas_archive_check.py                  # /mnt/nas03
    python3 scripts/nas_archive_check.py --nas /path/to/PWS_DB --no-write
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

# 覆い終えた日(to)が今日から何日まで遅れてよいか。None は数を出すだけ(公開の終わりが今日より前の種類)
LAG_DAYS = {
    "chinai_flow": 3,
    "chinai_capacity_result": 3,
    "interconnector_flow": 3,
    "interconnector_capacity_nd": 3,
    "demand_result_daily": 10,
    "outage_plan_result": 10,
    "frequency_50hz": 3,
    "frequency_60hz": 3,
    "fault_info": None,
    "re_curtailment_month": None,
}
# 統合 DB(DB整理/etl/db_sources.py)に入れている種類 → 表の名前
DB_TABLES = {
    "chinai_flow": "occto_line_flow_30min",
    "interconnector_flow": "occto_interconnector_5min",
    "chinai_capacity_result": "occto_line_capacity_daily",
}
DB_LAG_HOURS = 36      # CSV が替わってから Parquet に入るまで(ビルドは 1 日 1 回)
KOHYO_LAG_DAYS = 3
SD_LAG_DAYS = 9        # 週次
FREE_MIN_PCT = 5.0


def _csvs(d: Path, key: str) -> list[Path]:
    return sorted(p for p in d.glob(f"*/{key}_*.csv") if p.parent.name.isdigit())


def _head(p: Path) -> str:
    with p.open("rb") as f:
        return f.readline().decode("cp932", errors="replace").strip()


def check(nas: Path, today: dt.date) -> list[dict]:
    res: list[dict] = []

    def add(state: str, item: str, detail: str):
        res.append({"state": state, "item": item, "detail": detail})

    occto = nas / "occto_raw"
    for key, lag in LAG_DAYS.items():
        d = occto / key
        files = _csvs(d, key)
        try:
            man = json.loads((d / "_manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            man = {}
        if not files:
            add("NG", f"取得 {key}", "ファイルが無い")
            continue
        if not man:
            add("--", f"取得 {key}", f"{len(files)} 本(台帳はまだ無い。次の取得で作られる)")
            continue
        to = max(dt.date.fromisoformat(e["to"]) for e in man.values())
        at = max(e.get("at", "") for e in man.values())[:16]
        behind = (today - to).days
        detail = f"{len(files)} 本・{to} まで(最後の取得 {at})"
        if lag is None:
            add("--", f"取得 {key}", detail)
        else:
            add("OK" if behind <= lag else "NG", f"取得 {key}",
                detail + ("" if behind <= lag else f" — {behind} 日遅れ(許容 {lag} 日)"))

    for key, table in DB_TABLES.items():
        files = _csvs(occto / key, key)
        if not files:
            continue
        h0, h1 = _head(files[0]), _head(files[-1])
        add("OK" if h0 == h1 else "NG", f"書式 {key}",
            "最初のファイルと同じ見出し" if h0 == h1 else f"見出しが替わった: {h1[:120]}")
        last = files[-1]
        y, m = last.stem[-6:-2], last.stem[-2:]
        pq = nas / "db" / "parquet" / table / f"year={y}" / f"month={m}" / "data.parquet"
        if not pq.exists():
            add("NG", f"統合DB {table}", f"{y}-{m} の Parquet が無い")
            continue
        gap_h = (last.stat().st_mtime - pq.stat().st_mtime) / 3600
        if gap_h <= 0:
            detail = f"{y}-{m} まで入っている"
        elif gap_h <= DB_LAG_HOURS:
            detail = f"{y}-{m} の CSV が {gap_h:.0f} 時間前に替わり、次のビルド待ち"
        else:
            detail = f"{y}-{m} の CSV が Parquet より {gap_h:.0f} 時間新しい(ビルドが止まっている?)"
        add("OK" if gap_h <= DB_LAG_HOURS else "NG", f"統合DB {table}", detail)

    kohyo = sorted((occto / "kohyo").glob("*.csv"), key=lambda p: p.stat().st_mtime)
    if kohyo:
        age = (today - dt.date.fromtimestamp(kohyo[-1].stat().st_mtime)).days
        add("OK" if age <= KOHYO_LAG_DAYS else "NG", "公表API kohyo",
            f"最新 {kohyo[-1].name}(更新 {age} 日前)")
    else:
        add("NG", "公表API kohyo", "ファイルが無い")

    prov = nas / "system_disclosure_raw" / "provenance.jsonl"
    try:
        last_line = prov.read_text(encoding="utf-8").strip().splitlines()[-1]
        rec = json.loads(last_line)
        ts = next((rec[k] for k in ("fetched_at", "checked_at", "at", "ts") if k in rec), None)
        day = dt.date.fromisoformat(str(ts)[:10]) if ts else dt.date.fromtimestamp(prov.stat().st_mtime)
        age = (today - day).days
        add("OK" if age <= SD_LAG_DAYS else "NG", "10社 system_disclosure", f"最後の確認 {day}({age} 日前)")
    except (OSError, IndexError, ValueError):
        add("NG", "10社 system_disclosure", "provenance.jsonl が読めない")

    du = shutil.disk_usage(nas)
    free = du.free / du.total * 100
    add("OK" if free >= FREE_MIN_PCT else "NG", "空き", f"{du.free / 1e12:.1f} TB({free:.0f}%)")
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nas", type=Path, default=Path("/mnt/nas03"))
    ap.add_argument("--no-write", action="store_true", help="_status を書かずに表示だけ")
    args = ap.parse_args()
    now = dt.datetime.now()
    res = check(args.nas, now.date())
    ng = [r for r in res if r["state"] == "NG"]
    lines = [f"保管庫の確認 {now:%Y-%m-%d %H:%M}  NG {len(ng)} 件", ""]
    lines += [f"{r['state']:2s}  {r['item']:34s} {r['detail']}" for r in res]
    text = "\n".join(lines) + "\n"
    print(text, end="")
    if not args.no_write:
        out = args.nas / "occto_raw"
        (out / "_status.txt").write_text(text, encoding="utf-8")
        (out / "_status.json").write_text(json.dumps({"checked_at": now.isoformat(timespec="seconds"),
                                                      "ng": len(ng), "items": res},
                                                     ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
