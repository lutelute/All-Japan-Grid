#!/usr/bin/env python3
"""Publish the hazard support data to nas03 (PWS_DB share, mounted at /mnt/nas03 on pws-160core).

  ~/agj-hazard-data/.venv/bin/python ~/agj-hazard-data/scripts/publish_nas.py

1. raw files  -> /mnt/nas03/hazard_raw/{D1_tepco_transformers,...}/  (+ README.md per folder, top README.md)
2. manifest   -> /mnt/nas03/hazard_raw/manifest.jsonl  (adds nas_path to each line)
3. tables     -> /mnt/nas03/db/parquet/hazard_support/{table}.parquet  (written locally, then copied)
4. SQLite     -> /mnt/nas03/db/hazard_support.sqlite  (built on local disk, copied; never written in place)
5. /mnt/nas03/README.md: insert tree lines and status-table rows for hazard_raw / db (idempotent,
   existing lines are left untouched; a backup is kept in ~/agj-hazard-data/work/).
Does not touch pws.duckdb, *_views.sql, db_pipeline/, other *_raw folders or #recycle.
"""
import datetime as dt
import json
import shutil
import sqlite3
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path.home() / "agj-hazard-data"
NAS = Path("/mnt/nas03")
HRAW = NAS / "hazard_raw"
PQ = NAS / "db" / "parquet" / "hazard_support"
JST = dt.timezone(dt.timedelta(hours=9))
TODAY = dt.datetime.now(JST).strftime("%Y-%m-%d")

FOLDERS = {
    "D1": ("D1_tepco_transformers", "送変電設備: 東京電力PG・中部電力PGの空容量一覧(変圧器台数・設備容量、送電線)、設備計画、鹿島地区の発電所接続",
           "hv_transformers, hv_lines, plant_connections",
           "東京電力PG・中部電力PGの系統情報は各社著作物で『転載禁止』表記あり。研究室内部の検証用に限り、設備別の生値を外部へ再配布しない"),
    "D2": ("D2_population", "令和2年国勢調査 都道府県・市区町村別の主な結果(人口・世帯)", "municipal_population",
           "e-Stat(政府統計の総合窓口)利用規約。出典を記載すれば二次利用可"),
    "D3": ("D3_housing", "令和5年住宅・土地統計調査 第6-3表 住宅の種類・構造(木造/非木造)×建築の時期 別住宅数(市区町村)", "municipal_housing",
           "e-Stat 利用規約。出典記載で二次利用可"),
    "D4": ("D4_damage_functions", "内閣府(中央防災会議)の被害想定手法資料と、それを転記した県の手法資料(建物全壊・電柱被害・火力停止率)", "damage_functions",
           "内閣府防災情報のページは政府標準利用規約準拠(出典記載)。県資料は各県の著作物(出典明示の引用)"),
    "D5": ("D5_utility_offices", "一般送配電事業者10社の事業所一覧ページ(公式)と国土地理院 住所検索APIの応答キャッシュ", "utility_offices",
           "各社サイトの著作物(出典明示)。座標は国土地理院 地名・住所検索API(国土地理院コンテンツ利用規約)"),
    "D6": ("D6_utility_scale", "電力10社の有価証券報告書(FY2025)・会社概要ページ、電力・ガス取引監視等委員会 電力取引報(契約口数)", "utility_scale",
           "有価証券報告書・会社ページは各社著作物(出典明示)。電力取引報は政府標準利用規約(出典記載)"),
    "D7": ("D7_restoration_records", "過去災害の停電・復旧記録(経産省・内閣府・OCCTO・各社の検証報告/プレス資料)", "restoration_records",
           "政府資料は政府標準利用規約(出典記載)。各社・団体資料は各々の著作物(出典明示の引用)"),
}


def human(n):
    for u in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.0f}{u}" if u == "B" else f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}TB"


def rsync(src, dst):
    dst.mkdir(parents=True, exist_ok=True)
    subprocess.run(["rsync", "-rt", "--no-perms", "--no-owner", "--no-group", "--modify-window=2",
                    "--exclude", "csv/", f"{src}/", f"{dst}/"], check=True)


