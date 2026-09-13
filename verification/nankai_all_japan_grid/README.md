# 南海トラフ × All-Japan-Grid 検証（v0, 2026-09-13）

南海トラフ巨大地震に対する電力系統の停電・復旧を、All-Japan-Grid の正典系統モデルの上で計算した検証一式。
コードは `hazard/nankai/`（README にパイプライン・データ・限界）。ここは**人が読む成果物**を1か所に集めた場所。
ブランチ `feature/nankai-hazard`。

## 何を検証したか（要点）

- **解析ベース（A）**: J-SHIS 南海トラフ最大クラス Mw9.1 の 250m 震度 + 国土数値情報 A40 津波浸水 → 変電所・鉄塔・発電所の損傷（HAZUS 系脆弱性 + 日本補正、内閣府 2025 方式の火力停止率） → 連結成分・需給・DC潮流・過負荷連鎖 → 修理時間 + 作業班 + 優先順の復旧 → モンテカルロ N=200。停電を「物理停電（損傷・系統崩壊・上流孤立）」と「供給力不足の遮断（計画停電相当）」に分けて出す。
- **ポテンシャル法（B）**: 電源までの最良経路の生存率 × 供給余力の指標。A の 2 日後停電確率と需要加重相関 0.56。
- **内閣府想定との比較（五地域・物理停電）**: 直後 1,003 万 / 1 日 701 万 / 4 日 403 万 / 7 日 362 万軒（内閣府 2025 基本 2,060 / 1,350 / 36 / 32 万軒）。直後〜1 日は同じ桁、4 日以降は 1 桁多い＝津波浸水域の変電所（復旧 60 日）と上流孤立。内閣府は津波全壊需要家を復旧対象から除き配電を別勘定にしている（負の結果として記録）。
- **1 手ずつ可視化で見つけた不具合**: DC 潮流の単位（×100 の重ね掛け）→ 修正済み（`test_dc_flow_units_radial`）。
- **資源勘定 v0**: 復旧ジョブ 357 件・延べ 12.2 万人・日、稼働人数は班数上限に張り付き（人手律速）、主変圧器 122 台 vs 予備 28 台、電源車は保有＋応援の 1 桁上（原単位は仮定）。

## 成果物

| ファイル | 内容 |
|---|---|
| `REPORT_v0.md` | 判断レポート（方法・較正 24 変種・結果・負の結果・限界・記録） |
| `TECHNICAL_NOTE.pdf` / `.md` | 技術ノート（入力データ、地震動・津波の場、損傷、系統評価、系統崩壊と swing 方程式、復旧と待ち行列、モンテカルロ、ポテンシャル法、較正と検証、内閣府の採用手法との対応、限界、再現手順） |
| `slides_4_summary.pptx` | **プレゼン差し込み用 4 枚**（構図 → 4 つの手 → シネマティック GIF → 数字と一言）。3 枚目は `viewers/cinematic.gif`（PowerPoint のスライドショーで動く）、動画版 `viewers/cinematic.mp4`（1920×1080・34 秒）。旧版のインパクト GIF は `viewers/impact_all_japan.gif` |
| `viewers/cinematic.mp4` / `.gif` | **「夜の灯りが消えて戻る」シネマティック**：ふだんの夜 → 衝撃波 → 灯りが消える → 津波がトラフ軸から海を渡り A40 浸水想定域を水没 → 引き波 → 90 日で灯りが戻る（停電中の需要家カウンタ・内閣府 2025 併記）。灯り = √需要 × 受電可能確率。津波の到達順は海上最短経路（Dijkstra）の演出で伝播計算ではない。生成: `hazard/nankai/scripts/make_cinematic.py` |
| `slides_28.pptx` | 解説デッキ 28 枚（系統モデルの意義、需給・周波数・リレー、結果、負の結果） |
| `viewers/equations_play.html` | 数式スライド 12 枚（教科書の式 → 見えない → 動かす → 具体例 → つまり → なぜモデル化できるか → 文献と歴史の横軸フロー → 良し悪し／総括／参考文献） |
| `viewers/blackboard_notes.html` | 黒板ノート 15 板書 |
| `viewers/steps_viewer.html` | 1 手ずつビューア（1 サンプル 556 手、実線形で描画） |
| `viewers/hazard_map_artifact.html` | 自治体×時刻の停電確率地図（タイル不要・単独 HTML） |
| `viewers/nankai_hazard_walkthrough.mp4` | 解析の流れ動画 47 秒 |
| `figures/` | 震度、停電確率（直後/1/7/30 日）、期待停電日数、ポテンシャル、復旧曲線、内閣府比較、原因分解、資源勘定、GIF |
| `data/` | 復旧曲線 CSV、自治体別 CSV、内閣府比較、原因分解、資源勘定、較正スイープ、summary JSON |

公開版（Claude Artifact・非公開リンク）: 地図 `7b00ead4-…`、1 手ずつ `fb9fe868-…`、黒板 `72c5fce9-…`、数式スライド `367cbc76-…`（`https://claude.ai/code/artifact/<id>`）。

## 再現

```bash
PYTHONPATH=. python3 hazard/nankai/scripts/extract_grid_case.py --islands west east      # 正典→parquet（初回）
PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/run_pipeline.py --islands west east --samples 200 --out hazard/nankai/output/run_vN
bash hazard/nankai/scripts/postrun.sh hazard/nankai/output/run_vN docs/reports/nankai_hazard_2026-09-13 hazard/nankai/output/run_v1_gmpe
PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/resource_ledger.py --samples 20 --out hazard/nankai/output/run_vN
cd hazard/nankai && python3 -m pytest tests -q   # 8 tests
```

外部データ（J-SHIS 約 60 MB、A40 約 1 GB、N03）は git 管理外。取得手順は `hazard/nankai/docs/HAZARD_DATA_SOURCES.md`, `DATA_MANIFEST.md`。

## 検証の状態と次の一手

- 直後の桁は系統崩壊しきい値（25%）で較正しており、独立の裏付けではない。1 日後の一致と 4 日以降の乖離は合わせに行っていない。
- 未実施: 較正に使っていない地震（熊本 2016・北海道 2018・東北 2011）の再現、配電層、津波全壊需要家の除外集計、177 パターンの合成、周波数の動的化、待ち行列の深掘り（アクセス制約・資材リードタイム）。
- Artifact はブラウザで描画・操作を検証済み（別オリジン iframe のためローカル配信で JS 状態を確認する手順）。
