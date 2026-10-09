# 南海トラフ地震 電力ハザードマップ (nankai)

All-Japan-Grid の正典モデル(docs/data/built + 正典系譜の潮流ケース)を使い、
南海トラフ巨大地震が起きたときの**停電(供給支障)の空間分布と復旧の時間推移**を推定する。
2 つの独立した方向で推定し、互いに突き合わせる。

| 方向 | 何をするか | 出力 |
|---|---|---|
| **A. 解析ベース** | 地震動・津波 → 脆弱性曲線で設備(変電所・線路/鉄塔・発電機)の損傷をサンプル → 連結成分・需給・DC潮流・過負荷連鎖で直後の供給支障 → 修理時間分布+作業班制約+優先順で復旧を時系列評価。モンテカルロで確率化 | 母線/自治体ごとの停電確率 P(t)・期待停電日数・復旧曲線・GIF |
| **B. ポテンシャル法** | 潮流を解かない。中央値ハザード下の設備故障確率を枝重みにした「電源までの最良経路の生存率」× 「半径 R 内の生存供給ポテンシャル/負荷」で停電しやすさを指標化 | 母線ごとの指標(0〜1)。A との相関で妥当性を見る |

「倒壊」は鉄塔倒壊(線路単位・1基あたり脆弱性×基数)と変電所の extensive/complete 損傷として扱う。
発電所は損傷(HAZUS EPP)に加え、揺れによる自動停止(火力 5弱以上・原子力 scram)と津波浸水(沿岸火力の長期停止)を分ける。

南海トラフは 1 つの地震のプロジェクトとして、コード・設定・レポート・スライド・成果物をすべてこのディレクトリに置く
(2026-10-08 に `docs/reports/`・`docs/slides/`・`verification/` から移した)。All-Japan-Grid 本体からは正典モデルを読むだけ。
置き場所は末尾の「構成」。

## すぐ開く