def main():
    man = [json.loads(l) for l in (ROOT / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    by = defaultdict(list)
    for r in man:
        by[r["dataset"]].append(r)

    # 1. raw files + per-folder README
    for d, (folder, desc, tables, lic) in FOLDERS.items():
        src = ROOT / "raw" / d
        dst = HRAW / folder
        rsync(src, dst)
        rows = []
        for r in sorted(by[d], key=lambda x: x["local_path"]):
            rel = Path(r["local_path"]).relative_to(src)
            r["nas_path"] = str(dst / rel)
            rows.append(f"| `{rel}` | {human(r['bytes'])} | {r['retrieved_at'][:16]} | {r['url']} | {r.get('license', '')} |")
        readme = f"""# hazard_raw/{folder}

{desc}

- **用途**: 南海トラフ地震の電力ハザード解析(All-Japan-Grid `feature/nankai-hazard`, `hazard/nankai/`)の補助データ
- **正規化先**: `../../db/hazard_support.sqlite` と `../../db/parquet/hazard_support/` のテーブル `{tables}`
- **取得**: pws-160core `~/agj-hazard-data/scripts/fetch.py`(ブラウザUA・取得時にsha256とURLを manifest に記録)
- **取得日**: {min(x['retrieved_at'] for x in by[d])[:10]} 〜 {max(x['retrieved_at'] for x in by[d])[:10]}
- **利用条件**: {lic}
- **ファイル**: 取得物そのまま。`*.pdf.txt` は引用照合用に PyMuPDF で抽出したテキスト(`=== page N ===` 区切り、派生物)
- **更新**: {TODAY}

## ファイル一覧({len(rows)}件)

| ファイル(ホスト/名前) | サイズ | 取得日時(JST) | 出典URL | 利用条件メモ |
|---|---|---|---|---|
""" + "\n".join(rows) + "\n"
        (dst / "README.md").write_text(readme, encoding="utf-8")

    # 2. manifest with nas_path
    HRAW.mkdir(parents=True, exist_ok=True)
    (HRAW / "manifest.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in man), encoding="utf-8")

    # 3. parquet
    import pandas as pd
    tmp = ROOT / "work" / "parquet"
    tmp.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ROOT / "hazard_support.sqlite")
    tables = [t for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    counts = {}
    PQ.mkdir(parents=True, exist_ok=True)
    for t in tables:
        df = pd.read_sql_query(f"SELECT * FROM {t}", con)
        for c in df.columns:
            if df[c].dtype == object:
                df[c] = df[c].map(lambda v: None if v is None else str(v))
        df.to_parquet(tmp / f"{t}.parquet", index=False)
        shutil.copyfile(tmp / f"{t}.parquet", PQ / f"{t}.parquet")
        counts[t] = len(df)
    con.close()

    # 4. sqlite copy (atomic rename on the share)
    part = NAS / "db" / "hazard_support.sqlite.part"
    shutil.copyfile(ROOT / "hazard_support.sqlite", part)
    part.replace(NAS / "db" / "hazard_support.sqlite")

    # top README of hazard_raw
    sizes = {f: sum(p.stat().st_size for p in (HRAW / f).rglob("*") if p.is_file()) for f, *_ in FOLDERS.values()}
    top = f"""# hazard_raw — 南海トラフ電力ハザード解析の補助データ(生データ)

南海トラフ巨大地震による停電・復旧の解析(All-Japan-Grid `feature/nankai-hazard` ブランチ `hazard/nankai/`)が使う
補助データの取得物そのもの。すべての数値は出典URL・取得日時・原文引用(またはセル位置)付きで
`../db/hazard_support.sqlite`(Parquet: `../db/parquet/hazard_support/`)に正規化してある。

- **取得・構築**: pws-160core `~/agj-hazard-data/`(scripts/fetch.py → scripts/build_db.py → scripts/publish_nas.py)
- **正本の作業場所**: pws-160core のローカルディスク(SQLite は CIFS 上で直接書かない)。NAS は複写先
- **manifest.jsonl**: 取得物1件=1行(url, sha256, retrieved_at, license, local_path=サーバー, nas_path=このNAS)
- **欠損**: 見つからなかった値は DB の `missing` テーブルに探索先つきで記録
- **利用条件の注意**: 送配電会社の設備別の値(D1)は『転載禁止』資料由来。研究室内部の検証用に限り再配布しない
- **更新**: {TODAY}

## フォルダ

| フォルダ | 内容 | 正規化テーブル | サイズ |
|---|---|---|---|
""" + "\n".join(f"| `{f}/` | {desc} | {tb} | {human(sizes[f])} |" for f, desc, tb, _ in FOLDERS.values()) + f"""

## テーブル行数(hazard_support.sqlite, {TODAY})

| テーブル | 行数 |
|---|---|
""" + "\n".join(f"| {t} | {n:,} |" for t, n in counts.items()) + "\n"
    (HRAW / "README.md").write_text(top, encoding="utf-8")

    # 5. top-level README insertions
    rp = NAS / "README.md"
    raw_bytes = rp.read_bytes()
    text = raw_bytes.decode("utf-8")  # bytes round-trip keeps existing line endings untouched
    (ROOT / "work").mkdir(exist_ok=True)
    backup = ROOT / "work" / f"nas03_README.md.bak_{dt.datetime.now(JST).strftime('%Y%m%dT%H%M%S')}"
    backup.write_bytes(raw_bytes)
    tree_add = """├── hazard_raw/          南海トラフ電力ハザード解析の補助データ 生データ（出典・取得日つき）
│   ├── D1_tepco_transformers/ … D7_restoration_records/   7データセット（各READMEあり）
│   └── manifest.jsonl   取得物1件=1行（URL・sha256・取得日時・利用条件）
│
├── db/                  （本行は hazard_support 分のみ記載）
│   ├── hazard_support.sqlite            補助DB（pws-160core で構築し複写）
│   └── parquet/hazard_support/{table}.parquet   同DBのテーブル別Parquet
│
"""
    rows_add = ("| hazard_raw | ✅ 取得済み（2026-09-14） | 随時 | ~/agj-hazard-data/scripts/fetch.py（pws-160core） |\n"
                "| db/parquet/hazard_support | ✅ 作成済み（2026-09-14） | 随時 | ~/agj-hazard-data/scripts/build_db.py → publish_nas.py（pws-160core） |\n")
    changed = False
    if "├── hazard_raw/" not in text:
        anchor = "└── walk_japan/"
        assert text.count(anchor) == 1
        text = text.replace(anchor, tree_add + anchor)
        changed = True
    if "| hazard_raw |" not in text:
        anchor = "| JWE |"
        i = text.index(anchor)
        j = text.index("\n", i) + 1
        text = text[:j] + rows_add + text[j:]
        changed = True
    if changed:
        rp.write_bytes(text.encode("utf-8"))

    listing = subprocess.run(["bash", "-c", f"du -sh {HRAW}/* {PQ} {NAS}/db/hazard_support.sqlite 2>/dev/null"],
                             capture_output=True, text=True).stdout
    print(json.dumps(counts, ensure_ascii=False))
    print("README changed:", changed, "backup:", backup)
    print(listing)


if __name__ == "__main__":
    main()
