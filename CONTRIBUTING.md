# Contributing — データギャップと貢献経路 / Data gaps & how to help

All-Japan-Grid は「OSM から作った地図」を、日本の電力業界が継続的に使える
**公開・規格準拠・機械更新可能な系統リファレンス**へ育てるプロジェクトです。
その本丸は技術ではなく **権威データへのアクセス**（[docs/VISION.md](docs/VISION.md) Pillar 3、
連携設計は [docs/ENGAGEMENT.md](docs/ENGAGEMENT.md)）。本書は「**何が欠けていて、誰がどう
助けられるか**」を明示し、貢献が**再取得後も失われない**仕組みを説明します。

> This project grows an OpenStreetMap-derived map into an **open, standards-based,
> machine-updatable** reference model of Japan's grid. The hard part is **access to
> authoritative data**, not code. This document states the data gaps and the
> contribution paths that survive an OSM re-fetch.

---

## ⚠ 大原則 — 機密ファイアウォール / Confidentiality firewall【最重要】

**NDA・機密・事業者限定のデータを、この公開リポジトリ／Issue／PR に絶対に投稿しないでください。**
公開してよいのは「**公開データ由来の値**」または「**検証済みの真偽 + confidence タグ**」のみです
（[docs/ENGAGEMENT.md](docs/ENGAGEMENT.md) §4）。事業者・OCCTO との連携で得た機密実データは
公開リリースに入れず、検証結果（"この区間は実測と整合する/しない"）だけを `confidence` として
共有します。**一度の漏洩で信頼は失われます。** 迷ったら投稿前に Issue で相談してください。

> **Never submit NDA / confidential / utility-restricted data to this public repo, issues, or PRs.**
> Only publish values **derived from public data**, or a **validated true/false + confidence tag**.
> Confidential measurements obtained under agreement stay out of the public release; only the
> verdict ("this segment matches/doesn't match measurements") is shared as a `confidence` tag.

---

## 1. 何が欠けているか / What we need help with

骨格（全国トポロジ・接続性・CIM/CGMES 交換形式・機械更新の DB 土台）は揃っています。
資産化の核心課題は **権威ある電気的実態** の置換・検証です（[docs/VISION.md](docs/VISION.md) §2）。

| ギャップ | 現状の値 | あるべき権威ソース | 貢献トラック |
|---|---|---|---|
| **R / X / B（線路インピーダンス）** | 電圧クラス別の文献標準値・kV² 近似 | 事業者の設備諸元、文献値（Glover/Sarma 等）+ 不確かさ | B（実値）/ C（推定改善） |
| **変圧器諸元**（容量・タップ・%Z・結線） | 標準値からの合成 | 事業者設備データ、銘板値 | B / C |
| **母線接続の実態**（端点マッチング） | 地理的近接からの推定（誤接続あり） | 実トポロジ、衛星画像照合 | A（OSM）/ B |
| **実需要**（母線別 P/Q・プロファイル） | エリア需要を按分した合成値 | OCCTO エリア需要実績、各社公開値 | B（公開データ取込）|
| **発電機諸元**（出力範囲・コスト・ランプ） | 標準値・燃料種別ヒューリスティック | 国土数値情報 P03、供給計画、JEPX | B（公開データ取込）|
| **事業者・所有者帰属** | OSM `operator` タグ（無保証） | 各社供給区域、設備形成計画 | A / B |
| **第三者検証** | 衛星画像での部分突合せのみ | OCCTO/事業者公開値との突合せ | B / 連携 |

★最優先は **Tier 0 = 公開データの取り込み**（許可不要）。**国土数値情報 P03（発電所）は取り込み済み
＝発電所の 16.2% を権威データで裏付け**（`source=p03_db`、`ajgrid coverage` で確認）。残る公開データ
（OCCTO 公開図表・JEPX エリアプライス・系統情報サービスの公開分）が次。詳細は
[docs/ENGAGEMENT.md](docs/ENGAGEMENT.md) §2 Tier 0。

---

## 2. 貢献の3トラック / Three ways to contribute

### トラック A — 地図そのものを直す（OSM 上流）/ Fix the map upstream

