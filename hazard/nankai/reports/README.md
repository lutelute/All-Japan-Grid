# 南海トラフ レポートの索引

まず読むのは判断レポート [nankai_power_hazard_v0_2026-09-13.md](nankai_power_hazard_v0_2026-09-13.md)。
その後の作業(動的カスケード・復旧の人員・鹿島の件)は `nankai_hazard_2026-09-13/` の下の README にある。

## 読むもの

| 知りたいこと | ファイル | 日付 |
|---|---|---|
| 全体: 方法・較正・結果・負の結果 | [nankai_power_hazard_v0_2026-09-13.md](nankai_power_hazard_v0_2026-09-13.md) | 09-13 |
| 方法の仕様: 入力・式・再現手順 | [TECHNICAL_NOTE.md](nankai_hazard_2026-09-13/TECHNICAL_NOTE.md)・[PDF](nankai_hazard_2026-09-13/TECHNICAL_NOTE.pdf) | 09-13 |
| 揺れの到達から停電までの動的カスケード | [dynamics/README.md](nankai_hazard_2026-09-13/dynamics/README.md)・集計 [dynamic_summary.md](nankai_hazard_2026-09-13/dynamics/dynamic_summary.md) | 09-16 |
| 東の全域崩壊の引き金(鹿島)は仮定で決まっていた | [kashima_tsunami_artifact_2026-09-18.md](nankai_hazard_2026-09-13/dynamics/kashima_tsunami_artifact_2026-09-18.md) | 09-18 |
| 併架線の回線数を上位電圧で数え過ぎていた | [mixed_voltage_circuits_2026-09-21.md](nankai_hazard_2026-09-13/dynamics/mixed_voltage_circuits_2026-09-21.md)(AGJ 本体の修正は `docs/reports/mixed_voltage_circuits_builder_2026-09-21.md`) | 09-21 |
| 復旧の人員を実規模で見る | [workforce/README.md](nankai_hazard_2026-09-13/workforce/README.md) | 09-14 |
| 較正スイープ(24 変種) | [calibration_sweep.md](nankai_hazard_2026-09-13/calibration_sweep.md) | 09-13 |
| 内閣府の想定との比較 | [J-SHIS 版](nankai_hazard_2026-09-13/naikakufu_compare_jshis.md)・[GMPE 版](nankai_hazard_2026-09-13/naikakufu_compare_gmpe.md) | 09-13 |
| 到達表現 3 段階と復旧オペレーション試作 | [VISUAL_CANDIDATES.md](nankai_hazard_2026-09-13/VISUAL_CANDIDATES.md) | 09-13 |

## 動画

| 中身 | ファイル |
|---|---|
| 夜の灯りが消えて戻る(シネマティック) | [cinematic.mp4](nankai_hazard_2026-09-13/cinematic.mp4) |
| 地震と津波の到達 3 段階 | [arrival_L1.mp4](nankai_hazard_2026-09-13/arrival_L1.mp4)・[L2](nankai_hazard_2026-09-13/arrival_L2.mp4)・[L3](nankai_hazard_2026-09-13/arrival_L3.mp4) |
| 動的カスケード(夜景) | [西](nankai_hazard_2026-09-13/dynamics/cascade_west_night.mp4)・[東](nankai_hazard_2026-09-13/dynamics/cascade_east_night.mp4)・[東が持ちこたえる例](nankai_hazard_2026-09-13/dynamics/cascade_east_survive_night.mp4)・[東が津波後に崩れる例](nankai_hazard_2026-09-13/dynamics/cascade_east_collapse_night.mp4)・[東が直後に崩れる例](nankai_hazard_2026-09-13/dynamics/cascade_east_collapse_early_night.mp4) |
| シナリオ卓の書き出し | [既定](nankai_hazard_2026-09-13/tool/nankai_scenario_night_default.mp4)・[直後に崩れる型](nankai_hazard_2026-09-13/tool/nankai_scenario_night_east_collapse_early.mp4)・[90 分後に崩れる型](nankai_hazard_2026-09-13/tool/nankai_scenario_night_east_collapse_tsunami.mp4)・[復旧 90 日](nankai_hazard_2026-09-13/tool/nankai_scenario_restore_default.mp4) |
| 復旧オペレーション試作・復旧の人員 | [restoration_ops.mp4](nankai_hazard_2026-09-13/restoration_ops.mp4)・[restoration_workforce.mp4](nankai_hazard_2026-09-13/workforce/restoration_workforce.mp4) |
| 解析の流れ(47 秒) | [nankai_hazard_walkthrough.mp4](nankai_hazard_2026-09-13/nankai_hazard_walkthrough.mp4) |

## ブラウザで開く HTML

GitHub では中身が表示されないので、ダウンロードして開く。公開版(Claude Artifact)は `../README.md` の「すぐ開く」にある。

| 中身 | ファイル |
|---|---|
| 停電シナリオ卓(前提を切り替えて 3 時間と 90 日を比べる) | [nankai_scenario_tool.html](nankai_hazard_2026-09-13/tool/nankai_scenario_tool.html) |
| 復旧の待ち行列卓 | [nankai_restoration_queue.html](nankai_hazard_2026-09-13/tool/nankai_restoration_queue.html) |
| 自治体 × 時刻の停電確率地図 | [hazard_map_artifact.html](nankai_hazard_2026-09-13/hazard_map_artifact.html) |
| 1 手ずつビューア(1 サンプル 556 手) | [steps_viewer.html](nankai_hazard_2026-09-13/steps_viewer.html) |
| 黒板ノート・数式スライド | [blackboard_notes.html](nankai_hazard_2026-09-13/blackboard_notes.html)・[equations_play.html](nankai_hazard_2026-09-13/equations_play.html) |

## 図と表

`nankai_hazard_2026-09-13/` の直下にある。ファイル名の `_west` / `_east` は西(60 Hz)・東(50 Hz)、`_jshis` / `_gmpe` は揺れの入力。

- 図: 震度 `hazard_*.png`、停電確率 `pout_t{0,1,7,30}_*.png`、期待停電日数 `expected_days_*.png`、ポテンシャル法 `potential_*.png`、復旧曲線 `curve_*.png`、内閣府比較 `naikakufu_compare_*.png`、原因分解 `cause_decomposition_jshis.png`、資源勘定 `resource_ledger.png`
- 表: 自治体別 `municipalities_*.csv`、復旧の時間推移 `timeline_summary_*.csv`、集計 `summary_*.json`、較正 `calibration_sweep.csv`、資源勘定 `resource_ledger.*`