| 開きたいもの | 場所 |
|---|---|
| 判断レポート(まずこれ) | [reports/nankai_power_hazard_v0_2026-09-13.md](reports/nankai_power_hazard_v0_2026-09-13.md) |
| レポート・動画・HTML の索引 | [reports/README.md](reports/README.md) |
| 最新のデッキ | 候補デッキ v10・29 枚 [nankai_visual_candidates_v10_2026-09-21.pptx](slides/nankai_visual_candidates_v10_2026-09-21.pptx)・本編 [nankai_hazard_v0_2026-09-13.pptx](slides/nankai_hazard_v0_2026-09-13.pptx)・版の一覧 [slides/README.md](slides/README.md) |
| 09-13 時点の検証一式 | [verification/README.md](verification/README.md) |
| 触って試す(Claude Artifact。共有していなければ本人だけが開ける) | [停電シナリオ卓](https://claude.ai/artifact/MGr5RRXNQJ4QSYxQbnp152)・[復旧の待ち行列卓](https://claude.ai/artifact/Ri8H6EdNjayzF8PZcihCRt)・[電力ハザードマップ](https://claude.ai/artifact/GBxpWHnmZZvfLZEBmins1K)・[1 手ずつ](https://claude.ai/artifact/Y5A9GbprorEH6wTjoYNBd9)・[黒板ノート](https://claude.ai/artifact/FB1zKFniBXf2v1L2EzMogw)・[数式の動き](https://claude.ai/artifact/7jF4ascyjnzJrepa3vh9op) |
| 計算結果(git 管理外) | Mac のチェックアウトの `hazard/nankai/output/`(正典は `run_v10`、全体で約 714 MB)。補助 DB は pws-160core の `~/agj-hazard-data/` と nas03 の `hazard_raw/`・`db/` |

## 実行

```bash
# 1) 正典ネットから解析ケースを切り出す(初回のみ・west/east で約2分)
PYTHONPATH=. python3 hazard/nankai/scripts/extract_grid_case.py --islands west east
# 2) 一括実行(モンテカルロ N・GIF・自治体集約)
PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/run_pipeline.py --islands west east --samples 200
# 3) テスト
cd hazard/nankai && python3 -m pytest tests -q
```

出力は `output/run_<日時>/<island>/`: `bus_results.parquet`(母線×時刻の供給率・停電確率), `timeline_summary.csv`,
`potential.parquet`, `hazard.png`, `pout_t*.png`, `expected_days.png`, `potential.png`, `curve.png`,
`restoration.gif`, `municipalities.geojson/csv`(行政界があれば), 親に `summary.json`。

## データ

| 層 | 既定 | 実データ(あれば優先) |
|---|---|---|
| 地震動 | `config/scenario_nankai.yaml` の近似震源域 + 司・翠川(1999) + 藤本・翠川(2005) (`hazard_field.GMPEField`) | J-SHIS / 内閣府 250m メッシュ計測震度 (`data/derived/jshis_nankai_intensity.parquet`) |
| 地盤増幅 | 一様 1.6 (PGV) | J-SHIS 増幅率メッシュ (`data/derived/jshis_amp_vs400.parquet`) |
| 津波 | なし | 国土数値情報 A40 津波浸水想定 (`data/derived/tsunami_inundation_A40.gpkg`) |
| 行政界 | なし | 国土数値情報 N03 (`data/derived/municipalities.gpkg`) |
| 系統 | `data/derived/grid_<island>_*.parquet`(正典から切り出し) | — |
| 脆弱性・復旧 | `config/fragility_default.yaml`, `config/restoration_default.yaml` | `config/fragility.yaml`, `config/restoration.yaml`(文献整理版・schema キーで有効化) |

外部データの出典・利用条件は `docs/DATA_MANIFEST.md`, `docs/HAZARD_DATA_SOURCES.md`, `docs/FRAGILITY_SOURCES.md`。

## 前提と限界(正直に)

- **地震動の既定は合成場**である。司・翠川式は Mw8.3 程度までの回帰なので `gmpe_effective_mw: 8.5` で飽和させ、
  内閣府の震度分布に目視で寄せた(静岡・高知・徳島 6強〜7、名古屋 6弱〜6強、大阪 6弱〜6強、北陸 4〜5弱)。実データが入れば自動で置き換わる。
- **脆弱性は HAZUS-MH 系 + 日本補正係数(仮定)**。日本の変電機器の耐震性は米国標準より高いとして中央値を 1.8 倍している。
  この係数と「moderate 損傷で停電する確率 0.3」が結果の絶対値を大きく左右する。内閣府の停電軒数(直後 約2,710万軒)への較正は `reports/` に記録。
- **系統モデルの限界を引き継ぐ**: 正典モデルは島ごとに数百の成分に分かれ(フラグメント)、フラグメントは仮想電源(slack)で供給されている。
  本解析ではフラグメントの仮想電源を「基底の残差容量」とし、slack 母線が損傷すれば失われる扱いにした。線路容量は理論値(介入#45較正込み)、
  基底で既に過負荷の枝は基底潮流×1.3 を緊急定格とみなす。配電系統(6.6kV 以下)の被害は含まない=**変電所が生きていれば供給されるとみなす**ので、実際の停電はこれより多い。
- 液状化・斜面崩壊・地殻変動(沈降)は未考慮。津波は都道府県の最大クラス想定(A40)を使うので、県によって想定地震が南海トラフでない場合がある(manifest 参照)。
- 復旧は作業班数と修理時間分布の仮定に依存する。東日本大震災(東北電力 3日で80%・8日で94%)と内閣府想定を較正目標にする。

## 構成

```
hazard/nankai/
  README.md     この文書(入口)
  config/       シナリオ・脆弱性・復旧・動的カスケード・人員の YAML(既定版と文献版)
  src/nankai/   ハザード場・損傷・カスケード(静的/動的)・復旧・モンテカルロ・ポテンシャル法・地図
  scripts/      実行(run_pipeline / run_dynamic)・後処理(postrun.sh)・図と動画・ヒンドキャスト(北海道 2018・福島 2022)
  tests/        pytest
  tool/         停電シナリオ卓(1 枚の HTML。Artifact 版の元)
  tool_queue/   復旧の待ち行列卓
  data/         derived/(grid_*.parquet はコミット・大物は管理外)・external/(管理外)・取得スクリプト(ksj_pipeline/・support_pipeline/)
  docs/         外部データの出典と利用条件(DATA_MANIFEST・HAZARD_DATA_SOURCES・FRAGILITY_SOURCES)・耐水性の証拠
  reports/      判断レポート nankai_power_hazard_v0_2026-09-13.md と、その図・表・動画・個別レポート
                nankai_hazard_2026-09-13/(dynamics/・workforce/・tool/ を含む)
  slides/       デッキ(版ごとに別名。版の一覧は slides/README.md)
  verification/ 09-13 時点の検証一式(人が読む成果物を 1 か所に集めた写し。REPORT_v0・技術ノート・viewers/)
  output/       run_*/(計算結果・git 管理外)
```

All-Japan-Grid 側に残しているのは、トップ README の動画 `docs/assets/gif/nankai_cinematic.gif`(作り直しは
`scripts/make_readme_gifs.py nankai`)と、改善台帳 `docs/reports/IMPROVEMENT_LOG.md` の記録だけ。
`docs/` の外に出したので、レポートとスライドは GitHub Pages には載らない。