最も誰でもできる貢献。送電線・変電所・発電所の**位置や接続が間違っている**なら、
[OpenStreetMap](https://www.openstreetmap.org/) 本体を直してください。次回の `fetch → ingest`
で自動的に反映されます（本プロジェクトは OSM の派生物）。

- 対象: ジオメトリ、`power=*`、`voltage`、`name`、ルートの連結性。
- 利点: 全 OSM 利用者が裨益。来歴は OSM が保持。
- ライセンス: ODbL（[OSM の編集規約](https://www.openstreetmap.org/)に従う）。

### トラック B — 実値・補正を DB に投稿する（ドメイン専門家・研究者）/ Submit real values & corrections

**OSM に載らない電気的属性**（R/X/B、変圧器諸元、検証済み需要・発電値、正しい事業者帰属）は、
DB の **C 層（`enrichments`）** に `source` と `confidence` 付きで投稿します。これらは
`source=manual` / `external` 等の**専用ラベル**で記録され、**OSM 再取得で上書きされません**
（[docs/DB_ARCHITECTURE.md](docs/DB_ARCHITECTURE.md)）。これが「機械更新しても人手の補正が
残る」設計の核心です。

**単一フィールドの補正**（名前で対象を特定）:
```bash
ajgrid db curate --layer substations --region okinawa \
    --where-name "那覇変電所" --set operator="沖縄電力" --source manual
#  ↑ = python scripts/db/curate.py ...
ajgrid db export        # GeoJSON など派生物を再生成
```

**まとめて投稿**（PR で `fixes.json` を提出。JSON リスト）:
```json
[
  {"layer": "lines", "region": "kansai", "feature_key": "g:1a2b3c…",
   "field": "circuits", "value": 2, "source": "external", "confidence": 0.9},
  {"layer": "plants", "region": "okinawa", "osm_id": 123456,
   "field": "fuel_type", "value": "gas", "source": "manual"}
]
```
```bash
ajgrid db curate --import fixes.json
```

- **書き込めるフィールド**: 地物の属性（OSM タグ系）— 線路なら `voltage` / `circuits` /
  `cables` / `operator` / `capacity`、発電所なら `fuel_type` / `operator` / `output` など。
  C 層は汎用 key-value オーバーレイなので任意フィールドを足せますが、**`export` で GeoJSON
  プロパティとして出るもの**を対象にしてください。
- **対象の特定**: `--where-name`（現在の有効名）/ `--where-osm-id` / `--where-feature-key`
  （恒久キー `n/w/r{osm_id}` または暫定キー `g:{geometry-sha1}`）。
- **source の選び方**: 自分の手作業 = `manual`、外部の公開/権威データ = `external`
  （または `p03` / `occto` など由来名）。**`manual`/`external` は最優先**（`SOURCE_PRIORITY`）で
  合成値・OSM 値に勝ち、再取得でも消えません。**確度は必ず `confidence` で表明**してください。
- **機密データは投稿しない**（§冒頭の firewall）。公開できる値・検証済みタグのみ。

> **R/X/B・変圧器 %Z など「電気的実体」は Pillar 3 のフロンティア.** 現状これらは線路の
> `voltage`（電圧クラス）から**導出**しており、個別線路の生の R/X を `--set` しても潮流ソルバには
> まだ直結しません（モデルが線路単位の override を読む拡張が必要）。権威ある実測値をお持ちの場合は、
> **Issue で相談**いただくか、区間の「検証済み真偽 + `confidence`」として投稿してください。
> 受け皿（規格準拠の器）を用意し、override 経路を一緒に設計します（[docs/VISION.md](docs/VISION.md) §2）。

### トラック C — コード・ツール / Code & tooling

パイプライン（`src/`）、CLI（`ajgrid`）、エンリッチャ、CIM/CGMES エクスポート、テスト、ドキュメント。

```bash
git clone https://github.com/lutelute/All-Japan-Grid && cd All-Japan-Grid
python -m pytest -q          # 889 passed が緑であること
ajgrid solve okinawa --topology snapped --reconnect   # 動作確認
```

- 1 論理変更 = 1 コミット、テスト緑を維持。新機能はテスト同伴。
- **既存機能を安易に消さない**: 試行錯誤の設計判断が残っています。評価（git 履歴・参照・出力）
  してから変更・隔離してください。
- PR には何を・なぜ変えたかと、関連 Issue を明記。

---

## 3. なぜ貢献が残るか / Why your contribution persists

機械的更新ループ **`fetch → ingest(raw) → enrich(DB) → export`** は、raw OSM（R 層）と
キュレーション（C 層 = `enrichments`）を分離しています。OSM を再取得しても、

1. R 層（`raw_*`）だけが丸ごと差し替わり、
2. C 層の `manual`/`external`/権威ソースは**温存**され（`LEGACY_SOURCES` 外のため削除対象にならない）、
3. feature キーで照合して**自動的に再適用**されます。

すべての属性に **source / confidence / 取得日** が付き、誰が・いつ・どの権威で補正したかを
追跡できます。追跡正本は `data/db/enrichments.jsonl`（来歴付きバックアップ）。

---

## 4. ライセンス / Licensing

- **ネットワークデータ**: [ODbL](https://opendatacommons.org/licenses/odbl/)（OpenStreetMap 由来）
- **コード**: MIT
- **権威データの属性**: 出典のライセンスを**属性単位**で保持（`enrichments.source` が担保）。
  混在を避け、投稿時に由来とライセンスを明記してください。ライセンス不明・再配布不可のデータは
  投稿しないでください。

---

## 5. 相談・連携 / Discuss & collaborate

- バグ・データ誤り・小さな修正: **GitHub Issue / PR**。
- 共同研究・データ利用契約・規格化（事業者・OCCTO・大学・CRIEPI）: [docs/ENGAGEMENT.md](docs/ENGAGEMENT.md)
  の連携ラダー（Tier 2 = 福井大学経由の共同研究が本命の入口）を参照。
- 全体像: [docs/VISION.md](docs/VISION.md)（5本柱・段階 M0–M4）。

**地図 ≠ 運用モデル**、**合成値 vs 検証値** の峻別を続けることが、本プロジェクトの公共的価値です。
誇張のない、検証可能な日本系統リファレンスを一緒に育てましょう。
