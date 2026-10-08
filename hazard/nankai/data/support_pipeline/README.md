# 南海トラフ ハザード補助データの取得・DB 化スクリプト

pws-160core の `~/agj-hazard-data/scripts/` と同じもの(2026-09-14 時点の写し)。成果物は git に入れない。

| 置き場所 | 中身 |
|---|---|
| pws-160core `~/agj-hazard-data/` | raw/・hazard_support.sqlite・manifest.jsonl・records/ |
| nas03 `hazard_raw/D1〜D7/` | 生データ(フォルダごとに出典・取得日・利用条件の README) |
| nas03 `db/hazard_support.sqlite`・`db/parquet/hazard_support/` | DB 本体とテーブル別 Parquet |
| 手元 `hazard/nankai/data/external/hazard_support/` | DB の写し(git 管理外) |

```
~/agj-hazard-data/.venv/bin/python ~/agj-hazard-data/scripts/fetch.py URL --dataset D1 --license "..."
~/agj-hazard-data/.venv/bin/python ~/agj-hazard-data/scripts/build_db.py
~/agj-hazard-data/.venv/bin/python ~/agj-hazard-data/scripts/publish_nas.py
```

- `records_d1.py`・`records_misc.py` は東京電力パワーグリッドと中部電力パワーグリッドの空容量一覧(転載禁止)の値と引用を含むので、git に入れずサーバーと nas03 だけに置く。
- `d5_peek.py`・`d6_blocks.py`・`d6_links.py` は取得時の確認用の使い捨て。
